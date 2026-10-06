"""术语前后一致：关键词提取和参考译文的挑选。"""
from __future__ import annotations

import unittest

import deskmirror  # noqa: F401  预加载 DLL
from deskmirror.consistency import RefHistory, key_terms
from deskmirror.textutil import cache_key


class KeyTermsTest(unittest.TestCase):
    def test_terms(self) -> None:
        t = key_terms("The Employer shall return the Performance Security under the EPC Contract within 28 days.")
        for w in ("employer", "!employer", "performance security", "security", "EPC", "contract"):
            self.assertIn(w, t)
        for w in ("the", "shall", "within", "28", "under"):
            self.assertNotIn(w, t)
        self.assertIn("檩条", key_terms("屋面檩条的间距"))
        self.assertTrue({"リー", "ール", "交換"} <= key_terms("リールを交換してください"))   # 汉字、片假名按相邻两字
        self.assertIn("purlin", key_terms("Purlins and ground screws"))      # 复数还原
        self.assertNotIn("!purlin", key_terms("Purlins and ground screws"))  # 句首大写不算定义词


def _add(h: RefHistory, src: str, tr: str, hwnd: int = 1, app: str = "msedge.exe") -> None:
    h.add(cache_key(src), src, tr, hwnd, app)


class SelectTest(unittest.TestCase):
    def setUp(self) -> None:
        h = self.h = RefHistory()
        _add(h, "The tender shall be submitted before the deadline.", "投标文件应在截止日期前提交。")
        _add(h, "The Engineer shall issue the Taking-Over Certificate.", "监理工程师应签发接收证书。")
        _add(h, "Payment terms are described in Section 4.", "付款条件见第 4 节。")
        _add(h, "Purlins are fixed to the rafters with clamps.", "檩条用夹具固定在斜梁上。", hwnd=2)
        _add(h, "The Engineer class gains a new skill.", "工程师职业获得新技能。", hwnd=9, app="game.exe")

    def test_picks_paragraph_with_same_rare_term(self) -> None:
        refs = self.h.select(["The Engineer may reject defective Works."], [], 1, "msedge.exe")
        self.assertEqual(refs[0], ("The Engineer shall issue the Taking-Over Certificate.", "监理工程师应签发接收证书。"))
        self.assertNotIn(("The Engineer class gains a new skill.", "工程师职业获得新技能。"), refs, "别的程序不参考")

    def test_same_app_other_window_and_limits(self) -> None:
        refs = self.h.select(["Check the purlins and clamps."], [], 1, "msedge.exe")
        self.assertEqual(refs, [("Purlins are fixed to the rafters with clamps.", "檩条用夹具固定在斜梁上。")])
        self.assertEqual(self.h.select(["Check the purlins."], [], 3, "notepad.exe"), [], "别的窗口、别的程序都不参考")
        self.assertEqual(self.h.select(["Nothing in common here."], [], 1, "msedge.exe"), [])
        same = "The Engineer shall issue the Taking-Over Certificate."
        self.assertEqual(self.h.select([same], [cache_key(same)], 1, "msedge.exe"), [], "同一段不拿自己当参考")
        many = RefHistory()
        for i in range(30):
            _add(many, f"Clause {i}: the Performance Security covers item {i} of the works.", f"第 {i} 条：履约担保覆盖第 {i} 项。")
        refs = many.select(["Return the Performance Security."], [], 1, "msedge.exe")
        self.assertTrue(1 <= len(refs) <= 3)
        self.assertLessEqual(sum(len(s) + len(d) for s, d in refs), 600)

    def test_update_and_drop(self) -> None:
        key = cache_key("Purlins are fixed to the rafters with clamps.")
        self.h.update(key, "檩条用压块固定在椽上。")
        self.assertEqual(self.h.select(["purlins"], [], 2, "msedge.exe")[0][1], "檩条用压块固定在椽上。")
        self.h.drop(lambda src: "purlin" in src.lower())
        self.assertEqual(self.h.select(["purlins"], [], 2, "msedge.exe"), [])


if __name__ == "__main__":
    unittest.main()
