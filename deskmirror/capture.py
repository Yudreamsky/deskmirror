"""桌面采集：DXGI Desktop Duplication（首选）与 GDI（mss，兜底）。

Desktop Duplication 只在画面变化时交付新帧，并附带系统给出的脏矩形，
复制在显卡上完成，4K 屏也只需几毫秒；鼠标指针不在画面里。设置了
WDA_EXCLUDEFROMCAPTURE 的魔镜窗口不会出现在采集结果中（启动时实测核对）。

脏矩形只用来缩小比较范围：真正的“哪里变了、怎么变”由 tracker 按像素判断。
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
import uuid
from ctypes import wintypes as wt
from dataclasses import dataclass, field

import numpy as np

from .i18n import tr

log = logging.getLogger(__name__)

HRESULT = ctypes.c_long
S_OK = 0
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027
DXGI_ERROR_ACCESS_LOST = 0x887A0026
DXGI_ERROR_INVALID_CALL = 0x887A0001
E_ACCESSDENIED = 0x80070005
DXGI_FORMAT_B8G8R8A8_UNORM = 87
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1
D3D11_SDK_VERSION = 7


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> GUID:
    u = uuid.UUID(text)
    g = GUID(u.fields[0], u.fields[1], u.fields[2])
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


IID_IDXGIFactory1 = _guid("770aae78-f26f-4dba-a829-253c83d1b387")
IID_IDXGIOutput1 = _guid("00cddea8-939b-4b83-a340-a685226666cc")
IID_ID3D11Texture2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")


class DXGI_OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", wt.WCHAR * 32), ("DesktopCoordinates", wt.RECT), ("AttachedToDesktop", wt.BOOL),
                ("Rotation", ctypes.c_uint), ("Monitor", wt.HMONITOR)]


class DXGI_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wt.UINT), ("Denominator", wt.UINT)]


class DXGI_MODE_DESC(ctypes.Structure):
    _fields_ = [("Width", wt.UINT), ("Height", wt.UINT), ("RefreshRate", DXGI_RATIONAL), ("Format", ctypes.c_uint),
                ("ScanlineOrdering", ctypes.c_uint), ("Scaling", ctypes.c_uint)]


class DXGI_OUTDUPL_DESC(ctypes.Structure):
    _fields_ = [("ModeDesc", DXGI_MODE_DESC), ("Rotation", ctypes.c_uint), ("DesktopImageInSystemMemory", wt.BOOL)]


class DXGI_OUTDUPL_POINTER_POSITION(ctypes.Structure):
    _fields_ = [("Position", wt.POINT), ("Visible", wt.BOOL)]


class DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):
    _fields_ = [("LastPresentTime", ctypes.c_longlong), ("LastMouseUpdateTime", ctypes.c_longlong),
                ("AccumulatedFrames", wt.UINT), ("RectsCoalesced", wt.BOOL), ("ProtectedContentMaskedOut", wt.BOOL),
                ("PointerPosition", DXGI_OUTDUPL_POINTER_POSITION), ("TotalMetadataBufferSize", wt.UINT),
                ("PointerShapeBufferSize", wt.UINT)]


class DXGI_OUTDUPL_MOVE_RECT(ctypes.Structure):
    _fields_ = [("SourcePoint", wt.POINT), ("DestinationRect", wt.RECT)]


class DXGI_SAMPLE_DESC(ctypes.Structure):
    _fields_ = [("Count", wt.UINT), ("Quality", wt.UINT)]


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", wt.UINT), ("Height", wt.UINT), ("MipLevels", wt.UINT), ("ArraySize", wt.UINT),
                ("Format", ctypes.c_uint), ("SampleDesc", DXGI_SAMPLE_DESC), ("Usage", ctypes.c_uint),
                ("BindFlags", wt.UINT), ("CPUAccessFlags", wt.UINT), ("MiscFlags", wt.UINT)]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", wt.UINT), ("DepthPitch", wt.UINT)]


class D3D11_BOX(ctypes.Structure):
    _fields_ = [("left", wt.UINT), ("top", wt.UINT), ("front", wt.UINT), ("right", wt.UINT), ("bottom", wt.UINT),
                ("back", wt.UINT)]


class ComError(OSError):
    def __init__(self, what: str, hr: int) -> None:
        super().__init__(tr("{what} 失败 0x{hr:08X}").format(what=what, hr=hr & 0xFFFFFFFF))
        self.hr = hr & 0xFFFFFFFF


class Com:
    """最小的 COM 指针包装：按虚表序号调用方法。"""

    __slots__ = ("ptr", "_cache")

    def __init__(self, ptr: ctypes.c_void_p) -> None:
        self.ptr = ptr
        self._cache: dict[int, object] = {}

    def fn(self, index: int, restype, *argtypes):
        f = self._cache.get(index)
        if f is None:
            vtbl = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            f = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
            self._cache[index] = f
        return f

    def hr(self, what: str, index: int, argtypes: tuple, *args) -> int:
        hr = self.fn(index, HRESULT, *argtypes)(self.ptr, *args) & 0xFFFFFFFF
        if hr & 0x80000000:
            raise ComError(what, hr)
        return hr

    def query(self, iid: GUID) -> "Com":
        out = ctypes.c_void_p()
        self.hr("QueryInterface", 0, (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(iid),
                ctypes.byref(out))
        return Com(out)

    def release(self) -> None:
        if self.ptr:
            self.fn(2, wt.ULONG)(self.ptr)
            self.ptr = ctypes.c_void_p()
            self._cache.clear()


_dxgi = ctypes.WinDLL("dxgi")
_d3d11 = ctypes.WinDLL("d3d11")
_dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
_dxgi.CreateDXGIFactory1.restype = HRESULT
_d3d11.D3D11CreateDevice.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, wt.UINT, ctypes.c_void_p, wt.UINT,
                                     wt.UINT, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint),
                                     ctypes.POINTER(ctypes.c_void_p)]
_d3d11.D3D11CreateDevice.restype = HRESULT

Rect = tuple[int, int, int, int]


def _qpc_frequency() -> int:
    f = ctypes.c_longlong()
    ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(f))
    return f.value or 10_000_000


_QPF = _qpc_frequency()      # 桌面复制给的时刻是 QueryPerformanceCounter 的计数；perf_counter 用的是同一个时钟


class _RATIO(ctypes.Structure):
    _fields_ = [("num", ctypes.c_uint32), ("den", ctypes.c_uint32)]


class DWM_TIMING_INFO(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("cbSize", ctypes.c_uint32), ("rateRefresh", _RATIO), ("qpcRefreshPeriod", ctypes.c_uint64),
                ("rateCompose", _RATIO), ("qpcVBlank", ctypes.c_uint64), ("cRefresh", ctypes.c_uint64),
                ("cDXRefresh", ctypes.c_uint32), ("qpcCompose", ctypes.c_uint64), ("cFrame", ctypes.c_uint64),
                ("cDXPresent", ctypes.c_uint32), ("cRefreshFrame", ctypes.c_uint64), ("cFrameSubmitted", ctypes.c_uint64),
                ("cDXPresentSubmitted", ctypes.c_uint32), ("cFrameConfirmed", ctypes.c_uint64),
                ("cDXPresentConfirmed", ctypes.c_uint32), ("cRefreshConfirmed", ctypes.c_uint64),
                ("cDXRefreshConfirmed", ctypes.c_uint32), ("cFramesLate", ctypes.c_uint64),
                ("cFramesOutstanding", ctypes.c_uint32), ("cFrameDisplayed", ctypes.c_uint64),
                ("qpcFrameDisplayed", ctypes.c_uint64), ("cRefreshFrameDisplayed", ctypes.c_uint64),
                ("cFrameComplete", ctypes.c_uint64), ("qpcFrameComplete", ctypes.c_uint64),
                ("cFramePending", ctypes.c_uint64), ("qpcFramePending", ctypes.c_uint64),
                ("cFramesDisplayed", ctypes.c_uint64), ("cFramesComplete", ctypes.c_uint64),
                ("cFramesPending", ctypes.c_uint64), ("cFramesAvailable", ctypes.c_uint64),
                ("cFramesDropped", ctypes.c_uint64), ("cFramesMissed", ctypes.c_uint64),
                ("cRefreshNextDisplayed", ctypes.c_uint64), ("cRefreshNextPresented", ctypes.c_uint64),
                ("cRefreshesDisplayed", ctypes.c_uint64), ("cRefreshesPresented", ctypes.c_uint64),
                ("cRefreshStarted", ctypes.c_uint64), ("cPixelsReceived", ctypes.c_uint64),
                ("cPixelsDrawn", ctypes.c_uint64), ("cBuffersEmpty", ctypes.c_uint64)]


_dwmapi = ctypes.WinDLL("dwmapi")
_dwmapi.DwmGetCompositionTimingInfo.argtypes = [wt.HWND, ctypes.POINTER(DWM_TIMING_INFO)]
_dwmapi.DwmGetCompositionTimingInfo.restype = HRESULT


def compose_clock() -> tuple[float, float] | None:
    """系统合成器的节拍：(这一次合成对应的垂直同步时刻, 刷新周期)，秒（perf_counter 的时间轴）；取不到返回 None。

    实测（桌面复制 + 合成器动画）：取到新的一帧后马上问，这个时刻正是系统给这一帧里的动画取值的时刻，
    也就是这一帧画面算作“显示出来”的时刻；桌面复制报的 LastPresentTime 比它早 1～2 个周期，还忽前忽后。"""
    ti = DWM_TIMING_INFO()
    ti.cbSize = ctypes.sizeof(DWM_TIMING_INFO)
    if _dwmapi.DwmGetCompositionTimingInfo(None, ctypes.byref(ti)) != 0 or not ti.qpcRefreshPeriod:
        return None
    return ti.qpcVBlank / _QPF, ti.qpcRefreshPeriod / _QPF


def frame_tick(present: float) -> float:
    """刚取到的一帧算作哪一刻显示出来（合成器的节拍，见 compose_clock）；和 present 对不上时按 present 估。"""
    clock = compose_clock()
    if clock is None:
        return present + 0.006 if present else 0.0
    vb, period = clock
    if not present:
        return vb
    if -0.5 * period <= vb - present <= 2.5 * period:
        return vb
    return present + 1.5 * period


@dataclass
class Frame:
    """一帧画面。image 是本显示器的 BGRA（物理像素），由采集器复用，处理时不要长期持有引用。"""
    image: np.ndarray
    origin: tuple[int, int]            # 显示器左上角在虚拟桌面的坐标
    time: float
    dirty: list[Rect] = field(default_factory=list)   # 显示器内坐标；full=True 时可能为空
    moves: list[tuple[Rect, tuple[int, int]]] = field(default_factory=list)  # (目标矩形, 源左上角)
    full: bool = False                 # 整帧都要当作可能变化（首帧、丢失重建后）
    protected: bool = False            # 有受保护内容被系统遮黑
    acc: int = 1                       # 上次取帧以来系统合成了几帧（>1 = 中间的帧没赶上，直接给最新的）
    present: float = 0.0               # 桌面复制报的画面更新时刻（perf_counter 的时间轴；0 = 不知道）
    tick: float = 0.0                  # 这一帧画面显示出来的时刻（合成器节拍，见 frame_tick；0 = 不知道）


FULL_EVERY = 0.1        # 秒：整屏都报“变了”的帧里，关心范围以外的部分最多隔这么久看一次
BIG_FRAC = 0.6          # 脏矩形加起来超过屏幕的这么多：当作“整屏都报变了”


class DuplicationCapture:
    """单个显示器的 Desktop Duplication。只能在创建它的线程里使用。

    有时桌面复制每一帧都把整块屏幕报成“变了”（实测见过：魔镜的译文层交给系统合成器后在滚动时，哪怕那个窗口
    只有一小块、对截屏隐身；同样的测试换个时候又只报那一小块，可能和屏幕上别的程序有关）。这种帧只拷调用方
    关心的范围（roi：魔镜附近、正在滚动的区域），整帧先留在显卡上；其余部分最多隔 FULL_EVERY 补一次
    （之后的帧顺带补，或者没有新帧时 flush 补），不会漏掉真正的变化，只是晚一点。"""

    def __init__(self, device_name: str) -> None:
        self.device_name = device_name
        self.origin = (0, 0)
        self.size = (0, 0)
        self._factory = self._adapter = self._output = self._output1 = None
        self._device = self._context = self._dupl = self._staging = None
        self._buffer: np.ndarray | None = None
        self.lock = threading.Lock()          # 别的线程（录制）复制画面时拿着它，免得读到改了一半的帧
        self._need_full = True
        self._gdi = None
        self._meta = (ctypes.c_ubyte * 65536)()
        self._latest = None                   # 显卡上留着的最新一帧（只拷了一部分的帧用，之后补拷其余部分）
        self._latest_info = (0.0, 0.0, False)  # 它的 (present, tick, protected)
        self._stale_since = 0.0               # 缓冲区里有部分还没跟上最新一帧（从什么时候起）
        self._last_full = 0.0                 # 上次把报了变化的部分全拷过来的时刻
        self._open()

    # ------------------------------------------------------------------ setup
    def _open(self) -> None:
        fptr = ctypes.c_void_p()
        hr = _dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(fptr)) & 0xFFFFFFFF
        if hr & 0x80000000:
            raise ComError("CreateDXGIFactory1", hr)
        self._factory = Com(fptr)
        adapter_index = 0
        while True:
            aptr = ctypes.c_void_p()
            hr = self._factory.fn(12, HRESULT, wt.UINT, ctypes.POINTER(ctypes.c_void_p))(
                self._factory.ptr, adapter_index, ctypes.byref(aptr)) & 0xFFFFFFFF
            if hr == DXGI_ERROR_NOT_FOUND:
                break
            if hr & 0x80000000:
                raise ComError("EnumAdapters1", hr)
            adapter = Com(aptr)
            output_index = 0
            while True:
                optr = ctypes.c_void_p()
                hr = adapter.fn(7, HRESULT, wt.UINT, ctypes.POINTER(ctypes.c_void_p))(
                    adapter.ptr, output_index, ctypes.byref(optr)) & 0xFFFFFFFF
                if hr == DXGI_ERROR_NOT_FOUND:
                    break
                output = Com(optr)
                desc = DXGI_OUTPUT_DESC()
                output.hr("GetDesc", 7, (ctypes.POINTER(DXGI_OUTPUT_DESC),), ctypes.byref(desc))
                if desc.DeviceName == self.device_name:
                    rc = desc.DesktopCoordinates
                    self.origin = (rc.left, rc.top)
                    self.size = (rc.right - rc.left, rc.bottom - rc.top)
                    self._adapter, self._output = adapter, output
                    self._create_device()
                    return
                output.release()
                output_index += 1
            adapter.release()
            adapter_index += 1
        raise RuntimeError(tr("找不到显示器 {name} 对应的 DXGI 输出").format(name=self.device_name))

    def _create_device(self) -> None:
        dptr, cptr, level = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_uint()
        hr = _d3d11.D3D11CreateDevice(self._adapter.ptr, 0, None, 0, None, 0, D3D11_SDK_VERSION, ctypes.byref(dptr),
                                      ctypes.byref(level), ctypes.byref(cptr)) & 0xFFFFFFFF
        if hr & 0x80000000:
            raise ComError("D3D11CreateDevice", hr)
        self._device, self._context = Com(dptr), Com(cptr)
        self._output1 = self._output.query(IID_IDXGIOutput1)
        self._duplicate()

    def _duplicate(self) -> None:
        dptr = ctypes.c_void_p()
        self._output1.hr("DuplicateOutput", 22, (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)), self._device.ptr,
                         ctypes.byref(dptr))
        self._dupl = Com(dptr)
        desc = DXGI_OUTDUPL_DESC()
        self._dupl.fn(7, None, ctypes.POINTER(DXGI_OUTDUPL_DESC))(self._dupl.ptr, ctypes.byref(desc))
        if desc.Rotation not in (0, 1):
            raise RuntimeError(tr("暂不支持旋转的显示器"))
        w, h = desc.ModeDesc.Width, desc.ModeDesc.Height
        self.size = (w, h)
        if self._staging is None or self._buffer is None or self._buffer.shape[:2] != (h, w):
            if self._staging is not None:
                self._staging.release()
            tdesc = D3D11_TEXTURE2D_DESC(w, h, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_SAMPLE_DESC(1, 0),
                                         D3D11_USAGE_STAGING, 0, D3D11_CPU_ACCESS_READ, 0)
            sptr = ctypes.c_void_p()
            self._device.hr("CreateTexture2D", 5, (ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p,
                                                   ctypes.POINTER(ctypes.c_void_p)),
                            ctypes.byref(tdesc), None, ctypes.byref(sptr))
            self._staging = Com(sptr)
            self._buffer = np.zeros((h, w, 4), np.uint8)
            if self._latest is not None:
                self._latest.release()
                self._latest = None
            ldesc = D3D11_TEXTURE2D_DESC(w, h, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_SAMPLE_DESC(1, 0), 0, 0, 0, 0)
            lptr = ctypes.c_void_p()
            try:
                self._device.hr("CreateTexture2D", 5, (ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p,
                                                       ctypes.POINTER(ctypes.c_void_p)),
                                ctypes.byref(ldesc), None, ctypes.byref(lptr))
                self._latest = Com(lptr)
            except ComError as e:
                log.debug("显卡上留帧的纹理建不起来（%s）：整屏报变化时照样全拷", e)
        self._need_full = True
        self._stale_since = 0.0

    def _reset(self) -> None:
        if self._dupl is not None:
            self._dupl.release()
            self._dupl = None
        for attempt in range(40):
            try:
                self._duplicate()
                return
            except ComError as e:
                # 桌面切换（UAC、锁屏）期间 DuplicateOutput 会暂时失败，稍后重试。
                if attempt == 39:
                    raise
                log.debug("重建桌面复制失败 %s，稍后重试", e)
                time.sleep(0.25)

    # ------------------------------------------------------------------ frames
    def _acquire(self, timeout_ms: int):
        info = DXGI_OUTDUPL_FRAME_INFO()
        res = ctypes.c_void_p()
        hr = self._dupl.fn(8, HRESULT, wt.UINT, ctypes.POINTER(DXGI_OUTDUPL_FRAME_INFO), ctypes.POINTER(ctypes.c_void_p))(
            self._dupl.ptr, timeout_ms, ctypes.byref(info), ctypes.byref(res)) & 0xFFFFFFFF
        return hr, info, res

    def _base_frame(self) -> Frame:
        """复制刚建立时第一帧常是空图，而且静止桌面不会再送新帧。

        做法：先取走复制里积压的那一帧（之后的脏矩形都相对它），再用 GDI 截一张完整底图。
        两者之间发生的变化会同时出现在底图和下一帧的脏矩形里，重复应用也一致。
        """
        hr, _info, res = self._acquire(0)
        if hr == S_OK:
            Com(res).release()
            self._dupl.fn(14, HRESULT)(self._dupl.ptr)
        if self._gdi is None:
            import mss
            self._gdi = mss.MSS()
        w, h = self.size
        shot = self._gdi.grab({"left": self.origin[0], "top": self.origin[1], "width": w, "height": h})
        with self.lock:
            self._buffer[:] = np.frombuffer(shot.bgra, np.uint8).reshape(h, w, 4)
        self._need_full = False
        self._stale_since = 0.0
        return Frame(self._buffer, self.origin, time.perf_counter(), [], [], True, False)

    def _copy_to_buffer(self, src_ptr, regions: list[Rect]) -> None:
        """把 regions 从显卡上的 src 拷到内存缓冲区（经过可读纹理）。"""
        w, h = self.size
        copy = self._context.fn(46, None, ctypes.c_void_p, wt.UINT, wt.UINT, wt.UINT, wt.UINT, ctypes.c_void_p,
                                wt.UINT, ctypes.POINTER(D3D11_BOX))
        for l, t, r, b in regions:
            box = D3D11_BOX(l, t, 0, r, b, 1)
            copy(self._context.ptr, self._staging.ptr, 0, l, t, 0, src_ptr, 0, ctypes.byref(box))
        mapped = D3D11_MAPPED_SUBRESOURCE()
        self._context.hr("Map", 14, (ctypes.c_void_p, wt.UINT, ctypes.c_uint, wt.UINT,
                                     ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE)),
                         self._staging.ptr, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped))
        try:
            src = np.ctypeslib.as_array(ctypes.cast(mapped.pData, ctypes.POINTER(ctypes.c_ubyte)),
                                        shape=(h, mapped.RowPitch))
            buf = self._buffer
            with self.lock:
                for l, t, r, b in regions:
                    buf[t:b, l:r] = src[t:b, l * 4:r * 4].reshape(b - t, r - l, 4)
        finally:
            self._context.fn(15, None, ctypes.c_void_p, wt.UINT)(self._context.ptr, self._staging.ptr, 0)

    def stale(self) -> bool:
        """缓冲区里有部分落后于最新一帧，而且该补了（没有新帧时由调用方调 flush）。"""
        return bool(self._stale_since) and time.perf_counter() - self._last_full >= FULL_EVERY

    def flush(self) -> Frame | None:
        """之前只拷了一部分的帧，其余部分从显卡上留着的最新一帧补上（当作一帧交给调用方）。"""
        if not self._stale_since or self._latest is None:
            return None
        w, h = self.size
        self._copy_to_buffer(self._latest.ptr, [(0, 0, w, h)])
        self._stale_since = 0.0
        self._last_full = time.perf_counter()
        present, tick, protected = self._latest_info
        return Frame(self._buffer, self.origin, time.perf_counter(), [(0, 0, w, h)], [], False, protected, 1,
                     present, tick)

    def grab(self, timeout_ms: int = 50, roi: list[Rect] | None = None) -> Frame | None:
        """等待下一帧；超时返回 None。返回的 image 是内部缓冲区。
        roi：整屏都报“变了”时先只拷这些范围（显示器内坐标），见类的说明。"""
        if self._dupl is None:
            self._reset()
        if self._need_full:
            return self._base_frame()
        hr, info, res = self._acquire(timeout_ms)
        if hr == DXGI_ERROR_WAIT_TIMEOUT:
            return None
        if hr in (DXGI_ERROR_ACCESS_LOST, DXGI_ERROR_INVALID_CALL, E_ACCESSDENIED):
            log.info("桌面复制失效（0x%08X），重建", hr)
            self._reset()
            return None
        if hr & 0x80000000:
            raise ComError("AcquireNextFrame", hr)
        resource = Com(res)
        try:
            if info.LastPresentTime == 0:
                return None  # 只有鼠标动了
            present = info.LastPresentTime / _QPF
            tick = frame_tick(present)        # 拷贝之前马上问：拷完再问可能已经过了下一个节拍
            dirty: list[Rect] = []
            moves: list[tuple[Rect, tuple[int, int]]] = []
            if not info.TotalMetadataBufferSize or not self._read_metadata(info.TotalMetadataBufferSize, dirty, moves):
                self._need_full = True
                return None
            w, h = self.size
            regions = _union_rows(dirty + [m[0] for m in moves], w, h)
            if not regions:
                return None
            protected = bool(info.ProtectedContentMaskedOut)
            tex = resource.query(IID_ID3D11Texture2D)
            try:
                now = time.perf_counter()
                big = sum((r - l) * (b - t) for l, t, r, b in regions) >= BIG_FRAC * w * h
                if big and roi is not None and self._latest is not None and now - self._last_full < FULL_EVERY:
                    # 整屏都报“变了”：先只拷关心的范围，整帧留在显卡上，其余部分稍后补
                    self._context.fn(47, None, ctypes.c_void_p, ctypes.c_void_p)(self._context.ptr,
                                                                                 self._latest.ptr, tex.ptr)
                    self._latest_info = (present, tick, protected)
                    if not self._stale_since:
                        self._stale_since = now
                    regions = _union_rows([geom_inter(r, q) for r in regions for q in roi], w, h)
                else:
                    if self._stale_since:
                        regions = [(0, 0, w, h)]          # 之前跳过的部分一起补上
                        self._stale_since = 0.0
                    if big or regions == [(0, 0, w, h)]:
                        self._last_full = now
                if regions:
                    # 只把变化的区域从显存拷到可读纹理，减少总线传输。
                    self._copy_to_buffer(tex.ptr, regions)
            finally:
                tex.release()
            if not regions:
                return None
            return Frame(self._buffer, self.origin, time.perf_counter(), regions, moves, False,
                         protected, max(1, info.AccumulatedFrames), present, tick)
        finally:
            resource.release()
            self._dupl.fn(14, HRESULT)(self._dupl.ptr)

    def _read_metadata(self, total: int, dirty: list[Rect], moves: list) -> bool:
        if total > len(self._meta):
            self._meta = (ctypes.c_ubyte * (total * 2))()
        need = wt.UINT()
        msize = ctypes.sizeof(DXGI_OUTDUPL_MOVE_RECT)
        hr = self._dupl.fn(10, HRESULT, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT))(
            self._dupl.ptr, len(self._meta), self._meta, ctypes.byref(need)) & 0xFFFFFFFF
        if hr & 0x80000000:
            return False
        n_moves = need.value // msize
        arr = ctypes.cast(self._meta, ctypes.POINTER(DXGI_OUTDUPL_MOVE_RECT))
        for i in range(n_moves):
            m = arr[i]
            d = m.DestinationRect
            moves.append(((d.left, d.top, d.right, d.bottom), (m.SourcePoint.x, m.SourcePoint.y)))
        hr = self._dupl.fn(9, HRESULT, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT))(
            self._dupl.ptr, len(self._meta), self._meta, ctypes.byref(need)) & 0xFFFFFFFF
        if hr & 0x80000000:
            return False
        rects = ctypes.cast(self._meta, ctypes.POINTER(wt.RECT))
        for i in range(need.value // ctypes.sizeof(wt.RECT)):
            r = rects[i]
            dirty.append((r.left, r.top, r.right, r.bottom))
        return True

    def close(self) -> None:
        for com in (self._latest, self._staging, self._dupl, self._output1, self._context, self._device, self._output,
                    self._adapter, self._factory):
            if com is not None:
                com.release()
        self._latest = None
        self._staging = self._dupl = self._output1 = self._context = self._device = None
        self._output = self._adapter = self._factory = None
        if self._gdi is not None:
            self._gdi.close()
            self._gdi = None


def geom_inter(a: Rect, b: Rect) -> Rect:
    return max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])


def _union_rows(rects: list[Rect], w: int, h: int) -> list[Rect]:
    """把脏矩形裁到屏幕内；数量多时合并成覆盖它们的横条，减少 Python 循环。"""
    clipped = [(max(0, l), max(0, t), min(w, r), min(h, b)) for l, t, r, b in rects]
    clipped = [c for c in clipped if c[2] > c[0] and c[3] > c[1]]
    if len(clipped) <= 16:
        return clipped
    clipped.sort(key=lambda c: c[1])
    out: list[list[int]] = []
    for l, t, r, b in clipped:
        if out and t <= out[-1][3]:
            o = out[-1]
            o[0], o[2], o[3] = min(o[0], l), max(o[2], r), max(o[3], b)
        else:
            out.append([l, t, r, b])
    return [tuple(o) for o in out]


class GdiCapture:
    """兜底：mss（GDI BitBlt）。没有脏矩形，每帧整屏比较。"""

    def __init__(self, rect: Rect) -> None:
        import mss
        self._mss = mss.MSS()
        self.origin = (rect[0], rect[1])
        self.size = (rect[2] - rect[0], rect[3] - rect[1])
        self._mon = {"left": rect[0], "top": rect[1], "width": self.size[0], "height": self.size[1]}
        self._last = 0.0
        self._first = True
        self.lock = threading.Lock()          # 和 DuplicationCapture 一样的接口（这里每帧都是新数组，不会读到一半）

    def stale(self) -> bool:
        return False

    def flush(self) -> Frame | None:
        return None

    def grab(self, timeout_ms: int = 50, roi: list[Rect] | None = None) -> Frame | None:
        # GDI 没有“有新帧”通知，按最短间隔节流。
        wait = self._last + 0.033 - time.perf_counter()
        if wait > 0:
            time.sleep(min(wait, timeout_ms / 1000))
        shot = self._mss.grab(self._mon)
        self._last = time.perf_counter()
        img = np.frombuffer(shot.bgra, np.uint8).reshape(self.size[1], self.size[0], 4)
        return Frame(img, self.origin, self._last, [], [], True, False)

    def close(self) -> None:
        self._mss.close()


def open_capture(device_name: str, rect: Rect, prefer_dxgi: bool = True):
    if prefer_dxgi:
        try:
            return DuplicationCapture(device_name)
        except Exception as e:  # noqa: BLE001 - 任何初始化失败都回退 GDI
            log.warning("DXGI 桌面复制不可用（%s），改用 GDI 截屏", e)
    return GdiCapture(rect)
