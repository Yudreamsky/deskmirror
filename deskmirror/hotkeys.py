"""全局热键：Win32 RegisterHotKey + Qt 原生事件过滤器。"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal

from .i18n import tr

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312

_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
              "win": MOD_WIN, "meta": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "pgup": 0x21, "pageup": 0x21, "pgdown": 0x22, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}


def _key_code(name: str, keypad: bool) -> int:
    if len(name) == 1 and name.isascii() and name.isalnum():
        if keypad and name.isdigit():
            return 0x60 + int(name)  # VK_NUMPAD0..9
        return ord(name.upper())
    if name[0] == "f" and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x6F + int(name[1:])  # VK_F1..F24
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    raise ValueError(tr("不认识的按键：{name}").format(name=name))


def parse_hotkey(text: str) -> tuple[int, int]:
    """"Ctrl+Alt+S" → (修饰键, 虚拟键码)。格式和 Qt 的 QKeySequence 文本一致。"""
    mods, vk, keypad = 0, None, False
    for part in (p.strip().lower() for p in text.split("+")):
        if not part:
            raise ValueError(tr("快捷键格式不对：{text}").format(text=text))
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif part == "num":
            keypad = True
        elif vk is not None:
            raise ValueError(tr("快捷键只能有一个主键：{text}").format(text=text))
        else:
            vk = _key_code(part, keypad)
    if vk is None:
        raise ValueError(tr("快捷键缺少主键：{text}").format(text=text))
    if not mods and not 0x70 <= vk <= 0x87:  # 除了 F 键，单键会吞掉正常打字
        raise ValueError(tr("快捷键至少要带一个 Ctrl / Alt / Shift / Win：{text}").format(text=text))
    return mods, vk


def is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class HoldShortcut(QObject):
    """注册热键只负责按下；按住期间以30ms轮询主键，松开撤回临时显示。"""
    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self._vk = None
        self._timer = QTimer(self, interval=30, timeout=self._poll)

    def start(self, combo: str) -> None:
        try:
            _, vk = parse_hotkey(combo)
        except ValueError:
            return
        if not is_key_down(vk):
            return  # 极快松键时，排队的按下事件不能再把译文隐藏。
        self._vk = vk
        if not self.active:
            self.active = True
            self.changed.emit(True)
        self._timer.start()

    def _poll(self) -> None:
        if self._vk is None or not is_key_down(self._vk):
            self.stop()

    def stop(self) -> None:
        self._timer.stop()
        self._vk = None
        if self.active:
            self.active = False
            self.changed.emit(False)


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and self._on_hotkey(int(msg.wParam)):
                return True, 0
        return False, 0


class HotkeyManager(QObject):
    activated = Signal(str)

    def __init__(self, app) -> None:
        super().__init__()
        self._actions: dict[int, str] = {}
        self._filter = _NativeFilter(self._dispatch)
        app.installNativeEventFilter(self._filter)

    def register(self, bindings: dict[str, str]) -> list[str]:
        """注册一组热键（动作名 → 组合键），返回注册失败的说明。"""
        self.unregister_all()
        errors = []
        for hid, (action, combo) in enumerate(bindings.items(), start=1):
            if not combo.strip():
                continue
            try:
                mods, vk = parse_hotkey(combo)
            except ValueError as e:
                errors.append(str(e))
                continue
            if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                self._actions[hid] = action
            else:
                errors.append(tr("{combo} 注册失败，可能被其他程序占用了").format(combo=combo))
        for err in errors:
            log.warning(err)
        return errors

    def unregister_all(self) -> None:
        for hid in self._actions:
            user32.UnregisterHotKey(None, hid)
        self._actions.clear()

    def _dispatch(self, hid: int) -> bool:
        action = self._actions.get(hid)
        if action is None:
            return False
        # 离开原生事件回调再处理，避免在里面弹窗口
        QTimer.singleShot(0, lambda: self.activated.emit(action))
        return True


_MOD_VKS = {"ctrl": (0x11,), "control": (0x11,), "alt": (0x12,), "shift": (0x10,), "win": (0x5B, 0x5C),
            "meta": (0x5B, 0x5C)}


def parse_modifiers(text: str) -> list[tuple[int, ...]]:
    """"Ctrl+Alt" → 每个修饰键对应的虚拟键码组（任意一个按下即可）。"""
    out = []
    for part in (p.strip().lower() for p in text.split("+")):
        if part in _MOD_VKS:
            out.append(_MOD_VKS[part])
        elif part:
            raise ValueError(tr("拖动键只能由 Ctrl / Alt / Shift / Win 组成：{text}").format(text=text))
    if not out:
        raise ValueError(tr("拖动键不能为空"))
    return out


def modifiers_down(groups: list[tuple[int, ...]]) -> bool:
    return all(any(is_key_down(vk) for vk in g) for g in groups)
