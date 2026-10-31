"""没接住的错误、Qt 的警告、程序崩溃：都记进日志。

魔镜用 pythonw / 打包版启动时没有控制台，Python 默认把没接住的错误写到控制台，等于直接丢了：界面上的按钮、
菜单、定时器出错，临时的后台线程出错，日志里一个字都没有。这里把它们接到日志里（和引擎记错误一样记调用位置
和错误说明）。程序直接崩掉（显卡驱动、系统接口这类）时，faulthandler 把各线程当时在做什么写进 logs/crash.log。
"""
from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("deskmirror.errors")
_crash_file = None
_qt_handler = None


def install(logdir: Path) -> None:
    """界面线程、后台线程、回调里“只能忽略”的错误写进日志；崩溃写进 crash.log。"""
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    sys.unraisablehook = _unraisablehook
    enable_crash_log(logdir)


def enable_crash_log(logdir: Path) -> None:
    """崩溃时把所有线程的调用栈追加到 crash.log（识别子进程也用这个）。"""
    global _crash_file
    if _crash_file is not None:
        return
    try:
        logdir.mkdir(parents=True, exist_ok=True)
        _crash_file = open(logdir / "crash.log", "a", encoding="utf-8")  # noqa: SIM115  进程活多久就开多久
        faulthandler.enable(_crash_file, all_threads=True)
    except OSError as e:
        _crash_file = None
        log.warning("崩溃记录打不开：%s", e)


def _excepthook(kind, value, tb) -> None:
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, value, tb)
        return
    log.error("没接住的错误", exc_info=(kind, value, tb))


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "?"
    log.error("后台线程 %s 出错停下了", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _unraisablehook(u) -> None:
    where = getattr(u.object, "__qualname__", None) or type(u.object).__name__
    if u.exc_value is None:
        log.warning("%s %s", u.err_msg or "忽略了一个错误", where)
    else:
        log.warning("%s %s", u.err_msg or "忽略了一个错误", where,
                    exc_info=(u.exc_type, u.exc_value, u.exc_traceback))


class Throttle:
    """同一句话：第一次就记；之后一分钟内的只数次数，过了一分钟再记一次，带上中间压下的次数。"""

    def __init__(self, window_s: float = 60.0, limit: int = 500) -> None:
        self.window_s = window_s
        self.limit = limit
        self._last: dict[str, list] = {}      # 这句话 → [上次记的时间, 之后压下的次数]
        self._lock = threading.Lock()         # Qt 的警告可能从别的线程来

    def hit(self, key: str, now: float | None = None) -> int | None:
        """该记就返回上次以来压下的次数（第一次是 0），不该记返回 None。"""
        now = time.monotonic() if now is None else now
        with self._lock:
            e = self._last.get(key)
            if e is not None and now - e[0] < self.window_s:
                e[1] += 1
                return None
            if e is None and len(self._last) >= self.limit:
                self._last.clear()
            skipped = e[1] if e is not None else 0
            self._last[key] = [now, 0]
            return skipped


def install_qt():
    """Qt 自己的警告（画不出来、窗口位置设不上……）写进日志，同一句一分钟只记一次。返回原来的处理函数。"""
    global _qt_handler
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    logger = logging.getLogger("deskmirror.qt")
    throttle = Throttle()

    def handler(kind, _context, message) -> None:
        try:
            level = levels.get(kind, logging.WARNING)
            if not logger.isEnabledFor(level):
                return
            skipped = throttle.hit(message)
            if skipped is None:
                return
            if skipped:
                logger.log(level, "%s（上一分钟里又出现了 %d 次）", message, skipped)
            else:
                logger.log(level, "%s", message)
        except Exception:  # noqa: BLE001 - Qt 回调里不能抛异常
            pass

    _qt_handler = handler                    # 留住引用
    return qInstallMessageHandler(handler)
