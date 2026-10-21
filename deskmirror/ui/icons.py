"""小图标：Windows 自带的图标字体（Segoe Fluent Icons，Windows 10 上是 Segoe MDL2 Assets）里的字符，
或者用几笔画出来的（截图工具栏上的画图工具）。都按 2 倍像素画，高分屏上也清楚。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap

_family: str | None = None


def icon_family() -> str:
    global _family
    if _family is None:
        families = set(QFontDatabase.families())
        _family = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), "")
    return _family


def glyph(code: int, color, px: int = 18) -> QIcon:
    family = icon_family()
    if not family:
        return QIcon()
    pm = QPixmap(px * 2, px * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    f = QFont(family)
    f.setPixelSize(px - 3)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRect(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, chr(code))
    p.end()
    return QIcon(pm)


def drawn(name: str, color, px: int = 18) -> QIcon:
    """截图工具栏上画出来的图标：rect / ellipse / arrow / pen / highlight / text / number / mosaic / ocr /
    translate / mirror。"""
    c = QColor(color)
    pm = QPixmap(px * 2, px * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    s = px
    m = s * 0.2
    box = QRectF(m, m, s - 2 * m, s - 2 * m)
    if name == "rect":
        p.drawRect(box.adjusted(0, 1.5, 0, -1.5))
    elif name == "ellipse":
        p.drawEllipse(box.adjusted(0, 1.5, 0, -1.5))
    elif name == "arrow":
        a, b = QPointF(m, s - m), QPointF(s - m, m)
        p.drawLine(a, b)
        p.drawLine(b, QPointF(b.x() - s * 0.32, b.y()))
        p.drawLine(b, QPointF(b.x(), b.y() + s * 0.32))
    elif name in ("pen", "highlight"):
        path = QPainterPath(QPointF(m, s * 0.62))
        path.cubicTo(QPointF(s * 0.35, s * 0.2), QPointF(s * 0.55, s * 0.9), QPointF(s - m, s * 0.38))
        if name == "highlight":
            hc = QColor(c)
            hc.setAlpha(110)
            p.setPen(QPen(hc, 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
    elif name == "text":
        f = QFont("Segoe UI")
        f.setPixelSize(int(s * 0.78))
        p.setFont(f)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "T")
    elif name == "number":
        p.drawEllipse(box)
        f = QFont("Segoe UI")
        f.setPixelSize(int(s * 0.5))
        f.setBold(True)
        p.setFont(f)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, "1")
    elif name == "mosaic":
        cell = (s - 2 * m) / 3
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0:
                    p.fillRect(QRectF(m + i * cell, m + j * cell, cell, cell), c)
        p.drawRect(box)
    elif name == "ocr":                     # 角上四个括号，中间一个 T：认出图里的字
        k = s * 0.22
        for x, y, dx, dy in ((m, m, 1, 1), (s - m, m, -1, 1), (m, s - m, 1, -1), (s - m, s - m, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * k))
        f = QFont("Segoe UI")
        f.setPixelSize(int(s * 0.5))
        p.setFont(f)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "T")
    elif name == "translate":               # “文A”：原位翻译
        f = QFont("Microsoft YaHei UI")
        f.setPixelSize(int(s * 0.5))
        p.setFont(f)
        p.drawText(QRectF(0, 0, s * 0.62, s * 0.66), Qt.AlignmentFlag.AlignCenter, "文")
        f2 = QFont("Segoe UI")
        f2.setPixelSize(int(s * 0.5))
        f2.setBold(True)
        p.setFont(f2)
        p.drawText(QRectF(s * 0.4, s * 0.34, s * 0.6, s * 0.66), Qt.AlignmentFlag.AlignCenter, "A")
    elif name == "mirror":                  # 镜框 + 上面的标签：变成魔镜
        p.drawRoundedRect(QRectF(m * 0.7, s * 0.34, s - 1.4 * m, s * 0.5), 2, 2)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(s * 0.5, s * 0.16, s * 0.36, s * 0.16), 1.5, 1.5)
    p.end()
    return QIcon(pm)
