"""Small reusable widgets."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLineEdit, QWidget, QSizePolicy

from .. import charts


def parse_float(text: str, default=0.0) -> float:
    t = (text or "").strip().replace(",", ".")
    if not t:
        return default
    try:
        return float(t)
    except ValueError:
        return default


def f5(v) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return "NA"
    return f"{v:.5f}"


class NumEdit(QLineEdit):
    """Line edit for numbers shown with 5 decimals (like the data screens)."""
    valueChanged = Signal(float)

    def __init__(self, value=0.0, decimals=5, parent=None, width=78):
        super().__init__(parent)
        self.decimals = decimals
        self.setAlignment(Qt.AlignLeft)
        self.setFixedWidth(width)
        self.set_value(value)
        self.editingFinished.connect(self._done)

    def set_value(self, v):
        self.setText(f"{v:.{self.decimals}f}")

    def value(self) -> float:
        return parse_float(self.text())

    def _done(self):
        v = self.value()
        self.set_value(v)
        self.valueChanged.emit(v)


class DevicePicture(QWidget):
    def __init__(self, device: str, parent=None):
        super().__init__(parent)
        self.device = device
        self.setFixedWidth(170)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def set_device(self, d):
        self.device = d
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        charts.draw_device_picture(p, QRectF(self.rect()).adjusted(4, 4, -4, -4), self.device)


class ChartWidget(QWidget):
    """Shows one of the three result graphs for a run."""
    PROBIT, DEPOSITION, CUMULATIVE = "probit", "deposition", "cumulative"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ds = None
        self.res = None
        self.kind = self.PROBIT
        self.show_throat = True
        self.title = ""
        self.setMinimumSize(200, 150)

    def set_data(self, ds, res, kind, show_throat=True, title=""):
        self.ds, self.res, self.kind, self.show_throat, self.title = ds, res, kind, show_throat, title
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), Qt.white)
        p.setPen(Qt.gray)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if self.ds is None:
            return
        t = self.title
        if self.kind == self.PROBIT:
            charts.draw_probit(p, r, self.res, title=t or None, fs=7)
        elif self.kind == self.DEPOSITION:
            charts.draw_deposition(p, self.ds, self.res, r, title=t or None,
                                   show_throat=self.show_throat, fs=7)
        else:
            charts.draw_cumulative(p, self.res, r, title=t or None, fs=7)
