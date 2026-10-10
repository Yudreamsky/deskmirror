"""输入框翻译用到的键盘：被动地听空格（Raw Input），模拟按 Ctrl+A、Ctrl+V，等用户松开修饰键，找光标在屏幕上的位置。

听键盘用 Raw Input（和 wheel.py 听滚轮一样挂在一个只收消息的隐藏窗口上）：只听、不拦，不会拖慢别的软件打字，
也不是钩子、不是注入。只看空格和 Ctrl、Alt、Shift、Win；别的键只用来“重新数”，不看是什么键、不记。
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes as wt
from typing import Callable

from .wheel import HWND_MESSAGE, LRESULT, RAWINPUTDEVICE, RAWINPUTHEADER, WNDCLASSW, WNDPROC

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_INPUT, WM_CLOSE = 0x00FF, 0x0010
RIDEV_INPUTSINK, RIDEV_REMOVE = 0x00000100, 0x00000001
RID_INPUT, RIM_TYPEKEYBOARD, RI_KEY_BREAK = 0x10000003, 1, 1
VK_SPACE, VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x20, 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_RIGHT, VK_A, VK_C, VK_V = 0x27, 0x41, 0x43, 0x56
MODIFIERS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", wt.USHORT), ("Flags", wt.USHORT), ("Reserved", wt.USHORT), ("VKey", wt.USHORT),
                ("Message", wt.UINT), ("ExtraInformation", wt.ULONG)]


class RAWINPUT_KB(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
                ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND), ("hwndMoveSize", wt.HWND),
                ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]


user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
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
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT
user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
user32.MapVirtualKeyW.restype = wt.UINT
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE


def modifiers_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in MODIFIERS)


def foreground() -> tuple[int, int]:
    """前台窗口和它的进程号。"""
    hwnd = user32.GetForegroundWindow() or 0
    pid = wt.DWORD()
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(hwnd), int(pid.value)


def caret_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """这个窗口的线程里系统光标（文字插入点）在屏幕上的位置；没有就是 None（不少自己画界面的软件没有）。"""
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not tid or not user32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndCaret:
        return None
    r = info.rcCaret
    p0, p1 = wt.POINT(r.left, r.top), wt.POINT(r.right, r.bottom)
    user32.ClientToScreen(info.hwndCaret, ctypes.byref(p0))
    user32.ClientToScreen(info.hwndCaret, ctypes.byref(p1))
    return (p0.x, p0.y, max(p1.x, p0.x + 1), max(p1.y, p0.y + 1))


def wait_released(timeout: float = 2.0) -> bool:
    """等用户松开 Ctrl、Alt、Shift、Win（按快捷键触发时还按着），免得和我们按的 Ctrl+A 混在一起。"""
    t0 = time.monotonic()
    while modifiers_down():
        if time.monotonic() - t0 > timeout:
            return False
        time.sleep(0.02)
    return True


def _key(vk: int, up: bool) -> INPUT:
    i = INPUT()
    i.type = 1                                  # INPUT_KEYBOARD
    i.u.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0), 0x0002 if up else 0, 0, 0)    # KEYEVENTF_KEYUP
    return i


def press(*keys: int) -> None:
    """依次按下 keys，再倒着松开（比如 press(VK_CONTROL, VK_A) 就是 Ctrl+A）。"""
    seq = [_key(vk, False) for vk in keys] + [_key(vk, True) for vk in reversed(keys)]
    arr = (INPUT * len(seq))(*seq)
    user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


class SpaceListener(threading.Thread):
    """在后台线程里听空格：on_space(时间, 前台窗口, 是否带修饰键) 每按下一次空格调一次（按住不放的连发也会来，
    由 inputbox.Taps 去认）；on_space_up() 松开空格；on_other() 按了别的键。"""

    def __init__(self, on_space: Callable[[float, int, bool], None], on_space_up: Callable[[], None],
                 on_other: Callable[[], None]) -> None:
        super().__init__(name="space-listener", daemon=True)
        self._on_space, self._on_up, self._on_other = on_space, on_space_up, on_other
        self.ok = False
        self._hwnd = None
        self._ready = threading.Event()
        self._buf = ctypes.create_string_buffer(128)

    def run(self) -> None:
        self._proc = WNDPROC(self._wndproc)       # 保持引用，防止回调被回收
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "DeskMirrorSpaceSink"
        user32.RegisterClassW(ctypes.byref(wc))
        self._hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, hinst, None)
        dev = RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, self._hwnd)       # 通用桌面 / 键盘
        self.ok = bool(self._hwnd) and bool(user32.RegisterRawInputDevices(ctypes.byref(dev), 1,
                                                                             ctypes.sizeof(RAWINPUTDEVICE)))
        if not self.ok:
            log.warning("听不到键盘（错误码 %s）：输入框翻译只能用快捷键", ctypes.get_last_error())
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        dev = RAWINPUTDEVICE(0x01, 0x06, RIDEV_REMOVE, None)
        user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(RAWINPUTDEVICE))

    def _wndproc(self, hwnd, umsg, wparam, lparam):
        if umsg == WM_INPUT:
            try:
                size = wt.UINT(ctypes.sizeof(self._buf))
                n = user32.GetRawInputData(lparam, RID_INPUT, self._buf, ctypes.byref(size),
                                           ctypes.sizeof(RAWINPUTHEADER))
                if n != 0xFFFFFFFF and n >= ctypes.sizeof(RAWINPUT_KB):
                    ri = RAWINPUT_KB.from_buffer_copy(self._buf.raw[:ctypes.sizeof(RAWINPUT_KB)])
                    if ri.header.dwType == RIM_TYPEKEYBOARD:
                        vk, up = ri.keyboard.VKey, bool(ri.keyboard.Flags & RI_KEY_BREAK)
                        if vk == VK_SPACE:
                            if up:
                                self._on_up()
                            else:
                                self._on_space(time.perf_counter(), foreground()[0], modifiers_down())
                        elif not up and vk != 0xFF:
                            self._on_other()
            except Exception:  # noqa: BLE001 - 消息回调里不能抛异常
                log.debug("解析键盘输入失败", exc_info=True)
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
