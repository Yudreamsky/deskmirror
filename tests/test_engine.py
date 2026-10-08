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


    def test_counter_keeps_old_translation_until_next_read(self) -> None:
        # 倒计时每跳一下像素都会变：计数器先留着旧译文（等下一次识别套模板），不露出原文；普通文字照常撤下
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}                                       # 窗口全露着：核对真的比像素
        y0 = next(y for y in range(200, 600) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        rect = (10, y0, 500, y0 + 22)
        held, plain = (add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy()) for _ in range(2))
        held.counter = True
        for b in (held, plain):
            b.state, b.translation = "done", "剩余 02:00"
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]             # 像素全变了（比如数字跳了）
        self.assertFalse(eng._verify(held))
        self.assertFalse(eng._verify(plain))
        self.assertGreater(held.held_until, time.perf_counter())
        self.assertEqual(held.hold_rect, held.screen_rect())
        self.assertEqual(plain.held_until, 0.0)

    def test_counter_change_is_read_again_right_away(self) -> None:
        # 游戏画面一直在动、等不到静止：计数器的数字一变，稍等一下就单独识别它那一小块，排在别的识别前面
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        eng.set_mirrors([(0, 0, W, H)])
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        y0 = next(y for y in range(200, 600) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        rect = (10, y0, 500, y0 + 22)
        b = add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy())
        b.counter, b.state, b.translation = True, "done", "剩余 02:00"
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]             # 数字跳了
        eng._content_changed(m, rect)
        self.assertIn(b.bid, eng._recount)
        eng._schedule_ocr()
        self.assertEqual(jobs, [], "先等数字画完")
        m.needs[:] = time.perf_counter() - 5                                     # 别处还有一大片早就等着识别
        eng._recount[b.bid] = time.perf_counter() - 0.01
        eng._schedule_ocr()
        self.assertEqual(len(jobs), 1)
        r = eng.jobs[jobs[0].job_id].rect
        self.assertTrue(E.geom.contains(r, rect), r)
        self.assertLess(E.geom.area(r), 3 * E.geom.area(rect), "只识别这一小块")
        self.assertEqual(eng._recount, {})

    def test_counter_tick_stays_counter_and_font_moves_slowly(self) -> None:
        # 倒计时跳了一格、重新识别：新块套模板直接译好、顶掉旧块，接着当计数器；字号估计跟着上一块慢慢走
        from deskmirror.ocr_worker import OcrBlockOut, OcrLineOut
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        eng.set_mirrors([(0, 0, W, H)])
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]   # 识别结果按窗口找画布
        y0 = next(y for y in range(200, 600) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        rect = (10, y0, 500, y0 + 22)
        old = add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy())
        old.text, old.key = "残り 02:00", E.textutil.cache_key("残り 02:00")
        eng.by_key[old.key].add(old.bid)
        eng.templates.learn(E.textutil.cache_key, "残り 02:00", "剩余 02:00")
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]             # 数字跳了
        # 引擎按笔画估字号（量得出时）：照它的做法算出这次的估计
        crop = np.dstack([m.cur] * 3)[y0 - 3:y0 + 25, 7:503]
        bg, fg = E.textutil.sample_colors(crop, [(3, 3, 493, 25)])
        ink = E.textutil.line_ink(crop, [(3, 3, 493, 25)], ["残り 01:59"], bg, fg)[0]
        e = E.font_em(E.Line(rect, "残り 01:59"), ink[4] if ink else 0.0)
        old.state, old.translation, old.counter, old.em = "done", "剩余 02:00", True, e * 1.15
        old.ok_rect = None
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        eng._submit_ocr(m, (0, y0 - 20, W, y0 + 42))
        eng._accept_block(eng.jobs[jobs[0].job_id], OcrBlockOut(rect, [OcrLineOut(rect, "残り 01:59", 0.99)], "残り 01:59"))
        new = [b for b in eng.blocks.values() if b.text == "残り 01:59"]
        self.assertEqual(len(new), 1)
        self.assertEqual((new[0].state, new[0].translation), ("done", "剩余 01:59"))
        self.assertTrue(new[0].counter)
        self.assertNotIn(old.bid, eng.blocks)
        self.assertAlmostEqual(new[0].em, old.em + (e - old.em) * 0.25)

    def test_snapshot_never_cuts_known_text(self) -> None:
        # 动态区域的抓拍只框变了的那几格：碰到的已知文字块要整块框进去，不然切下的半行（只剩数字）会顶掉整行
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        b = add_block(eng, sc, (10, 300, 500, 322), page[300:322, 10:500].copy())
        far = add_block(eng, sc, (10, 600, 500, 622), page[600:622, 10:500].copy())
        r = eng._whole_blocks(m, (400, 290, 560, 330), win)
        self.assertTrue(E.geom.contains(r, b.screen_rect()), r)
        self.assertFalse(E.geom.overlaps(r, far.screen_rect()))

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



class NotSeenTest(unittest.TestCase):
    def test_block_still_on_screen_survives_missed_reads(self) -> None:
        # 重新识别没报出来（三个字以内的短词置信度差一点），但像素和识别时一模一样：字还在，连着三次没认出来才删；
        # 字真的没了（像素变了）马上删
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        y0 = next(y for y in range(200, 600) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        rect = (10, y0, 500, y0 + 22)

        def miss() -> None:
            eng.ocr_busy = None
            eng._submit_ocr(m, (0, y0 - 20, W, y0 + 42))
            eng._finish_job(eng.jobs[jobs[-1].job_id], {"blocks": 0})

        b = add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy())
        b.state, b.translation = "done", "Save"
        miss()
        miss()
        self.assertIn(b.bid, eng.blocks, "两次没认出来：字还在，不删")
        miss()
        self.assertNotIn(b.bid, eng.blocks, "连着三次没认出来：删")
        b2 = add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy())
        m.cur[y0:y0 + 22, 10:500] = 255                                          # 字没了
        miss()
        self.assertNotIn(b2.bid, eng.blocks, "像素变了：马上删")

    def test_weak_read_keeps_block_but_never_creates_one(self) -> None:
        # 字号小的短词重新识别时置信度常差一点（0.6~0.88）：同一位置同样的字算“认出来了”，一直留着；但不拿它新建块
        from deskmirror.ocr_worker import OcrBlockOut, OcrLineOut, line_kind
        self.assertEqual(line_kind("セーブ", 0.95), "strong")
        self.assertEqual(line_kind("セーブ", 0.8), "weak")
        self.assertEqual(line_kind("セーブ", 0.5), "")
        self.assertEqual(line_kind("Quest: Head to the Lighthouse", 0.7), "strong")
        self.assertEqual(line_kind("…", 0.8), "")
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        y0 = next(y for y in range(200, 600) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        rect = (10, y0, 500, y0 + 22)
        b = add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy())
        b.text, b.key, b.state, b.translation = "セーブ", E.textutil.cache_key("セーブ"), "done", "Save"
        for _ in range(5):
            eng.ocr_busy = None
            eng._submit_ocr(m, (0, y0 - 20, W, y0 + 42))
            st = eng.jobs[jobs[-1].job_id]
            eng._accept_block(st, OcrBlockOut(rect, [OcrLineOut(rect, "セーブ", 0.8)], "セーブ", weak=True))
            eng._accept_block(st, OcrBlockOut((10, y0 + 200, 200, y0 + 222), [OcrLineOut((10, y0 + 200, 200, y0 + 222), "ロード", 0.8)],
                                              "ロード", weak=True))
            eng._finish_job(st, {"blocks": 2})
        self.assertIn(b.bid, eng.blocks, "置信度差一点也算认出来了：一直留着")
        self.assertFalse(any(x.text == "ロード" for x in eng.blocks.values()), "不拿置信度不够的短词新建块")


class SubtitleCoverTest(unittest.TestCase):
    def test_wider_new_line_is_covered_while_old_translation_is_held(self) -> None:
        # 字幕换句：旧译文留到新译文出来；新句子比旧底板宽时，先在新句子的位置垫一块同色空底板（画在最底下），两头不露原文
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        snaps = []
        eng._publish_cb = snaps.append
        y0 = 400
        old = add_block(eng, sc, (300, y0, 600, y0 + 30), page[y0:y0 + 30, 300:600].copy())
        old.state, old.translation, old.born_dynamic, old.dynamic = "done", "我们终于到了老灯塔。", True, True
        old.bg, old.fg = (24, 24, 28), (245, 245, 245)
        new = add_block(eng, sc, (200, y0, 700, y0 + 30), page[y0:y0 + 30, 200:700].copy())
        new.state, new.replaces = "translating", [old.bid]
        old.ok_rect = None
        old.hold_start = time.perf_counter()
        old.held_until, old.hold_rect = old.hold_start + 4.0, old.screen_rect()
        eng._publish(force=True)
        items = snaps[-1].items
        self.assertEqual(items[0].bid, -new.bid, "垫底的空底板先画")
        self.assertEqual((items[0].rect, items[0].text, items[0].bg), (new.screen_rect(), "", (24, 24, 28)))
        self.assertIn(old.bid, [it.bid for it in items[1:]], "旧译文画在它上面")
        old.held_until = time.perf_counter() - 0.1                               # 保留时间到了：不再垫
        eng._dirty = True
        eng._publish(force=True)
        self.assertNotIn(-new.bid, [it.bid for it in snaps[-1].items])

    def test_changed_subtitle_is_read_again_across_the_whole_picture(self) -> None:
        # 字幕换句：不等视频画面静止（等不到），0.15 秒后单独识别字幕那一条，左右取整个画面（新句子可能宽得多）
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        y0 = next(y for y in range(200, 600) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        rect = (10, y0, 500, y0 + 22)
        b = add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy())
        b.state, b.translation, b.born_dynamic = "done", "我们终于到了老灯塔。", True
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]             # 换句
        eng._content_changed(m, rect)
        self.assertGreater(b.held_until, time.perf_counter(), "旧译文先留着")
        self.assertIn(b.bid, eng._recount)
        eng._recount[b.bid] = time.perf_counter() - 0.01
        eng._schedule_ocr()
        self.assertEqual(len(jobs), 1)
        r = eng.jobs[jobs[0].job_id].rect
        self.assertEqual((r[0], r[2]), (0, W), "左右取整个画面")
        self.assertLessEqual(r[1], y0 - 22)
        self.assertGreaterEqual(r[3], y0 + 22 + 10)


class FirstSubtitleTest(unittest.TestCase):
    def _setup(self):
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        y0 = next(y for y in range(200, 600) if page[y:y + 22, 10:500].std() > 40 and page[y, 10:500].min() == 255)
        rect = (10, y0, 500, y0 + 22)
        b = add_block(eng, sc, rect, page[y0:y0 + 22, 10:500].copy())
        b.state, b.translation = "done", "我们终于到了老灯塔。"
        now = time.perf_counter()
        rows, cols = slice(y0 // E.TILE, (y0 + 22) // E.TILE + 1), slice(0, 500 // E.TILE + 1)
        m.last_chg[rows, cols], m.chg_start[rows, cols] = now, now - 5      # 视频画面：这一片一直在动
        return eng, m, win, b, y0

    def test_first_subtitle_on_moving_picture_keeps_old_translation(self) -> None:
        # 刚打开视频时第一句字幕建块那会儿画面还没被认定在动（没标成字幕）：换句时也要先留着旧译文，不空一秒
        eng, m, win, b, y0 = self._setup()
        self.assertFalse(b.born_dynamic)
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]             # 换句
        self.assertFalse(eng._verify(b))
        self.assertTrue(b.born_dynamic)
        self.assertGreater(b.held_until, time.perf_counter())

    def test_recently_scrolled_window_is_not_treated_as_video(self) -> None:
        # 画面在变是滚动造成的：网页文字照常一变就撤（不留旧译文）
        eng, m, win, b, y0 = self._setup()
        win.last_scroll_ok = time.perf_counter()
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]
        self.assertFalse(eng._verify(b))
        self.assertFalse(b.born_dynamic)
        self.assertEqual(b.held_until, 0.0)

    def test_held_subtitle_survives_a_read_with_dropped_results(self) -> None:
        # 换句后单独识别那一条：新句子的结果要是因为识别期间画面变了被丢掉，“没认出来”不可信，旧译文接着留着；
        # 字幕真的消失（识别结果干净、什么都没有）才撤下
        eng, m, win, b, y0 = self._setup()
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        b.born_dynamic = True
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]             # 换句
        self.assertFalse(eng._verify(b))
        b.ok_rect = None
        self.assertGreater(b.held_until, time.perf_counter())

        def read(stale: int) -> None:
            eng.ocr_busy = None
            eng._submit_ocr(m, (0, y0 - 20, W, y0 + 42))
            st = eng.jobs[jobs[-1].job_id]
            st.stale = stale
            eng._finish_job(st, {"blocks": 0})

        read(1)
        self.assertIn(b.bid, eng.blocks, "有结果被丢掉：旧译文接着留着")
        read(0)
        self.assertNotIn(b.bid, eng.blocks, "识别结果干净、什么都没有：字幕没了，撤下")

    def test_subtitle_changed_just_before_a_read_with_dropped_results(self) -> None:
        # 换了句、还没轮到核对这一块，识别就先完成了，而且新句子的结果因为画面在变被丢掉：
        # 这时才核对出来换了句（开始留着旧译文），也不能因为“没认出来”就删
        eng, m, win, b, y0 = self._setup()
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        b.born_dynamic = True
        m.cur[y0:y0 + 22, 10:500] = 255 - m.cur[y0:y0 + 22, 10:500]             # 换句（还没核对）
        eng._submit_ocr(m, (0, y0 - 20, W, y0 + 42))
        st = eng.jobs[jobs[-1].job_id]
        st.stale = 1
        eng._finish_job(st, {"blocks": 0})
        self.assertIn(b.bid, eng.blocks)
        self.assertGreater(b.held_until, time.perf_counter(), "核对出换了句：旧译文留着")

    def test_complete_read_gives_its_cached_translation_to_waiting_block(self) -> None:
        # 新句子第一次少认了句末的“。”（查不到缓存，正在请求翻译），旧字幕留着；第二次认全了，而这一句早就译过：
        # 直接把译文给正在等的块、旧字幕退场。以前会先把旧字幕删掉、等的块继续干等，空一秒
        from deskmirror.ocr_worker import OcrBlockOut, OcrLineOut
        eng, m, win, b, y0 = self._setup()
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        rect = b.rect
        held = b                                                    # 上一句的译文还留着
        held.born_dynamic, held.ok_rect = True, None
        held.hold_start = time.perf_counter()
        held.held_until, held.hold_rect = held.hold_start + 4.0, held.screen_rect()
        waiting = add_block(eng, held.canvas, rect, m.cur[y0:y0 + 22, 10:500].copy())
        waiting.text, waiting.key = "我们终于到了那座老灯塔", E.textutil.cache_key("我们终于到了那座老灯塔")
        waiting.state, waiting.born_dynamic, waiting.replaces = "translating", True, [held.bid]
        full = "我们终于到了那座老灯塔。"
        eng.cache[E.textutil.cache_key(full)] = "We finally made it to the old lighthouse."
        eng._submit_ocr(m, (0, y0 - 20, W, y0 + 42))
        eng._accept_block(eng.jobs[jobs[-1].job_id], OcrBlockOut(rect, [OcrLineOut(rect, full, 0.99)], full))
        self.assertEqual((waiting.state, waiting.translation), ("done", "We finally made it to the old lighthouse."))
        self.assertNotIn(held.bid, eng.blocks, "新译文有了，旧字幕退场")
        self.assertFalse(any(x.text == full for x in eng.blocks.values()), "不另建一块")

    def test_text_on_moving_background_becomes_subtitle(self) -> None:
        # 背景在动、笔画没变：核对通过，而且补上字幕的标记（下次换句先留着旧译文）
        eng, m, win, b, y0 = self._setup()
        patch = m.cur[y0:y0 + 22, 10:500]
        light = patch > 200
        patch[light] = np.random.default_rng(1).integers(205, 256, int(light.sum())).astype(np.uint8)
        self.assertTrue(eng._verify(b))
        self.assertTrue(b.born_dynamic)


class VerticalBlockTest(unittest.TestCase):
    def test_vertical_columns_become_one_line_sized_by_column_width(self) -> None:
        # 漫画气泡里的竖排两列：合成一段（译文横着排在两列占的地方），字号按列宽算（按框高算会大得离谱）
        from deskmirror.ocr_worker import OcrBlockOut, OcrLineOut
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        right, left = (460, 200, 512, 360), (404, 202, 456, 460)
        rect = (404, 200, 512, 460)
        ob = OcrBlockOut(rect, [OcrLineOut(right, "待って！", 0.9), OcrLineOut(left, "船が出ちゃう！", 0.98)],
                         "待って！船が出ちゃう！", vertical=True)
        eng._submit_ocr(m, (380, 180, 540, 480))
        eng._accept_block(eng.jobs[jobs[-1].job_id], ob)
        new = [b for b in eng.blocks.values() if b.text == "待って！船が出ちゃう！"]
        self.assertEqual(len(new), 1)
        b = new[0]
        self.assertEqual(b.lines, [(b.rect, b.text)], "两列合成一行")
        self.assertAlmostEqual(b.em, 52 * 0.95)
        self.assertEqual(b.line_h, round(52 * 1.25))
        self.assertEqual(b.cols, [(56, 0, 108, 160), (0, 2, 52, 260)], "各列的位置（相对块左上角）：底板只盖这几列")

    def test_vertical_plates_and_size_follow_the_ink(self) -> None:
        # 检测框左右多出好几像素（长的一列更多）：底板只盖各列字的墨迹，字号也按墨迹宽度估（不比按框宽估的大）
        from deskmirror.ocr_worker import OcrBlockOut, OcrLineOut
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.visible = {1: [(0, 0, W, H)]}
        eng.set_mirrors([(0, 0, W, H)])
        m.bgra = np.dstack([m.cur] * 3 + [np.full_like(m.cur, 255)])
        eng.win_canvas[1], eng.win_rects[1], eng.z_order = win, (0, 0, W, H), [1]
        jobs = []

        class Ocr:
            def submit(self, job) -> None:
                jobs.append(job)

        eng.ocr, eng.ocr_state = Ocr(), "ready"
        right, left = (460, 200, 512, 360), (404, 202, 456, 460)
        ob = OcrBlockOut((404, 200, 512, 460),
                         [OcrLineOut(right, "待って！", 0.9, ink=[(470, 204, 500, 240), (480, 330, 490, 356)]),
                          OcrLineOut(left, "船が出ちゃう！", 0.98, ink=[(412, 206, 444, 240), (424, 420, 432, 456)])],
                         "待って！船が出ちゃう！", vertical=True)
        eng._submit_ocr(m, (380, 180, 540, 480))
        eng._accept_block(eng.jobs[jobs[-1].job_id], ob)
        b = next(b for b in eng.blocks.values() if b.text == "待って！船が出ちゃう！")
        self.assertEqual(b.cols, [(66, 4, 96, 40), (76, 130, 86, 156), (8, 6, 40, 40), (20, 220, 28, 256)],
                         "每个字的墨迹（相对块左上角）")
        self.assertAlmostEqual(b.em, 30 / 0.92 / 0.74, msg="整列墨迹宽 30（去掉两边各留的 1 像素），比按框宽估的 52×0.95 小")


class ChatSwitchTest(unittest.TestCase):
    def test_chat_apps_follow_the_switch(self) -> None:
        # 聊天软件默认不翻（私人聊天不发出去）；打开“翻译聊天软件”就照常翻；密码管理器始终不翻
        from unittest import mock
        page = text_page(3000, W, 6)
        eng, m, win, sc = make_engine(page[0:H])
        eng.win_pids = {11: 101, 12: 102, 13: 103}
        eng._proc_names = {101: "wechat.exe", 102: "keepass.exe", 103: "chrome.exe"}
        titles = {11: "微信", 12: "KeePass", 13: "WhatsApp Web - Google Chrome"}
        with mock.patch.object(E.winapi, "window_title", side_effect=lambda h: titles[h]):
            eng._refresh_privacy(time.perf_counter() + 1)
            self.assertEqual(eng._excluded, {11, 12, 13})
            self.assertEqual(eng._excluded_chat, {11, 13}, "因为是聊天软件才不翻的：标签上提示可以打开")
            eng.cfg.scope.translate_chat = True
            eng._refresh_privacy(time.perf_counter() + 2)
            self.assertEqual(eng._excluded, {12}, "聊天软件照常翻，密码管理器仍不翻")
            self.assertEqual(eng._excluded_chat, set())


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
