"""显示器变了（开机时先是 1024×768、改分辨率、插拔显示器）：界面要按新的显示器重建译文层，引擎要重新截屏。
不碰真的屏幕：显示器和截屏都是假的。"""
from __future__ import annotations

import unittest

import numpy as np

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror import engine as E
from deskmirror import winapi
from deskmirror.app import _monitor_sig, _monitor_text, _Settled

from tests.test_engine import H, W, _NoCapture, add_block, make_engine

SMALL = winapi.Monitor(r"\\.\DISPLAY1", (0, 0, 1024, 768), (0, 0, 1024, 728), 96, True)
BIG = winapi.Monitor(r"\\.\DISPLAY1", (0, 0, 3840, 2160), (0, 0, 3840, 2112), 144, True)
RIGHT = winapi.Monitor(r"\\.\DISPLAY2", (3840, 0, 6400, 1600), (3840, 0, 6400, 1600), 96, False)


class SignatureTest(unittest.TestCase):
    def test_resolution_change_is_a_change(self) -> None:
        self.assertNotEqual(_monitor_sig([SMALL]), _monitor_sig([BIG]))
        self.assertNotEqual(_monitor_sig([BIG]), _monitor_sig([BIG, RIGHT]))     # 插上一块
        self.assertEqual(_monitor_sig([BIG]), _monitor_sig([winapi.Monitor(BIG.device, BIG.rect, (0, 0, 3840, 2000),
                                                                          BIG.dpi, True)]))   # 只是任务栏变了
        self.assertEqual(_monitor_text(_monitor_sig([SMALL, RIGHT])), r"\\.\DISPLAY1 1024x768, \\.\DISPLAY2 2560x1600")


class SettledTest(unittest.TestCase):
    def test_new_value_counts_once_it_stays(self) -> None:
        s = _Settled("1024", delay=1.0)
        self.assertFalse(s.update("1024", 0.0))
        self.assertFalse(s.update("3840", 1.0))          # 刚变：先等等
        self.assertFalse(s.update("3840", 1.5))
        self.assertTrue(s.update("3840", 2.0))           # 停稳 1 秒：算数
        self.assertEqual(s.value, "3840")
        self.assertFalse(s.update("3840", 3.0))

    def test_flicker_in_between_does_not_count(self) -> None:
        s = _Settled("A", delay=1.0)
        s.update("B", 0.0)
        s.update("C", 0.8)                               # 中间闪过的样子：重新计时
        self.assertFalse(s.update("C", 1.5))
        self.assertTrue(s.update("C", 1.9))
        s2 = _Settled("A", delay=1.0)
        s2.update("B", 0.0)
        self.assertFalse(s2.update("A", 0.5))            # 又变回来了：什么都不用做
        self.assertFalse(s2.update("B", 1.2))


class EngineMonitorsTest(unittest.TestCase):
    def test_engine_takes_the_new_monitor(self) -> None:
        page = np.full((H, W), 255, np.uint8)
        eng, m, win, sc = make_engine(page)
        old_cap = m.cap
        closed = []
        old_cap.close = lambda: closed.append(True)
        inside = add_block(eng, sc, (10, 100, 300, 122), page[100:122, 10:300])
        outside = add_block(eng, sc, (10, 1100, 300, 1122), page[1100:1122, 10:300])
        eng._hashes[(0, 1)] = (5, None)
        new = winapi.Monitor("NEW", (0, 0, W, 1000), (0, 0, W, 1000), 96, True)
        made = []

        def fake_mon(i, info):
            made.append(info.device)
            w, h = info.rect[2] - info.rect[0], info.rect[3] - info.rect[1]
            th, tw = -(-h // E.TILE), -(-w // E.TILE)
            mo = E.Mon(i, info, _NoCapture(), (info.rect[0], info.rect[1]), (w, h), np.zeros((h, w), np.uint8),
                       np.zeros((h, w), np.uint8), None, np.zeros((th, tw)), np.zeros((th, tw), np.float32),
                       np.zeros((th, tw), bool), 0.0)
            mo.last_chg, mo.chg_start, mo.last_ocr = np.zeros((th, tw)), np.zeros((th, tw)), np.zeros((th, tw))
            mo.snap_backoff = np.ones((th, tw), np.float32)
            return mo
        eng._make_mon = fake_mon
        real = winapi.monitors
        winapi.monitors = lambda: [new]
        try:
            eng.set_mirrors([(0, 0, 400, 300)])
            eng.monitors_changed()
            self.assertTrue(eng._monitors_dirty)
            eng._reset_monitors()
        finally:
            winapi.monitors = real
        self.assertEqual(made, ["NEW"])
        self.assertEqual(closed, [True], "旧的截屏关掉")
        self.assertEqual([mo.info.device for mo in eng.mons], ["NEW"])
        self.assertIn(inside.bid, eng.blocks)
        self.assertIsNone(inside.ok_rect, "留下的段落重新核对")
        self.assertNotIn(outside.bid, eng.blocks, "新屏幕外面的删掉")
        self.assertEqual(eng._hashes, {}, "按旧帧号记的行哈希不再用")


if __name__ == "__main__":
    unittest.main()
