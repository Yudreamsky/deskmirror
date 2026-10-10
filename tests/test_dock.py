"""吸边成球（ui/dock.py）：拖到哪条边算吸住、两块屏相接的边不算、球藏多少、虚线框怎么跟着鼠标、
动画和帧率无关，以及一次完整的拖动：魔镜拖到边上收成球（停止翻译）→ 球拖出来变虚线框（开始翻译）→ 松手落定。
离屏，不弹窗口；显示器是假的。"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import deskmirror  # noqa: E402,F401  预加载 DLL
from PySide6.QtCore import QObject, QPoint, Signal  # noqa: E402

from deskmirror import winapi  # noqa: E402
from deskmirror.ui import dock, layered  # noqa: E402
from deskmirror.ui.dock import Shape  # noqa: E402
from deskmirror.ui.mirror import BAND, TAB_H, grip_offset  # noqa: E402
from tests.test_render import _app  # noqa: E402

# 一块 1920×1080 的屏，任务栏在下面（工作区到 1040）
MAIN = winapi.Monitor("\\\\.\\DISPLAY1", (0, 0, 1920, 1080), (0, 0, 1920, 1040), 96, True)
# 右边接着一块，上沿往下错开 500
RIGHT = winapi.Monitor("\\\\.\\DISPLAY2", (1920, 500, 3840, 1580), (1920, 500, 3840, 1580), 96, False)
HIDPI = winapi.Monitor("\\\\.\\DISPLAY1", (0, 0, 2880, 1620), (0, 0, 2880, 1572), 144, True)


class GeometryTest(unittest.TestCase):
    def test_edges_of_one_screen(self) -> None:
        mons = [MAIN]
        near = lambda x, y: dock.edge_near(x, y, MAIN, mons, dock.ZONE, dock.ZONE_TOP)  # noqa: E731
        self.assertEqual(near(10, 500), "l")
        self.assertEqual(near(1905, 500), "r")
        self.assertEqual(near(900, 1060), "b", "鼠标在任务栏上也算下边")
        self.assertEqual(near(900, 1012), "b", "离任务栏内沿 28 px 以内")
        self.assertEqual(near(900, 500), "")
        self.assertEqual(near(900, 1), "t", "顶边要顶到最上沿")
        self.assertEqual(near(900, 20), "", "拖到菜单栏上（离顶边 20 px）不收")
        self.assertEqual(near(5, 1), "t", "角上取近的边")
        self.assertEqual(near(5, 8), "l")

    def test_shared_edge_does_not_dock(self) -> None:
        mons = [MAIN, RIGHT]
        self.assertEqual(dock.edge_near(1910, 200, MAIN, mons, dock.ZONE), "r", "右边这一段外面没有屏")
        self.assertEqual(dock.edge_near(1910, 700, MAIN, mons, dock.ZONE), "", "和右边那块屏相接的一段不吸")
        self.assertEqual(dock.edge_near(1930, 700, RIGHT, mons, dock.ZONE), "")
        self.assertEqual(dock.edge_near(3830, 700, RIGHT, mons, dock.ZONE), "r")
        self.assertEqual(dock.monitor_at(5000, 700, mons), RIGHT, "屏外的点取最近的屏")

    def test_zone_scales_with_dpi(self) -> None:
        self.assertEqual(dock.edge_near(40, 500, HIDPI, [HIDPI], dock.ZONE), "l", "150% 缩放：28 px 变成 42 px")
        self.assertEqual(dock.edge_near(40, 500, MAIN, [MAIN], dock.ZONE), "")
        x, y, d = dock.ball_rect("r", 500, HIDPI, False)
        self.assertEqual(d, 69)
        self.assertEqual(x, 2880 - 69 - 15)

    def test_ball_tucks_into_each_edge(self) -> None:
        d = dock.BUB
        x, y, _ = dock.ball_rect("l", 500, MAIN, True)
        self.assertAlmostEqual(x, -d * dock.TUCK)
        self.assertEqual(y, 500 - d / 2)
        x, _, _ = dock.ball_rect("r", 500, MAIN, True)
        self.assertAlmostEqual(1920 - x, d * (1 - dock.TUCK), msg="右边露出六成")
        _, y, _ = dock.ball_rect("b", 900, MAIN, True)
        self.assertAlmostEqual(1040 - y, d * (1 - dock.TUCK), msg="下边贴着任务栏内沿")
        _, y, _ = dock.ball_rect("t", 900, MAIN, False)
        self.assertEqual(y, dock.GAP)
        _, y, _ = dock.ball_rect("l", 5000, MAIN, False)
        self.assertEqual(y, 1040 - d - dock.GAP, "顺着边不出屏")

    def test_ball_is_pulled_at_most_pull(self) -> None:
        x0, _, _ = dock.ball_spot("l", 0, 500, MAIN)
        x1, _, _ = dock.ball_spot("l", 60, 500, MAIN)
        x2, _, _ = dock.ball_spot("l", 300, 500, MAIN)
        self.assertEqual(x0, dock.GAP)
        self.assertEqual(x1 - x0, 60 - dock.BUB / 2 - dock.GAP)
        self.assertEqual(x2 - x0, dock.PULL)
        _, y, _ = dock.ball_spot("b", 500, 700, MAIN)
        self.assertEqual(y, 1040 - dock.BUB - dock.GAP - dock.PULL)

    def test_dash_frame_follows_the_grip_and_stays_on_screen(self) -> None:
        gx, gy = grip_offset()
        m = dock.dash_rect(800, 400, (gx, gy), (640, 360), MAIN)
        self.assertEqual((m[0] + gx, m[1] + gy), (800, 400), "抓手在鼠标底下")
        self.assertEqual((m[2] - m[0], m[3] - m[1]), (640, 360))
        m = dock.dash_rect(1900, 10, (gx, gy), (640, 360), MAIN)
        self.assertLessEqual(m[2], 1920 - dock.MARGIN)
        self.assertGreaterEqual(m[1] - BAND - TAB_H, 0, "标签露得出来")
        m = dock.dash_rect(500, 500, (gx, gy), (2500, 1500), MAIN)
        self.assertLessEqual(m[2] - m[0], 1920 - 2 * dock.MARGIN, "比屏幕大就缩小")
        self.assertLessEqual(m[3], 1040)

    def test_default_dock_picks_the_near_side(self) -> None:
        self.assertEqual(dock.default_dock((100, 300, 700, 600), [MAIN])[0], "l")
        edge, mon, along = dock.default_dock((1200, 300, 1800, 600), [MAIN])
        self.assertEqual((edge, mon), ("r", MAIN))
        self.assertEqual(along, 300 - BAND - TAB_H / 2, "和标签一样高")
        left = winapi.Monitor("L", (-1920, 0, 0, 1080), (-1920, 0, 0, 1040), 96, False)
        self.assertEqual(dock.default_dock((100, 300, 700, 600), [MAIN, left])[0], "r", "左边接着别的屏：吸右边")

    def test_restore_after_screens_changed(self) -> None:
        self.assertEqual(dock.restore_dock({"edge": "r", "x": 1887, "y": 400}, [MAIN])[0], "r")
        self.assertIsNone(dock.restore_dock({"edge": "r", "x": 1887, "y": 700}, [MAIN, RIGHT]), "那条边现在接着别的屏")
        edge, mon, _ = dock.restore_dock({"edge": "l", "x": -500, "y": 300}, [MAIN])
        self.assertEqual((edge, mon), ("l", MAIN), "原来的屏没了：吸到最近那块屏的同一边")
        self.assertIsNone(dock.restore_dock({"edge": "x", "x": 1, "y": 1}, [MAIN]))
        self.assertIsNone(dock.restore_dock({"edge": "l"}, [MAIN]))
        self.assertEqual(dock.fit_rect((100, 100, 500, 400), [MAIN]), (100, 100, 500, 400))
        r = dock.fit_rect((3000, 2000, 3400, 2300), [MAIN])
        self.assertTrue(0 <= r[0] and r[2] <= 1920 and r[3] <= 1040, r)


class ApproachTest(unittest.TestCase):
    def _run(self, fps: float, seconds: float) -> Shape:
        cur, target = Shape(0, 0, 800, 600, 0.0), Shape(1000, 500, 46, 46, 1.0)
        for _ in range(int(seconds * fps)):
            dock.approach(cur, target, 1 / fps)
        return cur

    def test_independent_of_frame_rate(self) -> None:
        a, b = self._run(60, 0.12), self._run(144, 0.12)
        self.assertAlmostEqual(a.x, b.x, delta=8)
        self.assertAlmostEqual(a.k, b.k, delta=0.01)
        self.assertGreater(a.x, 800, "120 ms 走了八成多")

    def test_settles_and_reverses(self) -> None:
        cur, target = Shape(0, 0, 800, 600, 0.0), Shape(1000, 500, 46, 46, 1.0)
        for _ in range(30):
            dock.approach(cur, target, 1 / 60)
        back = Shape(0, 0, 800, 600, 0.0)
        for _ in range(3):
            dock.approach(cur, back, 1 / 60)
        self.assertLess(cur.k, 0.9, "中途反向：马上往回走")
        n = 0
        while not dock.approach(cur, back, 1 / 60):
            n += 1
        self.assertLess(n, 60, "一秒内落定")
        self.assertEqual((cur.x, cur.w, cur.k), (0, 800, 0.0))
        self.assertTrue(dock.approach(cur, back, 0.5), "到位以后一直算到位")

    def test_big_frame_gap_is_capped(self) -> None:
        cur = Shape(0, 0, 100, 100, 0.0)
        dock.approach(cur, Shape(1000, 0, 100, 100, 0.0), 2.0)
        self.assertLess(cur.x, 600, "卡了两秒也只按 50 ms 算，不会一下跳到位")


class _Frame(QObject):
    """MirrorFrame 的替身：只要 Docker 用到的那几样。"""
    rect_changed = Signal(tuple, bool)

    def __init__(self, rect) -> None:
        super().__init__()
        self.mirror = rect
        self.ghost = False
        self.visible = True
        self.finals: list[tuple] = []
        self.rect_changed.connect(lambda r, final: final and self.finals.append(r))

    def set_mirror(self, r) -> None:
        self.mirror = r

    def set_ghost(self, on: bool) -> None:
        self.ghost = on

    def hide(self) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class GestureTest(unittest.TestCase):
    def setUp(self) -> None:
        _app()
        self._ck = layered._colorkey
        layered._colorkey = False
        self.clock = _Clock()
        patches = [mock.patch.object(winapi, "monitors", lambda: [MAIN]),
                   mock.patch.object(winapi, "exclude_from_capture", lambda hwnd: True),
                   mock.patch.object(dock.time, "perf_counter", self.clock)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.frame = _Frame((600, 300, 1240, 660))
        self.d = dock.Docker(self.frame, {})
        self.events: list[bool] = []
        self.d.docked_changed.connect(self.events.append)

    def tearDown(self) -> None:
        self.d.close()
        layered._colorkey = self._ck

    def _settle(self, frames: int = 200) -> None:
        for _ in range(frames):
            if self.d.live is None or not self.d._timer.isActive():
                return
            self.clock.t += 1 / 60
            self.d._step()

    def test_drag_to_edge_docks_and_drag_out_lands(self) -> None:
        d, f = self.d, self.frame
        grab = QPoint(700, 285)                       # 标签上
        d.frame_press(grab)
        d.move(QPoint(500, 300))
        self.assertEqual(f.mirror, (400, 315, 1040, 675), "离边远：魔镜照常跟着走")
        self.assertEqual(self.events, [])
        d.move(QPoint(20, 300))
        self.assertEqual(self.events, [True], "到了左边：收成球，停止翻译")
        self.assertTrue(f.ghost, "魔镜窗口不画了，只接着鼠标")
        self.assertEqual(d.g.mode, "ball")
        d.move(QPoint(20, 700))
        self._settle()
        s = d.shape()
        self.assertEqual((s.k, s.w), (1.0, dock.BUB))
        self.assertEqual(s.y, 700 - dock.BUB / 2, "球顺着边跟着鼠标走")
        d.release(QPoint(20, 700))
        self._settle()
        self.assertTrue(d.docked and d.tucked)
        self.assertLess(d.shape().x, 0, "松手后藏进边缘一部分")
        self.assertFalse(f.visible)
        self.assertEqual(f.mirror, (600, 300, 1240, 660), "以后点开回到拖之前的地方")
        self.assertEqual(d.saved()["edge"], "l")

        d.ball_press(QPoint(5, 700))
        d.move(QPoint(60, 700))
        self.assertTrue(d.docked, "还在边缘带里：还是球（被边吸着）")
        d.move(QPoint(400, 600))
        self.assertEqual(self.events, [True, False], "离开边缘：变虚线框，开始翻译")
        gx, gy = grip_offset()
        self.assertEqual((f.mirror[0] + gx, f.mirror[1] + gy), (400, 600), "抓手在鼠标底下")
        self.assertEqual((f.mirror[2] - f.mirror[0], f.mirror[3] - f.mirror[1]), (640, 360), "和原来的魔镜一样大")
        self.assertTrue(d.live.target.dash and d.live.target.text)
        d.move(QPoint(10, 600))
        self.assertEqual(self.events, [True, False, True], "一次拖动里可以再拖回边上")
        d.move(QPoint(500, 500))
        self.assertEqual(self.events, [True, False, True, False])
        d.release(QPoint(500, 500))
        self._settle()
        self.assertIsNone(d.shape(), "落定：形状撤掉")
        self.assertTrue(f.visible and not f.ghost)
        self.assertEqual(f.finals[-1], f.mirror)
        self.assertEqual(d.saved(), {})

    def test_click_on_ball_unfolds_to_home(self) -> None:
        d, f = self.d, self.frame
        d.dock_now()
        self.assertEqual(self.events, [True])
        self.assertEqual(d.edge, "l", "魔镜在左半边：吸左边")
        self.assertFalse(f.visible)
        d.ball_press(QPoint(10, 280))
        d.release(QPoint(11, 281))
        self.assertEqual(self.events, [True, False], "点一下：展开，开始翻译")
        self.assertTrue(d.busy)
        self._settle()
        self.assertTrue(f.visible)
        self.assertEqual(f.mirror, (600, 300, 1240, 660))

    def test_hover_slides_out_and_tucks_back(self) -> None:
        d = self.d
        d.dock_now({"edge": "r", "x": 1887, "y": 400})
        tucked = d.shape().x
        d.hover(True)
        self.assertTrue(d.tucked, "刚吸住的这一会儿不理会")
        self.clock.t += 1.0
        d.hover(False)
        d.hover(True)
        self._settle()
        self.assertFalse(d.tucked)
        self.assertLess(d.shape().x, tucked, "滑出来")
        self.assertEqual(d.ball.x(), round(d.shape().x), "接鼠标的窗口跟着走")
        self.assertEqual(d.ball.x() + d.ball.width(), 1920, "一直伸到屏幕边上：鼠标甩到边上也点得到")
        d.hover(False)
        d._tuck()
        self._settle()
        self.assertTrue(d.tucked)
        self.assertEqual(d.shape().x, tucked)

    def test_hidden_mid_drag_finishes_the_gesture(self) -> None:
        d, f = self.d, self.frame
        d.frame_press(QPoint(700, 285))
        d.move(QPoint(15, 300))
        d.set_hidden(True)
        self._settle()
        self.assertIsNone(d.g)
        self.assertTrue(d.docked)
        self.assertFalse(d.ball.isVisible())
        self.assertFalse(f.visible)


if __name__ == "__main__":
    unittest.main()
