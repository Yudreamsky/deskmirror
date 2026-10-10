"""魔镜边框：可拖动、可调整大小的矩形框。

框内完全透明（逐像素透明 = 鼠标点击、选中、滚轮都落到下面的软件）；只有细边框和
上方的小标签接收鼠标：拖标签（或左头的抓手）移动，拖到屏幕边缘收成球（见 dock.py），拖边框或四角调整大小；
标签右侧是截原图、截译图、刷新、设置、隐藏按钮。按住拖动键（默认 Ctrl+Alt）时框内临时变成可拖动区域，松开即恢复穿透。
Windows 10 上用色键窗口（见 layered.py）：这个窗口看不见、只接鼠标，看得见的边线和标签画在跟着它的 _Chrome 上。
液态玻璃皮肤（见 glass.py）：边框是镜框外面一圈玻璃（也是拖它调整大小的地方），标签是浮在上面的玻璃长条。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import geom, winapi
from ..geom import Rect
from ..i18n import N_, tr
from . import glass, layered

BAND = 7          # 边框可抓取的宽度（像素）
LINE = 2          # 可见边线宽度
TAB_H = 26
MIN_W, MIN_H = 160, 90
GRIP_X, GRIP_W, GRIP_H = 4, 18, 20     # 标签左头的抓手（六个点）
_TITLE_X = GRIP_X + GRIP_W + 6         # “魔镜”两个字从这里开始
_GLASS_IN = 5                          # 液态玻璃的标签两头是圆的：抓手、文字往里挪一点


def band() -> int:
    """边框可抓取的宽度：液态玻璃是整圈玻璃的宽度。"""
    return glass.BAND if glass.active() else BAND


def chrome_top() -> int:
    """镜框上沿往上，边框和标签一共占多高（标签在上方时）。"""
    return band() + (glass.GAP if glass.active() else 0) + TAB_H


def _tab_top(m: Rect) -> int:
    return m[1] - chrome_top() + (0 if glass.active() else 1)      # 经典样子：标签压住边框带最外一像素


def _grip_x() -> int:
    return GRIP_X + (_GLASS_IN if glass.active() else 0)

_ICONS = {"refresh": "⟳", "settings": "⚙", "hide": "—"}
_LABELS = {"shot_orig": N_("截原图"), "shot_trans": N_("截译图"), "look": N_("看图"), "pause": N_("暂停")}
# 从右往左排：— ⚙ ⟳ 看图 截译图 截原图 语言 暂停
_ORDER = ("hide", "settings", "refresh", "look", "shot_trans", "shot_orig", "lang", "pause")
_TAB_LABEL_W = 166                       # 抓手、“魔镜”和一小段状态文字至少要的宽度


def grip_offset() -> tuple[int, int]:
    """标签在上方时，抓手中心相对镜框开口左上角的位置（从球里拖出魔镜时，抓手就在鼠标底下）。"""
    return (-band() + _grip_x() + GRIP_W // 2, _tab_top((0, 0, 0, 0)) + TAB_H // 2)


def _btn_font() -> QFont:
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(12)
    return f


def _meter_font() -> QFont:
    f = QFont("Consolas")
    f.setPixelSize(12)
    return f


# token 用量占的宽度按最长的样子留好：数字变了标签不跟着变宽变窄
_METER_SAMPLE = "≈↑999.9k ↓999.9k"


def _c(hex_: str, a: int = 255) -> QColor:
    c = QColor(hex_)
    c.setAlpha(a)
    return c


# 标签上的颜色：经典样子（深色标签）；液态玻璃的白玻璃、烟灰玻璃（照浏览器版）
_CLASSIC = {
    "ink": QColor(235, 238, 245), "meter": QColor(150, 200, 255), "radius": 4,
    "status": {"ok": QColor(120, 220, 140), "busy": QColor(120, 180, 255), "warn": QColor(255, 200, 90),
               "error": QColor(255, 110, 110), "paused": QColor(185, 185, 190)}, "status_other": QColor(200, 200, 200),
    "icon_hover": QColor(255, 255, 255, 40), "btn": (QColor(255, 255, 255, 32), QColor(255, 255, 255, 70)),
}
_GLASS_LIGHT = {
    "ink": _c("#1d1d1f"), "meter": _c("#48484a"), "radius": 9,
    "status": {"ok": _c("#1a7f37"), "busy": _c("#0b57d0"), "warn": _c("#a15c00"), "error": _c("#c62828"),
               "paused": _c("#6e6e73")}, "status_other": _c("#6e6e73"),
    "icon_hover": _c("#ffffff", 235), "btn": (_c("#ffffff", 153), _c("#ffffff", 235)), "btn_edge": _c("#000000", 20),
    "lang": (_c("#3d8bfd", 36), _c("#3d8bfd", 64)), "lang_ink": _c("#0b57d0"),
}
_GLASS_DARK = {
    "ink": _c("#f5f5f7"), "meter": _c("#c7c7cc"), "radius": 9,
    "status": {"ok": _c("#63d68a"), "busy": _c("#8ab8ff"), "warn": _c("#ffcc66"), "error": _c("#ff7b72"),
               "paused": _c("#aeaeb2")}, "status_other": _c("#aeaeb2"),
    "icon_hover": _c("#ffffff", 66), "btn": (_c("#ffffff", 36), _c("#ffffff", 66)), "btn_edge": _c("#ffffff", 30),
    "lang": (_c("#3d8bfd", 71), _c("#3d8bfd", 110)), "lang_ink": _c("#cfe0ff"),
}


_EDGE_CURSORS = {
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "lt": Qt.CursorShape.SizeFDiagCursor, "rb": Qt.CursorShape.SizeFDiagCursor,
    "rt": Qt.CursorShape.SizeBDiagCursor, "lb": Qt.CursorShape.SizeBDiagCursor,
    "move": Qt.CursorShape.SizeAllCursor, "tab": Qt.CursorShape.SizeAllCursor,
    "grip": Qt.CursorShape.OpenHandCursor,
}


class MirrorFrame(QWidget):
    rect_changed = Signal(tuple, bool)   # (新矩形, 是否拖动结束)
    refresh_clicked = Signal()
    settings_clicked = Signal()
    hide_clicked = Signal()
    shot_clicked = Signal(str)           # "orig" 截原图 / "trans" 截译图
    look_clicked = Signal()              # 看图翻译：把镜框里的画面发给能看图的模型
    pause_clicked = Signal()             # 暂停 / 继续
    lang_clicked = Signal(QPoint)        # 语言按钮：弹出原文 / 译成的语言菜单（屏幕坐标）
    menu_requested = Signal(QPoint)      # 右键标签：跟随窗口、新建 / 关闭魔镜

    def __init__(self, rect: Rect, color: str) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self._chrome: _Chrome | None = None   # 色键窗口时看得见的那一层
        if not layered.colorkey():
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.color = QColor(color)
        self.mirror: Rect = rect
        self.status = ""
        self.status_level = "ok"     # ok / busy / warn / error
        self.grab_mode = False
        self._drag: tuple[str, QPoint, Rect] | None = None    # 调整大小、按住拖动键在框内拖（拖标签见 dock）
        self.dock = None                     # 吸边成球（dock.Docker，由程序接上）：拖标签由它管
        self.ghost = False                   # 正在变形成球（或从球变回来）：这个窗口不画东西，只接着鼠标
        self._hover_grip = False
        self._tab_below = False
        self._buttons: dict[str, QRect] = {}
        self._hover_button = ""
        self.pinned = False                  # 正跟随某个窗口（标签上显示 📌）
        self.bound = None                    # 由程序管理：(窗口句柄, 相对位置, 上次窗口矩形)
        self.suspended = False               # 跟随的窗口最小化了：魔镜暂时收起
        self.paused = False                  # 用户点了“暂停”：按钮显示“继续”
        self.lang_label = ""                 # 语言按钮上的字，如“自动→中”（由程序按设置更新）
        self.meter = ""                      # 今天用掉的 token，如“↑12.3k ↓4.1k”（空 = 不显示）
        self.meter_tip = ""                  # 鼠标停在上面时显示的明细（由程序显示，见 app._hover_tip）
        self.meter_hovered = False
        self._meter_rect = QRect()
        self.backdrop: glass.Backdrop | None = None   # 液态玻璃取后面的画面（由程序接上）
        self._rim: glass.Rim | None = None
        self._pill: glass.Pill | None = None
        self.glass_renders = 0               # 玻璃重画了几块（调试、验收用）
        self._glass_force = False            # 下一轮把玻璃全部重取一遍（边框颜色换了）
        self._paint_clip: QRectF | None = None
        self.winId()
        if layered.colorkey():
            layered.apply(self, alpha=1)       # 整体 1/255 不透明：看不见，但不是色键的地方接得住鼠标
            self._chrome = _Chrome(self, flags)
        winapi.exclude_from_capture(int(self.winId()))
        winapi.set_exstyle(int(self.winId()), add=winapi.WS_EX_NOACTIVATE | winapi.WS_EX_TOOLWINDOW)
        self._layout()

    # ------------------------------------------------------------------ 几何
    def _screen_for(self, r: Rect) -> Rect:
        cx, cy = geom.center(r)
        for m in winapi.monitors():
            if geom.contains_pt(m.rect, cx, cy):
                return m.rect
        return winapi.monitors()[0].rect

    def _layout(self) -> None:
        m = self.mirror
        scr = self._screen_for(m)
        bd = band()
        self._tab_below = m[1] - chrome_top() < scr[1]
        outer = geom.expand(m, bd)
        tab_w = max(min(max(400, (m[2] - m[0]) // 2), max(280, m[2] - m[0])),
                    _TAB_LABEL_W + self._buttons_width() + self._meter_width()
                    + (2 * _GLASS_IN if glass.active() else 0))
        # 标签在下方时和上方对称：离镜框下沿的距离和在上方时离上沿一样
        top = m[3] + (m[1] - _tab_top(m)) - TAB_H if self._tab_below else _tab_top(m)
        tab = (m[0] - bd, top, m[0] - bd + tab_w, top + TAB_H)
        full = geom.union(outer, tab)
        self._origin = (full[0], full[1])
        self._tab = tab
        self.setGeometry(full[0], full[1], full[2] - full[0], full[3] - full[1])
        if self._chrome is not None:
            self._chrome.setGeometry(self.geometry())
        self._place_buttons()
        if glass.active():
            self.glass_refresh(time.perf_counter(), force=True)
        self.update()

    def visual(self) -> QWidget:
        """看得见的那个窗口（截译图时叠到截屏上的是它）。"""
        return self._chrome or self

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if glass.active() and not self.ghost:
            self.glass_refresh(time.perf_counter(), force=True)     # 藏着的时候后面的画面可能变了
        if self._chrome is not None and not self.ghost:
            self._chrome.setGeometry(self.geometry())
            self._chrome.show()

    def hideEvent(self, e) -> None:  # noqa: N802
        super().hideEvent(e)
        if self._chrome is not None:
            self._chrome.hide()

    def closeEvent(self, e) -> None:  # noqa: N802
        if self._chrome is not None:
            self._chrome.close()
        super().closeEvent(e)

    def _local(self, r: Rect) -> QRect:
        return QRect(r[0] - self._origin[0], r[1] - self._origin[1], r[2] - r[0], r[3] - r[1])

    def _button_w(self, name: str, fm: QFontMetrics) -> int:
        return TAB_H - 4 if name in _ICONS else fm.horizontalAdvance(self._label(name)) + 14

    def _meter_width(self) -> int:
        return QFontMetrics(_meter_font()).horizontalAdvance(_METER_SAMPLE) + 10 if self.meter else 0

    def _buttons_width(self) -> int:
        fm = QFontMetrics(_btn_font())
        return sum(self._button_w(n, fm) + (2 if n in _ICONS else 4) for n in _ORDER) + 2

    def _place_buttons(self) -> None:
        tab = self._local(self._tab)
        size = TAB_H - 4
        fm = QFontMetrics(_btn_font())
        x = tab.right() - 2 - (_GLASS_IN if glass.active() else 0)
        self._buttons = {}
        for name in _ORDER:
            w = self._button_w(name, fm)
            x -= w
            self._buttons[name] = QRect(x, tab.top() + 2, w, size)
            x -= 2 if name in _ICONS else 4

    def set_mirror(self, rect: Rect) -> None:
        if rect != self.mirror:
            self.mirror = rect
            self._layout()

    def _label(self, name: str) -> str:
        if name == "lang":
            return self.lang_label
        return tr("继续") if name == "pause" and self.paused else tr(_LABELS[name])

    def retranslate(self) -> None:
        """换了界面语言：按钮上的字宽度变了，重新排。"""
        self._layout()

    def set_lang_label(self, text: str) -> None:
        if text != self.lang_label:
            self.lang_label = text
            self._layout()                 # 字数变了：按钮重排，标签不够宽时加宽

    def set_paused(self, on: bool) -> None:
        if on != self.paused:
            self.paused = on
            self.update(self._local(self._tab))

    def set_pinned(self, on: bool) -> None:
        if on != self.pinned:
            self.pinned = on
            self.update(self._local(self._tab))

    def set_status(self, text: str, level: str) -> None:
        if text != self.status or level != self.status_level:
            self.status, self.status_level = text, level
            self.update(self._local(self._tab))

    def set_meter(self, text: str, tip: str) -> None:
        self.meter_tip = tip
        if text != self.meter:
            relayout = bool(text) != bool(self.meter)       # 出现 / 消失时标签要变宽 / 变窄
            self.meter = text
            if relayout:
                self._layout()
            else:
                self.update(self._local(self._tab))

    def set_ghost(self, on: bool) -> None:
        """变形期间（形状画在覆盖层上）：边线、标签都不画，窗口留着接住正在拖的鼠标。"""
        if on != self.ghost:
            self.ghost = on
            if not on and glass.active():
                self.glass_refresh(time.perf_counter(), force=True)
            if self._chrome is not None:
                self._chrome.setVisible(not on and self.isVisible())
            self.update()

    def set_grab_mode(self, on: bool) -> None:
        # 拖动途中先松开拖动键也没关系：按下时已经抓住鼠标，拖完为止。
        if on != self.grab_mode:
            self.grab_mode = on
            self.update()

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        if self.ghost:
            if self._chrome is None:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                p.fillRect(event.rect(), Qt.GlobalColor.transparent)
            else:
                p.fillRect(event.rect(), layered.key_color())
            p.end()
            return
        if self._chrome is None:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(event.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self._paint_grab(p, QColor(0, 0, 0, 1))      # 几乎透明（alpha=1）：看不见，但能接住鼠标
            self._paint_clip = QRectF(event.rect())
            self._paint_chrome(p)
            self._paint_clip = None
        else:
            # 色键窗口：这个窗口本身看不见，不是色键的地方接鼠标；看得见的画在 _Chrome 上（同一块跟着重画）
            p.fillRect(event.rect(), layered.key_color())
            black = QColor(0, 0, 0)
            self._paint_grab(p, black)
            inner = self._local(self.mirror)
            for cx, cy in (() if glass.active() else ((inner.left(), inner.top()), (inner.right(), inner.top()),
                                                      (inner.left(), inner.bottom()), (inner.right(), inner.bottom()))):
                p.fillRect(QRect(cx - 4, cy - 4, 9, 9), black)
            p.fillRect(self._local(self._tab), black)
            self._chrome.update(event.rect())
        p.end()

    def _paint_grab(self, p: QPainter, color: QColor) -> None:
        """抓取带（框外一圈，拖它调整大小）；按住拖动键时连框内一起。"""
        inner = self._local(self.mirror)
        bd = band()
        outer = self._local(geom.expand(self.mirror, bd))
        p.fillRect(QRect(outer.left(), outer.top(), outer.width(), bd), color)
        p.fillRect(QRect(outer.left(), inner.bottom() + 1, outer.width(), bd), color)
        p.fillRect(QRect(outer.left(), inner.top(), bd, inner.height()), color)
        p.fillRect(QRect(inner.right() + 1, inner.top(), bd, inner.height()), color)
        if self.grab_mode:
            p.fillRect(inner, color)

    def _paint_chrome(self, p: QPainter, solid: bool = False) -> None:
        """看得见的边线、四角和标签。solid：色键窗口里只能画不透明的颜色。"""
        if glass.active():
            self._paint_glass(p, solid)
            return
        inner = self._local(self.mirror)
        # 可见边线（画在框外，不压住镜内内容）
        color = layered.solid(self.color) if solid else self.color
        pen = QPen(color)
        pen.setWidth(LINE)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(inner).adjusted(-LINE / 2 - 0.5, -LINE / 2 - 0.5, LINE / 2 + 0.5, LINE / 2 + 0.5))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        for cx, cy in ((inner.left(), inner.top()), (inner.right(), inner.top()), (inner.left(), inner.bottom()),
                       (inner.right(), inner.bottom())):
            p.drawRect(QRect(cx - 4, cy - 4, 9, 9))
        if self.grab_mode:
            c = QColor(self.color)
            c.setAlpha(60)
            pen = QPen(layered.solid(c) if solid else c)
            pen.setWidth(2 if solid else 4)          # 不透明的画细一点
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(inner.adjusted(2, 2, -2, -2))
        self._paint_tab(p, solid)

    def _palette(self) -> dict:
        """标签上的颜色：经典（深色标签）；液态玻璃按后面的亮度用白玻璃（深色字）或烟灰玻璃（浅色字）。"""
        if not glass.active():
            return _CLASSIC
        return _GLASS_DARK if self._pill is not None and self._pill.tone.dark else _GLASS_LIGHT

    def _paint_tab(self, p: QPainter, solid: bool = False) -> None:
        tab = self._local(self._tab)
        if glass.active():
            self._glass_objects()
            self._pill.paint(p, tab.left(), tab.top(), solid)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(28, 30, 36, 255 if solid else 235))
            p.drawRoundedRect(tab, 5, 5)
        pal = self._palette()
        self._paint_grip(p, solid)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(pal["ink"])
        title = tr("魔镜") + ("📌" if self.pinned else "")
        title_x = _TITLE_X + (_GLASS_IN if glass.active() else 0)
        p.drawText(tab.adjusted(title_x, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        p.setPen(pal["status"].get(self.status_level, pal["status_other"]))
        left_btn = min((r.left() for r in self._buttons.values()), default=tab.right())
        fm = QFontMetrics(font)
        sx = tab.left() + title_x + 12 + fm.horizontalAdvance(title)      # 状态文字紧跟在标题后面
        self._meter_rect = QRect()
        if self.meter:
            # token 用量：贴在按钮左边，像网速监控那样 ↑ 输入 ↓ 输出（宽度在 _layout 里留好了）
            mw = self._meter_width()
            self._meter_rect = QRect(left_btn - 4 - mw, tab.top(), mw, tab.height())
            left_btn = self._meter_rect.left()
            pen = p.pen()
            p.setFont(_meter_font())
            p.setPen(pal["meter"])
            p.drawText(self._meter_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.meter)
            p.setFont(font)
            p.setPen(pen)
        status_rect = QRect(sx, tab.top(), max(0, left_btn - 6 - sx), tab.height())
        p.drawText(status_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(self.status, Qt.TextElideMode.ElideRight, status_rect.width()))
        rad = pal["radius"]
        if glass.active():
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for name, r in self._buttons.items():
            hover = name == self._hover_button
            if name in _ICONS:
                if hover:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(pal["icon_hover"])
                    p.drawRoundedRect(r, rad, rad)
                p.setPen(pal["ink"])
                f = QFont("Segoe UI Symbol")
                f.setPixelSize(15)
                p.setFont(f)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, _ICONS[name])
            else:
                # 文字按钮：带底色，看得出能点；暂停中的“继续”用醒目的黄底
                lit = name == "pause" and self.paused
                lang = name == "lang" and "lang" in pal
                p.setPen(Qt.PenStyle.NoPen)
                if lit:
                    p.setBrush(QColor(255, 200, 60, 255 if hover else 215))
                elif lang:
                    p.setBrush(pal["lang"][1 if hover else 0])
                else:
                    p.setBrush(pal["btn"][1 if hover else 0])
                p.drawRoundedRect(r, rad, rad)
                if "btn_edge" in pal and not lit:
                    p.setPen(QPen(pal["btn_edge"], 1.0))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5), rad - 0.5, rad - 0.5)
                p.setPen(QColor(30, 30, 34) if lit else pal["lang_ink"] if lang else pal["ink"])
                p.setFont(_btn_font())
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label(name))

    def _grip_rect(self) -> QRect:
        tab = self._local(self._tab)
        return QRect(tab.left() + _grip_x(), tab.top() + (TAB_H - GRIP_H) // 2, GRIP_W, GRIP_H)

    def _paint_grip(self, p: QPainter, solid: bool) -> None:
        """抓手：六个点，鼠标移上去或按住时变蓝（色键窗口里只能画不透明的颜色：先和标签底色混好）。"""
        lit = self._hover_grip or (self.dock is not None and self.dock.g is not None)
        r = self._grip_rect()
        p.save()
        if glass.active():
            # 玻璃标签本身是不透明地画上去的：色键窗口里抓手照样可以半透明地叠在上面
            dark = self._palette() is _GLASS_DARK
            bg = QColor(61, 139, 253, 217) if lit else QColor(255, 255, 255, 31) if dark else QColor(0, 0, 0, 15)
            dots = QColor(255, 255, 255) if lit else QColor(209, 209, 214) if dark else QColor(91, 91, 96)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
        else:
            bg = QColor(61, 139, 253, 205) if lit else QColor(255, 255, 255, 38)
            if solid:
                a = bg.alphaF()
                bg = QColor(round(28 + (bg.red() - 28) * a), round(30 + (bg.green() - 30) * a),
                            round(36 + (bg.blue() - 36) * a))
            dots = QColor(238, 241, 246)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, not solid)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 5, 5)
        p.setBrush(dots)
        cx, cy = r.left() + r.width() / 2, r.top() + r.height() / 2
        for dx in (-3.0, 3.0):
            for dy in (-5.5, 0.0, 5.5):
                p.drawEllipse(QRectF(cx + dx - 1.6, cy + dy - 1.6, 3.2, 3.2))
        p.restore()

    # ------------------------------------------------------------------ 液态玻璃
    def _paint_glass(self, p: QPainter, solid: bool) -> None:
        """液态玻璃：镜框外一圈玻璃（折射后面的画面），浮在上面的玻璃标签。"""
        self._glass_objects()
        inner = self._local(self.mirror)
        bd = glass.BAND
        clip = self._paint_clip
        self._rim.paint(p, inner.left() - bd, inner.top() - bd, solid, clip)
        if self.grab_mode:
            c = QColor(self.color)
            c.setAlpha(60)
            pen = QPen(layered.solid(c) if solid else c)
            pen.setWidth(2 if solid else 4)
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, not solid)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            r_in = max(0, glass.RADIUS - bd)
            p.drawRoundedRect(QRectF(inner).adjusted(2, 2, -2, -2), r_in, r_in)
            p.restore()
        if clip is None or clip.intersects(QRectF(self._glass_area("tab"))):
            self._paint_tab(p, solid)

    def _glass_objects(self) -> None:
        """按现在的大小准备边框、标签的玻璃（大小变了重算位移图）。"""
        m = self.mirror
        size = (m[2] - m[0], m[3] - m[1])
        if self._rim is None or self._rim.size != size:
            self._rim = glass.Rim(*size, self.color, solid=self._chrome is not None)
        elif self._rim.color != self.color:
            self._rim.set_color(self.color)              # 边框颜色换了：下一轮重取一遍
            self._glass_force = True
        tw = self._tab[2] - self._tab[0]
        if self._pill is None or self._pill.size != (tw, TAB_H):
            old = self._pill
            self._pill = glass.Pill.tab(tw, TAB_H)
            if old is not None:
                self._pill.tone = old.tone            # 标签变宽变窄时深浅照旧，不闪

    def glass_parts(self) -> dict[str, Rect]:
        """液态玻璃要取后面画面的几块（屏幕坐标）：边框的上下左右四条、标签。"""
        self._glass_objects()
        ox, oy = self.mirror[0] - glass.BAND, self.mirror[1] - glass.BAND
        parts = {name: lens.patch_rect(ox, oy) for name, lens in self._rim.lenses.items()}
        parts["tab"] = self._pill.patch_rect(self._tab[0], self._tab[1])
        return parts

    def _glass_area(self, name: str) -> QRect:
        """这一块玻璃在窗口里的范围（重画用）。"""
        if name == "tab":
            return self._local(self._tab).adjusted(-1, -1, 1, 5)        # 连下沿的影子
        inner = self._local(self.mirror)
        x0, y0, x1, y1 = self._rim.lenses[name].area
        ox, oy = inner.left() - glass.BAND, inner.top() - glass.BAND
        return QRect(ox + x0, oy + y0, x1 - x0, y1 - y0)

    def glass_refresh(self, now: float, force: bool = False) -> None:
        """液态玻璃：后面的画面变了的那几块重新取样、重画。force：位置、大小刚变过，全部重取（随后整个重画）。"""
        if self.backdrop is None or self.ghost or not glass.active() or not self.isVisible():
            return
        solid = self._chrome is not None
        parts = self.glass_parts()
        if self._glass_force:
            self._glass_force, force = False, True
            self.update()
        for name, rect in parts.items():
            patch = self.backdrop.fresh(self, name, rect, now, force)
            if patch is None:
                continue
            self.glass_renders += 1
            if name == "tab":
                if self._pill.render(patch, solid) and not force:
                    self.update(self._local(self._tab))           # 深浅换了：字的颜色也换
            else:
                self._rim.render(name, patch, solid)
            if not force:
                self.visual().repaint(self._glass_area(name))

    # ------------------------------------------------------------------ 鼠标
    def _zone(self, pos: QPoint) -> str:
        for name, r in self._buttons.items():
            if r.contains(pos):
                return "btn:" + name
        if self._grip_rect().contains(pos):
            return "grip"
        if self._local(self._tab).contains(pos):
            return "tab"
        inner = self._local(self.mirror)
        if inner.contains(pos):
            return "move" if self.grab_mode else ""
        x, y = pos.x(), pos.y()
        reach = 16  # 角上的调整区沿边延伸一点，好抓
        if x < inner.left() or x > inner.right():
            side = "l" if x < inner.left() else "r"
            if y < inner.top() + reach:
                return side + "t"
            if y > inner.bottom() - reach:
                return side + "b"
            return side
        if y < inner.top() or y > inner.bottom():
            side = "t" if y < inner.top() else "b"
            if x < inner.left() + reach:
                return "l" + side
            if x > inner.right() - reach:
                return "r" + side
            return side
        return ""

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.RightButton:
            zone = self._zone(e.position().toPoint())
            if zone in ("move", "tab", "grip") or zone.startswith("btn:"):
                self.menu_requested.emit(e.globalPosition().toPoint())
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        zone = self._zone(e.position().toPoint())
        if zone in ("tab", "grip") and self.dock is not None:
            # 拖标签：到了屏幕边缘就收成球（按住拖动键在框内拖不会收，能把魔镜放到屏幕最边上）
            self.dock.frame_press(e.globalPosition().toPoint())
            if zone == "grip":
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            self.update(self._local(self._tab))
        elif zone and not zone.startswith("btn:"):
            self._drag = ("move" if zone in ("tab", "grip") else zone, e.globalPosition().toPoint(), self.mirror)

    def _dock_drag(self) -> bool:
        return self.dock is not None and self.dock.g is not None and self.dock.g.src == "frame"

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pos = e.position().toPoint()
        if self._dock_drag():
            self.dock.move(e.globalPosition().toPoint())
            return
        if self._drag is None:
            self.meter_hovered = self._meter_rect.contains(pos)
            zone = self._zone(pos)
            hb = zone[4:] if zone.startswith("btn:") else ""
            if hb != self._hover_button or (zone == "grip") != self._hover_grip:
                self._hover_button = hb
                self._hover_grip = zone == "grip"
                self.update(self._local(self._tab))
            cur = _EDGE_CURSORS.get(zone)
            if cur is not None:
                self.setCursor(QCursor(cur))
            elif zone.startswith("btn:"):
                self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            else:
                self.unsetCursor()
            return
        zone, start, r0 = self._drag
        d = e.globalPosition().toPoint() - start
        dx, dy = d.x(), d.y()
        l, t, r, b = r0
        if zone == "move":
            nr = (l + dx, t + dy, r + dx, b + dy)
        else:
            if "l" in zone:
                l = min(l + dx, r - MIN_W)
            if "r" in zone:
                r = max(r + dx, l + MIN_W)
            if "t" in zone:
                t = min(t + dy, b - MIN_H)
            if "b" in zone:
                b = max(b + dy, t + MIN_H)
            nr = (l, t, r, b)
        if nr != self.mirror:
            self.set_mirror(nr)
            self.rect_changed.emit(nr, False)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if self._dock_drag():
            self.dock.release(e.globalPosition().toPoint())
            if self._zone(pos) == "grip":
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            self.update(self._local(self._tab))
            return
        if self._drag is None:
            zone = self._zone(pos)
            if zone == "btn:refresh":
                self.refresh_clicked.emit()
            elif zone == "btn:settings":
                self.settings_clicked.emit()
            elif zone == "btn:hide":
                self.hide_clicked.emit()
            elif zone == "btn:shot_orig":
                self.shot_clicked.emit("orig")
            elif zone == "btn:shot_trans":
                self.shot_clicked.emit("trans")
            elif zone == "btn:pause":
                self.pause_clicked.emit()
            elif zone == "btn:look":
                self.look_clicked.emit()
            elif zone == "btn:lang":
                r = self._buttons["lang"]
                self.lang_clicked.emit(self.mapToGlobal(QPoint(r.left(), r.bottom() + 2)))
            return
        self._finish_drag()

    def _finish_drag(self) -> None:
        self._drag = None
        self.rect_changed.emit(self.mirror, True)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.meter_hovered = False
        if self._hover_button or self._hover_grip:
            self._hover_button = ""
            self._hover_grip = False
            self.update(self._local(self._tab))


class _Chrome(QWidget):
    """色键窗口时看得见的边线和标签（鼠标穿过去，由看不见的 MirrorFrame 接）。大小、位置、显示都跟着 MirrorFrame。"""

    def __init__(self, frame: MirrorFrame, flags) -> None:
        super().__init__(None, flags | Qt.WindowType.WindowTransparentForInput)
        self.frame = frame
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.winId()
        layered.apply(self)
        winapi.exclude_from_capture(int(self.winId()))
        winapi.set_exstyle(int(self.winId()), add=winapi.WS_EX_NOACTIVATE | winapi.WS_EX_TOOLWINDOW
                           | winapi.WS_EX_TRANSPARENT)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(event.rect(), layered.key_color())
        self.frame._paint_clip = QRectF(event.rect())
        self.frame._paint_chrome(p, solid=True)
        self.frame._paint_clip = None
        p.end()
        layered.painted(self)
