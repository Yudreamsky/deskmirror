"""液态玻璃皮肤（ui/glass.py）：圆角矩形的深度和法线、边上往里取样（越靠外沿越远、三色略有不同）、
边框四条正好铺满一圈、色键窗口里整块不透明且不出现色键的颜色、深浅随背景换（带回差）、
后面的画面什么时候重取（引擎报告的变化 / 自己隔一会儿截一次 / 截图模式不动），
以及换成玻璃以后魔镜的边框、标签、球的位置和画法。离屏，不弹窗口；截屏和显示器是假的。"""
from __future__ import annotations

import os
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import deskmirror  # noqa: E402,F401  预加载 DLL
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from deskmirror import config, geom, winapi  # noqa: E402
from deskmirror.ui import dock, glass, layered, mirror  # noqa: E402
from tests.test_dock import MAIN, _Clock, _Frame  # noqa: E402
from tests.test_render import _app  # noqa: E402


def _alpha(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return a[:, 3:img.width() * 4:4].copy()


def _pixels(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return a[:, :img.width() * 4].reshape(img.height(), img.width(), 4).copy()


def _stripes(h: int, w: int) -> np.ndarray:
    """测试用的背景：竖条纹（看得出往哪边取样）。"""
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = (np.arange(w) * 37 % 256)[None, :, None]
    img[..., 3] = 255
    return img


class GlassOn(unittest.TestCase):
    """测试期间打开液态玻璃，结束时恢复。"""

    def setUp(self) -> None:
        self._was = glass.active()
        glass.set_active(True)
        self.addCleanup(glass.set_active, self._was)


class ShapeTest(unittest.TestCase):
    def test_depth_and_normal_of_rounded_rect(self) -> None:
        ys, xs = np.mgrid[0:60, 0:100].astype(np.float32)
        depth, nx, ny = glass._sdf(100, 60, 10, xs, ys)
        self.assertAlmostEqual(float(depth[30, 0]), 0.5, places=4, msg="最左一列像素中心离边 0.5")
        self.assertAlmostEqual(float(depth[30, 50]), 29.5, places=4)
        self.assertEqual((float(nx[30, 0]), float(ny[30, 0])), (-1.0, 0.0), "左边的法线朝左")
        self.assertEqual((float(nx[0, 50]), float(ny[0, 50])), (0.0, -1.0), "上边朝上")
        self.assertLess(float(depth[0, 0]), 0, "圆角外面的像素在形状外")
        self.assertAlmostEqual(float(nx[1, 1]), float(ny[1, 1]), places=4, msg="角上的法线沿对角线")
        self.assertLess(float(nx[1, 1]), 0)

    def test_lens_samples_inward_more_near_the_edge(self) -> None:
        lens = glass.Lens(200, 100, 18, 11, 6.5, (0, 30, 20, 70), ring=True)
        mx, _my = lens.maps[2]                       # 红色通道（位移倍数 1）
        p = lens.pad
        shift = mx[20, :] - (np.arange(20) + p)      # 左边一条横线上每个像素往哪取样
        self.assertAlmostEqual(float(shift[0]), 6.5 * (0.45 * (1 - 0.5 / 11) + 0.55 * (1 - np.sqrt(
            1 - (1 - 0.5 / 11) ** 2))), places=3, msg="最外一列往里取样最远")
        self.assertTrue(np.all(np.diff(shift[:11]) < 0), "越往里取得越近")
        self.assertTrue(np.allclose(shift[11:], 0), "玻璃以里不动")
        blue = lens.maps[0][0][20, 0] - p
        self.assertGreater(float(blue), float(shift[0]), "蓝色偏得多一点：边上一丝色散")

    def test_rim_parts_tile_the_ring(self) -> None:
        rim = glass.Rim(300, 200)
        W, H = rim.outer
        hits = np.zeros((H, W), np.int32)
        for lens in rim.lenses.values():
            x0, y0, x1, y1 = lens.area
            hits[y0:y1, x0:x1] += 1
        self.assertEqual(hits.max(), 1, "四条不重叠")
        ring = np.zeros((H, W), bool)
        ring[:glass.BAND, :] = ring[-glass.BAND:, :] = True
        ring[:, :glass.BAND] = ring[:, -glass.BAND:] = True
        self.assertTrue(np.all(hits[ring] == 1), "整圈都有")
        self.assertEqual(set(rim.lenses), {"t", "b", "l", "r"})

    def test_ring_is_transparent_inside(self) -> None:
        rim = glass.Rim(300, 200)
        img = rim.lenses["l"].render(None)
        a = _alpha(img)
        self.assertTrue(np.all(a[:, glass.BAND + 1:] == 0) if a.shape[1] > glass.BAND + 1 else True)
        self.assertTrue(np.all(a[:, 2:glass.BAND - 1] > 0), "玻璃那一圈看得见")
        top = _alpha(rim.lenses["t"].render(None))
        self.assertEqual(int(top[0, 0]), 0, "圆角外面透明")
        self.assertEqual(int(top[glass.RADIUS - 1, glass.RADIUS + 20]), 0, "上边那条伸进镜框里的部分透明")

    def test_render_uses_the_backdrop(self) -> None:
        lens = glass.Lens(200, 100, 18, 11, 6.5, (0, 30, 20, 70), ring=True)
        x0, y0, x1, y1 = lens.patch_rect(0, 0)
        patch = _stripes(y1 - y0, x1 - x0)
        px = _pixels(lens.render(patch, sat=1.0, lift=0.0))
        flat = _pixels(lens.render(None))
        self.assertGreater(len({tuple(v) for v in px[20, :11, :3]}), 3, "取到了条纹")
        self.assertFalse(np.array_equal(px[20, :11, :3], flat[20, :11, :3]))
        self.assertEqual(len({tuple(v) for v in flat[5:35, 5, :3]}), 1, "没截到时：同一深度一样的颜色")

    def test_solid_is_opaque_and_never_the_key_colour(self) -> None:
        lens = glass.Lens(120, 40, 20, 9, 6.0, (0, 0, 120, 40))
        x0, y0, x1, y1 = lens.patch_rect(0, 0)
        patch = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
        patch[...] = (layered.KEY[2], layered.KEY[1], layered.KEY[0], 255)      # 后面正好是色键的颜色
        lens.shade[:] = 0
        px = _pixels(lens.render(patch, sat=1.0, lift=0.0, solid=True))
        a = px[..., 3]
        self.assertTrue(set(np.unique(a)) <= {0, 255}, "色键窗口里没有半透明")
        inside = a == 255
        key = (px[..., 2] == layered.KEY[0]) & (px[..., 1] == layered.KEY[1]) & (px[..., 0] == layered.KEY[2])
        self.assertFalse(np.any(key & inside), "碰上色键的颜色挪开了一点")
        self.assertEqual(int(a[20, 0]), 255, "外沿再往外一圈也画上（抗锯齿混好背景）")

    def test_tone_follows_brightness_with_hysteresis(self) -> None:
        t = glass.Tone()
        self.assertFalse(t.update(0.6))
        self.assertTrue(t.update(0.3), "暗了：换烟灰玻璃")
        self.assertTrue(t.dark)
        self.assertFalse(t.update(0.48), "回到临界附近不来回换")
        self.assertTrue(t.update(0.6))
        self.assertFalse(t.dark)
        self.assertFalse(t.update(None))


class _Cap:
    def __init__(self) -> None:
        self.lock = threading.Lock()


class _Mon:
    def __init__(self, rect, img) -> None:
        self.rect = rect
        self.origin = rect[:2]
        self.bgra = img
        self.cap = _Cap()

    def local(self, r):
        return geom.shift(r, -self.origin[0], -self.origin[1])


class _Engine:
    def __init__(self) -> None:
        self.working = True
        self.mons = [_Mon((0, 0, 400, 300), _stripes(300, 400))]
        self.seq = 0
        self.rects: list = []

    def changes_since(self, seq):
        return self.seq, (self.rects if seq < self.seq else [])


class BackdropTest(unittest.TestCase):
    def test_follows_engine_changes(self) -> None:
        eng = _Engine()
        bd = glass.Backdrop(eng)
        bd.begin()
        r = (10, 10, 60, 30)
        first = bd.fresh("o", "t", r, 1.0)
        self.assertEqual(first.shape, (20, 50, 4), "第一次一定取")
        bd.begin()
        self.assertIsNone(bd.fresh("o", "t", r, 1.1), "引擎说没变：不重取")
        eng.seq, eng.rects = 1, [(200, 200, 220, 220)]
        bd.begin()
        self.assertIsNone(bd.fresh("o", "t", r, 1.2), "变的地方不在这块后面")
        eng.seq, eng.rects = 2, [(50, 0, 70, 12)]
        bd.begin()
        self.assertIsNone(bd.fresh("o", "t", r, 1.3), "说变了、其实画面一样（魔镜自己的窗口重画）：不重画")
        eng.mons[0].bgra[10:12, 50:60] = 1
        eng.seq, eng.rects = 3, [(50, 0, 70, 12)]
        bd.begin()
        self.assertIsNotNone(bd.fresh("o", "t", r, 1.3), "真的变了")
        self.assertIsNotNone(bd.fresh("o", "t", (11, 10, 61, 30), 1.3), "位置变了：重取")
        bd.frozen = True
        self.assertIsNone(bd.fresh("o", "t", (12, 10, 62, 30), 1.4), "截图模式：不动")

    def test_polls_itself_when_engine_is_not_capturing(self) -> None:
        eng = _Engine()
        eng.working = False
        bd = glass.Backdrop(eng)
        shots = [np.full((20, 50, 4), 10, np.uint8)]
        with mock.patch.object(glass.Backdrop, "grab", lambda self, rect: shots[-1].copy()):
            self.assertIsNotNone(bd.fresh("o", "t", (0, 0, 50, 20), 1.0))
            self.assertIsNone(bd.fresh("o", "t", (0, 0, 50, 20), 1.1), "没到时间不截")
            self.assertIsNone(bd.fresh("o", "t", (0, 0, 50, 20), 1.3), "截了，和上次一样")
            shots.append(np.full((20, 50, 4), 99, np.uint8))
            self.assertIsNotNone(bd.fresh("o", "t", (0, 0, 50, 20), 1.6), "变了")
        bd.forget("o")
        self.assertEqual(bd._seen, {})

    def test_grab_pads_beyond_the_screen(self) -> None:
        eng = _Engine()
        bd = glass.Backdrop(eng)
        self.assertEqual(bd.grab((5, 5, 25, 15)).shape, (10, 20, 4), "引擎在截的屏：直接从它的缓冲区复制")
        self.assertTrue(np.array_equal(bd.grab((5, 5, 25, 15)), eng.mons[0].bgra[5:15, 5:25]))
        eng.working = False
        with mock.patch.object(winapi, "monitors", lambda: [MAIN]):
            class _Shot:
                def __init__(self, w, h):
                    self.bgra = bytes(np.full((h, w, 4), 77, np.uint8))

            class _Mss:
                def grab(self, mon):
                    return _Shot(mon["width"], mon["height"])

            bd._mss = _Mss()
            img = bd.grab((-5, 0, 20, 10))
        self.assertEqual(img.shape, (10, 25, 4), "伸出屏幕的部分用边上的像素补齐")
        self.assertTrue(np.all(img == 77))


class LayoutTest(GlassOn):
    def test_classic_geometry_is_unchanged(self) -> None:
        glass.set_active(False)
        self.assertEqual(mirror.band(), 7)
        self.assertEqual(mirror.chrome_top(), 33)
        self.assertEqual(mirror.grip_offset(), (6, -19))
        self.assertEqual(dock.frame_shape((100, 100, 300, 200)), dock.Shape(98, 98, 204, 104, 0.0))

    def test_glass_geometry(self) -> None:
        self.assertEqual(mirror.band(), glass.BAND)
        self.assertEqual(mirror.chrome_top(), glass.BAND + glass.GAP + mirror.TAB_H)
        gx, gy = mirror.grip_offset()
        self.assertEqual(gy, -(glass.BAND + glass.GAP + mirror.TAB_H) + mirror.TAB_H // 2, "抓手在浮起的标签中间")
        s = dock.frame_shape((100, 100, 300, 200))
        self.assertEqual((s.x, s.y, s.w, s.h), (100 - glass.BAND, 100 - glass.BAND, 200 + 2 * glass.BAND,
                                                100 + 2 * glass.BAND), "变形从玻璃的外沿开始")
        self.assertEqual(dock._radius(s, 0.0), glass.RADIUS)
        self.assertEqual(dock._radius(s, 1.0), s.h / 2)


class _Backdrop:
    """假的后面画面：哪里都是条纹，每次都说要重画。"""

    def __init__(self) -> None:
        self.frozen = False
        self.calls: list = []

    def fresh(self, owner, part, rect, now, force=False):
        self.calls.append((part, rect, force))
        return _stripes(rect[3] - rect[1], rect[2] - rect[0])

    def grab(self, rect):
        return _stripes(rect[3] - rect[1], rect[2] - rect[0])


class FrameTest(GlassOn):
    def setUp(self) -> None:
        super().setUp()
        _app()
        self._ck = layered._colorkey
        layered._colorkey = False
        self.addCleanup(setattr, layered, "_colorkey", self._ck)
        for p in (mock.patch.object(winapi, "exclude_from_capture", lambda hwnd: True),
                  mock.patch.object(winapi, "monitors", lambda: [MAIN])):
            p.start()
            self.addCleanup(p.stop)

    def test_frame_layout_and_refresh(self) -> None:
        f = mirror.MirrorFrame((400, 300, 1000, 700), "#3D8BFD")
        self.addCleanup(f.close)
        tab = f._tab
        self.assertEqual(tab[1], 300 - glass.BAND - glass.GAP - mirror.TAB_H, "标签浮在玻璃上方")
        self.assertEqual(tab[0], 400 - glass.BAND)
        self.assertEqual((f.x(), f.y()), (400 - glass.BAND, tab[1]))
        self.assertEqual(f.y() + f.height(), 700 + glass.BAND)
        f.backdrop = _Backdrop()
        f.show()
        self.assertEqual({c[0] for c in f.backdrop.calls}, {"t", "b", "l", "r", "tab"}, "一出来就取一遍后面的画面")
        self.assertTrue(all(c[2] for c in f.backdrop.calls))
        n = f.glass_renders
        f.backdrop.calls.clear()
        f.glass_refresh(5.0)
        self.assertEqual(f.glass_renders, n + 5)
        parts = f.glass_parts()
        self.assertTrue(geom.contains(parts["l"], (400 - glass.BAND, 330, 400, 670)), "左边那条连同取样的余量")
        pm = f.grab()
        a = _alpha(pm.toImage())
        self.assertEqual(int(a[400 - f.y(), 700 - f.x()]), 0, "镜框里面透明（鼠标穿透）")
        self.assertEqual(int(a[500 - f.y(), 400 - glass.BAND + 4 - f.x()]), 255, "左边的玻璃不透明")
        self.assertEqual(int(a[tab[1] + 13 - f.y(), tab[0] + 40 - f.x()]), 255, "标签")

    def test_switching_back_to_classic(self) -> None:
        f = mirror.MirrorFrame((400, 300, 1000, 700), "#3D8BFD")
        self.addCleanup(f.close)
        glass.set_active(False)
        f._layout()
        self.assertEqual(f._tab[1], 300 - 7 - mirror.TAB_H + 1)
        self.assertEqual((f.x(), f.y()), (393, 300 - 7 - mirror.TAB_H + 1))
        img = f.grab().toImage()
        self.assertEqual(int(_alpha(img)[400 - f.y(), 700 - f.x()]), 0)


class BallTest(GlassOn):
    def setUp(self) -> None:
        super().setUp()
        _app()
        self._ck = layered._colorkey
        layered._colorkey = False
        self.addCleanup(setattr, layered, "_colorkey", self._ck)
        self.clock = _Clock()
        for p in (mock.patch.object(winapi, "monitors", lambda: [MAIN]),
                  mock.patch.object(winapi, "exclude_from_capture", lambda hwnd: True),
                  mock.patch.object(dock.time, "perf_counter", self.clock)):
            p.start()
            self.addCleanup(p.stop)
        self.balls: dict = {}
        self.d = dock.Docker(_Frame((600, 300, 1240, 660)), {}, self.balls)
        self.d.backdrop = _Backdrop()
        self.addCleanup(self.d.close)

    def test_docked_ball_is_glass_and_follows_the_slide(self) -> None:
        d = self.d
        d.dock_now({"edge": "r", "x": 1887, "y": 400})
        d.glass_refresh(self.clock.t)
        gb = self.balls[id(d)]
        s = d.shape()
        self.assertEqual(gb.at, (round(s.x), round(s.y)))
        self.assertTrue(gb.matches(s))
        self.clock.t += 1.0
        d.hover(True)
        self.assertIsNotNone(d._slide_bg, "滑出来之前先截好经过的那一块")
        n = d.glass_renders
        for _ in range(200):
            if d.live is None:
                break
            self.clock.t += 1 / 60
            d._step()
        self.assertGreater(d.glass_renders - n, 5, "滑动途中每帧跟着重画")
        self.assertTrue(gb.matches(d.shape()), "停下的位置也画好了")
        img = QImage(1920, 1080, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        dock.paint_shape(p, d.shape(), 0, 0, QColor("#3D8BFD"), False, gb)
        p.end()
        cx, cy = round(d.shape().x + d.shape().w / 2), round(d.shape().y + d.shape().h / 2)
        self.assertEqual(int(_alpha(img)[cy, cx]), 255, "球是实心的玻璃")

    def test_morph_uses_glass_look(self) -> None:
        d = self.d
        d.frame_press(QPoint(700, 285))
        d.move(QPoint(500, 300))
        d.move(QPoint(20, 300))
        s = d.shape()
        self.assertIsNotNone(s)
        img = QImage(1920, 1080, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        dock.paint_shape(p, s, 0, 0, QColor("#3D8BFD"), False, self.balls.get(id(d)))
        p.end()
        self.assertGreater(int(_alpha(img).max()), 0)


class ConfigTest(unittest.TestCase):
    def test_skin_choice(self) -> None:
        c = config.AppConfig()
        self.assertEqual(c.style.skin, "classic", "默认经典样子")
        c.style.skin = "glass"
        self.assertEqual(config.validate(c).style.skin, "glass")
        c.style.skin = "frosted"
        self.assertEqual(config.validate(c).style.skin, "classic")


if __name__ == "__main__":
    unittest.main()
