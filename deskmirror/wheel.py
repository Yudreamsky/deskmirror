"""滚轮监听：用 Raw Input 被动接收鼠标滚轮（不装全局钩子，不会拖慢系统鼠标）。

滚轮只是“提前量”：告诉引擎哪块画布可能马上要滚、往哪个方向、大约多远。
位置的最终依据始终是像素识别（见 engine 的滚轮曲线学习与预测）。
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes as wt
from typing import Callable

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_INPUT = 0x00FF
WM_QUIT = 0x0012
WM_CLOSE = 0x0010
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800
HWND_MESSAGE = wt.HWND(-3)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT), ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD), ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]


# RAWMOUSE 里 usFlags 后面是 4 字节对齐的联合体（ulButtons / usButtonFlags+usButtonData）：
# 手工补 2 字节，避免 ctypes 按 2 字节紧排读错位置。
class _RAWMOUSE_ALIGNED(ctypes.Structure):
    _fields_ = [("usFlags", wt.USHORT), ("_pad", wt.USHORT), ("usButtonFlags", wt.USHORT),
                ("usButtonData", wt.USHORT), ("ulRawButtons", wt.ULONG), ("lLastX", wt.LONG), ("lLastY", wt.LONG),
                ("ulExtraInformation", wt.ULONG)]


class _RAWINPUT_ALIGNED(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", _RAWMOUSE_ALIGNED)]


user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.ATOM
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wt.UINT, wt.UINT]
user32.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, wt.LPVOID, ctypes.POINTER(wt.UINT), wt.UINT]
user32.GetRawInputData.restype = wt.UINT
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE


class WheelListener(threading.Thread):
    """回调参数：(时间, x, y, 格数(正=向上滚), 是否水平, 按着Ctrl, 按着Shift)。"""

    def __init__(self, callback: Callable[[float, int, int, float, bool, bool, bool], None]) -> None:
        super().__init__(name="wheel-listener", daemon=True)
        self._cb = callback
        self._hwnd = None
        self._ready = threading.Event()
        self.ok = False
        self._buf = ctypes.create_string_buffer(128)

    def run(self) -> None:
        self._proc = WNDPROC(self._wndproc)  # 保持引用，防止回调被回收
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "DeskMirrorWheelSink"
        user32.RegisterClassW(ctypes.byref(wc))
        self._hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, hinst, None)
        dev = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, self._hwnd)
        self.ok = bool(self._hwnd) and bool(user32.RegisterRawInputDevices(ctypes.byref(dev), 1,
                                                                             ctypes.sizeof(RAWINPUTDEVICE)))
        if not self.ok:
            log.warning("滚轮监听不可用（错误码 %s），只用像素识别", ctypes.get_last_error())
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, umsg, wparam, lparam):
        if umsg == WM_INPUT:
            try:
                size = wt.UINT(ctypes.sizeof(self._buf))
                n = user32.GetRawInputData(lparam, RID_INPUT, self._buf, ctypes.byref(size),
                                           ctypes.sizeof(RAWINPUTHEADER))
                if n != 0xFFFFFFFF and n >= ctypes.sizeof(RAWINPUTHEADER):
                    ri = _RAWINPUT_ALIGNED.from_buffer_copy(self._buf.raw[:ctypes.sizeof(_RAWINPUT_ALIGNED)])
                    flags = ri.mouse.usButtonFlags
                    if ri.header.dwType == RIM_TYPEMOUSE and flags & (RI_MOUSE_WHEEL | RI_MOUSE_HWHEEL):
                        delta = ctypes.c_short(ri.mouse.usButtonData).value
                        pt = wt.POINT()
                        user32.GetCursorPos(ctypes.byref(pt))
                        ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
                        shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
                        self._cb(time.perf_counter(), pt.x, pt.y, delta / 120.0, bool(flags & RI_MOUSE_HWHEEL),
                                 ctrl, shift)
            except Exception:  # noqa: BLE001 - 消息回调里不能抛异常
                log.debug("解析滚轮输入失败", exc_info=True)
            return user32.DefWindowProcW(hwnd, umsg, wparam, lparam)
        if umsg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, umsg, wparam, lparam)

    def start_and_wait(self, timeout: float = 2.0) -> bool:
        self.start()
        self._ready.wait(timeout)
        return self.ok

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        self.join(2.0)
