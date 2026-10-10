"""覆盖层：每个显示器一个铺满屏幕的透明窗口，只在魔镜矩形内画译文。

窗口本身不随魔镜移动（译文锚定在屏幕上），移动魔镜只改变裁剪范围并重画进出的区域。
魔镜收成球、从球变回来的形状也画在这里（见 dock.py）：变形期间译文按形状裁剪。
窗口鼠标穿透、不抢焦点、对截屏隐身（不会把自己的译文当原文识别）。Windows 10 上是色键窗口，见 layered.py。
"""
from __future__ import annotations

import collections
import time

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

from .. import geom, winapi
from ..geom import Rect
from ..scene import Snapshot
from . import layered
from .dock import opening_region, paint_shape
from .render import Renderer


class UiState:
    """界面线程共享的显示状态。"""

    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.mirror: Rect = (0, 0, 0, 0)       # 主魔镜（状态、截图、调试命令用）
        self.mirrors: list[Rect] = []          # 所有显示中的魔镜（画译文用；收成球的、正在变形的不在里面）
        self.shapes: dict = {}                 # 正在变形的框和收起的球（dock.Shape）：变形中的译文按形状裁剪
        self.frame_color = QColor("#3D8BFD")   # 魔镜边框的颜色（球也用它）
        self.snapshot: Snapshot | None = None
        self.peek = False           # 按住看原文
        self.hidden = False         # 魔镜隐藏
        self.paused = False         # 用户暂停：框还在，不画译文（画面没在跟踪，留着会错位）
        self.shot_mode = False      # 截图模式：截图工具截得到魔镜，识别、翻译停下，译文定住
        self.debug = False          # 画出识别到的滚动画布边界
        self.hover_bid = 0
        # 调试统计：快照发出到画完的耗时、每次绘制耗时（毫秒）
        self.paint_lat: collections.deque[float] = collections.deque(maxlen=2000)
        self.paint_ms: collections.deque[float] = collections.deque(maxlen=2000)
        self._painted_stamp = 0.0


class Overlay(QWidget):
    def __init__(self, mon: winapi.Monitor, state: UiState) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.mon = mon
        self.state = state
        self.colorkey = layered.colorkey()
        if not self.colorkey:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        l, t, r, b = mon.rect
        # 比显示器矮 1 像素：避免被系统当成全屏程序（会影响任务栏和通知）。
        self.setGeometry(l, t, r - l, b - t - 1)
        self.winId()
        if self.colorkey:
            layered.apply(self)
        winapi.exclude_from_capture(int(self.winId()))
        winapi.set_exstyle(int(self.winId()), add=winapi.WS_EX_NOACTIVATE | winapi.WS_EX_TRANSPARENT
                           | winapi.WS_EX_TOOLWINDOW)

    def _color(self, c: QColor) -> QColor:
        return layered.solid(c) if self.colorkey else c

    def local(self, r: Rect) -> QRect:
        l, t, _r, _b = self.mon.rect
        return QRect(r[0] - l, r[1] - t, r[2] - r[0], r[3] - r[1])

    def _mirrors(self) -> list[Rect]:
        return self.state.mirrors

    def repaint_rect(self, r: Rect) -> None:
        """重画屏幕上的一块（变形中的形状、滑动的球）。"""
        c = geom.inter(r, self.mon.rect)
        if not geom.empty(c):
            self.update(self.local(c))

    def repaint_mirror(self, old: Rect | None = None) -> None:
        """重画所有魔镜的范围（以及移动前的范围、变形中显示译文的形状）。"""
        reg = QRegion()
        for mr in self._mirrors():
            m = geom.inter(mr, self.mon.rect)
            if not geom.empty(m):
                reg = reg.united(QRegion(self.local(m)))
        if old is not None:
            o = geom.inter(old, self.mon.rect)
            if not geom.empty(o):
                reg = reg.united(QRegion(self.local(o)))
        for s in self.state.shapes.values():
            c = geom.inter(s.box(), self.mon.rect)
            if s.text and not geom.empty(c):         # 变形中框里的译文：新快照来了也要重画
                reg = reg.united(QRegion(self.local(c)))
        if not reg.isEmpty():
            self.update(reg)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        t0 = time.perf_counter()
        try:
            self._paint(event)
            if self.colorkey:
                layered.painted(self)
        finally:
            st = self.state
            now = time.perf_counter()
            st.paint_ms.append((now - t0) * 1000)
            if st.snapshot is not None and st.snapshot.stamp > st._painted_stamp:
                st._painted_stamp = st.snapshot.stamp
                st.paint_lat.append((now - st.snapshot.stamp) * 1000)

    def _paint(self, event) -> None:
        p = QPainter(self)
        if self.colorkey:
            p.fillRect(event.rect(), layered.key_color())
        else:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(event.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        st = self.state
        if st.hidden:
            p.end()
            return
        ml, mt = self.mon.rect[0], self.mon.rect[1]
        shapes = [s for s in st.shapes.values() if geom.overlaps(s.box(), self.mon.rect)]
        snap = st.snapshot
        if snap is not None and not st.paused:
            mirrors = [m for m in (geom.inter(mr, self.mon.rect) for mr in self._mirrors()) if not geom.empty(m)]
            # 变形中、框里要显示译文的形状：译文按形状（圆角跟着变）裁剪
            openings = [(geom.inter(s.box(), self.mon.rect), opening_region(s, ml, mt)) for s in shapes if s.text]
            if mirrors or openings:
                if not st.peek:
                    self._paint_items(p, snap, mirrors, openings, ml, mt)
                for mirror in mirrors:
                    self._paint_mirror(p, snap, mirror)
        for s in shapes:
            paint_shape(p, s, ml, mt, st.frame_color, self.colorkey)
        p.end()

    def _paint_items(self, p: QPainter, snap: Snapshot, mirrors: list[Rect], openings: list, ml: int, mt: int) -> None:
        """每段译文只画一次：几个魔镜重叠时，重叠处不会叠出更深的底板。openings：变形中的形状
        （大致范围, 覆盖层坐标的裁剪区域）。"""
        boxes = mirrors + [b for b, _reg in openings]
        area = QRegion()
        if len(boxes) > 1 or openings:
            for m in mirrors:
                area = area.united(QRegion(self.local(m)))
            for _b, reg in openings:
                area = area.united(reg)
        single = len(boxes) == 1 and not openings
        for item in snap.items:
            if not any(geom.overlaps(item.room, m) or geom.overlaps(item.rect, m) for m in boxes):
                continue
            img = self.state.renderer.get(item)
            x, y = item.rect[0] + img.dx - ml, item.rect[1] + img.dy - mt
            for clip in item.clips:
                if single:
                    c = geom.inter(clip, mirrors[0])
                    if geom.empty(c):
                        continue
                    p.setClipRect(self.local(c))
                else:
                    c = geom.inter(clip, self.mon.rect)
                    reg = area.intersected(QRegion(self.local(c))) if not geom.empty(c) else QRegion()
                    if reg.isEmpty():
                        continue
                    p.setClipRegion(reg)
                p.drawImage(x, y, img.image)
        p.setClipping(False)

    def _paint_mirror(self, p: QPainter, snap: Snapshot, mirror: Rect) -> None:
        st = self.state
        if not st.peek:
            # 已识别、正在等译文的块：在镜内画一条细虚线提示“翻译中”；失败的画红色。
            for sr, clips, failed in snap.pending:
                if not geom.overlaps(sr, mirror):
                    continue
                pen = QPen(self._color(QColor(220, 60, 60, 200) if failed else QColor(61, 139, 253, 170)))
                pen.setWidth(2)
                pen.setStyle(Qt.PenStyle.DotLine)
                p.setPen(pen)
                for clip in clips:
                    c = geom.inter(geom.inter(clip, mirror), (sr[0], sr[3] - 1, sr[2], sr[3] + 2))
                    if not geom.empty(c):
                        lc = self.local(c)
                        p.drawLine(lc.left(), lc.top() + 1, lc.right(), lc.top() + 1)
        if st.debug:
            p.setClipRect(self.local(mirror))
            for _cid, clip, axis in snap.status.get("canvases", ()):
                pen = QPen(self._color(QColor(255, 140, 0, 220) if axis == "v" else QColor(170, 60, 255, 220)))
                pen.setWidth(2)
                pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                c = geom.inter(clip, self.mon.rect)
                if not geom.empty(c):
                    p.drawRect(self.local(c).adjusted(1, 1, -1, -1))
            p.setClipping(False)
