"""译文交给系统合成器（ui/glide.py）以后的离线单元测试：分组和裁剪、引擎给的位移曲线（滚轮、速度、停下）、
滚轮每格像素取中位数、按终点拉伸、快速找位移、帧的显示时刻，以及原来的译文层不再画镜内的译文（截图时照画）。
不建真的合成器窗口（那要在屏幕上开窗口，由 record.py 的 glidecheck、scrollperf 实测）。"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import deskmirror  # noqa: E402,F401  预加载 DLL
import numpy as np  # noqa: E402

from deskmirror import capture, pixels, wheelmodel  # noqa: E402
from deskmirror import engine as E  # noqa: E402
from deskmirror.scene import DrawItem, Snapshot  # noqa: E402
from deskmirror.ui import glide  # noqa: E402
from tests.test_engine import H, W, add_block, make_engine  # noqa: E402
from tests.test_pixels import text_page  # noqa: E402


def _item(bid: int, rect, cid: int = 7, clips=None) -> DrawItem:
    return DrawItem(bid, 1, rect, rect, tuple(clips or [(0, 0, 2000, 2000)]), "译文", (255, 255, 255), (0, 0, 0),
                    20, 1, 16.0, cid=cid)


class PlanTest(unittest.TestCase):
    def test_overlapping_mirrors_are_cut_apart(self) -> None:
        pieces = glide.disjoint([(0, 0, 100, 100), (50, 50, 150, 150)])
        area = sum((r - l) * (b - t) for l, t, r, b in pieces)
        self.assertEqual(area, 100 * 100 * 2 - 50 * 50, "重叠的部分只算一次")
        for i, a in enumerate(pieces):
            for b in pieces[i + 1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], "切开的几块互不重叠")

    def test_items_grouped_by_canvas_and_clipped_to_mirror(self) -> None:
        mirror = (100, 100, 500, 400)
        inside = _item(1, (120, 150, 300, 170))
        other_canvas = _item(2, (120, 200, 300, 220), cid=8)
        far = _item(3, (120, 900, 300, 920))
        plans = glide.plan([inside, other_canvas, far], {7: (0, -50), 8: (0, 0)}, {}, [mirror])
        self.assertEqual(set(plans), {(7, 0, 0), (8, 0, 0)}, "每个画布一组；远在镜外、也不会滚进来的块不挂")
        g = plans[(7, 0, 0)]
        self.assertEqual(g.clip, mirror)
        self.assertEqual([it.bid for it in g.items], [1])
        self.assertEqual(g.origin, (0, -50))

    def test_item_that_will_scroll_in_is_attached_early(self) -> None:
        mirror = (100, 100, 500, 400)
        below = _item(4, (120, 600, 300, 620))
        # 画布接下来会往上走 300 像素：现在在镜子下面的块，曲线走完时会进到镜子里
        curve = ((1.0, 0, 0), (1.2, 0, -300))
        plans = glide.plan([below], {7: (0, 0)}, {7: curve}, [mirror])
        self.assertIn((7, 0, 0), plans)
        self.assertEqual(glide.travel(curve, (0, 0)), (0.0, -300.0, 0.0, 0.0))

    def test_visible_parts_of_window_make_separate_clips(self) -> None:
        mirror = (0, 0, 1000, 1000)
        it = _item(5, (100, 100, 700, 120), clips=[(0, 0, 400, 1000), (600, 0, 1000, 1000)])
        plans = glide.plan([it], {7: (0, 0)}, {}, [mirror])
        self.assertEqual(sorted(g.clip for g in plans.values()), [(0, 0, 400, 1000), (600, 0, 1000, 1000)])


class CurveHelpersTest(unittest.TestCase):
    def test_simplify_keeps_bends_and_ends(self) -> None:
        line = [(t / 100, 0.0, t * 2.0) for t in range(11)]
        self.assertEqual(E._simplify(line), [line[0], line[-1]], "一条直线只留两头")
        bent = [(t / 100, 0.0, float(min(t, 5) * 10)) for t in range(11)]
        out = E._simplify(bent)
        self.assertIn(bent[5], out, "拐弯的地方要留下")
        self.assertEqual((out[0], out[-1]), (bent[0], bent[-1]))

    def test_combine_adds_parent_and_child_motion(self) -> None:
        one = E._combine_curves((("v", [(1.0, 0.0), (1.1, -40.0)]),), 10, 20)
        self.assertEqual(one, ((1.0, 10, 20.0), (1.1, 10, -20.0)))
        two = E._combine_curves((("v", [(1.0, 0.0), (1.1, -40.0)]), ("h", [(1.0, 0.0), (1.1, 6.0)])), 0, 0)
        self.assertEqual(two[-1], (1.1, 6.0, -40.0), "竖着滚的外层和横着滚的里层叠加")


class WheelModelTest(unittest.TestCase):
    def _model(self) -> wheelmodel.CurveModel:
        curve = np.clip(wheelmodel.GRID / 300.0, 0, 1)
        return wheelmodel.CurveModel(100.0, 5, curve, 5)

    def test_one_bad_episode_does_not_skew_pixels_per_notch(self) -> None:
        m = self._model()
        bad = wheelmodel.Episode(1, "k", "v", True, wheels=[(0.0, 2.0)], shifts=[(0.1, 140), (0.2, 137)])
        wheelmodel.learn(m, bad)       # 第一格没算进来：2 格滚了 277 像素
        self.assertEqual(m.px_per_notch, 100.0, "以前存的平均值当作三次，一次算偏的压不过")
        good = wheelmodel.Episode(1, "k", "v", True, wheels=[(0.0, 3.0)], shifts=[(0.1, 150), (0.2, 150)])
        wheelmodel.learn(m, good)
        self.assertEqual(m.px_per_notch, 100.0)

    def test_ratios_survive_save_and_load(self) -> None:
        import pathlib
        import tempfile
        m = self._model()
        m.ratios = [100.0, 101.0, 99.0]
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "w.json"
            wheelmodel.save_models(path, {"k": m})
            back = wheelmodel.load_models(path)["k"]
        self.assertEqual(back.ratios, [100.0, 101.0, 99.0])

    def test_remaining_lands_on_the_target(self) -> None:
        m = self._model()
        wheels = [(0.0, 3.0)]
        # 0.1 秒时曲线说走了 100，实测只走了 60：剩下的 240 要在曲线剩下的时间里走完
        rem = m.remaining(wheels, 0.1, 60.0)
        self.assertAlmostEqual(60.0 + rem(1.0), 300.0, places=3)
        self.assertEqual(rem(0.1), 0.0)


class QuickShiftTest(unittest.TestCase):
    def test_finds_shift_near_guess_from_three_strips(self) -> None:
        page = text_page(3000, 900, 5)
        prev, cur = page[400:1400].copy(), page[437:1437].copy()        # 内容上移 37 像素
        self.assertEqual(pixels.quick_shift(prev, cur, (0, 0, 900, 1000), -30, 24)[0], -37)

    def test_no_change_and_wrong_window(self) -> None:
        page = text_page(3000, 900, 6)
        prev = page[400:1400].copy()
        self.assertEqual(pixels.quick_shift(prev, prev.copy(), (0, 0, 900, 1000), 0, 24), (0, 0, 0))
        cur = page[520:1520].copy()                                     # 实际 -120，猜的是 -10 ± 24
        self.assertIsNone(pixels.quick_shift(prev, cur, (0, 0, 900, 1000), -10, 24), "找不到就交给整块找")


class EngineMotionTest(unittest.TestCase):
    def _scrolling(self):
        page = text_page(3000, W, 3)
        eng, m, win, sc = make_engine(page[0:H])
        eng.win_canvas[win.hwnd] = win
        eng.z_order = [win.hwnd]
        eng.visible = {win.hwnd: [(0, 0, W, H)]}
        eng._mirrors = [(0, 0, W, H)]
        b = add_block(eng, sc, (10, 300, 400, 322), page[300:322, 10:400])
        b.state, b.translation = "done", "译文"
        return eng, m, win, sc, b

    def test_velocity_fit_and_stop(self) -> None:
        eng, m, win, sc, _b = self._scrolling()
        t = 10.0
        sc.motion = [(t + i * 0.008, -8, 0.008) for i in range(5)]     # 每 8 毫秒上移 8 像素：-1000 像素/秒
        v, _a = eng._velocity_fit(sc)
        self.assertAlmostEqual(v, -1000.0, delta=1.0)
        eng._vel_shown = {sc.cid}
        eng.glide = True
        curves = eng._motion_curves(t + 0.04)
        pts = curves[sc.cid][1]
        self.assertEqual(pts[0], (sc.motion[-1][0], 0.0), "曲线从最近量到的那一帧开始，位移 0")
        self.assertAlmostEqual(pts[-1][1], -1000.0 * eng.CURVE_VEL_S, delta=0.5)
        # 下一帧看过这块却没动：马上不再外推
        eng._cur_frame_t = sc.motion[-1][0] + 0.012
        eng._frame_moved = {}
        eng._check_stopped(m, [(0, 0, W, H)])
        self.assertIsNone(eng._velocity_fit(sc))

    def test_snapshot_carries_origins_and_curves_only_for_glide(self) -> None:
        eng, m, win, sc, b = self._scrolling()
        got = []
        eng._publish_cb = got.append
        sc.offset[1] = -40
        b.ok_rect = b.screen_rect()
        eng.glide = False
        eng._publish(force=True)
        self.assertEqual(got[-1].curves, {})
        self.assertEqual(got[-1].origins[sc.cid], (0, -40))
        it = got[-1].items[0]
        self.assertEqual((it.cid, it.rect[1] - got[-1].origins[sc.cid][1]), (sc.cid, 300), "块在画布里的位置")
        t = 20.0
        sc.motion = [(t + i * 0.008, -8, 0.008) for i in range(5)]
        eng._vel_shown = {sc.cid}
        eng.glide = True
        with mock.patch("time.perf_counter", return_value=t + 0.04):
            eng._publish(force=True)
        curve = got[-1].curves[sc.cid]
        self.assertEqual(curve[0][1:], (0, -40), "曲线从画布量到的位置开始")
        self.assertLess(curve[-1][2], -40)


class FrameTickTest(unittest.TestCase):
    def test_tick_is_the_compose_vblank_when_plausible(self) -> None:
        with mock.patch.object(capture, "compose_clock", return_value=(10.006, 1 / 240)):
            self.assertEqual(capture.frame_tick(10.0), 10.006)
        with mock.patch.object(capture, "compose_clock", return_value=(10.5, 1 / 240)):
            self.assertAlmostEqual(capture.frame_tick(10.0), 10.0 + 1.5 / 240, "差太远就按报的时刻估")
        with mock.patch.object(capture, "compose_clock", return_value=None):
            self.assertAlmostEqual(capture.frame_tick(10.0), 10.006)


class OverlayLeavesItemsToGlideTest(unittest.TestCase):
    def test_overlay_paints_items_only_when_grabbed(self) -> None:
        from tests.test_render import _app
        _app()
        from deskmirror import config, winapi
        from deskmirror.ui.overlay import Overlay, UiState
        from deskmirror.ui.render import Renderer
        st = UiState(Renderer(config.StyleConfig()))
        st.mirror = (0, 0, 400, 300)
        st.mirrors = [st.mirror]
        st.snapshot = Snapshot((_item(1, (20, 20, 300, 44), clips=[(0, 0, 400, 300)]),), (), {}, 0.0)
        mon = winapi.Monitor("TEST", (0, 0, 400, 301), (0, 0, 400, 301), 96, True)
        with mock.patch.object(winapi, "exclude_from_capture", return_value=True):   # 离屏窗口没有真句柄
            o = Overlay(mon, st)
        from PySide6.QtCore import QRect
        st.glide = True
        plain = o.grab(QRect(0, 0, 400, 300)).toImage()
        full = o.grab_full(QRect(0, 0, 400, 300)).toImage()
        o.close()

        def px(img) -> np.ndarray:
            from PySide6.QtGui import QImage
            img = img.convertToFormat(QImage.Format.Format_ARGB32)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
            return a[:, :img.width() * 4].reshape(img.height(), img.width(), 4).copy()
        p, f = px(plain), px(full)
        # 离屏时窗口底色不一定透明：只比较“有译文那块”和“没有译文的地方”
        self.assertTrue((p[20:44, 20:300] == p[200:224, 20:300]).all(), "镜内的译文交给合成器了，这一层不画")
        self.assertGreater(int((f[20:44, 20:300] != p[20:44, 20:300]).any(axis=2).sum()), 500, "截图、录制时照样画出来")
        self.assertFalse(st.grab_items)


if __name__ == "__main__":
    unittest.main()
