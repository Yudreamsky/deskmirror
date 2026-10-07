"""检查和安装新版本（updater.py、命令行 update）：用本机的假发布（不连 GitHub），换文件在临时文件夹里做。"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import http.server
import io
import json
import os
import pathlib
import shutil
import tempfile
import threading
import unittest
import zipfile

from deskmirror import __version__, cli, config, updater


def _package(folder: pathlib.Path, marker: str) -> None:
    """一个假的发行包内容：DeskMirror 文件夹里有两个 exe、_internal、说明。"""
    (folder / "_internal").mkdir(parents=True)
    (folder / "_internal" / "lib.txt").write_text(marker, encoding="utf-8")
    for name in ("DeskMirror.exe", "DeskMirrorCLI.exe", "README.md", "LICENSE"):
        (folder / name).write_text(f"{name} {marker}", encoding="utf-8")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


class _Server:
    """本机的假 GitHub：/latest 是发布信息，其余是发行包和校验文件。"""

    def __init__(self, root: pathlib.Path) -> None:
        handler = functools.partial(_Quiet, directory=str(root))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class UpdaterTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._dir.name)
        self.web = self.tmp / "web"
        self.web.mkdir()
        self.server = _Server(self.web)
        self._env = os.environ.get("DESKMIRROR_UPDATE_URL")
        os.environ["DESKMIRROR_UPDATE_URL"] = self.server.url + "/latest"

    def tearDown(self) -> None:
        self.server.close()
        if self._env is None:
            os.environ.pop("DESKMIRROR_UPDATE_URL", None)
        else:
            os.environ["DESKMIRROR_UPDATE_URL"] = self._env
        self._dir.cleanup()

    def publish(self, version: str, sha: str | None = None, with_cli: bool = True) -> bytes:
        src = self.tmp / f"pkg-{version}" / "DeskMirror"
        _package(src, version)
        if not with_cli:
            (src / "DeskMirrorCLI.exe").unlink()
        name = f"DeskMirror-{version}-win64.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    z.write(f, pathlib.Path("DeskMirror") / f.relative_to(src))
        data = buf.getvalue()
        (self.web / name).write_bytes(data)
        (self.web / (name + ".sha256")).write_text(f"{sha or hashlib.sha256(data).hexdigest()}  {name}\n",
                                                   encoding="ascii")
        (self.web / "latest").write_text(json.dumps({
            "tag_name": f"v{version}", "body": "## 新功能\n- 更好", "html_url": self.server.url + "/page",
            "assets": [{"name": name, "size": len(data), "browser_download_url": f"{self.server.url}/{name}"},
                       {"name": name + ".sha256", "size": 80,
                        "browser_download_url": f"{self.server.url}/{name}.sha256"}]}), encoding="utf-8")
        return data

    def test_versions(self) -> None:
        self.assertEqual(updater.parse_version("v1.2.0"), (1, 2, 0))
        self.assertTrue(updater.is_newer("1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer("1.1.1", "1.1.1"))
        self.assertFalse(updater.is_newer(__version__))

    def test_release_download_and_extract(self) -> None:
        data = self.publish("9.9.9")
        rel = updater.latest_release()
        self.assertEqual((rel.version, rel.zip_size), ("9.9.9", len(data)))
        self.assertIn("新功能", rel.notes)
        seen = []
        zip_path = updater.download(rel, self.tmp / "stage", lambda d, t: seen.append((d, t)))
        self.assertEqual(zip_path.read_bytes(), data)
        self.assertEqual(seen[-1], (len(data), len(data)))
        app = updater.extract(zip_path, self.tmp / "stage" / "new")
        self.assertEqual((app / "DeskMirror.exe").read_text(encoding="utf-8"), "DeskMirror.exe 9.9.9")

    def test_bad_checksum_is_rejected_and_deleted(self) -> None:
        self.publish("9.9.9", sha="0" * 64)
        rel = updater.latest_release()
        with self.assertRaises(updater.UpdateError):
            updater.download(rel, self.tmp / "stage")
        self.assertEqual(list((self.tmp / "stage").iterdir()), [], "核对不上的不留下")

    def test_cancel(self) -> None:
        self.publish("9.9.9")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(updater.UpdateError):
            updater.download(updater.latest_release(), self.tmp / "stage", cancel=cancel)
        self.assertEqual(list((self.tmp / "stage").iterdir()), [])

    def test_package_without_cli_is_refused(self) -> None:
        self.publish("9.9.9", with_cli=False)
        zip_path = updater.download(updater.latest_release(), self.tmp / "stage")
        with self.assertRaises(updater.UpdateError):
            updater.extract(zip_path, self.tmp / "stage" / "new")

    def test_unsafe_zip_paths_are_refused(self) -> None:
        bad = self.tmp / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../evil.txt", "x")
        with self.assertRaises(updater.UpdateError):
            updater.extract(bad, self.tmp / "out")

    def _install(self) -> tuple[pathlib.Path, pathlib.Path]:
        target = self.tmp / "DeskMirror"
        _package(target, "old")
        (target / "README.ja.md").write_text("old", encoding="utf-8")     # 新版本里没有的说明：换下来
        (target / "deskmirror.json").write_text('{"keep": true}', encoding="utf-8")
        (target / "logs").mkdir()
        (target / "logs" / "deskmirror.log").write_text("log", encoding="utf-8")
        new_app = updater.stage(target) / "new" / "DeskMirror"
        _package(new_app, "new")
        return target, new_app

    def test_apply_package_swaps_program_files_only(self) -> None:
        target, new_app = self._install()
        updater.apply_package(new_app, target, 0, restart=False, old_version="1.0.0")
        self.assertEqual((target / "DeskMirror.exe").read_text(encoding="utf-8"), "DeskMirror.exe new")
        self.assertEqual((target / "_internal" / "lib.txt").read_text(encoding="utf-8"), "new")
        self.assertFalse((target / "README.ja.md").exists())
        self.assertEqual((target / "deskmirror.json").read_text(encoding="utf-8"), '{"keep": true}', "设置不动")
        self.assertTrue((target / "logs" / "deskmirror.log").exists())
        self.assertFalse((updater.stage(target) / "old").exists(), "换下来的旧版本删掉了")
        self.assertEqual(updater.take_result(target), {"from": "1.0.0", "to": __version__})
        self.assertIsNone(updater.take_result(target), "结果只报一次")
        updater.cleanup(target)
        self.assertFalse((updater.stage(target) / "new").exists())

    def test_apply_package_rolls_back_on_failure(self) -> None:
        target, new_app = self._install()
        real = shutil.copytree

        def broken(*a, **k):
            raise OSError("disk full")
        shutil.copytree = broken
        try:
            with self.assertRaises(updater.UpdateError):
                updater.apply_package(new_app, target, 0, restart=False, old_version="1.0.0")
        finally:
            shutil.copytree = real
        self.assertEqual((target / "DeskMirror.exe").read_text(encoding="utf-8"), "DeskMirror.exe old")
        self.assertEqual((target / "_internal" / "lib.txt").read_text(encoding="utf-8"), "old")
        self.assertEqual((target / "README.ja.md").read_text(encoding="utf-8"), "old")
        self.assertIsNone(updater.take_result(target))

    def test_install_method(self) -> None:
        orig = (updater.frozen, updater.program_dir, updater.ROOT)
        try:
            updater.frozen = lambda: True
            updater.program_dir = lambda: self.tmp
            updater.ROOT = self.tmp
            self.assertEqual(updater.install_method()[0], "package")
            updater.ROOT = self.tmp / "elsewhere"                  # 设置放到 %LOCALAPPDATA%：程序文件夹不能写
            self.assertEqual(updater.install_method()[0], "manual")
            updater.frozen = lambda: False                          # 源码版，但不是 git 下载的
            self.assertEqual(updater.install_method()[0], "manual")
        finally:
            updater.frozen, updater.program_dir, updater.ROOT = orig

    def test_cli_update_check(self) -> None:
        cfg_dir = tempfile.TemporaryDirectory()
        old_cfg = os.environ.get("DESKMIRROR_CONFIG")
        os.environ["DESKMIRROR_CONFIG"] = str(pathlib.Path(cfg_dir.name) / "deskmirror.json")
        try:
            for version, newer in (("9.9.9", True), (__version__, False)):
                self.publish(version)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main(["update", "--check", "--json"])
                res = json.loads(out.getvalue())
                self.assertEqual((code, res["latest"], res["newer"]), (0, version, newer))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["update", "--json"])                # 没加 --yes：不动手
            self.assertEqual((code, json.loads(out.getvalue())["ok"]), (0, True), "已经是最新版本")
            self.assertFalse(config.config_path().exists() and "update" in config.config_path().read_text())
        finally:
            if old_cfg is None:
                os.environ.pop("DESKMIRROR_CONFIG", None)
            else:
                os.environ["DESKMIRROR_CONFIG"] = old_cfg
            cfg_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
