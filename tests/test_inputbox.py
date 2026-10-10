"""输入框翻译的规则（inputbox.py）：什么时候算连按三次空格、框里的字怎么分段、记着的原文和译文怎么来回换。
各条照浏览器版的 tests/field.mjs。"""
from __future__ import annotations

import unittest

from deskmirror import inputbox as ib

IDEO = chr(0x3000)      # 全角空格
NBSP = chr(0xA0)


class TapsTest(unittest.TestCase):
    def tap(self, taps: ib.Taps, t: float, window: int = 1, mods: bool = False) -> bool:
        hit = taps.space(t, window, mods)
        taps.space_up()
        return hit

    def test_three_quick_spaces(self) -> None:
        t = ib.Taps()
        self.assertEqual([self.tap(t, x) for x in (0.0, 0.45, 0.9)], [False, False, True], "每下隔 0.45 秒也算")
        self.assertTrue(self.tap(t, 1.0), "第四下也算：输入法拿第一下空格选字时，用户会多按一下")
        self.assertFalse(self.tap(t, 1.8), "隔太久：重新数")

    def test_too_slow(self) -> None:
        t = ib.Taps()
        self.assertEqual([self.tap(t, x) for x in (0.0, 0.7, 1.4)], [False, False, False], "每下隔 0.7 秒不算连按")
        self.assertTrue(self.tap(t, 1.8) is False and self.tap(t, 2.1), "慢的后面接着快的：从最近一下数起")

    def test_auto_repeat_does_not_count(self) -> None:
        t = ib.Taps()
        self.assertFalse(t.space(0.0, 1, False))
        self.assertFalse(t.space(0.03, 1, False), "按住不放的连发")
        self.assertFalse(t.space(0.06, 1, False))
        t.space_up()
        self.assertFalse(self.tap(t, 0.2))
        self.assertTrue(self.tap(t, 0.4), "连发不算数，也不打断")

    def test_modifiers_other_keys_and_windows_reset(self) -> None:
        t = ib.Taps()
        self.tap(t, 0.0)
        self.tap(t, 0.1, mods=True)
        self.assertFalse(self.tap(t, 0.2), "带修饰键的空格（比如 Shift+空格切全角）：重新数")
        t = ib.Taps()
        self.tap(t, 0.0)
        self.tap(t, 0.1)
        t.other()
        self.assertFalse(self.tap(t, 0.2), "中间打了别的键")
        t = ib.Taps()
        self.tap(t, 0.0, window=1)
        self.tap(t, 0.1, window=1)
        self.assertFalse(self.tap(t, 0.2, window=2), "换了窗口")


class TextTest(unittest.TestCase):
    def test_body(self) -> None:
        self.assertEqual(ib.body_of("你好，世界   "), "你好，世界")
        self.assertEqual(ib.body_of("你好" + IDEO * 3), "你好", "输入法打出的全角空格也算")
        self.assertEqual(ib.body_of("你好 " + NBSP + " "), "你好")
        self.assertIsNone(ib.body_of("你好  "), "只有两个空格")
        self.assertIsNone(ib.body_of("   "), "空的")
        self.assertIsNone(ib.body_of("def f():\n   "), "行首连按空格（缩进）不算")
        self.assertEqual(ib.body_of("第一行\n第二行   "), "第一行\n第二行")
        self.assertEqual(ib.strip_tail("你好" + IDEO * 3 + "\n"), "你好")

    def test_norm(self) -> None:
        self.assertEqual(ib.norm(" a" + chr(0x200B) + "  b\n\nc" + chr(0xFEFF) + " "), "a b c", "去掉零宽字符，空白并成一个")

    def test_lines_round_trip(self) -> None:
        body = "你好\n\n  缩进的一行\n再见"
        lines, at, segs = ib.split_lines(body)
        self.assertEqual(at, [0, 2, 3])
        self.assertEqual(segs, ["你好", "缩进的一行", "再见"])
        out, full = ib.join_lines(lines, at, ["Hello", "An indented line", "Bye"])
        self.assertEqual(out, "Hello\n\n  An indented line\nBye", "空行、缩进照旧")
        self.assertTrue(full)
        out, full = ib.join_lines(lines, at, ["Hello", None, "Bye"])
        self.assertEqual(out, "Hello\n\n  缩进的一行\nBye", "没译出来的段留原文")
        self.assertFalse(full)

    def test_languages(self) -> None:
        self.assertEqual(ib.default_target("zh-Hans"), "en")
        self.assertEqual(ib.default_target("ja"), "en")
        self.assertEqual(ib.default_target("en"), "zh-Hans", "母语是英文：译成简体中文")
        self.assertEqual([ib.source_of(x) for x in ("zh-Hans", "zh-Hant", "ja", "en")], ["zh", "zh", "ja", "en"])


class MemoTest(unittest.TestCase):
    def test_back_and_forth_without_requests(self) -> None:
        m = ib.Memo()
        self.assertIsNone(m.find("你好，世界", "zh>en"), "新写的：要翻译")
        p = m.add("你好，世界", "Hello, world", "zh>en", True)
        m.seen(p, False, "Hello, world\n")                     # 编辑器读回来多了个换行
        pair, back = m.find("Hello,   world", "zh>en")
        self.assertTrue(back, "框里是译文：换回原文")
        self.assertEqual(pair.orig, "你好，世界")
        pair, back = m.find("你好，世界", "zh>en")
        self.assertFalse(back, "框里是原文：直接换成译文，不请求")
        self.assertIsNone(m.find("你好，世界！", "zh>en"), "换回原文后改了字：重新翻译")

    def test_target_change_and_partial(self) -> None:
        m = ib.Memo()
        m.add("我爱你", "I love you", "zh>en", True)
        self.assertIsNone(m.find("我爱你", "zh>ja"), "换了译成的语言：重新翻译")
        self.assertTrue(m.find("I love you", "zh>ja")[1], "框里是旧译文：照样能换回原文")
        m.add("你好\n再见", "Hello\n再见", "zh>en", False)
        self.assertIsNone(m.find("你好\n再见", "zh>en"), "上次有段没译出来：重新翻译")

    def test_keeps_the_last_twenty(self) -> None:
        m = ib.Memo()
        for i in range(25):
            m.add(f"原文{i}", f"text {i}", "zh>en", True)
        self.assertEqual(len(m.pairs), ib.MEMO_SIZE)
        self.assertIsNone(m.find("原文0", "zh>en"))
        self.assertIsNotNone(m.find("原文24", "zh>en"))


if __name__ == "__main__":
    unittest.main()
