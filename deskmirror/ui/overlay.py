"""覆盖层：每个显示器一个铺满屏幕的透明窗口，只在魔镜矩形内画译文。

窗口本身不随魔镜移动（译文锚定在屏幕上），移动魔镜只改变裁剪范围并重画进出的区域。
窗口鼠标穿透、不抢焦点、对截屏隐身（不会把自己的译文当原文识别）。
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
from .render import Renderer


class UiState:
    """界面线程共享的显示状态。"""

    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.mirror: Rect = (0, 0, 0, 0)       # 主魔镜（状态、截图、调试命令用）
        self.mirrors: list[Rect] = []          # 所有显示中的魔镜（画译文用）
        self.snapshot: Snapshot | None = None
        self.peek = False           # 按住看原文
        self.hidden = False         # 魔镜隐藏
        self.paused = False         # 用户暂停：框还在，不画译文（画面没在跟踪，留着会错位）
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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        l, t, r, b = mon.rect
        # 比显示器矮 1 像素：避免被系统当成全屏程序（会影响任务栏和通知）。
        self.setGeometry(l, t, r - l, b - t - 1)
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))
        winapi.set_exstyle(int(self.winId()), add=winapi.WS_EX_NOACTIVATE | winapi.WS_EX_TRANSPARENT
                           | winapi.WS_EX_TOOLWINDOW)

    def local(self, r: Rect) -> QRect:
        l, t, _r, _b = self.mon.rect
        return QRect(r[0] - l, r[1] - t, r[2] - r[0], r[3] - r[1])

    def _mirrors(self) -> list[Rect]:
        return self.state.mirrors or [self.state.mirror]

    def repaint_mirror(self, old: Rect | None = None) -> None:
        """重画所有魔镜的范围（以及移动前的范围）。"""
        reg = QRegion()
        for mr in self._mirrors():
            m = geom.inter(mr, self.mon.rect)
            if not geom.empty(m):
                reg = reg.united(QRegion(self.local(m)))
        if old is not None:
            o = geom.inter(old, self.mon.rect)
            if not geom.empty(o):
                reg = reg.united(QRegion(self.local(o)))
        if not reg.isEmpty():
            self.update(reg)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        t0 = time.perf_counter()
        try:
            self._paint(event)
        finally:
            st = self.state
            now = time.perf_counter()
            st.paint_ms.append((now - t0) * 1000)
            if st.snapshot is not None and st.snapshot.stamp > st._painted_stamp:
                st._painted_stamp = st.snapshot.stamp
                st.paint_lat.append((now - st.snapshot.stamp) * 1000)

    def _paint(self, event) -> None:
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(event.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        st = self.state
        snap = st.snapshot
        if snap is None or st.hidden or st.paused:
            p.end()
            return
        mirrors = [m for m in (geom.inter(mr, self.mon.rect) for mr in self._mirrors()) if not geom.empty(m)]
        if not mirrors:
            p.end()
            return
        ml, mt = self.mon.rect[0], self.mon.rect[1]
        if not st.peek:
            self._paint_items(p, snap, mirrors, ml, mt)
        for mirror in mirrors:
            self._paint_mirror(p, snap, mirror)
        p.end()

    def _paint_items(self, p: QPainter, snap: Snapshot, mirrors: list[Rect], ml: int, mt: int) -> None:
        """每段译文只画一次：几个魔镜重叠时，重叠处不会叠出更深的底板。"""
        area = QRegion()
        if len(mirrors) > 1:
            for m in mirrors:
                area = area.united(QRegion(self.local(m)))
        for item in snap.items:
            if not any(geom.overlaps(item.room, m) or geom.overlaps(item.rect, m) for m in mirrors):
                continue
            img = self.state.renderer.get(item)
            x, y = item.rect[0] + img.dx - ml, item.rect[1] + img.dy - mt
            for clip in item.clips:
                if len(mirrors) == 1:
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
                pen = QPen(QColor(220, 60, 60, 200) if failed else QColor(61, 139, 253, 170))
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
                pen = QPen(QColor(255, 140, 0, 220) if axis == "v" else QColor(170, 60, 255, 220))
                pen.setWidth(2)
                pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                c = geom.inter(clip, self.mon.rect)
                if not geom.empty(c):
                    p.drawRect(self.local(c).adjusted(1, 1, -1, -1))
            p.setClipping(False)
