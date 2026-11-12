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
        self.assertEqual((p["keep_alive"], p["options"]["num_ctx"]), ("30m", 4096), "本机 Ollama 和翻译用同一个模型")
        self.assertEqual(h, {})
        c = VisionConfig(base_url="https://ollama.com/", model="gemma4:31b", api_key="k")    # Ollama 云端
        url, p, h = vision.build_request(c, "prompt", "QUJD")
        self.assertEqual((url, h), ("https://ollama.com/api/chat", {"Authorization": "Bearer k"}))
        self.assertEqual(p["messages"][0]["images"], ["QUJD"])
        self.assertNotIn("keep_alive", p)
        self.assertNotIn("num_ctx", p["options"])
        self.assertFalse(vision.is_local(c.base_url), "发给 Ollama 云端前也要先问")
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
                c.vision.use_llm = True
                config.save(c)
                self.assertNotIn("secret-vision-key", p.read_text(encoding="utf-8"))
                self.assertEqual(config.load().vision.api_key, "secret-vision-key")
                self.assertTrue(config.load().vision.use_llm)
            finally:
                if old is None:
                    os.environ.pop("DESKMIRROR_CONFIG", None)
                else:
                    os.environ["DESKMIRROR_CONFIG"] = old

    def test_use_llm(self) -> None:
        c = AppConfig()
        c.llm.base_url, c.llm.model, c.llm.api_key, c.llm.num_ctx = "https://ollama.com", "gemma4:31b", "k", 8192
        self.assertIs(config.vision_service(c), c.vision, "默认看图翻译单独设")
        c.vision.use_llm = True
        v = config.vision_service(c)
        self.assertEqual((v.protocol, v.base_url, v.model, v.api_key, v.num_ctx),
                         ("ollama", "https://ollama.com", "gemma4:31b", "k", 8192))
        self.assertEqual((v.timeout_s, v.max_side), (120.0, 1600), "超时、图片大小还用看图翻译自己的")
        self.assertEqual((c.vision.base_url, c.vision.model), ("http://127.0.0.1:11434", "gemma4:12b"),
                         "看图翻译自己的设置留着，取消勾选时还用")
        c.llm.protocol, c.llm.base_url, c.llm.model = "openai", "https://api.example.com/v1", "vl"
        url, _p, h = vision.build_request(config.vision_service(c), "prompt", "QUJD")
        self.assertEqual((url, h["Authorization"]), ("https://api.example.com/v1/chat/completions", "Bearer k"))


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

    def test_settings_vision_uses_this_api(self) -> None:
        from PySide6.QtWidgets import QApplication

        from deskmirror.ui.settings import SettingsDialog
        app = QApplication.instance() or QApplication([])
        cfg = AppConfig()
        cfg.vision.model = "qwen-vl"
        dlg = SettingsDialog(cfg)
        self.assertFalse(dlg.v_same.isChecked())
        self.assertTrue(dlg.v_model.isEnabled())
        dlg.base_url.setText("https://ollama.com")
        dlg.model.setCurrentText("gemma4:31b")
        dlg.api_key.setText("k")
        dlg.v_same.setChecked(True)
        self.assertEqual((dlg.v_protocol.currentData(), dlg.v_base.text(), dlg.v_model.text(), dlg.v_key.text()),
                         ("ollama", "https://ollama.com", "gemma4:31b", "k"), "显示翻译服务的")
        self.assertFalse(any(w.isEnabled() for w in (dlg.v_protocol, dlg.v_base, dlg.v_model, dlg.v_key)))
        dlg.model.setCurrentText("gemma4:27b")
        self.assertEqual(dlg.v_model.text(), "gemma4:27b", "上面改了，下面跟着变")
        c = dlg.collect()
        self.assertTrue(c.vision.use_llm)
        self.assertEqual((c.vision.base_url, c.vision.model, c.vision.api_key), ("http://127.0.0.1:11434", "qwen-vl", ""),
                         "看图翻译自己的设置照旧存着")
        self.assertEqual(config.vision_service(c).model, "gemma4:27b")
        dlg.v_same.setChecked(False)
        self.assertEqual((dlg.v_base.text(), dlg.v_model.text(), dlg.v_key.text()),
                         ("http://127.0.0.1:11434", "qwen-vl", ""), "取消勾选：换回它自己的")
        self.assertTrue(dlg.v_model.isEnabled())
        self.assertFalse(dlg.collect().vision.use_llm)
        dlg.close()
        cfg = AppConfig()
        cfg.vision.use_llm, cfg.vision.model, cfg.llm.model = True, "qwen-vl", "gemma4:31b"
        dlg = SettingsDialog(cfg)                     # 打开时已经勾着
        self.assertTrue(dlg.v_same.isChecked())
        self.assertEqual(dlg.v_model.text(), "gemma4:31b")
        self.assertFalse(dlg.v_model.isEnabled())
        self.assertEqual(dlg.collect().vision.model, "qwen-vl")
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
