"""安装文件在中文 Windows（系统编码 GBK）上也要能用。"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class SetupFilesTest(unittest.TestCase):
    def test_requirements_are_ascii(self) -> None:
        for name in ("requirements.txt", "requirements-build.txt"):
            data = (ROOT / name).read_bytes()
            self.assertTrue(all(b < 128 for b in data), f"{name} 只能用 ASCII：pip 按系统编码读，中文 Windows 上是 GBK")

    def test_scripts_run_python_in_utf8_mode(self) -> None:
        for name in ("setup.bat", "start.bat"):
            self.assertIn('set "PYTHONUTF8=1"', (ROOT / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
