"""全局热键：Win32 RegisterHotKey + Qt 原生事件过滤器。"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal

from .i18n import tr
from .keys import MOD_NOREPEAT, parse_hotkey, parse_modifiers  # noqa: F401  app 从这里导入

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

WM_HOTKEY = 0x0312


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


def modifiers_down(groups: list[tuple[int, ...]]) -> bool:
    return all(any(is_key_down(vk) for vk in g) for g in groups)
