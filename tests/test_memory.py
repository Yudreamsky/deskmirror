"""译文记忆：数字模板、本地记忆的存取（DPAPI 加密）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror import memory
from deskmirror.textutil import cache_key


class TemplateTest(unittest.TestCase):
    def test_counter_reuses_translation(self) -> None:
        tc = memory.TemplateCache()
        tc.learn(cache_key, "Gold: 120 coins", "金币：120 枚")
        self.assertEqual(tc.lookup(cache_key, "Gold: 150 coins"), "金币：150 枚")
        tc.learn(cache_key, "Running for 12m 3s", "已运行 12 分 3 秒")
        self.assertEqual(tc.lookup(cache_key, "Running for 12m 4s"), None, "12m 这种和字母连在一起的不算独立数字")
        tc.learn(cache_key, "Page 3 of 10", "第 3 页，共 10 页")
        self.assertEqual(tc.lookup(cache_key, "Page 4 of 12"), "第 4 页，共 12 页")
        tc.learn(cache_key, "Downloaded 45%", "已下载 45%")
        self.assertEqual(tc.lookup(cache_key, "Downloaded 46%"), "已下载 46%")

    def test_plural_and_rewritten_numbers_are_not_mixed(self) -> None:
        tc = memory.TemplateCache()
        tc.learn(cache_key, "1 day ago", "1天前")
        self.assertIsNone(tc.lookup(cache_key, "2 days ago"), "单复数不同，模板不同")
        tc.learn(cache_key, "3 items left", "还剩三件")       # 译文没有原样保留数字：不学
        self.assertIsNone(tc.lookup(cache_key, "5 items left"))
        tc.learn(cache_key, "Level 7", "等级 7")
        self.assertIsNone(tc.lookup(cache_key, "Level 7 boss"), "文字部分不同")

    def test_numbers_only_text_has_no_template(self) -> None:
        self.assertIsNone(memory.number_template("12:30"))
        self.assertIsNone(memory.number_template("120/150"))
        self.assertIsNotNone(memory.number_template("HP 120/150"))


class MemoryFileTest(unittest.TestCase):
    def test_save_and_load_encrypted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "deskmirror_memory.bin"
            mem = memory.Memory(p)
            mem.put("zh-Hans", cache_key("Hello world"), "你好，世界")
            mem.save()
            raw = p.read_bytes()
            self.assertNotIn("你好".encode("utf-8"), raw, "存盘内容必须加密")
            mem2 = memory.Memory(p)
            self.assertEqual(mem2.load(), 1)
            self.assertEqual(mem2.get("zh-Hans", cache_key("Hello world")), "你好，世界")
            self.assertIsNone(mem2.get("ja", cache_key("Hello world")))
            mem2.clear()
            self.assertFalse(p.exists())


class TermMatchTest(unittest.TestCase):
    def test_whole_words(self) -> None:
        from deskmirror.engine import _term_in
        self.assertTrue(_term_in("art", "modern art museum"))
        self.assertTrue(_term_in("art", "art."))
        self.assertFalse(_term_in("art", "start the game"))
        self.assertFalse(_term_in("art", "artist"))
        self.assertTrue(_term_in("art", "start art"))          # 第一次出现不算，后面那个算
        self.assertTrue(_term_in("hp potion", "buy hp potion x3"))
        self.assertTrue(_term_in("勇者", "伝説の勇者です"))        # 没有词边界的文字直接找
        self.assertTrue(_term_in("c++", "learn c++ today"))


if __name__ == "__main__":
    unittest.main()
