"""看图翻译（多模态）和字幕 / 对话的短上下文。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 界面测试不在桌面上弹窗
import numpy as np  # noqa: E402

import deskmirror  # noqa: E402,F401  预加载 DLL
from deskmirror import config, textutil, vision  # noqa: E402
from deskmirror import engine as E  # noqa: E402
from deskmirror.config import AppConfig, VisionConfig  # noqa: E402
from deskmirror.translator import ServiceError  # noqa: E402

from tests.test_engine import add_block, make_engine  # noqa: E402
from tests.test_pixels import text_page  # noqa: E402


class VisionRequestTest(unittest.TestCase):
    def test_local(self) -> None:
        self.assertTrue(vision.is_local("http://127.0.0.1:11434"))
        self.assertTrue(vision.is_local("localhost:1234/v1"))
        self.assertFalse(vision.is_local("https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.assertEqual(vision.host_of("https://api.example.com/v1"), "api.example.com")

    def test_payloads(self) -> None:
        url, p, h = vision.build_request(VisionConfig(), "prompt", "QUJD")
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(p["messages"][0]["images"], ["QUJD"])
        self.assertIs(p["think"], False)
        self.assertEqual(h, {})
        c = VisionConfig(protocol="openai", base_url="https://api.example.com/v1/", model="vl", api_key="k")
        url, p, h = vision.build_request(c, "prompt", "QUJD")
        self.assertEqual(url, "https://api.example.com/v1/chat/completions")
        self.assertEqual(p["messages"][0]["content"][1]["image_url"]["url"], "data:image/jpeg;base64,QUJD")
        self.assertEqual(h["Authorization"], "Bearer k")
        self.assertIn("Simplified Chinese", vision.vision_prompt("zh-Hans"))
        self.assertIn("mostly Korean", vision.vision_prompt("zh-Hans", "ko"))

    def test_stream_pieces_and_errors(self) -> None:
        self.assertEqual(vision._piece("ollama", json.dumps({"message": {"content": "你好"}}), "m"), "你好")
        self.assertEqual(vision._piece("openai", 'data: {"choices":[{"delta":{"content":"桥"}}]}', "m"), "桥")
        self.assertEqual(vision._piece("openai", "data: [DONE]", "m"), "")
        with self.assertRaises(ServiceError) as cm:
            vision._piece("ollama", json.dumps({"error": "model does not support images"}), "qwen")
        self.assertIn("不能看图", str(cm.exception))

    def test_encode_scales_down(self) -> None:
        img = np.full((900, 3000, 3), 200, np.uint8)
        b64, w, h = vision.encode_image(img, 1600)
        self.assertEqual((w, h), (1600, 480))
        self.assertTrue(len(b64) > 100)
        b64, w, h = vision.encode_image(np.zeros((300, 400, 3), np.uint8), 1600)
        self.assertEqual((w, h), (400, 300), "小图不放大")


class VisionConfigTest(unittest.TestCase):
    def test_key_encrypted_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "deskmirror.json"
            old = os.environ.get("DESKMIRROR_CONFIG")
            os.environ["DESKMIRROR_CONFIG"] = str(p)
            try:
                c = AppConfig()
                c.vision.api_key = "secret-vision-key"
                config.save(c)
                self.assertNotIn("secret-vision-key", p.read_text(encoding="utf-8"))
                self.assertEqual(config.load().vision.api_key, "secret-vision-key")
            finally:
                if old is None:
                    os.environ.pop("DESKMIRROR_CONFIG", None)
                else:
                    os.environ["DESKMIRROR_CONFIG"] = old


class QtPartsTest(unittest.TestCase):
    def test_qimage_to_bgr_and_settings(self) -> None:
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QApplication

        from deskmirror.app import _qimage_bgr
        from deskmirror.ui.settings import SettingsDialog
        app = QApplication.instance() or QApplication([])
        img = QImage(5, 3, QImage.Format.Format_RGB32)
        img.fill(QColor(10, 20, 30))
        self.assertEqual(_qimage_bgr(img)[1, 2].tolist(), [30, 20, 10])
        dlg = SettingsDialog(AppConfig())
        dlg.v_model.setText("qwen-vl")
        dlg.v_protocol.setCurrentIndex(1)
        c = dlg.collect()
        self.assertEqual((c.vision.model, c.vision.protocol, c.hotkeys.vision), ("qwen-vl", "openai", "Ctrl+Alt+V"))
        dlg.close()
        app.processEvents()


class DialogContextTest(unittest.TestCase):
    def test_previous_lines_go_with_subtitles(self) -> None:
        page = text_page(3000, 900, 13)
        eng, m, win, sc = make_engine(page[0:1200])
        sent = []

        class Pool:
            def submit(self, batch) -> None:
                sent.append(batch)

        eng.pool = Pool()

        def line(y: int, text: str, dynamic: bool):
            b = add_block(eng, sc, (10, y, 400, y + 22), page[y:y + 22, 10:400])
            b.text, b.key, b.state, b.born_dynamic = text, textutil.cache_key(text), "pending", dynamic
            eng.by_key[b.key].add(b.bid)
            return b

        first = line(100, "We have to reach the harbour.", True)
        eng._schedule_translation()
        self.assertEqual(sent[-1].dialog, [], "第一句没有前文")
        eng._on_translation(("segment", sent[-1].batch_id, 0, "我们必须赶到港口。"))
        eng._on_translation(("batch_done", sent[-1].batch_id, None, 0.5))
        self.assertEqual(first.state, "done")
        line(200, "The bridge is broken.", True)
        eng._schedule_translation()
        self.assertEqual(sent[-1].dialog, [("We have to reach the harbour.", "我们必须赶到港口。")])
        eng._on_translation(("batch_done", sent[-1].batch_id, None, 0.5))
        line(300, "Installation guide for the racking system.", False)
        eng.inflight.clear()
        eng._schedule_translation()
        self.assertEqual(sent[-1].dialog, [], "网页正文不带字幕上下文")


if __name__ == "__main__":
    unittest.main()
