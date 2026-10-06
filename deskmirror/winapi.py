"""Win32 辅助：DPI、显示器、顶层窗口、截屏隐身、按键状态和 DPAPI。

本程序所有几何量都用虚拟桌面的物理像素（进程为 Per-Monitor-V2 DPI 感知）。
"""
from __future__ import annotations

import base64
import ctypes
import logging
import os
from ctypes import wintypes as wt
from dataclasses import dataclass

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)

LONG_PTR = ctypes.c_ssize_t

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11
HWND_TOPMOST = wt.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
GW_HWNDNEXT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
LWA_ALPHA = 0x2

user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR
user32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
user32.SetWindowDisplayAffinity.restype = wt.BOOL
user32.GetWindowDisplayAffinity.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowDisplayAffinity.restype = wt.BOOL
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetWindowPos.restype = wt.BOOL
user32.GetTopWindow.argtypes = [wt.HWND]
user32.GetTopWindow.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetLayeredWindowAttributes.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD), ctypes.POINTER(ctypes.c_ubyte),
                                              ctypes.POINTER(wt.DWORD)]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), MONITORENUMPROC, wt.LPARAM]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD),
                ("szDevice", wt.WCHAR * 32)]


user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]

Rect = tuple[int, int, int, int]  # (left, top, right, bottom)，右下不含


def set_dpi_awareness() -> bool:
    """必须在创建任何窗口（包括 Qt）之前调用。"""
    try:
        return bool(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))  # PER_MONITOR_AWARE_V2
    except AttributeError:
        return False


@dataclass(frozen=True)
class Monitor:
    device: str
    rect: Rect
    work: Rect
    dpi: int
    primary: bool

    @property
    def scale(self) -> float:
        return self.dpi / 96.0


def monitors() -> list[Monitor]:
    found: list[Monitor] = []

    def callback(hmon, _hdc, _rc, _lp):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            dx, dy = wt.UINT(), wt.UINT()
            if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) != 0:
                dx.value = 96
            r, w = info.rcMonitor, info.rcWork
            found.append(Monitor(info.szDevice, (r.left, r.top, r.right, r.bottom), (w.left, w.top, w.right, w.bottom),
                                 int(dx.value), bool(info.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    found.sort(key=lambda m: (not m.primary, m.rect[0], m.rect[1]))
    return found


def exclude_from_capture(hwnd: int) -> bool:
    """窗口只在显示器上可见，截屏和录屏里没有（Windows 10 2004 起）；防止把自己的译文当原文识别。"""
    if user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
        return True
    log.warning("SetWindowDisplayAffinity 失败，错误码 %s", ctypes.get_last_error())
    return False


def include_in_capture(hwnd: int) -> bool:
    """撤销 exclude_from_capture（只在录演示视频时用：让自己的窗口连标题栏、阴影一起进画面）。"""
    return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_NONE))


def display_affinity(hwnd: int) -> int:
    value = wt.DWORD()
    return int(value.value) if user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(value)) else -1


def set_exstyle(hwnd: int, add: int = 0, remove: int = 0) -> None:
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    new = (style | add) & ~remove
    if new != style:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)


def exstyle(hwnd: int) -> int:
    return int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))


def keep_topmost(hwnd: int) -> None:
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def cursor_pos() -> tuple[int, int]:
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


@dataclass
class TopWindow:
    hwnd: int
    rect: Rect          # DWM 可见边框（不含 Win10/11 的隐形缩放边）
    pid: int
    cls: str
    topmost: bool
    title: str = ""


def _frame_bounds(hwnd: int) -> Rect | None:
    rc = wt.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rc), ctypes.sizeof(rc)) != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
            return None
    return rc.left, rc.top, rc.right, rc.bottom


def _cloaked(hwnd: int) -> bool:
    value = wt.DWORD()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)) != 0:
        return False
    return value.value != 0


_class_buf = ctypes.create_unicode_buffer(256)


def window_rect(hwnd: int) -> Rect | None:
    """窗口在屏幕上看得见的矩形（物理像素，不含隐形边框）；窗口没了返回 None。"""
    if not user32.IsWindow(hwnd):
        return None
    return _frame_bounds(hwnd)


def window_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd)) or not user32.IsWindowVisible(hwnd)


def window_class(hwnd: int) -> str:
    n = user32.GetClassNameW(hwnd, _class_buf, 256)
    return _class_buf.value if n > 0 else ""


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


# 桌面背景窗口铺满整个桌面、在 Z 序最底层：它上面的文字归“桌面”画布，不当成普通窗口。
_IGNORED_CLASSES = {"Progman", "WorkerW"}


def top_level_windows(skip_pid: int | None = None, with_titles: bool = False) -> list[TopWindow]:
    """按 Z 序从上到下列出可见、未隐藏的顶层窗口。

    跳过：本进程窗口、最小化、DWM 隐藏（其他虚拟桌面/后台 UWP）、鼠标穿透的覆盖层、
    整体透明的分层窗口、桌面背景窗口。
    """
    out: list[TopWindow] = []
    pid = wt.DWORD()
    hwnd = user32.GetTopWindow(None)
    guard = 0
    while hwnd and guard < 4096:
        guard += 1
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                continue
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if skip_pid is not None and pid.value == skip_pid:
                continue
            ex = exstyle(hwnd)
            if ex & WS_EX_TRANSPARENT:
                continue
            if ex & WS_EX_LAYERED:
                alpha = ctypes.c_ubyte(255)
                flags = wt.DWORD(0)
                if user32.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), ctypes.byref(flags)):
                    if flags.value & LWA_ALPHA and alpha.value == 0:
                        continue
            if _cloaked(hwnd):
                continue
            rect = _frame_bounds(hwnd)
            if rect is None or rect[2] - rect[0] <= 1 or rect[3] - rect[1] <= 1:
                continue
            cls = window_class(hwnd)
            if cls in _IGNORED_CLASSES:
                continue
            out.append(TopWindow(int(hwnd), rect, int(pid.value), cls, bool(ex & WS_EX_TOPMOST),
                                 window_title(hwnd) if with_titles else ""))
        finally:
            hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
    return out


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]


def process_name(pid: int) -> str:
    """进程的程序文件名（如 WeChat.exe）；没有权限或进程已退出时返回空串。"""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return ""
        return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)


# ---------------------------------------------------------------- DPAPI

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wt.LPCWSTR, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p,
                                     ctypes.c_void_p, wt.DWORD, ctypes.POINTER(DATA_BLOB)]
crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
                                       ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(DATA_BLOB)]
kernel32.LocalFree.argtypes = [ctypes.c_void_p]


def _blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob._buf = buf  # 防止被回收
    return blob


def protect(text: str) -> str:
    """用当前 Windows 账户的 DPAPI 加密，只有同一账户能解开。"""
    src, out = _blob(text.encode("utf-8")), DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(src), "deskmirror", None, None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode("ascii")
    finally:
        kernel32.LocalFree(out.pbData)


def unprotect(token: str) -> str:
    src, out = _blob(base64.b64decode(token.encode("ascii"))), DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(out.pbData)


def protect_bytes(data: bytes) -> bytes:
    """DPAPI 加密任意字节（当前 Windows 账户才能解开）。"""
    src, out = _blob(data), DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(src), "deskmirror", None, None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def unprotect_bytes(data: bytes) -> bytes:
    src, out = _blob(data), DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def current_pid() -> int:
    return os.getpid()
