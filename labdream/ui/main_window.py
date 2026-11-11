"""Main menu window."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtGui import QAction, QActionGroup, QFont
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import fileio, session
from ..i18n import LANGUAGES, language, set_language, tr
from ..model import new_dataset
from .dialogs import DeviceSelectDialog, SetupDialog
from .security_dialogs import AuditTrailDialog, ChangePasswordDialog, UserManagementDialog
from .widgets import DevicePicture
from .wizard import DataWizard


class MainWindow(QMainWindow):
    """Impactor data analysis (APSD) module."""
    logout_requested = Signal()
    language_changed = Signal()
    home_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{fileio.APP_VERSION} – {tr('Inhaler Testing Data Analysis')}")
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
        title.setFont(QFont("Arial", 30, QFont.Bold))
        title.setStyleSheet("color:#1f4fa8")
        col.addWidget(title)
        sub = QLabel(tr("Inhaler Testing Data Analysis Software") + "\n"
                     + " · ".join(tr(x) for x in ("Cascade Impactor", "Multi-Stage Liquid Impinger",
                                                   "Marple-Miller Impactor", "Next Generation Impactor")))
        sub.setFont(QFont("Arial", 11))
        sub.setWordWrap(True)
        col.addWidget(sub)
        ver = QLabel(fileio.APP_VERSION + "   (Ph. Eur. 2.9.18 / USP <601>)")
        ver.setStyleSheet("color:#666")
        col.addWidget(ver)
        col.addSpacing(20)
        buttons = [(tr("Enter &New Data"), self.new_data, session.can("edit_data")),
                   (tr("&Open Existing Data File"), self.open_file, True),
                   (tr("&Set-up (Templates)"), self.setup, session.can("templates")),
                   (tr("&User Management"), self.users, session.can("manage_users")),
                   (tr("&Audit Trail"), self.audit, session.can("view_audit")),
                   (tr("Switch &Module"), self.go_home, True),
                   (tr("E&xit"), self.close, True)]
        for text, fn, enabled in buttons:
            b = QPushButton(text)
            b.setMinimumHeight(38)
            b.setFont(QFont("Arial", 12))
            b.clicked.connect(fn)
            b.setEnabled(enabled)
            if not enabled:
                b.setToolTip(tr("Not permitted for your role"))
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.resize(780, 600)

        u = session.user
        self.statusBar().showMessage(
            f"{tr('User')}: {u.username} ({u.full_name}) – {tr(u.role)}" if u else "")

        m = self.menuBar().addMenu(tr("&File"))
        self._act(m, tr("New…"), self.new_data, "Ctrl+N", session.can("edit_data"))
        self._act(m, tr("Open…"), self.open_file, "Ctrl+O")
        m.addSeparator()
        self._act(m, tr("Switch Module"), self.go_home)
        self._act(m, tr("Log Out"), self.logout)
        self._act(m, tr("Exit"), self.close, "Ctrl+Q")
        um = self.menuBar().addMenu(tr("&Users"))
        self._act(um, tr("Change Password…"), self.change_password)
        self._act(um, tr("User Management…"), self.users, None, session.can("manage_users"))
        self._act(um, tr("Audit Trail…"), self.audit, None, session.can("view_audit"))
        t = self.menuBar().addMenu(tr("&Tools"))
        self._act(t, tr("Set-up…"), self.setup, None, session.can("templates"))
        lm = t.addMenu(tr("Language"))
        grp = QActionGroup(self)
        for code, name in LANGUAGES.items():
            a = QAction(name, self, checkable=True)
            a.setChecked(code == language())
            a.triggered.connect(lambda _=False, c=code: self.change_language(c))
            grp.addAction(a)
            lm.addAction(a)
        h = self.menuBar().addMenu(tr("&Help"))
        self._act(h, tr("About LabDream"), self.about)
        self._logging_out = False

    def _act(self, menu, text, fn, shortcut=None, enabled=True):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(fn)
        a.setEnabled(enabled)
        menu.addAction(a)
        return a

    # ------------------------------------------------------------------
    def new_data(self):
        if not session.can("edit_data"):
            return
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
                        ds.created_by = ds.created_at = ds.modified_by = ds.modified_at = ""
                        ds.revision = 0
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(self, tr("Template"), f"{tr('Could not read template:')}\n{e}")
        session.log("FILE_NEW", dev, {})
        DataWizard(ds, None, self).exec()

    def open_file(self):
        start = self.settings.value("data_dir", "", type=str)
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open Data File"), start,
            f"{tr('Data files')} (*{fileio.NATIVE_EXT} *.cpl *.CPL);;LabDream (*{fileio.NATIVE_EXT});;"
            f"{tr('Legacy impactor data')} (*.cpl *.CPL);;* (*)")
        if not path:
            return
        try:
            ds = fileio.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Open"), f"{tr('Could not open file:')}\n{e}")
            return
        session.log("FILE_OPENED", os.path.basename(path), {"path": path, "revision": ds.revision})
        self.pic.set_device(ds.device)
        DataWizard(ds, path, self).exec()

    def setup(self):
        if session.can("templates"):
            SetupDialog(self).exec()

    def users(self):
        if session.can("manage_users"):
            UserManagementDialog(self).exec()

    def audit(self):
        if session.can("view_audit"):
            AuditTrailDialog(self).exec()

    def change_password(self):
        ChangePasswordDialog(self).exec()

    def change_language(self, code):
        if code == language():
            return
        set_language(code)
        self.settings.setValue("language", code)
        session.log("LANGUAGE_CHANGED", code, {})
        self.language_changed.emit()

    def go_home(self):
        self._logging_out = True
        self.home_requested.emit()

    def logout(self):
        self._logging_out = True
        session.log("LOGOUT", session.name(), {})
        session.user = None
        self.logout_requested.emit()

    def closeEvent(self, ev):
        ev.accept()
        if self._logging_out or getattr(self, "_rebuilding", False):
            return
        if session.user is not None:
            session.log("LOGOUT", session.name(), {"reason": "exit"})
            session.user = None
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def about(self):
        QMessageBox.about(self, tr("About LabDream"),
                          f"<b>{fileio.APP_VERSION}</b><br>{tr('Inhaler Testing Data Analysis Software')}<br><br>"
                          + tr("Aerodynamic particle size distribution by log-probit analysis "
                               "(MMAD, GSD, FPD, FPF) for CI, MSLI, MMI and NGI."))
