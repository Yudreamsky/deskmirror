"""命令行改设置（deskmirror config …）：用临时配置文件，不碰真实设置；API Key 用假的。"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest

from deskmirror import cli, config, i18n

FAKE_KEY = "sk-test-FAKE-0000-1111"


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._dir.name) / "deskmirror.json"
        self._env = os.environ.get("DESKMIRROR_CONFIG")
        os.environ["DESKMIRROR_CONFIG"] = str(self.path)
        cfg = config.AppConfig()
        cfg.ui_lang = "zh"
        config.save(cfg)
        self._running = cli._running
        cli._running = lambda: False

    def tearDown(self) -> None:
        cli._running = self._running
        if self._env is None:
            os.environ.pop("DESKMIRROR_CONFIG", None)
        else:
            os.environ["DESKMIRROR_CONFIG"] = self._env
        self._dir.cleanup()
        i18n.set_ui_lang("zh")

    def run_cli(self, *args: str, stdin: str | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        old_stdin = cli.sys.stdin
        if stdin is not None:
            cli.sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(list(args))
        finally:
            cli.sys.stdin = old_stdin
        return code, out.getvalue(), err.getvalue()

    def json_cli(self, *args: str, stdin: str | None = None) -> tuple[int, dict]:
        code, out, _err = self.run_cli(*args, "--json", stdin=stdin)
        self.assertTrue(out.isascii(), "JSON 只用 ASCII：任何代码页下都不乱码")
        return code, json.loads(out)

    def test_set_and_get(self) -> None:
        code, res = self.json_cli("config", "set", "llm.model", "qwen3:8b", "scope.mode", "window")
        self.assertEqual(code, 0)
        self.assertEqual(res["changed"], {"llm.model": "qwen3:8b", "scope.mode": "window"})
        self.assertEqual(self.json_cli("config", "get", "llm.model")[1]["value"], "qwen3:8b")
        saved = config.load()
        self.assertEqual((saved.llm.model, saved.scope.mode), ("qwen3:8b", "window"))

    def test_bad_values_are_rejected_not_clamped(self) -> None:
        for args, needle in ((("llm.concurrency", "99"), "1 到 8"), (("llm.protocol", "foo"), "ollama, openai"),
                             (("hotkeys.peek", "Ctrl+Q+W"), "只能有一个主键"), (("memory.enabled", "maybe"), "true"),
                             (("style.border_color", "blue"), "#RRGGBB"), (("llm.base_url", "api.x.com"), "http"),
                             (("llm.timeout_s", "abc"), "数字")):
            code, out, err = self.run_cli("config", "set", *args)
            self.assertEqual(code, 1, args)
            self.assertIn(needle, err, args)
        self.assertEqual(config.load().llm.concurrency, 1, "出错时什么都不改")

    def test_unknown_and_read_only_keys(self) -> None:
        code, _out, err = self.run_cli("config", "get", "llm.modle")
        self.assertEqual(code, 1)
        self.assertIn("llm.model", err, "猜出拼错的名字")
        code, _out, err = self.run_cli("config", "set", "mirror_rect", "[1,2,3,4]")
        self.assertEqual(code, 1)
        self.assertIn("拖魔镜", err)
        code, res = self.json_cli("config", "set", "usage.chars", "3")
        self.assertEqual((code, res["ok"]), (1, False))

    def test_api_key_from_stdin_is_encrypted_and_masked(self) -> None:
        code, out, _err = self.run_cli("config", "set", "llm.api_key", "-", stdin=FAKE_KEY + "\n")
        self.assertEqual(code, 0)
        self.assertNotIn(FAKE_KEY, out)
        self.assertIn("sk-…1111", out)
        self.assertNotIn(FAKE_KEY, self.path.read_text(encoding="utf-8"), "存盘时加密")
        self.assertEqual(config.load().llm.api_key, FAKE_KEY)
        for args in (("config", "get", "llm.api_key"), ("config", "list"), ("config", "keys")):
            self.assertNotIn(FAKE_KEY, self.run_cli(*args)[1], args)
            self.assertNotIn(FAKE_KEY, self.run_cli(*args, "--json")[1], args)

    def test_lists_take_commas(self) -> None:
        self.json_cli("config", "set", "scope.exclude_apps", "a.exe，b.exe, c.exe")
        self.assertEqual(config.load().scope.exclude_apps, ["a.exe", "b.exe", "c.exe"])
        self.json_cli("config", "set", "scope.exclude_titles", '["网银", "Bank"]')
        self.assertEqual(config.load().scope.exclude_titles, ["网银", "Bank"])

    def test_reset(self) -> None:
        self.json_cli("config", "set", "track.stable_ms", "500")
        code, res = self.json_cli("config", "reset", "track.stable_ms")
        self.assertEqual((code, res["changed"]), (0, {"track.stable_ms": 350}))

    def test_service_presets(self) -> None:
        code, res = self.json_cli("service")
        self.assertEqual(code, 0)
        self.assertIn("deepseek", [s["id"] for s in res["services"]])
        self.assertTrue(next(s for s in res["services"] if s["id"] == "ollama")["current"])
        code, _out, _err = self.run_cli("service", "deepseek")
        self.assertEqual(code, 0)
        llm = config.load().llm
        self.assertEqual((llm.protocol, llm.base_url, llm.model), ("openai", "https://api.deepseek.com", "deepseek-chat"))
        self.assertGreaterEqual(llm.concurrency, 2)
        self.json_cli("service", "openai")
        self.assertEqual(config.load().llm.model, "", "没有默认模型的服务：不留着上一家的模型名")
        self.assertEqual(self.json_cli("service", "nosuch")[0], 1)

    def test_glossary(self) -> None:
        self.json_cli("glossary", "add", "Port Lumen", "卢门港")
        self.json_cli("glossary", "add", "Mina", "米娜", "--app", "game.exe")
        self.json_cli("glossary", "add", "port lumen", "卢门")            # 同一个词再加：改译法
        terms = self.json_cli("glossary", "list")[1]["glossary"]
        self.assertEqual(terms, [{"src": "Mina", "dst": "米娜", "app": "game.exe"},
                                 {"src": "port lumen", "dst": "卢门", "app": ""}])
        self.assertEqual(self.json_cli("glossary", "remove", "Mina")[0], 1, "只删同一个程序的")
        self.assertEqual(self.json_cli("glossary", "remove", "Mina", "--app", "game.exe")[0], 0)
        self.assertEqual(len(config.load().glossary), 1)

    def test_every_setting_is_documented(self) -> None:
        code, res = self.json_cli("config", "keys")
        self.assertEqual(code, 0)
        keys = {k["key"]: k for k in res["keys"]}
        self.assertEqual(set(keys), set(cli.settable_keys()))
        self.assertEqual([k for k, v in keys.items() if not v["description"]], [], "每项设置都有说明")
        self.assertEqual(keys["llm.concurrency"]["range"], [1, 8])
        self.assertIn("openai", keys["llm.protocol"]["choices"])
        self.assertTrue(keys["ocr.device"]["restart"])

    def test_usage_and_unknown_command(self) -> None:
        code, out, _err = self.run_cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("config set", out)
        self.assertEqual(self.run_cli("nosuch")[0], 2)
        self.assertEqual(self.json_cli("version")[1]["version"], cli.__version__)


if __name__ == "__main__":
    unittest.main()
