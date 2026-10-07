"""检查和安装新版本。

两种装法分开处理：
- 源码版（git clone 下来、用 .venv 跑的）：git fetch 看 main 上有没有新提交；更新 = git pull --ff-only，
  再按 requirements.txt 装依赖。配置 deskmirror.json、日志都不进版本库，更新不会动。
- 打包版（exe）：看 GitHub Releases 上的最新版本号；更新 = 打开下载页（解压覆盖旧文件夹即可，配置在 exe 旁边）。

只访问 GitHub，不发送任何屏幕内容。日志不记录命令输出以外的东西。
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from . import HOMEPAGE, ROOT, __version__
from .i18n import tr

log = logging.getLogger(__name__)

RELEASES_API = "https://api.github.com/repos/Yudreamsky/deskmirror/releases/latest"
RELEASES_PAGE = HOMEPAGE + "/releases/latest"
_NO_WINDOW = 0x08000000      # CREATE_NO_WINDOW：pythonw 下跑 git、pip 不弹黑框


@dataclass
class UpdateInfo:
    kind: str                         # "git"：源码版；"release"：打包版
    current: str = __version__
    latest: str = ""                  # 最新发布的版本号（拿不到时空）
    behind: int = 0                   # 源码版：main 上比本地多几个提交
    newer: bool = False
    notes: str = ""                   # 最新版本的更新说明（发布页上写的）
    commits: list[str] = field(default_factory=list)   # 源码版：新提交的标题（最多 20 个）
    error: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "current": self.current, "latest": self.latest, "behind": self.behind,
                "newer": self.newer, "notes": self.notes, "commits": self.commits, "error": self.error}


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def is_git_checkout() -> bool:
    return not getattr(sys, "frozen", False) and (ROOT / ".git").exists()


def _git(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=_NO_WINDOW)


def latest_release(timeout: float = 10.0) -> tuple[str, str]:
    """→ (版本号, 更新说明)。"""
    import httpx
    from .translator import make_client
    from .config import LlmConfig
    with make_client(LlmConfig(), timeout_s=timeout) as c:
        r = c.get(RELEASES_API, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
    tag = str(data.get("tag_name") or "").lstrip("vV")
    if not tag:
        raise httpx.HTTPError("no tag")
    return tag, str(data.get("body") or "")[:4000]


def check() -> UpdateInfo:
    """看一下有没有新版本（几秒钟，要联网）。"""
    info = UpdateInfo(kind="git" if is_git_checkout() else "release")
    try:
        info.latest, info.notes = latest_release()
    except Exception as e:  # noqa: BLE001 - 发布页拿不到时源码版仍可以按提交比较
        log.info("取最新发布失败：%s", type(e).__name__)
        if info.kind == "release":
            info.error = tr("连不上 GitHub，稍后再试")
            return info
    if info.kind == "release":
        info.newer = _version_tuple(info.latest) > _version_tuple(info.current)
        return info
    try:
        fetch = _git("fetch", "--quiet", "origin")
        if fetch.returncode != 0:
            info.error = tr("git fetch 失败：{msg}").format(msg=fetch.stderr.strip()[:200])
            return info
        up = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").stdout.strip() or "origin/main"
        n = _git("rev-list", "--count", f"HEAD..{up}")
        info.behind = int(n.stdout.strip() or 0) if n.returncode == 0 else 0
        if info.behind:
            log_ = _git("log", "--format=%s", "-n", "20", f"HEAD..{up}")
            info.commits = [s for s in log_.stdout.splitlines() if s.strip()]
        info.newer = info.behind > 0
    except FileNotFoundError:
        info.error = tr("没找到 git：源码版更新要用 git")
    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        info.error = tr("检查更新出错：{name}").format(name=type(e).__name__)
    return info


def apply_git() -> tuple[bool, str]:
    """源码版更新：git pull --ff-only，再装依赖。→ (成功了吗, 给用户看的说明)。"""
    if not is_git_checkout():
        return False, tr("不是源码版：请到发布页下载新版")
    st = _git("status", "--porcelain", "--untracked-files=no")
    if st.stdout.strip():
        return False, tr("程序文件夹里有改过的文件，自动更新会冲突：请先处理（git status 查看）")
    pull = _git("pull", "--ff-only", timeout=180.0)
    if pull.returncode != 0:
        return False, tr("git pull 失败：{msg}").format(msg=(pull.stderr or pull.stdout).strip()[:300])
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.exists() else sys.executable.replace("pythonw.exe", "python.exe")
    env = dict(os.environ, PYTHONUTF8="1")
    env.setdefault("PIP_CACHE_DIR", str(ROOT / ".cache" / "pip"))
    try:
        pip = subprocess.run([exe, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r",
                              str(ROOT / "requirements.txt")], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=900, env=env, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, tr("代码已更新，但安装依赖出错（{name}）：请运行 setup.bat").format(name=type(e).__name__)
    if pip.returncode != 0:
        return False, tr("代码已更新，但安装依赖失败：请运行 setup.bat。{msg}").format(msg=pip.stderr.strip()[-300:])
    head = _git("log", "-1", "--format=%h %s").stdout.strip()
    log.info("已更新到 %s", head)
    return True, tr("已更新到最新：{head}").format(head=head)


def restart_command() -> list[str]:
    """重启自己用的命令（新进程会等旧进程退出再启动，见 app.main）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    exe = str(pyw) if pyw.exists() else sys.executable
    return [exe, "-B", "-m", "deskmirror"]
