"""开机自动启动（autostart.py）：写、删启动项，任务管理器里禁用了算没开，程序挪了地方改路径，命令行能改。
只动注册表里一个临时的测试键，不碰真的启动项。"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
import winreg
from unittest import mock

from deskmirror import autostart, cli, config
from tests import test_cli

TEST_KEY = r"Software\DeskMirrorTest"


def _wipe() -> None:
    for sub in (r"\StartupApproved\Run", r"\StartupApproved", r"\Run", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY + sub)
        except OSError:
            pass


class _ScratchKeys(unittest.TestCase):
    def setUp(self) -> None:
        _wipe()
        for name, sub in (("RUN_KEY", r"\Run"), ("APPROVED_KEY", r"\StartupApproved\Run")):
            p = mock.patch.object(autostart, name, TEST_KEY + sub)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(_wipe)

    def _approved(self, first: int) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, autostart.APPROVED_KEY) as k:
            winreg.SetValueEx(k, autostart.NAME, 0, winreg.REG_BINARY, bytes([first]) + bytes(11))


class AutostartTest(_ScratchKeys):
    def test_command_of_source_install(self) -> None:
        cmd = autostart.command()
        self.assertTrue(cmd.endswith(" --autostart"))
        self.assertIn("pythonw.exe", cmd, "不弹黑框")
        self.assertIn("autostart.pyw", cmd)
        for p in autostart._paths(cmd):
            self.assertTrue(p.exists(), p)

    def test_command_of_packaged_exe(self) -> None:
        for exe in ("DeskMirror.exe", "DeskMirrorCLI.exe"):          # 命令行改设置时也写界面程序
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", r"D:\Apps\DeskMirror" + "\\" + exe):
                self.assertEqual(autostart.command(), r'"D:\Apps\DeskMirror\DeskMirror.exe" --autostart', exe)

    def test_enable_disable(self) -> None:
        self.assertFalse(autostart.enabled())
        autostart.set_enabled(True)
        self.assertTrue(autostart.enabled())
        self.assertEqual(autostart.current(), autostart.command())
        autostart.set_enabled(False)
        self.assertFalse(autostart.enabled())
        self.assertEqual(autostart.current(), "")
        autostart.set_enabled(False)                       # 本来就没有：不报错

    def test_disabled_in_task_manager_counts_as_off(self) -> None:
        autostart.set_enabled(True)
        self._approved(3)
        self.assertFalse(autostart.enabled(), "任务管理器里禁用了")
        self._approved(2)
        self.assertTrue(autostart.enabled())
        self._approved(3)
        autostart.set_enabled(True)
        self.assertTrue(autostart.enabled(), "在设置里重新打开：清掉禁用")

    def test_refresh_after_moving(self) -> None:
        self.assertFalse(autostart.refresh(), "没开：不写")
        autostart._write(r'"X:\gone\DeskMirror.exe" --autostart')
        self._approved(3)
        self.assertTrue(autostart.refresh(), "指向的文件没了：改成现在的路径")
        self.assertEqual(autostart.current(), autostart.command())
        self.assertFalse(autostart.enabled(), "任务管理器里的禁用照旧")
        with tempfile.TemporaryDirectory() as d:
            other = pathlib.Path(d) / "DeskMirror.exe"
            other.write_bytes(b"")
            autostart._write(f'"{other}" --autostart')
            self.assertFalse(autostart.refresh(), "指向另一个还在的安装：不抢")
            self.assertEqual(autostart.current(), f'"{other}" --autostart')


class MainEntryTest(unittest.TestCase):
    def test_autostart_flag_opens_the_app_not_the_cli(self) -> None:
        src = pathlib.Path(autostart.__file__).with_name("__main__.py").read_text(encoding="utf-8")
        self.assertIn('if a != "--autostart"', src)


class CliAutostartTest(_ScratchKeys):
    # 借用命令行测试的临时配置和调用办法（不继承它的测试）
    run_cli = test_cli.CliTest.run_cli
    json_cli = test_cli.CliTest.json_cli

    def setUp(self) -> None:
        test_cli.CliTest.setUp(self)
        self.addCleanup(test_cli.CliTest.tearDown, self)
        super().setUp()

    def test_config_set_autostart(self) -> None:
        before = self.path.read_bytes()
        code, res = self.json_cli("config", "set", "autostart", "true")
        self.assertEqual(code, 0)
        self.assertEqual(res["changed"], {"autostart": True})
        self.assertTrue(autostart.enabled())
        self.assertEqual(self.path.read_bytes(), before, "不写配置文件（运行中的魔镜不用重新载入）")
        self.assertIs(self.json_cli("config", "get", "autostart")[1]["value"], True)
        self.assertIn("autostart", self.json_cli("config", "list")[1]["settings"])
        keys = {k["key"]: k for k in self.json_cli("config", "keys")[1]["keys"]}
        self.assertEqual((keys["autostart"]["type"], keys["autostart"]["default"]), ("bool", False))
        code, res = self.json_cli("config", "reset", "autostart")
        self.assertEqual(code, 0)
        self.assertFalse(autostart.enabled())
        code, res = self.json_cli("config", "set", "autostart", "maybe")
        self.assertNotEqual(code, 0)

    def test_mixed_with_file_settings(self) -> None:
        code, res = self.json_cli("config", "set", "autostart", "on", "llm.model", "qwen3:8b")
        self.assertEqual(code, 0)
        self.assertTrue(autostart.enabled())
        self.assertEqual(config.load().llm.model, "qwen3:8b")
        self.assertNotIn("autostart", (self.path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
