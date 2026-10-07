"""桌面魔镜：后台识别并翻译整个可见桌面，前台用可拖动的矩形魔镜在原位置显示译文。"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

__version__ = "1.1.0"
CONTACT_EMAIL = "a885187@gmail.com"   # 作者邮箱（设置 → 关于）
HOMEPAGE = "https://github.com/Yudreamsky/deskmirror"   # 项目主页（设置 → 关于）
KOFI_URL = "https://ko-fi.com/dreamskyu"   # 海外打赏的 Ko-fi 主页（关于 → 打赏作者）；空着就不显示


def _data_root() -> Path:
    """设置、日志、学到的滚轮曲线放在哪：源码运行时是项目根目录；打包成 exe 时放在 exe 旁边（解压即用，
    删掉文件夹就清理干净），那里写不进去（比如放进了 Program Files）就改放 %LOCALAPPDATA%\\DeskMirror。"""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent
    here = Path(sys.executable).resolve().parent
    try:
        probe = here / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return here
    except OSError:
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DeskMirror"
        d.mkdir(parents=True, exist_ok=True)
        return d


ROOT = _data_root()
# 可选：单独放在这里的 DirectML 版 onnxruntime（和环境里的 CPU 版互不影响）；只在用显卡识别时插到搜索路径最前面。
# 一般不需要：环境里直接装 onnxruntime-directml（见 requirements.txt）就能用显卡。
DIRECTML_RUNTIME = ROOT / ".cache" / "directml-probe" / "1.24.4"


def _preload_system_dlls() -> None:
    """抢先加载系统自带的 VC++ 运行库和 ICU。

    Anaconda 的 Python 目录里带着旧版 msvcp140.dll 和不兼容的 icuuc.dll，会比系统版本先被找到：
    onnxruntime 因此崩溃，PySide6 报“找不到指定的程序”。同名 DLL 在进程里加载过一次后会被直接复用，
    所以要在导入任何依赖之前先把系统版本加载进来。
    """
    if sys.platform != "win32":
        return
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    for name in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
                 "concrt140.dll", "icuuc.dll", "icuin.dll"):
        path = system32 / name
        if path.exists() and not kernel32.GetModuleHandleW(name):
            try:
                ctypes.WinDLL(str(path))
            except OSError:
                pass


def use_directml_runtime() -> bool:
    """在导入 onnxruntime 之前调用：存在隔离的 DirectML 运行库时优先使用它。"""
    if "onnxruntime" in sys.modules:
        return "DmlExecutionProvider" in getattr(sys.modules["onnxruntime"], "get_available_providers", lambda: [])()
    if not (DIRECTML_RUNTIME / "onnxruntime" / "__init__.py").exists():
        return False
    path = str(DIRECTML_RUNTIME)
    if path not in sys.path:
        sys.path.insert(0, path)
    return True


_preload_system_dlls()
