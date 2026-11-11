"""PBE data processing module: main menu, study editor, electronic signatures.

21 CFR Part 11 controls implemented here (together with security.py):
  11.10(d)  only logged-in users; role permissions (edit / sign / maintenance)
  11.10(e)  audit trail of create / open / save (with reason and every changed
            value) / sign / print / export / import; record metadata
  11.10(c)  SHA-256 file checksum – files altered outside the program are rejected
  11.50     signature manifest: printed name, date/time, meaning – on screen and
            in every report
  11.70     signature bound to the record content hash; any change invalidates it
  11.200    signing requires user ID + password re-entry; failures lock the account
"""
from __future__ import annotations

import copy
import html
import os

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtGui import QPdfWriter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import fileio, pbe, session
from ..i18n import LANGUAGES, language, set_language, tr, trf
from ..pbe_report import PbeReport, g, sig_meaning
from ..security import AuthError
from .dialogs import ok_cancel
from .security_dialogs import AuditTrailDialog, ChangePasswordDialog, UserManagementDialog, message

SETTINGS = ("LabDream", "LabDream")
THETA_CHOICES = [("Guidance (exact)", pbe.THETA_P), ("Excel workbook (rounded)", pbe.THETA_P_WORKBOOK)]


def _num(text):
    t = (text or "").strip().replace(",", ".")
    if not t:
        return None
    return float(t)


# ======================================================================
class DataGrid(QTableWidget):
    """Batch / container / life-stage grid with Excel copy & paste."""
    edited = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.batches = []
        self.m = 1
        self.names = []
        self.readonly = False
        self._loading = False
        self.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.verticalHeader().setDefaultSectionSize(22)
        self.itemChanged.connect(self._changed)

    def load(self, batches, m, names, readonly):
        self._loading = True
        self.batches, self.m, self.names, self.readonly = batches, m, names, readonly
        rows = sum(len(b.containers) for b in batches)
        self.clear()
        self.setColumnCount(2 + m)
        self.setHorizontalHeaderLabels([tr("Batch No."), tr("No.")] +
                                       [trf("Life Stage {n}", n=s + 1) + (f" ({names[s]})" if names[s] else "")
                                        for s in range(m)])
        self.setRowCount(rows)
        self._map = []
        r = 0
        grey = QColor("#f0f0f0")
        for j, b in enumerate(batches):
            for i, c in enumerate(b.containers):
                self._map.append((j, i))
                it = QTableWidgetItem(b.batch_no if i == 0 else "")
                if i != 0 or readonly:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if i != 0:
                    it.setBackground(grey)
                self.setItem(r, 0, it)
                it = QTableWidgetItem(c.no)
                if readonly:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.setItem(r, 1, it)
                for s in range(m):
                    v = c.values[s] if s < len(c.values) else None
                    it = QTableWidgetItem("" if v is None else repr(v))
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if readonly:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    self.setItem(r, 2 + s, it)
                r += 1
        self.resizeColumnsToContents()
        for col in range(2, 2 + m):
            self.setColumnWidth(col, max(self.columnWidth(col), 110))
        self._loading = False

    def _set_cell(self, row, col, text):
        """Store text into the model; returns False if rejected."""
        if row >= len(self._map):
            return False
        j, i = self._map[row]
        b = self.batches[j]
        c = b.containers[i]
        if col == 0:
            if i != 0:
                return False
            b.batch_no = text.strip()
        elif col == 1:
            c.no = text.strip()
        else:
            s = col - 2
            try:
                v = _num(text)
            except ValueError:
                return False
            while len(c.values) < self.m:
                c.values.append(None)
            c.values[s] = v
        return True

    def _changed(self, item):
        if self._loading:
            return
        ok = self._set_cell(item.row(), item.column(), item.text())
        if not ok:
            self._loading = True
            j, i = self._map[item.row()]
            c = self.batches[j].containers[i]
            col = item.column()
            if col >= 2:
                v = c.values[col - 2]
                item.setText("" if v is None else repr(v))
            self._loading = False
            QMessageBox.warning(self, self.title, tr("Please enter a number."))
            return
        if item.column() >= 2:
            self._loading = True
            j, i = self._map[item.row()]
            v = self.batches[j].containers[i].values[item.column() - 2]
            item.setText("" if v is None else repr(v))
            self._loading = False
        self.edited.emit()

    def keyPressEvent(self, ev):
        if ev.matches(QKeySequence.Copy):
            self.copy_selection()
            return
        if ev.matches(QKeySequence.Paste) and not self.readonly:
            self.paste()
            return
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and not self.readonly and self.state() != QAbstractItemView.EditingState:
            for it in self.selectedItems():
                if it.flags() & Qt.ItemIsEditable:
                    it.setText("")
            return
        super().keyPressEvent(ev)

    def copy_selection(self):
        rng = self.selectedRanges()
        if not rng:
            return
        r = rng[0]
        lines = []
        for row in range(r.topRow(), r.bottomRow() + 1):
            lines.append("\t".join((self.item(row, c).text() if self.item(row, c) else "")
                                   for c in range(r.leftColumn(), r.rightColumn() + 1)))
        QApplication.clipboard().setText("\n".join(lines))

    def paste(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        rows = [ln.split("\t") for ln in text.rstrip("\r\n").replace("\r", "").split("\n")]
        r0, c0 = max(0, self.currentRow()), max(0, self.currentColumn())
        bad = 0
        self._loading = True
        try:
            for dr, cells in enumerate(rows):
                for dc, cell in enumerate(cells):
                    r, c = r0 + dr, c0 + dc
                    if r >= self.rowCount() or c >= self.columnCount():
                        continue
                    it = self.item(r, c)
                    if it is None or not (it.flags() & Qt.ItemIsEditable):
                        continue
                    if self._set_cell(r, c, cell):
                        j, i = self._map[r]
                        if c >= 2:
                            v = self.batches[j].containers[i].values[c - 2]
                            it.setText("" if v is None else repr(v))
                        else:
                            it.setText(cell.strip())
                    else:
                        bad += 1
        finally:
            self._loading = False
        self.edited.emit()
        if bad:
            QMessageBox.warning(self, self.title, trf("{n} pasted cells were not numbers and were ignored.", n=bad))


# ======================================================================
class SignDialog(QDialog):
    """21 CFR 11.200: user ID + password, meaning of signature."""

    def __init__(self, st, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Electronic Signature"))
        self.st = st
        self.sig = None
        lay = QVBoxLayout(self)
        info = QLabel(tr("By signing you confirm the data and results of this record. "
                         "Your electronic signature is the legally binding equivalent of your "
                         "handwritten signature (21 CFR Part 11)."))
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.meaning = QComboBox()
        for code, perm in (("performed", "sign_performed"), ("reviewed", "sign_reviewed"),
                           ("approved", "sign_approved")):
            if session.can(perm):
                self.meaning.addItem(sig_meaning(code), code)
        self.user = QLineEdit(session.name())
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.comment = QLineEdit()
        form.addRow(tr("Meaning"), self.meaning)
        form.addRow(tr("User name"), self.user)
        form.addRow(tr("Password"), self.pw)
        form.addRow(tr("Comment"), self.comment)
        lay.addLayout(form)
        lay.addWidget(QLabel(tr("Record SHA-256:") + " " + st.content_hash()[:32] + "…"))
        self.err = QLabel()
        self.err.setStyleSheet("color:#c00")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        lay.addWidget(ok_cancel(self, self._ok, self.reject))
        self.pw.setFocus()
        self.resize(460, 280)

    def _ok(self):
        meaning = self.meaning.currentData()
        if meaning is None:
            self.err.setText(tr("Your role is not permitted to sign."))
            return
        uname = self.user.text().strip()
        if uname.lower() != session.name().lower():
            self.err.setText(tr("You can only sign with your own user account."))
            session.log("SIGNATURE_FAILED", self.st.file_name, {"reason": "different user id", "entered": uname})
            return
        try:
            u = session.store.verify_signature(uname, self.pw.text())
        except AuthError as e:
            self.err.setText(message(str(e)))
            session.log("SIGNATURE_FAILED", self.st.file_name, {"reason": str(e)})
            self.pw.clear()
            if str(e) == "locked":
                self.reject()
            return
        valid = self.st.valid_signatures()
        performers = {s.username.lower() for s in valid if s.meaning == "performed"}
        if meaning in ("reviewed", "approved") and u.username.lower() in performers:
            self.err.setText(tr("The person who performed the analysis cannot also review or approve it."))
            return
        if any(s.username.lower() == u.username.lower() and s.meaning == meaning for s in valid):
            self.err.setText(tr("You have already signed this record with this meaning."))
            return
        self.sig = pbe.Signature(u.username, u.full_name or u.username, meaning, pbe.utc_now(),
                                 self.st.content_hash(), self.comment.text().strip())
        self.accept()


# ======================================================================
class PbeEditor(QDialog):
    def __init__(self, st: pbe.PbeStudy, path=None, parent=None, imported_from=""):
        super().__init__(parent)
        self.st = st
        self.path = path
        self.saved_copy = copy.deepcopy(st) if path else None
        self.modified = bool(imported_from)
        self.readonly = not session.can("edit_data")
        self._warned_signed = False
        self._loading = False
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1200, 800)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_setup(), tr("1  Study Setup"))
        self.tabs.addTab(self._build_data(), tr("2  Data Entry"))
        self.results = QTextBrowser()
        self.results.setOpenExternalLinks(False)
        self.tabs.addTab(self.results, tr("3  PBE Results"))
        self.tabs.addTab(self._build_signatures(), tr("4  Signatures"))
        self.tabs.currentChanged.connect(self._tab)

        bar = QHBoxLayout()
        u = session.user
        mode = tr("Maintenance Mode") if session.can("maintenance") else (
            tr("Operator Mode") if session.can("edit_data") else tr("Read-only Mode"))
        self.status = QLabel(f"{tr('User')}: {u.username if u else '?'} ({tr(u.role) if u else ''})  |  {mode}")
        self.status.setStyleSheet("color:#555")
        bar.addWidget(self.status)
        bar.addStretch(1)
        self.b_save = QPushButton(tr("&Save"))
        self.b_saveas = QPushButton(tr("Save &As…"))
        self.b_print = QPushButton(tr("&Print / PDF…"))
        self.b_export = QPushButton(tr("&Export CSV…"))
        self.b_sign = QPushButton(tr("Sign…"))
        self.b_close = QPushButton(tr("Close"))
        for b in (self.b_save, self.b_saveas, self.b_print, self.b_export, self.b_sign, self.b_close):
            b.setMinimumWidth(96)
            bar.addWidget(b)
        lay.addLayout(bar)
        self.b_save.clicked.connect(self.save)
        self.b_saveas.clicked.connect(self.save_as)
        self.b_print.clicked.connect(self.print_)
        self.b_export.clicked.connect(self.export)
        self.b_sign.clicked.connect(self.sign)
        self.b_close.clicked.connect(self.close)
        self.b_save.setEnabled(not self.readonly)
        self.b_saveas.setEnabled(not self.readonly)
        self.b_print.setEnabled(session.can("print"))
        self.b_export.setEnabled(session.can("export"))
        self.b_sign.setEnabled(any(session.can(p) for p in ("sign_performed", "sign_reviewed", "sign_approved")))
        self.load_setup()
        self.load_data()
        self.refresh_signatures()
        self._title()
        if imported_from:
            session.log("PBE_IMPORTED", os.path.basename(imported_from), {"source": imported_from})

    # ------------------------------------------------------------------ setup tab
    def _build_setup(self):
        w = QWidget()
        outer = QHBoxLayout(w)
        box = QGroupBox(tr("Study Information"))
        f = QFormLayout(box)
        self.e = {}
        for key, label in (("title", "Study title"), ("study_no", "Study No."), ("product", "Product"),
                           ("test_product", "Test product (T)"), ("reference_product", "Reference product (R)"),
                           ("parameter", "Measured parameter"), ("unit", "Unit"), ("method", "Method / SOP")):
            e = QLineEdit()
            e.textEdited.connect(self._setup_changed)
            self.e[key] = e
            f.addRow(tr(label), e)
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(90)
        self.notes.textChanged.connect(self._setup_changed)
        f.addRow(tr("Notes"), self.notes)
        outer.addWidget(box, 3)

        right = QVBoxLayout()
        dbox = QGroupBox(tr("Study Design"))
        gl = QGridLayout(dbox)
        gl.addWidget(QLabel(""), 0, 0)
        gl.addWidget(QLabel(tr("Batches (l)")), 0, 1)
        gl.addWidget(QLabel(tr("Containers per batch (n)")), 0, 2)
        self.sp = {}
        for r, (k, lab) in enumerate((("R", "Reference"), ("T", "Test")), start=1):
            gl.addWidget(QLabel(tr(lab)), r, 0)
            l = QSpinBox(); l.setRange(1, 50)
            n = QSpinBox(); n.setRange(1, 500)
            gl.addWidget(l, r, 1); gl.addWidget(n, r, 2)
            self.sp[k] = (l, n)
        gl.addWidget(QLabel(tr("Life stages per container (m)")), 3, 0, 1, 2)
        self.sp_m = QSpinBox(); self.sp_m.setRange(1, pbe.MAX_STAGES)
        gl.addWidget(self.sp_m, 3, 2)
        gl.addWidget(QLabel(tr("Life stage names")), 4, 0, 1, 3)
        hl = QHBoxLayout()
        self.stage_edits = []
        for s in range(pbe.MAX_STAGES):
            e = QLineEdit(); e.setMaximumWidth(60)
            e.textEdited.connect(self._setup_changed)
            self.stage_edits.append(e); hl.addWidget(e)
        gl.addLayout(hl, 5, 0, 1, 3)
        self.b_apply = QPushButton(tr("Apply Design"))
        self.b_apply.setToolTip(tr("Rebuild the data tables with this design. Existing values are kept."))
        self.b_apply.clicked.connect(self.apply_design)
        gl.addWidget(self.b_apply, 6, 2)
        hint = QLabel(tr("Guidance example: 3 batches × 10 containers × 3 life stages (B / M / E). "
                         "Nebulizer data have one life stage."))
        hint.setWordWrap(True); hint.setStyleSheet("color:#666")
        gl.addWidget(hint, 7, 0, 1, 3)
        right.addWidget(dbox)

        cbox = QGroupBox(tr("Statistical Constants (FDA guidance)"))
        cf = QFormLayout(cbox)
        self.ln = QCheckBox(tr("ln-transform the measured values (recommended)"))
        self.ln.toggled.connect(self._setup_changed)
        cf.addRow(self.ln)
        self.theta = QComboBox()
        for lab, v in THETA_CHOICES:
            self.theta.addItem(f"{tr(lab)}  θp = {g(v, 6)}", v)
        self.theta.addItem(tr("Custom value"), None)
        self.theta_custom = QDoubleSpinBox(); self.theta_custom.setDecimals(6); self.theta_custom.setRange(0, 100)
        self.theta.currentIndexChanged.connect(self._theta_mode)
        self.theta_custom.valueChanged.connect(self._setup_changed)
        th = QHBoxLayout(); th.addWidget(self.theta, 1); th.addWidget(self.theta_custom)
        cf.addRow("θp", th)
        self.s0 = QDoubleSpinBox(); self.s0.setDecimals(4); self.s0.setRange(0.0001, 10); self.s0.setSingleStep(0.01)
        self.alpha = QDoubleSpinBox(); self.alpha.setDecimals(4); self.alpha.setRange(0.0001, 0.4999); self.alpha.setSingleStep(0.01)
        self.s0.valueChanged.connect(self._setup_changed)
        self.alpha.valueChanged.connect(self._setup_changed)
        cf.addRow("σT0", self.s0)
        cf.addRow("α", self.alpha)
        txt = QLabel(tr("θp = ((ln 1.11)² + 0.01) / σT0² ;  reference-scaled if σR > σT0, otherwise "
                        "constant-scaled ;  PBE passes if the 95% upper confidence bound Hη ≤ 0. "
                        "Only administrators (maintenance mode) can change the constants."))
        txt.setWordWrap(True); txt.setStyleSheet("color:#666")
        cf.addRow(txt)
        right.addWidget(cbox)
        right.addStretch(1)
        outer.addLayout(right, 2)
        return w

    def _theta_mode(self, *_):
        custom = self.theta.currentData() is None
        self.theta_custom.setVisible(custom)
        self._setup_changed()

    def load_setup(self):
        st = self.st
        self._loading = True
        for k, e in self.e.items():
            e.setText(getattr(st, k))
            e.setReadOnly(self.readonly)
        self.notes.setPlainText(st.notes)
        self.notes.setReadOnly(self.readonly)
        self.sp["R"][0].setValue(len(st.reference)); self.sp["R"][1].setValue(len(st.reference[0].containers) if st.reference else 10)
        self.sp["T"][0].setValue(len(st.test)); self.sp["T"][1].setValue(len(st.test[0].containers) if st.test else 10)
        self.sp_m.setValue(st.m)
        names = (st.stage_names + [""] * pbe.MAX_STAGES)[:pbe.MAX_STAGES]
        for e, n in zip(self.stage_edits, names):
            e.setText(n); e.setReadOnly(self.readonly)
        for w in (self.sp["R"][0], self.sp["R"][1], self.sp["T"][0], self.sp["T"][1], self.sp_m, self.b_apply, self.ln):
            w.setEnabled(not self.readonly)
        self.ln.setChecked(st.ln_transform)
        idx = next((i for i, (_, v) in enumerate(THETA_CHOICES) if abs(v - st.theta_p) < 1e-12), len(THETA_CHOICES))
        self.theta.setCurrentIndex(idx)
        self.theta_custom.setValue(st.theta_p)
        self.theta_custom.setVisible(idx == len(THETA_CHOICES))
        self.s0.setValue(st.sigma_t0)
        self.alpha.setValue(st.alpha)
        maint = session.can("maintenance") and not self.readonly
        for w in (self.theta, self.theta_custom, self.s0, self.alpha):
            w.setEnabled(maint)
        self._loading = False

    def store_setup(self):
        st = self.st
        for k, e in self.e.items():
            setattr(st, k, e.text())
        st.notes = self.notes.toPlainText()
        names = [e.text().strip() for e in self.stage_edits]
        st.stage_names = names
        st.ln_transform = self.ln.isChecked()
        v = self.theta.currentData()
        st.theta_p = float(v) if v is not None else float(self.theta_custom.value())
        st.sigma_t0 = float(self.s0.value())
        st.alpha = float(self.alpha.value())

    def _setup_changed(self, *_):
        if self._loading or self.readonly:
            return
        self.store_setup()
        self._mark()

    def apply_design(self):
        st = self.st
        lR, nR = self.sp["R"][0].value(), self.sp["R"][1].value()
        lT, nT = self.sp["T"][0].value(), self.sp["T"][1].value()
        m = self.sp_m.value()
        lost = 0
        for batches, l, n in ((st.reference, lR, nR), (st.test, lT, nT)):
            for j, b in enumerate(batches):
                for i, c in enumerate(b.containers):
                    for s, v in enumerate(c.values):
                        if v is not None and (j >= l or i >= n or s >= m):
                            lost += 1
        if lost and QMessageBox.question(
                self, tr("Apply Design"),
                trf("{n} entered values are outside the new design and will be removed. Continue?", n=lost)) \
                != QMessageBox.Yes:
            return
        st.reference = pbe.make_batches(lR, nR, m, old=st.reference)
        st.test = pbe.make_batches(lT, nT, m, old=st.test)
        st.m = m
        self.store_setup()
        self.load_data()
        self._mark()

    # ------------------------------------------------------------------ data tab
    def _build_data(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        hint = QLabel(tr("Enter or paste (Ctrl+V) the measured values from Excel. One row per container; "
                         "enter the batch number in the first row of each batch."))
        hint.setWordWrap(True)
        h.addWidget(hint, 1)
        self.b_imp_csv = QPushButton(tr("Import CSV (Table 1 format)…"))
        self.b_imp_xls = QPushButton(tr("Import Excel workbook…"))
        self.b_imp_csv.clicked.connect(lambda: self.import_into("csv"))
        self.b_imp_xls.clicked.connect(lambda: self.import_into("xlsx"))
        for b in (self.b_imp_csv, self.b_imp_xls):
            b.setEnabled(not self.readonly)
            h.addWidget(b)
        v.addLayout(h)
        sp = QSplitter()
        self.grids = {}
        for k, lab in (("R", "Reference"), ("T", "Test")):
            box = QGroupBox(tr(lab))
            bl = QVBoxLayout(box)
            grid = DataGrid(tr(lab))
            grid.edited.connect(self._mark)
            bl.addWidget(grid)
            self.grids[k] = grid
            sp.addWidget(box)
        v.addWidget(sp, 1)
        return w

    def load_data(self):
        st = self.st
        names = (st.stage_names + [""] * pbe.MAX_STAGES)[:st.m]
        self.grids["R"].load(st.reference, st.m, names, self.readonly)
        self.grids["T"].load(st.test, st.m, names, self.readonly)

    def import_into(self, kind):
        s = QSettings(*SETTINGS)
        start = s.value("pbe_dir", "", type=str)
        flt = "CSV (*.csv *.txt)" if kind == "csv" else "Excel (*.xlsx *.xlsm)"
        path, _ = QFileDialog.getOpenFileName(self, tr("Import"), start, flt)
        if not path:
            return
        try:
            if kind == "csv":
                ref, test, m, names = pbe.parse_long_table(pbe.read_csv_rows(path))
            else:
                ref, test, m = pbe.import_workbook(path)
                names = None
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Import"), f"{tr('Could not import the file:')}\n{tr(str(e))}")
            return
        if any(v is not None for b in self.st.reference + self.st.test for c in b.containers for v in c.values):
            if QMessageBox.question(self, tr("Import"), tr("Replace the data currently entered?")) != QMessageBox.Yes:
                return
        st = self.st
        st.reference, st.test, st.m = ref, test, m
        if names:
            st.stage_names = (list(names) + st.stage_names[len(names):])[:pbe.MAX_STAGES]
        self.load_setup()
        self.load_data()
        self._mark()
        session.log("PBE_IMPORTED", st.file_name or tr("(new file)"), {"source": path, "m": m,
                    "reference_batches": len(ref), "test_batches": len(test)})

    # ------------------------------------------------------------------ results
    def _tab(self, i):
        if i == 2:
            self.show_results()
        elif i == 3:
            self.refresh_signatures()

    def show_results(self):
        st = self.st
        try:
            res = pbe.compute(st)
        except pbe.PbeError as e:
            self.results.setHtml(f"<h2>{tr('PBE Results')}</h2><p style='color:#b00'><b>"
                                 f"{html.escape(tr('PBE cannot be calculated:'))}</b> {html.escape(tr(str(e)))}</p>")
            return
        e = html.escape
        gm = tr("Geometric mean") if st.ln_transform else tr("Mean")
        ok = res.passed
        color = "#1b7a1b" if ok else "#b00000"
        verdict = tr("PBE PASSED – the test product is bioequivalent to the reference product.") if ok \
            else tr("PBE FAILED – bioequivalence is not demonstrated.")
        crit = tr("reference-scaled") if res.scaling == "reference" else tr("constant-scaled")
        cmp_ = "&gt;" if res.scaling == "reference" else "&le;"
        css = ("<style>table{border-collapse:collapse;margin:4px 0 12px 0} td,th{border:1px solid #aaa;"
               "padding:3px 8px} th{background:#e6ecf5} td.n{text-align:right;font-family:Menlo,Consolas,monospace}</style>")
        h = [css, f"<h2>{e(tr('PBE Results'))} – {e(st.parameter or '')}</h2>",
             f"<p style='font-size:15px;color:{color}'><b>{e(verdict)}</b><br>"
             f"σR = {g(res.ref.sigma)} {cmp_} σT0 = {g(st.sigma_t0)} → {e(crit)}; "
             f"Hη = {g(res.applied.h_eta)}</p>"]
        h.append(f"<h3>{e(tr('Summary of PBE results'))}</h3><table><tr><th>{e(tr('Variable'))}</th>"
                 f"<th>{e(gm)} {e(tr('Test'))}</th><th>{e(gm)} {e(tr('Reference'))}</th>"
                 f"<th>{e(tr('Geometric Mean Ratio') if st.ln_transform else tr('Mean Ratio'))}</th>"
                 f"<th>σT</th><th>σR</th><th>σT/σR</th></tr>"
                 f"<tr><td>{e(st.parameter or '—')}</td><td class=n>{g(res.test.geo_mean, 5)}</td>"
                 f"<td class=n>{g(res.ref.geo_mean, 5)}</td><td class=n>{g(res.gmr, 5)}</td>"
                 f"<td class=n>{g(res.test.sigma)}</td><td class=n>{g(res.ref.sigma)}</td>"
                 f"<td class=n>{g(res.sigma_ratio, 5)}</td></tr></table>")
        h.append(f"<table><tr><th>{e(tr('Criterion'))}</th><th>{e(tr('Applicable'))}</th>"
                 f"<th>{e(tr('Scaled linearized point estimate'))}</th><th>{e(tr('95% upper confidence bound'))}</th>"
                 f"<th>{e(tr('Pass or Fail PBE'))}</th></tr>")
        for c in (res.reference_scaled, res.constant_scaled):
            pf = (tr("Pass") if c.passed else tr("Fail")) if c.applies else "--"
            h.append(f"<tr><td>{e(tr('Reference-scaled') if c.name == 'reference' else tr('Constant-scaled'))}</td>"
                     f"<td>{e(tr('Yes') if c.applies else tr('Not applicable'))}</td><td class=n>{g(c.eq)}</td>"
                     f"<td class=n>{g(c.h_eta)}</td><td><b>{e(pf)}</b></td></tr>")
        h.append("</table>")
        h.append(f"<h3>{e(tr('Intermediate values'))}</h3><table><tr><th></th><th>l</th><th>n</th><th>m</th>"
                 f"<th>X̄</th><th>MSB</th><th>MSW</th><th>σ</th></tr>")
        for lab, p in ((tr("Reference"), res.ref), (tr("Test"), res.test)):
            h.append(f"<tr><td>{e(lab)}</td><td class=n>{p.l}</td><td class=n>{p.n}</td><td class=n>{p.m}</td>"
                     f"<td class=n>{g(p.mean, 7)}</td><td class=n>{g(p.msb)}</td><td class=n>{g(p.msw)}</td>"
                     f"<td class=n>{g(p.sigma)}</td></tr>")
        h.append("</table>")
        chi = " ; ".join(f"χ²<sub>{k}</sub> = {g(v)}" for k, v in res.chi2.items())
        h.append(f"<p>Δ = X̄T − X̄R = {g(res.delta, 7)} ; t(1−α, {res.df_t}) = {g(res.t_value)} ; {chi} ; "
                 f"θp = {g(st.theta_p)} ; σT0 = {g(st.sigma_t0)} ; α = {g(st.alpha)}</p>")
        h.append("<table><tr>")
        for c in (res.reference_scaled, res.constant_scaled):
            sfx = "s" if c.name == "reference" else "c"
            title = tr("Reference-scaled criterion") if c.name == "reference" else tr("Constant-scaled criterion")
            h.append(f"<td style='border:none;vertical-align:top'><b>{e(title)}</b><table>"
                     "<tr><th>q</th><th>Eq</th><th>Hq</th><th>Uq=(Hq−Eq)²</th></tr>")
            for k, lab in (("D", "D"), ("1", "1"), ("2", "2"), ("3", "3" + sfx), ("4", "4" + sfx)):
                h.append(f"<tr><td>{lab}</td><td class=n>{g(c.E[k])}</td><td class=n>{g(c.H[k])}</td>"
                         f"<td class=n>{g(c.U[k])}</td></tr>")
            off = f" − θp·σT0²" if c.name == "constant" else ""
            h.append(f"<tr><td>Σ</td><td class=n>Eq{off} = {g(c.eq)}</td><td class=n>Hη = {g(c.h_eta)}</td>"
                     f"<td class=n>{g(c.uq)}</td></tr></table></td>")
        h.append("</tr></table>")
        if st.m == 1:
            h.append(f"<p style='color:#666'>{e(tr('m = 1: E2 / E4 and their H and U terms are ignored (guidance).'))}</p>")
        self.results.setHtml("".join(h))

    # ------------------------------------------------------------------ signatures
    def _build_signatures(self):
        w = QWidget()
        v = QVBoxLayout(w)
        lab = QLabel(tr("Signatures are linked to the SHA-256 hash of the record content. Any change to "
                        "the data or settings after signing invalidates the signature; the record must then "
                        "be signed again."))
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.sig_table = QTableWidget(0, 6)
        self.sig_table.setHorizontalHeaderLabels([tr("Meaning"), tr("Printed name"), tr("User ID"),
                                                  tr("Date / time (UTC)"), tr("Comment"), tr("Status")])
        self.sig_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sig_table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.sig_table, 1)
        self.meta = QLabel()
        self.meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.meta)
        return w

    def refresh_signatures(self):
        st = self.st
        h = st.content_hash()
        self.sig_table.setRowCount(len(st.signatures))
        for i, s in enumerate(st.signatures):
            okk = s.record_hash == h
            vals = [sig_meaning(s.meaning), s.full_name, s.username, s.timestamp, s.comment,
                    tr("valid") if okk else tr("INVALID – data changed after signing")]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if not okk:
                    it.setForeground(QColor("#b00000"))
                self.sig_table.setItem(i, j, it)
        self.sig_table.resizeColumnsToContents()
        self.meta.setText(f"{tr('File')}: {st.file_name or tr('(new file)')}   {tr('Revision')}: {st.revision}   "
                          f"{tr('Created')}: {st.created_by} {st.created_at}   {tr('Last modified')}: "
                          f"{st.modified_by} {st.modified_at}\nSHA-256: {h}")

    def sign(self):
        self.store_setup()
        if self.modified or not self.path:
            QMessageBox.information(self, tr("Electronic Signature"),
                                    tr("Save the record before signing it."))
            if not self.save():
                return
        try:
            pbe.compute(self.st)
        except pbe.PbeError as e:
            QMessageBox.warning(self, tr("Electronic Signature"),
                                tr("PBE cannot be calculated:") + "\n" + tr(str(e)))
            return
        d = SignDialog(self.st, self)
        if d.exec() != QDialog.Accepted or d.sig is None:
            return
        s = d.sig
        self.st.signatures.append(s)
        self.st.revision += 1
        pbe.save(self.st, self.path)
        self.saved_copy = copy.deepcopy(self.st)
        session.log("E_SIGNATURE", os.path.basename(self.path),
                    {"meaning": s.meaning, "full_name": s.full_name, "record_sha256": s.record_hash,
                     "comment": s.comment, "revision": self.st.revision})
        self.refresh_signatures()
        self._title()
        QMessageBox.information(self, tr("Electronic Signature"),
                                trf("Signed as '{m}' by {n} at {t}.", m=sig_meaning(s.meaning), n=s.full_name, t=s.timestamp))

    # ------------------------------------------------------------------ save
    def _mark(self):
        if self._loading:
            return
        if not self._warned_signed and self.st.signatures and self.saved_copy is not None \
                and self.saved_copy.valid_signatures():
            self._warned_signed = True
            QMessageBox.warning(self, tr("Electronic Signature"),
                                tr("This record is signed. Changing it invalidates the existing signatures; "
                                   "it will have to be signed again."))
        self.modified = True
        self._title()

    def _title(self):
        name = self.st.file_name or tr("(new file)")
        self.setWindowTitle(f"{tr('PBE Data Processing')} – {name}{' *' if self.modified else ''}  –  {fileio.APP_VERSION}")

    def _reason(self):
        if self.saved_copy is None or not pbe.diff_studies(self.saved_copy, self.st):
            return ""
        text, ok = QInputDialog.getText(self, tr("Reason for Change"),
                                        tr("Enter the reason for changing this data file:"))
        if not ok:
            return None
        if not text.strip():
            QMessageBox.warning(self, tr("Reason for Change"), tr("A reason for change is required."))
            return None
        return text.strip()

    def _write(self, path, reason=""):
        st = self.st
        changes = pbe.diff_studies(self.saved_copy, st) if self.saved_copy is not None else []
        invalidated = len(self.saved_copy.valid_signatures()) - len(st.valid_signatures()) \
            if self.saved_copy is not None else 0
        now = pbe.utc_now()
        if not st.created_by:
            st.created_by, st.created_at = session.name(), now
        st.modified_by, st.modified_at = session.name(), now
        st.revision += 1
        pbe.save(st, path)
        details = {"path": path, "revision": st.revision, "module": "PBE", "record_sha256": st.content_hash()}
        if reason:
            details["reason"] = reason
        if changes:
            details["changes"] = changes[:500]
            if len(changes) > 500:
                details["more_changes"] = len(changes) - 500
        if invalidated > 0:
            details["signatures_invalidated"] = invalidated
        try:
            r = pbe.compute(st)
            details["result"] = f"{r.scaling}-scaled, Hη={r.applied.h_eta:.6g}, {'PASS' if r.passed else 'FAIL'}"
        except pbe.PbeError as e:
            details["result"] = f"not calculable: {e}"
        session.log("FILE_SAVED" if self.saved_copy is not None else "FILE_CREATED", os.path.basename(path), details)
        self.saved_copy = copy.deepcopy(st)
        self.path = path
        self.modified = False
        self._title()
        self.refresh_signatures()

    def save(self):
        if self.readonly:
            return False
        self.store_setup()
        if not self.path:
            return self.save_as()
        reason = self._reason()
        if reason is None:
            return False
        self._write(self.path, reason)
        return True

    def save_as(self):
        if self.readonly:
            return False
        self.store_setup()
        s = QSettings(*SETTINGS)
        start = s.value("pbe_dir", "", type=str)
        base = os.path.splitext(self.st.file_name or (self.st.study_no or "pbe_study"))[0] + pbe.PBE_EXT
        path, _ = QFileDialog.getSaveFileName(self, tr("Save As"), os.path.join(start, base),
                                              f"{tr('PBE study')} (*{pbe.PBE_EXT})")
        if not path:
            return False
        if not path.lower().endswith(pbe.PBE_EXT):
            path += pbe.PBE_EXT
        if self.path and os.path.abspath(path) != os.path.abspath(self.path):
            # new record derived from an existing one: signatures do not carry over
            if self.st.signatures:
                self.st.signatures = []
            self.saved_copy = None
            self.st.created_by = self.st.created_at = ""
            self.st.revision = 0
            reason = ""
        else:
            reason = self._reason()
            if reason is None:
                return False
        s.setValue("pbe_dir", os.path.dirname(path))
        self._write(path, reason)
        return True

    # ------------------------------------------------------------------ output
    def print_(self):
        self.store_setup()
        rep = PbeReport(self.st, printed_by=session.name())
        r = QMessageBox.question(self, tr("Print"), tr("Save the report as PDF? (No = print preview)"),
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return
        if r == QMessageBox.Yes:
            base = os.path.splitext(self.st.file_name or "pbe_report")[0]
            path, _ = QFileDialog.getSaveFileName(self, tr("Save report as PDF"), base + ".pdf", "PDF (*.pdf)")
            if not path:
                return
            w = QPdfWriter(path)
            w.setResolution(300)
            w.setTitle(f"{fileio.APP_VERSION} PBE report")
            w.setCreator(fileio.APP_VERSION)
            rep.render(w)
            del w
            session.log("REPORT_PDF", self.st.file_name or tr("(new file)"),
                        {"module": "PBE", "pdf": os.path.basename(path), "record_sha256": self.st.content_hash(),
                         "unsaved_changes": self.modified})
            QMessageBox.information(self, tr("Print"), trf("Report saved:\n{path}", path=path))
            return
        printer = QPrinter(QPrinter.HighResolution)
        prev = QPrintPreviewDialog(printer, self)
        prev.setWindowTitle(f"{fileio.APP_VERSION} – {tr('Print Preview')}")
        prev.paintRequested.connect(rep.render)
        prev.resize(1000, 800)
        prev.exec()
        session.log("REPORT_PRINTED", self.st.file_name or tr("(new file)"),
                    {"module": "PBE", "record_sha256": self.st.content_hash(), "unsaved_changes": self.modified})

    def export(self):
        self.store_setup()
        base = os.path.splitext(self.st.file_name or "pbe_study")[0]
        path, _ = QFileDialog.getSaveFileName(self, tr("Export"), base + ".csv", "CSV (*.csv)")
        if path:
            pbe.export_csv(self.st, path, fileio.APP_VERSION)
            session.log("FILE_EXPORTED", self.st.file_name or tr("(new file)"),
                        {"module": "PBE", "csv": os.path.basename(path), "record_sha256": self.st.content_hash()})
            QMessageBox.information(self, tr("Export"), trf("Data exported:\n{path}", path=path))

    def closeEvent(self, ev):
        if self.modified and not self.readonly:
            r = QMessageBox.question(self, fileio.APP_NAME, tr("Save changes to the data file?"),
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                ev.ignore(); return
            if r == QMessageBox.Yes and not self.save():
                ev.ignore(); return
            if r == QMessageBox.No:
                session.log("CHANGES_DISCARDED", self.st.file_name or tr("(new file)"), {"module": "PBE"})
        session.log("FILE_CLOSED", self.st.file_name or tr("(new file)"), {"module": "PBE"})
        ev.accept()


# ======================================================================
class PbeMainWindow(QMainWindow):
    """Main menu of the PBE module."""
    logout_requested = Signal()
    language_changed = Signal()
    home_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{fileio.APP_VERSION} – {tr('PBE Data Processing')}")
        self.settings = QSettings(*SETTINGS)
        w = QWidget()
        self.setCentralWidget(w)
        lay = QHBoxLayout(w)
        art = QLabel("PBE")
        art.setAlignment(Qt.AlignCenter)
        art.setFixedWidth(200)
        art.setFont(QFont("Arial", 44, QFont.Bold))
        art.setStyleSheet("color:white;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #2a6f97,stop:1 #1b3f5c);"
                          "border-radius:12px")
        lay.addWidget(art)
        col = QVBoxLayout()
        title = QLabel(tr("PBE Data Processing Software"))
        title.setFont(QFont("Arial", 24, QFont.Bold))
        title.setStyleSheet("color:#1f4fa8")
        col.addWidget(title)
        sub = QLabel(tr("Population bioequivalence of in-vitro tests (FDA Budesonide inhalation suspension "
                        "guidance, PBE statistical procedure). 21 CFR Part 11 compliant records."))
        sub.setWordWrap(True)
        col.addWidget(sub)
        ver = QLabel(fileio.APP_VERSION)
        ver.setStyleSheet("color:#666")
        col.addWidget(ver)
        col.addSpacing(16)
        buttons = [(tr("&New PBE Study"), self.new_study, session.can("edit_data")),
                   (tr("&Open PBE Study"), self.open_study, True),
                   (tr("New Study from &Import (CSV / Excel)…"), self.new_from_import, session.can("edit_data")),
                   (tr("&User Management"), self.users, session.can("manage_users")),
                   (tr("&Audit Trail"), self.audit, session.can("view_audit")),
                   (tr("Switch &Module"), self.go_home, True),
                   (tr("E&xit"), self.close, True)]
        for text, fn, enabled in buttons:
            b = QPushButton(text)
            b.setMinimumHeight(36)
            b.setFont(QFont("Arial", 12))
            b.clicked.connect(fn)
            b.setEnabled(enabled)
            if not enabled:
                b.setToolTip(tr("Not permitted for your role"))
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.resize(780, 560)
        u = session.user
        self.statusBar().showMessage(f"{tr('User')}: {u.username} ({u.full_name}) – {tr(u.role)}" if u else "")
        m = self.menuBar().addMenu(tr("&File"))
        self._act(m, tr("New…"), self.new_study, "Ctrl+N", session.can("edit_data"))
        self._act(m, tr("Open…"), self.open_study, "Ctrl+O")
        m.addSeparator()
        self._act(m, tr("Switch Module"), self.go_home)
        self._act(m, tr("Log Out"), self.logout)
        self._act(m, tr("Exit"), self.close, "Ctrl+Q")
        um = self.menuBar().addMenu(tr("&Users"))
        self._act(um, tr("Change Password…"), lambda: ChangePasswordDialog(self).exec())
        self._act(um, tr("User Management…"), self.users, None, session.can("manage_users"))
        self._act(um, tr("Audit Trail…"), self.audit, None, session.can("view_audit"))
        t = self.menuBar().addMenu(tr("&Tools"))
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
        self._leaving = False

    def _act(self, menu, text, fn, shortcut=None, enabled=True):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(fn)
        a.setEnabled(enabled)
        menu.addAction(a)
        return a

    def new_study(self):
        if not session.can("edit_data"):
            return
        st = pbe.new_study(3, 10, 3, 10, 1)
        session.log("FILE_NEW", "PBE", {"module": "PBE"})
        PbeEditor(st, None, self).exec()

    def new_from_import(self):
        if not session.can("edit_data"):
            return
        start = self.settings.value("pbe_dir", "", type=str)
        path, _ = QFileDialog.getOpenFileName(self, tr("Import"), start,
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
            QMessageBox.critical(self, tr("Import"), f"{tr('Could not import the file:')}\n{tr(str(e))}")
            return
        st = pbe.PbeStudy(m=m, reference=ref, test=test)
        if names:
            st.stage_names = (list(names) + st.stage_names[len(names):])[:pbe.MAX_STAGES]
        st.title = os.path.splitext(os.path.basename(path))[0]
        session.log("FILE_NEW", "PBE", {"module": "PBE", "import": path})
        PbeEditor(st, None, self, imported_from=path).exec()

    def open_study(self):
        start = self.settings.value("pbe_dir", "", type=str)
        path, _ = QFileDialog.getOpenFileName(self, tr("Open Data File"), start,
                                              f"{tr('PBE study')} (*{pbe.PBE_EXT});;* (*)")
        if not path:
            return
        try:
            st = pbe.load(path)
        except Exception as e:  # noqa: BLE001
            session.log("FILE_OPEN_FAILED", os.path.basename(path), {"path": path, "error": str(e), "module": "PBE"})
            QMessageBox.critical(self, tr("Open"), f"{tr('Could not open file:')}\n{tr(str(e))}")
            return
        self.settings.setValue("pbe_dir", os.path.dirname(path))
        session.log("FILE_OPENED", os.path.basename(path), {"path": path, "revision": st.revision, "module": "PBE",
                                                            "record_sha256": st.content_hash()})
        PbeEditor(st, path, self).exec()

    def users(self):
        if session.can("manage_users"):
            UserManagementDialog(self).exec()

    def audit(self):
        if session.can("view_audit"):
            AuditTrailDialog(self).exec()

    def change_language(self, code):
        if code == language():
            return
        set_language(code)
        self.settings.setValue("language", code)
        session.log("LANGUAGE_CHANGED", code, {})
        self.language_changed.emit()

    def go_home(self):
        self._leaving = True
        self.home_requested.emit()

    def logout(self):
        self._leaving = True
        session.log("LOGOUT", session.name(), {})
        session.user = None
        self.logout_requested.emit()

    def closeEvent(self, ev):
        ev.accept()
        if self._leaving or getattr(self, "_rebuilding", False):
            return
        if session.user is not None:
            session.log("LOGOUT", session.name(), {"reason": "exit"})
            session.user = None
        QApplication.quit()

    def about(self):
        QMessageBox.about(self, tr("About LabDream"),
                          f"<b>{fileio.APP_VERSION}</b><br>{tr('PBE Data Processing Software')}<br><br>"
                          + tr("Population bioequivalence of in-vitro tests (FDA Budesonide inhalation suspension "
                               "guidance, PBE statistical procedure). 21 CFR Part 11 compliant records."))
