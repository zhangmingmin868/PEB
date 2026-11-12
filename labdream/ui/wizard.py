"""The three data screens: User Setup, Deposition Data, Results Summary."""
from __future__ import annotations

import copy
import datetime as _dt
import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QPdfWriter
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QRadioButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import fileio, reports, session
from ..devices import factory_ecd
from ..engine import analyse, mean_sd_rsd, NA
from ..i18n import tr, trf
from ..model import HEADING_LABELS, diff_datasets
from .dialogs import GroupResultsDialog, GroupSpecDialog, PrintDialog
from .widgets import ChartWidget, DevicePicture, NumEdit, f5, parse_float

RUN_WORDS = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
             "Eleven", "Twelve"]


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def _readonly(item):
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    item.setBackground(QColor(240, 240, 240))


# ======================================================================
class SetupScreen(QWidget):
    """Screen 1 of 3."""

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self._loading = False
        ds = wiz.ds
        lay = QHBoxLayout(self)
        sbox = QGroupBox(tr("Stage Title") + "   /   " + tr("Calibration"))
        sg = QGridLayout(sbox)
        self.title_edits = []
        self.ecd_edits = []
        self.cal = NumEdit(0, decimals=2)
        self.cal.valueChanged.connect(self.on_cal_flow)
        for r in range(ds.n_rows):
            e = QLineEdit()
            e.setFixedWidth(100)
            self.title_edits.append(e)
            sg.addWidget(e, r, 0)
            if r == 0:
                sg.addWidget(QLabel(tr("Flow Rate (L/min)")), r, 1, Qt.AlignHCenter)
            elif r == 1:
                sg.addWidget(self.cal, r, 1)
            elif r == 2:
                sg.addWidget(QLabel(tr("Stage ECD (µm)")), r, 1, Qt.AlignHCenter | Qt.AlignBottom)
            else:
                ecd = NumEdit(0)
                self.ecd_edits.append(ecd)
                sg.addWidget(ecd, r, 1)
        self.factory = QPushButton(tr("Default ECD"))
        self.factory.setToolTip(tr("Set the stage ECDs to the manufacturer values at this flow rate"))
        self.factory.clicked.connect(self.reset_ecd)
        sg.addWidget(self.factory, ds.n_rows, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#666")
        sg.addWidget(self.note, ds.n_rows + 1, 0, 1, 2)
        sg.setRowStretch(ds.n_rows + 2, 1)
        lay.addWidget(sbox)

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
        obox = QGroupBox(tr("Other Information"))
        ol = QVBoxLayout(obox)
        self.other = QLineEdit()
        ol.addWidget(self.other)
        right.addWidget(obox)
        right.addStretch(1)
        lay.addLayout(right, 1)
        btns = QVBoxLayout()
        self.btn_reset = QPushButton(tr("&Reset"))
        self.btn_reset.clicked.connect(self.reset)
        btns.addWidget(self.btn_reset)
        for text, fn in ((tr("&Save"), wiz.save), (tr("Save &As"), wiz.save_as)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            b.setEnabled(session.can("edit_data"))
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

    def load(self):
        ds = self.wiz.ds
        self._loading = True
        edit = session.can("edit_data")
        maint = session.can("maintenance")
        for r, e in enumerate(self.title_edits):
            e.setText(tr(ds.row_titles[r]))
            e.setProperty('orig', ds.row_titles[r])
            e.setVisible(not (r == 2 and not ds.dev.has_presep))
            e.setReadOnly(not maint)
        self.cal.set_value(ds.cal_flow)
        self.cal.setReadOnly(not edit)
        for k, e in enumerate(self.ecd_edits):
            e.set_value(ds.ecd[k])
            last = k == len(self.ecd_edits) - 1
            e.setEnabled(not last)
            e.setReadOnly(not maint)
        self.factory.setEnabled(edit)
        self.btn_reset.setEnabled(maint)
        for i, (lab, val) in enumerate(ds.info):
            self.info_lab[i].setText(tr(lab))
            self.info_lab[i].setProperty('orig', lab)
            self.info_lab[i].setReadOnly(not maint)
            self.info_val[i].setText(val)
            self.info_val[i].setReadOnly(not edit)
        self.other.setText(ds.other_info)
        self.other.setReadOnly(not edit)
        self.note.setText(tr("ECDs follow the flow rate automatically (Ph. Eur. 2.9.18 / USP <601>).")
                          + ("" if maint else " " + tr("Only an administrator can edit stage titles and ECDs.")))
        self._loading = False

    def store(self):
        ds = self.wiz.ds
        ds.row_titles = [self._orig(e) for e in self.title_edits]
        ds.cal_flow = self.cal.value()
        ds.ecd = [e.value() for e in self.ecd_edits]
        ds.ecd[-1] = 0.0
        ds.info = [[self._orig(self.info_lab[i]), self.info_val[i].text()] for i in range(len(ds.info))]
        ds.other_info = self.other.text()

    @staticmethod
    def _orig(edit):
        """Keep the stored (English) text when the translated text was not edited."""
        orig = edit.property('orig')
        return orig if orig is not None and edit.text() == tr(orig) else edit.text()

    def on_cal_flow(self, flow):
        """New calibration flow rate -> stage ECDs and run flow rates follow."""
        if self._loading:
            return
        ds = self.wiz.ds
        if flow <= 0:
            self.cal.set_value(ds.cal_flow)
            return
        old = ds.cal_flow
        if abs(flow - old) < 1e-9:
            return
        new_ecd = factory_ecd(ds.dev, flow)
        for e, v in zip(self.ecd_edits, new_ecd):
            e.set_value(v)
        ds.cal_flow = flow
        ds.ecd = list(new_ecd)
        for run in ds.runs:                     # runs still at the old default follow
            if abs(run.flow - old) < 1e-9 or run.flow <= 0:
                run.flow = flow
        self.wiz.modified = True
        session.log("FLOW_RATE_CHANGED", ds.file_name or tr("(new file)"),
                    {"from": old, "to": flow, "ecd": [round(x, 5) for x in new_ecd]})

    def reset_ecd(self):
        ds = self.wiz.ds
        flow = self.cal.value()
        for e, v in zip(self.ecd_edits, factory_ecd(ds.dev, flow)):
            e.set_value(v)
        self.wiz.modified = True

    def reset(self):
        ds = self.wiz.ds
        dev = ds.dev
        ds.row_titles = list(dev.row_titles)
        ds.cal_flow = dev.default_cal_flow
        ds.ecd = list(dev.default_ecd)
        self.wiz.modified = True
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
        box = QGroupBox(tr("Deposition Data"))
        bl = QVBoxLayout(box)
        self.table = QTableWidget()
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self._changed)
        bl.addWidget(self.table)
        bl.addWidget(QLabel(tr("* as determined during testing for uniformity of delivered dose.")))
        left.addWidget(box)
        lay.addLayout(left, 1)

        side = QVBoxLayout()
        nb = QGroupBox(tr("Number of Runs"))
        nl = QHBoxLayout(nb)
        self.nruns = QComboBox()
        self.nruns.addItems([tr(w) for w in RUN_WORDS])
        self.nruns.currentIndexChanged.connect(self._nruns)
        nl.addWidget(self.nruns)
        nl.addWidget(QLabel(tr("Scroll right to view mean\nvalues, SD and RSD[%]")))
        side.addWidget(nb)

        row = QHBoxLayout()
        ub = QGroupBox(tr("Unit Mass"))
        ul = QVBoxLayout(ub)
        self.mg = QRadioButton("mg")
        self.ug = QRadioButton("µg")
        ul.addWidget(self.mg); ul.addWidget(self.ug)
        self.ug.toggled.connect(self._opts)
        row.addWidget(ub)
        self.pb = QGroupBox(tr("Preseparator"))
        pl = QVBoxLayout(self.pb)
        self.ps_show = QRadioButton(tr("Show"))
        self.ps_hide = QRadioButton(tr("Hide"))
        pl.addWidget(self.ps_show); pl.addWidget(self.ps_hide)
        self.ps_show.toggled.connect(self._opts)
        row.addWidget(self.pb)
        side.addLayout(row)

        row2 = QHBoxLayout()
        fb = QGroupBox(tr("Fine Particle Dose Spec."))
        fl = QGridLayout(fb)
        self.fpd_stage_rb = QRadioButton()
        self.fpd_stage = QComboBox()
        self.fpd_size_rb = QRadioButton(tr("Less than or equal to"))
        self.fpd_size = NumEdit(5.0)
        self.grp = QPushButton(tr("Group"))
        self.grp.clicked.connect(self._groups)
        fl.addWidget(self.fpd_stage_rb, 0, 0)
        fl.addWidget(self.fpd_stage, 0, 1)
        self.to_filter = QLabel()
        fl.addWidget(self.to_filter, 0, 2)
        fl.addWidget(self.fpd_size_rb, 1, 0, 1, 3)
        h = QHBoxLayout(); h.addWidget(self.fpd_size); h.addWidget(QLabel("µm")); h.addWidget(self.grp)
        fl.addLayout(h, 2, 0, 1, 3)
        bgf = QButtonGroup(fb)
        bgf.addButton(self.fpd_stage_rb); bgf.addButton(self.fpd_size_rb)
        self.fpd_stage_rb.toggled.connect(self._opts)
        self.fpd_stage.currentIndexChanged.connect(self._opts)
        self.fpd_size.valueChanged.connect(self._opts)
        row2.addWidget(fb)
        self.hb = QGroupBox(tr("High Flow Rates\n>= 60 L/min"))
        hl = QVBoxLayout(self.hb)
        self.remove = QCheckBox(tr("Remove\nStages"))
        self.s6 = QCheckBox(tr("Stage 6"))
        self.s7 = QCheckBox(tr("Stage 7"))
        for w in (self.remove, self.s6, self.s7):
            hl.addWidget(w)
            w.toggled.connect(self._opts)
        row2.addWidget(self.hb)
        side.addLayout(row2)

        rb = QGroupBox()
        rl = QVBoxLayout(rb)
        lab = QLabel(tr("Probit Range 4 - 6\nParticle Size Distributions are assumed to be\n"
                        "Log-Normal if Log-Probit graphs have a\nregression Coefficient, R², greater than:"))
        lab.setWordWrap(True)
        rl.addWidget(lab)
        self.r2 = NumEdit(0.95)
        self.r2.valueChanged.connect(self._opts)
        rl.addWidget(self.r2, 0, Qt.AlignHCenter)
        lab2 = QLabel(tr("GSD will be reported as \"NA\" for particle\nsize distributions which are not Log-Normal."))
        lab2.setWordWrap(True)
        rl.addWidget(lab2)
        side.addWidget(rb)
        side.addStretch(1)
        bh = QHBoxLayout()
        self.btns = []
        for text, fn in ((tr("&Reset"), self.reset), (tr("&Save"), wiz.save), (tr("Save &As"), wiz.save_as)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bh.addWidget(b)
            self.btns.append(b)
        side.addLayout(bh)
        lay.addLayout(side)

    # ------------------------------------------------------------------
    def row_map(self):
        ds = self.wiz.ds
        m = [("dose_no", None)]
        for r in range(ds.n_rows):
            if ds.row_active(r):
                m.append(("mass", r))
        m += [("flow", None), ("doses", None), ("delivered", None), ("total", None)]
        return m

    def load(self):
        ds = self.wiz.ds
        edit = session.can("edit_data")
        self._loading = True
        self.nruns.setCurrentIndex(ds.n_runs - 1)
        self.mg.setChecked(ds.unit_mg); self.ug.setChecked(not ds.unit_mg)
        self.pb.setVisible(ds.dev.has_presep)
        self.ps_show.setChecked(ds.show_presep); self.ps_hide.setChecked(not ds.show_presep)
        self.fpd_stage.clear()
        for r in range(3, ds.n_rows - 1):
            self.fpd_stage.addItem(tr(ds.row_titles[r]), r)
        self.fpd_stage.setCurrentIndex(max(0, self.fpd_stage.findData(ds.fpd_stage_row)))
        self.to_filter.setText(trf("to {name}", name=tr(ds.row_titles[-1])))
        self.fpd_stage_rb.setChecked(ds.fpd_by_stage)
        self.fpd_size_rb.setChecked(not ds.fpd_by_stage)
        self.fpd_size.set_value(ds.fpd_size)
        self.hb.setVisible(ds.dev.supports_remove_stages)
        self.remove.setChecked(ds.remove_stage6 or ds.remove_stage7)
        self.s6.setChecked(ds.remove_stage6)
        self.s7.setChecked(ds.remove_stage7)
        self.r2.set_value(ds.r2_limit)
        for w in (self.nruns, self.mg, self.ug, self.ps_show, self.ps_hide, self.fpd_stage_rb,
                  self.fpd_size_rb, self.remove, self.s6, self.s7):
            w.setEnabled(edit)
        self.fpd_size.setReadOnly(not edit)
        self.r2.setReadOnly(not session.can("maintenance") and not edit)
        for b in self.btns:
            b.setEnabled(edit)
        self._loading = False
        self._enable()
        self.fill_table()

    def _enable(self):
        edit = session.can("edit_data")
        self.fpd_stage.setEnabled(edit and self.fpd_stage_rb.isChecked())
        self.fpd_size.setEnabled(self.fpd_size_rb.isChecked())
        self.s6.setEnabled(edit and self.remove.isChecked())
        self.s7.setEnabled(edit and self.remove.isChecked())

    def fill_table(self):
        ds = self.wiz.ds
        edit = session.can("edit_data")
        self._loading = True
        rows = self.row_map()
        n = ds.n_runs
        t = self.table
        t.clear()
        t.setRowCount(len(rows))
        t.setColumnCount(n + 3)
        t.setHorizontalHeaderLabels([trf("Run {n}", n=i + 1) for i in range(n)]
                                    + [tr("Mean"), tr("SD"), tr("RSD[%]")])
        labels = []
        for kind, r in rows:
            labels.append({"dose_no": tr("Dose No."), "flow": tr("Flow (L/min)"),
                           "doses": trf("Doses to {dev}", dev=ds.device), "delivered": tr("Delivered Dose*"),
                           "total": tr("Total Dose Per Shot")}.get(kind) or tr(ds.row_titles[r]))
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
                if kind == "total" or not edit:
                    _readonly(it)
                t.setItem(i, j, it)
            st = mean_sd_rsd(vals) if kind != "dose_no" else ("", "", "")
            for k, v in enumerate(st):
                it = QTableWidgetItem(f5(v) if v != "" else "")
                _readonly(it)
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
        dlg = GroupSpecDialog(self.wiz.ds, self, readonly=not session.can("edit_data"))
        if dlg.exec() == QDialog.Accepted:
            self.wiz.modified = True

    def reset(self):
        ds = self.wiz.ds
        if QMessageBox.question(self, tr("Reset"), tr("Clear all deposition data?")) != QMessageBox.Yes:
            return
        for run in ds.runs:
            run.masses = [0.0] * ds.n_rows
            run.flow = ds.cal_flow
            run.doses = 1.0
            run.delivered = 0.0
            run.dose_no = ""
        self.wiz.modified = True
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
        self.sw = QCheckBox(tr("Report Shot Weight"))
        self.sw.toggled.connect(self._sw)
        right.addWidget(self.sw)
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._changed)
        self.table.horizontalScrollBar().valueChanged.connect(lambda *_: self.update_charts())
        self.table.currentCellChanged.connect(lambda *_: self.update_charts())
        right.addWidget(self.table, 1)
        h = QHBoxLayout()
        gb = QPushButton(tr("Group Results"))
        gb.clicked.connect(self._group_results)
        h.addWidget(gb)
        h.addStretch(1)
        right.addLayout(h)
        bot = QHBoxLayout()
        fb = QGroupBox(tr("FPD Specification"))
        fl = QVBoxLayout(fb)
        self.spec = QLabel()
        fl.addWidget(self.spec)
        bh = QHBoxLayout()
        self.b_save = QPushButton(tr("&Save"))
        self.b_save.clicked.connect(wiz.save)
        self.b_saveas = QPushButton(tr("Save &As"))
        self.b_saveas.clicked.connect(wiz.save_as)
        self.b_print = QPushButton(tr("&Print"))
        self.b_print.clicked.connect(self.print_)
        self.b_export = QPushButton(tr("&Export"))
        self.b_export.clicked.connect(self.export)
        for b in (self.b_save, self.b_saveas, self.b_print, self.b_export):
            bh.addWidget(b)
        fl.addLayout(bh)
        bot.addWidget(fb, 1)
        vb = QGroupBox(tr("View Graph"))
        vl = QGridLayout(vb)
        self.v_probit = QRadioButton(tr("Probit"))
        self.v_dep = QRadioButton(tr("Deposition"))
        self.v_cum = QRadioButton(tr("Cumulative"))
        self.v_probit.setChecked(True)
        self.throat = QCheckBox(tr("Show\nThroat"))
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
        self.sw.setEnabled(session.can("edit_data"))
        self.b_save.setEnabled(session.can("edit_data"))
        self.b_saveas.setEnabled(session.can("edit_data"))
        self.b_print.setEnabled(session.can("print"))
        self.b_export.setEnabled(session.can("export"))
        if ds.fpd_by_stage:
            self.spec.setText(trf("{a} to {b}", a=tr(ds.row_titles[ds.fpd_stage_row]), b=tr(ds.row_titles[-1])))
        else:
            self.spec.setText(trf("Less than or Equal to {d} µm", d=f"{ds.fpd_size:.5f}"))
        self._loading = False
        self.refresh()

    def refresh(self):
        ds = self.wiz.ds
        self.summary = analyse(ds)
        runs = self.summary.runs
        n = len(runs)
        edit = session.can("edit_data")
        self._loading = True
        t = self.table
        t.clear()
        t.setRowCount(len(self.ROWS))
        t.setColumnCount(n + 3)
        t.setHorizontalHeaderLabels([trf("Run {n}", n=i + 1) for i in range(n)]
                                    + [tr("Mean/dose"), tr("SD/dose"), tr("%RSD/dose")])
        u = ds.unit
        labels = []
        for key, lab in self.ROWS:
            lab = tr(lab)
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
                if not key.startswith("sw") or not edit:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(i, j, it)
            st = mean_sd_rsd([v for v in vals if isinstance(v, (int, float))])
            for k, v in enumerate(st):
                it = QTableWidgetItem(f5(v))
                _readonly(it)
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
                c.set_data(ds, res, kind, self.throat.isChecked(), title=trf("Run {n}", n=res.run))
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
        rr = reports.ReportRenderer(ds, sel, printed_by=session.name())
        kinds = ", ".join(k for k, _, _ in sel)
        if dlg.to_pdf:
            base = os.path.splitext(ds.file_name or "report")[0]
            path, _ = QFileDialog.getSaveFileName(self, tr("Save report as PDF"), base + ".pdf", "PDF (*.pdf)")
            if not path:
                return
            w = QPdfWriter(path)
            w.setResolution(300)
            w.setTitle(f"{fileio.APP_VERSION} report")
            rr.render(w)
            del w
            session.log("REPORT_PDF", ds.file_name, {"reports": kinds, "pdf": os.path.basename(path)})
            QMessageBox.information(self, tr("Print"), trf("Report saved:\n{path}", path=path))
            return
        printer = QPrinter(QPrinter.HighResolution)
        prev = QPrintPreviewDialog(printer, self)
        prev.setWindowTitle(f"{fileio.APP_VERSION} – {tr('Print Preview')}")
        prev.paintRequested.connect(rr.render)
        prev.resize(1000, 800)
        prev.exec()
        session.log("REPORT_PRINTED", ds.file_name, {"reports": kinds})

    def export(self):
        ds = self.wiz.ds
        base = os.path.splitext(ds.file_name or "data")[0]
        path, _ = QFileDialog.getSaveFileName(self, tr("Export"), base + ".csv", "CSV (*.csv)")
        if path:
            fileio.export_csv(ds, path)
            session.log("FILE_EXPORTED", ds.file_name, {"csv": os.path.basename(path)})
            QMessageBox.information(self, tr("Export"), trf("Data exported:\n{path}", path=path))


# ======================================================================
class DataWizard(QDialog):
    def __init__(self, ds, path=None, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.path = path
        self.modified = False
        self.saved_copy = copy.deepcopy(ds) if path else None
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
        u = session.user
        mode = tr("Maintenance Mode") if session.can("maintenance") else (
            tr("Operator Mode") if session.can("edit_data") else tr("Read-only Mode"))
        self.status = QLabel(f"{tr('User')}: {u.username if u else '?'} ({tr(u.role) if u else ''})  |  {mode}")
        self.status.setStyleSheet("color:#555")
        nav.addWidget(self.status)
        nav.addStretch(1)
        self.back = QPushButton(tr("< &Back"))
        self.next = QPushButton(tr("&Next >"))
        self.cancel = QPushButton(tr("Cancel"))
        self.help = QPushButton(tr("Help"))
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
        self.next.setText(tr("&Finish") if i == 2 else tr("&Next >"))
        if i == 2:
            title = tr("Shot Weight Input & Results Summary") + " [ " + trf("Screen {n} of 3", n=3) + " ]"
        else:
            title = (f"{tr(self.ds.dev.name)} - {tr(['User Setup', 'Deposition Data'][i])}"
                     f" [ {trf('Screen {n} of 3', n=i + 1)} ]")
        self.setWindowTitle(f"{title}  –  {fileio.APP_VERSION}")

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
    def _write(self, path, reason=""):
        ds = self.ds
        changes = diff_datasets(self.saved_copy, ds) if self.saved_copy is not None else []
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if not ds.created_by:
            ds.created_by, ds.created_at = session.name(), now
        ds.modified_by, ds.modified_at = session.name(), now
        ds.revision += 1
        fileio.save(ds, path)
        details = {"path": path, "revision": ds.revision}
        if reason:
            details["reason"] = reason
        if changes:
            details["changes"] = changes[:500]
            if len(changes) > 500:
                details["more_changes"] = len(changes) - 500
        session.log("FILE_SAVED" if self.saved_copy is not None else "FILE_CREATED",
                    os.path.basename(path), details)
        from .. import records
        records.register(records.MOD_APSD, path, ds.dev.name)
        self.saved_copy = copy.deepcopy(ds)
        self.path = path
        self.modified = False

    def _reason(self):
        """Ask why an existing record is being changed. None = cancelled."""
        if self.saved_copy is None or not diff_datasets(self.saved_copy, self.ds):
            return ""
        text, ok = QInputDialog.getText(self, tr("Reason for Change"),
                                        tr("Enter the reason for changing this data file:"))
        if not ok:
            return None
        if not text.strip():
            QMessageBox.warning(self, tr("Reason for Change"), tr("A reason for change is required."))
            return None
        return text.strip()

    def save(self):
        if not session.can("edit_data"):
            return False
        self.store_current()
        if not self.path or self.path.lower().endswith(".cpl"):
            return self.save_as()
        reason = self._reason()
        if reason is None:
            return False
        self._write(self.path, reason)
        return True

    def save_as(self):
        if not session.can("edit_data"):
            return False
        self.store_current()
        s = QSettings("LabDream", "LabDream")
        start = s.value("data_dir", "", type=str)
        base = os.path.splitext(self.ds.file_name or "untitled")[0] + fileio.NATIVE_EXT
        path, _ = QFileDialog.getSaveFileName(self, tr("Save As"), os.path.join(start, base),
                                              f"LabDream (*{fileio.NATIVE_EXT})")
        if not path:
            return False
        if not path.lower().endswith(fileio.NATIVE_EXT):
            path += fileio.NATIVE_EXT
        reason = self._reason()
        if reason is None:
            return False
        self._write(path, reason)
        return True

    def closeEvent(self, ev):
        if self.modified and session.can("edit_data"):
            r = QMessageBox.question(self, fileio.APP_NAME, tr("Save changes to the data file?"),
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                ev.ignore(); return
            if r == QMessageBox.Yes and not self.save():
                ev.ignore(); return
            if r == QMessageBox.No:
                session.log("CHANGES_DISCARDED", self.ds.file_name or tr("(new file)"), {})
        session.log("FILE_CLOSED", self.ds.file_name or tr("(new file)"), {})
        ev.accept()

    def show_help(self):
        i = self.stack.currentIndex()
        texts = [
            tr("help_screen1"),
            tr("help_screen2"),
            tr("help_screen3"),
        ]
        QMessageBox.information(self, tr("Help"), texts[i])
