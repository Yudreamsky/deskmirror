"""截图上的标注：矩形、椭圆、箭头、画笔、荧光笔、文字、序号、马赛克，可以撤销、重做。

坐标是截下的图里的像素（物理像素，相对选区左上角），画到屏幕上时由截图界面缩放；存出来的图和屏幕上一样。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF

TOOLS = ("rect", "ellipse", "arrow", "pen", "highlight", "text", "number", "mosaic")
COLORS = ("#E5484D", "#F5A524", "#30A46C", "#3D8BFD", "#FFFFFF", "#1C1C1C")
WIDTHS = (2, 4, 7)
FONT = "Microsoft YaHei UI"


@dataclass
class Mark:
    tool: str
    color: QColor
    width: float
    pts: list[QPointF] = field(default_factory=list)   # 两点类：[起点, 终点]；画笔：轨迹；文字、序号：[位置]
    text: str = ""
    number: int = 0

    def rect(self) -> QRectF:
        a, b = self.pts[0], self.pts[-1]
        return QRectF(a, b).normalized()


def text_px(width: float) -> int:
    return int(14 + width * 3.2)


def number_d(width: float) -> float:
    return 18 + width * 3.0


def text_font(width: float) -> QFont:
    f = QFont(FONT)
    f.setPixelSize(text_px(width))
    return f


def bounds(m: Mark) -> QRectF:
    """标注占的范围（大致，判断要不要重画用）。"""
    if m.tool == "text":
        fm = QFontMetricsF(text_font(m.width))
        lines = m.text.split("\n") or [""]
        w = max(fm.horizontalAdvance(s) for s in lines)
        return QRectF(m.pts[0], m.pts[0] + QPointF(w, fm.height() * len(lines)))
    if m.tool == "number":
        r = number_d(m.width) / 2
        return QRectF(m.pts[0] - QPointF(r, r), m.pts[0] + QPointF(r, r))
    xs = [p.x() for p in m.pts]
    ys = [p.y() for p in m.pts]
    pad = m.width * 3 + 2
    return QRectF(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)


def _arrow(p: QPainter, a: QPointF, b: QPointF, color: QColor, width: float) -> None:
    """尾巴细、头大的箭头（和常见截图工具一样）。"""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = math.hypot(dx, dy)
    if length < 1:
        return
    ux, uy = dx / length, dy / length
    head = min(length * 0.6, 9 + width * 3.2)
    half = head * 0.55
    base = QPointF(b.x() - ux * head, b.y() - uy * head)
    nx, ny = -uy, ux
    tail = max(1.0, width * 0.35)
    neck = max(tail, width * 0.8)
    poly = QPolygonF([QPointF(a.x() + nx * tail, a.y() + ny * tail),
                      QPointF(base.x() + nx * neck, base.y() + ny * neck),
                      QPointF(base.x() + nx * half, base.y() + ny * half), b,
                      QPointF(base.x() - nx * half, base.y() - ny * half),
                      QPointF(base.x() - nx * neck, base.y() - ny * neck),
                      QPointF(a.x() - nx * tail, a.y() - ny * tail)])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawPolygon(poly)


def _stroke(pts: list[QPointF]) -> QPainterPath:
    path = QPainterPath(pts[0])
    if len(pts) == 1:
        path.lineTo(pts[0] + QPointF(0.01, 0))
        return path
    for i in range(1, len(pts) - 1):                 # 中点二次曲线：手画的线不起棱角
        mid = (pts[i] + pts[i + 1]) / 2
        path.quadTo(pts[i], mid)
    path.lineTo(pts[-1])
    return path


def mosaic(base: QImage, r: QRectF, cell: int) -> QImage:
    """把 base 里 r 那一块打成马赛克（先缩小再用最近邻放大回去）。"""
    rr = r.toAlignedRect().intersected(base.rect())
    if rr.isEmpty():
        return QImage()
    part = base.copy(rr)
    small = part.scaled(max(1, rr.width() // cell), max(1, rr.height() // cell), Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    return small.scaled(rr.width(), rr.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation)


def paint(p: QPainter, m: Mark, base: QImage | None = None) -> None:
    """把一个标注画上去（p 的坐标系 = 截下的图的像素）。马赛克要用原图 base。"""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if m.tool in ("rect", "ellipse"):
        p.setPen(QPen(m.color, m.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = m.rect()
        if m.tool == "rect":
            p.drawRect(r)
        else:
            p.drawEllipse(r)
    elif m.tool == "arrow" and len(m.pts) >= 2:
        _arrow(p, m.pts[0], m.pts[-1], m.color, m.width)
    elif m.tool in ("pen", "highlight") and m.pts:
        c = QColor(m.color)
        w = m.width
        if m.tool == "highlight":
            c.setAlpha(96)
            w = max(12.0, m.width * 4.5)
        p.setPen(QPen(c, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_stroke(m.pts))
    elif m.tool == "text" and m.text:
        p.setFont(text_font(m.width))
        fm = QFontMetricsF(p.font())
        y = m.pts[0].y() + fm.ascent()
        p.setPen(QPen(m.color))
        for line in m.text.split("\n"):
            p.drawText(QPointF(m.pts[0].x(), y), line)
            y += fm.height()
    elif m.tool == "number":
        d = number_d(m.width)
        c = m.pts[0]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(m.color))
        p.drawEllipse(c, d / 2, d / 2)
        f = QFont(FONT)
        f.setPixelSize(int(d * 0.58))
        f.setBold(True)
        p.setFont(f)
        light = m.color.lightness() > 170
        p.setPen(QColor("#1C1C1C") if light else QColor("#FFFFFF"))
        p.drawText(QRectF(c.x() - d / 2, c.y() - d / 2, d, d), Qt.AlignmentFlag.AlignCenter, str(m.number))
    elif m.tool == "mosaic" and base is not None and len(m.pts) >= 2:
        r = m.rect()
        img = mosaic(base, r, max(6, int(m.width * 3)))
        if not img.isNull():
            p.drawImage(r.toAlignedRect().intersected(base.rect()).topLeft(), img)
    p.restore()


class MarkStack:
    """画好的标注：撤销把最后一个拿走，重做放回去；画新的就清掉重做。"""

    def __init__(self) -> None:
        self.marks: list[Mark] = []
        self._redo: list[Mark] = []

    def add(self, m: Mark) -> None:
        self.marks.append(m)
        self._redo.clear()

    def undo(self) -> bool:
        if not self.marks:
            return False
        self._redo.append(self.marks.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self.marks.append(self._redo.pop())
        return True

    def next_number(self) -> int:
        return 1 + sum(1 for m in self.marks if m.tool == "number")

    def render(self, base: QImage) -> QImage:
        """原图 + 全部标注 → 新图（马赛克取原图的像素，不会把别的标注也打码）。"""
        out = base.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(out)
        for m in self.marks:
            paint(p, m, base)
        p.end()
        return out.convertToFormat(QImage.Format.Format_RGB32)
