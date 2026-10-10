"""吸边成球：拖着魔镜的标签到屏幕边缘，魔镜缩成一个球吸在边上（停止翻译）；从边上把球拖出来，
球张开成虚线框跟着鼠标走（开始翻译），松手落定成魔镜。点一下球，魔镜回到收起前的地方。

手感照浏览器版 0.7.0：拖着魔镜，鼠标离边缘 28 px 以内就缩成球；拖着球离开边缘 96 px 才变回框；吸住时往里拖，
球最多跟出来 36 px，像被边缘吸着。松手后球藏进边缘四成，鼠标移上去滑出来，移开 1.6 秒后再藏回去。
一次拖动里可以来回变。变形每帧往目标靠一截（f = 1 − e^(−dt/τ)，τ = 60 ms）：目标跟着鼠标走，中途可以反向，
和帧率无关。

框和球的形状画在每块屏幕的覆盖层上（overlay.py 按 UiState.shapes 画）：窗口不用每帧改大小（分层窗口每帧改尺寸
开销大、容易闪）。接鼠标的是看不见的窗口：拖动从哪个窗口开始就一直由它接（魔镜的标签，或者球的 Ball 窗口），
变形期间它只是不画东西。
四条边都吸，只吸当前显示器的外边缘（两块屏相接的边不算）；顶边要把鼠标顶到最上沿才吸，免得把魔镜拖到菜单栏上
就收起来。全程物理像素，门槛按显示器 DPI 缩放。
液态玻璃皮肤（glass.py）：变形途中是不折射的玻璃样子（每帧都改大小，来不及取样）；收好的球按它后面的画面折射，
滑出、藏回时从开始滑之前截好的一块里取样，每帧跟着重画。
"""
from __future__ import annotations

import collections
import math
import time
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

from .. import geom, winapi
from ..geom import Rect
from . import glass, layered
from .mirror import LINE, MIN_H, MIN_W, TAB_H, chrome_top, grip_offset

# 长度按 96 DPI 写，用的时候乘显示器的缩放
BUB = 46            # 球的直径
GAP = 10            # 球完整露出时离屏幕边缘多远
TUCK = 0.42         # 吸住后藏进边缘的比例
ZONE = 28           # 拖着魔镜，鼠标离边缘这么近：缩成球
ZONE_TOP = 2        # 顶边：鼠标要顶到最上沿（把魔镜拖到菜单栏上不算）
ZONE_OUT = 96       # 拖着球，离开边缘这么远：变成虚线框
PULL = 36           # 球被往里拖时最多跟出来多少
SLOP = 4            # 按下以后挪了这么多才算拖，不然算点
MARGIN = 8          # 虚线框离屏幕边缘至少这么远
TAU = 0.060         # 变形的时间常数（秒）
TUCK_DELAY = 1600   # 鼠标离开球多久以后藏回去（毫秒）
HOVER_GRACE = 0.7   # 刚吸住的这一会儿不理会“鼠标移上来”：球从鼠标底下滑进边缘时，系统会补发一次
EDGES = ("l", "r", "t", "b")


@dataclass
class Shape:
    """覆盖层上画的框或球：屏幕坐标，边线的外沿。k：0 = 方框，1 = 圆球。"""
    x: float
    y: float
    w: float
    h: float
    k: float
    dash: bool = False      # 虚线：松手就是魔镜（从边上拖出来的时候）
    text: bool = False      # 框里显示译文（按形状裁剪）
    dark: bool = False      # 液态玻璃：后面是深色画面（烟灰玻璃）

    def box(self) -> Rect:
        """要重画的范围（含阴影）。"""
        m = (6, 6, 6, 10) if glass.active() else (4, 4, 4, 6)
        return (math.floor(self.x) - m[0], math.floor(self.y) - m[1],
                math.ceil(self.x + self.w) + m[2], math.ceil(self.y + self.h) + m[3])


def _edge() -> float:
    """形状的边有多宽：经典是边线，液态玻璃是整圈玻璃。"""
    return glass.BAND if glass.active() else LINE


def _radius(s: Shape, k: float) -> float:
    """圆角：经典从方角变到圆；液态玻璃从边框的圆角变到圆。"""
    r0 = glass.RADIUS if glass.active() else 0.0
    return r0 + (min(s.w, s.h) / 2 - r0) * k


def frame_shape(m: Rect, dash: bool = False, text: bool = False) -> Shape:
    """魔镜的样子（k = 0）：边线（液态玻璃是整圈玻璃）画在开口外面，和 mirror.py 一样。"""
    e = _edge()
    return Shape(m[0] - e, m[1] - e, m[2] - m[0] + 2 * e, m[3] - m[1] + 2 * e, 0.0, dash, text)


def approach(cur: Shape, target: Shape, dt: float, tau: float = TAU) -> bool:
    """形状往目标靠一截（指数趋近，和帧率无关；一帧最多算 50 ms）。返回是不是已经到位。"""
    f = 1.0 - math.exp(-min(0.05, max(0.0, dt)) / tau)
    done = True
    for name, eps in (("x", 0.4), ("y", 0.4), ("w", 0.4), ("h", 0.4), ("k", 0.004)):
        d = getattr(target, name) - getattr(cur, name)
        if abs(d) > eps:
            setattr(cur, name, getattr(cur, name) + d * f)
            done = False
        else:
            setattr(cur, name, getattr(target, name))
    cur.dash, cur.text, cur.dark = target.dash, target.text, target.dark
    return done


# ---------------------------------------------------------------------------------------------------- 几何
def _dist(r: Rect, x: float, y: float) -> float:
    dx = max(r[0] - x, 0.0, x - (r[2] - 1))
    dy = max(r[1] - y, 0.0, y - (r[3] - 1))
    return math.hypot(dx, dy)


def monitor_at(x: float, y: float, mons: list) -> winapi.Monitor:
    """这一点所在的显示器；不在任何显示器上就取最近的。"""
    for m in mons:
        if geom.contains_pt(m.rect, x, y):
            return m
    return min(mons, key=lambda m: _dist(m.rect, x, y))


def is_outer(m: winapi.Monitor, edge: str, along: float, mons: list) -> bool:
    """显示器的这条边在 along 处是不是外边缘：紧挨着外面没有别的显示器。"""
    l, t, r, b = m.rect
    if edge in ("l", "r"):
        y = min(max(int(along), t), b - 1)
        pt = (l - 1, y) if edge == "l" else (r, y)
    else:
        x = min(max(int(along), l), r - 1)
        pt = (x, t - 1) if edge == "t" else (x, b)
    return not any(o is not m and geom.contains_pt(o.rect, *pt) for o in mons)


def edge_near(x: float, y: float, m: winapi.Monitor, mons: list, zone: float, top_zone: float | None = None,
              only: str = "") -> str:
    """鼠标在这块屏幕哪条外边缘的吸附带里（only：只看这一条）；角上离两条边都近时取近的。量到工作区的边
    （任务栏那一边量到任务栏的内沿，鼠标在任务栏上也算）。"""
    l, t, r, b = m.work
    dists = {"l": x - l, "r": r - 1 - x, "t": y - t, "b": b - 1 - y}
    best = ""
    for e, d in dists.items():
        if only and e != only:
            continue
        z = top_zone if e == "t" and top_zone is not None else zone
        if d <= z * m.scale and is_outer(m, e, y if e in ("l", "r") else x, mons) and (not best or d < dists[best]):
            best = e
    return best


def ball_rect(edge: str, along: float, m: winapi.Monitor, tucked: bool) -> tuple[float, float, float]:
    """球的左上角和直径：贴着 edge，球心在这条边上的 along 处；tucked 时藏进边缘一部分。"""
    d, gap = BUB * m.scale, GAP * m.scale
    l, t, r, b = m.work
    if edge in ("l", "r"):
        y = min(max(along - d / 2, t + gap), b - d - gap)
        if edge == "l":
            x = l - d * TUCK if tucked else l + gap
        else:
            x = r - d * (1 - TUCK) if tucked else r - d - gap
    else:
        x = min(max(along - d / 2, l + gap), r - d - gap)
        if edge == "t":
            y = t - d * TUCK if tucked else t + gap
        else:
            y = b - d * (1 - TUCK) if tucked else b - d - gap
    return x, y, d


def ball_spot(edge: str, x: float, y: float, m: winapi.Monitor) -> tuple[float, float, float]:
    """拖着的球在哪：贴着这条边，顺着边跟着鼠标走；往里拖时被边缘吸着，最多跟出来 PULL。"""
    bx, by, d = ball_rect(edge, y if edge in ("l", "r") else x, m, False)
    pull = PULL * m.scale
    if edge == "l":
        bx += min(max(x - d / 2 - bx, 0.0), pull)
    elif edge == "r":
        bx += min(max(x - d / 2 - bx, -pull), 0.0)
    elif edge == "t":
        by += min(max(y - d / 2 - by, 0.0), pull)
    else:
        by += min(max(y - d / 2 - by, -pull), 0.0)
    return bx, by, d


def dash_rect(x: float, y: float, grab: tuple[int, int], size: tuple[int, int], m: winapi.Monitor) -> Rect:
    """虚线框跟着鼠标走：鼠标抓着框上 grab 那一点（相对开口左上角），大小和魔镜一样，
    整个留在这块屏幕里（上面的标签也露出来）；屏幕放不下就缩小。"""
    l, t, r, b = m.work
    margin = MARGIN * m.scale
    top = t + chrome_top() + 4 * m.scale
    w = int(min(size[0], max(MIN_W, r - l - 2 * margin)))
    h = int(min(size[1], max(MIN_H, b - top - margin)))
    nx, ny = x - grab[0], y - grab[1]
    nx = l + margin if r - w - margin < l + margin else min(max(nx, l + margin), r - w - margin)
    ny = top if b - h - margin < top else min(max(ny, top), b - h - margin)
    nx, ny = int(round(nx)), int(round(ny))
    return (nx, ny, nx + w, ny + h)


def default_dock(m_rect: Rect, mons: list) -> tuple[str, winapi.Monitor, float]:
    """没收起过的魔镜收成球吸在哪：魔镜所在屏幕离它近的左边或右边，和标签一样高；左右都挨着别的屏幕就上下。"""
    cx, cy = geom.center(m_rect)
    mon = monitor_at(cx, cy, mons)
    l, t, r, b = mon.work
    tab_y = m_rect[1] - chrome_top() + TAB_H / 2
    cands = [(0, d, e, tab_y) for e, d in (("l", cx - l), ("r", r - cx)) if is_outer(mon, e, tab_y, mons)]
    cands += [(1, d, e, cx) for e, d in (("t", cy - t), ("b", b - cy)) if is_outer(mon, e, cx, mons)]
    if not cands:
        return "r", mon, tab_y
    _, _, edge, along = min(cands)
    return edge, mon, along


def restore_dock(spot: dict, mons: list) -> tuple[str, winapi.Monitor, float] | None:
    """上次存的球（边、球心）现在还能不能吸回去：显示器、分辨率变了就找最近的屏幕，那条边不是外边缘就不算。"""
    try:
        edge, x, y = spot["edge"], float(spot["x"]), float(spot["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if edge not in EDGES:
        return None
    mon = monitor_at(x, y, mons)
    along = y if edge in ("l", "r") else x
    return (edge, mon, along) if is_outer(mon, edge, along, mons) else None


def fit_rect(m: Rect, mons: list) -> Rect:
    """魔镜回到某块屏幕上看得见的地方（显示器、分辨率变了以后）：中心不在任何屏幕上就挪进最近的那块，太大就缩小。"""
    cx, cy = geom.center(m)
    if any(geom.contains_pt(mo.rect, cx, cy) for mo in mons):
        return m
    l, t, r, b = monitor_at(cx, cy, mons).work
    w = max(MIN_W, min(m[2] - m[0], r - l - 40))
    h = max(MIN_H, min(m[3] - m[1], b - t - 80))
    x = min(max(m[0], l + 20), r - w - 20)
    y = min(max(m[1], t + chrome_top() + 20), b - h - 20)
    return (x, y, x + w, y + h)


# ---------------------------------------------------------------------------------------------------- 画
def paint_shape(p: QPainter, s: Shape, ox: int, oy: int, color: QColor, colorkey: bool,
                ball: GlassBall | None = None) -> None:
    """在覆盖层上画框或球（ox, oy：覆盖层左上角的屏幕坐标）。色键窗口只能画不透明的颜色，也不能抗锯齿。
    ball：液态玻璃的球（按后面的画面折射好的），正好是给这个位置画的就用它。"""
    k = min(1.0, max(0.0, s.k))
    rect = QRectF(s.x - ox, s.y - oy, s.w, s.h)
    if glass.active():
        if ball is not None and ball.matches(s):
            ball.paint(p, ox, oy, color, colorkey)
        else:
            glass.paint_morph(p, rect, _radius(s, k), k, color, s.dark, s.dash, colorkey)
            if k > (0.85 if colorkey else 0.7):
                _glyph(p, rect, k, QColor(255, 255, 255) if s.dark else QColor(color), colorkey)
        return
    r = k * min(s.w, s.h) / 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, not colorkey)
    p.setPen(Qt.PenStyle.NoPen)
    if k > 0.6 and not colorkey:
        # 球下面一圈很淡的影子（小面积，不用模糊）
        p.setBrush(QColor(0, 0, 0, int(55 * (k - 0.6) / 0.4)))
        p.drawRoundedRect(rect.adjusted(-1, 1, 1, 3), r + 1, r + 1)
    if colorkey:
        if k >= 0.5:
            p.setBrush(layered.solid(color))
            p.drawRoundedRect(rect, r, r)
    elif k > 0:
        fill = QColor(color)
        fill.setAlphaF(k)
        p.setBrush(fill)
        p.drawRoundedRect(rect, r, r)
    pen = QPen(layered.solid(color) if colorkey else color)
    pen.setWidthF(LINE)
    if s.dash:
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([3.0, 2.0])
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    half = LINE / 2
    rr = max(0.0, r - half)
    p.drawRoundedRect(rect.adjusted(half, half, -half, -half), rr, rr)
    if k > (0.85 if colorkey else 0.7):
        _glyph(p, rect, k, QColor(255, 255, 255), colorkey)
    p.restore()


def _glyph(p: QPainter, rect: QRectF, k: float, c: QColor, colorkey: bool, halo: QColor | None = None) -> None:
    """球上的“镜”字（快变成球时渐显）。halo：字周围一圈淡淡的光晕（玻璃球上，背景花的时候也看得清）。"""
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(max(8, int(min(rect.width(), rect.height()) * 0.43)))
    font.setBold(True)
    c = QColor(c)
    fade = 1.0 if colorkey else min(1.0, (k - 0.7) / 0.3)
    c.setAlphaF(c.alphaF() * fade)
    p.save()
    p.setFont(font)
    if halo is not None and not colorkey:
        h = QColor(halo)
        h.setAlphaF(h.alphaF() * fade)
        p.setPen(h)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            p.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, "镜")
    p.setPen(c)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "镜")
    p.restore()


class GlassBall:
    """液态玻璃皮肤下收好的球：按它后面的画面折射。at：是给哪个位置（屏幕坐标，取整）画的。"""

    def __init__(self, d: int) -> None:
        self.pill = glass.Pill.bubble(d)
        self.at: tuple[int, int] | None = None

    def matches(self, s: Shape) -> bool:
        return self.at is not None and s.k >= 0.999 and round(s.w) == self.pill.size[0] \
            and (round(s.x), round(s.y)) == self.at

    def render(self, patch, x: int, y: int, colorkey: bool) -> None:
        self.pill.render(patch, colorkey)
        self.at = (x, y)

    def paint(self, p: QPainter, ox: int, oy: int, color: QColor, colorkey: bool) -> None:
        x, y = self.at[0] - ox, self.at[1] - oy
        d = self.pill.size[0]
        dark = self.pill.tone.dark
        if not colorkey:
            # 球下面一层柔和的影子（覆盖层鼠标穿透，影子大一点也没关系）
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            for dy, grow, a in ((2.0, 0.5, 30), (3.5, 1.5, 18), (5.5, 3.0, 9)):
                p.setBrush(QColor(0, 0, 0, a * (2 if dark else 1)))
                p.drawEllipse(QRectF(x - grow, y + dy - grow, d + 2 * grow, d + 2 * grow))
            p.restore()
        self.pill.paint(p, x, y, colorkey)
        if dark:
            _glyph(p, QRectF(x, y, d, d), 1.0, QColor(255, 255, 255), colorkey, QColor(0, 0, 0, 70))
        else:
            ink = QColor(color).darker(150)
            _glyph(p, QRectF(x, y, d, d), 1.0, ink, colorkey, QColor(255, 255, 255, 150))


def opening_region(s: Shape, ox: int, oy: int) -> QRegion:
    """框里显示译文的范围（覆盖层坐标）：边线（液态玻璃是整圈玻璃）里面，圆角跟着形状走。"""
    k = min(1.0, max(0.0, s.k))
    e = _edge()
    inner = QRectF(s.x - ox + e, s.y - oy + e, max(0.0, s.w - 2 * e), max(0.0, s.h - 2 * e))
    r = max(0.0, _radius(s, k) - e)
    if r < 1:
        return QRegion(inner.toAlignedRect())
    path = QPainterPath()
    path.addRoundedRect(inner, r, r)
    return QRegion(path.toFillPolygon().toPolygon())


# ---------------------------------------------------------------------------------------------------- 球的窗口
class Ball(QWidget):
    """收起后的球接鼠标的窗口：本身看不见（球画在覆盖层上），只接点击、拖动、鼠标移上来。
    接鼠标的范围是球，再加上球和屏幕边缘之间那一条：鼠标一甩到屏幕边上，球滑出来以后鼠标还在它上面，点得到。"""

    def __init__(self, dock: Docker) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.dock = dock
        self._hit: tuple[QRectF, QRectF] = (QRectF(), QRectF())   # 窗口里的球、通到边上的那一条
        if not layered.colorkey():
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.winId()
        if layered.colorkey():
            layered.apply(self, alpha=1)       # 整体 1/255 不透明：看不见，球那一圈接得住鼠标
        winapi.exclude_from_capture(int(self.winId()))
        winapi.set_exstyle(int(self.winId()), add=winapi.WS_EX_NOACTIVATE | winapi.WS_EX_TOOLWINDOW)

    def place(self, ball: Shape, edge: str, screen: Rect) -> None:
        """球在 ball，贴着 edge；窗口从球一直伸到这块屏幕的那条边。"""
        x0, y0, x1, y1 = ball.x, ball.y, ball.x + ball.w, ball.y + ball.h
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        strip = {"l": (screen[0], y0, cx, y1), "r": (cx, y0, screen[2], y1),
                 "t": (x0, screen[1], x1, cy), "b": (x0, cy, x1, screen[3])}[edge]
        wl, wt = math.floor(min(x0, strip[0])), math.floor(min(y0, strip[1]))
        wr, wb = math.ceil(max(x1, strip[2])), math.ceil(max(y1, strip[3]))
        self._hit = (QRectF(x0 - wl, y0 - wt, ball.w, ball.h),
                     QRectF(strip[0] - wl, strip[1] - wt, max(0.0, strip[2] - strip[0]), max(0.0, strip[3] - strip[1])))
        self.setGeometry(wl, wt, max(1, wr - wl), max(1, wb - wt))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        if layered.colorkey():
            p.fillRect(event.rect(), layered.key_color())
            p.setBrush(QColor(0, 0, 0))
        else:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(event.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setBrush(QColor(0, 0, 0, 1))          # 几乎透明：看不见，但接得住鼠标
        p.setPen(Qt.PenStyle.NoPen)
        ball, strip = self._hit
        p.drawEllipse(ball)
        p.drawRect(strip)
        p.end()

    def enterEvent(self, e) -> None:  # noqa: N802
        self.dock.hover(True)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.dock.hover(False)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.dock.ball_press(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self.dock.g is not None:
            self.dock.move(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.dock.release(e.globalPosition().toPoint())


# ---------------------------------------------------------------------------------------------------- 手势和动画
class _Gesture:
    """一次拖动。src：从哪开始拖（frame 魔镜标签 / ball 球）；mode：现在是什么（frame 实线魔镜跟着走 /
    ball 球 / dash 虚线框）。grab：鼠标抓着魔镜开口左上角往哪偏多少。"""

    def __init__(self, src: str, x: int, y: int, home: Rect, grab: tuple[int, int]) -> None:
        self.src = src
        self.mode = "ball" if src == "ball" else "frame"
        self.x0, self.y0 = self.x, self.y = x, y
        self.moved = False
        self.home = home                  # 开始拖之前魔镜在哪：吸住以后点开回到这里
        self.grab = grab
        self.mons = winapi.monitors()
        self.edge = ""
        self.mon: winapi.Monitor | None = None


class _Live:
    def __init__(self, cur: Shape, target: Shape, kind: str, on_settle) -> None:
        self.cur = cur
        self.target = target
        self.kind = kind                  # drag 跟着鼠标 / settle 松手后落定 / slide 球滑出、藏回
        self.on_settle = on_settle


class Docker(QObject):
    """一个魔镜的吸边成球：拖动手势、动画、球的窗口。形状交给覆盖层画（shapes 就是 UiState.shapes）。"""
    docked_changed = Signal(bool)     # True：收成球（这个魔镜停止翻译）；False：展开（开始翻译）
    repaint = Signal(tuple)           # 覆盖层要重画的屏幕范围
    committed = Signal()              # 一次拖动、点开结束了：位置和吸附状态该存了

    def __init__(self, frame, shapes: dict, balls: dict | None = None) -> None:
        super().__init__()
        self.frame = frame
        self.shapes = shapes
        self.docked = False
        self.edge = ""                    # 吸在哪条边：l / r / t / b
        self.mon: winapi.Monitor | None = None
        self.along = 0.0                  # 球心在这条边上的位置
        self.tucked = False
        self.hidden = False               # 魔镜整体隐藏（托盘、快捷键）：球也藏起来
        self.g: _Gesture | None = None
        self.live: _Live | None = None
        self.hover_t = 0.0                # 鼠标什么时候移到球上的（0 = 不在球上）
        self.trace: collections.deque = collections.deque(maxlen=900)   # 最近的动画帧，验收时量帧间隔
        self.ball = Ball(self)
        self.backdrop: glass.Backdrop | None = None   # 液态玻璃取后面的画面（由程序接上）
        self.balls: dict = {} if balls is None else balls   # 液态玻璃的球（UiState.balls，覆盖层按 shapes 的键取）
        self._slide_bg = None                 # 球滑出、藏回时取样用的背景：(屏幕范围, 画面)
        self.glass_renders = 0
        self._t = 0.0
        self._docked_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self._tuck_timer = QTimer(self)
        self._tuck_timer.setSingleShot(True)
        self._tuck_timer.setInterval(TUCK_DELAY)
        self._tuck_timer.timeout.connect(self._tuck)

    # ------------------------------------------------------------------ 状态
    @property
    def busy(self) -> bool:
        """正在拖，或者正在变形、落定（这期间不跟随窗口、不接新的拖动）。"""
        return self.g is not None or (self.live is not None and self.live.kind != "slide")

    def saved(self) -> dict:
        """存进配置的样子：{} = 没收起；否则是吸的边和球完整露出时的球心。"""
        if not self.docked or self.mon is None:
            return {}
        x, y, d = ball_rect(self.edge, self.along, self.mon, False)
        return {"edge": self.edge, "x": int(round(x + d / 2)), "y": int(round(y + d / 2))}

    def shape(self) -> Shape | None:
        return self.shapes.get(id(self))

    def dock_now(self, spot: dict | None = None) -> None:
        """不要动画，直接收成球藏在边上（启动时恢复上次的样子、开机自启）。spot：上次存的位置，
        没有或者用不了就吸到离魔镜近的一边。"""
        mons = winapi.monitors()
        edge, mon, along = (restore_dock(spot, mons) if spot else None) or default_dock(self.frame.mirror, mons)
        self._end_live(keep=False)
        self.g = None
        self.edge, self.mon, self.along, self.tucked = edge, mon, along, True
        home = fit_rect(self.frame.mirror, mons)
        if home != self.frame.mirror:
            self.frame.set_mirror(home)
        self.frame.set_ghost(False)
        self.frame.hide()
        shape = self._ball_shape(True)
        self._publish(shape, None)
        self._place_ball(shape)
        self.ball.setVisible(not self.hidden)
        self._docked_at = time.perf_counter()
        if not self.docked:
            self.docked = True
            self.docked_changed.emit(True)

    def set_hidden(self, on: bool) -> None:
        self.hidden = on
        if on:
            self._tuck_timer.stop()
            self.cancel()
        self.ball.setVisible(self.docked and not on and not self.busy)

    def close(self) -> None:
        self._timer.stop()
        self._tuck_timer.stop()
        self.live = None
        self._clear_shape()
        self.balls.pop(id(self), None)
        self.ball.close()

    # ------------------------------------------------------------------ 液态玻璃的球
    def _glass_ball(self, d: int) -> GlassBall:
        gb = self.balls.get(id(self))
        if gb is None or gb.pill.size[0] != d:
            old = gb
            gb = self.balls[id(self)] = GlassBall(d)
            if old is not None:
                gb.pill.tone = old.pill.tone
        return gb

    def _dark(self) -> bool:
        """变形途中用白玻璃还是烟灰玻璃：跟着球（没有球就跟着魔镜的标签）。"""
        gb = self.balls.get(id(self))
        if gb is not None and gb.at is not None:
            return gb.pill.tone.dark
        pill = getattr(self.frame, "_pill", None)
        return bool(pill is not None and pill.tone.dark)

    def glass_refresh(self, now: float, force: bool = False) -> None:
        """液态玻璃：收好的球后面的画面变了，重新折射、重画（滑动、变形途中不管，见 _step）。"""
        if not glass.active() or self.backdrop is None or not self.docked or self.hidden or self.live is not None:
            return
        s = self.shape()
        if s is None or s.k < 0.999:
            return
        x, y, d = round(s.x), round(s.y), round(s.w)
        gb = self._glass_ball(d)
        patch = self.backdrop.fresh(self, "ball", gb.pill.patch_rect(x, y), now, force or gb.at != (x, y))
        if patch is None:
            return
        gb.render(patch, x, y, layered.colorkey())
        self.glass_renders += 1
        self.repaint.emit(s.box())

    def _slide_backdrop(self, target: Shape) -> None:
        """球要滑出或藏回：先把滑动经过的那一块背景截好，每帧从里面取样（不用每帧截屏）。"""
        self._slide_bg = None
        if not glass.active() or self.backdrop is None:
            return
        cur = self.shape() or target
        gb = self._glass_ball(round(target.w))
        area = geom.union(gb.pill.patch_rect(round(cur.x), round(cur.y)),
                          gb.pill.patch_rect(round(target.x), round(target.y)))
        img = None if self.backdrop.frozen else self.backdrop.grab(area)
        if img is not None:
            self._slide_bg = (area, img)

    def _glass_follow(self, c: Shape) -> None:
        """滑动途中：按球现在的位置从截好的背景里取样重画。"""
        if self._slide_bg is None or c.k < 0.999:
            return
        area, img = self._slide_bg
        x, y = round(c.x), round(c.y)
        gb = self._glass_ball(round(c.w))
        l, t, r, b = gb.pill.patch_rect(x, y)
        if l < area[0] or t < area[1] or r > area[2] or b > area[3]:
            return
        gb.render(img[t - area[1]:b - area[1], l - area[0]:r - area[0]], x, y, layered.colorkey())
        self.glass_renders += 1

    # ------------------------------------------------------------------ 拖动
    def frame_press(self, gp: QPoint) -> None:
        """在魔镜的标签（或抓手）上按下。"""
        if self.busy or self.docked:
            return
        m = self.frame.mirror
        self.g = _Gesture("frame", gp.x(), gp.y(), m, (gp.x() - m[0], gp.y() - m[1]))

    def ball_press(self, gp: QPoint) -> None:
        if not self.docked or self.busy:
            return
        self._tuck_timer.stop()
        if self.live is not None:             # 正在滑出、藏回：从现在的样子接着拖
            self.live.kind, self.live.on_settle = "drag", None
        g = self.g = _Gesture("ball", gp.x(), gp.y(), self.frame.mirror, grip_offset())
        g.edge, g.mon = self.edge, self.mon

    def move(self, gp: QPoint) -> None:
        g = self.g
        if g is None:
            return
        g.x, g.y = gp.x(), gp.y()
        if not g.moved:
            if math.hypot(g.x - g.x0, g.y - g.y0) < SLOP * monitor_at(g.x0, g.y0, g.mons).scale:
                return
            g.moved = True
        if g.mode == "ball":
            if not edge_near(g.x, g.y, g.mon, g.mons, ZONE_OUT, only=g.edge):
                self._to_dash(g)
        else:
            mon = monitor_at(g.x, g.y, g.mons)
            edge = edge_near(g.x, g.y, mon, g.mons, ZONE, ZONE_TOP)
            if edge:
                self._to_ball(g, edge, mon)
        if g.mode == "ball":
            self._retarget(self._spot_shape(g))
        elif g.mode == "dash":
            self._follow_dash(g)
        else:
            self._move_frame(g)

    def release(self, gp: QPoint) -> None:
        g, self.g = self.g, None
        if g is None:
            return
        if not g.moved:
            if g.src == "ball":
                self.unfold()
            return
        g.x, g.y = gp.x(), gp.y()
        self._finish(g)

    def cancel(self) -> None:
        """拖到一半魔镜被隐藏了（快捷键、托盘）：按现在的样子了结这次拖动。"""
        g, self.g = self.g, None
        if g is not None and g.moved:
            self._finish(g)

    def _finish(self, g: _Gesture) -> None:
        if g.mode == "ball":
            self._dock(g)
        elif g.mode == "dash":
            self._retarget(frame_shape(self.frame.mirror, dash=True, text=True), "settle", self._landed)
        else:
            self.frame.rect_changed.emit(self.frame.mirror, True)

    def _move_frame(self, g: _Gesture) -> None:
        """还没到边缘：魔镜照常跟着鼠标走。"""
        w, h = g.home[2] - g.home[0], g.home[3] - g.home[1]
        x, y = g.x - g.grab[0], g.y - g.grab[1]
        nr = (x, y, x + w, y + h)
        if nr != self.frame.mirror:
            self.frame.set_mirror(nr)
            self.frame.rect_changed.emit(nr, False)

    def _to_ball(self, g: _Gesture, edge: str, mon: winapi.Monitor) -> None:
        """变成球：停止翻译，魔镜的标签、边线藏起来，形状缩成球贴到边上，接着跟着鼠标顺着边走。"""
        start = self.live.cur if self.live is not None else frame_shape(self.frame.mirror)
        if g.mode == "frame":
            self.frame.set_ghost(True)
        g.mode, g.edge, g.mon = "ball", edge, mon
        self._run(start, self._spot_shape(g), "drag")
        if not self.docked:
            self.docked = True
            self.docked_changed.emit(True)

    def _to_dash(self, g: _Gesture) -> None:
        """变成虚线框：球张开成魔镜那么大，跟着鼠标走；同时开始翻译，译文在框里跟着长出来。"""
        start = self.live.cur if self.live is not None else (self.shape() or self._ball_shape(self.tucked))
        g.mode = "dash"
        m = self._dash_rect(g)
        self.frame.set_mirror(m)
        self._run(replace(start), frame_shape(m, dash=True, text=True), "drag")
        if self.docked:
            self.docked = False
            self.docked_changed.emit(False)
        self.frame.rect_changed.emit(m, False)

    def _follow_dash(self, g: _Gesture) -> None:
        m = self._dash_rect(g)
        if m != self.frame.mirror:
            self.frame.set_mirror(m)
            self._retarget(frame_shape(m, dash=True, text=True))
            self.frame.rect_changed.emit(m, False)

    def _dash_rect(self, g: _Gesture) -> Rect:
        size = (g.home[2] - g.home[0], g.home[3] - g.home[1])
        return dash_rect(g.x, g.y, g.grab, size, monitor_at(g.x, g.y, g.mons))

    def _spot_shape(self, g: _Gesture) -> Shape:
        x, y, d = ball_spot(g.edge, g.x, g.y, g.mon)
        return Shape(x, y, d, d, 1.0)

    def _dock(self, g: _Gesture) -> None:
        """拖着球松手：滑过去藏进边缘一部分。魔镜的位置记成开始拖之前的样子，以后点开回到那里。"""
        self.edge, self.mon, self.tucked = g.edge, g.mon, True
        self.along = g.y if g.edge in ("l", "r") else g.x
        self.frame.set_ghost(False)
        self.frame.hide()
        home = fit_rect(g.home, g.mons)
        if home != self.frame.mirror:
            self.frame.set_mirror(home)
        self._docked_at = time.perf_counter()
        self._retarget(self._ball_shape(True), "settle", self._docked_settled)

    def _docked_settled(self) -> None:
        self._end_live(keep=True)
        self._place_ball(self.shape())
        self.ball.setVisible(not self.hidden)
        self._docked_at = time.perf_counter()
        self.glass_refresh(self._docked_at, force=True)
        self.committed.emit()

    def _landed(self) -> None:
        """虚线框（或点开的球）落定成魔镜：形状撤掉，魔镜的边线、标签出来。"""
        self._end_live(keep=False)
        self.ball.hide()
        self.hover_t = 0.0
        self.frame.set_ghost(False)
        if not self.hidden:
            self.frame.show()
        self.frame.rect_changed.emit(self.frame.mirror, True)
        self.committed.emit()

    def unfold(self) -> None:
        """点一下球：魔镜回到收起前的地方，同时开始翻译。"""
        if not self.docked or self.busy:
            return
        self._tuck_timer.stop()
        home = fit_rect(self.frame.mirror, winapi.monitors())
        if home != self.frame.mirror:
            self.frame.set_mirror(home)
        self.ball.hide()
        start = self.shape() or self._ball_shape(self.tucked)
        self._run(replace(start), frame_shape(home, text=True), "settle", self._landed)
        self.docked = False
        self.docked_changed.emit(False)

    # ------------------------------------------------------------------ 球滑出来、藏回去
    def hover(self, on: bool) -> None:
        self.hover_t = time.perf_counter() if on else 0.0
        if not self.docked or self.busy:
            return
        if on:
            self._tuck_timer.stop()
            if self.tucked and time.perf_counter() - self._docked_at > HOVER_GRACE:
                self._slide(False)
        elif not self.tucked:
            self._tuck_timer.start()

    def _tuck(self) -> None:
        if self.docked and not self.busy and not self.tucked and not self.hover_t:
            self._slide(True)

    def _slide(self, tucked: bool) -> None:
        self.tucked = tucked
        target = self._ball_shape(tucked)
        self._slide_backdrop(target)
        self._retarget(target, "slide", self._slid)

    def _slid(self) -> None:
        self._end_live(keep=True)
        self._slide_bg = None

    def _ball_shape(self, tucked: bool) -> Shape:
        x, y, d = ball_rect(self.edge, self.along, self.mon, tucked)
        return Shape(x, y, d, d, 1.0)

    def _place_ball(self, s: Shape | None) -> None:
        if s is not None and self.mon is not None:
            self.ball.place(s, self.edge, self.mon.rect)

    # ------------------------------------------------------------------ 动画
    def _run(self, start: Shape, target: Shape, kind: str, on_settle=None) -> None:
        old = self.shape()
        self.live = _Live(replace(start), target, kind, on_settle)
        self._publish(self.live.cur, old.box() if old is not None else None)
        if not self._timer.isActive():
            self._t = time.perf_counter()
            self._timer.start()

    def _retarget(self, target: Shape, kind: str = "", on_settle=None) -> None:
        """动画的目标换了（跟着鼠标走）；没在动就从现在的样子开始动。"""
        if self.live is None:
            start = self.shape() or target
            self._run(start, target, kind or "drag", on_settle)
            return
        self.live.target = target
        if kind:
            self.live.kind = kind
        if on_settle is not None:
            self.live.on_settle = on_settle
        if not self._timer.isActive():
            self._t = time.perf_counter()
            self._timer.start()

    def _step(self) -> None:
        lv = self.live
        if lv is None:
            self._timer.stop()
            return
        now = time.perf_counter()
        dt, self._t = now - self._t, now
        old = lv.cur.box()
        done = approach(lv.cur, lv.target, dt)
        c = lv.cur
        self.trace.append((now, round(c.x, 1), round(c.y, 1), round(c.w, 1), round(c.h, 1), round(c.k, 3)))
        self._publish(c, old)
        if lv.kind == "slide":
            self._place_ball(c)
            self._glass_follow(c)
        if done:
            self._timer.stop()
            cb, lv.on_settle = lv.on_settle, None
            if cb is not None:
                cb()

    def _end_live(self, keep: bool) -> None:
        self._timer.stop()
        lv, self.live = self.live, None
        if keep and lv is not None:
            self.shapes[id(self)] = replace(lv.cur)
        elif not keep:
            self._clear_shape()

    def _publish(self, s: Shape, old: Rect | None) -> None:
        if glass.active():
            s.dark = self._dark()
        self.shapes[id(self)] = s
        box = s.box()
        self.repaint.emit(geom.union(old, box) if old is not None else box)

    def _clear_shape(self) -> None:
        s = self.shapes.pop(id(self), None)
        if s is not None:
            self.repaint.emit(s.box())
