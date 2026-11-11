"""Group specification / group results / print / setup / device selection dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import reports, session
from ..devices import DEVICES, DEVICE_ORDER
from ..engine import mean_sd_rsd
from ..i18n import tr, trf
from ..model import GROUP_OFF, GROUP_SIZE, GROUP_STAGE, Group
from .widgets import DevicePicture, NumEdit, f5


def ok_cancel(parent, accept, reject):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(tr("OK"))
    bb.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
    bb.accepted.connect(accept)
    bb.rejected.connect(reject)
    return bb


class DeviceSelectDialog(QDialog):
    def __init__(self, parent=None, current="CI"):
        super().__init__(parent)
        self.setWindowTitle(tr("Select Impactor / Impinger"))
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.bg = QButtonGroup(self)
        for i, code in enumerate(DEVICE_ORDER):
            col = QVBoxLayout()
            pic = DevicePicture(code)
            pic.setFixedSize(150, 190)
            rb = QRadioButton(tr(DEVICES[code].name))
            rb.setChecked(code == current)
            self.bg.addButton(rb, i)
            col.addWidget(pic, 0, Qt.AlignHCenter)
            col.addWidget(rb, 0, Qt.AlignHCenter)
            row.addLayout(col)
        lay.addLayout(row)
        lay.addWidget(ok_cancel(self, self.accept, self.reject))

    def device(self):
        return DEVICE_ORDER[max(0, self.bg.checkedId())]


class GroupSpecDialog(QDialog):
    def __init__(self, ds, parent=None, readonly=False):
        super().__init__(parent)
        self.ds = ds
        self.setWindowTitle(tr("Group Specification"))
        outer = QHBoxLayout(self)
        outer.addWidget(DevicePicture(ds.device))
        right = QVBoxLayout()
        row = QHBoxLayout()
        self.ctrls = []
        stage_names = [(r, tr(ds.row_titles[r])) for r in range(ds.n_rows) if ds.row_active(r)]
        for g in range(5):
            grp = ds.groups[g]
            box = QGroupBox(trf("Group {n}", n=g + 1))
            v = QVBoxLayout(box)
            off = QRadioButton(tr("Off"))
            size = QRadioButton(tr("Size Spec."))
            stage = QRadioButton(tr("Group Spec."))
            bg = QButtonGroup(box)
            for b in (off, size, stage):
                bg.addButton(b)
            v.addWidget(off)
            v.addSpacing(8)
            v.addWidget(size)
            v.addWidget(QLabel(tr("Minimum")))
            mn = NumEdit(grp.min_um)
            h1 = QHBoxLayout(); h1.addWidget(mn); h1.addWidget(QLabel("µm")); v.addLayout(h1)
            v.addWidget(QLabel(tr("Maximum")))
            mx = NumEdit(grp.max_um)
            h2 = QHBoxLayout(); h2.addWidget(mx); h2.addWidget(QLabel("µm")); v.addLayout(h2)
            v.addSpacing(16)
            v.addWidget(stage)
            v.addWidget(QLabel(tr("From")))
            cf = QComboBox()
            v.addWidget(cf)
            v.addWidget(QLabel(tr("To")))
            ct = QComboBox()
            v.addWidget(ct)
            for r, name in stage_names:
                cf.addItem(name, r)
                ct.addItem(name, r)
            cf.setCurrentIndex(max(0, cf.findData(grp.from_row)))
            ct.setCurrentIndex(max(0, ct.findData(grp.to_row)))
            {GROUP_OFF: off, GROUP_SIZE: size, GROUP_STAGE: stage}[grp.mode].setChecked(True)

            def upd(_=None, size=size, stage=stage, mn=mn, mx=mx, cf=cf, ct=ct):
                mn.setEnabled(size.isChecked() and not readonly)
                mx.setEnabled(size.isChecked() and not readonly)
                cf.setEnabled(stage.isChecked() and not readonly)
                ct.setEnabled(stage.isChecked() and not readonly)
            for b in (off, size, stage):
                b.toggled.connect(upd)
                b.setEnabled(not readonly)
            upd()
            self.ctrls.append((off, size, stage, mn, mx, cf, ct))
            row.addWidget(box)
        right.addLayout(row)
        right.addWidget(ok_cancel(self, self.reject if readonly else self._ok, self.reject))
        outer.addLayout(right)

    def _ok(self):
        groups = []
        for off, size, stage, mn, mx, cf, ct in self.ctrls:
            mode = GROUP_OFF if off.isChecked() else (GROUP_SIZE if size.isChecked() else GROUP_STAGE)
            groups.append(Group(mode, mn.value(), mx.value(), cf.currentData(), ct.currentData()))
        self.ds.groups = groups
        self.accept()


class GroupResultsDialog(QDialog):
    def __init__(self, ds, summary, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Group Results"))
        self.resize(1100, 560)
        outer = QHBoxLayout(self)
        outer.addWidget(DevicePicture(ds.device))
        v = QVBoxLayout()
        runs = summary.runs
        heads = [tr("Group"), "", ""] + [trf("Run {n}", n=r.run) for r in runs] + [tr("Mean"), tr("SD"), tr("%RSD")]
        active = [g for g in range(5) if ds.groups[g].mode != GROUP_OFF]
        t = QTableWidget(len(active) * 2, len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().setVisible(False)
        u = ds.unit
        for i, g in enumerate(active):
            gr0 = runs[0].groups[g]
            for k, (lab, attr) in enumerate(((f"{tr('Particle Dose')} [{u}]", "dose"),
                                             (f"{tr('Particle Fraction')} [%]", "fraction"))):
                rr = i * 2 + k
                t.setItem(rr, 0, QTableWidgetItem(trf("Group {n}", n=g + 1) if k == 0 else ""))
                t.setItem(rr, 1, QTableWidgetItem((tr("From") + " " + gr0.label_from) if k == 0
                                                  else (tr("To") + " " + gr0.label_to)))
                t.setItem(rr, 2, QTableWidgetItem(lab))
                vals = [getattr(r.groups[g], attr) for r in runs]
                st = mean_sd_rsd([x for x in vals if isinstance(x, (int, float))])
                for j, x in enumerate(vals + list(st)):
                    it = QTableWidgetItem(f5(x))
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    t.setItem(rr, 3 + j, it)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.resizeColumnsToContents()
        v.addWidget(t)
        ok = QPushButton(tr("OK"))
        ok.clicked.connect(self.accept)
        v.addWidget(ok, 0, Qt.AlignHCenter)
        outer.addLayout(v)


class PrintDialog(QDialog):
    def __init__(self, n_runs, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Print"))
        lay = QVBoxLayout(self)
        box = QGroupBox(tr("Report Type"))
        g = QGridLayout(box)
        runs = [str(i) for i in range(1, n_runs + 1)] + [reports.MEAN]
        self.items = {}
        r = 0
        for kind, text in ((reports.EP, "according to the European Pharmacopoeia method."),
                           (reports.USP, "according to the United States Pharmacopeia method.")):
            cb = QCheckBox(tr("Results and Analysis from run"))
            a = QComboBox()
            b = QComboBox()
            for x in runs:
                a.addItem(tr(x) if x == reports.MEAN else x, x)
                b.addItem(tr(x) if x == reports.MEAN else x, x)
            b.setCurrentIndex(len(runs) - 1)
            h = QHBoxLayout()
            h.addWidget(cb); h.addWidget(a); h.addWidget(QLabel(tr("to run"))); h.addWidget(b)
            h.addWidget(QLabel(tr("(one run per page)"))); h.addStretch(1)
            g.addLayout(h, r, 0); r += 1
            g.addWidget(QLabel("      " + tr(text)), r, 0); r += 1
            self.items[kind] = (cb, a, b)
        for kind, text in ((reports.GRAPHICAL, "Graphical Summary (up to 3 runs per page)"),
                           (reports.TABULAR, "Tabular Summary (runs one or two pages)"),
                           (reports.GROUPS, "Group Results (all runs on a single page)")):
            cb = QCheckBox(tr(text))
            g.addWidget(cb, r, 0); r += 1
            self.items[kind] = (cb, None, None)
        self.items[reports.TABULAR][0].setChecked(True)
        lay.addWidget(box)
        h = QHBoxLayout()
        self.pdf = QPushButton(tr("Save as PDF…"))
        ok = QPushButton(tr("OK"))
        cancel = QPushButton(tr("Cancel"))
        ok.setDefault(True)
        h.addStretch(1); h.addWidget(ok); h.addWidget(self.pdf); h.addWidget(cancel); h.addStretch(1)
        lay.addLayout(h)
        self.to_pdf = False
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self.pdf.clicked.connect(self._pdf)

    def _pdf(self):
        self.to_pdf = True
        self.accept()

    def selections(self):
        out = []
        for kind, (cb, a, b) in self.items.items():
            if cb.isChecked():
                out.append((kind, a.currentData() if a else None, b.currentData() if b else None))
        return out


class SetupDialog(QDialog):
    """Maintenance set-up: default templates read when entering new data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("LabDream Set-up"))
        self.s = QSettings("LabDream", "LabDream")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edits = {}
        self.old = {}
        for code in DEVICE_ORDER:
            h = QHBoxLayout()
            cb = QCheckBox(tr("Read from Template"))
            cb.setChecked(self.s.value(f"template/{code}/use", False, type=bool))
            e = QLineEdit(self.s.value(f"template/{code}/path", "", type=str))
            b = QPushButton(tr("Browse…"))
            b.clicked.connect(lambda _=False, e=e: self._browse(e))
            h.addWidget(cb); h.addWidget(e, 1); h.addWidget(b)
            w = QWidget(); w.setLayout(h)
            form.addRow(tr(DEVICES[code].name), w)
            self.edits[code] = (cb, e)
            self.old[code] = (cb.isChecked(), e.text())
        h = QHBoxLayout()
        self.data_dir = QLineEdit(self.s.value("data_dir", "", type=str))
        self.old_dir = self.data_dir.text()
        b = QPushButton(tr("Browse…"))
        b.clicked.connect(self._browse_dir)
        h.addWidget(self.data_dir, 1); h.addWidget(b)
        w = QWidget(); w.setLayout(h)
        form.addRow(tr("Data file folder"), w)
        lay.addLayout(form)
        lay.addWidget(ok_cancel(self, self._ok, self.reject))
        self.resize(760, 260)

    def _browse(self, e):
        p, _ = QFileDialog.getOpenFileName(self, tr("Template file"), e.text(),
                                           f"{tr('Data files')} (*.ldd *.cpl *.CPL);;* (*)")
        if p:
            e.setText(p)

    def _browse_dir(self):
        p = QFileDialog.getExistingDirectory(self, tr("Data file folder"), self.data_dir.text())
        if p:
            self.data_dir.setText(p)

    def _ok(self):
        changes = {}
        for code, (cb, e) in self.edits.items():
            self.s.setValue(f"template/{code}/use", cb.isChecked())
            self.s.setValue(f"template/{code}/path", e.text())
            if self.old[code] != (cb.isChecked(), e.text()):
                changes[code] = {"use": cb.isChecked(), "path": e.text()}
        self.s.setValue("data_dir", self.data_dir.text())
        if self.old_dir != self.data_dir.text():
            changes["data_dir"] = self.data_dir.text()
        if changes:
            session.log("SETTINGS_CHANGED", "templates", changes)
        self.accept()
