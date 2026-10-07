"""Windows 10 上的色键窗口（ui/layered.py）和截图模式的窗口登记（离屏，不弹窗口）。"""
from __future__ import annotations

import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import deskmirror  # noqa: E402,F401  预加载 DLL
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from deskmirror import winapi  # noqa: E402
from deskmirror.config import StyleConfig  # noqa: E402
from deskmirror.ui import layered  # noqa: E402
from deskmirror.ui.render import Renderer, _binarize  # noqa: E402
from tests.test_render import _app, item  # noqa: E402


def _pixels(img: QImage) -> np.ndarray:
    """BGRA，颜色不预乘。"""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    return np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy()


def _rgb(img: QImage, x: int, y: int) -> tuple[int, int, int]:
    c = img.pixelColor(x, y)
    return c.red(), c.green(), c.blue()


class ColorKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        _app()
        self._orig = layered._colorkey
        layered._colorkey = True

    def tearDown(self) -> None:
        layered._colorkey = self._orig

    def test_binarize_keeps_only_opaque_or_clear_pixels(self) -> None:
        img = QImage(4, 1, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(0, 0, 1, 1, QColor(200, 100, 50))
        p.fillRect(1, 0, 1, 1, QColor(200, 100, 50, 200))     # 多于一半：变成不透明，颜色不变
        p.fillRect(2, 0, 1, 1, QColor(200, 100, 50, 60))      # 少于一半：去掉
        p.fillRect(3, 0, 1, 1, QColor(*layered.KEY))          # 正好是色键：挪开一点，不然会变成透明
        p.end()
        px = _pixels(_binarize(img))[0]
        self.assertEqual(sorted(set(px[:, 3].tolist())), [0, 255])
        self.assertEqual(tuple(px[0, :3].tolist()), (50, 100, 200))
        self.assertTrue(all(abs(int(a) - b) <= 2 for a, b in zip(px[1, :3], (50, 100, 200))))
        self.assertEqual(px[2, 3], 0)
        self.assertNotEqual((px[3, 2], px[3, 1], px[3, 0]), layered.KEY)

    def test_plates_are_always_opaque(self) -> None:
        st = StyleConfig()
        st.plate_opacity = 0.5
        r = Renderer(st, binary=True)
        self.assertEqual(r.style.plate_opacity, 1.0)
        alpha = _pixels(r.get(item("Boats leave every hour.", (100, 100, 400, 130))).image)[..., 3]
        self.assertTrue(set(np.unique(alpha).tolist()) <= {0, 255})
        self.assertGreater(float((alpha == 255).mean()), 0.5, "底板盖住原文")
        self.assertEqual(Renderer(st).style.plate_opacity, 0.5, "半透明窗口照设置来")

    def test_mirror_frame_has_an_invisible_hit_window_and_a_visible_layer(self) -> None:
        from deskmirror.ui.mirror import BAND, MirrorFrame
        f = MirrorFrame((300, 300, 900, 700), "#3d8bfd")
        try:
            vis = f.visual()
            self.assertIsNot(vis, f)
            self.assertEqual(vis.geometry(), f.geometry())
            f.set_mirror((320, 330, 1000, 760))
            self.assertEqual(vis.geometry(), f.geometry(), "大小、位置跟着走")
            inner = f._local(f.mirror)
            inside = (inner.center().x(), inner.center().y())
            band = (inner.left() - BAND + 1, inner.center().y())
            tab = f._local(f._tab)
            corner = (tab.left() + 3, tab.bottom() - 3)
            hit, look = f.grab().toImage(), vis.grab().toImage()
            self.assertEqual(_rgb(hit, *inside), layered.KEY, "框内透明，鼠标穿过去")
            self.assertNotEqual(_rgb(hit, *band), layered.KEY, "框外的抓取带接鼠标（窗口整体看不见）")
            self.assertNotEqual(_rgb(hit, *corner), layered.KEY, "标签接鼠标")
            self.assertEqual(_rgb(look, *inside), layered.KEY)
            self.assertEqual(_rgb(look, *band), layered.KEY, "抓取带看不见")
            self.assertEqual(_rgb(look, *corner), (28, 30, 36), "标签不透明")
            f.set_grab_mode(True)
            self.assertNotEqual(_rgb(f.grab().toImage(), *inside), layered.KEY, "按住拖动键时框内也接鼠标")
            self.assertEqual(_rgb(vis.grab().toImage(), *inside), layered.KEY, "看起来还是透明的")
            shot = layered.grab(vis, QRect(0, 0, vis.width(), vis.height())).toImage()
            self.assertEqual(shot.pixelColor(*inside).alpha(), 0, "截译图时色键的地方当透明")
            self.assertEqual(shot.pixelColor(*corner).alpha(), 255)
        finally:
            f.close()

    def test_overlay_background_is_the_key_colour(self) -> None:
        from deskmirror.ui.overlay import Overlay, UiState
        mon = winapi.Monitor("TEST", (0, 0, 800, 600), (0, 0, 800, 560), 96, True)
        o = Overlay(mon, UiState(Renderer(StyleConfig(), binary=True)))
        try:
            self.assertEqual(_rgb(o.grab(QRect(10, 10, 40, 40)).toImage(), 5, 5), layered.KEY)
            self.assertEqual(layered.grab(o, QRect(10, 10, 40, 40)).toImage().pixelColor(5, 5).alpha(), 0)
        finally:
            o.close()


class CaptureVisibilityTest(unittest.TestCase):
    def tearDown(self) -> None:
        winapi.set_capture_visible(False)

    def test_screenshot_mode_bookkeeping(self) -> None:
        gone = 0x7FFF0001                      # 已经关掉的窗口
        winapi._excluded.add(gone)
        winapi.set_capture_visible(True)
        self.assertNotIn(gone, winapi._excluded, "关掉了的窗口不再管")
        failures = len(winapi.capture_failures)
        self.assertTrue(winapi.exclude_from_capture(gone), "截图模式里新建的窗口先不隐身")
        self.assertIn(gone, winapi._excluded, "记下来，截图模式结束时再隐身")
        self.assertEqual(len(winapi.capture_failures), failures)
        winapi.set_capture_visible(False)
        self.assertNotIn(gone, winapi._excluded)


if __name__ == "__main__":
    unittest.main()
