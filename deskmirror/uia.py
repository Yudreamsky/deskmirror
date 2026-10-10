"""UI Automation：读当前输入框里的字、看光标在不在最后、是不是密码框（输入框翻译用）。

用 ctypes 直接调 COM，不装别的库；各接口方法在虚表里的位置照 Windows SDK 的 UIAutomationClient.h。
只在输入框翻译自己的后台线程里用（那个线程开头调一次 init()）。只读，不改框里的字（写回去走粘贴，见 fieldtrans.py）。
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes as wt
from dataclasses import dataclass

log = logging.getLogger(__name__)

ole32 = ctypes.WinDLL("ole32")
oleaut32 = ctypes.WinDLL("oleaut32")
oleaut32.SysStringLen.argtypes = [ctypes.c_void_p]
oleaut32.SysStringLen.restype = ctypes.c_uint
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wt.DWORD]
ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
ole32.CLSIDFromString.argtypes = [wt.LPCWSTR, ctypes.c_void_p]

HRESULT = ctypes.c_long
P = ctypes.c_void_p


class GUID(ctypes.Structure):
    _fields_ = [("d1", wt.DWORD), ("d2", wt.WORD), ("d3", wt.WORD), ("d4", ctypes.c_ubyte * 8)]


def _guid(s: str) -> GUID:
    g = GUID()
    ole32.CLSIDFromString("{" + s + "}", ctypes.byref(g))
    return g


CLSID_CUIAutomation = _guid("ff48dba4-60ef-4201-aa87-54103eef594e")
IID_IUIAutomation = _guid("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee")
IID_ValuePattern = _guid("a94cd8b1-0844-4cd6-9d2d-640537ab39e9")
IID_TextPattern = _guid("32eba289-3583-42c9-9c59-3b6d9a1e9b6a")
IID_TextPattern2 = _guid("506a921a-fcc9-409f-b23b-37eb74106872")
ValuePatternId, TextPatternId, TextPattern2Id = 10002, 10014, 10024
EditControlTypeId, DocumentControlTypeId, ComboBoxControlTypeId = 50004, 50030, 50003
Start, End = 0, 1                       # TextPatternRangeEndpoint


def _call(obj: int, index: int, *args, argtypes=()) -> int:
    """调 COM 对象虚表里第 index 个方法（0–2 是 IUnknown），返回 HRESULT。"""
    vtbl = ctypes.cast(ctypes.c_void_p(obj), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(HRESULT, P, *argtypes)(vtbl[index])
    return fn(obj, *args)


def _release(obj: int | None) -> None:
    if obj:
        _call(obj, 2)


def _out_ptr(obj: int, index: int, *pre, argtypes=()) -> int:
    out = P()
    hr = _call(obj, index, *pre, ctypes.byref(out), argtypes=(*argtypes, ctypes.POINTER(P)))
    return (out.value or 0) if hr >= 0 else 0


def _bstr(obj: int, index: int, *pre, argtypes=()) -> str | None:
    out = P()
    if _call(obj, index, *pre, ctypes.byref(out), argtypes=(*argtypes, ctypes.POINTER(P))) < 0 or not out.value:
        return None
    try:
        return ctypes.wstring_at(out.value, oleaut32.SysStringLen(out.value))
    finally:
        oleaut32.SysFreeString(out.value)


def _int(obj: int, index: int) -> int | None:
    out = ctypes.c_int()
    return out.value if _call(obj, index, ctypes.byref(out), argtypes=(ctypes.POINTER(ctypes.c_int),)) >= 0 else None


def _pattern(el: int, pid: int, iid: GUID) -> int:
    return _out_ptr(el, 14, pid, ctypes.byref(iid), argtypes=(ctypes.c_int, ctypes.POINTER(GUID)))


@dataclass
class Field:
    """当前有键盘焦点的界面元素（输入框）。"""
    pid: int
    hwnd: int
    control: int
    password: bool
    readonly: bool
    rect: tuple[int, int, int, int]
    text: str | None            # None = 读不到
    caret_end: bool | None      # None = 不知道

    @property
    def editable(self) -> bool:
        return self.control in (EditControlTypeId, DocumentControlTypeId, ComboBoxControlTypeId)


class Uia:
    def __init__(self) -> None:
        self._ua = 0

    def init(self) -> bool:
        """在要用它的线程里调用一次。"""
        ole32.CoInitializeEx(None, 0)          # COINIT_MULTITHREADED
        out = P()
        hr = ole32.CoCreateInstance(ctypes.byref(CLSID_CUIAutomation), None, 1, ctypes.byref(IID_IUIAutomation),
                                    ctypes.byref(out))
        if hr < 0 or not out.value:
            log.warning("UI Automation 不可用（%#x），输入框翻译只能用快捷键（借剪贴板读字）", hr & 0xFFFFFFFF)
            return False
        self._ua = out.value
        return True

    def focused(self, max_chars: int) -> Field | None:
        """有键盘焦点的元素；读它的字（最多 max_chars + 1 个字，多了说明太长）和光标位置。"""
        if not self._ua:
            return None
        el = _out_ptr(self._ua, 8)                                      # IUIAutomation::GetFocusedElement
        if not el:
            return None
        try:
            rect = wt.RECT()
            _call(el, 43, ctypes.byref(rect), argtypes=(ctypes.POINTER(wt.RECT),))      # CurrentBoundingRectangle
            password = bool(_int(el, 35))                                                # CurrentIsPassword
            hwnd = P()
            _call(el, 36, ctypes.byref(hwnd), argtypes=(ctypes.POINTER(P),))             # CurrentNativeWindowHandle
            f = Field(pid=_int(el, 20) or 0, hwnd=hwnd.value or 0, control=_int(el, 21) or 0, password=password,
                      readonly=False, rect=(rect.left, rect.top, rect.right, rect.bottom), text=None, caret_end=None)
            if password:
                return f                                                 # 密码框：不读
            self._read(el, f, max_chars)
            return f
        finally:
            _release(el)

    def _read(self, el: int, f: Field, max_chars: int) -> None:
        tp = _pattern(el, TextPatternId, IID_TextPattern)
        if tp:
            try:
                doc = _out_ptr(tp, 7)                                    # DocumentRange
                if doc:
                    try:
                        f.text = _bstr(doc, 12, max_chars + 1, argtypes=(ctypes.c_int,))     # GetText
                        f.caret_end = self._caret_at_end(el, tp, doc)
                    finally:
                        _release(doc)
            finally:
                _release(tp)
        vp = _pattern(el, ValuePatternId, IID_ValuePattern)
        if vp:
            try:
                f.readonly = bool(_int(vp, 5))                           # CurrentIsReadOnly
                if f.text is None:
                    f.text = _bstr(vp, 4)                                # CurrentValue
            finally:
                _release(vp)
        if f.text is not None:
            f.text = f.text.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _caret_at_end(el: int, tp: int, doc: int) -> bool | None:
        """光标后面只剩空白（编辑器常在最后多一个换行）就算在最后。读不到光标返回 None。"""
        caret = 0
        tp2 = _pattern(el, TextPattern2Id, IID_TextPattern2)
        if tp2:
            try:
                active = wt.BOOL()
                out = P()
                if _call(tp2, 10, ctypes.byref(active), ctypes.byref(out),            # GetCaretRange
                         argtypes=(ctypes.POINTER(wt.BOOL), ctypes.POINTER(P))) >= 0:
                    caret = out.value or 0
            finally:
                _release(tp2)
        if not caret:
            arr = _out_ptr(tp, 5)                                       # GetSelection
            if arr:
                try:
                    n = _int(arr, 3) or 0                               # IUIAutomationTextRangeArray::Length
                    if n:
                        caret = _out_ptr(arr, 4, 0, argtypes=(ctypes.c_int,))       # GetElement(0)
                finally:
                    _release(arr)
        if not caret:
            return None
        try:
            tail = _out_ptr(doc, 3)                                     # Clone
            if not tail:
                return None
            try:
                # 从光标（选区的末端）到文档末尾那一段：MoveEndpointByRange(Start, caret, End)
                if _call(tail, 15, Start, caret, End, argtypes=(ctypes.c_int, P, ctypes.c_int)) < 0:
                    return None
                rest = _bstr(tail, 12, 64, argtypes=(ctypes.c_int,))
                return rest is not None and not rest.strip()
            finally:
                _release(tail)
        finally:
            _release(caret)
