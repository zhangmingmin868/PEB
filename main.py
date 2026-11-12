"""Lemonix INHA Workstation (LabDream 3.1) – impactor data analysis (APSD) + PBE data processing.

Run:  python main.py
"""
import os
import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from labdream import fileio, session
from labdream.i18n import set_language
from labdream.ui.home import MODULE_APSD, MODULE_PBE, MODULES, HomeWindow, module_enabled
from labdream.ui.main_window import MainWindow
from labdream.ui.pbe_window import PbeMainWindow
from labdream.ui.security_dialogs import FirstAdminDialog, LoginDialog
from labdream.ui.workstation import Workstation


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

    def _swap(self, new):
        old = self.win
        self.win = new
        new.show()
        if old is not None:
            old._rebuilding = True
            old._leaving = True
            old._logging_out = True
            old.close()
            old.deleteLater()

    def show_main(self):
        """After log-in: the workstation window (navigation Start / Method / Data / Report / ...)."""
        self.module = None
        w = Workstation()
        w.logout_requested.connect(self.on_logout)
        self._swap(w)

    def open_module(self, code):         # kept for the legacy module windows
        self.module = code
        w = PbeMainWindow() if code == MODULE_PBE else MainWindow()
        w.logout_requested.connect(self.on_logout)
        w.language_changed.connect(self.on_language)
        w.home_requested.connect(self.show_main)
        self._swap(w)

    def on_logout(self):
        old = self.win
        self.win = None
        if old is not None:
            old.hide()
            old.deleteLater()
        if self.login():
            self.show_main()
        else:
            self.qapp.quit()

    def on_language(self):
        if getattr(self, "module", None):
            self.open_module(self.module)
        else:
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
