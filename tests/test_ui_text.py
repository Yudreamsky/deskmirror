"""英文软件界面（Houdini 这类）的文字：并排的按钮名拆开、两行写的名字合成一块、按笔画估字号、照原文对齐、
短标签不折行、快捷键不翻译、标签页的底色（合成画面，不启动采集、识别和翻译）。"""
from __future__ import annotations

import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import deskmirror  # noqa: E402,F401  预加载 DLL
from deskmirror import layout, textutil  # noqa: E402
from deskmirror.layout import Line  # noqa: E402
from deskmirror.scene import DrawItem  # noqa: E402

from tests.test_engine import add_block, make_engine  # noqa: E402
from tests.test_pixels import text_page  # noqa: E402


def _glyphs(img: np.ndarray, y0: int, y1: int, x: int, words: list[int], letter: int = 5, gap_letter: int = 1,
            gap_word: int = 3) -> int:
    """在 img 上画一行“字”：words 是每个词的字母数；返回画到哪儿。"""
    for wi, n in enumerate(words):
        for _ in range(n):
            img[y0:y1, x:x + letter] = 220
            x += letter + gap_letter
        x += gap_word - gap_letter
    return x


class SplitTest(unittest.TestCase):
    def test_labels_side_by_side_are_split(self) -> None:
        # Houdini 工具架：“Spot Light”“Area Light”中间空 12 像素（词距 3 像素），检测框把两个框成了一行
        img = np.full((40, 300), 58, np.uint8)
        end = _glyphs(img, 14, 24, 20, [4, 5])
        _glyphs(img, 14, 24, end + 12 - 3, [4, 5])
        pieces = layout.split_wide_gaps(img, (16, 11, 150, 27))
        self.assertEqual(len(pieces), 2)
        self.assertLessEqual(pieces[0][2], pieces[1][0])
        self.assertTrue(pieces[0][0] == 16 and pieces[1][2] >= 140, "两头照原来的框留白")

    def test_words_of_one_label_stay_together(self) -> None:
        img = np.full((40, 300), 58, np.uint8)
        _glyphs(img, 14, 24, 20, [8, 3, 4])           # Increase per Turn：词距 3～5 像素
        self.assertEqual(layout.split_wide_gaps(img, (16, 11, 150, 27)), [(16, 11, 150, 27)])

    def test_flat_or_textured_box_is_left_alone(self) -> None:
        img = np.full((40, 300), 58, np.uint8)
        self.assertEqual(layout.split_wide_gaps(img, (16, 11, 150, 27)), [(16, 11, 150, 27)])
        noisy = np.random.default_rng(1).integers(0, 255, (40, 300)).astype(np.uint8)
        self.assertEqual(layout.split_wide_gaps(noisy, (16, 11, 150, 27)), [(16, 11, 150, 27)])


class StackTest(unittest.TestCase):
    def test_two_line_name_under_an_icon(self) -> None:
        # Houdini 的 Geometry / Light：两行居中、框叠在一起
        geo, light = (253, 50, 308, 67), (263, 61, 298, 79)
        self.assertTrue(layout.centered_stack(geo, light))
        paras = layout.candidate_paragraphs([geo, light])
        self.assertEqual(len(paras), 1)
        drafts = layout.split_by_text([Line(geo, "Geometry", 1.0), Line(light, "Light", 1.0)])
        self.assertEqual([layout.join_lines(d.lines) for d in drafts], ["Geometry Light"])

    def test_menu_items_and_icons_are_not_stacks(self) -> None:
        # 菜单项左对齐、中线不齐；上面的图标认成“●”的不和名字合成一块
        self.assertFalse(layout.centered_stack((100, 10, 160, 27), (100, 31, 140, 48)))
        self.assertFalse(layout.centered_stack((617, 141, 652, 159), (617, 163, 652, 181)), "一样宽的 Copy / Paste")
        icon, label = (200, 40, 222, 60), (190, 58, 232, 74)
        drafts = layout.split_by_text([Line(icon, "●", 1.0), Line(label, "Area Light", 1.0)])
        self.assertEqual(len(drafts), 2)

    def test_spaced_centered_lines_stay_apart(self) -> None:
        # 游戏里居中的竖排菜单（新游戏 / 读取）：行距宽，各是一项
        self.assertFalse(layout.centered_stack((300, 100, 400, 130), (310, 150, 390, 180)))


class LabelAndSizeTest(unittest.TestCase):
    def test_is_label(self) -> None:
        for t in ("Point Light", "Save As...", "Increase per Turn", "灯光和摄像机"):
            self.assertTrue(layout.is_label(t), t)
        for t in ("This is a sentence.", "Boats leave every hour from Pier 2 and come back at noon",
                  "这是一句很长很长的中文句子，用来说明问题。"):
            self.assertFalse(layout.is_label(t), t)

    def test_short_words_sized_by_ink_not_box(self) -> None:
        # “Line”“Camera”这种短词，检测框两头的留白占比大：按字宽估会大一圈，按笔画估和别的名字一样
        line = Line((0, 0, 44, 14), "Camera")
        self.assertAlmostEqual(layout.font_em(line, 10.0), 13.0)
        long = Line((0, 0, 600, 20), "Boats leave every hour from Pier 2, rain or shine")
        cw_em = layout.font_em(long)
        self.assertAlmostEqual(layout.font_em(long, cw_em / 1.3), cw_em, places=5)
        self.assertLessEqual(layout.font_em(long, 10.0), 1.1 * 13.0 + 1e-9, "长行按字宽，但不离笔画太远")

    def test_line_ink_share_by_letter_shapes(self) -> None:
        # 同样 10 像素高的墨迹：有上伸又有下伸（Light）、只有上伸（Paste）、中文
        patch = np.full((24, 60, 3), 40, np.uint8)
        patch[6:16, 5:55] = 210
        r = [(0, 0, 60, 24)]
        light = textutil.line_ink(patch, r, ["Light"], (40, 40, 40), (210, 210, 210))[0]
        paste = textutil.line_ink(patch, r, ["Paste"], (40, 40, 40), (210, 210, 210))[0]
        han = textutil.line_ink(patch, r, ["灯光"], (40, 40, 40), (210, 210, 210))[0]
        self.assertEqual(light[:4], (5, 6, 55, 16))
        self.assertAlmostEqual(light[4], round(10 / 0.94, 2))
        self.assertAlmostEqual(paste[4], round(10 / 0.72, 2))
        self.assertAlmostEqual(han[4], round(10 / 0.88, 2))

    def test_underline_is_not_ink(self) -> None:
        patch = np.full((24, 60, 3), 255, np.uint8)
        patch[6:16, 5:55] = 0
        patch[20, :] = 0                       # 链接的下划线横贯整行
        ink = textutil.line_ink(patch, [(0, 0, 60, 24)], ["Paste"], (255, 255, 255), (0, 0, 0))[0]
        self.assertEqual(ink[3], 16)


class ColorAndShortcutTest(unittest.TestCase):
    def test_tab_plate_takes_the_tab_color(self) -> None:
        # 标签页：框外一圈碰到黑色的边框和缝，框里是灰的标签页底色：底板用灰色，不是一块黑方块
        img = np.zeros((26, 80, 3), np.uint8)
        img[3:23, 3:77] = (86, 86, 86)
        img[10:16, 15:65:3] = (240, 240, 240)
        bg, fg = textutil.sample_colors(img, [(3, 3, 77, 23)])
        self.assertEqual(bg, (86, 86, 86))
        self.assertGreater(sum(fg), 600)

    def test_dropdown_gradient_plate(self) -> None:
        # 下拉框上浅下深：底板照着画渐变；纯色的底不用
        img = np.zeros((24, 120, 3), np.uint8)
        for y in range(24):
            img[y, :] = 93 - y                     # 93 → 70
        img[9:15, 20:100:3] = 235                  # 字
        grad = textutil.plate_gradient(img, [(2, 2, 118, 22)], (82, 82, 82), (235, 235, 235))
        self.assertIsNotNone(grad)
        self.assertGreater(grad[0][0], grad[1][0] + 10)
        flat = np.full((24, 120, 3), 60, np.uint8)
        flat[9:15, 20:100:3] = 235
        self.assertIsNone(textutil.plate_gradient(flat, [(2, 2, 118, 22)], (60, 60, 60), (235, 235, 235)))

    def test_shortcuts(self) -> None:
        for t in ("Ctrl+C", "Alt+Shift+F4", "F2", "ctrl + v", "Shift+Del"):
            self.assertTrue(textutil.looks_like_shortcut(t), t)
        for t in ("Delete", "Copy", "Ctrl", "Paste Special", "F2 Rename"):
            self.assertFalse(textutil.looks_like_shortcut(t), t)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _item(text: str, rect, align: str = "left", ink=None, room=None, label: bool = True, n_lines: int = 1) -> DrawItem:
    h = rect[3] - rect[1]
    return DrawItem(1, 1, rect, room or rect, (rect,), text, (58, 58, 58), (230, 230, 230), h // n_lines, n_lines,
                    15.0, align=align, ink=ink, label=label)


def _ink_cols(r) -> tuple[int, int]:
    from PySide6.QtGui import QImage
    img = r.image.convertToFormat(QImage.Format.Format_ARGB32)
    a = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(img.height(), img.bytesPerLine() // 4, 4)
    xs = np.flatnonzero((a[:, :img.width(), 1] > 150).any(axis=0))
    return int(xs[0]) + r.dx, int(xs[-1]) + 1 + r.dx


class RenderAlignTest(unittest.TestCase):
    def setUp(self) -> None:
        _app()
        from deskmirror.config import StyleConfig
        from deskmirror.ui.render import Renderer
        self.r = Renderer(StyleConfig())

    def test_right_aligned_label_ends_at_the_original_ink(self) -> None:
        # 参数名右对齐贴着输入框：译文的右边对齐原文最后一个字母的右边（不是检测框的边）
        r = self.r.get(_item("Increase", (100, 0, 220, 20), "right", ink=(5, 4, 114, 16)))   # 离屏环境没有中文字体，用英文
        left, right = _ink_cols(r)
        # 离屏测试环境的字体是等宽方块，画出来的边和量出来的差几像素（真字体差 1～2 像素）；左对齐的话右边会差 13 像素
        self.assertLessEqual(abs(right - 114), 5)
        self.assertGreater(left, 10)

    def test_centered_label_keeps_its_center(self) -> None:
        r = self.r.get(_item("Point", (50, 0, 115, 14), "center", ink=(4, 3, 57, 13)))
        left, right = _ink_cols(r)
        self.assertLessEqual(abs((left + right) / 2 - 30.5), 2)

    def test_left_label_starts_at_the_ink_not_the_box(self) -> None:
        r = self.r.get(_item("Height", (0, 0, 90, 20), "left", ink=(7, 4, 85, 16)))
        self.assertLessEqual(abs(_ink_cols(r)[0] - 7), 2)

    def test_label_never_wraps(self) -> None:
        # 放不下的短标签：一行，截断（鼠标停上去看全文），不折成两行盖到别的行上
        r = self.r.get(_item("运动特效视图运动特效视图", (0, 0, 60, 18), "left", ink=(3, 3, 57, 15)))
        self.assertLessEqual(r.height, 18 + 2 * 2)
        self.assertTrue(r.truncated)

    def test_two_line_name_splits_evenly(self) -> None:
        from PySide6.QtGui import QFont
        from deskmirror.ui.render import _balanced
        f = QFont("Microsoft YaHei UI")
        f.setPixelSize(12)
        self.assertEqual(_balanced("几何体灯光", 2, f, 1000), [(0, 3), (3, 2)])
        self.assertEqual(_balanced("Geometry Light", 2, f, 1000), [(0, 8), (9, 5)])
        self.assertIsNone(_balanced("几何体灯光", 2, f, 10))
        r = self.r.get(_item("柏拉图立体", (780, 50, 830, 80), "center", ink=(8, 5, 49, 27), n_lines=2))
        self.assertFalse(r.truncated)
        self.assertLess(_ink_cols(r)[1] - _ink_cols(r)[0], 45, "分两行，每行不超过原来的宽度")


class EngineAlignTest(unittest.TestCase):
    def _blocks(self, specs):
        page = text_page(3000, 900, 6)
        eng, m, win, sc = make_engine(page[0:1200])
        out = []
        for rect, text, label in specs:
            b = add_block(eng, sc, rect, page[rect[1]:rect[3], rect[0]:rect[2]].copy())
            b.text, b.label, b.em = text, label, 15.0
            b.em_raw = 15.0
            b.ink = (4, 3, rect[2] - rect[0] - 4, rect[3] - rect[1] - 3)
            out.append(b)
        return eng, sc, out

    def test_parameter_names_are_right_aligned(self) -> None:
        eng, sc, bs = self._blocks([((132, 77, 219, 97), "Radius Mode", True),
                                    ((134, 108, 219, 128), "Start Radius", True),
                                    ((103, 139, 219, 159), "Increase per Turn", True)])
        for b in bs:
            eng._update_align(sc, b)
        self.assertEqual([b.align for b in bs], ["right"] * 3, "后到的块把先到的也改过来")

    def test_toolbar_row_is_centered(self) -> None:
        eng, sc, bs = self._blocks([((2, 58, 46, 72), "Camera", True), ((53, 58, 114, 72), "Point Light", True),
                                    ((122, 58, 175, 72), "Spot Light", True), ((183, 58, 236, 72), "Area Light", True)])
        for b in bs:
            eng._update_align(sc, b)
        self.assertEqual([b.align for b in bs], ["center"] * 4)

    def test_one_far_coincidence_does_not_decide(self) -> None:
        # 上面一排标签页的左边碰巧和下面一个参数名的左边对齐：一块、隔得远，不算
        eng, sc, bs = self._blocks([((70, 3, 110, 20), "Modify", True), ((70, 245, 160, 262), "Increase per Turn", True)])
        for b in bs:
            eng._update_align(sc, b)
        self.assertEqual([b.align for b in bs], ["left", "left"])
        self.assertEqual([b.align_n for b in bs], [0, 0])

    def test_column_sizes_are_unified(self) -> None:
        eng, sc, bs = self._blocks([((132, 77, 219, 97), "Radius Mode", True),
                                    ((134, 108, 219, 128), "Start Radius", True),
                                    ((103, 139, 219, 159), "Increase per Turn", True)])
        bs[1].em_raw = bs[1].em = 17.0                 # 检测框差一两个像素，估出来大了一点
        for b in bs:
            eng._update_align(sc, b)
        self.assertEqual({b.em for b in bs}, {15.0})

    def test_heading_keeps_its_size(self) -> None:
        # 标题和正文左边对齐，字号差得多：不统一
        eng, sc, bs = self._blocks([((100, 100, 500, 140), "The old lighthouse", True),
                                    ((100, 160, 700, 190), "Open daily from 9 a.m. to 5 p.m.", False),
                                    ((100, 210, 650, 240), "Tickets are sold at the pier.", False)])
        bs[0].em_raw = bs[0].em = 22.0
        for b in bs:
            eng._update_align(sc, b)
        self.assertEqual(bs[0].em, 22.0)
        self.assertEqual(bs[0].align, "left")


if __name__ == "__main__":
    unittest.main()
