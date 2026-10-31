"""Raw Input：在后台线程里挂一个只收消息的隐藏窗口，被动地收某一类设备（鼠标、键盘）的原始输入。

只听、不拦：不是全局钩子，也不是注入，不会拖慢系统鼠标、别的软件打字。
滚轮监听（wheel.py）和输入框翻译听空格（fieldkeys.py）都用它。
"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes as wt

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_INPUT, WM_CLOSE = 0x00FF, 0x0010
RIDEV_INPUTSINK, RIDEV_REMOVE = 0x00000100, 0x00000001
RID_INPUT = 0x10000003
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
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE


class RawInputSink(threading.Thread):
    """收一类设备的原始输入。子类给出 CLASS_NAME（隐藏窗口的类名）、USAGE（(用途页, 用途)：(1, 2) 鼠标、
    (1, 6) 键盘），实现 on_input 和 on_failed。"""
    CLASS_NAME = ""
    USAGE = (0, 0)

    def __init__(self, name: str) -> None:
        super().__init__(name=name, daemon=True)
        self.ok = False
        self._hwnd = None
        self._ready = threading.Event()
        self._buf = ctypes.create_string_buffer(128)

    def on_input(self, data: bytes, size: int) -> None:
        """一条原始输入：data 是 RAWINPUT 结构所在的缓冲区，size 是这一条实际的字节数。在监听线程里调。"""
        raise NotImplementedError

    def on_failed(self, err: int) -> None:
        """登记没成功（收不到这类输入）：记日志说明会怎样。"""
        raise NotImplementedError

    def run(self) -> None:
        self._proc = WNDPROC(self._wndproc)       # 保持引用，防止回调被回收
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = self.CLASS_NAME
        user32.RegisterClassW(ctypes.byref(wc))
        self._hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, hinst, None)
        dev = RAWINPUTDEVICE(*self.USAGE, RIDEV_INPUTSINK, self._hwnd)
        self.ok = bool(self._hwnd) and bool(user32.RegisterRawInputDevices(ctypes.byref(dev), 1,
                                                                             ctypes.sizeof(RAWINPUTDEVICE)))
        if not self.ok:
            self.on_failed(ctypes.get_last_error())
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        dev = RAWINPUTDEVICE(*self.USAGE, RIDEV_REMOVE, None)            # 窗口没了：登记也撤掉
        user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(RAWINPUTDEVICE))

    def _wndproc(self, hwnd, umsg, wparam, lparam):
        if umsg == WM_INPUT:
            try:
                size = wt.UINT(ctypes.sizeof(self._buf))
                n = user32.GetRawInputData(lparam, RID_INPUT, self._buf, ctypes.byref(size),
                                           ctypes.sizeof(RAWINPUTHEADER))
                if n != 0xFFFFFFFF and n >= ctypes.sizeof(RAWINPUTHEADER):
                    self.on_input(self._buf.raw, n)
            except Exception:  # noqa: BLE001 - 消息回调里不能抛异常
                log.debug("解析原始输入失败（%s）", self.name, exc_info=True)
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
