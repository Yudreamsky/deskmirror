"""界面语言：给用户看的中文都要写成 tr("…") 或 N_("…")，对照表里要有英文，占位符要对得上。

以后加功能时漏了包 tr、漏了写英文，这里会报出文件和行号。
"""
from __future__ import annotations

import ast
import pathlib
import re
import string
import unittest

import deskmirror
from deskmirror import i18n

PKG = pathlib.Path(deskmirror.__file__).resolve().parent
CJK = re.compile(r"[　-〿一-鿿＀-￯]")
SKIP_FILES = {"i18n.py", "i18n_en.py"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# 有意不翻译的中文（日志、正则之外）：不是界面文字
ALLOWED = {
    "app.py": {"镜"},                                                     # 托盘图标上的字：标志
    "config.py": {"简体中文", "繁體中文", "日本語",                          # 语言名用各自的文字写
                  "网上银行", "网银", "手机银行", "支付宝", "微信支付"},       # 按窗口标题排除，要和真实标题一致
    "ocr_worker.py": {"DirectML 会话退回了 CPU", "识别进程意外退出"},         # 只进日志
    "translator.py": {"Simplified Chinese (简体中文)", "Traditional Chinese (繁體中文)", "Japanese (日本語)"},  # 给模型看
    "ui/guide.py": {"港口指南", "今天这座桥封了。", "请走北边那条路。", "港口在 3 公里外。", "船每小时开一班。"},  # 示意图
    "ui/settings.py": {"，"},                                             # 解析名单时中文逗号也算分隔符
    "vertical.py": {"一-_—ー－‐−~～|｜"},                                  # 竖排识别：可能是竖线（长音）认出来的字
}


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")


def _is_log(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr in LOG_METHODS and isinstance(f.value, ast.Name)
            and f.value.id in ("log", "logger", "logging"))


def scan() -> tuple[dict[str, str], list[str]]:
    """→ (tr / N_ 里的中文原文 → 第一次出现的位置, 没包起来的界面中文)。"""
    keys: dict[str, str] = {}
    bad: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        if rel in SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and _call_name(n) in ("tr", "N_") and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.setdefault(a.value, f"{rel}:{n.lineno}")
                elif isinstance(a, ast.JoinedStr):
                    bad.append(f"{rel}:{n.lineno} tr 里不能用 f-string，改成 tr(\"…{{x}}…\").format(x=…)")
                continue
            if isinstance(n, ast.JoinedStr):
                text = "".join(str(v.value) for v in n.values if isinstance(v, ast.Constant))
            elif (isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
                  and not isinstance(parent.get(n), ast.JoinedStr)):
                text = n.value
            else:
                continue
            if not CJK.search(text) or text in ALLOWED.get(rel, ()):
                continue
            p = parent.get(n)
            while p is not None and not isinstance(p, ast.Call):
                p = parent.get(p)
            if p is not None and ((_call_name(p) in ("tr", "N_") and isinstance(n, ast.Constant))
                                  or _is_log(p) or _call_name(p) == "compile"):
                continue
            bad.append(f"{rel}:{n.lineno} {text[:40]!r}")
    return keys, bad


def _fields(s: str) -> set[str]:
    return {f for _lit, f, _spec, _conv in string.Formatter().parse(s) if f is not None}


class CoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from deskmirror.i18n_en import EN
        cls.en = EN
        cls.keys, cls.bad = scan()

    def test_ui_text_wrapped(self) -> None:
        self.assertEqual(self.bad, [], "给用户看的中文要写成 tr(\"…\") 或 N_(\"…\")")

    def test_every_key_has_english(self) -> None:
        missing = [f"{loc} {k[:40]!r}" for k, loc in self.keys.items() if k not in self.en]
        self.assertEqual(missing, [], "i18n_en.py 里缺这些英文")

    def test_no_stale_english(self) -> None:
        self.assertEqual([k[:40] for k in self.en if k not in self.keys], [], "对照表里有代码已经不用的条目")

    def test_placeholders_match(self) -> None:
        diff = [k[:40] for k in self.keys if k in self.en and _fields(k) != _fields(self.en[k])]
        self.assertEqual(diff, [], "英文的 {占位符} 要和中文一致")

    def test_english_is_english(self) -> None:
        # 只允许提到托盘图标上的“镜”字；别把中文标点带进英文
        odd = [v[:40] for v in self.en.values() if CJK.search(v.replace("“镜”", ""))]
        self.assertEqual(odd, [])

    def test_no_ampersand(self) -> None:
        # 标签页、按钮、菜单、分组框会把 & 当快捷键标记吃掉（“Scope & privacy”变成“Scope  privacy”）
        self.assertEqual([v[:40] for v in self.en.values() if "&" in v], [], "英文里用 and，别用 &")


class SwitchTest(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_ui_lang("zh")

    def test_tr(self) -> None:
        self.assertEqual(i18n.tr("设置…"), "设置…")
        i18n.set_ui_lang("en")
        self.assertEqual(i18n.tr("设置…"), "Settings…")
        self.assertEqual(i18n.tr("没有这一条"), "没有这一条", "对照表里没有的原样返回")
        i18n.set_ui_lang("fr")
        self.assertEqual(i18n.ui_lang(), "zh", "不认识的界面语言退回中文")

    def test_native_language(self) -> None:
        cases = {"zh-CN": "zh-Hans", "zh-SG": "zh-Hans", "zh-TW": "zh-Hant", "zh-HK": "zh-Hant",
                 "zh-Hant-TW": "zh-Hant", "en-US": "en", "en-GB": "en", "ja-JP": "ja", "ko-KR": "ko",
                 "id-ID": "id", "de-DE": "en", "": "en"}
        for name, want in cases.items():
            self.assertEqual(i18n.native_from_locale(name), want, name)
        self.assertEqual([i18n.ui_lang_for(x) for x in ("zh-Hans", "zh-Hant", "en", "ja", "ko", "id")],
                         ["zh", "zh", "en", "en", "en", "en"])


if __name__ == "__main__":
    unittest.main()
