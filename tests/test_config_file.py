"""设置文件存盘：每次都留一份一模一样的备份；配置文件坏了（断电、死机时正在存，或者被改坏了）就用备份恢复。
用临时配置文件，不碰真实设置；API Key 用假的。"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

from deskmirror import config, i18n

FAKE_KEY = "sk-test-FAKE-2222-3333"


class ConfigFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._dir.name)
        self.path = self.dir / "deskmirror.json"
        self._env = os.environ.get("DESKMIRROR_CONFIG")
        os.environ["DESKMIRROR_CONFIG"] = str(self.path)
        i18n.set_ui_lang("zh")
        cfg = config.AppConfig()
        cfg.target_lang = "ja"
        cfg.llm.api_key = FAKE_KEY
        config.save(cfg)

    def tearDown(self) -> None:
        if self._env is None:
            os.environ.pop("DESKMIRROR_CONFIG", None)
        else:
            os.environ["DESKMIRROR_CONFIG"] = self._env
        config.load_result = "ok"
        self._dir.cleanup()

    def test_save_keeps_an_identical_backup(self) -> None:
        bak = self.dir / "deskmirror.bak.json"
        self.assertEqual(config.backup_path(), bak)
        self.assertEqual(bak.read_bytes(), self.path.read_bytes())
        self.assertNotIn(FAKE_KEY, self.path.read_text(encoding="utf-8"))      # 密钥照样加密存
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["deskmirror.bak.json", "deskmirror.json"])

    def test_damaged_file_comes_back_from_backup(self) -> None:
        for damage in (b"", b"\x00" * 300, b'{"target_lang": "ja", "llm": {', b"[1, 2]"):
            with self.subTest(damage=damage[:12]):
                self.path.write_bytes(damage)
                with self.assertLogs("deskmirror.config", "WARNING"):
                    cfg = config.load()
                self.assertEqual(config.load_result, "backup")
                self.assertEqual(cfg.target_lang, "ja")
                self.assertEqual(cfg.llm.api_key, FAKE_KEY)
                self.assertIn("备份恢复", config.load_note())
                self.assertEqual((self.dir / "deskmirror.broken.json").read_bytes(), damage)   # 坏的留着
                config.save(cfg)                    # 魔镜接着照常存：配置文件又是好的了
                self.assertEqual(config.load().target_lang, "ja")
                self.assertEqual(config.load_result, "ok")

    def test_damaged_without_backup_uses_defaults(self) -> None:
        config.backup_path().unlink()
        self.path.write_bytes(b"\x00" * 64)
        with self.assertLogs("deskmirror.config", "WARNING"):
            cfg = config.load()
        self.assertEqual(config.load_result, "defaults")
        self.assertEqual(cfg.target_lang, config.AppConfig().target_lang)
        self.assertIn("deskmirror.broken.json", config.load_note())

    def test_deleted_on_purpose_starts_fresh(self) -> None:
        self.path.unlink()                          # 用户删了配置文件想从头来：不去翻备份
        cfg = config.load()
        self.assertEqual(config.load_result, "ok")
        self.assertEqual(config.load_note(), "")
        self.assertEqual(cfg.target_lang, config.AppConfig().target_lang)


if __name__ == "__main__":
    unittest.main()
