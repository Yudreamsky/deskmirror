"""滚动识别的离线单元测试（合成画面）。"""
from __future__ import annotations

import unittest

import cv2
import numpy as np

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror import pixels


def text_page(h: int, w: int, seed: int, line_h: int = 22) -> np.ndarray:
    """画一张有很多行“文字”的长页面（灰度）。"""
    rng = np.random.default_rng(seed)
    img = np.full((h, w), 255, np.uint8)
    words = ["lorem", "ipsum", "dolor", "sit", "amet", "scroll", "canvas", "mirror", "text", "block", "anchor"]
    y = 16
    while y < h - 4:
        if rng.random() < 0.15:
            y += line_h  # 段落间空行
            continue
        s = " ".join(rng.choice(words, size=int(rng.integers(3, 9))))
        cv2.putText(img, s, (int(rng.integers(6, 30)), y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1, cv2.LINE_AA)
        y += line_h
    return img


class DetectShiftTest(unittest.TestCase):
    def setUp(self) -> None:
        self.page = text_page(4000, 700, 1)
        self.side = text_page(4000, 300, 2)

    def screen(self, scroll_main: int, scroll_side: int) -> np.ndarray:
        """1200x1100 的“窗口”：顶部固定标题 80 像素，左侧滚动正文 700 宽，右侧独立滚动侧栏 300 宽。"""
        scr = np.full((1100, 1200), 240, np.uint8)
        scr[0:80, :] = 200
        cv2.putText(scr, "FIXED HEADER Title Navigation Home About", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2)
        scr[80:1100, 0:700] = self.page[scroll_main:scroll_main + 1020, :]
        scr[80:1100, 700:704] = 120  # 分隔线
        scr[80:1100, 704:1004] = self.side[scroll_side:scroll_side + 1020, :]
        return scr

    def test_main_scroll_only(self) -> None:
        prev = self.screen(300, 500)
        for s in (3, 37, 120, 400, -55):
            cur = self.screen(300 + s, 500)
            res = pixels.detect_shift(prev, cur, (0, 0, 1200, 1100))
            self.assertIsNotNone(res, s)
            self.assertEqual(res.axis, "v")
            self.assertEqual(res.shift, -s)  # 内容上移 s 像素
            l, t, r, b = res.viewport
            self.assertGreaterEqual(t, 80, "不能把固定标题当成滚动区域")
            self.assertLessEqual(r, 704, "不能把右侧独立区域算进来")
            self.assertLess(l, 60)

    def test_side_scroll_only(self) -> None:
        prev = self.screen(300, 500)
        cur = self.screen(300, 560)
        res = pixels.detect_shift(prev, cur, (0, 0, 1200, 1100))
        self.assertIsNotNone(res)
        self.assertEqual(res.shift, -60)
        l, t, r, b = res.viewport
        self.assertGreaterEqual(l, 700)
        self.assertGreaterEqual(t, 80)

    def test_no_shift_on_content_change(self) -> None:
        prev = self.screen(300, 500)
        cur = prev.copy()
        cur[300:700, 0:700] = text_page(400, 700, 99)
        self.assertIsNone(pixels.detect_shift(prev, cur, (0, 0, 1200, 1100)))

    def test_horizontal(self) -> None:
        wide = np.hstack([text_page(900, 500, 5 + k) for k in range(6)])
        prev = wide[:, 400:1600].copy()
        cur = wide[:, 470:1670].copy()
        res = pixels.detect_shift(prev, cur, (0, 0, 1200, 900), axis="h")
        self.assertIsNotNone(res)
        self.assertEqual(res.shift, -70)

    def test_static_rows(self) -> None:
        prev = self.screen(300, 500)
        cur = self.screen(300 + 40, 500)
        # 整个窗口当成“已知画布”，这次平移只发生在正文：标题行原地不动且有内容
        st, mv = pixels.static_rows(prev, cur, (0, 0, 1200, 1100), (0, 80, 700, 1100), -40)
        self.assertGreater(st, 5)

    def video_screen(self, scroll: int, frame: int, side: bool = True) -> np.ndarray:
        """仿视频网站观看页：顶部固定栏 56 像素；主栏顶部是一直在播放的视频，下面是文字；右侧推荐栏。
        整页一起滚动，视频每帧画面都不同。"""
        rng = np.random.default_rng(1000 + frame)
        doc = np.full((4000, 1440), 249, np.uint8)
        doc[:, 24:724] = self.page[:, :700]
        doc[0:80, 24:1030] = 249
        noise = cv2.resize(rng.integers(0, 255, (9, 16), dtype=np.uint8), (1006, 566), interpolation=cv2.INTER_CUBIC)
        doc[80:646, 24:1030] = noise
        if side:
            doc[:, 1060:1360] = self.side[:, :300]
        scr = np.full((1300, 1440), 255, np.uint8)
        scr[56:] = doc[scroll:scroll + 1244]
        cv2.putText(scr, "VideoTube  Search  Sign in", (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2)
        return scr

    def test_scroll_with_playing_video(self) -> None:
        # 视频在播放时滚动：整页（视频所在的主栏 + 推荐栏）都要认成同一次滚动，不能只认出推荐栏
        for start, s in ((0, 40), (0, 120), (200, 60), (300, 200)):
            res = pixels.detect_shift(self.video_screen(start, 0), self.video_screen(start + s, 1), (0, 56, 1440, 1300))
            self.assertIsNotNone(res, (start, s))
            self.assertEqual(res.shift, -s)
            l, t, r, b = res.viewport
            self.assertLess(l, 60, (start, s, res.viewport))
            self.assertGreater(r, 1300, (start, s, res.viewport))
        # 没有推荐栏、视频占了大半屏：主栏的文字照样认出滚动
        res = pixels.detect_shift(self.video_screen(0, 0, False), self.video_screen(60, 1, False), (0, 56, 1440, 1300))
        self.assertIsNotNone(res)
        self.assertEqual(res.shift, -60)

    def test_page_switch_with_video(self) -> None:
        # 换页（视频照样在播）：不能当成滚动
        prev = self.video_screen(0, 0)
        cur = prev.copy()
        cur[56:] = text_page(1244, 1440, 77)
        self.assertIsNone(pixels.detect_shift(prev, cur, (0, 56, 1440, 1300)))

    def test_busy_background(self) -> None:
        line = np.full((30, 400), 250, np.uint8)
        cv2.putText(line, "Plain text on a white page", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 20, 1, cv2.LINE_AA)
        self.assertFalse(pixels.busy_background(line, 20, 250))
        rng = np.random.default_rng(3)
        video = cv2.resize(rng.integers(0, 255, (3, 20), dtype=np.uint8), (400, 30), interpolation=cv2.INTER_CUBIC)
        cv2.putText(video, "Subtitle over a video", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2, cv2.LINE_AA)
        self.assertTrue(pixels.busy_background(video, 255, 120))

    def test_verify_patch_caret_and_digit(self) -> None:
        img = np.full((200, 400), 255, np.uint8)
        cv2.putText(img, "Verify this line 12345", (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 1, cv2.LINE_AA)
        box = (0, 24, 300, 48)
        ref = img[24:48, 0:300].copy()
        cur = img.copy()
        ok, dx, dy = pixels.verify_patch(ref, cur, box)
        self.assertTrue(ok)
        caret = cur.copy()
        caret[26:46, 250:252] = 0  # 闪烁的光标
        self.assertTrue(pixels.verify_patch(ref, caret, box)[0])
        changed = cur.copy()
        cv2.rectangle(changed, (60, 28), (70, 42), 0, -1)  # 改了一个字
        self.assertFalse(pixels.verify_patch(ref, changed, box)[0])
        shifted = np.full_like(cur, 255)
        shifted[1:, 2:] = cur[:-1, :-2]
        ok, dx, dy = pixels.verify_patch(ref, shifted, box)
        self.assertTrue(ok)
        self.assertEqual((dx, dy), (2, 1))


class SameGlyphsTest(unittest.TestCase):
    """鼠标经过时的核对：字的形状还在就算同一段字，不管颜色、深浅；笔画缺了不算。"""

    def setUp(self) -> None:
        self.img = np.full((200, 400), 255, np.uint8)
        cv2.putText(self.img, "Open the project folder", (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 1, cv2.LINE_AA)
        cv2.putText(self.img, "Close all other windows", (8, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 1, cv2.LINE_AA)
        self.box = (4, 24, 300, 48)
        self.ref = self.img[24:48, 4:300].copy()

    def looks(self, change) -> np.ndarray:
        cur = self.img.copy()
        l, t, r, b = self.box
        change(cur[t:b, l:r])
        return cur

    def test_hover_looks_still_match(self) -> None:
        def tint(p):
            p[p > 128] = 160                       # 底色变暗（差 95 级）

        def invert(p):
            p[:] = 255 - p                         # 深浅反过来：菜单项高亮成深底浅字

        def underline(p):
            p[19, :] = 0                           # 出了下划线

        for name, change in (("tint", tint), ("invert", invert), ("underline", underline)):
            cur = self.looks(change)
            self.assertFalse(pixels.verify_patch(self.ref, cur, self.box)[0], name)   # 平常的核对对不上
            self.assertTrue(pixels.same_glyphs(self.ref, cur, self.box, 8), name)
        shifted = np.full_like(self.img, 255)
        shifted[1:, 2:] = self.looks(invert)[:-1, :-2]
        self.assertTrue(pixels.same_glyphs(self.ref, shifted, self.box, 8), "差一两个像素也行")

    def test_covered_or_changed_text_does_not_match(self) -> None:
        def popup(p):
            p[:, 120:] = 240                       # 弹出的菜单盖住了后半段

        def other(p):
            p[:] = self.img[104:128, 4:300]        # 换了一行字

        def gone(p):
            p[:] = 255                             # 字没了

        def digit(p):
            cv2.rectangle(p, (60, 4), (70, 18), 255, -1)    # 擦掉了一个字

        for name, change in (("popup", popup), ("other", other), ("gone", gone), ("digit", digit)):
            self.assertFalse(pixels.same_glyphs(self.ref, self.looks(change), self.box, 8), name)
        self.assertFalse(pixels.same_glyphs(np.full_like(self.ref, 255), self.img, self.box, 8), "参考图里没有字")


if __name__ == "__main__":
    unittest.main()
