"""The three data screens: User Setup, Deposition Data, Results Summary."""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont, QColor, QPageLayout
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtGui import QPdfWriter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
                               QHeaderView, QAbstractItemView, QScrollArea)

from .. import fileio, reports
from ..devices import MAX_RUNS
from ..engine import analyse, mean_sd_rsd, NA
from ..model import HEADING_LABELS, new_dataset
from .dialogs import GroupResultsDialog, GroupSpecDialog, PrintDialog
from .widgets import ChartWidget, DevicePicture, NumEdit, f5, parse_float

RUN_WORDS = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
             "Eleven", "Twelve"]
SCREEN_TITLES = ["User Setup", "Deposition Data", "Results Summary"]


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


# ======================================================================
class SetupScreen(QWidget):
    """Screen 1 of 3."""

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        lay = QHBoxLayout(self)
        # stage titles + calibration ----------------------------------
        sbox = QGroupBox("Stage Title                    Calibration")
        sg = QGridLayout(sbox)
        self.title_edits = []
        self.ecd_edits = []
        ds = wiz.ds
        self.cal = NumEdit(0, decimals=2)
        for r in range(ds.n_rows):
            e = QLineEdit()
            e.setFixedWidth(100)
            self.title_edits.append(e)
            sg.addWidget(e, r, 0)
            if r == 0:
                sg.addWidget(QLabel("Flow Rate (L/min)"), r, 1, Qt.AlignHCenter)
            elif r == 1:
                sg.addWidget(self.cal, r, 1)
            elif r == 2:
                sg.addWidget(QLabel("Stage ECD"), r, 1, Qt.AlignHCenter | Qt.AlignBottom)
            else:
                ecd = NumEdit(0)
                self.ecd_edits.append(ecd)
                sg.addWidget(ecd, r, 1)
        sg.setRowStretch(ds.n_rows, 1)
        lay.addWidget(sbox)
        # info pairs -----------------------------------------------------
        right = QVBoxLayout()
        grid = QGridLayout()
        self.info_lab = []
        self.info_val = []
        for i, (lab, val) in enumerate(ds.info):
            le = QLineEdit()
            le.setFixedWidth(170)
            ve = QLineEdit()
            ve.setMinimumWidth(170)
            if lab in HEADING_LABELS:
                le.setStyleSheet("color: #1f4fa8;")
                ve.setVisible(False)
            grid.addWidget(le, i, 0)
            grid.addWidget(ve, i, 1)
            self.info_lab.append(le)
            self.info_val.append(ve)
        right.addLayout(grid)
        obox = QGroupBox("Other Information")
        ol = QVBoxLayout(obox)
        self.other = QLineEdit()
        ol.addWidget(self.other)
        right.addWidget(obox)
        right.addStretch(1)
        lay.addLayout(right, 1)
        btns = QVBoxLayout()
        for text, fn in (("&Reset", self.reset), ("&Save", wiz.save), ("Save &As", wiz.save_as)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

    def load(self):
        ds = self.wiz.ds
        for r, e in enumerate(self.title_edits):
            e.setText(ds.row_titles[r])
            e.setVisible(ds.row_active(r) or (r == 2 and ds.dev.has_presep))
            if r == 2 and not ds.dev.has_presep:
                e.setVisible(False)
        self.cal.set_value(ds.cal_flow)
        for k, e in enumerate(self.ecd_edits):
            e.set_value(ds.ecd[k])
            e.setEnabled(k < len(self.ecd_edits) - 1)
        for i, (lab, val) in enumerate(ds.info):
            self.info_lab[i].setText(lab)
            self.info_val[i].setText(val)
        self.other.setText(ds.other_info)

    def store(self):
        ds = self.wiz.ds
        ds.row_titles = [e.text() for e in self.title_edits]
        ds.cal_flow = self.cal.value()
        ds.ecd = [e.value() for e in self.ecd_edits]
        ds.ecd[-1] = 0.0
        ds.info = [[self.info_lab[i].text(), self.info_val[i].text()] for i in range(len(ds.info))]
        ds.other_info = self.other.text()

    def reset(self):
        ds = self.wiz.ds
        dev = ds.dev
        ds.row_titles = list(dev.row_titles)
        ds.cal_flow = dev.default_cal_flow
        ds.ecd = list(dev.default_ecd)
        self.load()


# ======================================================================
class DepositionScreen(QWidget):
    """Screen 2 of 3."""

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self._loading = False
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        box = QGroupBox("Deposition Data")
        bl = QVBoxLayout(box)
        self.table = QTableWidget()
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self._changed)
        bl.addWidget(self.table)
        bl.addWidget(QLabel("* as determined during testing for uniformity of delivered dose."))
        left.addWidget(box)
        lay.addLayout(left, 1)

        side = QVBoxLayout()
        nb = QGroupBox("Number of Runs")
        nl = QHBoxLayout(nb)
        self.nruns = QComboBox()
        self.nruns.addItems(RUN_WORDS)
        self.nruns.currentIndexChanged.connect(self._nruns)
        nl.addWidget(self.nruns)
        nl.addWidget(QLabel("Scroll right to view mean\nvalues, SD and RSD[%]"))
        side.addWidget(nb)

        row = QHBoxLayout()
        ub = QGroupBox("Unit Mass")
        ul = QVBoxLayout(ub)
        self.mg = QRadioButton("mg")
        self.ug = QRadioButton("µg")
        ul.addWidget(self.mg); ul.addWidget(self.ug)
        self.ug.toggled.connect(self._opts)
        row.addWidget(ub)
        self.pb = QGroupBox("Preseparator")
        pl = QVBoxLayout(self.pb)
        self.ps_show = QRadioButton("Show")
        self.ps_hide = QRadioButton("Hide")
        pl.addWidget(self.ps_show); pl.addWidget(self.ps_hide)
        self.ps_show.toggled.connect(self._opts)
        row.addWidget(self.pb)
        side.addLayout(row)

        row2 = QHBoxLayout()
        fb = QGroupBox("Fine Particle Dose Spec.")
        fl = QGridLayout(fb)
        self.fpd_stage_rb = QRadioButton()
        self.fpd_stage = QComboBox()
        self.fpd_size_rb = QRadioButton("Less than or equal to")
        self.fpd_size = NumEdit(5.0)
        grp = QPushButton("Group")
        grp.clicked.connect(self._groups)
        fl.addWidget(self.fpd_stage_rb, 0, 0)
        fl.addWidget(self.fpd_stage, 0, 1)
        self.to_filter = QLabel("to Filter")
        fl.addWidget(self.to_filter, 0, 2)
        fl.addWidget(self.fpd_size_rb, 1, 0, 1, 3)
        h = QHBoxLayout(); h.addWidget(self.fpd_size); h.addWidget(QLabel("µm")); h.addWidget(grp)
        fl.addLayout(h, 2, 0, 1, 3)
        bgf = QButtonGroup(fb)
        bgf.addButton(self.fpd_stage_rb); bgf.addButton(self.fpd_size_rb)
        self.fpd_stage_rb.toggled.connect(self._opts)
        self.fpd_stage.currentIndexChanged.connect(self._opts)
        self.fpd_size.valueChanged.connect(self._opts)
        row2.addWidget(fb)
        self.hb = QGroupBox("High Flow Rates\n>= 60 L/min")
        hl = QVBoxLayout(self.hb)
        self.remove = QCheckBox("Remove\nStages")
        self.s6 = QCheckBox("Stage 6")
        self.s7 = QCheckBox("Stage 7")
        for w in (self.remove, self.s6, self.s7):
            hl.addWidget(w)
            w.toggled.connect(self._opts)
        row2.addWidget(self.hb)
        side.addLayout(row2)

        rb = QGroupBox()
        rl = QVBoxLayout(rb)
        rl.addWidget(QLabel("Probit Range 4 - 6\nParticle Size Distributions are assumed to be\n"
                            "Log-Normal if Log-Probit graphs have a\nregression Coefficient, R², greater than:"))
        self.r2 = NumEdit(0.95)
        self.r2.valueChanged.connect(self._opts)
        rl.addWidget(self.r2, 0, Qt.AlignHCenter)
        rl.addWidget(QLabel("GSD will be reported as \"NA\" for particle\nsize distributions which are not Log-Normal."))
        side.addWidget(rb)
        side.addStretch(1)
        bh = QHBoxLayout()
        for text, fn in (("&Reset", self.reset), ("&Save", wiz.save), ("Save &As", wiz.save_as)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bh.addWidget(b)
        side.addLayout(bh)
        lay.addLayout(side)

    # ------------------------------------------------------------------
    def row_map(self):
        """Table row -> (kind, data row index)."""
        ds = self.wiz.ds
        m = [("dose_no", None)]
        for r in range(ds.n_rows):
            if ds.row_active(r):
                m.append(("mass", r))
        m += [("flow", None), ("doses", None), ("delivered", None), ("total", None)]
        return m

    def load(self):
        ds = self.wiz.ds
        self._loading = True
        self.nruns.setCurrentIndex(ds.n_runs - 1)
        self.mg.setChecked(ds.unit_mg); self.ug.setChecked(not ds.unit_mg)
        self.pb.setVisible(ds.dev.has_presep)
        self.ps_show.setChecked(ds.show_presep); self.ps_hide.setChecked(not ds.show_presep)
        self.fpd_stage.clear()
        for r in range(3, ds.n_rows - 1):
            self.fpd_stage.addItem(ds.row_titles[r], r)
        self.fpd_stage.setCurrentIndex(max(0, self.fpd_stage.findData(ds.fpd_stage_row)))
        self.to_filter.setText(f"to {ds.row_titles[-1]}")
        self.fpd_stage_rb.setChecked(ds.fpd_by_stage)
        self.fpd_size_rb.setChecked(not ds.fpd_by_stage)
        self.fpd_size.set_value(ds.fpd_size)
        self.hb.setVisible(ds.dev.supports_remove_stages)
        self.remove.setChecked(ds.remove_stage6 or ds.remove_stage7)
        self.s6.setChecked(ds.remove_stage6)
        self.s7.setChecked(ds.remove_stage7)
        self.r2.set_value(ds.r2_limit)
        self._loading = False
        self._enable()
        self.fill_table()

    def _enable(self):
        self.fpd_stage.setEnabled(self.fpd_stage_rb.isChecked())
        self.fpd_size.setEnabled(self.fpd_size_rb.isChecked())
        self.s6.setEnabled(self.remove.isChecked())
        self.s7.setEnabled(self.remove.isChecked())

    def fill_table(self):
        ds = self.wiz.ds
        self._loading = True
        rows = self.row_map()
        n = ds.n_runs
        t = self.table
        t.clear()
        t.setRowCount(len(rows))
        t.setColumnCount(n + 3)
        t.setHorizontalHeaderLabels([f"Run {i+1}" for i in range(n)] + ["Mean", "SD", "RSD[%]"])
        u = ds.unit
        labels = []
        for kind, r in rows:
            labels.append({"dose_no": "Dose No.", "flow": "Flow (L/min)",
                           "doses": f"Doses to {ds.device}", "delivered": "Delivered Dose*",
                           "total": "Total Dose Per Shot"}.get(kind) or ds.row_titles[r])
        t.setVerticalHeaderLabels(labels)
        for i, (kind, r) in enumerate(rows):
            vals = []
            for j in range(n):
                run = ds.runs[j]
                if kind == "dose_no":
                    txt = run.dose_no
                elif kind == "mass":
                    vals.append(run.masses[r]); txt = f5(run.masses[r])
                elif kind == "flow":
                    vals.append(run.flow); txt = f"{run.flow:.2f}"
                elif kind == "doses":
                    vals.append(run.doses); txt = f"{run.doses:g}"
                elif kind == "delivered":
                    vals.append(run.delivered); txt = f5(run.delivered)
                else:
                    tot = sum(run.masses[q] for q in range(ds.n_rows) if ds.row_active(q)) / (run.doses or 1)
                    vals.append(tot); txt = f5(tot)
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if kind == "total":
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    it.setBackground(QColor(240, 240, 240))
                t.setItem(i, j, it)
            st = mean_sd_rsd(vals) if kind != "dose_no" else ("", "", "")
            for k, v in enumerate(st):
                it = QTableWidgetItem(f5(v) if v != "" else "")
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setBackground(QColor(240, 240, 240))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(i, n + k, it)
        t.resizeColumnsToContents()
        for c in range(n + 3):
            t.setColumnWidth(c, max(t.columnWidth(c), 90))
        self._loading = False

    def _changed(self, item):
        if self._loading:
            return
        ds = self.wiz.ds
        i, j = item.row(), item.column()
        if j >= ds.n_runs:
            return
        kind, r = self.row_map()[i]
        run = ds.runs[j]
        if kind == "dose_no":
            run.dose_no = item.text()
        elif kind == "mass":
            run.masses[r] = parse_float(item.text())
        elif kind == "flow":
            run.flow = parse_float(item.text(), ds.cal_flow)
        elif kind == "doses":
            run.doses = parse_float(item.text(), 1.0) or 1.0
        elif kind == "delivered":
            run.delivered = parse_float(item.text())
        self.wiz.modified = True
        self.fill_table()
        self.table.setCurrentCell(min(i + 1, self.table.rowCount() - 1), j)

    def _nruns(self, idx):
        if self._loading:
            return
        self.wiz.ds.n_runs = idx + 1
        self.wiz.modified = True
        self.fill_table()

    def _opts(self, *_):
        if self._loading:
            return
        ds = self.wiz.ds
        ds.unit_mg = self.mg.isChecked()
        ds.show_presep = self.ps_show.isChecked() if ds.dev.has_presep else False
        ds.fpd_by_stage = self.fpd_stage_rb.isChecked()
        if self.fpd_stage.currentData() is not None:
            ds.fpd_stage_row = self.fpd_stage.currentData()
        ds.fpd_size = self.fpd_size.value()
        rem = self.remove.isChecked()
        ds.remove_stage6 = rem and self.s6.isChecked()
        ds.remove_stage7 = rem and self.s7.isChecked()
        ds.r2_limit = self.r2.value()
        self.wiz.modified = True
        self._enable()
        self.fill_table()

    def _groups(self):
        GroupSpecDialog(self.wiz.ds, self).exec()

    def reset(self):
        ds = self.wiz.ds
        if QMessageBox.question(self, "Reset", "Clear all deposition data?") != QMessageBox.Yes:
            return
        for run in ds.runs:
            run.masses = [0.0] * ds.n_rows
            run.flow = ds.cal_flow
            run.doses = 1.0
            run.delivered = 0.0
            run.dose_no = ""
        self.load()


# ======================================================================
class ResultsScreen(QWidget):
    """Screen 3 of 3."""

    ROWS = [("sw_mean", "Shot Weight Mean [mg]"), ("sw_sd", "Shot Weight Standard Deviation [mg]"),
            ("total", "Total Dose Per Shot"), ("delivered", "Calc. Delivered Dose"),
            ("fpd", "Fine Particle Dose"), ("fpf", "Fine Particle Fraction [%]"),
            ("mmad", "MMAD [µm]"), ("gsd", "GSD"), ("r2", "R²"), ("flow", "Flow Rate [L/min]")]

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.summary = None
        self._loading = False
        lay = QHBoxLayout(self)
        gcol = QVBoxLayout()
        self.charts = [ChartWidget() for _ in range(3)]
        for c in self.charts:
            gcol.addWidget(c)
        lay.addLayout(gcol, 1)
        right = QVBoxLayout()
        self.sw = QCheckBox("Report Shot Weight")
        self.sw.toggled.connect(self._sw)
        right.addWidget(self.sw)
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._changed)
        self.table.horizontalScrollBar().valueChanged.connect(lambda *_: self.update_charts())
        self.table.currentCellChanged.connect(lambda *_: self.update_charts())
        right.addWidget(self.table, 1)
        h = QHBoxLayout()
        gb = QPushButton("Group Results")
        gb.clicked.connect(self._group_results)
        h.addWidget(gb)
        h.addStretch(1)
        right.addLayout(h)
        bot = QHBoxLayout()
        fb = QGroupBox("FPD Specification")
        fl = QVBoxLayout(fb)
        self.spec = QLabel()
        fl.addWidget(self.spec)
        bh = QHBoxLayout()
        for text, fn in (("Save", wiz.save), ("Save &As", wiz.save_as), ("Print", self.print_),
                         ("&Export", self.export)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bh.addWidget(b)
        fl.addLayout(bh)
        bot.addWidget(fb, 1)
        vb = QGroupBox("View Graph")
        vl = QGridLayout(vb)
        self.v_probit = QRadioButton("Probit")
        self.v_dep = QRadioButton("Deposition")
        self.v_cum = QRadioButton("Cumulative")
        self.v_probit.setChecked(True)
        self.throat = QCheckBox("Show\nThroat")
        self.throat.setChecked(True)
        vl.addWidget(self.v_probit, 0, 0); vl.addWidget(self.v_dep, 1, 0); vl.addWidget(self.v_cum, 2, 0)
        vl.addWidget(self.throat, 1, 1)
        for w in (self.v_probit, self.v_dep, self.v_cum, self.throat):
            w.toggled.connect(lambda *_: self.update_charts())
        bot.addWidget(vb)
        right.addLayout(bot)
        lay.addLayout(right, 2)

    def load(self):
        ds = self.wiz.ds
        self._loading = True
        self.sw.setChecked(ds.report_shot_weight)
        if ds.fpd_by_stage:
            self.spec.setText(f"{ds.row_titles[ds.fpd_stage_row]} to {ds.row_titles[-1]}")
        else:
            self.spec.setText(f"Less than or Equal to {ds.fpd_size:.5f} µm")
        self._loading = False
        self.refresh()

    def refresh(self):
        ds = self.wiz.ds
        self.summary = analyse(ds)
        runs = self.summary.runs
        n = len(runs)
        self._loading = True
        t = self.table
        t.clear()
        t.setRowCount(len(self.ROWS))
        t.setColumnCount(n + 3)
        t.setHorizontalHeaderLabels([f"Run {i+1}" for i in range(n)] + ["Mean/dose", "SD/dose", "%RSD/dose"])
        u = ds.unit
        labels = []
        for key, lab in self.ROWS:
            if key in ("total", "delivered", "fpd"):
                lab = f"{lab} [{u}]"
            labels.append(lab)
        t.setVerticalHeaderLabels(labels)
        get = {"sw_mean": lambda r: ds.runs[r.run - 1].shot_weight_mean,
               "sw_sd": lambda r: ds.runs[r.run - 1].shot_weight_sd,
               "total": lambda r: r.total, "delivered": lambda r: r.delivered_calc,
               "fpd": lambda r: r.fpd, "fpf": lambda r: r.fpf, "mmad": lambda r: r.mmad,
               "gsd": lambda r: r.gsd, "r2": lambda r: r.r2, "flow": lambda r: r.flow}
        for i, (key, _) in enumerate(self.ROWS):
            vals = [get[key](r) for r in runs]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(f"{v:.2f}" if key == "flow" else f5(v))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not key.startswith("sw"):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(i, j, it)
            st = mean_sd_rsd([v for v in vals if isinstance(v, (int, float))])
            for k, v in enumerate(st):
                it = QTableWidgetItem(f5(v))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setBackground(QColor(240, 240, 240))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(i, n + k, it)
            t.setRowHidden(i, key.startswith("sw") and not ds.report_shot_weight)
        t.resizeColumnsToContents()
        for c in range(n + 3):
            t.setColumnWidth(c, max(t.columnWidth(c), 90))
        self._loading = False
        self.update_charts()

    def visible_runs(self):
        t = self.table
        n = len(self.summary.runs) if self.summary else 0
        first = t.columnAt(0)
        if first < 0:
            first = 0
        cur = t.currentColumn()
        if 0 <= cur < n and not (first <= cur < first + 3):
            first = cur
        first = max(0, min(first, max(0, n - 3)))
        return list(range(first, min(n, first + 3)))

    def update_charts(self):
        if not self.summary:
            return
        ds = self.wiz.ds
        kind = (ChartWidget.PROBIT if self.v_probit.isChecked() else
                ChartWidget.DEPOSITION if self.v_dep.isChecked() else ChartWidget.CUMULATIVE)
        vis = self.visible_runs()
        for k, c in enumerate(self.charts):
            if k < len(vis):
                res = self.summary.runs[vis[k]]
                c.setVisible(True)
                c.set_data(ds, res, kind, self.throat.isChecked(), title=f"Run {res.run}")
            else:
                c.setVisible(False)

    def _sw(self, on):
        if self._loading:
            return
        self.wiz.ds.report_shot_weight = on
        self.wiz.modified = True
        self.refresh()

    def _changed(self, item):
        if self._loading:
            return
        ds = self.wiz.ds
        key = self.ROWS[item.row()][0]
        j = item.column()
        if j >= ds.n_runs:
            return
        if key == "sw_mean":
            ds.runs[j].shot_weight_mean = parse_float(item.text())
        elif key == "sw_sd":
            ds.runs[j].shot_weight_sd = parse_float(item.text())
        self.wiz.modified = True
        self.refresh()

    def _group_results(self):
        GroupResultsDialog(self.wiz.ds, self.summary, self).exec()

    def print_(self):
        ds = self.wiz.ds
        dlg = PrintDialog(ds.n_runs, self)
        if dlg.exec() != QDialog.Accepted:
            return
        sel = dlg.selections()
        if not sel:
            return
        rr = reports.ReportRenderer(ds, sel)
        if dlg.to_pdf:
            base = os.path.splitext(ds.file_name or "report")[0]
            path, _ = QFileDialog.getSaveFileName(self, "Save report as PDF", base + ".pdf", "PDF (*.pdf)")
            if not path:
                return
            w = QPdfWriter(path)
            w.setResolution(300)
            w.setTitle(f"{fileio.APP_VERSION} report")
            rr.render(w)
            QMessageBox.information(self, "Print", f"Report saved:\n{path}")
            return
        printer = QPrinter(QPrinter.HighResolution)
        prev = QPrintPreviewDialog(printer, self)
        prev.setWindowTitle(f"{fileio.APP_VERSION} – Print Preview")
        prev.paintRequested.connect(rr.render)
        prev.resize(1000, 800)
        prev.exec()

    def export(self):
        ds = self.wiz.ds
        base = os.path.splitext(ds.file_name or "data")[0]
        path, _ = QFileDialog.getSaveFileName(self, "Export", base + ".csv", "CSV (*.csv)")
        if path:
            fileio.export_csv(ds, path)
            QMessageBox.information(self, "Export", f"Data exported:\n{path}")


# ======================================================================
class DataWizard(QDialog):
    def __init__(self, ds, path=None, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.path = path
        self.modified = False
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1180, 760)
        outer = QVBoxLayout(self)
        body = QHBoxLayout()
        self.pic = DevicePicture(ds.device)
        body.addWidget(self.pic)
        self.stack = QStackedWidget()
        self.screens = [SetupScreen(self), DepositionScreen(self), ResultsScreen(self)]
        for s in self.screens:
            self.stack.addWidget(s)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        outer.addWidget(_hline())
        nav = QHBoxLayout()
        nav.addStretch(1)
        self.back = QPushButton("< &Back")
        self.next = QPushButton("&Next >")
        self.cancel = QPushButton("Cancel")
        self.help = QPushButton("Help")
        for b in (self.back, self.next, self.cancel, self.help):
            b.setMinimumWidth(90)
            nav.addWidget(b)
        outer.addLayout(nav)
        self.back.clicked.connect(lambda: self.go(-1))
        self.next.clicked.connect(lambda: self.go(+1))
        self.cancel.clicked.connect(self.close)
        self.help.clicked.connect(self.show_help)
        self.screens[0].load()
        self.set_page(0)

    def set_page(self, i):
        self.stack.setCurrentIndex(i)
        self.back.setEnabled(i > 0)
        self.next.setText("&Finish" if i == 2 else "&Next >")
        title = SCREEN_TITLES[i]
        if i == 2:
            self.setWindowTitle(f"Shot Weight Input & Results Summary [ Screen 3 of 3 ]  –  {fileio.APP_VERSION}")
        else:
            self.setWindowTitle(f"{self.ds.dev.name} - {title} [ Screen {i+1} of 3 ]  –  {fileio.APP_VERSION}")

    def store_current(self):
        if self.stack.currentIndex() == 0:
            self.screens[0].store()

    def go(self, step):
        i = self.stack.currentIndex()
        self.store_current()
        j = i + step
        if j > 2:
            self.close()
            return
        j = max(0, j)
        self.screens[j].load()
        self.set_page(j)

    # ------------------------------------------------------------------
    def save(self):
        self.store_current()
        if not self.path or self.path.lower().endswith(".cpl"):
            return self.save_as()
        fileio.save(self.ds, self.path)
        self.modified = False
        return True

    def save_as(self):
        self.store_current()
        s = QSettings("LabDream", "LabDream")
        start = s.value("data_dir", "", type=str)
        base = os.path.splitext(self.ds.file_name or "untitled")[0] + fileio.NATIVE_EXT
        path, _ = QFileDialog.getSaveFileName(self, "Save As", os.path.join(start, base),
                                              f"LabDream data (*{fileio.NATIVE_EXT})")
        if not path:
            return False
        if not path.lower().endswith(fileio.NATIVE_EXT):
            path += fileio.NATIVE_EXT
        fileio.save(self.ds, path)
        self.path = path
        self.modified = False
        return True

    def closeEvent(self, ev):
        if self.modified:
            r = QMessageBox.question(self, fileio.APP_NAME, "Save changes to the data file?",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                ev.ignore(); return
            if r == QMessageBox.Yes and not self.save():
                ev.ignore(); return
        ev.accept()

    def show_help(self):
        i = self.stack.currentIndex()
        texts = [
            "Screen 1 – User Setup\n\nEnter stage titles, calibration flow rate and the stage "
            "cut-off diameters (ECD) at that flow rate, together with the analysis and sample details.",
            "Screen 2 – Deposition Data\n\nEnter the mass of drug recovered from each location for "
            "every run, the sampling flow rate, the number of doses and (optionally) the delivered dose "
            "from the uniformity of delivered dose test.\n\nFPD can be specified by size (default "
            "≤ 5 µm) or by stage. Up to five groups can be defined with the Group button.",
            "Screen 3 – Results Summary\n\nMMAD, GSD, FPD and FPF are calculated by log-probit "
            "interpolation of the cumulative % undersize. GSD is reported only when R² of the "
            "probit 4–6 regression exceeds the limit.\n\nLOD: FPD by size when the cumulative mass is "
            "< 2 % or fewer than three stages hold > 1 %.\nNA: MMAD/GSD when > 50 % of the mass is on "
            "the filter or top stage, or fewer than three stages hold > 1 %.",
        ]
        QMessageBox.information(self, "Help", texts[i])
