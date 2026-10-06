"""打包成 exe：python packaging\\build.py → dist\\DeskMirror\\DeskMirror.exe 和 dist\\DeskMirror-<版本>-win64.zip。

先装打包工具（只在打包时用）：.venv\\Scripts\\python -m pip install -r requirements-build.txt
zip 里是一个 DeskMirror 文件夹：解压后双击 DeskMirror.exe；设置和日志存在这个文件夹里。
"""
import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deskmirror import __version__  # noqa: E402

BUILD, DIST = ROOT / "build", ROOT / "dist"
NAME = f"DeskMirror-{__version__}-win64"
LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|ThirdPartyNotices)", re.I)
CODE = (".dll", ".pyd", ".exe", ".py", ".pyc", ".pyi")
# 安装包里没带许可证全文的：补上（Apache-2.0 全文从 packaging 包里取，内容一样）
ANTLR_BSD = """Copyright (c) 2012-2017 The ANTLR Project. All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following
   disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following
   disclaimer in the documentation and/or other materials provided with the distribution.
3. Neither name of copyright holders nor the names of its contributors may be used to endorse or promote products
   derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

# exe 的“属性 → 详细信息”
VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={v4}, prodvers={v4}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Yudreamsky'),
      StringStruct('FileDescription', 'DeskMirror'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'DeskMirror'),
      StringStruct('LegalCopyright', 'Copyright (C) 2026 Yudreamsky. GPL-3.0'),
      StringStruct('OriginalFilename', 'DeskMirror.exe'),
      StringStruct('ProductName', 'DeskMirror'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def bundled_distributions(app: Path) -> set[str]:
    """打进包里的第三方 Python 包（按 PyInstaller 的模块清单和 _internal 下的文件夹对到安装包名）。"""
    names = {p.name for p in (app / "_internal").iterdir()}
    toc = BUILD / "pyinstaller" / "deskmirror" / "PYZ-00.toc"
    entries = ast.literal_eval(toc.read_text(encoding="utf-8"))
    names |= {e[0].split(".")[0] for e in (entries[1] if isinstance(entries, tuple) else entries)}
    owners = metadata.packages_distributions()
    return {d for n in names for d in owners.get(n, ())} - {"deskmirror"}


def copy_licenses(app: Path) -> list[str]:
    """把打进包里的各组件的许可证原文放进 licenses\\<组件>\\（二进制分发要附上）。"""
    out = app / "licenses"
    shutil.rmtree(out, ignore_errors=True)
    dists = sorted(bundled_distributions(app), key=str.lower)
    for name in dists + ["pyinstaller"]:                     # pyinstaller：exe 里的启动器（GPL，带例外条款）
        d = metadata.distribution(name)
        for f in d.files or ():
            if f.suffix.lower() not in CODE and ("licenses" in f.parts or LICENSE_FILE.search(f.name)):
                src = Path(d.locate_file(f))
                if src.is_file():
                    dest = out / name / "_".join(p for p in f.parts if not p.endswith(".dist-info"))
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
    apache = Path(metadata.distribution("packaging").locate_file("packaging-%s.dist-info/licenses/LICENSE.APACHE"
                                                                  % metadata.version("packaging")))
    for name, head in (("rapidocr", "RapidOCR, Copyright RapidAI, https://github.com/RapidAI/RapidOCR\n"
                                    "PaddleOCR models (PP-OCR), Copyright PaddlePaddle Authors, "
                                    "https://github.com/PaddlePaddle/PaddleOCR\n\n"),):
        (out / name).mkdir(parents=True, exist_ok=True)
        (out / name / "LICENSE.txt").write_text(head + apache.read_text(encoding="utf-8"), encoding="utf-8")
    for name in ("PySide6_Essentials", "shiboken6"):          # 安装包里只有商业许可说明：补上 LGPL-3.0 和它引用的 GPL-3.0
        if name in dists:
            shutil.copy2(ROOT / "packaging" / "LGPL-3.0.txt", out / name / "LGPL-3.0.txt")
            shutil.copy2(ROOT / "LICENSE", out / name / "GPL-3.0.txt")
    if "antlr4-python3-runtime" in dists:
        (out / "antlr4-python3-runtime" / "LICENSE.txt").parent.mkdir(parents=True, exist_ok=True)
        (out / "antlr4-python3-runtime" / "LICENSE.txt").write_text(ANTLR_BSD, encoding="utf-8")
    (out / "Python").mkdir(exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE_PYTHON.txt", out / "Python" / "LICENSE.txt")
    missing = [n for n in dists if not (out / n).exists()]
    if missing:
        raise SystemExit(f"这些组件找不到许可证文件，补上再打包：{missing}")
    return dists


def main() -> None:
    BUILD.mkdir(exist_ok=True)
    nums = tuple(([int(x) for x in __version__.split(".")] + [0, 0, 0, 0])[:4])
    (BUILD / "version_info.txt").write_text(VERSION_INFO.format(v=__version__, v4=nums), encoding="utf-8")
    env = dict(os.environ)
    # .venv 建在 Anaconda 上时，_ssl、_ctypes 等依赖的 DLL 在 Anaconda 的 Library\bin：让 PyInstaller 找得到
    lib_bin = Path(sys.base_prefix) / "Library" / "bin"
    if lib_bin.is_dir():
        env["PATH"] = str(lib_bin) + os.pathsep + env.get("PATH", "")
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "deskmirror.spec"), "--noconfirm",
                    "--clean", "--log-level", "WARN", "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller")],
                   check=True, env=env)
    app = DIST / "DeskMirror"
    for name in ("LICENSE", "THIRD-PARTY-NOTICES.md", "README.md"):
        shutil.copy2(ROOT / name, app / name)
    print("许可证：", ", ".join(copy_licenses(app)))
    zpath = DIST / f"{NAME}.zip"
    zpath.unlink(missing_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                z.write(f, Path("DeskMirror") / f.relative_to(app))
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (DIST / f"{NAME}.zip.sha256").write_text(f"{digest}  {zpath.name}\n", encoding="ascii")
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"{zpath}  {zpath.stat().st_size / 1e6:.1f} MB（解压后 {size / 1e6:.0f} MB）\nSHA256 {digest}")


if __name__ == "__main__":
    main()
