"""引擎里画布移动、找回段落的离线单元测试（合成画面，不启动采集、识别和翻译）。"""
from __future__ import annotations

import time
import unittest

import numpy as np

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror import engine as E
from deskmirror import winapi
from deskmirror.config import AppConfig
from deskmirror.scene import Block, Canvas

from tests.test_pixels import text_page

W, H = 900, 1200


class _NoCapture:
    def close(self) -> None:
        pass


def make_engine(frame: np.ndarray) -> tuple[E.Engine, E.Mon, Canvas, Canvas]:
    eng = E.Engine(AppConfig(), lambda snap: None)
    th, tw = -(-H // E.TILE), -(-W // E.TILE)
    info = winapi.Monitor("TEST", (0, 0, W, H), (0, 0, W, H), 96, True)
    m = E.Mon(0, info, _NoCapture(), (0, 0), (W, H), frame.copy(), frame.copy(), None, np.zeros((th, tw)),
              np.zeros((th, tw), np.float32), np.zeros((th, tw), bool), 0.0)
    m.last_chg, m.chg_start, m.last_ocr = np.zeros((th, tw)), np.zeros((th, tw)), np.zeros((th, tw))
    m.snap_backoff = np.ones((th, tw), np.float32)
    m.ready = True
    eng.mons = [m]
    win = Canvas("window", eng.desktop, [0, 0], (0, 0, W, H), hwnd=1)
    eng.desktop.children.append(win)
    sc = Canvas("scroll", win, [0, 0], (0, 0, W, H), axis="v")
    win.children.append(sc)
    return eng, m, win, sc


def add_block(eng: E.Engine, canvas: Canvas, rect, ref: np.ndarray) -> Block:
    b = Block(canvas, rect, [(rect, "x")], "x", "x", ref, (255, 255, 255), (0, 0, 0), rect[3] - rect[1])
    b.ok_rect = canvas.to_screen(rect)
    eng.blocks[b.bid] = b
    canvas.blocks[b.bid] = b
    return b


class ScrollOnceTest(unittest.TestCase):
    def test_same_scroll_split_in_two_parts_moves_once(self) -> None:
        # 变化区域被压在上面的窗口切成两块，两块各自认出同一次滚动：画布只能移动一次
        page = text_page(3000, W, 3)
        eng, m, win, sc = make_engine(page[0:H])
        b = add_block(eng, sc, (10, 300, 400, 322), page[300:322, 10:400])
        eng._frame_moved, eng._ok_pending = {}, {}
        eng._apply_scroll(m, win, (0, 0, W, 700), "v", -20)
        eng._apply_scroll(m, win, (0, 0, W, H), "v", -20)
        self.assertEqual(sc.offset, [0, -20])
        self.assertEqual(b.screen_rect()[1], 280)
        self.assertIsNotNone(b.ok_rect, "第二块确认了同样的平移，移动前确认过的块应照样沿用确认")

    def test_child_moved_first_is_undone(self) -> None:
        # 先在子画布范围里认出了位移，随后发现是外层整体在滚：子画布不能再自己移一遍
        page = text_page(3000, W, 4)
        eng, m, win, sc = make_engine(page[0:H])
        inner = Canvas("scroll", sc, [0, 0], (100, 400, 800, 900), axis="v")
        sc.children.append(inner)
        b = add_block(eng, inner, (120, 500, 500, 522), page[500:522, 120:500])
        eng._frame_moved, eng._ok_pending = {}, {}
        eng._apply_scroll(m, win, (100, 400, 800, 900), "v", -30)
        eng._apply_scroll(m, win, (0, 0, W, H), "v", -30)
        self.assertEqual(inner.offset, [0, 0])
        self.assertEqual(sc.offset, [0, -30])
        self.assertEqual(b.screen_rect()[1], 470)


class MergeSplitScrollTest(unittest.TestCase):
    def test_parts_split_by_popup_become_one_canvas(self) -> None:
        # 网页上压着一个小弹窗：变化区域被切成上下两块，第一次滚动时两块各自认出同样的位移。
        # 不能建两个各自为政的滚动画布：第二块并进第一块建的画布，块也跟着移动一次。
        page = text_page(3000, W, 9)
        eng, m, win, sc = make_engine(page[0:H])
        win.children.remove(sc)                      # 还没有滚动画布
        top = add_block(eng, win, (20, 100, 400, 122), page[100:122, 20:400])
        bottom = add_block(eng, win, (20, 900, 400, 922), page[900:922, 20:400])
        eng._frame_moved, eng._ok_pending = {}, {}
        win.last_move = -10.0
        c1 = eng._apply_scroll(m, win, (0, 600, W, H), "v", -30)
        c2 = eng._apply_scroll(m, win, (0, 0, W, 500), "v", -30)
        self.assertIsNotNone(c1)
        self.assertIs(c1, c2)
        self.assertEqual(len([c for c in win.children if c.kind == "scroll"]), 1)
        self.assertIs(top.canvas, c1)
        self.assertEqual(top.screen_rect()[1], 70)
        self.assertEqual(bottom.screen_rect()[1], 870)
        self.assertIsNotNone(top.ok_rect, "合并进来的块在这块确认过的范围里，应沿用确认")


    def test_blocks_beside_popup_follow_the_scroll(self) -> None:
        # 弹窗左右两侧的段落：既不在第一块也不在第二块里，但这一帧被同一次滚动解释掉了，也要跟着滚
        page = text_page(3000, W, 10)
        eng, m, win, sc = make_engine(page[0:H])
        win.children.remove(sc)
        m.cur[:] = page[30:30 + H]                  # 整页上移 30 像素
        ys = [y for y in range(320, 560) if page[y:y + 22, 20:400].std() > 40 and page[y, 20:400].min() == 255]
        y = ys[0]
        side = add_block(eng, win, (20, y, 400, y + 22), page[y:y + 22, 20:400])
        eng._frame_moved, eng._ok_pending = {}, {}
        win.last_move = -10.0
        c = eng._apply_scroll(m, win, (0, 600, W, H), "v", -30)
        eng._apply_scroll(m, win, (0, 0, W, 300), "v", -30)
        self.assertTrue(eng._explained_by_frame_shift(m, win, (0, 300, 450, 600), True))
        self.assertIs(side.canvas, c)
        self.assertEqual(side.screen_rect()[1], y - 30)


class OcrPieceTest(unittest.TestCase):
    def test_window_without_pending_tiles_is_not_ocr_target(self) -> None:
        # 待识别的格子围着一个小弹窗（弹窗本身没有待识别的格子）：外接矩形碰到弹窗，但不能切出弹窗那一块
        page = text_page(3000, W, 11)
        eng, m, win, sc = make_engine(page[0:H])
        popup = (300, 400, 500, 520)
        eng.z_order = [2, 1]
        eng.win_rects = {2: popup, 1: (0, 0, W, H)}
        mask = np.zeros(m.needs.shape, bool)
        mask[20:40, 10:40] = True                      # 160..640 × 320..640 的格子：把弹窗围在中间
        mask[400 // 16:520 // 16, 300 // 16:500 // 16] = False
        pieces = eng._split_by_window(m, (160, 320, 640, 640), mask)
        self.assertEqual(len(pieces), 1)
        self.assertFalse(any(p == popup or (p[0] >= 300 and p[2] <= 500 and p[1] >= 400 and p[3] <= 520)
                             for p in pieces))


class RefindTest(unittest.TestCase):
    def test_paragraph_found_nearby_is_moved(self) -> None:
        page = text_page(3000, W, 7)
        eng, m, win, sc = make_engine(page[0:H])
        y0 = next(y for y in range(400, 700) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        b = add_block(eng, sc, (10, y0, 500, y0 + 22), page[y0:y0 + 22, 10:500].copy())
        m.cur[:] = page[137:137 + H]   # 画面实际滚了 137 像素，画布没跟上
        t0 = time.perf_counter()
        self.assertTrue(eng._refind(b))
        self.assertLess(time.perf_counter() - t0, 0.05)
        self.assertEqual(b.screen_rect()[1], y0 - 137)
        self.assertEqual(b.ok_rect, b.screen_rect())

    def test_changed_paragraph_is_not_moved(self) -> None:
        page = text_page(3000, W, 8)
        eng, m, win, sc = make_engine(page[0:H])
        other = text_page(60, 490, 99)
        y = next(k for k in range(0, 40) if other[k:k + 22].std() > 40)
        b = add_block(eng, sc, (10, 600, 500, 622), other[y:y + 22].copy())
        self.assertFalse(eng._refind(b))
        self.assertEqual(b.rect, (10, 600, 500, 622))



class PendingVisibleTest(unittest.TestCase):
    def test_hidden_pending_block_not_reported(self) -> None:
        # 窗口下半截被别的窗口挡住：挡住的那块没译好也不算“在翻译”（范围外的窗口永远不会翻译）
        page = text_page(3000, W, 5)
        eng, m, win, sc = make_engine(page[0:H])
        eng.win_canvas[1] = win
        eng.z_order = [1]
        eng.visible = {1: [(0, 0, W, 600)]}
        shown = add_block(eng, sc, (10, 100, 400, 122), page[100:122, 10:400])
        hidden = add_block(eng, sc, (10, 800, 400, 822), page[800:822, 10:400])
        shown.state = hidden.state = "pending"
        snaps = []
        eng._publish_cb = snaps.append
        eng._publish(force=True)
        self.assertEqual([sr for sr, _c, _f in snaps[-1].pending], [shown.screen_rect()])


class NumberTickTest(unittest.TestCase):
    def test_counter_change_cools_tiles(self) -> None:
        # 只是数字变了、译文套模板：这几格不算“无故变化”，热度清零
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.templates.learn(E.textutil.cache_key, "Time remaining: 35 seconds", "剩余时间：35 秒")
        self.assertEqual(eng._cached(E.textutil.cache_key("Time remaining: 32 seconds"),
                                     "Time remaining: 32 seconds"), "剩余时间：32 秒")
        m.heat[:] = 3.0
        eng._cool(m, (16, 160, 400, 192))
        self.assertEqual(float(m.heat[10:12, 1:25].max()), 0.0)
        self.assertEqual(float(m.heat[20, 5]), 3.0)


    def test_memory_hit_teaches_template(self) -> None:
        # 重启后：从记忆里取到的译文顺带学会模板，只差数字的另一段直接套用，不发请求
        import tempfile
        from pathlib import Path
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        with tempfile.TemporaryDirectory() as d:
            eng.memory = E.Memory(Path(d) / "mem.bin")
            src = "Note 23.4 about the north garden: The museum offers free tours."
            eng.memory.put(eng.cfg.target_lang, E.textutil.cache_key(src), "关于北花园的注释 23.4：博物馆提供免费导览。")
            other = "Note 23.14 about the north garden: The museum offers free tours."
            self.assertIsNone(eng._cached(E.textutil.cache_key(other), other))
            self.assertIsNotNone(eng._cached(E.textutil.cache_key(src), src))
            self.assertEqual(eng._cached(E.textutil.cache_key(other), other), "关于北花园的注释 23.14：博物馆提供免费导览。")



class PauseTest(unittest.TestCase):
    def test_paused_engine_does_not_capture_and_resume_rechecks(self) -> None:
        page = text_page(3000, W, 9)
        eng, m, win, sc = make_engine(page[0:H])

        class CountingCap(_NoCapture):
            grabs = 0

            def grab(self, timeout_ms: int = 50):
                CountingCap.grabs += 1
                return None

        m.cap = CountingCap()
        eng.set_mirrors([(0, 0, 400, 300)])
        b = add_block(eng, sc, (10, 100, 400, 122), page[100:122, 10:400])
        eng.inbox.put(("work", False))
        self.assertTrue(eng._tick())
        self.assertFalse(eng.working)
        eng._tick()
        self.assertEqual(CountingCap.grabs, 0, "暂停时不截屏")
        eng.inbox.put(("wheel", (time.perf_counter(), 100, 100, -3.0, False, False, False)))
        eng._drain_inbox()
        self.assertEqual(eng.episodes, {}, "暂停时的滚轮不记")
        eng._set_working(True)
        self.assertIsNone(b.ok_rect, "继续时所有段落先当作没核对过")
        self.assertTrue((m.needs[0:300 // E.TILE, 0:400 // E.TILE] > 0).all(), "魔镜里重新识别")



class RefsInBatchTest(unittest.TestCase):
    def test_batch_carries_refs_and_results_become_refs(self) -> None:
        # 术语前后一致：同一个窗口里含同样词语的已有译文跟着这一批发出去；这一批的结果又成为后面的参考
        page = text_page(3000, W, 10)
        eng, m, win, sc = make_engine(page[0:H])
        sent = []

        class Pool:
            def submit(self, batch) -> None:
                sent.append(batch)

        eng.pool = Pool()
        b = add_block(eng, sc, (10, 100, 400, 122), page[100:122, 10:400])
        b.text = "The Engineer may reject the works."
        b.key = E.textutil.cache_key(b.text)
        b.state = "pending"
        eng.by_key[b.key].add(b.bid)
        old = "The Engineer shall issue the certificate."
        eng.refs.add(E.textutil.cache_key(old), old, "监理工程师应签发证书。", 1, "")
        eng._schedule_translation()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].refs, [(old, "监理工程师应签发证书。")])
        self.assertEqual(sent[0].hwnd, 1)
        eng._on_translation(("segment", sent[0].batch_id, 0, "监理工程师可以拒收工程。"))
        self.assertEqual(b.state, "done")
        self.assertEqual(eng.refs.select(["Ask the Engineer."], [], 1, "")[0][1] in
                         ("监理工程师应签发证书。", "监理工程师可以拒收工程。"), True)
        self.assertEqual(len(eng.refs), 2)
        eng.cfg.llm.consistency = False
        b2 = add_block(eng, sc, (10, 200, 400, 222), page[200:222, 10:400])
        b2.text, b2.key, b2.state = "The Engineer approves.", E.textutil.cache_key("The Engineer approves."), "pending"
        eng.by_key[b2.key].add(b2.bid)
        eng.inflight.clear()
        eng._schedule_translation()
        self.assertEqual(sent[-1].refs, [], "设置里关掉就不带参考")


if __name__ == "__main__":
    unittest.main()
