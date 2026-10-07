"""检查更新的窗口：查 GitHub 上的最新版本，有新版就显示更新说明；点“更新”后下载、核对、解压，再退出魔镜换上新版本。

真正的活儿在 updater.py（命令行 update 也用它）：打包版换文件、源码版 git pull 都在魔镜退出以后由助手进程做。
"""
from __future__ import annotations

import threading
import webbrowser

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout)

from .. import __version__, updater, winapi
from ..i18n import tr


class _Relay(QObject):
    done = Signal(str, object)          # (什么事, 结果或异常)
    progress = Signal(int, int)


class UpdateDialog(QDialog):
    install_ready = Signal(object)      # 准备好了：新版本的程序文件夹（打包版）或 None（源码版）；请程序退出、交给助手进程
    skip_requested = Signal(str)        # 跳过这个版本

    def __init__(self, release: updater.Release | None = None) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(tr("桌面魔镜 · 检查更新"))
        self.resize(640, 520)
        self.release: updater.Release | None = None
        self.method, self.reason = "manual", ""
        self.auto_start = False          # 调试通道用：查到新版本就直接更新
        self._cancel = threading.Event()
        self._relay = _Relay()
        self._relay.done.connect(self._on_done)
        self._relay.progress.connect(self._on_progress)
        lay = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.status.setOpenExternalLinks(True)
        lay.addWidget(self.status)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.hide()
        lay.addWidget(self.notes, 1)
        self.bar = QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        self.skip = QPushButton(tr("跳过这个版本"))
        self.skip.clicked.connect(self._skip)
        self.skip.hide()
        row.addWidget(self.skip)
        row.addStretch(1)
        self.action = QPushButton()
        self.action.clicked.connect(self._act)
        self.action.hide()
        row.addWidget(self.action)
        self.close_btn = QPushButton(tr("关闭"))
        self.close_btn.clicked.connect(self.close)
        row.addWidget(self.close_btn)
        lay.addLayout(row)
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))
        if release is not None:
            self._relay.done.emit("checked", (release, updater.install_method()))
        else:
            self.check()

    # ------------------------------------------------------------------ 后台
    def _run(self, tag: str, fn) -> None:
        def work() -> None:
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001 - 原样交给界面显示
                res = e
            self._relay.done.emit(tag, res)
        threading.Thread(target=work, daemon=True).start()

    def check(self) -> None:
        self.status.setText(tr("正在查 GitHub 上的最新版本…"))
        self.action.hide()
        self._run("checked", lambda: (updater.latest_release(), updater.install_method()))

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setMaximum(max(1, total))
        self.bar.setValue(done)
        self.bar.setFormat(f"{done / 1e6:.0f} / {total / 1e6:.0f} MB")

    def _on_done(self, tag: str, res) -> None:
        if isinstance(res, Exception):
            msg = str(res) if isinstance(res, updater.UpdateError) else tr("出错了：{name}").format(
                name=type(res).__name__)
            self.status.setText(("❌ " if tag != "checked" else "⚠️ ") + msg)
            self.bar.hide()
            self._show_action(tr("重试"), "retry" if tag == "checked" else "start")
            return
        if tag == "checked":
            self.release, (self.method, self.reason) = res
            self._show_release()
        elif tag == "downloaded":
            self.status.setText(tr("下载好了，也核对过了。马上退出魔镜、换上新版本，再自动打开…"))
            self.bar.hide()
            self.install_ready.emit(res)

    def _show_release(self) -> None:
        rel = self.release
        if not updater.is_newer(rel.version):
            self.status.setText(tr("已经是最新版本（{version}）。").format(version=__version__))
            return
        self.status.setText(tr("<b>有新版本 {latest}</b>（现在是 {current}）。更新说明：").format(
            latest=rel.version, current=__version__))
        self.notes.setMarkdown(rel.notes or tr("（没有更新说明）"))
        self.notes.show()
        self.skip.show()
        if self.method == "package":
            mb = f"{rel.zip_size / 1e6:.0f} MB" if rel.zip_size else ""
            self._show_action(tr("下载并更新 {size}").format(size=mb).strip(), "start")
        elif self.method == "git":
            self._show_action(tr("更新（git pull）"), "start")
        else:
            self.status.setText(self.status.text() + "<br>" + tr("{reason}，请到 {link} 下载。").format(
                reason=self.reason, link=f'<a href="{rel.page}">{tr("发布页")}</a>'))
            self._show_action(tr("打开下载页面"), "page")
        if self.auto_start and self.method != "manual":
            self._start()

    def _show_action(self, text: str, what: str) -> None:
        self.action.setText(text)
        self.action.setProperty("what", what)
        self.action.setEnabled(True)
        self.action.show()

    # ------------------------------------------------------------------ 按钮
    def _act(self) -> None:
        what = self.action.property("what")
        if what == "retry":
            self.check()
        elif what == "page":
            webbrowser.open(self.release.page if self.release else updater.RELEASES_PAGE)
        elif what == "cancel":
            self._cancel.set()
        else:
            self._start()

    def _start(self) -> None:
        self.skip.hide()
        if self.method == "git":
            self.status.setText(tr("马上退出魔镜，更新源码、装好依赖后再自动打开（要一两分钟）…"))
            self.action.hide()
            self.install_ready.emit(None)
            return
        self._cancel.clear()
        self.status.setText(tr("正在下载 {version}…").format(version=self.release.version))
        self.bar.setValue(0)
        self.bar.show()
        self._show_action(tr("取消"), "cancel")
        rel, cancel = self.release, self._cancel

        def work():
            zip_path = updater.download(rel, updater.stage(), lambda d, t: self._relay.progress.emit(d, t), cancel)
            return updater.extract(zip_path, updater.stage() / "new")
        self._run("downloaded", work)

    def _skip(self) -> None:
        if self.release is not None:
            self.skip_requested.emit(self.release.version)
        self.close()

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._cancel.set()               # 正在下载就停下
        super().closeEvent(ev)
