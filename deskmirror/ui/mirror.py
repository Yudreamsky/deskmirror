"""魔镜边框：可拖动、可调整大小的矩形框。

框内完全透明（逐像素透明 = 鼠标点击、选中、滚轮都落到下面的软件）；只有细边框和
上方的小标签接收鼠标：拖标签移动，拖边框或四角调整大小；标签右侧是截原图、截译图、
刷新、设置、隐藏按钮。按住拖动键（默认 Ctrl+Alt）时框内临时变成可拖动区域，松开即恢复穿透。
Windows 10 上用色键窗口（见 layered.py）：这个窗口看不见、只接鼠标，看得见的边线和标签画在跟着它的 _Chrome 上。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import geom, winapi
from ..geom import Rect
from ..i18n import N_, tr
from . import layered

BAND = 7          # 边框可抓取的宽度（像素）
LINE = 2          # 可见边线宽度
TAB_H = 26
MIN_W, MIN_H = 160, 90

_ICONS = {"refresh": "⟳", "settings": "⚙", "hide": "—"}
_LABELS = {"shot_orig": N_("截原图"), "shot_trans": N_("截译图"), "look": N_("看图"), "pause": N_("暂停")}
# 从右往左排：— ⚙ ⟳ 看图 截译图 截原图 语言 暂停
_ORDER = ("hide", "settings", "refresh", "look", "shot_trans", "shot_orig", "lang", "pause")
_TAB_LABEL_W = 150                       # “魔镜”和一小段状态文字至少要的宽度


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


_EDGE_CURSORS = {
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "lt": Qt.CursorShape.SizeFDiagCursor, "rb": Qt.CursorShape.SizeFDiagCursor,
    "rt": Qt.CursorShape.SizeBDiagCursor, "lb": Qt.CursorShape.SizeBDiagCursor,
    "move": Qt.CursorShape.SizeAllCursor,
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
        self._drag: tuple[str, QPoint, Rect] | None = None
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
        self._tab_below = m[1] - BAND - TAB_H < scr[1]
        outer = geom.expand(m, BAND)
        tab_w = max(min(max(400, (m[2] - m[0]) // 2), max(280, m[2] - m[0])),
                    _TAB_LABEL_W + self._buttons_width() + self._meter_width())
        if self._tab_below:
            tab = (m[0] - BAND, m[3] + BAND - 1, m[0] - BAND + tab_w, m[3] + BAND - 1 + TAB_H)
        else:
            tab = (m[0] - BAND, m[1] - BAND - TAB_H + 1, m[0] - BAND + tab_w, m[1] - BAND + 1)
        full = geom.union(outer, tab)
        self._origin = (full[0], full[1])
        self._tab = tab
        self.setGeometry(full[0], full[1], full[2] - full[0], full[3] - full[1])
        if self._chrome is not None:
            self._chrome.setGeometry(self.geometry())
        self._place_buttons()
        self.update()

    def visual(self) -> QWidget:
        """看得见的那个窗口（截译图时叠到截屏上的是它）。"""
        return self._chrome or self

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if self._chrome is not None:
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
        x = tab.right() - 2
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

    def set_grab_mode(self, on: bool) -> None:
        # 拖动途中先松开拖动键也没关系：按下时已经抓住鼠标，拖完为止。
        if on != self.grab_mode:
            self.grab_mode = on
            self.update()

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        if self._chrome is None:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(event.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self._paint_grab(p, QColor(0, 0, 0, 1))      # 几乎透明（alpha=1）：看不见，但能接住鼠标
            self._paint_chrome(p)
        else:
            # 色键窗口：这个窗口本身看不见，不是色键的地方接鼠标；看得见的画在 _Chrome 上（同一块跟着重画）
            p.fillRect(event.rect(), layered.key_color())
            black = QColor(0, 0, 0)
            self._paint_grab(p, black)
            inner = self._local(self.mirror)
            for cx, cy in ((inner.left(), inner.top()), (inner.right(), inner.top()), (inner.left(), inner.bottom()),
                           (inner.right(), inner.bottom())):
                p.fillRect(QRect(cx - 4, cy - 4, 9, 9), black)
            p.fillRect(self._local(self._tab), black)
            self._chrome.update(event.rect())
        p.end()

    def _paint_grab(self, p: QPainter, color: QColor) -> None:
        """抓取带（框外一圈，拖它调整大小）；按住拖动键时连框内一起。"""
        inner = self._local(self.mirror)
        outer = self._local(geom.expand(self.mirror, BAND))
        p.fillRect(QRect(outer.left(), outer.top(), outer.width(), BAND), color)
        p.fillRect(QRect(outer.left(), inner.bottom() + 1, outer.width(), BAND), color)
        p.fillRect(QRect(outer.left(), inner.top(), BAND, inner.height()), color)
        p.fillRect(QRect(inner.right() + 1, inner.top(), BAND, inner.height()), color)
        if self.grab_mode:
            p.fillRect(inner, color)

    def _paint_chrome(self, p: QPainter, solid: bool = False) -> None:
        """看得见的边线、四角和标签。solid：色键窗口里只能画不透明的颜色。"""
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

    def _paint_tab(self, p: QPainter, solid: bool = False) -> None:
        tab = self._local(self._tab)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(28, 30, 36, 255 if solid else 235))
        p.drawRoundedRect(tab, 5, 5)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QColor(235, 238, 245))
        title = tr("魔镜") + ("📌" if self.pinned else "")
        p.drawText(tab.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        colors = {"ok": QColor(120, 220, 140), "busy": QColor(120, 180, 255), "warn": QColor(255, 200, 90),
                  "error": QColor(255, 110, 110), "paused": QColor(185, 185, 190)}
        p.setPen(colors.get(self.status_level, QColor(200, 200, 200)))
        left_btn = min((r.left() for r in self._buttons.values()), default=tab.right())
        fm = QFontMetrics(font)
        sx = tab.left() + 22 + fm.horizontalAdvance(title)      # 状态文字紧跟在标题后面
        self._meter_rect = QRect()
        if self.meter:
            # token 用量：贴在按钮左边，像网速监控那样 ↑ 输入 ↓ 输出（宽度在 _layout 里留好了）
            mw = self._meter_width()
            self._meter_rect = QRect(left_btn - 4 - mw, tab.top(), mw, tab.height())
            left_btn = self._meter_rect.left()
            pen = p.pen()
            p.setFont(_meter_font())
            p.setPen(QColor(150, 200, 255))
            p.drawText(self._meter_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.meter)
            p.setFont(font)
            p.setPen(pen)
        status_rect = QRect(sx, tab.top(), max(0, left_btn - 6 - sx), tab.height())
        p.drawText(status_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(self.status, Qt.TextElideMode.ElideRight, status_rect.width()))
        for name, r in self._buttons.items():
            if name in _ICONS:
                if name == self._hover_button:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 40))
                    p.drawRoundedRect(r, 4, 4)
                p.setPen(QColor(235, 238, 245))
                f = QFont("Segoe UI Symbol")
                f.setPixelSize(15)
                p.setFont(f)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, _ICONS[name])
            else:
                # 文字按钮：带底色，看得出能点；暂停中的“继续”用醒目的黄底
                lit = name == "pause" and self.paused
                p.setPen(Qt.PenStyle.NoPen)
                if lit:
                    p.setBrush(QColor(255, 200, 60, 255 if name == self._hover_button else 215))
                else:
                    p.setBrush(QColor(255, 255, 255, 70 if name == self._hover_button else 32))
                p.drawRoundedRect(r, 4, 4)
                p.setPen(QColor(30, 30, 34) if lit else QColor(235, 238, 245))
                p.setFont(_btn_font())
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label(name))

    # ------------------------------------------------------------------ 鼠标
    def _zone(self, pos: QPoint) -> str:
        for name, r in self._buttons.items():
            if r.contains(pos):
                return "btn:" + name
        if self._local(self._tab).contains(pos):
            return "move"
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
            if zone == "move" or zone.startswith("btn:"):
                self.menu_requested.emit(e.globalPosition().toPoint())
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        zone = self._zone(e.position().toPoint())
        if zone and not zone.startswith("btn:"):
            self._drag = (zone, e.globalPosition().toPoint(), self.mirror)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pos = e.position().toPoint()
        if self._drag is None:
            self.meter_hovered = self._meter_rect.contains(pos)
            zone = self._zone(pos)
            hb = zone[4:] if zone.startswith("btn:") else ""
            if hb != self._hover_button:
                self._hover_button = hb
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
        if self._hover_button:
            self._hover_button = ""
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
        self.frame._paint_chrome(p, solid=True)
        p.end()
        layered.painted(self)
