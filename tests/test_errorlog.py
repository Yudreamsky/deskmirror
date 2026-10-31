"""没接住的错误、Qt 警告、崩溃记录：都要进日志（没有控制台时 Python 默认会把它们丢掉）。"""
import faulthandler
import gc
import io
import logging
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from deskmirror import errorlog  # noqa: E402

SCREEN_TEXT = "Tickets are sold at the pier"


def run_thread(target) -> None:
    t = threading.Thread(target=target, name="probe")
    t.start()
    t.join()


def log_through_formatter(action, logger_name: str, debug: bool = False) -> str:
    """做 action，返回魔镜日志格式（errorlog.Formatter）写出来的字；debug=True 时临时打开调试日志。"""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(errorlog.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger, root = logging.getLogger(logger_name), logging.getLogger()
    old_level = root.level
    logger.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    try:
        action()
    finally:
        logger.removeHandler(handler)
        root.setLevel(old_level)
    return buf.getvalue()


def raise_with_screen_text():
    screen_text = SCREEN_TEXT
    return {}[screen_text]


class HookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = (sys.excepthook, threading.excepthook, sys.unraisablehook)
        self.fault_was_on = faulthandler.is_enabled()
        self.tmp = tempfile.TemporaryDirectory()
        errorlog.install(Path(self.tmp.name))

    def tearDown(self) -> None:
        sys.excepthook, threading.excepthook, sys.unraisablehook = self.saved
        faulthandler.disable()
        if errorlog._crash_file is not None:
            errorlog._crash_file.close()
            errorlog._crash_file = None
        if self.fault_was_on:
            faulthandler.enable()
        self.tmp.cleanup()

    def test_thread_error_is_logged(self) -> None:
        def boom():
            raise RuntimeError("线程里出错")
        with self.assertLogs("deskmirror.errors", "ERROR") as cm:
            t = threading.Thread(target=boom, name="probe")
            t.start()
            t.join()
        self.assertIn("probe", cm.output[0])
        self.assertIn("RuntimeError", cm.output[0])

    def test_ui_callback_error_is_logged(self) -> None:
        from PySide6.QtCore import QCoreApplication, QTimer
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])

        def boom():
            raise ValueError("按钮回调里出错")
        with self.assertLogs("deskmirror.errors", "ERROR") as cm:
            QTimer.singleShot(0, boom)
            for _ in range(20):
                QCoreApplication.processEvents()
                if cm.output:
                    break
        self.assertIn("ValueError", cm.output[0])

    def test_thread_error_in_log_file_has_no_screen_text(self) -> None:
        # 错误说明里可能有屏幕上的字（比如 KeyError 的键是认出来的原文）：写进日志文件时只有种类和代码位置
        def boom():
            screen_text = "Tickets are sold at the pier"
            return {}[screen_text]
        text = log_through_formatter(lambda: run_thread(boom), "deskmirror.errors")
        self.assertIn("后台线程 probe 出错停下了", text)
        self.assertIn("KeyError", text)
        self.assertIn("return {}[screen_text]", text)           # 出在哪一行代码
        self.assertNotIn("Tickets are sold", text)

    def test_ignored_error_is_logged(self) -> None:
        class Bad:
            def __del__(self):
                raise RuntimeError("析构时出错")
        with self.assertLogs("deskmirror.errors", "WARNING") as cm:
            b = Bad()
            del b
            gc.collect()
        self.assertIn("RuntimeError", cm.output[0])

    def test_crash_log_is_on(self) -> None:
        self.assertTrue(faulthandler.is_enabled())
        self.assertTrue((Path(self.tmp.name) / "crash.log").exists())


class FormatterTest(unittest.TestCase):
    """老代码里的 log.exception（引擎、翻译线程……）也走这个格式。"""

    def test_caught_error_only_kind_and_place(self) -> None:
        log = logging.getLogger("deskmirror.test.fmt")

        def act():
            try:
                raise_with_screen_text()
            except KeyError:
                log.exception("引擎处理出错")
        text = log_through_formatter(act, "deskmirror.test.fmt")
        self.assertIn("引擎处理出错", text)
        self.assertIn("KeyError", text)
        self.assertIn("return {}[screen_text]", text)
        self.assertNotIn(SCREEN_TEXT, text)

    def test_detail_only_with_debug_log_on(self) -> None:
        log = logging.getLogger("deskmirror.test.fmt")

        def act():
            try:
                raise_with_screen_text()
            except KeyError:
                log.exception("引擎处理出错")
        self.assertIn(SCREEN_TEXT, log_through_formatter(act, "deskmirror.test.fmt", debug=True))


class WorkerErrorTest(unittest.TestCase):
    def test_worker_keeps_screen_text_apart(self) -> None:
        from deskmirror.ocr_worker import job_error
        try:
            raise_with_screen_text()
        except KeyError:
            where, detail = job_error()
        self.assertIn("KeyError", where)
        self.assertNotIn(SCREEN_TEXT, where)
        self.assertIn(SCREEN_TEXT, detail)

    def test_engine_logs_detail_only_at_debug(self) -> None:
        from deskmirror import engine as E
        from deskmirror.config import AppConfig
        from deskmirror.ocr_worker import job_error
        eng = E.Engine(AppConfig(), lambda snap: None)
        eng.jobs[7] = object()                 # 只要任务还登记着
        try:
            raise_with_screen_text()
        except KeyError:
            report = job_error()
        with self.assertLogs("deskmirror.engine", "DEBUG") as cm:
            eng._on_ocr(("error", 7, report))
        shown = [r.getMessage() for r in cm.records if r.levelno >= logging.INFO]
        hidden = [r.getMessage() for r in cm.records if r.levelno == logging.DEBUG]
        self.assertTrue(shown and all(SCREEN_TEXT not in m for m in shown))
        self.assertTrue(any(SCREEN_TEXT in m for m in hidden))


class QtWarningTest(unittest.TestCase):
    def test_same_warning_once_a_minute(self) -> None:
        from PySide6.QtCore import qInstallMessageHandler, qWarning
        prev = errorlog.install_qt()
        try:
            with self.assertLogs("deskmirror.qt", "WARNING") as cm:
                for _ in range(3):
                    qWarning("QPainter::begin: Paint device returned engine == 0")
                qWarning("另一句")
        finally:
            qInstallMessageHandler(prev)
        self.assertEqual(len(cm.output), 2)
        self.assertIn("Paint device", cm.output[0])


class ThrottleTest(unittest.TestCase):
    def test_counts_what_it_held_back(self) -> None:
        t = errorlog.Throttle(60.0)
        self.assertEqual(t.hit("a", now=0.0), 0)
        self.assertIsNone(t.hit("a", now=10.0))
        self.assertIsNone(t.hit("a", now=59.0))
        self.assertEqual(t.hit("b", now=59.5), 0)
        self.assertEqual(t.hit("a", now=61.0), 2)      # 过了一分钟再记，带上中间压下的 2 次
        self.assertIsNone(t.hit("a", now=62.0))

    def test_forgets_when_full(self) -> None:
        t = errorlog.Throttle(60.0, limit=3)
        for k in "abc":
            t.hit(k, now=0.0)
        self.assertEqual(t.hit("d", now=1.0), 0)
        self.assertEqual(t.hit("a", now=2.0), 0)       # 记满清空过：a 当作第一次


if __name__ == "__main__":
    unittest.main()
