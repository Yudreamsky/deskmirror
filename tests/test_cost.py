"""省钱相关（#6 #7）：读回服务报的 token 用量、报不了时估算；离开时只翻镜框里的；一天的 token 用到上限就停；
命令行改设置（#4）；版本号比较（#5）。本地假服务，不连外网。"""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import deskmirror  # noqa: E402,F401  预加载 DLL
from deskmirror import cli, config, textutil, updater, usagelog  # noqa: E402
from deskmirror.app import _short_num  # noqa: E402
from deskmirror.config import LlmConfig  # noqa: E402
from deskmirror.translator import ServiceError, Usage, estimate_tokens, make_client, stream_translate  # noqa: E402

from tests.test_engine import add_block, make_engine  # noqa: E402
from tests.test_pixels import text_page  # noqa: E402


class _FakeChat(BaseHTTPRequestHandler):
    """/usage/：最后一段带 usage（OpenAI 兼容）；/plain/：不报用量；/ollama/api/chat：Ollama 原生；/poor/：余额不足。"""

    def log_message(self, *args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.payloads.append((self.path, body))
        if self.path.startswith("/poor/"):
            data = json.dumps({"error": {"message": "Insufficient Balance"}}).encode()
            self.send_response(402)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.end_headers()
        if self.path.startswith("/ollama/"):
            for obj in ({"message": {"content": "[1] 你好\n"}, "done": False},
                        {"message": {"content": "[2] 打开设置"}, "done": True, "prompt_eval_count": 321,
                         "eval_count": 12}):
                self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
            return
        for piece in ("[1] 你好\n", "[2] 打开设置"):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
        if self.path.startswith("/usage/"):
            last = {"choices": [], "usage": {"prompt_tokens": 456, "completion_tokens": 9, "total_tokens": 465,
                                             "prompt_cache_hit_tokens": 384, "prompt_cache_miss_tokens": 72}}
            self.wfile.write(f"data: {json.dumps(last)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


class UsageTest(unittest.TestCase):
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

    def run_batch(self, path: str, protocol: str = "openai") -> tuple[Usage, dict]:
        cfg = LlmConfig(protocol=protocol, base_url=self.base + path, model="m", api_key="k")
        got: dict[int, str] = {}
        with make_client(cfg) as client:
            usage = stream_translate(cfg, "zh-Hans", ["Hello", "Open settings"], lambda i, t: got.__setitem__(i, t),
                                     client, threading.Event())
        return usage, got

    def test_reported_usage(self) -> None:
        usage, got = self.run_batch("/usage")
        self.assertEqual(got, {0: "你好", 1: "打开设置"})
        self.assertEqual((usage.tokens_in, usage.tokens_out, usage.exact, usage.cached), (456, 9, True, 384))
        body =[b for p, b in self.srv.payloads if p.startswith("/usage/")][-1]
        self.assertEqual(body["stream_options"], {"include_usage": True}, "要请服务在最后报用量")

    def test_ollama_counts(self) -> None:
        usage, got = self.run_batch("/ollama", protocol="ollama")
        self.assertEqual(got, {0: "你好", 1: "打开设置"})
        self.assertEqual((usage.tokens_in, usage.tokens_out, usage.exact), (321, 12, True))

    def test_estimated_when_not_reported(self) -> None:
        usage, _ = self.run_batch("/plain")
        self.assertFalse(usage.exact)
        self.assertGreater(usage.tokens_in, 100, "系统提示词也算输入")
        self.assertGreater(usage.tokens_out, 0)

    def test_insufficient_balance(self) -> None:
        with self.assertRaises(ServiceError) as cm:
            self.run_batch("/poor")
        self.assertIn("402", str(cm.exception))
        self.assertFalse(cm.exception.retryable, "余额不足重试也没用：停下等用户充值")

    def test_estimate(self) -> None:
        self.assertEqual(estimate_tokens("你好世界"), 4)
        self.assertEqual(estimate_tokens("abcdefgh"), 2)
        self.assertEqual(_short_num(950), "950")
        self.assertEqual(_short_num(12345), "12.3k")
        self.assertEqual(_short_num(2_500_000), "2.50M")


class EngineGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.logdir = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(usagelog, "log_dir", lambda: Path(self.logdir.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.logdir.cleanup)
        page = text_page(3000, 900, 21)
        self.page = page
        self.eng, _m, _win, self.sc = make_engine(page[0:1200])
        self.sent = []

        class Pool:
            def submit(pool, batch) -> None:  # noqa: N805
                self.sent.append(batch)

        self.eng.pool = Pool()

    def block(self, y: int, text: str):
        b = add_block(self.eng, self.sc, (10, y, 400, y + 22), self.page[y:y + 22, 10:400])
        b.text, b.key, b.state = text, textutil.cache_key(text), "pending"
        self.eng.by_key[b.key].add(b.bid)
        return b

    def test_frugal_only_inside_mirror(self) -> None:
        eng = self.eng
        eng.set_mirrors([(0, 0, 500, 300)])
        inside, outside = self.block(100, "Inside the mirror"), self.block(900, "Far below the mirror")
        eng.frugal = True
        self.assertTrue(eng._in_scope(inside, inside.screen_rect()))
        self.assertFalse(eng._in_scope(outside, outside.screen_rect()), "离开时不预译镜框外")
        eng.frugal = False
        self.assertTrue(eng._in_scope(outside, outside.screen_rect()))

    def test_budget_stops_new_requests(self) -> None:
        eng = self.eng
        self.block(100, "Some text to translate")
        eng.service["budget"] = True
        eng._schedule_translation()
        self.assertEqual(self.sent, [], "用到上限后不再发请求")
        eng.service["budget"] = False
        eng._schedule_translation()
        self.assertEqual(len(self.sent), 1)

    def test_tokens_counted(self) -> None:
        eng = self.eng
        self.block(100, "Some text to translate")
        eng._schedule_translation()
        bid = self.sent[-1].batch_id
        eng._on_translation(("segment", bid, 0, "要翻译的一些文字"))
        eng._on_translation(("batch_done", bid, None, 0.4, Usage(500, 20, True, 448)))
        self.assertEqual((eng.service["tok_in"], eng.service["tok_out"], eng.service["tok_cached"],
                          eng.service["tok_est"]), (500, 20, 448, False))
        recs = usagelog.read()
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["in"], recs[0]["out"], recs[0]["cached"], recs[0]["segments"]), (500, 20, 448, 1))
        self.assertNotIn("Some text", json.dumps(recs[0]), "用量日志里不能有屏幕上的字")
        s = usagelog.summarize(recs)
        self.assertEqual((s["requests"], s["cache_hit_rate"], list(s["by_batch_chars"])), (1, 0.896, ["<50"]))

    def test_small_batches_wait_while_busy(self) -> None:
        eng = self.eng
        eng.cfg.llm.concurrency = 5
        self.block(100, "First line")
        eng._schedule_translation()
        self.assertEqual(len(self.sent), 1, "没有请求在途：立刻发")
        late = self.block(200, "A second line")
        eng._schedule_translation()
        self.assertEqual(len(self.sent), 1, "有请求在途、新文字又少：等一下凑一批")
        self.block(300, "And a third line")
        late.created -= 1.0                       # 等够了
        for b in eng.blocks.values():
            b.created = min(b.created, late.created)
        eng._schedule_translation()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[-1].texts, ["A second line", "And a third line"], "凑成了一批")


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.path)
        self.env = mock.patch.dict(os.environ, {"DESKMIRROR_CONFIG": self.path})
        self.env.start()

    def tearDown(self) -> None:
        from deskmirror import i18n
        i18n.set_ui_lang("zh")          # 命令行按配置换了界面语言：别影响后面的测试
        self.env.stop()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def run_cli(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 2
                buf.write(str(e.code))
        return code, buf.getvalue()

    def test_set_get_reset(self) -> None:
        self.assertEqual(self.run_cli("config", "set", "llm.model", "deepseek-chat")[0], 0)
        self.assertEqual(config.load().llm.model, "deepseek-chat")
        code, out = self.run_cli("config", "set", "llm.concurrency", "99", "--json")
        self.assertNotEqual(code, 0, "超出范围直接报错，不悄悄改成别的值")
        self.assertIn("8", json.loads(out)["error"], "说清楚允许的范围")
        self.assertEqual(config.load().llm.concurrency, 1)
        self.run_cli("config", "set", "guard.show_meter", "off")
        self.assertFalse(config.load().guard.show_meter)
        self.run_cli("config", "set", "scope.exclude_apps", "a.exe, b.exe")
        self.assertEqual(config.load().scope.exclude_apps, ["a.exe", "b.exe"])
        self.run_cli("config", "reset", "llm.concurrency")
        self.assertEqual(config.load().llm.concurrency, 1)
        self.assertEqual(json.loads(self.run_cli("config", "get", "llm.model", "--json")[1])["value"], "deepseek-chat")

    def test_secret_never_printed(self) -> None:
        with mock.patch.dict(os.environ, {"MY_KEY": "sk-secret-123"}):
            code, out = self.run_cli("config", "set", "llm.api_key", "--env", "MY_KEY")
        self.assertEqual(code, 0)
        self.assertNotIn("sk-secret", out)
        self.assertEqual(config.load().llm.api_key, "sk-secret-123")
        self.assertNotIn("sk-secret", Path(self.path).read_text(encoding="utf-8"), "存盘时加密")
        self.assertNotIn("sk-secret", self.run_cli("config", "list")[1])
        schema = json.loads(self.run_cli("config", "schema")[1])["keys"]
        self.assertEqual(next(s for s in schema if s["key"] == "llm.api_key")["value"], cli.mask("sk-secret-123"))
        self.assertNotIn("secret", cli.mask("sk-secret-123"))

    def test_rejects(self) -> None:
        self.assertNotEqual(self.run_cli("config", "set", "usage.requests", "3")[0], 0, "用量由程序自己记")
        code, out = self.run_cli("config", "set", "no.such", "1", "--json")
        self.assertNotEqual(code, 0)
        self.assertFalse(json.loads(out)["ok"])
        self.assertIn("no.such", json.loads(out)["error"])
        self.assertNotEqual(self.run_cli("config", "set", "guard.show_meter", "maybe")[0], 0)


class UpdaterTest(unittest.TestCase):
    def test_version_compare(self) -> None:
        self.assertGreater(updater.parse_version("1.2.0"), updater.parse_version("1.1.10"))
        self.assertEqual(updater.parse_version("v1.1.1"), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
