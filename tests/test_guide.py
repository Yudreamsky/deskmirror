"""新手指南和“关于”（离屏，不连外网：本机 Ollama 的检查用假服务）。"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 不在桌面上弹窗
import deskmirror  # noqa: E402,F401  预加载 DLL
from deskmirror import i18n  # noqa: E402
from deskmirror.config import AppConfig  # noqa: E402
from deskmirror.ui import guide as G  # noqa: E402


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class OllamaStatusTest(unittest.TestCase):
    def test_messages(self) -> None:
        ok, msg = G.ollama_status([], "连不上服务，检查服务地址和网络", "gemma4:12b")
        self.assertFalse(ok)
        self.assertIn("ollama.com", msg)
        ok, msg = G.ollama_status(["qwen3.8:27b"], "", "gemma4:12b")
        self.assertFalse(ok)
        self.assertIn("ollama pull gemma4:12b", msg)
        ok, _msg = G.ollama_status(["gemma4:12b", "qwen3.8:27b"], "", "gemma4:12b")
        self.assertTrue(ok)


class GuideDialogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()
        self._orig = G.GuideDialog._check_local
        G.GuideDialog._check_local = lambda self: None     # 不去连本机的 Ollama

    def tearDown(self) -> None:
        G.GuideDialog._check_local = self._orig
        i18n.set_ui_lang("zh")

    def test_pages_and_choices(self) -> None:
        cfg = AppConfig()
        g = G.GuideDialog(cfg)
        llms, scopes, done = [], [], []
        g.apply_llm.connect(llms.append)
        g.apply_scope.connect(scopes.append)
        g.guide_done.connect(lambda: done.append(1))
        self.assertEqual(g.pages.count(), G.STEPS)
        self.assertEqual(g.step_label.text(), "新手指南 · 第 1 步，共 6 步")
        self.assertTrue(g.lang_buttons["zh-Hans"].isChecked(), "第 1 步选中现在的译文语言")
        self.assertTrue(g.use_local.isChecked(), "默认是本机 Ollama")
        g._go(1)
        g._go(1)                                   # 第 3 步：改成云端 DeepSeek
        self.assertEqual(g.pages.currentIndex(), G.P_SERVICE)
        g.use_cloud.setChecked(True)
        g.preset.setCurrentIndex(0)
        g.key.setText("test-key")
        g._go(1)
        self.assertEqual(len(llms), 1)
        self.assertEqual((llms[0].protocol, llms[0].api_key), ("openai", "test-key"))
        self.assertTrue(llms[0].base_url.startswith("https://"))
        self.assertGreaterEqual(llms[0].concurrency, 2)
        g._go(1)                                   # 第 5 步：只翻魔镜所在的窗口
        g.scope.setCurrentIndex(g.scope.findData("window"))
        g._go(1)
        self.assertEqual(scopes, ["window"])
        self.assertEqual(g.pages.currentIndex(), G.STEPS - 1)
        self.assertEqual(g.next.text(), "开始使用")
        self.assertIn("DeepSeek", g.summary.text())
        self.assertIn("简体中文", g.summary.text())
        g._go(1)                                   # 开始使用 = 关掉
        self.app.processEvents()
        self.assertTrue(done)

    def test_keep_existing_cloud_settings(self) -> None:
        cfg = AppConfig()
        cfg.llm.protocol, cfg.llm.base_url, cfg.llm.model, cfg.llm.api_key = \
            "openai", "https://api.deepseek.com", "deepseek-flash", "k"
        g = G.GuideDialog(cfg)
        llms = []
        g.apply_llm.connect(llms.append)
        self.assertTrue(g.use_cloud.isChecked())
        self.assertEqual((g.model.currentText(), g.key.text()), ("deepseek-flash", "k"))
        for _ in range(3):
            g._go(1)
        self.assertEqual(g.pages.currentIndex(), G.P_USAGE)
        self.assertEqual(llms, [], "没改就不动现在的设置")
        g.close()

    def test_fetch_models_for_cloud(self) -> None:
        g = G.GuideDialog(AppConfig())
        g._run = lambda tag, fn: g._on_check_done(tag, fn())      # 同步跑，不开线程
        orig, seen = G.list_models, []
        G.list_models = lambda llm: seen.append(llm) or (["deepseek-flash", "deepseek-pro"], "")
        try:
            g.preset.setCurrentIndex(0)
            g.key.setText("test-key")
            g.model.setCurrentText("deepseek-old")
            g._fetch_models()
            self.assertTrue(g.use_cloud.isChecked(), "点了获取模型列表就是要用云端")
            self.assertEqual((seen[0].protocol, seen[0].api_key), ("openai", "test-key"))
            self.assertEqual([g.model.itemText(i) for i in range(g.model.count())], ["deepseek-flash", "deepseek-pro"])
            self.assertEqual(g.model.currentText(), "deepseek-old", "已经填的名字不动")
            self.assertIn("取到 2 个模型", g.cloud_status.text())
            self.assertIn("deepseek-old", g.cloud_status.text(), "提醒填的名字不在列表里")
            self.assertTrue(g.fetch.isEnabled())
            G.list_models = lambda llm: ([], "还没填 API Key")
            g._fetch_models()
            self.assertIn("还没填 API Key", g.cloud_status.text())
        finally:
            G.list_models = orig
        openai = next(i for i in range(g.preset.count()) if g.preset.itemData(i)[0] == "https://api.openai.com/v1")
        g.preset.setCurrentIndex(openai)                 # 换服务：旧列表和别家的模型名都清掉
        self.assertEqual((g.model.count(), g.model.currentText()), (0, ""))
        g.preset.setCurrentIndex(0)
        self.assertEqual(g.model.currentText(), "deepseek-chat")
        g.close()

    def test_pick_language(self) -> None:
        from PySide6.QtWidgets import QLabel
        g = G.GuideDialog(AppConfig())
        picked = []
        g.apply_language.connect(picked.append)
        self.assertEqual(g.next.text(), "下一步")
        g.lang_buttons["ja"].click()               # 日语：译文用日语，界面换成英文
        self.assertEqual(picked, ["ja"])
        self.assertEqual(i18n.ui_lang(), "en")
        self.assertTrue(g.lang_buttons["ja"].isChecked())
        self.assertEqual((g.next.text(), g.back.text(), g.skip.text()), ("Next", "Back", "Skip"))
        self.assertEqual(g.windowTitle(), "DeskMirror · Getting started")
        self.assertEqual(g.step_label.text(), "Getting started · step 1 of 6")
        self.assertEqual(g.pages.count(), G.STEPS, "后面各页按英文重建，页数不变")
        welcome = " ".join(lbl.text() for lbl in g.pages.widget(G.P_WELCOME).findChildren(QLabel))
        self.assertIn("Welcome to DeskMirror", welcome)
        g.lang_buttons["en"].click()               # 英文界面里换一种：不用重建
        self.assertEqual(picked, ["ja", "en"])
        g.lang_buttons["zh-Hant"].click()          # 繁体中文：界面换回中文
        self.assertEqual(i18n.ui_lang(), "zh")
        self.assertEqual(g.next.text(), "下一步")
        for _ in range(G.STEPS - 1):
            g._go(1)
        self.assertIn("繁體中文", g.summary.text())
        g.close()


class AboutTest(unittest.TestCase):
    def test_about(self) -> None:
        app = _app()
        from PySide6.QtWidgets import QLabel

        from deskmirror.ui.about import AboutDialog
        d = AboutDialog()
        texts = " ".join(lbl.text() for lbl in d.findChildren(QLabel))
        for want in ("a885187@gmail.com", "GPL-3.0", deskmirror.__version__, "github.com/Yudreamsky/deskmirror"):
            self.assertIn(want, texts)
        asked = []
        d.page.guide_requested.connect(lambda: asked.append(1))
        d.page.copy_mail.click()
        self.assertEqual(app.clipboard().text(), "a885187@gmail.com")
        from PySide6.QtWidgets import QPushButton
        next(b for b in d.findChildren(QPushButton) if b.text() == "打开新手指南").click()
        self.assertEqual(asked, [1])
        d.close()

    def test_reward(self) -> None:
        _app()
        from PySide6.QtWidgets import QLabel, QPushButton

        from deskmirror.ui import about as A
        self.assertTrue(A.REWARD_IMAGE.exists(), "赞赏码图片要跟着程序一起发布")
        d = A.AboutDialog()
        next(b for b in d.findChildren(QPushButton) if b.text() == "打赏作者…").click()
        r = d.page.reward_dialog
        self.assertIsNotNone(r)
        self.assertFalse(r.code.pixmap().isNull())
        texts = " ".join(lbl.text() for lbl in r.findChildren(QLabel))
        self.assertIn("完全自愿", texts)
        self.assertEqual("Ko-fi" in texts, bool(A.KOFI_URL), "没填 Ko-fi 地址就不显示那一行")
        orig = A.KOFI_URL
        A.KOFI_URL = "https://ko-fi.com/example"
        try:
            k = A.RewardDialog()
            self.assertIn("https://ko-fi.com/example", " ".join(lbl.text() for lbl in k.findChildren(QLabel)))
            k.close()
        finally:
            A.KOFI_URL = orig
        r.close()
        d.close()


class EnglishUiTest(unittest.TestCase):
    """英文界面：魔镜标签、打赏窗口、设置窗口、服务的出错说明。"""

    def setUp(self) -> None:
        self.app = _app()
        i18n.set_ui_lang("en")

    def tearDown(self) -> None:
        i18n.set_ui_lang("zh")

    def test_mirror_tab(self) -> None:
        from deskmirror.ui.mirror import MirrorFrame
        i18n.set_ui_lang("zh")
        f = MirrorFrame((300, 300, 1100, 800), "#3d8bfd")
        zh_w = f._buttons_width()
        i18n.set_ui_lang("en")
        f.retranslate()
        self.assertEqual([f._label(n) for n in ("pause", "look", "shot_trans", "shot_orig")],
                         ["Pause", "Image", "Shot", "Orig. shot"])
        self.assertGreater(f._buttons_width(), zh_w, "英文按钮更宽，标签跟着加宽")
        f.set_paused(True)
        self.assertEqual(f._label("pause"), "Resume")
        f.close()

    def test_reward_kofi_first(self) -> None:
        from deskmirror.ui import about as A
        if not A.KOFI_URL:
            self.skipTest("没填 Ko-fi 地址")
        r = A.RewardDialog()
        first = r.layout().itemAt(0).widget().text()
        self.assertIn("Ko-fi", first, "英文界面 Ko-fi 放最前面")
        self.assertIn("Buy me a coffee", first)
        r.close()

    def test_settings(self) -> None:
        from deskmirror.ui.settings import SettingsDialog
        cfg = AppConfig()
        cfg.ui_lang = "en"
        d = SettingsDialog(cfg)
        self.assertEqual([d.tabs.tabText(i) for i in range(d.tabs.count())],
                         ["Translation service", "Scope and privacy", "Glossary", "Recognition and display", "Hotkeys",
                          "About"])
        self.assertEqual(d.source.itemText(0), "Auto-detect")
        self.assertEqual(d.ui_lang.currentData(), "en")
        d.ui_lang.setCurrentIndex(d.ui_lang.findData("zh"))
        self.assertEqual(d.collect().ui_lang, "zh")
        d.close()

    def test_service_messages(self) -> None:
        from deskmirror.config import LlmConfig
        from deskmirror.translator import list_models
        self.assertEqual(list_models(LlmConfig(base_url=""))[1], "Enter the service address first")


if __name__ == "__main__":
    unittest.main()
