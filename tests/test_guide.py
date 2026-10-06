"""新手指南和“关于”（离屏，不连外网：本机 Ollama 的检查用假服务）。"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 不在桌面上弹窗
import deskmirror  # noqa: E402,F401  预加载 DLL
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

    def test_pages_and_choices(self) -> None:
        cfg = AppConfig()
        g = G.GuideDialog(cfg)
        llms, scopes, done = [], [], []
        g.apply_llm.connect(llms.append)
        g.apply_scope.connect(scopes.append)
        g.guide_done.connect(lambda: done.append(1))
        self.assertEqual(g.pages.count(), G.STEPS)
        self.assertTrue(g.use_local.isChecked(), "默认是本机 Ollama")
        g._go(1)                                   # 第 2 步：改成云端 DeepSeek
        g.use_cloud.setChecked(True)
        g.preset.setCurrentIndex(0)
        g.key.setText("test-key")
        g._go(1)
        self.assertEqual(len(llms), 1)
        self.assertEqual((llms[0].protocol, llms[0].api_key), ("openai", "test-key"))
        self.assertTrue(llms[0].base_url.startswith("https://"))
        self.assertGreaterEqual(llms[0].concurrency, 2)
        g._go(1)                                   # 第 4 步：只翻魔镜所在的窗口
        g.scope.setCurrentIndex(g.scope.findData("window"))
        g._go(1)
        self.assertEqual(scopes, ["window"])
        self.assertEqual(g.pages.currentIndex(), G.STEPS - 1)
        self.assertEqual(g.next.text(), "开始使用")
        self.assertIn("DeepSeek", g.summary.text())
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
        self.assertEqual((g.model.text(), g.key.text()), ("deepseek-flash", "k"))
        g._go(1)
        g._go(1)
        self.assertEqual(llms, [], "没改就不动现在的设置")
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


if __name__ == "__main__":
    unittest.main()
