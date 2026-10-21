"""截图时的自动框选：鼠标下面有哪些东西可以一下框住——整个窗口、窗口里的子窗口、界面元素（按钮、列表项、面板，
靠 UI Automation）、一段文字（识别进程只找字在哪、不认字）。坐标都是屏幕物理像素。

截图界面盖住了整个屏幕，UI Automation 的“点在哪个元素上”会问到截图界面自己，所以从鼠标下面那个窗口开始一层层往里找：
每层把子元素和它们的矩形一次取回来（带缓存的 FindAll），包住鼠标的都往里找（Chrome 顶层下面有两个和窗口一样大的，
一个是空的），要最深、最小的那一条。放在后台线程里做，
界面线程不等：鼠标停一下才问，结果来了再换框。
"""
from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from ctypes import wintypes as wt
from dataclasses import dataclass

from . import geom
from .geom import Rect

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumChildWindows.argtypes = [wt.HWND, ENUMPROC, wt.LPARAM]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

MIN_W, MIN_H = 12, 10          # 更小的（一个字、图标里的一笔）不要
SAME_PX = 3                    # 四条边都差不到这么多：当成同一个框


@dataclass(frozen=True)
class Candidate:
    rect: Rect
    kind: str                  # element / text / child / window / screen


def child_rects(hwnd: int) -> list[Rect]:
    """窗口里看得见的子窗口（老式 Win32 程序的面板、输入框、按钮）。"""
    out: list[Rect] = []

    def cb(h, _lp):
        if user32.IsWindowVisible(h):
            rc = wt.RECT()
            if user32.GetWindowRect(h, ctypes.byref(rc)):
                r = (rc.left, rc.top, rc.right, rc.bottom)
                if r[2] - r[0] >= MIN_W and r[3] - r[1] >= MIN_H:
                    out.append(r)
        return True

    user32.EnumChildWindows(hwnd, ENUMPROC(cb), 0)
    return out


def excluded_rects(wins, cfg) -> list[Rect]:
    """排除名单里的窗口露在屏幕上的部分（规则和引擎一样：程序名、标题里的词；打开“聊天软件也翻译”时聊天软件不算）。
    wins：Z 序从上到下的 winapi.TopWindow。原位翻译前把这些地方涂掉：和平时一样，不把它们的字发给翻译服务。"""
    from . import winapi
    from .config import CHAT_APPS, CHAT_TITLES
    sc = cfg.scope
    apps = {a.lower() for a in sc.exclude_apps}
    words = [w.lower() for w in sc.exclude_titles]
    if sc.translate_chat:
        apps -= {a.lower() for a in CHAT_APPS}
        chat_words = {w.lower() for w in CHAT_TITLES}
        words = [w for w in words if w not in chat_words]
    names: dict[int, str] = {}
    out: list[Rect] = []
    above: list[Rect] = []
    for w in wins:
        if w.pid not in names:
            names[w.pid] = winapi.process_name(w.pid).lower()
        title = (w.title or winapi.window_title(w.hwnd)).lower() if words else ""
        if names[w.pid] in apps or (words and any(x in title for x in words)):
            vis = [w.rect]
            for a in above:
                vis = geom.subtract_all(vis, a)
            out.extend(vis)
        above.append(w.rect)
    return out


def masked(bgr, origin: tuple[int, int], rects: list[Rect]):
    """把 rects（屏幕坐标）盖住的地方涂成灰色，返回新的图（原图不动）。"""
    import numpy as np
    out = np.array(bgr, copy=True, order="C")
    h, w = out.shape[:2]
    box = (origin[0], origin[1], origin[0] + w, origin[1] + h)
    for r in rects:
        c = geom.inter(r, box)
        if not geom.empty(c):
            out[c[1] - box[1]:c[3] - box[1], c[0] - box[0]:c[2] - box[0]] = 128
    return out


def window_at(x: int, y: int, windows: list[tuple[int, Rect]]) -> tuple[int, Rect] | None:
    """Z 序从上到下的顶层窗口里，最上面那个包住 (x, y) 的。"""
    for hwnd, r in windows:
        if geom.contains_pt(r, x, y):
            return hwnd, r
    return None


def build_chain(x: int, y: int, screen: Rect, window: Rect | None, groups: list[tuple[str, list[Rect]]]) -> list[Candidate]:
    """点 (x, y) 上能框住的东西，从小到大。groups：[(种类, 矩形们)]，比如界面元素、文字段落、子窗口；
    只取包住这个点的，裁到窗口和屏幕里。太小的、和别的几乎一样大的去掉（先来的种类优先）。"""
    bound = geom.inter(window, screen) if window is not None else screen
    found: list[Candidate] = []
    for kind, rects in groups:
        for r in rects:
            if geom.contains_pt(r, x, y):
                c = geom.inter(r, bound)
                if c[2] - c[0] >= MIN_W and c[3] - c[1] >= MIN_H:
                    found.append(Candidate(c, kind))
    if window is not None and not geom.empty(bound):
        found.append(Candidate(bound, "window"))
    found.append(Candidate(screen, "screen"))
    found.sort(key=lambda c: geom.area(c.rect))
    out: list[Candidate] = []
    for c in found:
        same = next((i for i, o in enumerate(out) if all(abs(a - b) <= SAME_PX for a, b in zip(c.rect, o.rect))), None)
        if same is None:
            out.append(c)
        elif c.kind in ("window", "screen"):
            out[same] = c        # 和整个窗口（屏幕）一样大的元素、子窗口就是这个窗口（屏幕）
    return out


# --------------------------------------------------------------------- UI Automation
class UiaProbe:
    """后台线程：ask(token, hwnd, x, y) → on_result(token, [矩形，从小到大])，在后台线程里回调。
    只回答最新的那个问题（鼠标一直在动时前面的作废）。"""

    TIME_BUDGET = 0.3          # 一次最多找这么久（复杂的网页一层几百个子元素）
    FANOUT = 4                 # 每层包住鼠标的子元素最多试这么多个（从小的试起）
    MAX_DEPTH = 40

    def __init__(self, on_result) -> None:
        self._q: queue.Queue = queue.Queue()
        self._on_result = on_result
        self.last_ms = 0.0                 # 上一次找了多久（调试用）
        self._thread = threading.Thread(target=self._run, name="snip-uia", daemon=True)
        self._thread.start()

    def ask(self, token, hwnd: int, x: int, y: int) -> None:
        self._q.put((token, hwnd, x, y))

    def close(self) -> None:
        self._q.put(None)

    def _run(self) -> None:
        from . import uia as U
        U.ole32.CoInitializeEx(None, 0)          # COINIT_MULTITHREADED
        out = U.P()
        hr = U.ole32.CoCreateInstance(ctypes.byref(U.CLSID_CUIAutomation), None, 1, ctypes.byref(U.IID_IUIAutomation),
                                      ctypes.byref(out))
        ua = out.value if hr >= 0 else 0
        cond = U._out_ptr(ua, 18) if ua else 0                                      # get_ControlViewCondition
        cache = U._out_ptr(ua, 20) if ua else 0                                     # CreateCacheRequest
        if cache:
            U._call(cache, 3, 30001, argtypes=(ctypes.c_int,))                      # AddProperty(BoundingRectangle)
        ok = bool(ua and cond and cache)
        if not ok:
            log.info("截图：UI Automation 不可用，只框窗口和文字")
        try:
            while True:
                item = self._q.get()
                while True:                        # 只答最新的
                    try:
                        newer = self._q.get_nowait()
                    except queue.Empty:
                        break
                    item = newer
                    if item is None:
                        break
                if item is None:
                    return
                token, hwnd, x, y = item
                rects: list[Rect] = []
                t0 = time.perf_counter()
                if ok:
                    try:
                        rects = self._chain(U, ua, cond, cache, hwnd, x, y)
                    except Exception:  # noqa: BLE001
                        log.debug("截图：UI Automation 出错", exc_info=True)
                self.last_ms = (time.perf_counter() - t0) * 1000
                self._on_result(token, rects)
        finally:
            for obj in (cache, cond, ua):
                U._release(obj)

    def _chain(self, U, ua: int, cond: int, cache: int, hwnd: int, x: int, y: int) -> list[Rect]:
        """从窗口往里找包住 (x, y) 的元素：返回最深、最小的那条路上的矩形，从小到大。超时就用已经找到的。"""
        root = U._out_ptr(ua, 6, hwnd, argtypes=(wt.HWND,))                        # ElementFromHandle
        if not root:
            return []
        t0 = time.perf_counter()
        best: list[Rect] = []

        def visit(el: int, path: list[Rect]) -> None:
            nonlocal best
            if len(path) >= self.MAX_DEPTH or time.perf_counter() - t0 > self.TIME_BUDGET:
                return
            hits = self._hits(U, el, cond, cache, x, y)
            try:
                for e, r in hits[:self.FANOUT]:
                    p = path + [r]
                    if not best or geom.area(r) < geom.area(best[-1]) or (
                            geom.area(r) == geom.area(best[-1]) and len(p) > len(best)):
                        best = p
                    visit(e, p)
            finally:
                for e, _r in hits:
                    U._release(e)

        try:
            visit(root, [])
        finally:
            U._release(root)
        return list(reversed(best))

    @staticmethod
    def _hits(U, el: int, cond: int, cache: int, x: int, y: int) -> list[tuple[int, Rect]]:
        """el 的子元素里包住 (x, y) 的，从小到大（用完要 release）。"""
        arr = U._out_ptr(el, 8, 2, cond, cache, argtypes=(ctypes.c_int, U.P, U.P))      # FindAllBuildCache(子元素)
        if not arr:
            return []
        out: list[tuple[int, Rect]] = []
        try:
            n = U._int(arr, 3) or 0                                                     # Length
            for i in range(min(n, 2000)):
                e = U._out_ptr(arr, 4, i, argtypes=(ctypes.c_int,))                    # GetElement
                if not e:
                    continue
                rc = wt.RECT()
                U._call(e, 75, ctypes.byref(rc), argtypes=(ctypes.POINTER(wt.RECT),))  # CachedBoundingRectangle
                r = (rc.left, rc.top, rc.right, rc.bottom)
                if r[2] > r[0] and r[3] > r[1] and geom.contains_pt(r, x, y):
                    out.append((e, r))
                else:
                    U._release(e)
        finally:
            U._release(arr)
        out.sort(key=lambda er: geom.area(er[1]))
        return out
