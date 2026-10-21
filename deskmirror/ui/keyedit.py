"""设置窗口里的快捷键框：点一下，按下新的组合键就记下来，不用手打 "Ctrl+Alt+O"。

录的时候装一个低级键盘钩子（WH_KEYBOARD_LL）：被别的程序注册成全局热键的组合键也收得到，而且不会顺手触发它们。
只吞掉组成组合键的那个主键；修饰键照常放过（吞掉它的松开，系统会以为 Ctrl 一直按着）。
录完试着注册一下，注册不上就是被别的程序占着。设置窗口开着时，魔镜自己的快捷键先放开（见 app.open_settings）。
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes as wt

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QPushButton

from ..i18n import tr
from ..keys import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, combo_text, mods_text, parse_hotkey

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x100, 0x104
LRESULT = ctypes.c_ssize_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE

_MOD_OF_VK = {0x10: MOD_SHIFT, 0xA0: MOD_SHIFT, 0xA1: MOD_SHIFT, 0x11: MOD_CONTROL, 0xA2: MOD_CONTROL,
              0xA3: MOD_CONTROL, 0x12: MOD_ALT, 0xA4: MOD_ALT, 0xA5: MOD_ALT, 0x5B: MOD_WIN, 0x5C: MOD_WIN}
_PROBE_ID = 0xBFF0


def probe(text: str) -> bool:
    """这个组合键现在注册得上吗（注册上了马上放开）。False：被别的程序占着，或者是系统保留的。"""
    mods, vk = parse_hotkey(text)
    if user32.RegisterHotKey(None, _PROBE_ID, mods | MOD_NOREPEAT, vk):
        user32.UnregisterHotKey(None, _PROBE_ID)
        return True
    return False


class Recorder:
    """按键 → 组合键（不依赖 Qt、不装钩子：测试直接喂按键）。

    feed(vk, down) 返回 (要不要吞掉这个键, 结果)。结果：None（接着录）、("set", 文字)、("clear", "")、("cancel", "")、
    ("hint", 说明，接着录)。mods_only：只录修饰键（按住拖动魔镜用的 Ctrl+Alt），全部松开时定下。"""

    def __init__(self, mods_only: bool = False) -> None:
        self.mods_only = mods_only
        self.held: set[int] = set()
        self.peak = 0

    def _mods(self) -> int:
        m = 0
        for vk in self.held:
            m |= _MOD_OF_VK[vk]
        return m

    def feed(self, vk: int, down: bool) -> tuple[bool, tuple[str, str] | None]:
        if vk in _MOD_OF_VK:
            if down:
                self.held.add(vk)
                if self.mods_only:
                    self.peak |= self._mods()
            else:
                self.held.discard(vk)
                if self.mods_only and not self.held and self.peak:
                    return False, ("set", mods_text(self.peak))
            return False, None
        if not down:
            return False, None
        mods = self._mods()
        if not mods and vk == 0x1B:
            return True, ("cancel", "")
        if not mods and vk in (0x08, 0x2E):
            if self.mods_only:
                return True, ("hint", tr("拖动魔镜用的键不能清空"))
            return True, ("clear", "")
        if self.mods_only:
            return True, ("hint", tr("只按 Ctrl、Alt、Shift、Win（可以几个一起按），松开就记下"))
        try:
            text = combo_text(mods, vk)
            parse_hotkey(text)
        except ValueError as e:
            return True, ("hint", str(e))
        return True, ("set", text)


class KeyboardHook:
    """低级键盘钩子：on_key(vk, down) 返回 True 就吞掉这个键。装在调用线程上（要有消息循环，界面线程就行）。"""

    def __init__(self, on_key) -> None:
        self._on_key = on_key
        self._proc = HOOKPROC(self._callback)      # 留着引用：被回收了钩子会调到野指针
        self._hook = None

    def start(self) -> bool:
        if not self._hook:
            self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        return bool(self._hook)

    def stop(self) -> None:
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        if code == 0:
            k = KBDLLHOOKSTRUCT.from_address(lparam)
            try:
                if self._on_key(int(k.vkCode), wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)):
                    return 1
            except Exception:  # noqa: BLE001  钩子里不能抛出去
                log.exception("快捷键录入出错")
        return user32.CallNextHookEx(None, code, wparam, lparam)


class HotkeyEdit(QPushButton):
    """显示一个快捷键；点一下进入录制，按下组合键就换上。Esc 取消，Backspace 清空（不用这个快捷键）。"""
    changed = Signal(str)
    hint = Signal(str)          # 录制时的提示（这个键不能用之类），由设置窗口显示在旁边

    def __init__(self, value: str, mods_only: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.mods_only = mods_only
        self._value = value
        self._rec: Recorder | None = None
        self._hook = KeyboardHook(self._on_key)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(190)
        self.setToolTip(tr("点一下，再按新的组合键。Esc 取消；Backspace 清空（不用这个快捷键）")
                        if not mods_only else tr("点一下，再按住想用的修饰键（比如 Ctrl+Alt），松开就记下"))
        self.clicked.connect(self.start)
        self._show()

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        if value != self._value:
            self._value = value
            self.changed.emit(value)
        self._show()

    def recording(self) -> bool:
        return self._rec is not None

    def start(self) -> None:
        if self._rec is not None:
            return
        self._rec = Recorder(self.mods_only)
        if not self._hook.start():
            self._rec = None
            self.hint.emit(tr("没法录快捷键（装不上键盘钩子）"))
            return
        self.setText(tr("按住修饰键…") if self.mods_only else tr("请按组合键…"))
        self.setFocus()

    def stop(self) -> None:
        self._hook.stop()
        if self._rec is not None:
            self._rec = None
            self._show()

    def _on_key(self, vk: int, down: bool) -> bool:
        rec = self._rec
        if rec is None:
            return False
        swallow, res = rec.feed(vk, down)
        if res is not None:
            QTimer.singleShot(0, lambda r=res: self._finish(r))   # 别在钩子回调里改界面
        return swallow

    def _finish(self, res: tuple[str, str]) -> None:
        kind, text = res
        if self._rec is None:
            return
        if kind == "hint":
            self.hint.emit(text)
            return
        self.stop()
        if kind == "set":
            self.set_value(text)
        elif kind == "clear":
            self.set_value("")
        self.hint.emit("")

    def focusOutEvent(self, e) -> None:
        self.stop()
        super().focusOutEvent(e)

    def hideEvent(self, e) -> None:
        self.stop()
        super().hideEvent(e)

    def keyPressEvent(self, e) -> None:
        if self._rec is not None:
            e.accept()            # 录制中的按键由钩子处理；这里只挡住按钮自己的空格、回车
            return
        super().keyPressEvent(e)

    def _show(self) -> None:
        self.setText(self._value.replace("+", " + ") if self._value else tr("（不用）"))
