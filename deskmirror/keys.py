"""快捷键文字的解析（不依赖 Qt：命令行改设置时也用它检查格式）。注册热键见 hotkeys.py。"""
from __future__ import annotations

from .i18n import tr

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
              "win": MOD_WIN, "meta": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "pgup": 0x21, "pageup": 0x21, "pgdown": 0x22, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E, "prtsc": 0x2C, "printscreen": 0x2C, "pause": 0x13,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}
_SINGLE_OK = set(range(0x70, 0x88)) | {0x2C, 0x13}   # F1–F24、PrtSc、Pause：单独按也不影响打字
# 显示用的写法（parse_hotkey 都认）
_KEY_NAMES = {0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x08: "Backspace", 0x21: "PgUp", 0x22: "PgDown",
              0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2D: "Ins",
              0x2E: "Del", 0x2C: "PrtSc", 0x13: "Pause", 0xC0: "`", 0xBD: "-", 0xBB: "=", 0xDB: "[", 0xDD: "]",
              0xBA: ";", 0xDE: "'", 0xBC: ",", 0xBE: ".", 0xBF: "/", 0xDC: "\\"}


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
    if not mods and vk not in _SINGLE_OK:  # 除了 F 键、PrtSc、Pause，单键会吞掉正常打字
        raise ValueError(tr("快捷键至少要带一个 Ctrl / Alt / Shift / Win：{text}").format(text=text))
    return mods, vk


def key_name(vk: int) -> str:
    """虚拟键码 → 快捷键里的写法；不能用作快捷键的键（单独的修饰键、媒体键等）返回空串。"""
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num+{vk - 0x60}"
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    return _KEY_NAMES.get(vk, "")


def mods_text(mods: int) -> str:
    """修饰键 → "Ctrl+Alt"（顺序固定：Ctrl、Alt、Shift、Win）。"""
    return "+".join(n for flag, n in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win"))
                    if mods & flag)


def combo_text(mods: int, vk: int) -> str:
    """(修饰键, 虚拟键码) → "Ctrl+Alt+S"：parse_hotkey 反过来。"""
    name = key_name(vk)
    if not name:
        raise ValueError(tr("这个键不能用作快捷键"))
    head = mods_text(mods)
    return f"{head}+{name}" if head else name


def normalize_hotkey(text: str) -> str:
    """统一写法（"ctrl + alt + s" → "Ctrl+Alt+S"），用来判断两个快捷键是不是同一个；空着照旧是空串。"""
    return combo_text(*parse_hotkey(text)) if text.strip() else ""


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
