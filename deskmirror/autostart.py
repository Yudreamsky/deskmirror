"""开机自动启动（#9）：写当前用户的启动项（HKCU\\…\\CurrentVersion\\Run），不用管理员权限；关掉就删掉这一项。

以注册表为准：设置窗口打开时读它决定勾不勾；任务管理器“启动应用”里禁用了的（StartupApproved），也算没开。
程序挪了地方、启动项指向的文件没了，启动时改成现在的路径（指向别的、还在的安装就不动）。
开机自启时带 --autostart：魔镜都收成球待命，点开或拖出来才开始截屏、识别（识别模型那时才载入，开机更快）。
源码版用项目根目录的 autostart.pyw 启动：.venv 里的 pythonw 不弹黑框，从哪个目录启动都找得到程序。
"""
from __future__ import annotations

import re
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
NAME = "DeskMirror"
FLAG = "--autostart"


def command() -> str:
    """现在这个程序的启动命令。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" {FLAG}'
    root = Path(__file__).resolve().parent.parent
    py = root / ".venv" / "Scripts" / "pythonw.exe"
    if not py.exists():
        py = Path(sys.executable).resolve().with_name("pythonw.exe")    # 没用 setup.bat 建环境：用现在这个 Python
    return f'"{py}" -B -X utf8 "{root / "autostart.pyw"}" {FLAG}'


def current() -> str:
    """启动项里现在写的命令（没有就是空）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _kind = winreg.QueryValueEx(k, NAME)
            return str(value)
    except OSError:
        return ""


def _disabled() -> bool:
    """任务管理器里禁用了：StartupApproved 里这一项第一个字节是单数（02 启用，03 禁用）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as k:
            data, _kind = winreg.QueryValueEx(k, NAME)
    except OSError:
        return False
    return isinstance(data, bytes) and bool(data) and data[0] % 2 == 1


def enabled() -> bool:
    return bool(current()) and not _disabled()


def _write(cmd: str) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, cmd)


def _delete(key: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, NAME)
    except FileNotFoundError:
        pass


def set_enabled(on: bool) -> None:
    """打开：写启动项，顺便清掉任务管理器里的禁用；关掉：删掉。写不进注册表抛 OSError。"""
    if on:
        _write(command())
    else:
        _delete(RUN_KEY)
    _delete(APPROVED_KEY)


def _paths(cmd: str) -> list[Path]:
    return [Path(p) for p in re.findall(r'"([^"]+)"', cmd)]


def refresh() -> bool:
    """启动项指向的文件没了（程序挪了地方）：改成现在的路径。返回改没改。任务管理器里的禁用不动。"""
    cur = current()
    if not cur or cur == command():
        return False
    paths = _paths(cur)
    if paths and all(p.exists() for p in paths):
        return False                       # 指向别的、还在的安装（比如另外解压的打包版）：不抢
    _write(command())
    return True
