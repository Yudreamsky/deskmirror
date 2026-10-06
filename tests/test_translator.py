"""设置页“获取模型列表”：成功时给出模型名，失败时说清原因（本地假服务，不连外网）。"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror.config import LlmConfig
from deskmirror.translator import list_models


class _Fake(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.server.agents.append(self.headers.get("User-Agent", ""))
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": "gemma4:12b"}, {"name": "aya:8b"}]})
        elif self.path in ("/models", "/v1/models"):
            if self.headers.get("Authorization") != "Bearer good":
                self._send(401, {"error": {"message": "Authentication Fails"}})
            else:
                self._send(200, {"object": "list", "data": [{"id": "deepseek-flash"}, {"id": "deepseek-chat"}]})
        elif self.path == "/bad/models":
            self._send(200, "not a list")
        else:
            self._send(404, {"error": "not found"})

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ListModelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
        cls.srv.agents = []
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def cfg(self, protocol: str, base: str, key: str = "") -> LlmConfig:
        return LlmConfig(protocol=protocol, base_url=base, api_key=key)

    def test_openai_compatible(self) -> None:
        self.assertEqual(list_models(self.cfg("openai", self.base, "good")), (["deepseek-chat", "deepseek-flash"], ""))
        self.assertEqual(list_models(self.cfg("openai", self.base + "/v1/", "good"))[0], ["deepseek-chat", "deepseek-flash"])
        self.assertTrue(self.srv.agents[-1].startswith("DeskMirror/"), "如实标明客户端身份")

    def test_ollama(self) -> None:
        self.assertEqual(list_models(self.cfg("ollama", self.base)), (["aya:8b", "gemma4:12b"], ""))

    def test_reasons(self) -> None:
        self.assertIn("还没填 API Key", list_models(self.cfg("openai", self.base))[1])
        self.assertIn("密钥不对", list_models(self.cfg("openai", self.base, "wrong"))[1])
        self.assertIn("404", list_models(self.cfg("openai", self.base + "/nothing", "good"))[1])
        self.assertIn("不是模型列表", list_models(self.cfg("openai", self.base + "/bad", "good"))[1])
        self.assertIn("先填服务地址", list_models(self.cfg("openai", "  "))[1])
        free = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
        port = free.server_address[1]
        free.server_close()                       # 这个端口现在没人监听
        self.assertIn("连不上", list_models(self.cfg("openai", f"http://127.0.0.1:{port}", "good"))[1])


if __name__ == "__main__":
    unittest.main()
