"""截图（hotkeys.capture，默认 Ctrl+1）。按下时每块屏幕定格成一张图，上面盖一层全屏的截图界面：

- 鼠标停在哪就框住那个窗口、按钮、段落（snap.py），滚轮换大一层、小一层；按住拖动就自己画框。
- 框好以后：拖里面移动、拖边角改大小、方向键微调（Shift 一次 10 像素，按住 Ctrl 改大小）。
- 工具栏：矩形、椭圆、箭头、画笔、荧光笔、文字、序号、马赛克，撤销、重做；识别文字、原位翻译；
  变成魔镜（M，Shift+M 另开一个）、贴到屏幕（Ctrl+T）、保存（Ctrl+S）、复制（Enter、Ctrl+C、双击）、关闭（Esc）。
- 放大镜：光标附近放大，下面是坐标和颜色，按 C 复制颜色。右键：有选区就重选，没有就退出。

一个选区只在一块屏幕里。标注记在整块屏幕的图上（选区挪了，标注留在原地）。截下的图只在点“保存”时写硬盘
（交给 app）；识别、翻译经 app 给的 services 走引擎，原位翻译和平时一样先涂掉排除名单里的窗口。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from .. import geom, snap, winapi
from ..geom import Rect
from ..i18n import N_, tr
from . import marks as mk
from .icons import drawn, glyph
from .intrans import InPlace

log = logging.getLogger(__name__)

ACCENT = QColor("#3D8BFD")
DIM = QColor(0, 0, 0, 105)
INK = "#202124"
TWO_POINT = ("rect", "ellipse", "arrow", "mosaic")
HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
UIA_WARM_S = 0.4      # 一个窗口头一回答上来之后这么久里同一个点也再问：Chrome 这类程序被问了才开始建网页的无障碍树
_CURSORS = {"nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
            "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
            "inside": Qt.CursorShape.SizeAllCursor}
TOOL_TIPS = {"rect": N_("矩形"), "ellipse": N_("椭圆"), "arrow": N_("箭头"), "pen": N_("画笔"),
             "highlight": N_("荧光笔"), "text": N_("文字"), "number": N_("序号"), "mosaic": N_("马赛克")}


@dataclass
class PinData:
    """截图贴到屏幕上：图、原来在屏幕上的位置；做过原位翻译的话还有另一种样子（原文 / 译文），贴图上能来回换。"""
    image: QImage
    rect: Rect
    alt: QImage | None = None
    showing_translation: bool = False
    hwnd: int = 0                  # 主要来自哪个窗口（贴图上再做原位翻译时用）
    masks: list = None             # 截图那一刻排除名单里的窗口露在外面的部分（屏幕坐标）


@dataclass
class Shot:
    """一块屏幕按下快捷键那一刻的样子。"""
    mon: winapi.Monitor
    screen: object             # QScreen
    image: QImage              # 整块屏幕，物理像素，RGB32
    bgr: np.ndarray            # 同样的像素（高, 宽, 3），给识别用


def _norm(a: tuple[int, int], b: tuple[int, int]) -> Rect:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _clamp_rect(r: Rect, bound: Rect) -> Rect:
    """整个矩形挪回 bound 里（大小不变，除非比 bound 还大）。"""
    w, h = min(r[2] - r[0], bound[2] - bound[0]), min(r[3] - r[1], bound[3] - bound[1])
    x = max(bound[0], min(r[0], bound[2] - w))
    y = max(bound[1], min(r[1], bound[3] - h))
    return (x, y, x + w, y + h)


class SnipView(QWidget):
    """一块屏幕上的截图界面：铺满这块屏幕，画定格的图、暗下去的四周、选区、标注、放大镜。"""

    def __init__(self, session: "SnipSession", shot: Shot) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.s = session
        self.shot = shot
        self.mon = shot.mon
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        g = shot.screen.geometry()
        self.dpr = (self.mon.rect[2] - self.mon.rect[0]) / max(1, g.width())
        self.pix = QPixmap.fromImage(shot.image)
        self.pix.setDevicePixelRatio(self.dpr)
        self.winId()
        if self.windowHandle() is not None:
            self.windowHandle().setScreen(shot.screen)
        self.setGeometry(g)
        winapi.exclude_from_capture(int(self.winId()))      # 引擎还在截屏：别让它看到这层定格的图
        self._last_dyn: QRect | None = None

    def _hole(self) -> QRectF | None:
        s = self.s
        if s.sel is not None and s.sel_view is self:
            return self.local(s.sel)
        if s.state == "hover" and s.hover_view is self and s.current() is not None:
            return self.local(s.current().rect)
        return None

    def _dynamic(self) -> QRect:
        """会变的地方：框（连边框、上面的尺寸标签）和放大镜。整屏 4K 重画一次要十几毫秒，鼠标一动只重画这些。"""
        r = QRectF()
        hole = self._hole()
        if hole is not None:
            r = r.united(hole.adjusted(-8, -36, 8, 8))
        if self.s.magnifier_on(self):
            r = r.united(self._mag_box().adjusted(-3, -3, 3, 3))
        return r.toAlignedRect()

    def refresh(self) -> None:
        new = self._dynamic()
        if self._last_dyn is None:
            self.update()
        else:
            self.update(self._last_dyn.united(new))
        self._last_dyn = new

    # ------------------------------------------------------------------ 坐标
    def phys(self, pos: QPointF) -> tuple[int, int]:
        return (self.mon.rect[0] + int(round(pos.x() * self.dpr)), self.mon.rect[1] + int(round(pos.y() * self.dpr)))

    def local(self, r: Rect) -> QRectF:
        ox, oy = self.mon.rect[0], self.mon.rect[1]
        return QRectF((r[0] - ox) / self.dpr, (r[1] - oy) / self.dpr, (r[2] - r[0]) / self.dpr,
                      (r[3] - r[1]) / self.dpr)

    def local_pt(self, x: int, y: int) -> QPointF:
        return QPointF((x - self.mon.rect[0]) / self.dpr, (y - self.mon.rect[1]) / self.dpr)

    def hit(self, pos: QPointF) -> str:
        """鼠标在选区的哪儿：八个把手、里面、外面。"""
        if self.s.sel is None or self.s.sel_view is not self:
            return "outside"
        r = self.local(self.s.sel)
        k = 6.0
        near_l, near_r = abs(pos.x() - r.left()) <= k, abs(pos.x() - r.right()) <= k
        near_t, near_b = abs(pos.y() - r.top()) <= k, abs(pos.y() - r.bottom()) <= k
        in_x = r.left() - k <= pos.x() <= r.right() + k
        in_y = r.top() - k <= pos.y() <= r.bottom() + k
        if near_t and near_l:
            return "nw"
        if near_t and near_r:
            return "ne"
        if near_b and near_l:
            return "sw"
        if near_b and near_r:
            return "se"
        if near_t and in_x:
            return "n"
        if near_b and in_x:
            return "s"
        if near_l and in_y:
            return "w"
        if near_r and in_y:
            return "e"
        return "inside" if r.contains(pos) else "outside"

    # ------------------------------------------------------------------ 画
    def paintEvent(self, _e) -> None:
        s = self.s
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pix)
        full = QRectF(self.rect())
        hole = self._hole()
        if s.marks.marks or s.cur_mark is not None:
            self._paint_marks(p)
        if hole is None:
            p.fillRect(full, DIM)
        else:
            for r in (QRectF(full.left(), full.top(), full.width(), hole.top() - full.top()),
                      QRectF(full.left(), hole.bottom(), full.width(), full.bottom() - hole.bottom()),
                      QRectF(full.left(), hole.top(), hole.left() - full.left(), hole.height()),
                      QRectF(hole.right(), hole.top(), full.right() - hole.right(), hole.height())):
                if r.width() > 0 and r.height() > 0:
                    p.fillRect(r, DIM)
            self._paint_hole(p, hole, s.sel is not None and s.sel_view is self)
        if s.magnifier_on(self):
            self._paint_magnifier(p)
        p.end()

    def _paint_marks(self, p: QPainter) -> None:
        s = self.s
        p.save()
        if s.sel is not None and s.sel_view is self:
            p.setClipRect(self.local(s.sel))
        p.scale(1 / self.dpr, 1 / self.dpr)
        base = s.composite(self)
        for m in s.marks.marks if s.sel_view is self else []:
            mk.paint(p, m, base)
        if s.cur_mark is not None and s.sel_view is self:
            mk.paint(p, s.cur_mark, base)
        p.restore()

    def _paint_hole(self, p: QPainter, hole: QRectF, selected: bool) -> None:
        s = self.s
        if selected and s.show_tr and s.translated is not None:
            p.save()
            p.setClipRect(hole)
            p.translate(hole.topLeft())
            p.scale(1 / self.dpr, 1 / self.dpr)
            p.drawImage(QPointF(0, 0), s.translated)
            p.restore()
            if s.marks.marks or s.cur_mark is not None:
                self._paint_marks(p)         # 标注画在译文上面
        p.setPen(QPen(ACCENT, 2 if not selected else 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(hole.adjusted(0.75, 0.75, -0.75, -0.75))
        if selected and s.tool is None and s.editor is None:
            p.setPen(QPen(QColor("white"), 1))
            p.setBrush(ACCENT)
            for c in self._handle_points(hole):
                p.drawRect(QRectF(c.x() - 3.5, c.y() - 3.5, 7, 7))
        r = s.sel if selected else s.current().rect
        self._badge(p, hole, f"{r[2] - r[0]} × {r[3] - r[1]}")

    @staticmethod
    def _handle_points(r: QRectF) -> list[QPointF]:
        cx, cy = r.center().x(), r.center().y()
        return [QPointF(r.left(), r.top()), QPointF(cx, r.top()), QPointF(r.right(), r.top()),
                QPointF(r.right(), cy), QPointF(r.right(), r.bottom()), QPointF(cx, r.bottom()),
                QPointF(r.left(), r.bottom()), QPointF(r.left(), cy)]

    def _badge(self, p: QPainter, hole: QRectF, text: str) -> None:
        f = QFont("Segoe UI")
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetricsF(f)
        w, h = fm.horizontalAdvance(text) + 12, fm.height() + 6
        y = hole.top() - h - 4
        if y < 2:
            y = hole.top() + 4
        box = QRectF(max(2.0, hole.left()), y, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 24, 210))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    MAG, MAG_INFO, MAG_N = 150.0, 40.0, 15

    def _mag_box(self) -> QRectF:
        """放大镜（连下面的坐标、颜色）在窗口里的位置：光标右下，靠边就翻到另一边。"""
        lp = self.local_pt(*self.s.mouse)
        bx, by = lp.x() + 22, lp.y() + 22
        if bx + self.MAG > self.width() - 4:
            bx = lp.x() - 22 - self.MAG
        if by + self.MAG + self.MAG_INFO > self.height() - 4:
            by = lp.y() - 22 - self.MAG - self.MAG_INFO
        return QRectF(bx, by, self.MAG, self.MAG + self.MAG_INFO)

    def _paint_magnifier(self, p: QPainter) -> None:
        x, y = self.s.mouse
        ix, iy = x - self.mon.rect[0], y - self.mon.rect[1]
        n = self.MAG_N
        zoom_box = self.MAG
        src = self.shot.image.copy(QRect(ix - n // 2, iy - n // 2, n, n))
        info_h = self.MAG_INFO
        mb = self._mag_box()
        bx, by = mb.x(), mb.y()
        box = QRectF(bx, by, zoom_box, zoom_box)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(box, src)
        cell = zoom_box / n
        c = QColor(ACCENT)
        c.setAlpha(110)
        p.fillRect(QRectF(box.left(), box.top() + cell * (n // 2), zoom_box, cell), c)
        p.fillRect(QRectF(box.left() + cell * (n // 2), box.top(), cell, zoom_box), c)
        p.setPen(QPen(QColor("white"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        color = self.shot.image.pixelColor(max(0, min(self.shot.image.width() - 1, ix)),
                                           max(0, min(self.shot.image.height() - 1, iy)))
        info = QRectF(bx, by + zoom_box, zoom_box, info_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 24, 225))
        p.drawRect(info)
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("white"))
        msg = self.s.color_message()
        line2 = msg or f"{color.name().upper()}   " + tr("按 C 复制颜色")
        p.drawText(info.adjusted(6, 3, -4, -info_h / 2), Qt.AlignmentFlag.AlignVCenter, f"{x}, {y}")
        sw = QRectF(info.left() + 6, info.top() + info_h / 2 + 3, 10, 10)
        p.fillRect(sw, color)
        p.drawText(info.adjusted(20, info_h / 2, -4, -2), Qt.AlignmentFlag.AlignVCenter, line2)
        p.restore()

    # ------------------------------------------------------------------ 鼠标、键盘
    def mousePressEvent(self, e) -> None:
        self.s.press(self, e.position(), e.button(), e.modifiers())

    def mouseMoveEvent(self, e) -> None:
        self.s.move(self, e.position(), e.modifiers())

    def mouseReleaseEvent(self, e) -> None:
        self.s.release(self, e.position(), e.button(), e.modifiers())

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.hit(e.position()) == "inside" and self.s.tool is None:
            self.s.copy()

    def wheelEvent(self, e) -> None:
        self.s.wheel(e.angleDelta().y())

    def keyPressEvent(self, e) -> None:
        if not self.s.key(e):
            super().keyPressEvent(e)


class Toolbar(QFrame):
    """选区下面的工具栏（第二排是画图工具的颜色和粗细）。"""

    def __init__(self, session: "SnipSession", parent: QWidget) -> None:
        super().__init__(parent)
        self.s = session
        self.setObjectName("snipbar")
        self.setStyleSheet("QFrame#snipbar { background: #FAFAFA; border: 1px solid #C8C8CC; border-radius: 6px; }"
                           "QToolButton { border: none; border-radius: 4px; padding: 3px; }"
                           "QToolButton:hover { background: #E8E8EC; }"
                           "QToolButton:checked { background: #D6E4FF; }"
                           "QLabel { color: #555; padding: 0 6px; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(1)
        outer.addLayout(row)
        self.buttons: dict[str, QToolButton] = {}

        def add(key: str, icon, tip: str, cb, checkable: bool = False) -> None:
            b = QToolButton(self)
            b.setIcon(icon)
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(cb)
            row.addWidget(b)
            self.buttons[key] = b

        def sep() -> None:
            line = QFrame(self)
            line.setFixedSize(1, 18)
            line.setStyleSheet("background: #D0D0D4;")
            row.addSpacing(3)
            row.addWidget(line)
            row.addSpacing(3)

        for t in mk.TOOLS:
            add(t, drawn(t, INK), tr(TOOL_TIPS[t]), lambda _c=False, t=t: session.set_tool(t), checkable=True)
        sep()
        add("undo", glyph(0xE7A7, INK), tr("撤销（Ctrl+Z）"), session.undo)
        add("redo", glyph(0xE7A6, INK), tr("重做（Ctrl+Y）"), session.redo)
        sep()
        add("ocr", drawn("ocr", INK), tr("识别文字：认出选区里的字，可以复制"), session.ocr)
        add("translate", drawn("translate", INK), tr("原位翻译：选区里的字换成译文，再点换回原文"),
            session.toggle_translate, checkable=True)
        sep()
        add("mirror", drawn("mirror", INK), tr("变成魔镜（M）：魔镜挪到这里；按住 Shift 点就另开一个"), session.to_mirror)
        add("pin", glyph(0xE718, INK), tr("贴到屏幕（Ctrl+T）"), session.pin)
        add("save", glyph(0xE74E, INK), tr("保存（Ctrl+S）"), session.save)
        add("copy", glyph(0xE8C8, INK), tr("复制（Enter、Ctrl+C、双击选区）"), session.copy)
        add("close", glyph(0xE711, INK), tr("关闭（Esc）"), session.cancel)
        self.status = QLabel("", self)
        self.status.hide()
        row.addWidget(self.status)
        self.opts = QWidget(self)
        orow = QHBoxLayout(self.opts)
        orow.setContentsMargins(2, 0, 2, 2)
        orow.setSpacing(4)
        self.swatches: list[QToolButton] = []
        for c in mk.COLORS:
            b = QToolButton(self.opts)
            b.setCheckable(True)
            b.setFixedSize(20, 20)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(f"QToolButton {{ background: {c}; border: 1px solid #9A9AA0; border-radius: 10px; }}"
                            "QToolButton:checked { border: 2px solid #3D8BFD; }")
            b.clicked.connect(lambda _c=False, c=c: session.set_color(c))
            orow.addWidget(b)
            self.swatches.append(b)
        orow.addSpacing(8)
        self.widths: list[QToolButton] = []
        for w in mk.WIDTHS:
            b = QToolButton(self.opts)
            b.setCheckable(True)
            b.setFixedSize(24, 22)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setIcon(self._dot(w))
            b.setToolTip(tr("粗细"))
            b.clicked.connect(lambda _c=False, w=w: session.set_width(w))
            orow.addWidget(b)
            self.widths.append(b)
        orow.addStretch(1)
        outer.addWidget(self.opts)
        self.opts.hide()

    @staticmethod
    def _dot(w: int):
        from PySide6.QtGui import QIcon
        pm = QPixmap(36, 36)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(INK))
        d = 3 + w * 1.2
        p.drawEllipse(QPointF(9, 9), d / 2, d / 2)
        p.end()
        return QIcon(pm)

    def sync(self) -> None:
        s = self.s
        for t in mk.TOOLS:
            self.buttons[t].setChecked(s.tool == t)
        self.buttons["translate"].setChecked(bool(s.show_tr and s.translated is not None))
        self.opts.setVisible(s.tool is not None)
        for b, c in zip(self.swatches, mk.COLORS):
            b.setChecked(QColor(c) == s.color)
        for b, w in zip(self.widths, mk.WIDTHS):
            b.setChecked(w == s.width)
        self.adjustSize()

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))
        self.adjustSize()


class TextWindow(QWidget):
    """识别文字的结果：可以改、可以复制，截图关掉以后还留着，点关闭才没。"""

    def __init__(self, text: str, near: QPoint) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(tr("识别出的文字"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        copy = QPushButton(tr("复制"))
        copy.clicked.connect(self._copy)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.close)
        row.addWidget(copy)
        row.addWidget(close)
        lay.addLayout(row)
        self.resize(460, 300)
        self.move(near)
        winapi.exclude_from_capture(int(self.winId()))

    def _copy(self) -> None:
        cur = self.edit.textCursor()
        QGuiApplication.clipboard().setText(cur.selectedText().replace(" ", "\n") if cur.hasSelection()
                                            else self.edit.toPlainText())


class SnipSession(QObject):
    """一次截图：从按下快捷键到复制、保存、贴图、变成魔镜或关掉。界面线程里用。"""
    finished = Signal()
    copy_requested = Signal(QImage)
    save_requested = Signal(QImage)
    pin_requested = Signal(object)               # PinData：图、原来在屏幕上的位置、另一种样子（原文 / 译文）
    mirror_requested = Signal(object, bool)      # 选区（物理像素），另开一个
    text_requested = Signal(str, object)         # 认出的字，选区
    _uia_done = Signal(object, object)

    def __init__(self, shots: list[Shot], windows: list[tuple[int, Rect]], cfg, services,
                 masks: list[Rect] | None = None) -> None:
        super().__init__()
        self.masks = masks or []                 # 截图这一刻排除名单里的窗口露在外面的部分（原位翻译前涂掉）
        self.shots = shots
        self.windows = windows
        self.cfg = cfg
        self.services = services
        self.state = "hover"                     # hover / drag / selected
        self.sel: Rect | None = None
        self.sel_view: SnipView | None = None
        self.hover_view: SnipView | None = None
        self.mouse = winapi.cursor_pos()
        self.chain: list[snap.Candidate] = []
        self.level = 0
        self.drag: dict | None = None
        self.tool: str | None = None
        self.color = QColor(mk.COLORS[0])
        self.width = mk.WIDTHS[1]
        self.marks = mk.MarkStack()
        self.cur_mark: mk.Mark | None = None
        self.editor = None
        self._inplace: InPlace | None = None
        self.show_tr = False
        self._gen = 0
        self._composite: tuple | None = None
        self.texts: dict[str, list[Rect]] = {}
        self._children: dict[int, list[Rect]] = {}
        self.uia_rects: list[Rect] = []
        self.uia_hwnd = 0
        self._uia_token = 0
        self._uia_asked: tuple = (0, 0, None)
        self._uia_at: tuple[int, int] | None = None   # 上次答的是哪个点
        self._uia_first: dict[int, float] = {}        # 每个窗口头一回答上来的时间
        self.prev_focus = winapi.foreground_window()  # 截图前在用的窗口：关掉截图界面后焦点还给它
        self.restore_focus = True                     # 贴图、识别出的字的窗口要自己拿焦点时不还
        self._color_msg = ("", 0.0)
        self.closed = False
        self._uia_timer = QTimer(self)
        self._uia_timer.setSingleShot(True)
        self._uia_timer.setInterval(70)
        self._uia_timer.timeout.connect(self._ask_uia)
        self._uia_done.connect(self._on_uia)
        self.probe = snap.UiaProbe(lambda tok, rects: self._uia_done.emit(tok, rects)) if cfg.capture.snap else None
        self.views = [SnipView(self, s) for s in shots]
        self.toolbar: Toolbar | None = None

    # ------------------------------------------------------------------ 开始、结束
    def start(self) -> None:
        for v in self.views:
            v.show()
        v = self.view_at(*self.mouse) or self.views[0]
        v.raise_()
        v.activateWindow()
        v.setFocus()
        self.hover(*self.mouse)
        if self.cfg.capture.snap:
            order = sorted(self.shots, key=lambda s: not geom.contains_pt(s.mon.rect, *self.mouse))
            for s in order:              # 先找光标所在那块屏幕上的文字段落
                self.services.ocr(s.bgr, (s.mon.rect[0], s.mon.rect[1]),
                                  lambda kind, data, d=s.mon.device: self._on_paras(d, kind, data), detect_only=True)

    def _finish(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._gen += 1
        if self.probe is not None:
            self.probe.close()
        if self.restore_focus:
            # 不然 Windows 把焦点交给 Z 序里下一个窗口（不一定是原来那个）：Enter 复制完 Ctrl+V 会粘错地方
            winapi.give_focus(self.prev_focus)
        for v in self.views:
            v.hide()
            v.deleteLater()
        self.finished.emit()

    def cancel(self) -> None:
        self._finish()

    # ------------------------------------------------------------------ 自动框选
    def view_at(self, x: int, y: int) -> SnipView | None:
        return next((v for v in self.views if geom.contains_pt(v.mon.rect, x, y)), None)

    def current(self) -> snap.Candidate | None:
        if not self.chain:
            return None
        return self.chain[max(0, min(self.level, len(self.chain) - 1))]

    def _chain_at(self, x: int, y: int, v: SnipView) -> list[snap.Candidate]:
        top = snap.window_at(x, y, self.windows)
        hwnd, wrect = top if top is not None else (0, None)
        if hwnd and hwnd not in self._children:
            self._children[hwnd] = snap.child_rects(hwnd)
        uia = self.uia_rects if hwnd and self.uia_hwnd == hwnd else []
        return snap.build_chain(x, y, v.mon.rect, wrect, [("element", uia), ("text", self.texts.get(v.mon.device, [])),
                                                         ("child", self._children.get(hwnd, []))])

    def hover(self, x: int, y: int) -> None:
        self.mouse = (x, y)
        v = self.view_at(x, y)
        old = self.hover_view
        self.hover_view = v
        if self.state == "hover":
            new = self._chain_at(x, y, v) if v is not None and self.cfg.capture.snap else []
            if new != self.chain:
                keep = self.current()
                self.chain = new
                self.level = self._same_level(new, keep) if keep is not None and self.level > 0 else 0
            if self.probe is not None:
                self._uia_timer.start()
        for w in {old, v}:
            if w is not None:
                w.refresh()

    @staticmethod
    def _same_level(new: list[snap.Candidate], keep: snap.Candidate) -> int:
        """换了一组候选时停在哪一层：还有原来那个框就停在它上面；没有就停在同一种、大小最接近的那个
        （滚轮选好的“整个窗口”、列表里的一项，鼠标一动或者界面元素晚一点答上来，都不要跳回最小的）。"""
        for i, c in enumerate(new):
            if c.rect == keep.rect:
                return i
        same = [i for i, c in enumerate(new) if c.kind == keep.kind]
        if not same:
            return 0
        return min(same, key=lambda i: abs(geom.area(new[i].rect) - geom.area(keep.rect)))

    def _ask_uia(self) -> None:
        if self.closed or self.probe is None or self.state != "hover":
            return
        x, y = self.mouse
        top = snap.window_at(x, y, self.windows)
        if top is None:
            return
        hwnd = top[0]
        first = self._uia_first.get(hwnd)
        warm = first is not None and time.monotonic() - first > UIA_WARM_S
        if warm and self.uia_hwnd == hwnd and self._uia_at == (x, y):
            return                   # 这个点问过了
        self._uia_token += 1
        self._uia_asked = (self._uia_token, hwnd, (x, y))
        self.probe.ask(self._uia_token, hwnd, x, y)

    def _on_uia(self, token, rects) -> None:
        if self.closed or token != self._uia_asked[0]:
            return
        self.uia_hwnd = self._uia_asked[1]
        self._uia_at = self._uia_asked[2]
        self.uia_rects = list(rects)
        self._uia_first.setdefault(self.uia_hwnd, time.monotonic())
        if self.state == "hover":
            self.hover(*self.mouse)

    def _on_paras(self, device: str, kind: str, data) -> None:
        if self.closed or kind != "paras":
            return
        self.texts[device] = [tuple(r) for r in data]
        if self.state == "hover":
            self.hover(*self.mouse)

    def wheel(self, delta: int) -> None:
        if self.state == "hover" and self.chain and delta:
            self.level = max(0, min(len(self.chain) - 1, self.level + (1 if delta > 0 else -1)))
            if self.hover_view is not None:
                self.hover_view.refresh()

    def magnifier_on(self, v: SnipView) -> bool:
        if not self.cfg.capture.magnifier or self.hover_view is not v:
            return False
        if self.state == "hover":
            return True
        return self.drag is not None and self.drag.get("mode") in ("new",) + HANDLES

    def color_message(self) -> str:
        text, t = self._color_msg
        return text if text and time.monotonic() - t < 1.5 else ""

    # ------------------------------------------------------------------ 鼠标
    def press(self, v: SnipView, pos: QPointF, button, mods) -> None:
        x, y = v.phys(pos)
        if button == Qt.MouseButton.RightButton:
            if self.editor is not None:
                self._close_editor(commit=False)
            elif self.state == "selected":
                self.clear_selection()
            else:
                self.cancel()
            return
        if button != Qt.MouseButton.LeftButton:
            return
        if self.editor is not None:
            self._close_editor(commit=True)
            return
        if self.state == "hover":
            self.drag = {"mode": "new", "start": (x, y), "view": v, "moved": False}
            self.state = "drag"
            return
        if self.state != "selected":
            return
        hit = v.hit(pos)
        if self.tool is not None and hit in ("inside",) + HANDLES and v is self.sel_view:
            self._start_mark(x, y, mods)
            return
        if self.tool is None and hit != "outside":
            self.drag = {"mode": hit, "start": (x, y), "orig": self.sel}
            return
        if hit == "outside" and not self.marks.marks and self.translated is None:
            self.clear_selection()
            self.drag = {"mode": "new", "start": (x, y), "view": v, "moved": False}
            self.state = "drag"

    def move(self, v: SnipView, pos: QPointF, mods) -> None:
        x, y = v.phys(pos)
        if self.drag is None:
            if self.state == "hover":
                self.hover(x, y)
            elif self.state == "selected":
                self.mouse = (x, y)
                hit = v.hit(pos)
                if self.tool is not None:
                    v.setCursor(Qt.CursorShape.CrossCursor if hit != "outside" else Qt.CursorShape.ArrowCursor)
                else:
                    v.setCursor(_CURSORS.get(hit, Qt.CursorShape.ArrowCursor))
            return
        mode = self.drag["mode"]
        if mode == "new":
            dv = self.drag["view"]
            sx, sy = self.drag["start"]
            if not self.drag["moved"] and abs(x - sx) + abs(y - sy) < 4 * dv.dpr:
                return
            self.drag["moved"] = True
            b = dv.mon.rect
            x, y = max(b[0], min(b[2], x)), max(b[1], min(b[3], y))
            self.mouse = (x, y)
            self.sel_view = dv
            self.sel = _norm((sx, sy), (x, y))
            self.hover_view = dv
            dv.refresh()
            return
        if mode == "mark":
            self._extend_mark(x, y, mods)
            return
        sx, sy = self.drag["start"]
        dx, dy = x - sx, y - sy
        o = self.drag["orig"]
        b = self.sel_view.mon.rect
        self.mouse = (x, y)
        if mode == "inside":
            r = _clamp_rect((o[0] + dx, o[1] + dy, o[2] + dx, o[3] + dy), b)
        else:
            l, t, r_, bt = o
            if "w" in mode:
                l = o[0] + dx
            if "e" in mode:
                r_ = o[2] + dx
            if "n" in mode:
                t = o[1] + dy
            if "s" in mode:
                bt = o[3] + dy
            r = _norm((max(b[0], min(b[2], l)), max(b[1], min(b[3], t))),
                      (max(b[0], min(b[2], r_)), max(b[1], min(b[3], bt))))
        if r != self.sel and r[2] - r[0] >= 1 and r[3] - r[1] >= 1:
            self.sel = r
            self._selection_changed()
            self.sel_view.refresh()
            self._place_toolbar()

    def release(self, v: SnipView, pos: QPointF, button, mods) -> None:
        if button != Qt.MouseButton.LeftButton or self.drag is None:
            return
        d = self.drag
        self.drag = None
        if d["mode"] == "new":
            if not d["moved"]:
                c = self.current()
                self.sel_view = d["view"]
                self.sel = c.rect if c is not None else d["view"].mon.rect
            if self.sel is None or self.sel[2] - self.sel[0] < 2 or self.sel[3] - self.sel[1] < 2:
                self.clear_selection()
                return
            self.state = "selected"
            self._selection_changed()
            after = self.cfg.capture.after
            if after == "copy":
                self.copy()
                return
            if after == "pin":
                self.pin()
                return
            self._show_toolbar()
            self.sel_view.update()
            return
        if d["mode"] == "mark":
            self._end_mark()
            return
        self._place_toolbar()

    def clear_selection(self) -> None:
        if self.editor is not None:
            self._close_editor(commit=False)
        v = self.sel_view
        self.sel = None
        self.sel_view = None
        self.state = "hover"
        self.tool = None
        self.marks = mk.MarkStack()
        self.cur_mark = None
        self._selection_changed()
        if self.toolbar is not None:
            self.toolbar.hide()
            self.toolbar.deleteLater()
            self.toolbar = None
        if v is not None:
            v.setCursor(Qt.CursorShape.CrossCursor)
            v.update()
        self.hover(*self.mouse)

    @property
    def translated(self) -> QImage | None:
        return self._inplace.result if self._inplace is not None else None

    @property
    def tr_busy(self) -> bool:
        return self._inplace is not None and self._inplace.busy

    def _selection_changed(self) -> None:
        if self._inplace is not None:
            self._inplace.cancel()               # 位置变了：进行中的识别、翻译作废
            self._inplace = None
            self.show_tr = False
            self._composite = None
            self._status("")
        self._gen += 1
        if self.toolbar is not None:
            self.toolbar.sync()

    # ------------------------------------------------------------------ 键盘
    def key(self, e) -> bool:
        k = e.key()
        mods = e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if self.editor is not None:
            if k == Qt.Key.Key_Escape:
                self._close_editor(commit=False)
                return True
            return False
        if k == Qt.Key.Key_Escape:
            self.cancel()
            return True
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (ctrl and k == Qt.Key.Key_C):
            if self.state == "hover" and self.current() is not None:
                self.sel_view, self.sel, self.state = self.hover_view, self.current().rect, "selected"
            self.copy()
            return True
        if k == Qt.Key.Key_C and not ctrl and self.state in ("hover", "drag"):
            self._copy_color()
            return True
        if self.state != "selected":
            if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
                step = 10 if shift else 1
                dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(k, 0)
                dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(k, 0)
                x, y = winapi.cursor_pos()
                _set_cursor(x + dx, y + dy)
                return True
            return False
        if ctrl and k == Qt.Key.Key_S:
            self.save()
        elif ctrl and k == Qt.Key.Key_T:
            self.pin()
        elif ctrl and k == Qt.Key.Key_Z:
            self.redo() if shift else self.undo()
        elif ctrl and k == Qt.Key.Key_Y:
            self.redo()
        elif k == Qt.Key.Key_M and not ctrl:
            self.to_mirror(new=shift)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 10 if shift else 1
            dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(k, 0)
            dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(k, 0)
            l, t, r, b = self.sel
            r = (l, t, max(l + 1, r + dx), max(t + 1, b + dy)) if ctrl else (l + dx, t + dy, r + dx, b + dy)
            self.sel = _clamp_rect(r, self.sel_view.mon.rect)
            self._selection_changed()
            self.sel_view.update()
            self._place_toolbar()
        else:
            return False
        return True

    def _copy_color(self) -> None:
        v = self.view_at(*self.mouse)
        if v is None:
            return
        ix, iy = self.mouse[0] - v.mon.rect[0], self.mouse[1] - v.mon.rect[1]
        if not (0 <= ix < v.shot.image.width() and 0 <= iy < v.shot.image.height()):
            return
        name = v.shot.image.pixelColor(ix, iy).name().upper()
        QGuiApplication.clipboard().setText(name)
        self._color_msg = (tr("已复制 {color}").format(color=name), time.monotonic())
        v.update()

    # ------------------------------------------------------------------ 标注
    def set_tool(self, tool: str) -> None:
        if self.editor is not None:
            self._close_editor(commit=True)
        self.tool = None if self.tool == tool else tool
        if self.toolbar is not None:
            self.toolbar.sync()
            self._place_toolbar()
        if self.sel_view is not None:
            self.sel_view.update()

    def set_color(self, c: str) -> None:
        self.color = QColor(c)
        if self.toolbar is not None:
            self.toolbar.sync()

    def set_width(self, w: int) -> None:
        self.width = w
        if self.toolbar is not None:
            self.toolbar.sync()

    def _img_pt(self, x: int, y: int) -> QPointF:
        """屏幕物理坐标 → 选区所在那块屏幕的图里的坐标（标注都记在这里）。"""
        m = self.sel_view.mon.rect
        return QPointF(x - m[0], y - m[1])

    def _start_mark(self, x: int, y: int, mods) -> None:
        pt = self._img_pt(x, y)
        if self.tool == "text":
            self._open_editor(pt)
            return
        if self.tool == "number":
            self.marks.add(mk.Mark("number", QColor(self.color), self.width, [pt], number=self.marks.next_number()))
            self.sel_view.update()
            return
        self.cur_mark = mk.Mark(self.tool, QColor(self.color), self.width, [pt, QPointF(pt)] if self.tool in TWO_POINT
                                else [pt])
        self.drag = {"mode": "mark"}

    def _extend_mark(self, x: int, y: int, mods) -> None:
        m = self.cur_mark
        if m is None:
            return
        pt = self._img_pt(x, y)
        if m.tool in TWO_POINT:
            a = m.pts[0]
            if mods & Qt.KeyboardModifier.ShiftModifier and m.tool in ("rect", "ellipse", "mosaic"):
                side = max(abs(pt.x() - a.x()), abs(pt.y() - a.y()))         # Shift：正方形、正圆
                pt = QPointF(a.x() + side * (1 if pt.x() >= a.x() else -1), a.y() + side * (1 if pt.y() >= a.y() else -1))
            m.pts[-1] = pt
        else:
            last = m.pts[-1]
            if abs(pt.x() - last.x()) + abs(pt.y() - last.y()) >= 1.5:
                m.pts.append(pt)
        self.sel_view.refresh()

    def _end_mark(self) -> None:
        m = self.cur_mark
        self.cur_mark = None
        if m is None:
            return
        if m.tool in TWO_POINT:
            a, b = m.pts[0], m.pts[-1]
            if abs(a.x() - b.x()) + abs(a.y() - b.y()) < 3:
                self.sel_view.update()
                return
        self.marks.add(m)
        self._composite = None
        self.sel_view.update()

    def _open_editor(self, pt: QPointF) -> None:
        v = self.sel_view
        ed = QLineEdit(v)
        f = mk.text_font(self.width)
        f.setPixelSize(max(9, int(round(mk.text_px(self.width) / v.dpr))))
        ed.setFont(f)
        ed.setFrame(False)
        ed.setTextMargins(0, 0, 0, 0)
        ed.setStyleSheet(f"QLineEdit {{ background: rgba(255, 255, 255, 140); color: {self.color.name()};"
                         f" border: 1px dashed {ACCENT.name()}; padding: 0px; }}")
        lp = QPointF(pt.x() / v.dpr, pt.y() / v.dpr)
        ed.move(int(lp.x()) - 1, int(lp.y()) - 1)
        ed.resize(260, int(QFontMetricsF(f).height()) + 4)
        ed.returnPressed.connect(lambda: self._close_editor(commit=True))
        ed.show()
        ed.setFocus()
        self.editor = (ed, pt, QColor(self.color), self.width)

    def _close_editor(self, commit: bool) -> None:
        if self.editor is None:
            return
        ed, pt, color, width = self.editor
        self.editor = None
        text = ed.text().strip()
        ed.hide()
        ed.deleteLater()
        if commit and text:
            self.marks.add(mk.Mark("text", color, width, [pt], text=text))
            self._composite = None
        if self.sel_view is not None:
            self.sel_view.setFocus()
            self.sel_view.update()

    def undo(self) -> None:
        if self.editor is None and self.marks.undo():
            self._composite = None
            self.sel_view.update()

    def redo(self) -> None:
        if self.editor is None and self.marks.redo():
            self._composite = None
            self.sel_view.update()

    def composite(self, v: SnipView) -> QImage:
        """马赛克要从“现在看到的样子”取像素：整块屏幕的图，原位翻译开着时叠上译文。"""
        if not (self.show_tr and self.translated is not None and v is self.sel_view):
            return v.shot.image
        if self._composite is None or self._composite[0] is not self.translated:
            img = v.shot.image.copy()
            p = QPainter(img)
            p.drawImage(QPointF(self.sel[0] - v.mon.rect[0], self.sel[1] - v.mon.rect[1]), self.translated)
            p.end()
            self._composite = (self.translated, img)
        return self._composite[1]

    # ------------------------------------------------------------------ 出图
    def crop(self) -> QImage:
        v = self.sel_view
        m = v.mon.rect
        return v.shot.image.copy(QRect(self.sel[0] - m[0], self.sel[1] - m[1], self.sel[2] - self.sel[0],
                                       self.sel[3] - self.sel[1]))

    def crop_bgr(self) -> np.ndarray:
        v = self.sel_view
        m = v.mon.rect
        return v.shot.bgr[self.sel[1] - m[1]:self.sel[3] - m[1], self.sel[0] - m[0]:self.sel[2] - m[0]]

    def final_image(self, translated: bool | None = None) -> QImage | None:
        """选区 + 译文（开着的话）+ 标注：复制、保存、贴图的就是它，和屏幕上看到的一样。
        translated：指定要原文还是译文的样子（贴图两种都要）；None = 现在显示的那种。"""
        if self.sel is None or self.sel_view is None:
            return None
        if self.editor is not None:
            self._close_editor(commit=True)
        use_tr = (self.show_tr if translated is None else translated) and self.translated is not None
        base = self.translated if use_tr else self.crop()
        if not self.marks.marks:
            return base.copy()
        out = base.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(out)
        m = self.sel_view.mon.rect
        p.translate(-(self.sel[0] - m[0]), -(self.sel[1] - m[1]))
        full = self.composite(self.sel_view)
        for mark in self.marks.marks:
            mk.paint(p, mark, full)
        p.end()
        return out.convertToFormat(QImage.Format.Format_RGB32)

    def copy(self) -> None:
        img = self.final_image()
        if img is not None:
            self.copy_requested.emit(img)
        self._finish()

    def save(self) -> None:
        img = self.final_image()
        if img is not None:
            self.save_requested.emit(img)
        self._finish()

    def pin(self) -> None:
        img = self.final_image()
        if img is not None:
            alt = self.final_image(translated=not self.show_tr) if self.translated is not None else None
            self.restore_focus = False           # 贴图自己拿焦点（Esc、Ctrl+C 马上能用）
            self.pin_requested.emit(PinData(img, self.sel, alt, self.show_tr and alt is not None,
                                            self._window_under_selection(), self.masks))
        self._finish()

    def to_mirror(self, new: bool = False) -> None:
        if self.sel is None:
            return
        if QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            new = True
        self.mirror_requested.emit(self.sel, new)
        self._finish()

    # ------------------------------------------------------------------ 识别文字、原位翻译
    def _status(self, text: str) -> None:
        if self.toolbar is not None:
            self.toolbar.set_status(text)
            self._place_toolbar()

    def _window_under_selection(self) -> int:
        top = snap.window_at(*[int(v) for v in geom.center(self.sel)], self.windows)
        return top[0] if top is not None else 0

    def ocr(self) -> None:
        if self.sel is None:
            return
        gen = self._gen
        blocks: list = []
        self._status(tr("正在识别…"))

        def on_ocr(kind: str, data) -> None:
            if gen != self._gen or self.closed:
                return
            if kind == "blocks":
                blocks.extend(b for b in data if b.text.strip())
            elif kind == "error":
                self._status(str(data))
            elif kind == "done":
                if not blocks:
                    self._status(tr("选区里没认出字"))
                    return
                blocks.sort(key=lambda b: (b.rect[1] // 12, b.rect[0]))
                self.restore_focus = False           # 识别出的字的窗口自己拿焦点
                self.text_requested.emit("\n".join(b.text for b in blocks), self.sel)
                self._finish()
        self.services.ocr(self.crop_bgr(), (self.sel[0], self.sel[1]), on_ocr)

    def toggle_translate(self) -> None:
        if self.sel is None:
            return
        if self._inplace is not None:
            if self._inplace.result is not None:
                self.show_tr = not self.show_tr      # 译好了：原文、译文来回换
                self._composite = None
                self.sel_view.update()
            if self.toolbar is not None:
                self.toolbar.sync()
            return
        job = InPlace(self.services, self.cfg.style, self.crop(), (self.sel[0], self.sel[1]),
                      self._window_under_selection(), self.masks)
        job.updated.connect(self._on_inplace)
        job.status.connect(self._status)
        self._inplace = job
        self.show_tr = True
        job.start()
        if self.toolbar is not None:
            self.toolbar.sync()

    def _on_inplace(self) -> None:
        self._composite = None
        if self.toolbar is not None:
            self.toolbar.sync()
        if self.sel_view is not None:
            self.sel_view.update()

    # ------------------------------------------------------------------ 工具栏
    def _show_toolbar(self) -> None:
        if self.toolbar is None:
            self.toolbar = Toolbar(self, self.sel_view)
        self.toolbar.sync()
        self.toolbar.show()
        self._place_toolbar()

    def _place_toolbar(self) -> None:
        tb = self.toolbar
        if tb is None or self.sel is None:
            return
        tb.adjustSize()
        v = self.sel_view
        hole = v.local(self.sel)
        w, h = tb.width(), tb.height()
        x = hole.right() - w
        y = hole.bottom() + 8
        if y + h > v.height() - 4:
            y = hole.top() - 8 - h - 22          # 上面还有尺寸标签
            if y < 4:
                y = hole.bottom() - h - 8
        x = max(4.0, min(x, v.width() - w - 4.0))
        tb.move(int(x), int(y))
        tb.raise_()


def _set_cursor(x: int, y: int) -> None:
    import ctypes
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
