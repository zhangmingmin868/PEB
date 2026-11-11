"""Chart drawing shared by the screen and the printed reports (QPainter)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QFontMetricsF

from .engine import probit, NA

BLUE = QColor(40, 90, 200)
RED = QColor(220, 30, 30)
GRID = QColor(215, 215, 215)


def _nice_max(v):
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.6, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * e >= v:
            return m * e
    return 10 * e


def _font(p: QPainter, size: float, bold=False):
    f = QFont("Arial")
    f.setPointSizeF(size)
    f.setBold(bold)
    p.setFont(f)
    return QFontMetricsF(f, p.device())


def draw_probit(p: QPainter, rect: QRectF, res, title="Log-Probit Plot", fs=7.0):
    """Cumulative % undersize (probit 3–7) vs particle size (log 0.1–10 µm)."""
    p.save()
    fm = _font(p, fs)
    lh = fm.height()
    left = rect.left() + lh * 2.4
    bottom = rect.bottom() - lh * 2.4
    top = rect.top() + lh * 1.3
    right = rect.right() - lh * 0.8
    plot = QRectF(QPointF(left, top), QPointF(right, bottom))
    xmin, xmax = -1.0, 1.0
    ymin, ymax = 3.0, 7.0
    if res is not None and res.points:
        dmax = max(d for d, _ in res.points)
        dmin = min(d for d, _ in res.points)
        if dmax > 10.0:
            xmax = 2.0
        if dmin < 0.1:
            xmin = -2.0

    def X(lx):
        return plot.left() + (lx - xmin) / (xmax - xmin) * plot.width()

    def Y(y):
        return plot.bottom() - (y - ymin) / (ymax - ymin) * plot.height()

    # axes
    p.setPen(QPen(Qt.black, 0))
    p.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))
    p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
    for y in range(3, 8):
        yy = Y(y)
        p.drawLine(QPointF(plot.left() - lh * 0.25, yy), QPointF(plot.left(), yy))
        p.drawText(QRectF(rect.left(), yy - lh / 2, plot.left() - rect.left() - lh * 0.35, lh),
                   Qt.AlignRight | Qt.AlignVCenter, str(y))
    dec = int(xmin)
    while dec <= xmax:
        xx = X(dec)
        p.drawLine(QPointF(xx, plot.bottom()), QPointF(xx, plot.bottom() + lh * 0.3))
        lab = f"{10 ** dec:.1f}" if dec <= 1 else f"{10 ** dec:.0f}"
        if dec < -1:
            lab = f"{10 ** dec:.2f}"
        p.drawText(QRectF(xx - lh * 2, plot.bottom() + lh * 0.3, lh * 4, lh), Qt.AlignHCenter, lab)
        if dec < xmax:
            for k in range(2, 10):
                xs = X(dec + math.log10(k))
                p.drawLine(QPointF(xs, plot.bottom()), QPointF(xs, plot.bottom() + lh * 0.15))
        dec += 1
    p.drawText(QRectF(plot.left(), plot.bottom() + lh * 1.25, plot.width(), lh),
               Qt.AlignHCenter, "Particle Size [µm]")
    p.save()
    p.translate(rect.left() + lh * 0.1, plot.center().y())
    p.rotate(-90)
    p.drawText(QRectF(-plot.height() / 2 - lh * 2, 0, plot.height() + lh * 4, lh),
               Qt.AlignHCenter, "Cumulative % UnderSize")
    p.restore()
    p.drawText(QRectF(plot.left(), rect.top(), plot.width(), lh), Qt.AlignHCenter, title)

    if res is not None:
        r = max(1.5, lh * 0.16)
        reg = []
        for d, pc in res.points:
            if d <= 0:
                continue
            lx = math.log10(d)
            y = probit(pc)
            out = y < ymin or y > ymax or lx < xmin or lx > xmax
            yc = min(max(y, ymin), ymax)
            lxc = min(max(lx, xmin), xmax)
            if out:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(RED))
                yc = ymax if y > ymax else (ymin if y < ymin else yc)
                p.drawEllipse(QPointF(X(lxc), Y(yc) - (r * 1.5 if y > ymax else 0)), r, r)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(Qt.black))
                p.drawEllipse(QPointF(X(lx), Y(y)), r, r)
            if 4.0 - 1e-9 <= y <= 6.0 + 1e-9:
                reg.append(lx)
        if len(reg) >= 2 and res.slope != NA and res.intercept != NA:
            a, b = res.intercept, res.slope
            x0, x1 = min(reg), max(reg)
            ext = (x1 - x0) * 0.08
            x0, x1 = x0 - ext, x1 + ext
            p.setPen(QPen(BLUE, max(1.0, lh * 0.08)))
            p.setClipRect(plot)
            p.drawLine(QPointF(X(x0), Y(a + b * x0)), QPointF(X(x1), Y(a + b * x1)))
            p.setClipping(False)
    p.restore()


def draw_deposition(p: QPainter, ds, res, rect: QRectF, title="Drug Distribution per Discharge",
                    show_throat=True, fs=7.0, percent=False):
    """Bar chart of mass per location (filter on the left)."""
    p.save()
    fm = _font(p, fs)
    lh = fm.height()
    rows = [r for r in range(ds.n_rows) if ds.row_active(r)]
    if not show_throat:
        rows = [r for r in rows if r >= 3]
    rows = list(reversed(rows))
    vals = [res.masses_per_dose[r] if res else 0.0 for r in rows]
    if percent and res and res.total:
        vals = [100.0 * v / res.total for v in vals]
    names = [ds.row_titles[r] for r in rows]
    maxlab = max((fm.horizontalAdvance(n) for n in names), default=lh)
    left = rect.left() + lh * 3.2
    bottom = rect.bottom() - maxlab - lh * 1.6
    top = rect.top() + lh * 1.3
    right = rect.right() - lh * 0.5
    plot = QRectF(QPointF(left, top), QPointF(right, bottom))
    vmax = _nice_max(max(vals) if vals else 1.0)
    p.setPen(QPen(Qt.black, 0))
    p.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))
    p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
    for k in range(6):
        v = vmax * k / 5
        yy = plot.bottom() - plot.height() * k / 5
        p.drawLine(QPointF(plot.left() - lh * 0.25, yy), QPointF(plot.left(), yy))
        p.drawText(QRectF(rect.left(), yy - lh / 2, plot.left() - rect.left() - lh * 0.35, lh),
                   Qt.AlignRight | Qt.AlignVCenter, f"{v:.4g}")
    n = max(1, len(rows))
    bw = plot.width() / n
    p.setBrush(QBrush(BLUE))
    for i, (nm, v) in enumerate(zip(names, vals)):
        x = plot.left() + i * bw
        h = plot.height() * (v / vmax) if vmax else 0
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(x + bw * 0.22, plot.bottom() - h, bw * 0.56, h))
        p.setPen(QPen(Qt.black, 0))
        p.save()
        p.translate(x + bw / 2 + lh * 0.35, plot.bottom() + lh * 0.3)
        p.rotate(-90)
        p.drawText(QRectF(-maxlab, -lh, maxlab, lh), Qt.AlignRight | Qt.AlignVCenter, nm)
        p.restore()
    p.setPen(QPen(Qt.black, 0))
    p.drawText(QRectF(plot.left(), rect.bottom() - lh, plot.width(), lh), Qt.AlignHCenter, "Location")
    p.save()
    p.translate(rect.left() + lh * 0.1, plot.center().y())
    p.rotate(-90)
    unit = "%" if percent else ds.unit
    p.drawText(QRectF(-plot.height() / 2 - lh * 2, 0, plot.height() + lh * 4, lh),
               Qt.AlignHCenter, f"Drug Deposition [{unit}]")
    p.restore()
    p.drawText(QRectF(plot.left(), rect.top(), plot.width(), lh), Qt.AlignHCenter, title)
    p.restore()


def draw_cumulative(p: QPainter, res, rect: QRectF, title="Cumulative Drug Distribution", fs=7.0):
    """Cumulative % undersize versus upper aerodynamic diameter."""
    p.save()
    fm = _font(p, fs)
    lh = fm.height()
    left = rect.left() + lh * 3.0
    bottom = rect.bottom() - lh * 2.6
    top = rect.top() + lh * 1.3
    right = rect.right() - lh * 0.8
    plot = QRectF(QPointF(left, top), QPointF(right, bottom))
    pts = sorted(res.points) if res else []
    p.setPen(QPen(Qt.black, 0))
    p.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))
    p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
    for k in range(6):
        yy = plot.bottom() - plot.height() * k / 5
        p.drawLine(QPointF(plot.left() - lh * 0.25, yy), QPointF(plot.left(), yy))
        p.drawText(QRectF(rect.left(), yy - lh / 2, plot.left() - rect.left() - lh * 0.35, lh),
                   Qt.AlignRight | Qt.AlignVCenter, str(20 * k))
    n = max(1, len(pts))
    step = plot.width() / n
    xy = []
    for i, (d, pc) in enumerate(pts):
        x = plot.left() + step * (i + 0.5)
        y = plot.bottom() - plot.height() * pc / 100.0
        xy.append(QPointF(x, y))
        p.drawText(QRectF(x - step / 2, plot.bottom() + lh * 0.2, step, lh), Qt.AlignHCenter, f"{d:.3g}")
    p.drawText(QRectF(plot.left(), plot.bottom() + lh * 1.3, plot.width(), lh),
               Qt.AlignHCenter, "Upper Aerodynamic Diam. [µm]")
    p.save()
    p.translate(rect.left() + lh * 0.1, plot.center().y())
    p.rotate(-90)
    p.drawText(QRectF(-plot.height() / 2 - lh * 2, 0, plot.height() + lh * 4, lh),
               Qt.AlignHCenter, "Drug Deposition [%]")
    p.restore()
    p.drawText(QRectF(plot.left(), rect.top(), plot.width(), lh), Qt.AlignHCenter, title)
    if xy:
        p.setPen(QPen(BLUE, max(1.0, lh * 0.08)))
        for a, b in zip(xy, xy[1:]):
            p.drawLine(a, b)
        p.setBrush(QBrush(BLUE))
        for q in xy:
            p.drawEllipse(q, lh * 0.15, lh * 0.15)
    p.restore()


def draw_device_picture(p: QPainter, rect: QRectF, device: str):
    """Stylised drawing of the impactor (used on the left of every screen)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    g = QColor(235, 238, 242)
    p.fillRect(rect, QColor(250, 250, 252))
    cx = rect.center().x()
    w = rect.width()
    h = rect.height()
    metal = QColor(170, 176, 186)
    dark = QColor(110, 116, 126)
    pen = QPen(dark, 1.2)
    p.setPen(pen)
    if device in ("CI", "MSLI"):
        # induction port
        p.setBrush(metal)
        p.drawRect(QRectF(cx - w * 0.30, rect.top() + h * 0.08, w * 0.06, h * 0.30))
        p.drawRect(QRectF(cx - w * 0.30, rect.top() + h * 0.06, w * 0.42, h * 0.05))
        p.setBrush(QColor(60, 170, 110))
        p.drawRect(QRectF(cx + w * 0.12, rect.top() + h * 0.055, w * 0.12, h * 0.06))
        n = 9 if device == "CI" else 5
        top = rect.top() + h * 0.38
        sh = h * 0.52 / n
        for i in range(n):
            p.setBrush(metal if i % 2 == 0 else g)
            ww = w * (0.36 if device == "CI" else 0.42 - i * 0.02)
            p.drawRoundedRect(QRectF(cx - ww / 2 - w * 0.05, top + i * sh, ww, sh * 0.9), 3, 3)
        p.setBrush(dark)
        p.drawRect(QRectF(cx - w * 0.25, rect.top() + h * 0.91, w * 0.40, h * 0.03))
    elif device == "NGI":
        p.setBrush(metal)
        p.drawRect(QRectF(cx - w * 0.36, rect.top() + h * 0.18, w * 0.06, h * 0.30))
        p.drawRect(QRectF(cx - w * 0.36, rect.top() + h * 0.15, w * 0.36, h * 0.05))
        p.setBrush(QColor(60, 170, 110))
        p.drawRect(QRectF(cx, rect.top() + h * 0.145, w * 0.12, h * 0.06))
        p.setBrush(metal)
        p.drawRoundedRect(QRectF(rect.left() + w * 0.08, rect.top() + h * 0.48, w * 0.84, h * 0.22), 6, 6)
        p.setBrush(g)
        for i in range(8):
            p.drawEllipse(QPointF(rect.left() + w * (0.17 + i * 0.095), rect.top() + h * 0.59), w * 0.035, w * 0.035)
        p.setBrush(dark)
        p.drawRect(QRectF(rect.left() + w * 0.06, rect.top() + h * 0.70, w * 0.88, h * 0.04))
    else:  # MMI
        p.setBrush(QColor(60, 80, 130))
        for i in range(5):
            x = cx - w * 0.25 + (i % 2) * w * 0.12
            p.drawRoundedRect(QRectF(x, rect.top() + h * (0.18 + i * 0.13), w * 0.38, h * 0.11), 5, 5)
        p.setBrush(QColor(230, 200, 60))
        p.drawRect(QRectF(rect.left() + w * 0.12, rect.top() + h * 0.86, w * 0.76, h * 0.04))
        p.setBrush(QColor(200, 170, 40))
        p.drawRect(QRectF(cx + w * 0.05, rect.top() + h * 0.12, w * 0.28, h * 0.05))
    f = QFont("Arial")
    f.setPointSizeF(9)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(90, 90, 100))
    p.drawText(QRectF(rect.left(), rect.bottom() - 22, rect.width(), 20), Qt.AlignCenter, device)
    p.restore()
