"""没接住的错误、Qt 警告、崩溃记录：都要进日志（没有控制台时 Python 默认会把它们丢掉）。"""
import faulthandler
import gc
import logging
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from deskmirror import errorlog  # noqa: E402


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

    def test_error_text_only_in_debug_log(self) -> None:
        # 错误说明里可能有屏幕上的字（比如 KeyError 的键是认出来的原文）：只进调试日志
        def boom():
            screen_text = "Tickets are sold at the pier"
            return {}[screen_text]
        with self.assertLogs("deskmirror.errors", "DEBUG") as cm:
            t = threading.Thread(target=boom, name="probe")
            t.start()
            t.join()
        shown = "\n".join(r.getMessage() for r in cm.records if r.levelno >= logging.INFO)
        debug = "\n".join(r.getMessage() for r in cm.records if r.levelno == logging.DEBUG)
        self.assertIn("KeyError", shown)
        self.assertIn("return {}[screen_text]", shown)          # 出在哪一行代码
        self.assertNotIn("Tickets are sold", shown)
        self.assertIn("Tickets are sold", debug)

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
