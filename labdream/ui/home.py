"""Module selection shown after log-in: impactor data analysis (APSD) or PBE."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import fileio, session
from ..i18n import tr
from .dialogs import ok_cancel

MODULE_APSD, MODULE_PBE = "apsd", "pbe"
MODULES = {
    MODULE_APSD: ("Impactor Data Analysis (APSD)",
                  "Cascade impactor / NGI / MSLI / MMI: MMAD, GSD, FPD, FPF (Ph. Eur. 2.9.18 / USP <601>)"),
    MODULE_PBE: ("PBE Data Processing",
                 "Population bioequivalence of in-vitro tests (FDA PBE statistical procedure)"),
}


def module_enabled(code: str) -> bool:
    return QSettings("LabDream", "LabDream").value(f"modules/{code}", True, type=bool)


class ModulesDialog(QDialog):
    """Administrator: choose which modules are installed / available."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Modules"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Select the modules available on this computer:")))
        self.cb = {}
        for code, (name, _) in MODULES.items():
            c = QCheckBox(tr(name))
            c.setChecked(module_enabled(code))
            self.cb[code] = c
            lay.addWidget(c)
        lay.addWidget(ok_cancel(self, self._ok, self.reject))

    def _ok(self):
        if not any(c.isChecked() for c in self.cb.values()):
            QMessageBox.warning(self, tr("Modules"), tr("At least one module must be enabled."))
            return
        s = QSettings("LabDream", "LabDream")
        changes = {}
        for code, c in self.cb.items():
            old = module_enabled(code)
            if old != c.isChecked():
                changes[code] = [old, c.isChecked()]
            s.setValue(f"modules/{code}", c.isChecked())
        if changes:
            session.log("MODULES_CHANGED", "modules", changes)
        self.accept()


class HomeWindow(QMainWindow):
    module_selected = Signal(str)
    logout_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(fileio.APP_VERSION)
        w = QWidget()
        self.setCentralWidget(w)
        v = QVBoxLayout(w)
        t = QLabel("LabDream")
        t.setFont(QFont("Arial", 30, QFont.Bold))
        t.setStyleSheet("color:#1f4fa8")
        v.addWidget(t)
        v.addWidget(QLabel(tr("Select a module")))
        row = QHBoxLayout()
        colors = {MODULE_APSD: ("#1f4fa8", "#13306a"), MODULE_PBE: ("#2a6f97", "#1b3f5c")}
        self._leaving = False
        for code, (name, desc) in MODULES.items():
            b = QPushButton()
            b.setMinimumSize(320, 170)
            bl = QVBoxLayout(b)
            t1 = QLabel(tr(name))
            t1.setFont(QFont("Arial", 15, QFont.Bold))
            t2 = QLabel(tr(desc))
            t2.setFont(QFont("Arial", 11))
            for lab in (t1, t2):
                lab.setWordWrap(True)
                lab.setAlignment(Qt.AlignCenter)
                lab.setAttribute(Qt.WA_TransparentForMouseEvents)
                lab.setStyleSheet("color:white;background:transparent")
            bl.addStretch(1); bl.addWidget(t1); bl.addSpacing(8); bl.addWidget(t2); bl.addStretch(1)
            c1, c2 = colors[code]
            b.setStyleSheet(f"QPushButton{{padding:12px;border-radius:10px;"
                            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c1},stop:1 {c2})}}"
                            f"QPushButton:hover{{border:3px solid #f0b400}}"
                            f"QPushButton:disabled{{background:#bbb}}")
            en = module_enabled(code)
            b.setEnabled(en)
            if not en:
                b.setToolTip(tr("Module not enabled on this computer"))
            b.clicked.connect(lambda _=False, c=code: self._pick(c))
            row.addWidget(b)
        v.addLayout(row)
        h = QHBoxLayout()
        mod = QPushButton(tr("Modules…"))
        mod.setEnabled(session.can("modules"))
        mod.clicked.connect(self._modules)
        out = QPushButton(tr("Log Out"))
        out.clicked.connect(self._logout)
        ex = QPushButton(tr("Exit"))
        ex.clicked.connect(self.close)
        h.addWidget(mod); h.addStretch(1); h.addWidget(out); h.addWidget(ex)
        v.addLayout(h)
        u = session.user
        self.statusBar().showMessage(f"{tr('User')}: {u.username} ({u.full_name}) – {tr(u.role)}" if u else "")
        self.resize(720, 340)

    def _pick(self, code):
        self._leaving = True
        session.log("MODULE_SELECTED", code, {})
        self.module_selected.emit(code)

    def _modules(self):
        if ModulesDialog(self).exec() == QDialog.Accepted:
            self._leaving = True
            self.module_selected.emit("")        # rebuild home

    def _logout(self):
        self._leaving = True
        session.log("LOGOUT", session.name(), {})
        session.user = None
        self.logout_requested.emit()

    def closeEvent(self, ev):
        ev.accept()
        if self._leaving:
            return
        if session.user is not None:
            session.log("LOGOUT", session.name(), {"reason": "exit"})
            session.user = None
        QApplication.quit()
