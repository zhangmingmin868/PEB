"""Lemonix INHA Workstation – main window (layout of "Lemonix INHA工作站 - 版本1.pptx").

Left navigation:  Start · Method · Data · Report · Audit · Instrument · Maintenance · System
The calculation logic of the APSD (impactor) and PBE modules is unchanged; this
window only hosts them.  All controlled actions go through ``session`` (role
permissions + hash-chained audit trail).
"""
from __future__ import annotations

import copy
import csv
import datetime as _dt
import json
import os
import shutil
import sys

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog, QPrintPreviewWidget
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QTabWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QToolButton, QVBoxLayout, QWidget)

from .. import fileio, pbe, records, reports, session
from ..devices import DEVICES, DEVICE_ORDER
from ..i18n import LANGUAGES, language, set_language, tr, trf
from ..model import new_dataset
from ..pbe_report import PbeReport, sig_meaning
from ..security import (ALL_PERMISSIONS, AuthError, DEFAULT_POLICY, ROLES, data_dir, policy, role_permissions)
from .dialogs import PrintDialog, SetupDialog, ok_cancel
from .home import MODULE_APSD, MODULE_PBE, ModulesDialog, module_enabled
from .security_dialogs import (AuditTrailDialog, ChangePasswordDialog, UserManagementDialog, message)

SETTINGS = ("LabDream", "LabDream")
BRAND, PRODUCT = "Lemonix", "INHA Workstation"

C_BG, C_CARD, C_ACCENT, C_BLUE, C_GREEN, C_RED = "#e6eaef", "#ffffff", "#c8642a", "#4f72c4", "#4c8a3a", "#b3262e"

QSS = f"""
QMainWindow, #wsRoot {{ background:{C_BG}; }}
#brand {{ color:#2f5d50; font: bold 26px "Arial"; }}
#product {{ color:#8a9099; font: bold 12px "Arial"; }}
#nav {{ background:{C_CARD}; border-radius:10px; }}
#nav QToolButton {{ border:none; padding:8px 6px; font-size:14px; color:#333; text-align:left; }}
#nav QToolButton:hover {{ color:{C_ACCENT}; }}
#nav QToolButton:checked {{ color:{C_ACCENT}; font-weight:bold; border-bottom:2px solid {C_ACCENT}; }}
#nav QToolButton:disabled {{ color:#bbb; }}
#page {{ background:{C_CARD}; border-radius:10px; }}
#card {{ background:#f4f6f9; border-radius:10px; }}
#whitecard {{ background:white; border:1px solid #e3e7ee; border-radius:10px; }}
#crumb {{ background:white; border-radius:8px; padding:4px 12px; color:#333; }}
QTabWidget::pane {{ border:none; background:{C_CARD}; border-radius:10px; top:-1px; }}
QTabBar::tab {{ background:#d9dee6; color:#2a3f73; padding:6px 26px; margin-right:4px;
               border-top-left-radius:8px; border-top-right-radius:8px; font-weight:bold; min-width:80px; }}
QTabBar::tab:selected {{ background:{C_CARD}; }}
QPushButton {{ background:white; border:1px solid #c9ced6; border-radius:8px; padding:6px 18px; color:#222; }}
QPushButton:hover {{ border-color:{C_BLUE}; }}
QPushButton:disabled {{ color:#aaa; background:#f3f3f3; }}
QPushButton[kind="primary"] {{ background:{C_BLUE}; color:white; border:none; font-weight:bold; }}
QPushButton[kind="go"] {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #5aa04a,stop:1 #3d7330);
                          color:white; border:none; font-weight:bold; }}
QPushButton[kind="stop"] {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #c43a3f,stop:1 #8e1f25);
                            color:white; border:none; font-weight:bold; }}
QPushButton[kind="primary"]:disabled, QPushButton[kind="go"]:disabled, QPushButton[kind="stop"]:disabled
    {{ background:#c9ced6; color:#f4f4f4; }}
QPushButton[kind="menu"] {{ text-align:left; padding:9px 14px; font-weight:bold; }}
QPushButton[kind="small"] {{ padding:3px 10px; font-size:12px; }}
QTableWidget {{ border:none; gridline-color:#e7e9ee; selection-background-color:#cfdcf5; selection-color:black; }}
QHeaderView::section {{ background:#f0f1f3; border:none; border-bottom:1px solid #e1e3e8; padding:6px; color:#444; }}
"""


def _btn(text, kind="", slot=None, enabled=True, tip=""):
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if slot:
        b.clicked.connect(slot)
    b.setEnabled(enabled)
    if not enabled:
        b.setToolTip(tip or tr("Not permitted for your role"))
    elif tip:
        b.setToolTip(tip)
    return b


def _frame(name="whitecard"):
    f = QFrame()
    f.setObjectName(name)
    return f


def _h(*widgets, stretch_at=None):
    h = QHBoxLayout()
    for i, w in enumerate(widgets):
        if i == stretch_at:
            h.addStretch(1)
        if isinstance(w, int):
            h.addSpacing(w)
        elif w is None:
            h.addStretch(1)
        else:
            h.addWidget(w)
    return h


def _embed(dlg: QDialog) -> QDialog:
    """Show an existing dialog as a page (its Close button is hidden)."""
    dlg.setWindowFlags(Qt.Widget)
    for b in dlg.findChildren(QPushButton):
        if b.text() in (tr("Close"),):
            b.hide()
    return dlg


def _local(ts: str) -> str:
    """'YYYY-MM-DD HH:MM:SS UTC' -> local time string."""
    try:
        t = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=_dt.timezone.utc)
        return t.astimezone().strftime("%Y/%m/%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts or ""


def _deny(parent):
    QMessageBox.warning(parent, BRAND, tr("Not permitted for your role"))


# ======================================================================
#  E-signature for APSD records (bound to the file SHA-256 in the database)
# ======================================================================
class _SigView:
    def __init__(self, d):
        self.username, self.meaning = d["username"], d["meaning"]


class _ApsdSignTarget:
    """Duck-typed record for pbe_window.SignDialog."""

    def __init__(self, rec):
        self.rec = rec
        self.file_name = rec["name"]
        self._sha = records.file_sha256(rec["path"])
        _, self._sigs = records.status(rec)

    def content_hash(self):
        return self._sha

    def valid_signatures(self):
        return [_SigView(s) for s in self._sigs if s["valid"]]


def sign_record(parent, rec) -> bool:
    """Review / approve a record with an electronic signature. Returns True if signed."""
    from .pbe_window import PbeEditor, SignDialog
    if not os.path.exists(rec["path"]):
        QMessageBox.warning(parent, tr("Electronic Signature"), tr("The data file was not found."))
        return False
    stat, sigs = records.status(rec)
    if rec["module"] == records.MOD_PBE:
        try:
            st = pbe.load(rec["path"])
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(parent, tr("Open"), f"{tr('Could not open file:')}\n{tr(str(e))}")
            return False
        ed = PbeEditor(st, rec["path"], parent)
        n0 = len(st.signatures)
        _guard_approval(parent, sigs) and ed.sign()
        ed.modified = False
        ed.done(0)
        ed.deleteLater()
        return len(st.signatures) > n0
    if not _guard_approval(parent, sigs):
        return False
    tgt = _ApsdSignTarget(rec)
    d = SignDialog(tgt, parent)
    if d.exec() != QDialog.Accepted or d.sig is None:
        return False
    s = d.sig
    if s.meaning == "approved" and policy("report_requires_review") and \
            not any(x["valid"] and x["meaning"] == "reviewed" for x in sigs):
        QMessageBox.warning(parent, tr("Electronic Signature"), tr("The record must be reviewed before it can be approved."))
        return False
    u = session.store.get(s.username)
    ts = session.store.add_approval(rec["id"], s.meaning, u, tgt.content_hash(), s.comment)
    session.log("E_SIGNATURE", rec["name"], {"meaning": s.meaning, "full_name": s.full_name, "module": "APSD",
                                             "file_sha256": tgt.content_hash(), "comment": s.comment})
    QMessageBox.information(parent, tr("Electronic Signature"),
                            trf("Signed as '{m}' by {n} at {t}.", m=sig_meaning(s.meaning), n=s.full_name, t=ts))
    return True


def _guard_approval(parent, sigs) -> bool:
    if session.can("sign_approved") and not session.can("sign_reviewed") and policy("report_requires_review") \
            and not any(x["valid"] and x["meaning"] == "reviewed" for x in sigs):
        QMessageBox.warning(parent, tr("Electronic Signature"), tr("The record must be reviewed before it can be approved."))
        return False
    return True


# ======================================================================
#  Report view / approval dialog  ("报告查看")
# ======================================================================
def _apsd_selection():
    s = QSettings(*SETTINGS)
    raw = s.value("report_template/apsd", "", type=str)
    if raw:
        try:
            return [tuple(x) for x in json.loads(raw)]
        except ValueError:
            pass
    return [(reports.TABULAR, None, None), (reports.GRAPHICAL, None, None)]


class ReportViewDialog(QDialog):
    def __init__(self, rec, parent=None):
        super().__init__(parent)
        self.rec = rec
        self.setWindowTitle(tr("Report View") + " – " + rec["name"])
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1100, 820)
        lay = QVBoxLayout(self)
        self.renderer = None
        self.err = None
        self._build_renderer()
        self.printer = QPrinter(QPrinter.HighResolution)
        self.preview = QPrintPreviewWidget(self.printer, self)
        self.preview.paintRequested.connect(self._paint)
        lay.addWidget(self.preview, 1)
        self.sig = QLabel()
        self.sig.setWordWrap(True)
        self.sig.setTextFormat(Qt.RichText)
        lay.addWidget(self.sig)
        h = QHBoxLayout()
        h.addWidget(_btn(tr("Cancel"), "", self.reject))
        h.addStretch(1)
        h.addWidget(_btn(tr("Print…"), "", self.print_, session.can("print")))
        h.addWidget(_btn(tr("Save as PDF…"), "", self.pdf, session.can("print")))
        can_sign = any(session.can(p) for p in ("sign_performed", "sign_reviewed", "sign_approved"))
        self.b_sign = _btn(tr("Review / Approve"), "primary", self.sign, can_sign,
                           tr("Reports in different approval states are signed by users with the corresponding rights"))
        self.b_sign.setMinimumWidth(160)
        h.addWidget(self.b_sign)
        lay.addLayout(h)
        self._sigs()
        session.log("REPORT_VIEWED", rec["name"], {"module": rec["module"]})

    def _build_renderer(self):
        rec = self.rec
        try:
            if rec["module"] == records.MOD_PBE:
                self.renderer = PbeReport(pbe.load(rec["path"]), printed_by=session.name())
            else:
                self.renderer = reports.ReportRenderer(fileio.load(rec["path"]), _apsd_selection(),
                                                       printed_by=session.name())
        except Exception as e:  # noqa: BLE001
            self.renderer, self.err = None, str(e)

    def _paint(self, printer):
        if self.renderer is not None:
            self.renderer.render(printer)
        else:
            p = QPainter(printer)
            p.drawText(QRectF(50, 50, 2000, 200), tr("Could not open file:") + " " + tr(self.err or ""))
            p.end()

    def _sigs(self):
        stat, sigs = records.status(self.rec)
        rows = []
        for s in sigs:
            ok = "✔" if s["valid"] else "✘ " + tr("invalid – record changed after signing")
            rows.append(f"{sig_meaning(s['meaning'])}: <b>{s['full_name']}</b> ({s['username']}) "
                        f"{_local(s['ts']) if 'UTC' in s['ts'] else s['ts']} {ok}"
                        + (f" – {s['comment']}" if s.get("comment") else ""))
        self.sig.setText(f"<b>{tr('Approval status')}:</b> {tr(records.STATUS_TEXT[stat])}<br>"
                         + ("<br>".join(rows) if rows else tr("No signatures yet.")))

    def sign(self):
        if sign_record(self, self.rec):
            self._build_renderer()
            self.preview.updatePreview()
            self._sigs()

    def print_(self):
        if self.renderer is None:
            return
        prev = QPrintPreviewDialog(QPrinter(QPrinter.HighResolution), self)
        prev.paintRequested.connect(self.renderer.render)
        prev.resize(1000, 800)
        prev.exec()
        session.log("REPORT_PRINTED", self.rec["name"], {"module": self.rec["module"]})

    def pdf(self):
        if self.renderer is None:
            return
        from PySide6.QtGui import QPdfWriter
        base = os.path.splitext(self.rec["path"])[0] + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, tr("Save report as PDF"), base, "PDF (*.pdf)")
        if not path:
            return
        w = QPdfWriter(path)
        w.setResolution(300)
        self.renderer.render(w)
        del w
        session.log("REPORT_PDF", self.rec["name"], {"module": self.rec["module"], "pdf": path})
        QMessageBox.information(self, tr("Print"), trf("Report saved:\n{path}", path=path))


# ======================================================================
#  Record list (Data → APSD / PBE, Report)
# ======================================================================
class DeviceComboDialog(QDialog):
    """'选择装置' – drop-down selection of the impactor configuration."""

    def __init__(self, parent=None, current="NGI"):
        super().__init__(parent)
        self.setWindowTitle(tr("Select Apparatus"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Select the apparatus configuration:")))
        self.cb = QComboBox()
        for code in DEVICE_ORDER:
            self.cb.addItem(f"{code}  –  {tr(DEVICES[code].name)}", code)
        self.cb.setCurrentIndex(max(0, self.cb.findData(current)))
        self.cb.setMinimumWidth(380)
        lay.addWidget(self.cb)
        lay.addStretch(1)
        h = QHBoxLayout()
        h.addWidget(_btn(tr("Cancel"), "", self.reject))
        h.addStretch(1)
        h.addWidget(_btn(tr("Next"), "primary", self.accept))
        lay.addLayout(h)
        self.resize(460, 160)

    def device(self):
        return self.cb.currentData()


class ApsdTemplateDialog(PrintDialog):
    """Default content of APSD reports (report template)."""

    def __init__(self, parent=None):
        super().__init__(10, parent)
        self.setWindowTitle(tr("Report Template"))
        self.pdf.hide()
        for kind, (cb, a, b) in self.items.items():
            cb.setChecked(False)
        for kind, a, b in _apsd_selection():
            if kind in self.items:
                cb, ca, cb2 = self.items[kind]
                cb.setChecked(True)
                if ca is not None:
                    ca.setCurrentIndex(max(0, ca.findData(a)))
                    cb2.setCurrentIndex(max(0, cb2.findData(b)))

    def accept(self):
        sel = self.selections()
        if not sel:
            QMessageBox.warning(self, tr("Report Template"), tr("Select at least one report type."))
            return
        s = QSettings(*SETTINGS)
        old = s.value("report_template/apsd", "", type=str)
        new = json.dumps(sel)
        s.setValue("report_template/apsd", new)
        if old != new:
            session.log("REPORT_TEMPLATE_CHANGED", "APSD", {"old": old, "new": new})
        super().accept()


class PbeDefaultsDialog(QDialog):
    """PBE 'configuration': default design of a new study."""

    KEYS = [("n_ref", "Reference batches", 3), ("m_ref", "Containers per reference batch", 10),
            ("n_test", "Test batches", 3), ("m_test", "Containers per test batch", 10),
            ("stages", "Life stages / measurements", 1)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("PBE Configuration"))
        s = QSettings(*SETTINGS)
        form = QFormLayout(self)
        self.sp = {}
        for k, label, dflt in self.KEYS:
            sp = QSpinBox()
            sp.setRange(1, 60 if k.startswith("m") else (pbe.MAX_STAGES if k == "stages" else 20))
            sp.setValue(s.value(f"pbe_default/{k}", dflt, type=int))
            self.sp[k] = sp
            form.addRow(tr(label), sp)
        form.addRow(ok_cancel(self, self._ok, self.reject))

    def _ok(self):
        s = QSettings(*SETTINGS)
        ch = {}
        for k, sp in self.sp.items():
            old = s.value(f"pbe_default/{k}", None)
            if str(old) != str(sp.value()):
                ch[k] = [old, sp.value()]
            s.setValue(f"pbe_default/{k}", sp.value())
        if ch:
            session.log("SETTINGS_CHANGED", "PBE defaults", ch)
        self.accept()


def pbe_defaults():
    s = QSettings(*SETTINGS)
    return [s.value(f"pbe_default/{k}", d, type=int) for k, _, d in PbeDefaultsDialog.KEYS]


class RecordList(QWidget):
    COLS = ["No.", "Report name", "Generated", "Operator", "Approval", "Approval time", "Summary"]

    def __init__(self, module=None, parent=None, show_new=True):
        super().__init__(parent)
        self.module = module
        self.rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        self.filter_bar = QWidget()
        fb = QHBoxLayout(self.filter_bar)
        fb.setContentsMargins(0, 0, 0, 0)
        self.f_text = QLineEdit()
        self.f_text.setPlaceholderText(tr("Search name / operator"))
        self.f_status = QComboBox()
        self.f_status.addItem(tr("All states"), None)
        for k in (records.ST_DRAFT, records.ST_PERFORMED, records.ST_REVIEWED, records.ST_APPROVED,
                  records.ST_INVALID, records.ST_MISSING):
            self.f_status.addItem(tr(records.STATUS_TEXT[k]), k)
        self.f_text.textChanged.connect(self.reload)
        self.f_status.currentIndexChanged.connect(self.reload)
        fb.addWidget(QLabel(tr("Filter list")))
        fb.addWidget(self.f_text, 1)
        fb.addWidget(self.f_status)
        self.filter_bar.hide()
        lay.addWidget(self.filter_bar)
        cols = self.COLS if module else ["Module"] + self.COLS
        self.cols = cols
        self.t = QTableWidget(0, len(cols))
        self.t.setHorizontalHeaderLabels([tr(c) for c in cols])
        self.t.verticalHeader().hide()
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.setShowGrid(False)
        self.t.verticalHeader().setDefaultSectionSize(38)
        hh = self.t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(cols.index("Report name"), QHeaderView.Stretch)
        self.t.setContextMenuPolicy(Qt.CustomContextMenu)
        self.t.customContextMenuRequested.connect(self._menu)
        self.t.doubleClicked.connect(lambda *_: self.view())
        lay.addWidget(self.t, 1)
        hint = QLabel(tr("Colours show the approval state. Double-click or right-click an entry to view and approve it."))
        hint.setStyleSheet("color:#777;font-size:11px")
        lay.addWidget(hint)
        h = QHBoxLayout()
        if module and show_new:
            b = _btn(tr("New"), "primary", self.new, session.can("edit_data"))
            b.setMinimumWidth(150)
            h.addWidget(b)
            h.addWidget(_btn(tr("Open"), "", self.open_existing))
            perm = "templates" if module == records.MOD_APSD else "edit_data"
            h.addWidget(_btn(tr("Configure"), "", self.configure, session.can(perm)))
            h.addWidget(_btn(tr("Report Template"), "", self.template, session.can("templates")))
        h.addStretch(1)
        self.b_filter = _btn("⏷ " + tr("Filter list"), "small", self._toggle_filter)
        h.addWidget(self.b_filter)
        h.addWidget(_btn("⤓ " + tr("Export"), "small", self.export, session.can("export")))
        h.addWidget(_btn("⎙ " + tr("Print"), "small", self.print_list, session.can("print")))
        lay.addLayout(h)
        self.reload()

    # ------------------------------------------------------------------
    def _toggle_filter(self):
        self.filter_bar.setVisible(not self.filter_bar.isVisible())

    def reload(self):
        if session.store is None:
            return
        txt = self.f_text.text().strip().lower()
        want = self.f_status.currentData()
        out = []
        for rec in session.store.record_list(self.module):
            if rec["module"] == records.MOD_APSD and not module_enabled(MODULE_APSD):
                continue
            if rec["module"] == records.MOD_PBE and not module_enabled(MODULE_PBE):
                continue
            stat, sigs = records.status(rec)
            last = records.last_signature(sigs)
            if want and stat != want:
                continue
            if txt and txt not in rec["name"].lower() and txt not in rec["created_by"].lower():
                continue
            out.append((rec, stat, last))
        self.rows = out
        self.t.setRowCount(len(out))
        for i, (rec, stat, last) in enumerate(out):
            vals = [str(len(out) - i), rec["name"], _local(rec["created_at"]), rec["created_by"],
                    tr(records.STATUS_TEXT[stat]),
                    (_local(last["ts"]) if last and "UTC" in last["ts"] else (last["ts"] if last else "")),
                    rec.get("summary", "")]
            if not self.module:
                vals = [rec["module"]] + vals
            color = QColor(records.STATUS_COLOR[stat])
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setBackground(color)
                if j == 0:
                    it.setData(Qt.UserRole, rec["id"])
                self.t.setItem(i, j, it)

    def current(self):
        r = self.t.currentRow()
        if r < 0 or r >= len(self.rows):
            QMessageBox.information(self, BRAND, tr("Select an entry first."))
            return None
        return self.rows[r][0]

    def _menu(self, pos):
        idx = self.t.indexAt(pos)
        if idx.isValid():
            self.t.selectRow(idx.row())
        m = QMenu(self)
        m.addAction(tr("View report / approve"), self.view)
        m.addAction(tr("Open data"), self.edit)
        m.addAction(tr("Show in folder"), self.reveal)
        m.addSeparator()
        a = m.addAction(tr("Remove from list (file is kept)"), self.remove)
        a.setEnabled(session.can("data_management"))
        m.exec(self.t.viewport().mapToGlobal(pos))

    def view(self):
        rec = self.current()
        if rec:
            ReportViewDialog(rec, self).exec()
            self.reload()

    def edit(self):
        rec = self.current()
        if rec:
            open_record_file(self, rec["path"], rec["module"])
            self.reload()

    def reveal(self):
        rec = self.current()
        if rec:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(rec["path"])))

    def remove(self):
        rec = self.current()
        if rec and QMessageBox.question(self, BRAND, trf("Remove '{n}' from the list? The data file is not deleted.",
                                                         n=rec["name"])) == QMessageBox.Yes:
            session.store.remove_record(session.name(), rec["id"])
            self.reload()

    # ------------------------------------------------------------------
    def new(self):
        if not session.can("edit_data"):
            return _deny(self)
        if self.module == records.MOD_APSD:
            new_apsd(self)
        else:
            m = QMenu(self)
            m.addAction(tr("Blank study"), lambda: new_pbe(self, False))
            m.addAction(tr("Import data source file (CSV / Excel)…"), lambda: new_pbe(self, True))
            m.exec(self.cursor().pos())
        self.reload()

    def open_existing(self):
        s = QSettings(*SETTINGS)
        if self.module == records.MOD_APSD:
            filt = f"{tr('Data files')} (*{fileio.NATIVE_EXT} *.cpl *.CPL)"
            start = s.value("data_dir", "", type=str)
        else:
            filt = f"{tr('PBE study')} (*{pbe.PBE_EXT})"
            start = s.value("pbe_dir", "", type=str)
        path, _ = QFileDialog.getOpenFileName(self, tr("Open Data File"), start, filt + ";;* (*)")
        if path:
            open_record_file(self, path, self.module)
            self.reload()

    def configure(self):
        if self.module == records.MOD_APSD:
            SetupDialog(self).exec()
        else:
            PbeDefaultsDialog(self).exec()

    def template(self):
        if self.module == records.MOD_APSD:
            ApsdTemplateDialog(self).exec()
        else:
            QMessageBox.information(self, tr("Report Template"),
                                    tr("The PBE report follows the FDA PBE procedure: study information, Table 2 "
                                       "summary, intermediate values, E/H/U tables, conclusion, signature manifest "
                                       "and individual data."))

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export"), "records.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([tr(c) for c in self.cols] + ["path"])
            for i in range(self.t.rowCount()):
                w.writerow([self.t.item(i, j).text() for j in range(self.t.columnCount())] + [self.rows[i][0]["path"]])
        session.log("RECORD_LIST_EXPORTED", self.module or "all", {"file": path, "rows": self.t.rowCount()})
        QMessageBox.information(self, tr("Export"), trf("Data exported:\n{path}", path=path))

    def print_list(self):
        html = "<h3>%s</h3><table border=1 cellspacing=0 cellpadding=3><tr>%s</tr>" % (
            f"{BRAND} {PRODUCT} – {self.module or tr('Reports')}", "".join(f"<th>{tr(c)}</th>" for c in self.cols))
        for i in range(self.t.rowCount()):
            html += "<tr>" + "".join(f"<td>{self.t.item(i, j).text()}</td>" for j in range(self.t.columnCount())) + "</tr>"
        html += f"</table><p>{tr('Printed by')} {session.name()}  {_dt.datetime.now():%Y-%m-%d %H:%M:%S}</p>"
        tb = QTextBrowser()
        tb.setHtml(html)
        prev = QPrintPreviewDialog(QPrinter(QPrinter.HighResolution), self)
        prev.paintRequested.connect(lambda p: tb.document().print_(p))
        prev.exec()
        session.log("RECORD_LIST_PRINTED", self.module or "all", {"rows": self.t.rowCount()})


# ---------------------------------------------------------------------- open / new helpers
def open_record_file(parent, path, module):
    from .pbe_window import PbeEditor
    from .wizard import DataWizard
    if module == records.MOD_PBE or path.lower().endswith(pbe.PBE_EXT):
        try:
            st = pbe.load(path)
        except Exception as e:  # noqa: BLE001
            session.log("FILE_OPEN_FAILED", os.path.basename(path), {"path": path, "error": str(e), "module": "PBE"})
            QMessageBox.critical(parent, tr("Open"), f"{tr('Could not open file:')}\n{tr(str(e))}")
            return
        QSettings(*SETTINGS).setValue("pbe_dir", os.path.dirname(path))
        session.log("FILE_OPENED", os.path.basename(path), {"path": path, "revision": st.revision, "module": "PBE",
                                                            "record_sha256": st.content_hash()})
        if session.store.record_by_path(path) is None:
            records.register(records.MOD_PBE, path)
        PbeEditor(st, path, parent).exec()
        return
    try:
        ds = fileio.load(path)
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(parent, tr("Open"), f"{tr('Could not open file:')}\n{e}")
        return
    session.log("FILE_OPENED", os.path.basename(path), {"path": path, "revision": ds.revision})
    if not path.lower().endswith(".cpl") and session.store.record_by_path(path) is None:
        records.register(records.MOD_APSD, path, ds.dev.name)
    DataWizard(ds, path, parent).exec()


def new_apsd(parent):
    from .wizard import DataWizard
    s = QSettings(*SETTINGS)
    dlg = DeviceComboDialog(parent, s.value("last_device", "NGI", type=str))
    if dlg.exec() != QDialog.Accepted:
        return
    dev = dlg.device()
    s.setValue("last_device", dev)
    ds = new_dataset(dev)
    if s.value(f"template/{dev}/use", False, type=bool):
        p = s.value(f"template/{dev}/path", "", type=str)
        if p and os.path.exists(p):
            try:
                t = fileio.load(p)
                if t.device == dev:
                    ds = t
                    ds.file_name = ""
                    ds.created_by = ds.created_at = ds.modified_by = ds.modified_at = ""
                    ds.revision = 0
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(parent, tr("Template"), f"{tr('Could not read template:')}\n{e}")
    session.log("FILE_NEW", dev, {})
    DataWizard(ds, None, parent).exec()


def new_pbe(parent, from_import):
    from .pbe_window import PbeEditor
    s = QSettings(*SETTINGS)
    if not from_import:
        n_ref, m_ref, n_test, m_test, stages = pbe_defaults()
        st = pbe.new_study(n_ref, m_ref, n_test, m_test, stages)
        session.log("FILE_NEW", "PBE", {"module": "PBE"})
        PbeEditor(st, None, parent).exec()
        return
    start = s.value("pbe_dir", "", type=str)
    path, _ = QFileDialog.getOpenFileName(parent, tr("Import"), start,
                                          f"{tr('Data files')} (*.csv *.txt *.xlsx *.xlsm);;CSV (*.csv *.txt);;Excel (*.xlsx *.xlsm)")
    if not path:
        return
    try:
        if path.lower().endswith((".xlsx", ".xlsm")):
            ref, test, m = pbe.import_workbook(path)
            names = None
        else:
            ref, test, m, names = pbe.parse_long_table(pbe.read_csv_rows(path))
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(parent, tr("Import"), f"{tr('Could not import the file:')}\n{tr(str(e))}")
        return
    st = pbe.PbeStudy(m=m, reference=ref, test=test)
    if names:
        st.stage_names = (list(names) + st.stage_names[len(names):])[:pbe.MAX_STAGES]
    st.title = os.path.splitext(os.path.basename(path))[0]
    session.log("FILE_NEW", "PBE", {"module": "PBE", "import": path})
    PbeEditor(st, None, parent, imported_from=path).exec()


# ======================================================================
#  Pages
# ======================================================================
class Page(QWidget):
    title = ""

    def refresh(self):
        pass


class FlowDiagram(QWidget):
    """Impactor → flow controller → pump schematic (start page)."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(140)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = min(self.width(), 560)
        bw, bh, gap = 140, 120, (w - 3 * 140) / 2
        blue, pale = QColor("#4f72c4"), QColor("#e3e8f4")
        for i in range(3):
            x = i * (bw + gap)
            p.setPen(Qt.NoPen)
            p.setBrush(pale)
            p.drawRoundedRect(QRectF(x, 0, bw, bh), 14, 14)
            p.setBrush(blue)
            if i == 0:
                for k in range(4):
                    p.drawRoundedRect(QRectF(x + 40, 40 + k * 16, 60, 11), 5, 5)
                p.drawRect(QRectF(x + 62, 14, 8, 28))
                p.drawRect(QRectF(x + 62, 14, 26, 7))
            elif i == 1:
                p.drawRoundedRect(QRectF(x + 30, 34, 80, 54), 6, 6)
                p.setBrush(QColor("white"))
                p.drawRoundedRect(QRectF(x + 50, 48, 40, 22), 4, 4)
            else:
                p.drawRoundedRect(QRectF(x + 34, 20, 72, 80), 8, 8)
                p.setBrush(QColor("white"))
                p.drawRoundedRect(QRectF(x + 66, 34, 8, 14), 2, 2)
        p.setPen(QPen(blue, 2))
        p.drawLine(QPointF(100, 88), QPointF(bw + gap + 30, 70))
        p.drawLine(QPointF(2 * bw + gap - 30, 62), QPointF(2 * (bw + gap) + 34, 70))
        p.end()


class StartPage(Page):
    title = "Start"

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        left = QVBoxLayout()
        info = _frame("card")
        il = QVBoxLayout(info)
        il.addWidget(QLabel(f"<b style='color:#2a3f73'>{tr('Instrument information')}</b>"))
        self.inst = QComboBox()
        self.inst.currentIndexChanged.connect(self._inst_info)
        il.addWidget(self.inst)
        self.inst_form = QLabel()
        self.inst_form.setStyleSheet("font-size:11px")
        il.addWidget(self.inst_form)
        self.b_flow = _btn(tr("Flow test"), "", self._offline)
        self.b_leak = _btn(tr("Leak test"), "", self._offline)
        il.addWidget(self.b_flow)
        il.addWidget(self.b_leak)
        left.addWidget(info)
        mcard = _frame("card")
        ml = QVBoxLayout(mcard)
        ml.addWidget(QLabel(f"<b style='color:#2a3f73'>{tr('Method')}</b>"))
        self.method = QComboBox()
        self.method.currentIndexChanged.connect(self._method_info)
        ml.addWidget(self.method)
        self.method_info = QLabel()
        self.method_info.setStyleSheet("background:white;border-radius:6px;padding:6px")
        ml.addWidget(self.method_info)
        left.addWidget(mcard)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(230)
        lay.addWidget(lw)
        right = QVBoxLayout()
        right.addWidget(FlowDiagram())
        cards = QHBoxLayout()
        self.live = {}
        for keys in (("Temperature / RH", "Q", "P1", "P3/P2", "Leak rate"), ("Run Time", "Volume", "Sections", "Delay")):
            c = _frame()
            g = QGridLayout(c)
            for r, k in enumerate(keys):
                g.addWidget(QLabel(tr(k)), r, 0)
                v = QLabel("--")
                v.setStyleSheet("font-size:22px;font-weight:bold;color:#8bc34a" if keys[0].startswith("Temp")
                                else "font-size:22px;font-weight:bold;color:#3aa0e8")
                v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                g.addWidget(v, r, 1)
                self.live[k] = v
            cards.addWidget(c)
        right.addLayout(cards)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#a0522d")
        right.addWidget(self.status)
        right.addStretch(1)
        self.b_stop = _btn(tr("Abort"), "stop", self._offline)
        self.b_start = _btn(tr("Start run"), "go", self._offline)
        for b in (self.b_stop, self.b_start):
            b.setMinimumSize(150, 34)
        right.addLayout(_h(None, self.b_stop, 20, self.b_start))
        lay.addLayout(right, 1)

    def refresh(self):
        self.inst.blockSignals(True)
        self.inst.clear()
        self.insts = session.store.instruments()
        for i in self.insts:
            self.inst.addItem(f"{i['tag'] or i['name']}  {i['name']}", i["id"])
        if not self.insts:
            self.inst.addItem(tr("(no instrument configured)"), None)
        self.inst.blockSignals(False)
        self._inst_info()
        self.method.blockSignals(True)
        self.method.clear()
        self.methods = session.store.methods()
        for m in self.methods:
            self.method.addItem(m["name"])
        self.method.blockSignals(False)
        self._method_info()
        self.status.setText("● " + tr("Instrument not connected – offline data-processing mode. "
                                      "Start / abort and the flow and leak tests need a connected flow controller."))
        connected = False
        for b in (self.b_start, self.b_stop, self.b_flow, self.b_leak):
            b.setEnabled(connected)

    def _inst_info(self):
        i = self.inst.currentIndex()
        if 0 <= i < len(getattr(self, "insts", [])):
            d = self.insts[i]
            self.inst_form.setText(f"{tr('Name')}: {d['name']}<br>{tr('Model')}: {d['model']}<br>SN: {d['sn']}<br>"
                                   f"ID: {d['tag']}<br>{tr('Valid until')}: {d['valid_until']}")
        else:
            self.inst_form.setText(tr("Add instruments under Instrument."))

    def _method_info(self):
        i = self.method.currentIndex()
        if 0 <= i < len(getattr(self, "methods", [])):
            d = json.loads(self.methods[i]["data"])
            self.method_info.setText(
                f"{tr('Run time')}: <b>{d.get('run_time', '')} s</b><br>{tr('Volume')}: <b>{d.get('volume', '')} L</b><br>"
                f"{tr('Repeats')}: <b>{d.get('repeats', '')}</b><br>{tr('Delay')}: <b>{d.get('delay', '')} s</b>")
            self.live["Run Time"].setText(f"-- / {d.get('run_time', '')} s")
            self.live["Volume"].setText(f"-- / {d.get('volume', '')} L")
            self.live["Sections"].setText(f"-- / {d.get('repeats', '')}")
            self.live["Delay"].setText(f"-- / {d.get('delay', '')} s")
        else:
            self.method_info.setText(tr("No method. Create one under Method."))

    def _offline(self):
        QMessageBox.information(self, BRAND, tr("No instrument connected."))


class MethodPage(Page):
    title = "Method"
    FIELDS = {"run_time": 4.0, "volume": 4.0, "repeats": 3, "delay": 0.0, "pump_on": True, "pump_on_delay": 3.0,
              "pump_off": True, "pump_off_delay": 3.0, "flow_test_forced": True, "flow_test_freq": "every start",
              "p1_check": True, "p3p2_min": 0.0, "p3p2_max": 0.5, "leak_period": 30, "leak_test_forced": True,
              "leak_test_freq": "every start", "leak_limit": 0.5}
    FREQ = ["every start", "every run", "daily", "manual"]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        card = _frame("card")
        cl = QVBoxLayout(card)
        top = QHBoxLayout()
        top.addWidget(QLabel(f"<b style='color:#2a3f73'>{tr('Method name')}</b>"))
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setMinimumWidth(200)
        self.name.currentIndexChanged.connect(self._load)
        top.addWidget(self.name)
        top.addStretch(1)
        self.b_new = _btn(tr("New"), "small", self._new)
        top.addWidget(self.b_new)
        cl.addLayout(top)
        grid = QHBoxLayout()
        self.w = {}
        # run parameters
        run = _frame()
        rf = QFormLayout(run)
        rf.addRow(QLabel(f"<b>{tr('Run parameters')}</b>"))
        self.w["run_time"] = self._dsb(0, 3600, " s")
        self.w["volume"] = self._dsb(0, 1000, " L")
        self.w["repeats"] = QSpinBox()
        self.w["repeats"].setRange(1, 100)
        self.w["delay"] = self._dsb(0, 3600, " s")
        for k, lab in (("run_time", "Run time"), ("volume", "Volume"), ("repeats", "Repeats"), ("delay", "Delay")):
            rf.addRow(tr(lab), self.w[k])
        self.w["pump_on"] = QCheckBox(tr("Auto pump on"))
        self.w["pump_on_delay"] = self._dsb(0, 600, " s")
        self.w["pump_off"] = QCheckBox(tr("Auto pump off"))
        self.w["pump_off_delay"] = self._dsb(0, 600, " s")
        rf.addRow(self.w["pump_on"], self.w["pump_on_delay"])
        rf.addRow(self.w["pump_off"], self.w["pump_off_delay"])
        grid.addWidget(run, 1)
        col = QVBoxLayout()
        flow = _frame()
        ff = QFormLayout(flow)
        ff.addRow(QLabel(f"<b>{tr('Flow test')}</b>"))
        self.w["flow_test_forced"] = QCheckBox(tr("Enforce flow test"))
        self.w["flow_test_freq"] = self._freq()
        ff.addRow(self.w["flow_test_forced"], self.w["flow_test_freq"])
        self.w["p1_check"] = QCheckBox(tr("P1 check"))
        ff.addRow(self.w["p1_check"])
        self.w["p3p2_min"] = self._dsb(0, 1, "", 2)
        self.w["p3p2_max"] = self._dsb(0, 1, "", 2)
        ff.addRow(tr("Test limit P3/P2"), _wrap(_h(self.w["p3p2_min"], QLabel("~"), self.w["p3p2_max"])))
        col.addWidget(flow)
        leak = _frame()
        lf = QFormLayout(leak)
        lf.addRow(QLabel(f"<b>{tr('Leak test')}</b>"))
        self.w["leak_period"] = QSpinBox()
        self.w["leak_period"].setRange(1, 3600)
        self.w["leak_period"].setSuffix(" s")
        lf.addRow(tr("Test period"), self.w["leak_period"])
        self.w["leak_test_forced"] = QCheckBox(tr("Enforce leak test"))
        self.w["leak_test_freq"] = self._freq()
        lf.addRow(self.w["leak_test_forced"], self.w["leak_test_freq"])
        self.w["leak_limit"] = self._dsb(0, 100, " kPa/min", 2)
        lf.addRow(tr("Test limit PA"), self.w["leak_limit"])
        col.addWidget(leak)
        grid.addLayout(col, 1)
        cl.addLayout(grid)
        cl.addStretch(1)
        outer.addWidget(card, 1)
        self.b_save = _btn(tr("Save"), "go", self._save, session.can("methods"))
        self.b_save.setMinimumSize(150, 34)
        outer.addLayout(_h(None, self.b_save))
        self._set(dict(self.FIELDS))

    @staticmethod
    def _dsb(lo, hi, suffix, dec=1):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSuffix(suffix)
        return s

    def _freq(self):
        c = QComboBox()
        for f in self.FREQ:
            c.addItem(tr(f), f)
        return c

    def refresh(self):
        cur = self.name.currentText()
        self.name.blockSignals(True)
        self.name.clear()
        self.methods = {m["name"]: json.loads(m["data"]) for m in session.store.methods()}
        self.name.addItems(list(self.methods))
        self.name.blockSignals(False)
        if cur in self.methods:
            self.name.setCurrentText(cur)
        self._load()

    def _load(self, *_):
        d = dict(self.FIELDS)
        d.update(getattr(self, "methods", {}).get(self.name.currentText(), {}))
        self._set(d)

    def _set(self, d):
        for k, w in self.w.items():
            v = d.get(k, self.FIELDS[k])
            if isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(v)))
            else:
                w.setValue(v)
        ro = not session.can("methods")
        for w in self.w.values():
            w.setEnabled(not ro)

    def _get(self):
        out = {}
        for k, w in self.w.items():
            if isinstance(w, QCheckBox):
                out[k] = w.isChecked()
            elif isinstance(w, QComboBox):
                out[k] = w.currentData()
            elif isinstance(w, QSpinBox):
                out[k] = w.value()
            else:
                out[k] = round(w.value(), 4)
        return out

    def _new(self):
        if not session.can("methods"):
            return _deny(self)
        name, ok = QInputDialog.getText(self, tr("New"), tr("Method name"),
                                        text=_dt.date.today().strftime("%Y%m%d") + "-1")
        if ok and name.strip():
            self.name.setEditText(name.strip())
            self._set(dict(self.FIELDS))

    def _save(self):
        if not session.can("methods"):
            return _deny(self)
        name = self.name.currentText().strip()
        if not name:
            QMessageBox.warning(self, tr("Method"), tr("Enter a method name."))
            return
        data = self._get()
        reason = ""
        if name in self.methods and self.methods[name] != data:
            reason, ok = QInputDialog.getText(self, tr("Reason for Change"),
                                              tr("Enter the reason for changing this method:"))
            if not ok or not reason.strip():
                QMessageBox.warning(self, tr("Reason for Change"), tr("A reason for change is required."))
                return
        session.store.save_method(session.name(), name, data, reason.strip())
        self.refresh()
        self.name.setCurrentText(name)
        QMessageBox.information(self, tr("Method"), tr("Method saved."))


def _wrap(layout):
    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w


class DataPage(Page):
    title = "Data"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.runs = QTableWidget(0, 8)
        self.runs.setHorizontalHeaderLabels([tr(x) for x in ("Time", "Sections", "Status", "Flow", "P1", "Flow test",
                                                             "Leak test", "Operator")])
        self.runs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.runs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.runs.verticalHeader().hide()
        rw = QWidget()
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(16, 14, 16, 12)
        rl.addWidget(self.runs)
        self.runs_hint = QLabel(tr("Test records are written by the connected flow controller. "
                                   "No instrument is connected."))
        self.runs_hint.setStyleSheet("color:#777;font-size:11px")
        rl.addWidget(self.runs_hint)
        self.tabs.addTab(rw, tr("Test records"))
        self.lists = []
        if module_enabled(MODULE_APSD):
            self.apsd = RecordList(records.MOD_APSD)
            self.tabs.addTab(self.apsd, "APSD")
            self.lists.append(self.apsd)
        if module_enabled(MODULE_PBE):
            self.pbe = RecordList(records.MOD_PBE)
            self.tabs.addTab(self.pbe, "PBE")
            self.lists.append(self.pbe)
        self.tabs.setCurrentIndex(1 if self.lists else 0)
        lay.addWidget(self.tabs)

    def refresh(self):
        for l in self.lists:
            l.reload()
        rows = session.store.test_runs()
        self.runs.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, k in enumerate(("ts", "sections", "status", "flow", "p1", "flow_test", "leak_test", "operator")):
                self.runs.setItem(i, j, QTableWidgetItem(str(r[k])))


class ReportPage(Page):
    title = "Report"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.list = RecordList(None, show_new=False)
        self.tabs.addTab(self.list, tr("Report approval"))
        lay.addWidget(self.tabs)

    def refresh(self):
        self.list.reload()


class AuditPage(Page):
    title = "Audit"

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 12, 12, 12)
        self.dlg = None

    def refresh(self):
        if not session.can("view_audit"):
            if self.dlg is None:
                self.dlg = QLabel(tr("Not permitted for your role"))
                self.lay.addWidget(self.dlg)
            return
        if self.dlg is None:
            self.dlg = _embed(AuditTrailDialog(self))
            self.lay.addWidget(self.dlg)
        else:
            self.dlg.reload()


class InstrumentDialog(QDialog):
    KEYS = [("name", "Name"), ("model", "Model"), ("sn", "SN"), ("tag", "ID"), ("valid_until", "Valid until"),
            ("notes", "Notes")]

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Instrument"))
        form = QFormLayout(self)
        self.e = {}
        for k, lab in self.KEYS:
            self.e[k] = QLineEdit((data or {}).get(k, ""))
            form.addRow(tr(lab), self.e[k])
        self.e["valid_until"].setPlaceholderText("YYYY-MM-DD")
        form.addRow(ok_cancel(self, self._ok, self.reject))
        self.resize(420, 260)

    def _ok(self):
        if not self.e["name"].text().strip():
            QMessageBox.warning(self, tr("Instrument"), tr("Enter a name."))
            return
        self.accept()

    def data(self):
        return {k: e.text().strip() for k, e in self.e.items()}


class InstrumentPage(Page):
    title = "Instrument"
    COLS = ["Name", "Model", "SN", "ID", "Valid until", "Status", "Notes"]

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        self.t = QTableWidget(0, len(self.COLS))
        self.t.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.verticalHeader().hide()
        self.t.doubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.t)
        ok = session.can("instruments")
        lay.addLayout(_h(_btn(tr("Add…"), "primary", self.add, ok), _btn(tr("Edit…"), "", self.edit, ok), None))

    def refresh(self):
        self.rows = session.store.instruments()
        self.t.setRowCount(len(self.rows))
        today = _dt.date.today().isoformat()
        for i, r in enumerate(self.rows):
            vu = r["valid_until"]
            stat = tr("Calibration expired") if vu and vu < today else tr("Offline")
            for j, v in enumerate([r["name"], r["model"], r["sn"], r["tag"], vu, stat, r["notes"]]):
                it = QTableWidgetItem(v)
                if vu and vu < today:
                    it.setBackground(QColor("#f9dede"))
                self.t.setItem(i, j, it)

    def add(self):
        d = InstrumentDialog(self)
        if d.exec() == QDialog.Accepted:
            session.store.save_instrument(session.name(), d.data())
            self.refresh()

    def edit(self):
        if not session.can("instruments"):
            return
        i = self.t.currentRow()
        if 0 <= i < len(self.rows):
            d = InstrumentDialog(self, self.rows[i])
            if d.exec() == QDialog.Accepted:
                session.store.save_instrument(session.name(), d.data(), self.rows[i]["id"])
                self.refresh()


class MaintenancePage(Page):
    title = "Maintenance"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        items = [
            ("APSD templates and data folder", self.templates, session.can("templates")),
            ("Verify audit trail integrity", self.verify, session.can("view_audit")),
            ("Verify data files (SHA-256)", self.verify_files, session.can("view_audit")),
            ("Back up database…", self.backup, session.can("data_management")),
        ]
        for text, fn, ok in items:
            b = _btn(tr(text), "menu", fn, ok)
            b.setFixedWidth(340)
            lay.addWidget(b)
        lay.addStretch(1)

    def templates(self):
        SetupDialog(self).exec()

    def verify(self):
        ok, n, bad = session.store.verify()
        session.log("AUDIT_VERIFIED", "audit trail", {"ok": ok, "records": n})
        if ok:
            QMessageBox.information(self, tr("Audit Trail"),
                                    trf("Integrity check passed: {n} records, hash chain intact.", n=n))
        else:
            QMessageBox.critical(self, tr("Audit Trail"),
                                 trf("Integrity check FAILED at record #{id}. The audit trail has been altered.", id=bad))

    def verify_files(self):
        bad, n = [], 0
        for rec in session.store.record_list():
            n += 1
            if not os.path.exists(rec["path"]):
                bad.append(f"{rec['name']}: {tr('File missing')}")
                continue
            sha = records.file_sha256(rec["path"])
            if sha != rec["sha256"]:
                bad.append(f"{rec['name']}: {tr('changed outside the program')}")
        session.log("FILES_VERIFIED", "records", {"records": n, "problems": bad})
        if bad:
            QMessageBox.warning(self, tr("Verify data files (SHA-256)"), "\n".join(bad))
        else:
            QMessageBox.information(self, tr("Verify data files (SHA-256)"), trf("{n} records checked, all intact.", n=n))

    def backup(self):
        default = os.path.join(os.path.expanduser("~"), f"labdream_backup_{_dt.datetime.now():%Y%m%d_%H%M%S}.db")
        path, _ = QFileDialog.getSaveFileName(self, tr("Back up database…"), default, "SQLite (*.db)")
        if path:
            session.store.backup(session.name(), path)
            QMessageBox.information(self, tr("Back up database…"), trf("Report saved:\n{path}", path=path))


# ---------------------------------------------------------------------- System
class PermissionGroupsWidget(QWidget):
    PERM_TEXT = {"edit_data": "Enter / edit data", "print": "Print reports", "export": "Export data",
                 "view_audit": "View audit trail", "templates": "Templates / report templates",
                 "maintenance": "Maintenance mode (stage titles, calibration)", "manage_users": "User management",
                 "sign_performed": "Sign: performed", "sign_reviewed": "Sign: reviewed", "sign_approved": "Sign: approved",
                 "modules": "Module configuration", "methods": "Edit methods", "instruments": "Edit instruments",
                 "policies": "Edit policies", "data_management": "Data management / backup"}

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        self.t = QTableWidget(len(ALL_PERMISSIONS), len(ROLES))
        self.t.setHorizontalHeaderLabels([tr(r) for r in ROLES])
        self.t.setVerticalHeaderLabels([tr(self.PERM_TEXT[p]) for p in ALL_PERMISSIONS])
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.t)
        ok = session.can("manage_users")
        lay.addLayout(_h(_btn(tr("Restore defaults"), "", self.defaults, ok), None,
                         _btn(tr("Save"), "go", self.save, ok)))
        self.load()

    def load(self, perms=None):
        ok = session.can("manage_users")
        for j, role in enumerate(ROLES):
            have = perms[role] if perms else role_permissions(role)
            for i, p in enumerate(ALL_PERMISSIONS):
                it = QTableWidgetItem()
                flags = Qt.ItemIsUserCheckable | Qt.ItemIsEnabled if ok else Qt.ItemIsEnabled
                if role == "admin" and p == "manage_users":
                    flags = Qt.ItemIsEnabled
                it.setFlags(flags)
                it.setCheckState(Qt.Checked if p in have else Qt.Unchecked)
                self.t.setItem(i, j, it)

    def defaults(self):
        from ..security import PERMISSIONS
        self.load({r: PERMISSIONS[r] for r in ROLES})

    def save(self):
        if not session.can("manage_users"):
            return
        for j, role in enumerate(ROLES):
            perms = {p for i, p in enumerate(ALL_PERMISSIONS) if self.t.item(i, j).checkState() == Qt.Checked}
            session.store.set_role_permissions(session.name(), role, perms)
        QMessageBox.information(self, tr("Permission groups"),
                                tr("Permissions saved. They take effect at the next log in."))


class PolicyWidget(QTabWidget):
    def __init__(self):
        super().__init__()
        self.sp = {}
        ok = session.can("policies")

        def spin(key, lo, hi, suffix=""):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setSuffix(suffix)
            s.setValue(policy(key))
            s.setEnabled(ok)
            s.setMinimumWidth(240)
            s.setMaximumWidth(260)
            self.sp[key] = s
            return s

        def chk(key, text):
            c = QCheckBox(tr(text))
            c.setChecked(bool(policy(key)))
            c.setEnabled(ok)
            self.sp[key] = c
            return c

        pw = QWidget()
        f = QFormLayout(pw)
        f.addRow(tr("Minimum password length"), spin("pw_min_len", 4, 32))
        f.addRow(tr("Password validity"), spin("pw_expiry_days", 0, 3650, " " + tr("days (0 = never)")))
        f.addRow(tr("Password complexity"), chk("pw_complexity", "At least 3 of: upper case, lower case, digits, symbols"))
        f.addRow(tr("Password history"), spin("pw_history", 0, 24))
        f.addRow("", QLabel(tr("The new password must not equal this number of previous passwords")))
        f.addRow(tr("Password attempts"), spin("max_failed", 1, 20))
        f.addRow("", QLabel(tr("The account is locked after this number of wrong passwords")))
        f.addRow(tr("Account lock time"), spin("lock_minutes", 0, 1440, " min (0 = " + tr("administrator unlocks") + ")"))
        self.addTab(pw, tr("Password policy"))
        sy = QWidget()
        f2 = QFormLayout(sy)
        f2.addRow(tr("Inactivity lock"), spin("session_timeout_min", 0, 240, " min (0 = off)"))
        f2.addRow("", QLabel(tr("The screen is locked after this idle time; the password must be entered again.")))
        f2.addRow(tr("Audit trail"), QLabel(tr("Always on, cannot be disabled (append-only, SHA-256 hash chain).")))
        self.addTab(sy, tr("System policy"))
        es = QWidget()
        f3 = QFormLayout(es)
        f3.addRow(tr("Approval order"), chk("report_requires_review", "Reports must be reviewed before approval"))
        f3.addRow(tr("Signature components"), QLabel(tr("User ID + password re-entered at every signature")))
        f3.addRow(tr("Separation of duties"), QLabel(tr("The performer cannot review or approve the same record")))
        f3.addRow(tr("Signature binding"), QLabel(tr("Bound to the SHA-256 of the record; any change invalidates it")))
        self.addTab(es, tr("Electronic signature"))
        st = QWidget()
        f4 = QVBoxLayout(st)
        f4.addWidget(QLabel(tr("Save the policy settings. Every change is written to the audit trail.")))
        f4.addLayout(_h(_btn(tr("Restore defaults"), "", self.defaults, ok), _btn(tr("Save"), "go", self.save, ok), None))
        f4.addStretch(1)
        self.addTab(st, tr("Settings"))
        for i in range(3):
            w = self.widget(i)
            w.layout().addRow(_h(None, _btn(tr("Save"), "go", self.save, ok)))

    def values(self):
        return {k: (int(w.isChecked()) if isinstance(w, QCheckBox) else w.value()) for k, w in self.sp.items()}

    def defaults(self):
        for k, w in self.sp.items():
            if isinstance(w, QCheckBox):
                w.setChecked(bool(DEFAULT_POLICY[k]))
            else:
                w.setValue(DEFAULT_POLICY[k])

    def save(self):
        if not session.can("policies"):
            return _deny(self)
        ch = session.store.set_policy(session.name(), self.values())
        QMessageBox.information(self, tr("Policy"), tr("Policy saved.") if ch else tr("No changes."))


class SystemPage(Page):
    title = "System"
    language_changed = None

    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.crumb = QLabel()
        self.crumb.setObjectName("crumb")
        self.crumb.setFixedWidth(320)
        lay.addWidget(self.crumb)
        self.stack = QStackedWidget()
        self.stack.setObjectName("page")
        lay.addWidget(self.stack, 1)
        menu = QWidget()
        ml = QVBoxLayout(menu)
        ml.setContentsMargins(20, 20, 20, 20)
        self.subs = {}
        for key, text in (("config", "Configuration"), ("users", "User management"), ("settings", "System settings"),
                          ("policy", "Policy"), ("data", "Data management"), ("about", "About")):
            b = _btn(tr(text), "menu", lambda _=False, k=key: self.open(k))
            b.setFixedWidth(300)
            ml.addWidget(b)
        ml.addStretch(1)
        self.stack.addWidget(menu)
        self.home()

    def home(self):
        self.stack.setCurrentIndex(0)
        self.crumb.setText("›  " + tr("System"))

    def refresh(self):
        self.home()

    def open(self, key):
        names = {"config": "Configuration", "users": "User management", "settings": "System settings",
                 "policy": "Policy", "data": "Data management", "about": "About"}
        w = getattr(self, "_build_" + key)()
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 12, 16, 12)
        back = _btn("‹ " + tr("Back"), "small", self._back)
        bl.addLayout(_h(back, None))
        bl.addWidget(w, 1)
        while self.stack.count() > 1:
            old = self.stack.widget(1)
            self.stack.removeWidget(old)
            old.deleteLater()
        self.stack.addWidget(box)
        self.stack.setCurrentIndex(1)
        self.crumb.setText(f"›  {tr('System')}  ›  {tr(names[key])}")

    def _back(self):
        self.home()

    # --- sub pages
    def _build_config(self):
        w = QWidget()
        f = QFormLayout(w)
        mods = ", ".join(n for c, n in ((MODULE_APSD, "APSD"), (MODULE_PBE, "PBE")) if module_enabled(c))
        f.addRow(tr("Enabled modules"), _wrap(_h(QLabel(mods), _btn(tr("Modules…"), "small", self._modules,
                                                                    session.can("modules")), None)))
        lang = QComboBox()
        for code, name in LANGUAGES.items():
            lang.addItem(name, code)
        lang.setCurrentIndex(max(0, lang.findData(language())))
        lang.currentIndexChanged.connect(lambda *_: self.ws.change_language(lang.currentData()))
        f.addRow(tr("Language"), lang)
        f.addRow(tr("Product"), QLabel(f"{BRAND} {PRODUCT}"))
        return w

    def _modules(self):
        if ModulesDialog(self).exec() == QDialog.Accepted:
            self.ws.rebuild()

    def _build_users(self):
        t = QTabWidget()
        if session.can("manage_users"):
            t.addTab(_embed(UserManagementDialog(self)), tr("Users"))
        else:
            t.addTab(QLabel(tr("Not permitted for your role")), tr("Users"))
        t.addTab(PermissionGroupsWidget(), tr("Permission groups"))
        me = QWidget()
        ml = QVBoxLayout(me)
        u = session.user
        ml.addWidget(QLabel(f"{tr('User')}: <b>{u.username}</b> ({u.full_name}) – {tr(u.role)}"))
        ml.addLayout(_h(_btn(tr("Change Password…"), "", lambda: ChangePasswordDialog(self).exec()), None))
        ml.addStretch(1)
        t.addTab(me, tr("My account"))
        return t

    def _build_settings(self):
        w = QWidget()
        f = QFormLayout(w)
        s = QSettings(*SETTINGS)
        f.addRow(tr("APSD data folder"), QLabel(s.value("data_dir", "", type=str) or "–"))
        f.addRow(tr("PBE data folder"), QLabel(s.value("pbe_dir", "", type=str) or "–"))
        f.addRow(tr("Database / audit trail"), QLabel(session.store.path))
        f.addRow(tr("Clock"), QLabel(tr("Audit records use UTC; lists show local time.")))
        f.addRow(_wrap(_h(_btn(tr("APSD templates and data folder"), "", lambda: SetupDialog(self).exec(),
                                session.can("templates")), None)))
        return w

    def _build_policy(self):
        return PolicyWidget()

    def _build_data(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        ok = session.can("data_management")
        n = len(session.store.record_list())
        lay.addWidget(QLabel(trf("{n} records in the index.", n=n)))
        for text, fn, en in (("Back up database…", lambda: MaintenancePage.backup(self), ok),
                             ("Export audit trail…", self._export_audit, session.can("view_audit")),
                             ("Add existing data files to the list…", self._scan, ok),
                             ("Open database folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir())), ok)):
            b = _btn(tr(text), "menu", fn, en)
            b.setFixedWidth(340)
            lay.addWidget(b)
        lay.addWidget(QLabel(tr("Records are never deleted by the program. Removing an entry from a list keeps the "
                                "file and is written to the audit trail.")))
        lay.addStretch(1)
        return w

    def _export_audit(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export audit trail…"), "labdream_audit_trail.csv", "CSV (*.csv)")
        if path:
            session.store.export_csv(path)
            session.log("AUDIT_EXPORTED", "audit trail", {"file": path})
            QMessageBox.information(self, tr("Audit Trail"), trf("Data exported:\n{path}", path=path))

    def _scan(self):
        d = QFileDialog.getExistingDirectory(self, tr("Add existing data files to the list…"))
        if not d:
            return
        n = 0
        for root, _, files in os.walk(d):
            for fn in files:
                p = os.path.join(root, fn)
                low = fn.lower()
                if session.store.record_by_path(p):
                    continue
                if low.endswith(pbe.PBE_EXT):
                    try:
                        pbe.load(p)
                    except Exception:  # noqa: BLE001
                        continue
                    records.register(records.MOD_PBE, p)
                    n += 1
                elif low.endswith(fileio.NATIVE_EXT):
                    try:
                        ds = fileio.load(p)
                    except Exception:  # noqa: BLE001
                        continue
                    records.register(records.MOD_APSD, p, ds.dev.name)
                    n += 1
        session.log("RECORDS_SCANNED", d, {"added": n})
        QMessageBox.information(self, BRAND, trf("{n} files added to the list.", n=n))

    def _build_about(self):
        p11 = tr("user accounts and permission groups, password policy, hash-chained audit trail, "
                 "electronic signatures")
        w = QLabel(f"<h2>{BRAND} {PRODUCT}</h2><p>{fileio.APP_VERSION}</p>"
                   f"<p>{tr('Inhaler Testing Data Analysis Software')}: APSD (Ph. Eur. 2.9.18 / USP &lt;601&gt;) · "
                   f"PBE (FDA)</p><p>21 CFR Part 11: {p11}</p>")
        w.setWordWrap(True)
        w.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        return w


# ======================================================================
class _IdleFilter(QObject):
    def __init__(self, ws):
        super().__init__()
        self.ws = ws

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel, QEvent.MouseMove):
            self.ws.last_activity = _dt.datetime.now()
        return False


class LockDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Session locked"))
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(trf("The session of {u} was locked after inactivity. Enter the password to continue.",
                                 u=session.name())))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        lay.addWidget(self.pw)
        self.err = QLabel()
        self.err.setStyleSheet("color:#c00")
        lay.addWidget(self.err)
        self.logout = False
        lay.addLayout(_h(_btn(tr("Log Out"), "", self._logout), None, _btn(tr("Unlock"), "primary", self._ok)))
        self.pw.returnPressed.connect(self._ok)

    def _ok(self):
        try:
            session.store.verify_signature(session.name(), self.pw.text())
        except AuthError as e:
            self.err.setText(message(str(e)))
            self.pw.clear()
            if str(e) == "locked":
                self._logout()
            return
        session.log("SESSION_UNLOCKED", session.name(), {})
        self.accept()

    def _logout(self):
        self.logout = True
        self.reject()

    def reject(self):
        self.logout = True
        super().reject()


class Workstation(QMainWindow):
    logout_requested = Signal()
    language_changed = Signal()
    home_requested = Signal()

    NAV = [("start", "▷", "Start"), ("method", "☰", "Method"), ("data", "◔", "Data"), ("report", "▤", "Report"),
           ("audit", "⎙", "Audit"), ("instrument", "⫶", "Instrument"), ("maintenance", "✎", "Maintenance")]

    def __init__(self):
        super().__init__()
        self._leaving = False
        self._logging_out = False
        self.setWindowTitle(f"{BRAND} {PRODUCT} – {fileio.APP_VERSION}")
        self.setStyleSheet(QSS)
        self.last_activity = _dt.datetime.now()
        self._filter = _IdleFilter(self)
        QApplication.instance().installEventFilter(self._filter)
        self.idle = QTimer(self)
        self.idle.timeout.connect(self._check_idle)
        self.idle.start(15000)
        self._locked = False
        self.build()
        self.resize(1280, 800)

    def build(self, page=None):
        root = QWidget()
        root.setObjectName("wsRoot")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(14, 8, 14, 12)
        head = QHBoxLayout()
        logo = QVBoxLayout()
        logo.setSpacing(0)
        b = QLabel(BRAND)
        b.setObjectName("brand")
        p = QLabel(PRODUCT)
        p.setObjectName("product")
        logo.addWidget(b)
        logo.addWidget(p)
        head.addLayout(logo)
        head.addStretch(1)
        u = session.user
        self.user_btn = QToolButton()
        self.user_btn.setText(f"👤 {u.full_name or u.username} ({tr(u.role)})" if u else "")
        self.user_btn.setPopupMode(QToolButton.InstantPopup)
        self.user_btn.setStyleSheet("QToolButton{border:none;color:#2f5d50;font-weight:bold;padding:4px 8px}")
        m = QMenu(self)
        m.addAction(tr("Change Password…"), lambda: ChangePasswordDialog(self).exec())
        lm = m.addMenu(tr("Language"))
        for code, name in LANGUAGES.items():
            a = lm.addAction(name, lambda c=code: self.change_language(c))
            a.setCheckable(True)
            a.setChecked(code == language())
        m.addSeparator()
        m.addAction(tr("Log Out"), self.logout)
        m.addAction(tr("Exit"), self.close)
        self.user_btn.setMenu(m)
        head.addWidget(self.user_btn)
        v.addLayout(head)
        body = QHBoxLayout()
        nav = QFrame()
        nav.setObjectName("nav")
        nav.setFixedWidth(130)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(14, 18, 10, 18)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.nav_btn = {}
        for key, icon, text in self.NAV + [("system", "⚙", "System")]:
            if key == "system":
                nl.addStretch(1)
            t = QToolButton()
            t.setText(f"{icon}  {tr(text)}")
            t.setCheckable(True)
            t.setToolButtonStyle(Qt.ToolButtonTextOnly)
            t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            t.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.group.addButton(t)
            self.nav_btn[key] = t
            nl.addWidget(t)
        body.addWidget(nav)
        self.stack = QStackedWidget()
        self.pages = {"start": StartPage(), "method": MethodPage(), "data": DataPage(), "report": ReportPage(),
                      "audit": AuditPage(), "instrument": InstrumentPage(), "maintenance": MaintenancePage(),
                      "system": SystemPage(self)}
        for k, w in self.pages.items():
            holder = QFrame()
            holder.setObjectName("page" if k not in ("data", "report", "system") else "")
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(w)
            self.stack.addWidget(holder)
            w._holder = holder
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)
        self.nav_btn["audit"].setEnabled(session.can("view_audit"))
        self.show_page(page or QSettings(*SETTINGS).value("ws_page", "data", type=str))

    def show_page(self, key):
        if key not in self.pages or not self.nav_btn[key].isEnabled():
            key = "data"
        self.nav_btn[key].setChecked(True)
        w = self.pages[key]
        self.stack.setCurrentWidget(w._holder)
        w.refresh()
        self.current = key
        QSettings(*SETTINGS).setValue("ws_page", key)

    def rebuild(self):
        self.build(getattr(self, "current", "data"))

    # ------------------------------------------------------------------
    def _check_idle(self):
        mins = policy("session_timeout_min")
        if self._locked or mins <= 0 or session.user is None:
            return
        if _dt.datetime.now() - self.last_activity < _dt.timedelta(minutes=mins):
            return
        self._locked = True
        session.log("SESSION_LOCKED", session.name(), {"idle_minutes": mins})
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible() and w is not self:
                w.hide()
                w._ws_hidden = True
        d = LockDialog(self)
        d.exec()
        self._locked = False
        self.last_activity = _dt.datetime.now()
        if d.logout:
            for w in QApplication.topLevelWidgets():
                if isinstance(w, QDialog) and getattr(w, "_ws_hidden", False):
                    w.done(0)
            self.logout(reason="inactivity")
            return
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and getattr(w, "_ws_hidden", False):
                w._ws_hidden = False
                w.show()

    def change_language(self, code):
        if code == language():
            return
        set_language(code)
        QSettings(*SETTINGS).setValue("language", code)
        session.log("LANGUAGE_CHANGED", code, {})
        self.rebuild()

    def logout(self, reason=None):
        self._logging_out = True
        self.idle.stop()
        session.log("LOGOUT", session.name(), {"reason": reason} if reason else {})
        session.user = None
        self.logout_requested.emit()

    def closeEvent(self, ev):
        ev.accept()
        QApplication.instance().removeEventFilter(self._filter)
        self.idle.stop()
        if self._logging_out or getattr(self, "_rebuilding", False):
            return
        if session.user is not None:
            session.log("LOGOUT", session.name(), {"reason": "exit"})
            session.user = None
        QApplication.quit()
