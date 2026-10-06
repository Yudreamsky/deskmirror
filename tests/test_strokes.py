"""动态背景上的文字核对（笔画核对）的单元测试。"""
from __future__ import annotations

import unittest

import cv2
import numpy as np

import deskmirror  # noqa: F401
from deskmirror import pixels


def scene(seed: int, text: str | None, bright_bg: bool = False) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = 200 if bright_bg else 40
    img = np.clip(rng.normal(base, 25, (80, 520)), 0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 3)          # 像视频画面一样的连续背景
    if text:
        # 白字黑边：常见的字幕样式
        cv2.putText(img, text, (14, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 7, cv2.LINE_AA)
        cv2.putText(img, text, (14, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 255, 2, cv2.LINE_AA)
    return img


class StrokeTest(unittest.TestCase):
    rect = (6, 20, 506, 64)

    def ref(self, text="Hold the line, captain 123"):
        l, t, r, b = self.rect
        return scene(1, text)[t:b, l:r].copy()

    def check(self, cur) -> bool:
        return pixels.verify_strokes(self.ref(), cur, self.rect, fg_lum=255, bg_lum=40, cell=26)

    def test_same_text_new_background(self) -> None:
        self.assertTrue(self.check(scene(7, "Hold the line, captain 123")))

    def test_digit_changed(self) -> None:
        self.assertFalse(self.check(scene(7, "Hold the line, captain 128")))

    def test_text_gone_bright_background(self) -> None:
        self.assertFalse(self.check(scene(7, None, bright_bg=True)))

    def test_text_gone_dark_background(self) -> None:
        self.assertFalse(self.check(scene(7, None)))

    def test_other_sentence(self) -> None:
        self.assertFalse(self.check(scene(7, "Fall back to the river now")))


if __name__ == "__main__":
    unittest.main()
