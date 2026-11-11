"""Group specification / group results / print / setup / device selection dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView)

from ..devices import DEVICES, DEVICE_ORDER
from ..engine import mean_sd_rsd
from ..model import GROUP_OFF, GROUP_SIZE, GROUP_STAGE, Group
from .. import reports
from .widgets import DevicePicture, NumEdit, f5


class DeviceSelectDialog(QDialog):
    def __init__(self, parent=None, current="CI"):
        super().__init__(parent)
        self.setWindowTitle("Select Impactor / Impinger")
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.bg = QButtonGroup(self)
        for i, code in enumerate(DEVICE_ORDER):
            col = QVBoxLayout()
            pic = DevicePicture(code)
            pic.setFixedSize(150, 190)
            rb = QRadioButton(DEVICES[code].name)
            rb.setChecked(code == current)
            self.bg.addButton(rb, i)
            col.addWidget(pic, 0, Qt.AlignHCenter)
            col.addWidget(rb, 0, Qt.AlignHCenter)
            row.addLayout(col)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def device(self):
        return DEVICE_ORDER[max(0, self.bg.checkedId())]


class GroupSpecDialog(QDialog):
    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.setWindowTitle("Group Specification")
        outer = QHBoxLayout(self)
        outer.addWidget(DevicePicture(ds.device))
        right = QVBoxLayout()
        row = QHBoxLayout()
        self.ctrls = []
        stage_names = [(r, ds.row_titles[r]) for r in range(ds.n_rows) if ds.row_active(r)]
        for g in range(5):
            grp = ds.groups[g]
            box = QGroupBox(f"Group {g+1}")
            v = QVBoxLayout(box)
            off = QRadioButton("Off")
            size = QRadioButton("Size Spec.")
            stage = QRadioButton("Group Spec.")
            bg = QButtonGroup(box)
            for b in (off, size, stage):
                bg.addButton(b)
            v.addWidget(off)
            v.addSpacing(8)
            v.addWidget(size)
            v.addWidget(QLabel("Minimum"))
            mn = NumEdit(grp.min_um)
            h1 = QHBoxLayout(); h1.addWidget(mn); h1.addWidget(QLabel("µm")); v.addLayout(h1)
            v.addWidget(QLabel("Maximum"))
            mx = NumEdit(grp.max_um)
            h2 = QHBoxLayout(); h2.addWidget(mx); h2.addWidget(QLabel("µm")); v.addLayout(h2)
            v.addSpacing(16)
            v.addWidget(stage)
            v.addWidget(QLabel("From"))
            cf = QComboBox()
            v.addWidget(cf)
            v.addWidget(QLabel("To"))
            ct = QComboBox()
            v.addWidget(ct)
            for r, name in stage_names:
                cf.addItem(name, r)
                ct.addItem(name, r)
            cf.setCurrentIndex(max(0, cf.findData(grp.from_row)))
            ct.setCurrentIndex(max(0, ct.findData(grp.to_row)))
            {GROUP_OFF: off, GROUP_SIZE: size, GROUP_STAGE: stage}[grp.mode].setChecked(True)

            def upd(_=None, size=size, stage=stage, mn=mn, mx=mx, cf=cf, ct=ct):
                mn.setEnabled(size.isChecked()); mx.setEnabled(size.isChecked())
                cf.setEnabled(stage.isChecked()); ct.setEnabled(stage.isChecked())
            for b in (off, size, stage):
                b.toggled.connect(upd)
            upd()
            self.ctrls.append((off, size, stage, mn, mx, cf, ct))
            row.addWidget(box)
        right.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
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
        self.setWindowTitle("Group Results")
        self.resize(1100, 560)
        outer = QHBoxLayout(self)
        outer.addWidget(DevicePicture(ds.device))
        v = QVBoxLayout()
        runs = summary.runs
        heads = ["Group", "", ""] + [f"Run {r.run}" for r in runs] + ["Mean", "SD", "%RSD"]
        active = [g for g in range(5) if ds.groups[g].mode != GROUP_OFF]
        t = QTableWidget(len(active) * 2, len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().setVisible(False)
        u = ds.unit
        for i, g in enumerate(active):
            gr0 = runs[0].groups[g]
            for k, (lab, attr) in enumerate(((f"Particle Dose [{u}]", "dose"), ("Particle Fraction [%]", "fraction"))):
                rr = i * 2 + k
                t.setItem(rr, 0, QTableWidgetItem(f"Group {g+1}" if k == 0 else ""))
                t.setItem(rr, 1, QTableWidgetItem(("From " + gr0.label_from) if k == 0 else ("To " + gr0.label_to)))
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
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        v.addWidget(ok, 0, Qt.AlignHCenter)
        outer.addLayout(v)


class PrintDialog(QDialog):
    def __init__(self, n_runs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Print")
        lay = QVBoxLayout(self)
        box = QGroupBox("Report Type")
        g = QGridLayout(box)
        runs = [str(i) for i in range(1, n_runs + 1)] + [reports.MEAN]
        self.items = {}
        r = 0
        for kind, text in ((reports.EP, "according to the European Pharmacopoeia method."),
                           (reports.USP, "according to the United States Pharmacopeia method.")):
            cb = QCheckBox("Results and Analysis from run")
            a = QComboBox(); a.addItems(runs)
            b = QComboBox(); b.addItems(runs); b.setCurrentIndex(len(runs) - 1)
            h = QHBoxLayout()
            h.addWidget(cb); h.addWidget(a); h.addWidget(QLabel("to run")); h.addWidget(b)
            h.addWidget(QLabel("(one run per page)")); h.addStretch(1)
            g.addLayout(h, r, 0); r += 1
            g.addWidget(QLabel("      " + text), r, 0); r += 1
            self.items[kind] = (cb, a, b)
        for kind, text in ((reports.GRAPHICAL, "Graphical Summary (up to 3 runs per page)"),
                           (reports.TABULAR, "Tabular Summary (runs one or two pages)"),
                           (reports.GROUPS, "Group Results (all runs on a single page)")):
            cb = QCheckBox(text)
            g.addWidget(cb, r, 0); r += 1
            self.items[kind] = (cb, None, None)
        self.items[reports.TABULAR][0].setChecked(True)
        lay.addWidget(box)
        h = QHBoxLayout()
        self.pdf = QPushButton("Save as PDF…")
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
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
                out.append((kind, a.currentText() if a else None, b.currentText() if b else None))
        return out


class SetupDialog(QDialog):
    """Maintenance set-up: default templates read when entering new data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LabDream Set-up")
        self.s = QSettings("LabDream", "LabDream")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edits = {}
        for code in DEVICE_ORDER:
            h = QHBoxLayout()
            cb = QCheckBox("Read from Template")
            cb.setChecked(self.s.value(f"template/{code}/use", False, type=bool))
            e = QLineEdit(self.s.value(f"template/{code}/path", "", type=str))
            b = QPushButton("Browse…")
            b.clicked.connect(lambda _=False, e=e: self._browse(e))
            h.addWidget(cb); h.addWidget(e, 1); h.addWidget(b)
            w = QWidget(); w.setLayout(h)
            form.addRow(DEVICES[code].name, w)
            self.edits[code] = (cb, e)
        h = QHBoxLayout()
        self.data_dir = QLineEdit(self.s.value("data_dir", "", type=str))
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_dir)
        h.addWidget(self.data_dir, 1); h.addWidget(b)
        w = QWidget(); w.setLayout(h)
        form.addRow("Data file folder", w)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(720, 260)

    def _browse(self, e):
        p, _ = QFileDialog.getOpenFileName(self, "Template file", e.text(),
                                           "Data files (*.ldd *.cpl *.CPL);;All files (*)")
        if p:
            e.setText(p)

    def _browse_dir(self):
        p = QFileDialog.getExistingDirectory(self, "Data folder", self.data_dir.text())
        if p:
            self.data_dir.setText(p)

    def _ok(self):
        for code, (cb, e) in self.edits.items():
            self.s.setValue(f"template/{code}/use", cb.isChecked())
            self.s.setValue(f"template/{code}/path", e.text())
        self.s.setValue("data_dir", self.data_dir.text())
        self.accept()
