"""LabDream Version 1.0 – inhaler testing data analysis software.

Run:  python main.py [data-file]
"""
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from labdream import fileio
from labdream.ui.main_window import MainWindow
from labdream.ui.wizard import DataWizard


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(fileio.APP_NAME)
    app.setApplicationDisplayName(fileio.APP_VERSION)
    app.setStyle("Fusion")
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    icon = os.path.join(base, "assets", "labdream.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        ds = fileio.load(sys.argv[1])
        DataWizard(ds, sys.argv[1], win).show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
