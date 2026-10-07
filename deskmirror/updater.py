"""检查、下载、安装新版本（GitHub Releases）。不依赖 Qt：界面（ui/update.py）和命令行（update 命令）共用。

只访问 GitHub：取最新版本号、更新说明和发行包，不发送任何屏幕内容。有新版只提示，用户点了（或命令行 update）才下载。
三种情况：
- 打包版（解压即用的 exe）：下载 zip、核对 SHA256、解压到程序文件夹里的 .update\\new。退出魔镜后，由新版本自带的
  DeskMirrorCLI.exe（在 .update\\new 里运行）把旧的程序文件挪到 .update\\old、换上新的、启动新版本；中途出错就挪回旧的。
  只换程序文件（exe、_internal、许可证、说明），设置、日志、学到的滚轮曲线、译文记忆都在原处不动。
- 源码版（git clone 的）：退出魔镜后 git pull --ff-only、重装依赖、重新启动。改过代码（工作区不干净）就不自动更新。
- 其他（源码 ZIP、装在不能写入的文件夹里的 exe）：打开发布页，手动下载。
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from ctypes import wintypes as wt
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import httpx

from . import HOMEPAGE, ROOT, __version__
from .i18n import tr

log = logging.getLogger(__name__)

API = "https://api.github.com/repos/Yudreamsky/deskmirror/releases/latest"
RELEASES_PAGE = HOMEPAGE + "/releases/latest"
UPDATE_DIR = ".update"                    # 程序文件夹里：new = 解压的新版本，old = 换下来的旧版本，done.json = 结果
PROGRAM_ITEMS = ("DeskMirror.exe", "DeskMirrorCLI.exe", "_internal", "licenses", "LICENSE", "THIRD-PARTY-NOTICES.md")
QUIT_EVENT = "Local\\DeskMirror.Quit"    # 命令行更新时请正在运行的魔镜退出
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


class UpdateError(Exception):
    """出错原因（给用户看）。"""


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:4]) or (0,)


def is_newer(version: str, than: str = __version__) -> bool:
    return parse_version(version) > parse_version(than)


@dataclass
class Release:
    version: str                 # "1.2.0"
    notes: str                   # 更新说明（Markdown）
    page: str                    # 发布页
    zip_url: str = ""
    zip_name: str = ""
    zip_size: int = 0
    sha_url: str = ""


def _api() -> str:
    return os.environ.get("DESKMIRROR_UPDATE_URL") or API       # 测试时指向本机的假发布


def _client(timeout: float = 15.0) -> httpx.Client:
    """访问 GitHub 用系统代理（国内常要开代理才连得上）；SOCKS 代理用不了就直连。"""
    proxies = urllib.request.getproxies()
    proxy = proxies.get("https") or proxies.get("http") or None
    mounts = None
    if proxy and proxy.startswith(("http://", "https://")):
        mounts = {"all://127.0.0.1": httpx.HTTPTransport(), "all://localhost": httpx.HTTPTransport(),
                  "all://": httpx.HTTPTransport(proxy=proxy)}
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0), follow_redirects=True, trust_env=False,
                        mounts=mounts, headers={"User-Agent": f"DeskMirror/{__version__} (+{HOMEPAGE})",
                                                "Accept": "application/vnd.github+json"})


def latest_release() -> Release:
    try:
        with _client() as c:
            r = c.get(_api())
            if r.status_code == 404:
                raise UpdateError(tr("GitHub 上还没有发布过版本"))
            if r.status_code in (403, 429) and "rate limit" in r.text.lower():
                raise UpdateError(tr("这一小时查 GitHub 的次数用完了，过一会儿再试"))
            r.raise_for_status()
            data = r.json()
    except httpx.TimeoutException:
        raise UpdateError(tr("连 GitHub 超时（国内网络可能要开代理）")) from None
    except httpx.HTTPStatusError as e:
        raise UpdateError(tr("GitHub 返回错误（HTTP {code}）").format(code=e.response.status_code)) from None
    except (httpx.HTTPError, ValueError):
        raise UpdateError(tr("连不上 GitHub（国内网络可能要开代理）")) from None
    version = str(data.get("tag_name") or "").lstrip("vV")
    if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        raise UpdateError(tr("GitHub 上的版本号看不懂：{tag}").format(tag=data.get("tag_name")))
    rel = Release(version, str(data.get("body") or ""), str(data.get("html_url") or RELEASES_PAGE))
    want = f"DeskMirror-{version}-win64.zip"
    for a in data.get("assets") or []:
        if a.get("name") == want:
            rel.zip_url, rel.zip_name, rel.zip_size = a["browser_download_url"], want, int(a.get("size") or 0)
        elif a.get("name") == want + ".sha256":
            rel.sha_url = a["browser_download_url"]
    return rel


# ---------------------------------------------------------------------------------------------------- 能怎么更新
def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """程序文件所在的文件夹：打包版是 exe 旁边，源码版是项目根目录。"""
    return Path(sys.executable).resolve().parent if frozen() else Path(__file__).resolve().parent.parent


def _git(root: Path, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)


def install_method() -> tuple[str, str]:
    """(package | git | manual, 只能手动更新时的原因)。"""
    app = program_dir()
    if frozen():
        if ROOT.resolve() != app:
            return "manual", tr("魔镜放在不能写入的文件夹里（比如 Program Files），没法自动更新")
        return "package", ""
    if not (app / ".git").exists():
        return "manual", tr("这份源码不是用 git 下载的，没法自动更新")
    if shutil.which("git") is None:
        return "manual", tr("没找到 git，没法自动更新")
    try:
        dirty = _git(app, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "manual", tr("git 用不了，没法自动更新")
    if dirty:
        return "manual", tr("源码改动过（git 工作区不干净），自动更新会冲突；请自己 git pull")
    return "git", ""


# ---------------------------------------------------------------------------------------------------- 下载、解压
def download(rel: Release, dest: Path, progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None) -> Path:
    """下载发行包并核对 SHA256（核对不上就删掉）。"""
    if not rel.zip_url:
        raise UpdateError(tr("这个版本没有发行包"))
    if not rel.sha_url:
        raise UpdateError(tr("这个版本没有校验文件，没法确认下载完整"))
    dest.mkdir(parents=True, exist_ok=True)
    need = rel.zip_size * 6 + 200_000_000            # 压缩包 + 解压出来的 + 换下来的旧版本，再留点余量
    if shutil.disk_usage(dest).free < need:
        raise UpdateError(tr("磁盘空间不够：更新要大约 {mb} MB").format(mb=need // 1_000_000))
    out, part = dest / rel.zip_name, dest / (rel.zip_name + ".part")
    digest = hashlib.sha256()
    try:
        with _client(timeout=60) as c:
            want = c.get(rel.sha_url).raise_for_status().text.split()[0].strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", want):
                raise UpdateError(tr("校验文件的格式不对"))
            with c.stream("GET", rel.zip_url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or rel.zip_size or 0)
                done = 0
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        if cancel is not None and cancel.is_set():
                            raise UpdateError(tr("已取消"))
                        f.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if progress is not None:
                            progress(done, total)
    except httpx.TimeoutException:
        part.unlink(missing_ok=True)
        raise UpdateError(tr("下载超时（国内网络可能要开代理）")) from None
    except httpx.HTTPError:
        part.unlink(missing_ok=True)
        raise UpdateError(tr("下载失败（国内网络可能要开代理）")) from None
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != want:
        part.unlink(missing_ok=True)
        raise UpdateError(tr("下载的文件和校验值对不上（可能没下载完整），已删掉，请重试"))
    os.replace(part, out)
    return out


def extract(zip_path: Path, dest: Path) -> Path:
    """解压到 dest，返回里面的 DeskMirror 文件夹（新版本的程序文件）。"""
    shutil.rmtree(dest, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.startswith(("/", "\\")) or ":" in name or ".." in Path(name).parts:
                raise UpdateError(tr("发行包里有不安全的路径：{name}").format(name=name))
        z.extractall(dest)
    app = dest / "DeskMirror"
    if not (app / "DeskMirror.exe").is_file() or not (app / "DeskMirrorCLI.exe").is_file():
        raise UpdateError(tr("发行包里缺少 DeskMirror.exe 或 DeskMirrorCLI.exe"))
    return app


# ---------------------------------------------------------------------------------------------------- 交给助手进程
def stage(root: Path | None = None) -> Path:
    return (root or program_dir()) / UPDATE_DIR


def start_helper(new_app: Path | None, wait_pid: int, restart: bool) -> None:
    """起一个助手进程，等 wait_pid 退出后换上新版本：打包版是新版本里的 DeskMirrorCLI.exe，源码版是本项目的 Python。"""
    if new_app is not None:
        cmd = [str(new_app / "DeskMirrorCLI.exe"), "update", "--apply", str(program_dir()), "--wait", str(wait_pid),
               "--from", __version__]
        cwd = new_app
    else:
        py = program_dir() / ".venv" / "Scripts" / "python.exe"
        cmd = [str(py if py.exists() else sys.executable), "-m", "deskmirror", "update", "--apply-source",
               "--wait", str(wait_pid), "--from", __version__]
        cwd = program_dir()
    if restart:
        cmd.append("--restart")
    subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                     close_fds=True)


def request_quit() -> bool:
    """请正在运行的魔镜退出（命令行更新时用）；它没在运行返回 False。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    k32.OpenEventW.restype = wt.HANDLE
    h = k32.OpenEventW(0x0002, False, QUIT_EVENT)          # EVENT_MODIFY_STATE
    if not h:
        return False
    k32.SetEvent(h)
    k32.CloseHandle(h)
    return True


# ---------------------------------------------------------------------------------------------------- 助手进程里
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_k32.CreateToolhelp32Snapshot.restype = wt.HANDLE


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


_k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(_ProcessEntry)]
_k32.Process32FirstW.restype = wt.BOOL
_k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(_ProcessEntry)]
_k32.Process32NextW.restype = wt.BOOL


def _wait_exit(pid: int, timeout_s: float) -> bool:
    if pid <= 0:
        return True
    h = _k32.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
    if not h:
        return True                                         # 已经退出了
    try:
        return _k32.WaitForSingleObject(h, int(timeout_s * 1000)) == 0
    finally:
        _k32.CloseHandle(h)


def _processes_in(folder: Path, skip: Path) -> list[int]:
    """程序文件在 folder 里的进程（不算 skip 里的，也不算自己）：换文件前它们都要退出。"""
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)            # TH32CS_SNAPPROCESS
    if snap in (None, wt.HANDLE(-1).value):
        return []
    found = []
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = entry.th32ProcessID
            if pid != os.getpid():
                h = _k32.OpenProcess(0x1000, False, pid)    # PROCESS_QUERY_LIMITED_INFORMATION
                if h:
                    buf, size = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
                    if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        exe = Path(buf.value).resolve()
                        if exe.is_relative_to(folder) and not exe.is_relative_to(skip):
                            found.append(pid)
                    _k32.CloseHandle(h)
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return found


def _retry(fn: Callable[[], object], seconds: float = 15.0) -> None:
    """杀毒软件扫描、刚退出的进程还没放手时会暂时占着文件：等一会儿再试。"""
    end = time.monotonic() + seconds
    while True:
        try:
            fn()
            return
        except OSError:
            if time.monotonic() > end:
                raise
            time.sleep(0.5)


def _items(folder: Path) -> list[str]:
    return [n for n in PROGRAM_ITEMS if (folder / n).exists()] + sorted(p.name for p in folder.glob("README*.md"))


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def apply_package(new_app: Path, target: Path, wait_pid: int, restart: bool, old_version: str) -> None:
    """（在新版本的 DeskMirrorCLI.exe 里运行）等旧的魔镜退出，旧程序文件挪到 .update\\old，换上新的，启动新版本。
    出错就把旧的挪回去（启动旧的），并抛出 UpdateError。"""
    new_app, target = new_app.resolve(), target.resolve()
    _wait_exit(wait_pid, 60)
    end = time.monotonic() + 60
    while _processes_in(target, stage(target)) and time.monotonic() < end:   # 识别子进程、别的命令行
        time.sleep(0.5)
    old = stage(target) / "old"
    shutil.rmtree(old, ignore_errors=True)
    old.mkdir(parents=True)
    moved, copied = [], []
    try:
        for name in sorted(set(_items(target)) | set(_items(new_app))):
            if (target / name).exists():
                _retry(lambda n=name: os.replace(target / n, old / n))
                moved.append(name)
        for name in _items(new_app):
            src = new_app / name
            if src.is_dir():
                shutil.copytree(src, target / name)
            else:
                shutil.copy2(src, target / name)
            copied.append(name)
    except OSError as e:
        log.exception("换新版本失败，换回旧版本")
        for name in copied:
            try:
                _remove(target / name)
            except OSError:
                log.exception("删不掉新版本的 %s", name)
        for name in moved:
            try:
                _retry(lambda n=name: os.replace(old / n, target / n))
            except OSError:
                log.exception("挪不回旧版本的 %s", name)
        if restart and (target / "DeskMirror.exe").exists():
            subprocess.Popen([str(target / "DeskMirror.exe")], cwd=str(target))
        raise UpdateError(tr("换新版本时出错，已经换回旧版本：{error}").format(error=e)) from None
    (stage(target) / "done.json").write_text(json.dumps({"from": old_version, "to": __version__}), encoding="utf-8")
    log.info("已从 %s 更新到 %s", old_version, __version__)
    if restart:
        subprocess.Popen([str(target / "DeskMirror.exe")], cwd=str(target))
    shutil.rmtree(old, ignore_errors=True)          # 删不干净的，新版本启动后再清


def apply_source(root: Path, wait_pid: int, restart: bool, old_version: str) -> None:
    """（源码版的助手进程）等魔镜退出，git pull --ff-only，重装依赖，再启动。出错也会把魔镜重新打开。"""
    _wait_exit(wait_pid, 60)
    try:
        r = _git(root, "pull", "--ff-only", timeout=300)
        if r.returncode != 0:
            raise UpdateError(tr("git pull 失败：{error}").format(error=(r.stderr or r.stdout).strip()[-300:]))
        py = root / ".venv" / "Scripts" / "python.exe"
        env = dict(os.environ, PYTHONUTF8="1", PIP_CACHE_DIR=os.environ.get("PIP_CACHE_DIR")
                   or str(root / ".cache" / "pip"))
        r = subprocess.run([str(py), "-m", "pip", "install", "-r", str(root / "requirements.txt")], cwd=str(root),
                           env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                           creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            raise UpdateError(tr("装依赖失败：{error}").format(error=(r.stderr or r.stdout).strip()[-300:]))
        stage(root).mkdir(exist_ok=True)
        version = _read_version(root)                       # 以 git pull 之后的源码为准
        (stage(root) / "done.json").write_text(json.dumps({"from": old_version, "to": version}), encoding="utf-8")
        log.info("源码已从 %s 更新到 %s", old_version, version)
    finally:
        if restart:
            subprocess.Popen(["cmd", "/c", str(root / "start.bat")], cwd=str(root), creationflags=CREATE_NO_WINDOW)


def _read_version(root: Path) -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (root / "deskmirror" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def take_result(root: Path | None = None) -> dict | None:
    """新版本启动时调用：刚才的更新结果 {"from", "to"}（只读一次）。"""
    done = stage(root) / "done.json"
    if not done.exists():
        return None
    try:
        return json.loads(done.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        done.unlink(missing_ok=True)


def cleanup(root: Path | None = None) -> None:
    """清掉 .update 里留下的旧版本、解压的新版本和压缩包（助手进程刚退出时可能还删不掉：下次再删）。"""
    folder = stage(root)
    for name in ("old", "new"):
        shutil.rmtree(folder / name, ignore_errors=True)
    for f in folder.glob("*.zip*"):
        try:
            f.unlink()
        except OSError:
            pass


def message_box(text: str) -> None:
    """助手进程没有窗口：出错时弹个系统对话框告诉用户。"""
    ctypes.windll.user32.MessageBoxW(None, text, tr("桌面魔镜"), 0x30)       # MB_ICONWARNING


def release_dict(rel: Release) -> dict:
    return asdict(rel)
