"""译文层（系统合成器版）：滚动时由 Windows 的合成器每一帧移动译文。

原来的译文层（overlay.py）是一张铺满屏幕的透明窗口，引擎每发来一次新位置就把魔镜里整块重画、交给系统。
它最快也只能跟着引擎每秒几十次一格一格地跳，而且总比屏幕上的原文晚几帧。这里把每块译文做成系统合成器
（DirectComposition）里的一块“视觉”，交给系统合成：

- 同一个画布（一块滚动区域）里的译文挂在同一个“移动层”上，滚动只改这一层的位置，译文本身不用重画；
- 正在滚动时，引擎给出接下来位移随时间的折线（滚轮学到的曲线，或按速度外推的一小段），交给系统当动画：
  系统每合成一帧，就按这一帧显示出来的时刻取值。屏幕刷新多快，译文就跟多快，不经过我们的程序；
- 移动层外面套一层不动的“裁剪层”，裁到魔镜里、窗口没被挡住的部分（和原来的译文层一样）。

窗口本身鼠标穿透、不抢焦点、对截屏隐身。等待提示、变形中的形状、收起的球、调试框还是原来的译文层画；
Windows 10 的色键窗口（ui/layered.py）不用这一层。截图、录制时的译文仍用原来的绘制代码画（见 app.py）。
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes as wt
from dataclasses import dataclass, field

import numpy as np

from .. import geom, winapi
from ..geom import Rect
from ..scene import DrawItem
from . import dcomp

log = logging.getLogger(__name__)

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOREDIRECTIONBITMAP = 0x80000, 0x20, 0x00200000
LWA_ALPHA = 2
SW_SHOWNOACTIVATE = 4
CLASS_NAME = "DeskMirrorGlide"
MARGIN = 24                  # 块离裁剪范围这么近（或曲线上会经过）就先挂上，滚进来时已经在那儿

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
                ("hIconSm", wt.HICON)]


_user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
_user32.CreateWindowExW.restype = wt.HWND
_user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.DWORD, wt.BYTE, wt.DWORD]
_user32.DestroyWindow.argtypes = [wt.HWND]
_user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wt.HMODULE
_class_ok = False


def _make_window(rect: Rect) -> int:
    """一块显示器大小（矮 1 像素，免得被当成全屏程序）的窗口：没有自己的画面（内容全由合成器给），
    鼠标穿透、不抢焦点、不进任务栏、对截屏隐身。隐身失败就不用这一层（返回前已关掉窗口，抛出 OSError）。"""
    global _class_ok
    hinst = _kernel32.GetModuleHandleW(None)
    if not _class_ok:
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(_user32.DefWindowProcW, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = CLASS_NAME
        if not _user32.RegisterClassExW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:   # 1410：已经注册过
            raise ctypes.WinError(ctypes.get_last_error())
        _class_ok = True
    l, t, r, b = rect
    ex = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOREDIRECTIONBITMAP
    hwnd = _user32.CreateWindowExW(ex, CLASS_NAME, "DeskMirror glide", WS_POPUP, l, t, r - l, b - t - 1, None, None,
                                   hinst, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    _user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    if not winapi.exclude_from_capture(int(hwnd)):
        _user32.DestroyWindow(hwnd)
        raise OSError("SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) failed")
    _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    return int(hwnd)


# ---------------------------------------------------------------------------------------------- 规划（纯计算，可单测）
@dataclass
class GroupPlan:
    """一个画布在一块裁剪范围里的译文：裁剪范围不动，里面的译文按画布的位移（曲线）一起动。"""
    clip: Rect                                  # 屏幕坐标
    origin: tuple[int, int]                     # 画布在这份快照里的屏幕位移（和 items 的位置一致）
    curve: tuple = ()                           # ((时刻, x, y), ...)：画布位移接下来怎么变；空 = 不动
    items: list[DrawItem] = field(default_factory=list)


def disjoint(rects: list[Rect]) -> list[Rect]:
    """几个魔镜重叠时切成互不重叠的几块（重叠处的译文只画一次，半透明的底板不会叠深）。"""
    out: list[Rect] = []
    for r in rects:
        pieces = [r]
        for o in out:
            pieces = geom.subtract_all(pieces, o)
        out.extend(p for p in pieces if not geom.empty(p))
    return out


def travel(curve: tuple, origin: tuple[int, int]) -> tuple[float, float, float, float]:
    """曲线上画布相对此刻位置最远会走到哪：(左, 上, 右, 下) 的偏移。"""
    if not curve:
        return 0.0, 0.0, 0.0, 0.0
    xs = [x - origin[0] for _t, x, _y in curve]
    ys = [y - origin[1] for _t, _x, y in curve]
    return min(0.0, min(xs)), min(0.0, min(ys)), max(0.0, max(xs)), max(0.0, max(ys))


def plan(items, origins: dict, curves: dict, mirrors: list[Rect]) -> dict[tuple, GroupPlan]:
    """快照里的译文按 (画布, 第几块可见范围, 第几块魔镜) 分组；块（连同排版可用的范围、曲线上会走过的路）
    碰到这组的裁剪范围才挂上去。"""
    pieces = disjoint([m for m in mirrors if not geom.empty(m)])
    out: dict[tuple, GroupPlan] = {}
    reach: dict[int, tuple] = {}
    for it in items:
        origin = origins.get(it.cid, (0, 0))
        curve = curves.get(it.cid, ())
        tr = reach.get(it.cid)
        if tr is None:
            tr = reach[it.cid] = travel(curve, origin)
        box = geom.union(it.rect, it.room)
        ext = (box[0] + tr[0] - MARGIN, box[1] + tr[1] - MARGIN, box[2] + tr[2] + MARGIN, box[3] + tr[3] + MARGIN)
        for ci, c in enumerate(it.clips):
            for pj, p in enumerate(pieces):
                r = geom.inter(c, p)
                if geom.empty(r) or not geom.overlaps(ext, r):
                    continue
                key = (it.cid, ci, pj)
                g = out.get(key)
                if g is None:
                    g = out[key] = GroupPlan(r, origin, curve)
                g.items.append(it)
    return out


# ---------------------------------------------------------------------------------------------- 合成器里的视觉树
class _Group:
    __slots__ = ("clipv", "movev", "items", "clip", "motion")

    def __init__(self, dev: dcomp.Device, root: dcomp.Visual) -> None:
        self.clipv = dev.visual()
        self.movev = dev.visual()
        self.clipv.add(self.movev)
        root.add(self.clipv)
        self.items: dict[int, list] = {}         # bid → [视觉, 表面, 位置]
        self.clip = None
        self.motion = None


class _Layer:
    """一块显示器上的窗口和它的视觉树。"""

    def __init__(self, dev: dcomp.Device, mon: winapi.Monitor) -> None:
        self.mon = mon
        self.hwnd = _make_window(mon.rect)
        try:
            self.target = dev.target(self.hwnd)
            self.root = dev.visual()
            self.target.set_root(self.root)
        except OSError:
            _user32.DestroyWindow(self.hwnd)
            raise
        self.groups: dict[tuple, _Group] = {}

    def close(self) -> None:
        for g in self.groups.values():
            for v, _s, _o in g.items.values():
                v.release()
            g.movev.release()
            g.clipv.release()
        self.groups.clear()
        try:
            self.target.set_root(None)
        except OSError:
            pass
        self.root.release()
        self.target.release()
        _user32.DestroyWindow(self.hwnd)


class Glide:
    """所有显示器的译文层（系统合成器）。建不起来（没有合适的显卡接口、不能对截屏隐身）就抛出 OSError，
    由调用的人退回原来的译文层。"""

    def __init__(self, monitors: list[winapi.Monitor], renderer) -> None:
        self.renderer = renderer
        self.dev = dcomp.Device()
        self.layers: list[_Layer] = []
        try:
            for m in monitors:
                self.layers.append(_Layer(self.dev, m))
            self.dev.commit()
        except OSError:
            self.close()
            raise
        self._plates: dict[int, tuple] = {}      # bid → (排好的图 Rendered, 表面)
        self.trace: list | None = None          # 调试：每次交给合成器的位移（测滚动跟随用，平时 None）
        self.syncs = 0
        self.commits = 0
        self.sync_ms = 0.0

    def hwnds(self) -> list[int]:
        return [ly.hwnd for ly in self.layers]

    def _plate(self, it: DrawItem):
        r = self.renderer.get(it)
        hit = self._plates.get(it.bid)
        if hit is not None and hit[0] is r:
            return r, hit[1]
        img = r.image
        surf = self.dev.surface(img.width(), img.height())
        bits = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes())
        surf.upload(bits.ctypes.data, img.bytesPerLine())
        if hit is not None:
            hit[1].release()                     # 视觉还在用的话合成器自己留着它，这里只放掉我们的引用
        self._plates[it.bid] = (r, surf)
        return r, surf

    def sync(self, snap, mirrors: list[Rect], show: bool = True) -> None:
        """按快照摆好所有译文（show=False：全部拿掉，比如按住看原文、隐藏、暂停）。"""
        t0 = time.perf_counter()
        items = snap.items if (show and snap is not None) else ()
        want = plan(items, snap.origins if snap is not None else {}, snap.curves if snap is not None else {}, mirrors)
        changed = False         # 什么都没变就不提交：每次提交，桌面复制都会把整屏报成“变了”
        for ly in self.layers:
            L, T = ly.mon.rect[0], ly.mon.rect[1]
            mine = {k: g for k, g in want.items() if geom.overlaps(g.clip, ly.mon.rect)}
            for k in [k for k in ly.groups if k not in mine]:
                changed = True
                g = ly.groups.pop(k)
                ly.root.remove(g.clipv)
                for v, _s, _o in g.items.values():
                    v.release()
                g.movev.release()
                g.clipv.release()
            for k, gp in mine.items():
                g = ly.groups.get(k)
                if g is None:
                    g = ly.groups[k] = _Group(self.dev, ly.root)
                    changed = True
                c = geom.inter(gp.clip, ly.mon.rect)
                clip = (c[0] - L, c[1] - T, c[2] - L, c[3] - T)
                if g.clip != clip:
                    g.clipv.clip(clip)
                    g.clip = clip
                    changed = True
                motion = gp.curve or ("static", gp.origin)
                if g.motion != motion:
                    self._move(g, gp.origin, gp.curve, L, T, k[0])
                    g.motion = motion
                    changed = True
                seen = set()
                for it in gp.items:
                    r, surf = self._plate(it)
                    pos = (it.rect[0] - gp.origin[0] + r.dx, it.rect[1] - gp.origin[1] + r.dy)
                    rec = g.items.get(it.bid)
                    if rec is None:
                        v = self.dev.visual()
                        v.content(surf)
                        v.offset(*pos)
                        g.movev.add(v, above=it.bid > 0)       # 换句时垫的空底板（负的编号）放在最下面
                        g.items[it.bid] = [v, surf, pos]
                        changed = True
                    else:
                        if rec[1] is not surf:
                            rec[0].content(surf)
                            rec[1] = surf
                            changed = True
                        if rec[2] != pos:
                            rec[0].offset(*pos)
                            rec[2] = pos
                            changed = True
                    seen.add(it.bid)
                for bid in [b for b in g.items if b not in seen]:
                    v, _s, _o = g.items.pop(bid)
                    g.movev.remove(v)
                    v.release()
                    changed = True
        if changed:
            self.dev.commit()
            self.commits += 1
        if snap is not None:
            live = {it.bid for it in snap.items}
            for bid in [b for b in self._plates if b not in live]:
                self._plates.pop(bid)[1].release()
        self.syncs += 1
        self.sync_ms += (time.perf_counter() - t0) * 1000

    def move(self, curves: dict) -> None:
        """只换位移曲线（引擎量到新位移后马上发来的，见 Engine._publish_motion）：译文本身不动。"""
        changed = False
        for ly in self.layers:
            L, T = ly.mon.rect[0], ly.mon.rect[1]
            for key, g in ly.groups.items():
                curve = curves.get(key[0])
                if curve is None or g.motion == curve:
                    continue
                self._move(g, None, curve, L, T, key[0])
                g.motion = curve
                changed = True
        if changed:
            self.dev.commit()
            self.commits += 1

    def _move(self, g: _Group, origin, curve: tuple, L: int, T: int, cid: int) -> None:
        """移动层的位置：不动就是一个数；在动就把曲线交给合成器（两个方向分别看，只有一个方向在动时另一个是数）。"""
        if not curve:
            g.movev.offset(origin[0] - L, origin[1] - T)
            if self.trace is not None:
                self.trace.append((time.perf_counter(), cid, origin, ()))
            return
        for k, axis, base in ((1, "x", L), (2, "y", T)):
            vals = [p[k] - base for p in curve]
            if max(vals) - min(vals) < 0.01:
                g.movev.set_offset(axis, vals[0])
            else:
                anim = self.dev.animation([(p[0], v) for p, v in zip(curve, vals)])
                g.movev.animate(axis, anim)
                anim.release()
        if self.trace is not None:
            self.trace.append((time.perf_counter(), cid, origin or (curve[0][1], curve[0][2]), curve))

    def close(self) -> None:
        for ly in self.layers:
            try:
                ly.close()
            except OSError:
                log.debug("关闭译文层（合成器）出错", exc_info=True)
        self.layers = []
        for _r, s in getattr(self, "_plates", {}).values():
            s.release()
        self._plates = {}
        try:
            self.dev.commit()
        except OSError:
            pass
        self.dev.close()
