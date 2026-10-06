"""界面语言：中文写在代码里，英文对照表在 i18n_en.py。

给用户看的文字一律写成 tr("中文")；要先放进表里、等显示时才翻的（模块级的名称表等）用 N_("中文") 标记，
显示时再 tr()。带变量的写成 tr("共 {n} 块").format(n=...)，对照表里的英文用同样的 {n}。
tests/test_i18n.py 会检查：给用户看的中文都包了 tr / N_，对照表里都有英文，占位符也对得上。

界面只有中文和英文：母语是中文（简、繁）用中文界面，其余用英文界面。日志仍然用中文，给开发者看。
"""
from __future__ import annotations

import ctypes
import locale

UI_LANGS = {"zh": "中文", "en": "English"}       # 设置里的“界面语言”，各用自己的文字
LANG_PAGE_TITLE = "选择你的母语 · Choose your language"   # 新手指南第 1 步：这时还没选语言，两种都写

_lang = "zh"


def set_ui_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in UI_LANGS else "zh"


def ui_lang() -> str:
    return _lang


def tr(text: str) -> str:
    """界面文字：中文界面原样返回；英文界面查对照表，没有的原样返回。"""
    if _lang == "zh":
        return text
    from .i18n_en import EN
    return EN.get(text, text)


def N_(text: str) -> str:  # noqa: N802 - gettext 的惯用名
    """只做标记：这段文字要翻译，等显示时再 tr()。"""
    return text


def ui_lang_for(native: str) -> str:
    """母语对应的界面语言。"""
    return "zh" if native.startswith("zh") else "en"


def native_from_locale(name: str) -> str:
    """Windows 的语言名（zh-CN、zh-TW、en-US、ja-JP…）→ 支持的译文语言；认不出的当英语。"""
    from .config import LANGUAGES
    n = name.replace("_", "-").lower()
    if n.startswith("zh"):
        return "zh-Hant" if any(t in n for t in ("hant", "-tw", "-hk", "-mo")) else "zh-Hans"
    base = n.split("-")[0]
    return base if base in LANGUAGES else "en"


def system_locale() -> str:
    """Windows 的界面语言（如 zh-CN）；拿不到时退回 Python 的区域设置。"""
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.LCIDToLocaleName.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32]
        buf = ctypes.create_unicode_buffer(85)
        if k32.LCIDToLocaleName(k32.GetUserDefaultUILanguage(), buf, 85, 0):
            return buf.value
    except (OSError, AttributeError):
        pass
    return locale.getlocale()[0] or ""
