"""Main menu window."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import fileio
from ..model import new_dataset
from .dialogs import DeviceSelectDialog, SetupDialog
from .widgets import DevicePicture
from .wizard import DataWizard


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{fileio.APP_VERSION} – Inhaler Testing Data Analysis")
        self.settings = QSettings("LabDream", "LabDream")
        self.last_device = self.settings.value("last_device", "CI", type=str)

        w = QWidget()
        self.setCentralWidget(w)
        lay = QHBoxLayout(w)
        self.pic = DevicePicture(self.last_device)
        self.pic.setFixedWidth(220)
        lay.addWidget(self.pic)
        col = QVBoxLayout()
        title = QLabel("LabDream")
        f = QFont("Arial", 30, QFont.Bold)
        title.setFont(f)
        title.setStyleSheet("color:#1f4fa8")
        col.addWidget(title)
        sub = QLabel("Inhaler Testing Data Analysis Software\n"
                     "Cascade Impactor · Multi-Stage Liquid Impinger · Marple-Miller Impactor · "
                     "Next Generation Impactor")
        sub.setFont(QFont("Arial", 11))
        col.addWidget(sub)
        ver = QLabel(fileio.APP_VERSION + "   (Ph. Eur. 2.9.18 / USP <601>)")
        ver.setStyleSheet("color:#666")
        col.addWidget(ver)
        col.addSpacing(24)
        for text, fn in (("Enter &New Data", self.new_data),
                         ("&Open Existing Data File", self.open_file),
                         ("&Set-up (Templates)", self.setup),
                         ("E&xit", self.close)):
            b = QPushButton(text)
            b.setMinimumHeight(40)
            b.setFont(QFont("Arial", 12))
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.resize(760, 520)

        m = self.menuBar().addMenu("&File")
        for text, fn, sc in (("New…", self.new_data, "Ctrl+N"), ("Open…", self.open_file, "Ctrl+O"),
                             ("Exit", self.close, "Ctrl+Q")):
            a = QAction(text, self)
            a.setShortcut(sc)
            a.triggered.connect(fn)
            m.addAction(a)
        t = self.menuBar().addMenu("&Tools")
        a = QAction("Set-up…", self)
        a.triggered.connect(self.setup)
        t.addAction(a)
        h = self.menuBar().addMenu("&Help")
        a = QAction("About LabDream", self)
        a.triggered.connect(self.about)
        h.addAction(a)

    # ------------------------------------------------------------------
    def new_data(self):
        dlg = DeviceSelectDialog(self, self.last_device)
        if dlg.exec() != QDialog.Accepted:
            return
        dev = dlg.device()
        self.last_device = dev
        self.settings.setValue("last_device", dev)
        self.pic.set_device(dev)
        ds = new_dataset(dev)
        if self.settings.value(f"template/{dev}/use", False, type=bool):
            p = self.settings.value(f"template/{dev}/path", "", type=str)
            if p and os.path.exists(p):
                try:
                    t = fileio.load(p)
                    if t.device == dev:
                        ds = t
                        ds.file_name = ""
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(self, "Template", f"Could not read template:\n{e}")
        DataWizard(ds, None, self).exec()

    def open_file(self):
        start = self.settings.value("data_dir", "", type=str)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Data File", start,
            f"Data files (*{fileio.NATIVE_EXT} *.cpl *.CPL);;LabDream (*{fileio.NATIVE_EXT});;"
            "Legacy impactor data (*.cpl *.CPL);;All files (*)")
        if not path:
            return
        try:
            ds = fileio.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Open", f"Could not open file:\n{e}")
            return
        self.pic.set_device(ds.device)
        DataWizard(ds, path, self).exec()

    def setup(self):
        SetupDialog(self).exec()

    def about(self):
        QMessageBox.about(self, "About LabDream",
                          f"<b>{fileio.APP_VERSION}</b><br>Inhaler testing data analysis software.<br><br>"
                          "Aerodynamic particle size distribution by log-probit analysis "
                          "(MMAD, GSD, FPD, FPF) for CI, MSLI, MMI and NGI.")
