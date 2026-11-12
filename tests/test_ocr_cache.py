"""识别进程里“认过的行不认第二遍”的单元测试（不加载识别模型：认字那一步换成假的，只数它被叫了几次）。"""
from __future__ import annotations

import unittest

import cv2
import numpy as np

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror import ocr_worker as O


def draw(lines: list[tuple[str, int, int]], w: int = 900, h: int = 300, bg: int = 250) -> np.ndarray:
    img = np.full((h, w, 3), bg, np.uint8)
    for text, x, y in lines:
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 1, cv2.LINE_AA)
    return img


def box(text: str, x: int, y: int, pad: int = 4) -> tuple[int, int, int, int]:
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 1)
    return x - pad, y - th - pad, x + tw + pad, y + base + pad


class LineCacheTest(unittest.TestCase):
    LINES = [("Open the harbour gate", 30, 60), ("Tickets are sold at the pier", 30, 130), ("Rent a bicycle", 30, 200)]

    def setUp(self) -> None:
        self.seen: list[int] = []                 # 每次真去“认字”时认了几行
        self.score = 0.97
        self._real = O._recognize_images
        self._on, self._max = O._line_cache_on, O.LINE_CACHE_MAX
        O._line_cache.clear()
        O._line_cache_on = True

        def fake(_engine, crops):
            self.seen.append(len(crops))
            # 假的识别结果：由这一小块图的内容决定（同样的像素 → 同样的“字”）
            return [("t%d" % (int(c.astype(np.int64).sum()) % 100000), self.score) for c in crops]

        O._recognize_images = fake

    def tearDown(self) -> None:
        O._recognize_images = self._real
        O._line_cache_on, O.LINE_CACHE_MAX = self._on, self._max
        O._line_cache.clear()

    def read(self, img: np.ndarray, rects) -> list[tuple[str, float]]:
        return O._recognize(None, img, list(rects), cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))

    def test_same_lines_are_read_once(self) -> None:
        img = draw(self.LINES)
        rects = [box(*ln) for ln in self.LINES]
        first = self.read(img, rects)
        self.assertEqual(self.seen, [3])
        # 再读一遍：检测框每次会差一两个像素，字还是那些字
        moved = [(r[0] - 2, r[1] + 1, r[2] + 1, r[3] - 1) for r in rects]
        again = self.read(img, moved)
        self.assertEqual(self.seen, [3], "认过的行不该再认")
        # 假的识别结果跟着整块图走（框一变就变）；从记下的结果里拿，才会和第一次一样
        self.assertEqual(again, first)
        # 画面滚了 37 像素：同样的字出现在别的位置
        scrolled = draw([(t, x, y + 37) for t, x, y in self.LINES])
        self.assertEqual(self.read(scrolled, [box(t, x, y + 37) for t, x, y in self.LINES]), first)
        self.assertEqual(self.seen, [3])

    def test_changed_line_is_read_again(self) -> None:
        img = draw(self.LINES)
        rects = [box(*ln) for ln in self.LINES]
        first = self.read(img, rects)
        lines = list(self.LINES)
        lines[1] = ("Tickets are sold at the port", 30, 130)
        img2 = draw(lines)
        second = self.read(img2, [box(*ln) for ln in lines])
        self.assertEqual(self.seen, [3, 1], "只有变了的那一行重新认")
        self.assertEqual((second[0], second[2]), (first[0], first[2]))
        self.assertNotEqual(second[1], first[1])

    def test_pale_text_beside_dark_text_counts(self) -> None:
        # 深色的字后面跟着很浅的字（“回复 · 3 分钟前”那种）：只有浅色那半截变了，也得重新认
        def page(tail: str) -> np.ndarray:
            img = draw([("Reply", 30, 60)])
            cv2.putText(img, tail, (120, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (228, 228, 228), 1, cv2.LINE_AA)
            return img
        rect = (26, 36, 330, 70)
        a = self.read(page("3 min ago"), [rect])
        b = self.read(page("5 min ago"), [rect])
        self.assertEqual(self.seen, [1, 1])
        self.assertNotEqual(a, b)

    def test_unsure_results_are_not_kept(self) -> None:
        img = draw(self.LINES)
        rects = [box(*ln) for ln in self.LINES]
        self.score = 0.7                           # 把握不大：下次照旧重认（多读几次，结果才稳）
        self.read(img, rects)
        self.read(img, rects)
        self.assertEqual(self.seen, [3, 3])
        self.score = 0.97
        self.read(img, rects)
        self.read(img, rects)
        self.assertEqual(self.seen, [3, 3, 3])

    def test_identical_lines_in_one_read_are_read_once(self) -> None:
        lines = [("Reply", 30, 60), ("Reply", 30, 130), ("Reply", 400, 130), ("Forward", 30, 200)]
        img = draw(lines)
        out = self.read(img, [box(*ln) for ln in lines])
        self.assertEqual(self.seen, [2], "三个一样的按钮名只认一个")
        self.assertEqual(out[0], out[1])
        self.assertEqual(out[1], out[2])
        self.assertNotEqual(out[0], out[3])

    def test_blank_boxes_and_switch(self) -> None:
        img = draw(self.LINES)
        rects = [box(*ln) for ln in self.LINES]
        blank = (500, 220, 700, 260)               # 框里什么都没有：照样交给识别（结果是空的），不记
        self.read(img, rects + [blank])
        self.read(img, rects + [blank])
        self.assertEqual(self.seen, [4, 1])
        # 不给灰度图、或者关掉（DESKMIRROR_OCR_CACHE=0）：每次都认
        O._recognize(None, img, rects)
        self.assertEqual(self.seen[-1], 3)
        O._line_cache_on = False
        self.read(img, rects)
        self.assertEqual(self.seen[-1], 3)

    def test_memory_is_bounded(self) -> None:
        O.LINE_CACHE_MAX = 2
        img = draw(self.LINES)
        rects = [box(*ln) for ln in self.LINES]
        self.read(img, rects)
        self.assertEqual(len(O._line_cache), 2)
        self.read(img, rects[1:])                  # 后两行还记着
        self.assertEqual(self.seen, [3])
        self.read(img, rects[:1])                  # 最早的那行已经挤掉了
        self.assertEqual(self.seen, [3, 1])


if __name__ == "__main__":
    unittest.main()
