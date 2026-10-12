"""DirectComposition（系统合成器）的最小封装：译文层用它把译文交给系统合成，滚动时由系统每一帧移动。

用法见 glide.py。只用到这几样：显卡设备（D3D11，BGRA）、合成设备、窗口目标、视觉（位置、裁剪、内容、子视觉）、
表面（一块像素，从内存上传）、动画（按绝对时刻的分段多项式，系统在每次合成时取值）。
全部在界面线程里调用。COM 对象按虚表序号调用（和 capture.py 一样）；重载的方法在虚表里是倒序排的
（MSVC 的规矩：后声明的在前），例如 IDCompositionVisual 的 3 = SetOffsetX(动画)、4 = SetOffsetX(数值)。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from ..capture import D3D11_BOX, GUID, HRESULT, Com, ComError, _guid, _QPF

IID_IDXGIDevice = _guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_IDCompositionDevice = _guid("C37EA93A-E7AA-450D-B16F-9746CB0407F3")
IID_ID3D11Texture2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")

D3D_DRIVER_TYPE_HARDWARE = 1
D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20
DXGI_FORMAT_B8G8R8A8_UNORM = 87
DXGI_ALPHA_MODE_PREMULTIPLIED = 1

_PP = ctypes.POINTER(ctypes.c_void_p)
_CUBIC = (ctypes.c_double, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float)


class D2D_RECT_F(ctypes.Structure):
    _fields_ = [("left", ctypes.c_float), ("top", ctypes.c_float), ("right", ctypes.c_float),
                ("bottom", ctypes.c_float)]


def _new(com: Com, what: str, index: int, argtypes: tuple = (), *args) -> Com:
    out = ctypes.c_void_p()
    com.hr(what, index, argtypes + (_PP,), *args, ctypes.byref(out))
    return Com(out)


class Device:
    """一个显卡设备 + 合成设备；所有窗口、视觉、表面都从这里建。"""

    def __init__(self) -> None:
        d3d11 = ctypes.WinDLL("d3d11")
        dptr, cptr, level = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_uint()
        hr = d3d11.D3D11CreateDevice(None, D3D_DRIVER_TYPE_HARDWARE, None, D3D11_CREATE_DEVICE_BGRA_SUPPORT, None, 0,
                                     7, ctypes.byref(dptr), ctypes.byref(level), ctypes.byref(cptr)) & 0xFFFFFFFF
        if hr & 0x80000000:
            raise ComError("D3D11CreateDevice", hr)
        self._d3d, self._ctx = Com(dptr), Com(cptr)
        dxgi = self._d3d.query(IID_IDXGIDevice)
        try:
            out = ctypes.c_void_p()
            dcomp = ctypes.WinDLL("dcomp")
            dcomp.DCompositionCreateDevice.restype = HRESULT
            hr = dcomp.DCompositionCreateDevice(dxgi.ptr, ctypes.byref(IID_IDCompositionDevice),
                                                ctypes.byref(out)) & 0xFFFFFFFF
            if hr & 0x80000000:
                raise ComError("DCompositionCreateDevice", hr)
            self._dc = Com(out)
        finally:
            dxgi.release()
        self._update = self._ctx.fn(48, None, ctypes.c_void_p, wt.UINT, ctypes.POINTER(D3D11_BOX), ctypes.c_void_p,
                                    wt.UINT, wt.UINT)          # ID3D11DeviceContext::UpdateSubresource

    def target(self, hwnd: int) -> "Target":
        return Target(_new(self._dc, "CreateTargetForHwnd", 6, (wt.HWND, wt.BOOL), hwnd, True))

    def visual(self) -> "Visual":
        return Visual(_new(self._dc, "CreateVisual", 7))

    def surface(self, w: int, h: int) -> "Surface":
        return Surface(self, _new(self._dc, "CreateSurface", 8, (wt.UINT, wt.UINT, ctypes.c_uint, ctypes.c_uint),
                                  max(1, w), max(1, h), DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_ALPHA_MODE_PREMULTIPLIED), w, h)

    def animation(self, points: list[tuple[float, float]]) -> "Com":
        """按 (绝对时刻 perf_counter 秒, 值) 折线建一个动画：点与点之间匀速，最后一点之后停在那个值。"""
        anim = _new(self._dc, "CreateAnimation", 25)
        t0 = points[0][0]
        anim.hr("SetAbsoluteBeginTime", 4, (ctypes.c_longlong,), int(round(t0 * _QPF)))
        for (ta, va), (tb, vb) in zip(points, points[1:]):
            if tb > ta:
                anim.hr("AddCubic", 5, _CUBIC, ta - t0, va, (vb - va) / (tb - ta), 0.0, 0.0)
        anim.hr("End", 8, (ctypes.c_double, ctypes.c_float), max(0.0, points[-1][0] - t0), points[-1][1])
        return anim

    def commit(self) -> None:
        self._dc.hr("Commit", 3, ())

    def close(self) -> None:
        for c in (self._dc, self._ctx, self._d3d):
            c.release()


class Target:
    def __init__(self, com: Com) -> None:
        self.com = com

    def set_root(self, v: "Visual | None") -> None:
        self.com.hr("SetRoot", 3, (ctypes.c_void_p,), v.com.ptr if v is not None else None)

    def release(self) -> None:
        self.com.release()


class Visual:
    __slots__ = ("com",)

    def __init__(self, com: Com) -> None:
        self.com = com

    def offset(self, x: float, y: float) -> None:
        self.com.hr("SetOffsetX", 4, (ctypes.c_float,), x)
        self.com.hr("SetOffsetY", 6, (ctypes.c_float,), y)

    def animate(self, axis: str, anim: Com) -> None:
        """位置的一个分量交给动画（系统合成时按当时的时刻取值）。"""
        self.com.hr("SetOffset" + axis.upper(), 3 if axis == "x" else 5, (ctypes.c_void_p,), anim.ptr)

    def set_offset(self, axis: str, v: float) -> None:
        self.com.hr("SetOffset" + axis.upper(), 4 if axis == "x" else 6, (ctypes.c_float,), v)

    def clip(self, r: tuple[float, float, float, float] | None) -> None:
        if r is None:
            self.com.hr("SetClip", 13, (ctypes.c_void_p,), None)
        else:
            self.com.hr("SetClip", 14, (ctypes.POINTER(D2D_RECT_F),), ctypes.byref(D2D_RECT_F(*r)))

    def content(self, s: "Surface | None") -> None:
        self.com.hr("SetContent", 15, (ctypes.c_void_p,), s.com.ptr if s is not None else None)

    def add(self, child: "Visual", above: bool = True) -> None:
        """加一个子视觉：above=True 放在所有兄弟的最上面，False 放在最下面。"""
        self.com.hr("AddVisual", 16, (ctypes.c_void_p, wt.BOOL, ctypes.c_void_p), child.com.ptr, above, None)

    def remove(self, child: "Visual") -> None:
        self.com.hr("RemoveVisual", 17, (ctypes.c_void_p,), child.com.ptr)

    def remove_all(self) -> None:
        self.com.hr("RemoveAllVisuals", 18, ())

    def release(self) -> None:
        self.com.release()


class Surface:
    __slots__ = ("dev", "com", "w", "h")

    def __init__(self, dev: Device, com: Com, w: int, h: int) -> None:
        self.dev, self.com, self.w, self.h = dev, com, w, h

    def upload(self, data: int, stride: int) -> None:
        """整块换成内存里的像素（预乘透明度的 BGRA，data 是首地址，stride 是每行字节数）。"""
        tex, off = ctypes.c_void_p(), wt.POINT()
        self.com.hr("BeginDraw", 3, (ctypes.c_void_p, ctypes.POINTER(GUID), _PP, ctypes.POINTER(wt.POINT)), None,
                    ctypes.byref(IID_ID3D11Texture2D), ctypes.byref(tex), ctypes.byref(off))
        t = Com(tex)
        try:
            box = D3D11_BOX(off.x, off.y, 0, off.x + self.w, off.y + self.h, 1)
            self.dev._update(self.dev._ctx.ptr, t.ptr, 0, ctypes.byref(box), data, stride, 0)
        finally:
            t.release()
            self.com.hr("EndDraw", 4, ())

    def release(self) -> None:
        self.com.release()
