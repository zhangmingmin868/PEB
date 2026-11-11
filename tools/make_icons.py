"""Generate assets/labdream.ico, .icns and .png (run once; output is committed)."""
import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QLinearGradient, QBrush

OUT = os.path.join(os.path.dirname(__file__), "..", "assets")


def draw(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size
    g = QLinearGradient(0, 0, 0, s)
    g.setColorAt(0, QColor(46, 98, 196))
    g.setColorAt(1, QColor(24, 60, 140))
    p.setBrush(QBrush(g))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.18, s * 0.18)
    # stacked impactor stages
    for i in range(5):
        w = s * (0.50 - i * 0.05)
        p.setBrush(QColor(255, 255, 255, 235 - i * 25))
        p.drawRoundedRect(QRectF((s - w) / 2, s * (0.20 + i * 0.105), w, s * 0.075), s * 0.02, s * 0.02)
    p.setPen(QColor(255, 255, 255))
    f = QFont("Arial")
    f.setBold(True)
    f.setPixelSize(int(s * 0.20))
    p.setFont(f)
    p.drawText(QRectF(0, s * 0.72, s, s * 0.22), Qt.AlignCenter, "LD")
    p.end()
    return img


def main():
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    draw(512).save(os.path.join(OUT, "labdream.png"))
    draw(256).save(os.path.join(OUT, "labdream.ico"))
    ok = draw(512).save(os.path.join(OUT, "labdream.icns"))
    print("icns written" if ok else "icns not supported by this Qt build")


if __name__ == "__main__":
    main()
