"""语言：手动指定原文 / 译成的语言、印尼语、原文选韩文时换识别模型。"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 按钮测试不在桌面上弹窗
import deskmirror  # noqa: E402,F401  预加载 DLL
from deskmirror import config, textutil, translator
from deskmirror import engine as E
from deskmirror.config import AppConfig

from tests.test_engine import add_block, make_engine
from tests.test_pixels import text_page

ID_TEXT = "Pasang sekrup tanah secara vertikal dan pastikan semua klem sudah terpasang dengan benar."
EN_TEXT = "Install the ground screws vertically and make sure every clamp is tightened."


class PromptTest(unittest.TestCase):
    def test_source_hint_and_indonesian(self) -> None:
        self.assertIn("mostly Indonesian", translator.system_prompt("zh-Hans", "id"))
        self.assertNotIn("mostly", translator.system_prompt("zh-Hans", "auto"))
        self.assertIn("Indonesian (Bahasa Indonesia)", translator.system_prompt("id", "en"))


class OcrFixTest(unittest.TestCase):
    def test_katakana_long_vowel_read_as_dash(self) -> None:
        # 识别模型常把片假名的长音认成减号、汉字“一”：改回长音，术语表才对得上（セーブ → 存档）
        f = textutil.fix_ocr
        self.assertEqual(f("セ-ブ"), "セーブ")
        self.assertEqual(f("セ" + chr(0x4E00) + "ブ"), "セーブ")
        self.assertEqual(f("コーヒ-"), "コーヒー")
        self.assertEqual(f("メニュー" + chr(0x4E00) + "覧"), "メニュー" + chr(0x4E00) + "覧", "后面是汉字：是“一”")
        for t in ("A-B 2-3", "残り 02:06", "卢门-港", "セーブ"):
            self.assertEqual(f(t), t)


class IndonesianTest(unittest.TestCase):
    def test_detect(self) -> None:
        self.assertTrue(textutil.looks_indonesian(ID_TEXT))
        self.assertTrue(textutil.looks_indonesian("Hubungi kami untuk penawaran"))
        self.assertFalse(textutil.looks_indonesian(EN_TEXT))

    def test_needs_translation(self) -> None:
        self.assertTrue(textutil.needs_translation(ID_TEXT, "zh-Hans"))
        self.assertTrue(textutil.needs_translation(ID_TEXT, "en"), "印尼文不能当成英文跳过")
        self.assertFalse(textutil.needs_translation(EN_TEXT, "en"))
        self.assertFalse(textutil.needs_translation(ID_TEXT, "id"), "已经是印尼文")
        self.assertTrue(textutil.needs_translation(EN_TEXT, "id"))


class ConfigTest(unittest.TestCase):
    def test_validate(self) -> None:
        c = AppConfig()
        c.source_lang, c.target_lang = "xx", "id"
        c = config.validate(c)
        self.assertEqual((c.source_lang, c.target_lang), ("auto", "id"))
        self.assertEqual(config.ocr_lang_for("ko"), "korean")
        self.assertEqual(config.ocr_lang_for("id"), "default")


class _StubOcr:
    started: list = []

    def __init__(self, device, threads, on_message, lang="default") -> None:
        _StubOcr.started.append(lang)
        self.closed = False

    def close(self, timeout: float = 3.0) -> None:
        self.closed = True


class EngineLangTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = E.OcrClient
        E.OcrClient = _StubOcr
        _StubOcr.started = []

    def tearDown(self) -> None:
        E.OcrClient = self._orig

    def test_target_change_resets_translations(self) -> None:
        page = text_page(3000, 900, 11)
        eng, m, win, sc = make_engine(page[0:1200])
        b = add_block(eng, sc, (10, 100, 400, 122), page[100:122, 10:400])
        b.text, b.key, b.state, b.translation = EN_TEXT, textutil.cache_key(EN_TEXT), "done", "把地螺丝垂直安装好。"
        n = add_block(eng, sc, (10, 200, 200, 222), page[200:222, 10:200])
        n.text, n.key, n.state = "120 / 150", textutil.cache_key("120 / 150"), "skip"
        eng.cache[b.key] = b.translation
        eng.cfg.target_lang = "id"
        eng._apply_languages()
        self.assertEqual(eng.cache, {})
        self.assertEqual((b.state, b.translation), ("pending", ""))
        self.assertEqual(n.state, "skip", "纯数字换了语言也不用翻")
        self.assertEqual(_StubOcr.started, [], "只换译成的语言，不换识别模型")

    def test_korean_source_restarts_ocr(self) -> None:
        page = text_page(3000, 900, 12)
        eng, m, win, sc = make_engine(page[0:1200])
        eng.ocr = _StubOcr("cpu", 1, None)
        old = eng.ocr
        _StubOcr.started = []
        b = add_block(eng, sc, (10, 100, 400, 122), page[100:122, 10:400])
        eng.cfg.source_lang = "ko"
        eng._apply_languages()
        self.assertTrue(old.closed)
        self.assertEqual(_StubOcr.started, ["korean"])
        self.assertNotIn(b.bid, eng.blocks, "旧模型认出来的块作废")
        self.assertTrue((m.needs > 0).all(), "整块屏幕重新识别")
        eng.cfg.source_lang = "en"
        eng._apply_languages()
        self.assertEqual(_StubOcr.started, ["korean", "default"])
        eng.cfg.source_lang = "id"
        eng._apply_languages()
        self.assertEqual(len(_StubOcr.started), 2, "英文换印尼文不用换模型")


class LangButtonTest(unittest.TestCase):
    def test_button(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        from deskmirror.ui.mirror import MirrorFrame
        app = QApplication.instance() or QApplication([])
        f = MirrorFrame((300, 300, 1100, 800), "#3d8bfd")
        f.show()
        app.processEvents()
        self.assertIn("lang", f._buttons)
        f.set_lang_label("英→中")
        w0 = f._buttons["lang"].width()
        f.set_lang_label("自动→印尼")
        self.assertGreater(f._buttons["lang"].width(), w0)
        rects = list(f._buttons.values())
        self.assertFalse(any(a.intersects(b) for i, a in enumerate(rects) for b in rects[i + 1:]), "按钮不重叠")
        got = []
        f.lang_clicked.connect(got.append)
        QTest.mouseClick(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, f._buttons["lang"].center())
        app.processEvents()
        self.assertEqual(len(got), 1)
        f.close()


if __name__ == "__main__":
    unittest.main()
