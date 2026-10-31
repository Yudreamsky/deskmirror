"""滚轮监听：用 Raw Input 被动接收鼠标滚轮（不装全局钩子，不会拖慢系统鼠标；见 rawinput.py）。

滚轮只是“提前量”：告诉引擎哪块画布可能马上要滚、往哪个方向、大约多远。
位置的最终依据始终是像素识别（见 engine 的滚轮曲线学习与预测）。
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes as wt
from typing import Callable

from .rawinput import RAWINPUTHEADER, RawInputSink

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)

RIM_TYPEMOUSE = 0
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800


# RAWMOUSE 里 usFlags 后面是 4 字节对齐的联合体（ulButtons / usButtonFlags+usButtonData）：
# 手工补 2 字节，避免 ctypes 按 2 字节紧排读错位置。
class _RAWMOUSE_ALIGNED(ctypes.Structure):
    _fields_ = [("usFlags", wt.USHORT), ("_pad", wt.USHORT), ("usButtonFlags", wt.USHORT),
                ("usButtonData", wt.USHORT), ("ulRawButtons", wt.ULONG), ("lLastX", wt.LONG), ("lLastY", wt.LONG),
                ("ulExtraInformation", wt.ULONG)]


class _RAWINPUT_ALIGNED(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", _RAWMOUSE_ALIGNED)]


user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]


class WheelListener(RawInputSink):
    """回调参数：(时间, x, y, 格数(正=向上滚), 是否水平, 按着Ctrl, 按着Shift)。"""
    CLASS_NAME = "DeskMirrorWheelSink"
    USAGE = (0x01, 0x02)                     # 通用桌面 / 鼠标

    def __init__(self, callback: Callable[[float, int, int, float, bool, bool, bool], None]) -> None:
        super().__init__("wheel-listener")
        self._cb = callback

    def on_failed(self, err: int) -> None:
        log.warning("滚轮监听不可用（错误码 %s），只用像素识别", err)

    def on_input(self, data: bytes, size: int) -> None:
        ri = _RAWINPUT_ALIGNED.from_buffer_copy(data[:ctypes.sizeof(_RAWINPUT_ALIGNED)])
        flags = ri.mouse.usButtonFlags
        if ri.header.dwType == RIM_TYPEMOUSE and flags & (RI_MOUSE_WHEEL | RI_MOUSE_HWHEEL):
            delta = ctypes.c_short(ri.mouse.usButtonData).value
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
            self._cb(time.perf_counter(), pt.x, pt.y, delta / 120.0, bool(flags & RI_MOUSE_HWHEEL), ctrl, shift)
