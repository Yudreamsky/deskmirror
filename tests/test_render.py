"""译文排版：放不下时向右借用空白（中日文译成英文常需要），借来的地方用多少占多少；
引擎只把右边纯色、没有别的字的地方算成可借的空白（合成画面，不启动采集、识别和翻译）。"""
from __future__ import annotations

import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import deskmirror  # noqa: E402,F401  预加载 DLL
from deskmirror.config import StyleConfig  # noqa: E402
from deskmirror.scene import DrawItem  # noqa: E402
from deskmirror.ui.render import Renderer  # noqa: E402

from tests.test_engine import add_block, make_engine  # noqa: E402


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def item(text: str, rect, room=None, n_lines: int = 1, bid: int = 1, stretch: int = 0) -> DrawItem:
    h = rect[3] - rect[1]
    return DrawItem(bid, 1, rect, room or rect, (rect,), text, (255, 255, 255), (0, 0, 0), h // n_lines, n_lines,
                    h / n_lines * 0.9, stretch=stretch)


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _app()

    def test_short_heading_borrows_room_to_the_right(self) -> None:
        rect = (100, 100, 232, 150)                 # “老灯塔”三个字那么宽
        narrow = Renderer(StyleConfig()).get(item("The Old Lighthouse", rect))
        self.assertTrue(narrow.truncated or narrow.font_px < round(50 * 0.9 * 0.74), "没地方借时只能缩小、截断")
        r = Renderer(StyleConfig()).get(item("The Old Lighthouse", rect, (100, 100, 2100, 150)))
        self.assertFalse(r.truncated)
        self.assertEqual(r.font_px, round(50 * 0.9 * 0.74), "借到地方就不用缩小字号")
        self.assertGreater(r.width, 232 - 100 + 4)
        self.assertLess(r.width, 2000, "借来的地方用多少占多少")
        self.assertEqual(r.height, 50 + 4, "向右借了就不用向下借")

    def test_text_that_fits_keeps_its_box(self) -> None:
        rect = (100, 100, 500, 150)
        r = Renderer(StyleConfig()).get(item("老灯塔", rect, (100, 100, 900, 150)))
        self.assertEqual(r.width, 400 + 4, "放得下就不借")

    def test_dialog_prefers_borrowing_over_shrinking(self) -> None:
        rect = (100, 100, 640, 232)                 # 两行日文对话那么大
        text = "But today it's stormy and the road is closed. Let's look for the lighthouse's underground passage."
        here = Renderer(StyleConfig()).get(item(text, rect, n_lines=2))
        r = Renderer(StyleConfig()).get(item(text, rect, (100, 100, 4100, 232), n_lines=2))
        self.assertGreater(r.font_px, here.font_px, "能向右借就少缩字号")
        self.assertEqual(r.height, 132 + 4)

    def test_plate_covers_trailing_cjk_punctuation(self) -> None:
        rect = (100, 100, 500, 140)
        it = DrawItem(1, 1, rect, rect, (rect,), "Tickets are sold at the pier.", (255, 255, 255), (0, 0, 0), 40, 1, 36,
                      src="门票在码头的售票亭购买。")
        r = Renderer(StyleConfig()).get(it)
        self.assertGreaterEqual(r.width, 400 + 4 + 24, "句末的“。”常在识别框外面，要盖住")
        self.assertEqual(Renderer(StyleConfig()).get(item("Tickets", rect)).width, 400 + 4)

    def test_word_not_split(self) -> None:
        from deskmirror.ui.render import _breaks_word
        self.assertTrue(_breaks_word("Captain Mina", [(0, 6), (6, 6)]))       # Captai / n Mina
        self.assertFalse(_breaks_word("Captain Mina", [(0, 8), (8, 4)]))      # Captain / Mina
        self.assertFalse(_breaks_word("船长米娜", [(0, 2), (2, 2)]), "中文本来就能在字之间换行")

    @staticmethod
    def _box_for(text: str, px: int, frac: float, h: int = 45):
        """宽度正好让 text 在字号 px、横向压到 frac 时放得下的单行原文框。"""
        from PySide6.QtGui import QFont, QFontMetricsF
        f = QFont(StyleConfig().font_family)
        f.setPixelSize(px)
        return (100, 100, 100 + int(QFontMetricsF(f).horizontalAdvance(text) * frac) + 2, 100 + h)

    def test_mild_squash_before_shrinking(self) -> None:
        # 英文比原文长一点：先横向压扁一点（八成以内几乎看不出来），字号不变
        text, base = "Time left 02:06", round(45 * 0.9 * 0.74)
        r = Renderer(StyleConfig()).get(item(text, self._box_for(text, base, 0.86)))
        self.assertEqual(r.font_px, base)
        self.assertTrue(0.8 <= r.squash < 1.0, r.squash)
        self.assertEqual(r.height, 45 + 4)

    def test_label_in_panel_squashes_instead_of_spilling_below(self) -> None:
        # 面板里的名牌、倒计时：缩到最小比例、压到八成还放不下时，下面是面板边框（不是空白）就再压扁一些（最扁六成），
        # 不伸出面板；下面是空白（比如网页标题下面）才照旧向下排成两行、不压那么扁
        text, base = "Time left 02:06", round(45 * 0.9 * 0.74)
        rect = self._box_for(text, base, 0.52)
        room = (rect[0], rect[1], rect[2], 145 + 90)
        spill = Renderer(StyleConfig()).get(item(text, rect, room))
        self.assertGreater(spill.height, 45 + 4, "下面是空白：照旧向下排")
        self.assertGreaterEqual(spill.squash, 0.8)
        it = DrawItem(1, 1, rect, room, (rect,), text, (255, 255, 255), (0, 0, 0), 45, 1, 45 * 0.9, soft=145 + 3)
        r = Renderer(StyleConfig()).get(it)
        self.assertEqual(r.height, 45 + 4, "下面是边框：不伸出去")
        self.assertFalse(r.truncated)
        self.assertTrue(0.6 <= r.squash < 0.8, r.squash)
        self.assertGreaterEqual(r.font_px, round(base * 0.75) - 1)

    def test_cjk_squashed_at_most_to_80_percent(self) -> None:
        # 中日韩文字压扁了难看：最多压到八成，再不行就缩字号
        text = "剩余时间还有很多很多"
        rect = self._box_for(text, round(45 * 0.9 * 0.74), 0.5)
        it = DrawItem(1, 1, rect, (rect[0], rect[1], rect[2], 235), (rect,), text, (255, 255, 255), (0, 0, 0), 45, 1,
                      45 * 0.9, soft=148)
        self.assertGreaterEqual(Renderer(StyleConfig()).get(it).squash, 0.8)

    def test_two_lines_in_one_line_box_stay_inside_the_plate(self) -> None:
        # 识别框比字高的单行原文（小名牌）：译文缩小排成两行塞进原来的高度时整段竖直居中，第二行不能掉出底板被裁掉
        from PySide6.QtGui import QFont, QFontMetricsF
        f = QFont(StyleConfig().font_family)
        f.setPixelSize(22)
        rect = (100, 100, 100 + int(QFontMetricsF(f).horizontalAdvance("Captain") * 1.05) + 2, 160)
        it = DrawItem(1, 1, rect, rect, (rect,), "Captain Mina", (255, 255, 255), (0, 0, 0), 60, 1, 30)
        r = Renderer(StyleConfig()).get(it)
        self.assertEqual(r.height, 60 + 4)
        ink = [y for y in range(r.height) if any(r.image.pixelColor(x, y).red() < 128 for x in range(r.width))]
        self.assertTrue(ink, "画了字")
        self.assertGreater(min(ink), 1)
        self.assertLess(max(ink), r.height - 2, "最后一行的字没被底板下边裁掉")
        self.assertLess(abs(min(ink) - (r.height - 1 - max(ink))), 12, "整段大致竖直居中")

    def test_empty_text_is_just_a_plate(self) -> None:
        # 换句时垫在新句子下面的空底板：只有底色，大小和原文块一样
        rect = (100, 100, 400, 140)
        r = Renderer(StyleConfig()).get(DrawItem(-1, 1, rect, rect, (rect,), "", (24, 24, 28), (245, 245, 245), 40, 1, 36))
        self.assertEqual((r.width, r.height, r.truncated), (300 + 4, 40 + 4, False))
        c = r.image.pixelColor(150, 20)
        self.assertEqual((c.red(), c.green(), c.blue()), (24, 24, 28))

    def test_vertical_bubble_translation_reads_vertically(self) -> None:
        # 竖排气泡的中文译文也竖着排：在“！”后面换列，标点换成竖排的写法；英文译文照旧横排
        from unittest import mock

        from deskmirror.ui.render import _vertical_columns
        self.assertEqual(_vertical_columns("等等！船要开了！", 5), [list("等等！"), list("船要开了！")])
        self.assertEqual(_vertical_columns("快跑——！", 6), [["快", "跑", chr(0xFE31), chr(0xFE31), "！"]])
        self.assertEqual(_vertical_columns("我们终于到了那座老灯塔", 4), [list("我们终于"), list("到了那座"), list("老灯塔")])
        rect = (0, 0, 81, 204)

        def bubble(text: str) -> DrawItem:
            return DrawItem(9, 1, rect, rect, (rect,), text, (255, 255, 255), (0, 0, 0), 65, 1, 52 * 0.95, src="x",
                            vertical=True)

        with mock.patch.object(Renderer, "_render_vertical", wraps=Renderer(StyleConfig())._render_vertical) as spy:
            r = Renderer(StyleConfig()).get(bubble("等等！船要开了！"))
            self.assertEqual(spy.call_count, 1)
            self.assertEqual((r.width, r.height), (81 + 4, 204 + 4))
            Renderer(StyleConfig()).get(bubble("Wait! The ship is leaving!"))
            self.assertEqual(spy.call_count, 1, "英文不竖着排")

    def test_vertical_bubble_plate_covers_only_columns_and_text(self) -> None:
        # 两列长短不一（右边一列短）：底板只盖原来的两列和译文，不铺满两列合起来的方块——
        # 方块右下角在椭圆气泡外面，铺满会盖掉气泡的弧形边框
        rect, cols = (0, 0, 81, 204), ((44, 0, 81, 124), (0, 2, 37, 204))

        def bubble(text: str) -> DrawItem:
            return DrawItem(9, 1, rect, rect, (rect,), text, (255, 255, 255), (0, 0, 0), 65, 1, 37 * 0.95, src="x",
                            vertical=True, cols=cols)

        def alpha(r, x: int, y: int) -> int:          # 原文块坐标 → 图片坐标
            return r.image.pixelColor(x - r.dx, y - r.dy).alpha()

        for text in ("等等！船要开了！", "Go!"):
            r = Renderer(StyleConfig()).get(bubble(text))
            self.assertEqual(alpha(r, 78, 200), 0, f"{text}：短的那列下面、方块的角上不画底板")
            self.assertGreater(alpha(r, 60, 120), 0, f"{text}：原文的右列盖住")
            self.assertGreater(alpha(r, 18, 200), 0, f"{text}：原文的左列盖住")
        img = r.image                                 # 横排的译文（英文）：在气泡里左右居中
        ink = [x for x in range(img.width()) for y in range(img.height())
               if img.pixelColor(x, y).alpha() > 200 and img.pixelColor(x, y).red() < 100]
        self.assertTrue(ink)
        self.assertLess(abs((min(ink) + max(ink)) / 2 - img.width() / 2), 4, "横排的译文在气泡里居中")

    def test_long_word_widens_plate_instead_of_splitting(self) -> None:
        rect = (100, 100, 160, 134)                 # “装備”两个字那么宽，右边不是纯色空白
        r = Renderer(StyleConfig()).get(item("Equipment", rect, (100, 100, 160, 200), stretch=700))
        self.assertFalse(r.truncated)
        self.assertGreater(r.width, 60 + 4, "底板放宽到放得下整个词")
        self.assertLessEqual(r.width, 700 - 100 + 4, "不越过右边的字")

    def test_long_word_never_runs_into_next_label(self) -> None:
        rect = (100, 100, 160, 134)                 # 右边紧挨着下一个菜单项
        r = Renderer(StyleConfig()).get(item("Equipment", rect, (100, 100, 160, 200), stretch=170))
        self.assertLessEqual(r.width, 170 - 100 + 4)

    def test_room_change_relayouts(self) -> None:
        rnd = Renderer(StyleConfig())
        rect = (100, 100, 232, 150)
        a = rnd.get(item("The Old Lighthouse", rect))
        b = rnd.get(item("The Old Lighthouse", rect, (100, 100, 700, 150)))
        self.assertNotEqual(a.width, b.width, "可借的宽度变了要重新排版")


class RoomRightTest(unittest.TestCase):
    def page(self) -> np.ndarray:
        frame = np.full((1200, 900), 255, np.uint8)
        frame[100:140, 10:130] = 40                 # 原文（深色字）
        frame[90:170, 300:500] = 150                # 右边有一张图
        return frame

    def test_borrows_plain_space_until_picture(self) -> None:
        eng, m, win, _sc = make_engine(self.page())
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertTrue(150 <= b.extra_w <= 170, b.extra_w)     # 到图片前面为止，留一点距离

    def test_limited_by_block_on_the_right(self) -> None:
        eng, m, win, _sc = make_engine(self.page())
        add_block(eng, win, (230, 105, 290, 135), m.cur[105:135, 230:290].copy())
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertEqual(b.extra_w, 230 - 20 - 130)              # 右边的块前面留半个行高

    def test_new_block_takes_back_borrowed_space(self) -> None:
        eng, m, win, _sc = make_engine(self.page())
        a = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, a, m)
        v = a.version
        b = add_block(eng, win, (200, 104, 260, 136), m.cur[104:136, 200:260].copy())
        eng._update_room(win, b, m)
        self.assertEqual(a.extra_w, 200 - 20 - 130)
        self.assertGreater(a.version, v, "左边那块要重新排版")

    def test_specks_behind_translucent_panel_still_count_as_plain(self) -> None:
        frame = self.page()
        frame[110, 160] = frame[125, 200] = frame[131, 240] = 230    # 半透明面板后面透出来的星点
        eng, m, win, _sc = make_engine(frame)
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertTrue(150 <= b.extra_w <= 170, b.extra_w)
        frame[:, 180:183] = 120                                      # 一条整列的边框线
        eng, m, win, _sc = make_engine(frame)
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertEqual(b.extra_w, 180 - 130 - 6)

    def test_no_borrowing_over_moving_picture(self) -> None:
        import time

        from deskmirror import engine as E
        eng, m, win, _sc = make_engine(self.page())
        now = time.perf_counter()
        m.last_chg[:, 140 // E.TILE:] = now                        # 右边一直在变（视频画面），颜色却和底色一样
        m.chg_start[:, 140 // E.TILE:] = now - 5
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertEqual(b.extra_w, 0)

    def test_counter_still_borrows_while_its_digits_change(self) -> None:
        # 倒计时：原文自己每秒都在变，面板外面还有动画；原文右边那片是静止的纯色，照样能借（不然译文忽大忽小）
        import time

        from deskmirror import engine as E
        eng, m, win, _sc = make_engine(self.page())
        now = time.perf_counter()
        rows, own = slice(100 // E.TILE, 140 // E.TILE + 1), slice(0, 130 // E.TILE + 1)
        m.last_chg[rows, own] = now                                 # 原文所在的格子（含最右边那格）一直在变
        m.chg_start[rows, own] = now - 5
        m.last_chg[:, 304 // E.TILE:] = now                         # 图片那边也在动（游戏背景的动画）
        m.chg_start[:, 304 // E.TILE:] = now - 5
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertTrue(150 <= b.extra_w <= 170, b.extra_w)

    def test_cut_off_glyph_does_not_block_borrowing(self) -> None:
        # 识别框没把最后一个字框全：紧挨着的几列只露出一点笔画，照样能借右边的空白；整列的边框照样挡住
        frame = self.page()
        frame[110:125, 130:133] = 40                                 # 最后一个字露在框外的一截
        eng, m, win, _sc = make_engine(frame)
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertTrue(150 <= b.extra_w <= 170, b.extra_w)
        frame[96:144, 131:133] = 120                                 # 紧贴着的一条竖边框
        eng, m, win, _sc = make_engine(frame)
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertEqual(b.extra_w, 0)

    def test_animation_beside_narrow_gap_does_not_block(self) -> None:
        # 原文右边只剩一小条空白，再往右是面板边框和在动的游戏画面：那一小条照样能借（只看整格都在那一小条里的格子）
        import time

        from deskmirror import engine as E
        frame = self.page()
        frame[90:150, 150:153] = 120                                 # 面板右边框
        eng, m, win, _sc = make_engine(frame)
        now = time.perf_counter()
        m.last_chg[:, 144 // E.TILE:] = now                         # 边框外面一直在动（含跨着边框的那一格）
        m.chg_start[:, 144 // E.TILE:] = now - 5
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertEqual(b.extra_w, 150 - 130 - 6)

    def test_room_below_is_only_plain_space(self) -> None:
        # 向下借地方只算同色的空白：面板边框以下不算（倒计时、按钮的译文不伸出面板）
        frame = self.page()
        eng, m, win, _sc = make_engine(frame)
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertEqual(b.plain_below, b.room_bottom - b.rect[3], "下面是空白：能借多少借多少")
        frame[160:163, 0:400] = 120                                  # 原文下面 20 像素处一条横边框
        eng, m, win, _sc = make_engine(frame)
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        eng._update_room(win, b, m)
        self.assertEqual(b.plain_below, 160 - 140 - 3)
        b.dynamic = True
        eng._update_room(win, b, m)
        self.assertEqual(b.plain_below, -1, "字幕这类深色底板的字照旧向下排")

    def test_no_borrowing_on_busy_background(self) -> None:
        eng, m, win, _sc = make_engine(self.page())
        b = add_block(eng, win, (10, 100, 130, 140), m.cur[100:140, 10:130].copy())
        b.dynamic = True
        eng._update_room(win, b, m)
        self.assertEqual(b.extra_w, 0)


if __name__ == "__main__":
    unittest.main()
