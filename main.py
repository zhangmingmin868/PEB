"""LabDream Version 2.0 – inhaler testing data analysis software.

Run:  python main.py
"""
import os
import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from labdream import fileio, session
from labdream.i18n import set_language
from labdream.ui.main_window import MainWindow
from labdream.ui.security_dialogs import FirstAdminDialog, LoginDialog


class App:
    def __init__(self, qapp):
        self.qapp = qapp
        self.win = None

    def login(self) -> bool:
        if not session.store.has_users():
            if FirstAdminDialog().exec() != QDialog.Accepted:
                return False
        while True:
            d = LoginDialog()
            r = d.exec()
            if r == 2:                    # language switched: reopen translated
                continue
            return r == QDialog.Accepted

    def show_main(self):
        old = self.win
        self.win = MainWindow()
        self.win.logout_requested.connect(self.on_logout)
        self.win.language_changed.connect(self.on_language)
        self.win.show()
        if old is not None:
            old._rebuilding = True
            old.close()
            old.deleteLater()

    def on_logout(self):
        self.win.hide()
        self.win.deleteLater()
        self.win = None
        if self.login():
            self.show_main()
        else:
            self.qapp.quit()

    def on_language(self):
        self.show_main()


def main():
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(fileio.APP_NAME)
    qapp.setApplicationDisplayName(fileio.APP_VERSION)
    qapp.setStyle("Fusion")
    qapp.setQuitOnLastWindowClosed(False)
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    icon = os.path.join(base, "assets", "labdream.png")
    if os.path.exists(icon):
        qapp.setWindowIcon(QIcon(icon))
    set_language(QSettings("LabDream", "LabDream").value("language", "en", type=str))
    session.init()
    app = App(qapp)
    if not app.login():
        return 0
    app.show_main()
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
