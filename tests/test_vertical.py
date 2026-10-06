"""竖排文字（漫画气泡）：切成单字、找出写成竖线的长音、几列从右往左连起来（用本机日文字体画测试图，不加载识别模型）。"""
from __future__ import annotations

import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror import vertical as V

FONT = "C:/Windows/Fonts/YuGothM.ttc"


def column(chars: str, size: int = 34, pitch: int = 42, bar_at: tuple = ()) -> np.ndarray:
    """白底黑字竖排一列（BGR）；bar_at 里的位置画成一整条竖线（竖排的长音）。"""
    font = ImageFont.truetype(FONT, size)
    w = size + 16
    img = Image.new("RGB", (w, pitch * len(chars) + 16), "white")
    d = ImageDraw.Draw(img)
    for i, ch in enumerate(chars):
        y = 8 + i * pitch
        if i in bar_at:
            d.rectangle([w // 2 - 2, y + 2, w // 2 + 2, y + pitch - 6], fill="black")
        else:
            d.text((8, y), ch, font=font, fill="black")
    return np.asarray(img)[:, :, ::-1].copy()


class VerticalTest(unittest.TestCase):
    def test_tall_boxes_are_columns(self) -> None:
        self.assertTrue(V.is_column((0, 0, 50, 160)))
        self.assertFalse(V.is_column((0, 0, 200, 40)), "横排的一行")
        self.assertFalse(V.is_column((0, 0, 40, 50)), "单个字")

    def test_cells_one_per_character(self) -> None:
        cells, bars, bg = V.column_cells(column("待って！"))
        self.assertEqual(len(cells), 4, "“！”的点并给那一竖，不单独成一格")
        self.assertEqual(bars, [False] * 4)
        self.assertGreater(bg, 200)
        cells, _bars, _bg = V.column_cells(column("船が出ちゃう"))
        self.assertEqual(len(cells), 6, "“う”头上的一横归“う”，不并给上面的“ゃ”")

    def test_vertical_bar_is_a_long_vowel(self) -> None:
        cells, bars, _bg = V.column_cells(column("走れーっ", bar_at=(2,)))
        self.assertEqual(bars, [False, False, True, False])
        self.assertGreater(cells[2].shape[1], 0)
        self.assertEqual(V.fill_bars("走れ一っ", 1), "走れーっ", "模型认成“一”：按竖线的位置换成长音")
        self.assertIsNone(V.fill_bars("もう一度走れ一", 1), "像横线的字比竖线多：对不上，分段再认")
        self.assertEqual(V.bar_char("走れ"), "ー")
        self.assertEqual(V.bar_char("我们走"), "—", "中文竖排：破折号")
        runs = V.split_at_bars(cells, bars)
        self.assertEqual([len(r) for r in runs], [2, 1])
        row = V.row_image(runs[0], 255)
        self.assertGreater(row.shape[1], row.shape[0], "拼成横的一行")

    def test_columns_join_and_read_right_to_left(self) -> None:
        # 同一列被检测成上下两截（句末的“！”单独一个框）：接成一列
        self.assertEqual(V.join_columns([(100, 10, 150, 160), (115, 150, 132, 195)]), [(100, 10, 150, 195)])
        # 一个气泡里两列：从右往左；离得远的另一个气泡单独成段
        right, left, far = (150, 10, 200, 170), (95, 12, 148, 250), (400, 300, 450, 420)
        self.assertEqual(V.group_columns([left, far, right]), [[far], [right, left]])


if __name__ == "__main__":
    unittest.main()
