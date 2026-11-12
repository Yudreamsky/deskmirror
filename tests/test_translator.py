"""翻译服务接口（本地假服务，不连外网）：设置页“获取模型列表”给出模型名或说清原因；
OpenAI 兼容接口默认关掉模型的“思考”，不认这个参数的服务自动去掉重发。"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror.config import LlmConfig
from deskmirror.translator import SegmentParser, ServiceError, list_models, make_client, stream_translate


class _Fake(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.server.agents.append(self.headers.get("User-Agent", ""))
        self.server.auth.append(self.headers.get("Authorization"))
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


class _FakeChat(BaseHTTPRequestHandler):
    """/ok/ 什么参数都收；/strict/ 不认 thinking 参数（像 OpenAI 官方那样报 400）；/broken/ 总是报 400。"""

    def log_message(self, *args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.payloads.append((self.path, body))
        if self.path.startswith("/broken/") or (self.path.startswith("/strict/") and "thinking" in body):
            msg = "Model Not Exist" if self.path.startswith("/broken/") else "Unrecognized request argument supplied: thinking"
            data = json.dumps({"error": {"message": msg}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ("[1] 你好", "，世界\n[2] 打开", "设置"):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


class ThinkingSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeChat)
        cls.srv.payloads = []
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def translate(self, path: str, **kw) -> dict[int, str]:
        cfg = LlmConfig(protocol="openai", base_url=self.base + path, model="deepseek-flash", api_key="k", **kw)
        got: dict[int, str] = {}
        with make_client(cfg) as client:
            stream_translate(cfg, "zh-Hans", ["Hello, world!", "Open settings"], lambda i, t: got.__setitem__(i, t),
                             client, threading.Event())
        return got

    def sent(self, path: str) -> list[dict]:
        return [body for p, body in self.srv.payloads if p.startswith(path)]

    def test_thinking_disabled_by_default(self) -> None:
        self.assertEqual(self.translate("/ok"), {0: "你好，世界", 1: "打开设置"})
        self.assertEqual(self.sent("/ok/")[-1]["thinking"], {"type": "disabled"})

    def test_can_keep_thinking(self) -> None:
        self.translate("/ok2", disable_thinking=False)
        self.assertNotIn("thinking", self.sent("/ok2/")[-1])

    def test_service_without_the_parameter(self) -> None:
        self.assertEqual(self.translate("/strict"), {0: "你好，世界", 1: "打开设置"})
        first, second = self.sent("/strict/")
        self.assertIn("thinking", first)
        self.assertNotIn("thinking", second)
        self.translate("/strict")                 # 记住了：之后不再先报错再重发
        self.assertEqual(len(self.sent("/strict/")), 3)
        self.assertNotIn("thinking", self.sent("/strict/")[-1])

    def test_other_errors_still_reported(self) -> None:
        with self.assertRaises(ServiceError):
            self.translate("/broken")
        self.assertEqual(len(self.sent("/broken/")), 2)
        with self.assertRaises(ServiceError):
            self.translate("/broken")
        self.assertIn("thinking", self.sent("/broken/")[2], "别的错误不能让它以为是不认 thinking 参数")


class ListModelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
        cls.srv.agents, cls.srv.auth = [], []
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
        self.assertIsNone(self.srv.auth[-1])
        list_models(self.cfg("ollama", self.base, "k"))          # Ollama 云端：带上密钥
        self.assertEqual(self.srv.auth[-1], "Bearer k")

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


class _FakeOllama(BaseHTTPRequestHandler):
    """Ollama 原生 /api/chat：记下请求头和请求体；/key/ 下要 Bearer good（像 ollama.com 那样，没密钥、密钥不对都回 401）。"""

    def log_message(self, *args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append((self.path, self.headers.get("Authorization"), body))
        if self.path.startswith("/key/") and self.headers.get("Authorization") != "Bearer good":
            data = b'{"error":"Unauthorized"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for piece in ("[1] 你好，世界\n", "[2] 打开设置"):
            self.wfile.write((json.dumps({"message": {"content": piece}, "done": False}, ensure_ascii=False) + "\n").encode())
        self.wfile.write(b'{"message":{"content":""},"done":true,"prompt_eval_count":50,"eval_count":9}\n')


class OllamaKeyTest(unittest.TestCase):
    """Ollama 原生接口带 API Key（ollama.com 云端）；本机的 Ollama 照旧。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
        cls.srv.seen = []
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def translate(self, path: str, key: str) -> dict[int, str]:
        cfg = LlmConfig(protocol="ollama", base_url=self.base + path, model="gemma4:31b", api_key=key)
        got: dict[int, str] = {}
        with make_client(cfg) as client:
            usage = stream_translate(cfg, "zh-Hans", ["Hello, world!", "Open settings"],
                                     lambda i, t: got.__setitem__(i, t), client, threading.Event())
        self.assertEqual((usage.tokens_in, usage.tokens_out, usage.exact), (50, 9, True))
        return got

    def test_key_sent(self) -> None:
        self.assertEqual(self.translate("/key", "good"), {0: "你好，世界", 1: "打开设置"})
        _path, auth, body = self.srv.seen[-1]
        self.assertEqual(auth, "Bearer good")
        self.assertEqual((body["keep_alive"], body["options"]["num_ctx"]), ("30m", 4096),
                         "不是 ollama.com 的 Ollama（本机、局域网）照旧带 num_ctx、keep_alive")
        self.assertIs(body["think"], False)
        self.translate("/open", "")
        self.assertIsNone(self.srv.seen[-1][1], "没填密钥就不带")

    def test_key_missing_or_wrong(self) -> None:
        with self.assertRaises(ServiceError) as cm:
            self.translate("/key", "")
        self.assertIn("要 API Key", str(cm.exception))
        self.assertFalse(cm.exception.retryable)
        with self.assertRaises(ServiceError) as cm:
            self.translate("/key", "wrong")
        self.assertIn("密钥无效", str(cm.exception))

    def test_cloud_request(self) -> None:
        from deskmirror.config import is_ollama_cloud
        from deskmirror.translator import _ollama_chat
        for url in ("https://ollama.com", "https://ollama.com/", "ollama.com", "https://api.ollama.com"):
            self.assertTrue(is_ollama_cloud(url), url)
        for url in ("http://127.0.0.1:11434", "https://notollama.com", "https://api.deepseek.com", ""):
            self.assertFalse(is_ollama_cloud(url), url)
        cfg = LlmConfig(protocol="ollama", base_url="https://ollama.com", model="gemma4:31b", api_key="k")
        payload, headers = _ollama_chat(cfg, "https://ollama.com", [{"role": "user", "content": "hi"}])
        self.assertEqual(headers, {"Authorization": "Bearer k"})
        self.assertNotIn("keep_alive", payload, "云端用不着让模型留在显存里")
        self.assertEqual(payload["options"], {"temperature": cfg.temperature})
        self.assertIs(payload["think"], False)

    def test_cloud_model_name_hint(self) -> None:
        import httpx

        from deskmirror.translator import _http_error
        resp = httpx.Response(404, json={"error": "model 'gemma4:31b-cloud' not found"})
        self.assertIn("gemma4:31b", str(_http_error(resp, True, ollama_cloud=True)))
        self.assertIn("不带 cloud", str(_http_error(resp, True, ollama_cloud=True)))
        self.assertNotIn("不带 cloud", str(_http_error(resp)))


class OddReplyTest(unittest.TestCase):
    """服务回的不是该有的样子：说清楚原因，不能冒出没接住的错误（界面上只会显示“内部错误”，命令行是一屏调用栈）。"""

    def _translate(self, cfg: LlmConfig, handler):
        import httpx
        got: dict[int, str] = {}
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            usage = stream_translate(cfg, "zh-Hans", ["Hello"], got.__setitem__, client, threading.Event())
        return got, usage

    def test_error_body_is_a_list_or_text(self) -> None:
        import httpx
        api = LlmConfig(protocol="openai", base_url="http://x", model="m", api_key="k")
        # Gemini 的 OpenAI 兼容接口把错误包在数组里；有的网关只回一句话，或者 null
        for body, want in (([{"error": {"message": "API key not valid"}}], "API key not valid"), ("boom", "boom"),
                           ([], ""), (None, "")):
            with self.assertRaises(ServiceError) as cm:
                self._translate(api, lambda req, body=body: httpx.Response(500, json=body))
            self.assertIn("HTTP 500", str(cm.exception))
            self.assertEqual(cm.exception.detail, want)

    def test_ollama_address_answers_with_a_web_page(self) -> None:
        import httpx
        ollama = LlmConfig(protocol="ollama", base_url="http://x", model="m")
        for text in ("<html>\n<body>Sign in</body>\n</html>\n", '["not", "an", "object"]\n', '"text"\n'):
            with self.assertRaises(ServiceError) as cm:
                self._translate(ollama, lambda req, text=text: httpx.Response(200, text=text))
            self.assertIn("接入方式", str(cm.exception))

    def test_openai_stream_with_odd_lines(self) -> None:
        import httpx
        api = LlmConfig(protocol="openai", base_url="http://x", model="m", api_key="k")
        lines = ['data: "keep-alive"', "data: [1, 2]", "data: not json",
                 'data: {"choices": [{"delta": {"content": "[1] 你好"}}]}', "data: [DONE]"]
        got, _usage = self._translate(api, lambda req: httpx.Response(200, text="\n\n".join(lines) + "\n\n"))
        self.assertEqual(got, {0: "你好"})


class ThinkTagTest(unittest.TestCase):
    """模型把思考写在 <think>…</think> 里：流式返回时这个标记可能被切成两截。"""

    @staticmethod
    def _feed(pieces: list[str]) -> dict[int, str]:
        out: dict[int, str] = {}
        p = SegmentParser(2, out.__setitem__)
        for piece in pieces:
            p.feed_raw(piece)
        p.close()
        return out

    def test_tag_split_between_chunks(self) -> None:
        want = {0: "你好", 1: "世界"}
        text = "<think>let me see</think>[1] 你好\n[2] 世界\n"
        self.assertEqual(self._feed([text]), want)
        for cut in range(1, len("<think>")):                 # "<" + "think>…"、"<t" + "hink>…"……
            self.assertEqual(self._feed([text[:cut], text[cut:]]), want, cut)
        self.assertEqual(self._feed(list(text)), want, "一个字一个字地来")

    def test_text_that_only_looks_like_the_tag(self) -> None:
        self.assertEqual(self._feed(["[1] a <", "b> c\n[2] 1 <", " 2"]), {0: "a <b> c", 1: "1 < 2"})
        self.assertEqual(self._feed(["[1] x\n[2] 3 <"]), {0: "x", 1: "3 <"}, "结尾的 < 不能丢")
        self.assertEqual(self._feed(["[1] x\n[2] y <th"]), {0: "x", 1: "y <th"})


class ServiceDetailTest(unittest.TestCase):
    def test_service_wording_stays_out_of_the_log(self) -> None:
        # 服务自己写的说明可能带着请求里的原文：界面上照常显示，日志用的 brief 里没有
        import httpx

        from deskmirror.translator import _http_error
        resp = httpx.Response(400, json={"error": {"message": "Input 'Tickets are sold at the pier' is too long"}})
        err = _http_error(resp)
        self.assertIn("Tickets are sold", str(err))
        self.assertIn("HTTP 400", err.brief)
        self.assertNotIn("Tickets are sold", err.brief)
        plain = ServiceError("连不上翻译服务")
        self.assertEqual(plain.brief, "连不上翻译服务")


if __name__ == "__main__":
    unittest.main()
