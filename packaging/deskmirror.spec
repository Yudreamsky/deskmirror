# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置。不要直接用它：运行 python packaging\build.py（先生成版本信息，再调用这个文件，最后打 zip）。
import importlib.util
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - PyInstaller 提供
SYS32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
# VC++ 运行库用系统里新的那份：Anaconda 自带的旧版 msvcp140.dll 会让 onnxruntime 崩溃
VC_RUNTIME = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
              "msvcp140_atomic_wait.dll", "concrt140.dll")
# RapidOCR 只用 onnxruntime 引擎；别的推理引擎（paddle、torch…）不打包
OTHER_ENGINES = ("mnn", "openvino", "paddle", "pytorch", "tensorrt")

hidden = [m for m in collect_submodules("rapidocr")
          if not any(f".inference_engine.{e}" in m for e in OTHER_ENGINES) and not m.endswith(".cli")]
datas = [(str(ROOT / "deskmirror" / "assets"), "deskmirror/assets")]
datas += collect_data_files("rapidocr")             # 识别模型（含韩文）和配置
binaries = collect_dynamic_libs("onnxruntime")      # DirectML.dll 等：运行时才加载，静态分析找不到
# Qt 插件也是运行时按路径加载的。.venv 建在 Anaconda 上时，PyInstaller 自己读不到 Qt 的库信息（Anaconda 的 ICU
# 让 QtCore 导入失败），不会自动带插件：这里手动带上用得到的（launcher.py 里用 QT_PLUGIN_PATH 指过去）
PYSIDE = Path(importlib.util.find_spec("PySide6").submodule_search_locations[0])
QT_PLUGINS = ("platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll", "imageformats/qjpeg.dll",
              "imageformats/qico.dll", "imageformats/qgif.dll")
binaries += [(str(PYSIDE / "plugins" / p), str(Path("PySide6/plugins") / Path(p).parent)) for p in QT_PLUGINS]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "torch", "paddle", "openvino", "tensorrt", "MNN"]
    + [f"rapidocr.inference_engine.{e}" for e in OTHER_ENGINES],
)


def _keep(entry) -> bool:
    name = Path(entry[0]).name.lower()
    if name.startswith("icu"):                        # Anaconda 的 ICU 和 Qt 不兼容；Qt 用 Windows 自带的
        return False
    if name in VC_RUNTIME:                            # 下面换成系统里的新版本
        return False
    if name.startswith("opencv_videoio_ffmpeg"):      # 视频读写，用不到
        return False
    if name == "opengl32sw.dll":                      # 软件 OpenGL，界面用不到
        return False
    return True


a.binaries = [b for b in a.binaries if _keep(b)] + \
    [(n, str(SYS32 / n), "BINARY") for n in VC_RUNTIME if (SYS32 / n).exists()]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DeskMirror",
    console=False,
    icon=str(ROOT / "packaging" / "deskmirror.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DeskMirror", upx=False)
