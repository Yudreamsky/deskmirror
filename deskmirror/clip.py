"""剪贴板（输入框翻译用）：写回输入框时借用一下（模拟 Ctrl+V 粘贴），粘完把用户原来的内容放回去。

放进去的字带上“不进剪贴板历史、不同步到云、剪贴板工具别记”的标记，Win+V 里看不到；放回原来的内容时也带上，
免得历史里多出一条重复的。读不到框里的字时用 Ctrl+C 复制出来读（那一下是那个软件自己复制的，会进剪贴板历史）。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.OpenClipboard.argtypes = [wt.HWND]
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.EnumClipboardFormats.argtypes = [wt.UINT]
user32.EnumClipboardFormats.restype = wt.UINT
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wt.UINT
user32.GetClipboardSequenceNumber.restype = wt.DWORD
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.GlobalSize.argtypes = [wt.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [wt.HGLOBAL]

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
# 不是一块内存的格式（位图、图元文件、调色板句柄等）存不下来：存 CF_DIB 就够了，位图会由系统再生成
_HANDLE_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E} | set(range(0x300, 0x400))
MAX_SAVE = 256 * 1024 * 1024


class ClipboardBusy(OSError):
    pass


def _open() -> None:
    for _ in range(40):                      # 别的程序正开着剪贴板：等一下再试
        if user32.OpenClipboard(None):
            return
        time.sleep(0.01)
    raise ClipboardBusy("clipboard is busy")


def _alloc(data: bytes) -> int:
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not h:
        raise MemoryError
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    return h


def _set(fmt: int, data: bytes) -> None:
    h = _alloc(data)
    if not user32.SetClipboardData(fmt, h):
        kernel32.GlobalFree(h)


def _private() -> None:
    """标记：别进剪贴板历史、别同步到云、剪贴板工具别记。"""
    zero = (0).to_bytes(4, "little")
    _set(user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing"), b"\0")
    _set(user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory"), zero)
    _set(user32.RegisterClipboardFormatW("CanUploadToCloudClipboard"), zero)


def seq() -> int:
    """剪贴板换过多少次内容：放回原来的内容之前看一眼，别把用户这期间新复制的盖掉。"""
    return int(user32.GetClipboardSequenceNumber())


def save() -> list[tuple[int, bytes]]:
    """现在剪贴板里的所有内容（每种格式一份）。"""
    _open()
    out, total = [], 0
    try:
        fmt = user32.EnumClipboardFormats(0)
        while fmt:
            if fmt not in _HANDLE_FORMATS:
                h = user32.GetClipboardData(fmt)
                size = kernel32.GlobalSize(h) if h else 0
                p = kernel32.GlobalLock(h) if size else None
                if p:
                    try:
                        total += size
                        if total > MAX_SAVE:
                            raise MemoryError("clipboard too large")
                        out.append((fmt, ctypes.string_at(p, size)))
                    finally:
                        kernel32.GlobalUnlock(h)
            fmt = user32.EnumClipboardFormats(fmt)
    finally:
        user32.CloseClipboard()
    return out


def restore(saved: list[tuple[int, bytes]]) -> None:
    _open()
    try:
        user32.EmptyClipboard()
        for fmt, data in saved:
            _set(fmt, data)
        if saved:
            _private()
    finally:
        user32.CloseClipboard()


def put_text(text: str) -> int:
    """放一段字（带“别记”的标记），返回放好以后的序号。"""
    _open()
    try:
        user32.EmptyClipboard()
        _set(CF_UNICODETEXT, (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le"))
        _private()
    finally:
        user32.CloseClipboard()
    return seq()


def get_text() -> str | None:
    _open()
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        p = kernel32.GlobalLock(h) if h else None
        if not p:
            return None
        try:
            return ctypes.wstring_at(p).replace("\r\n", "\n")
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()
