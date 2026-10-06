"""分段规则的单元测试（行框数据取自真实维基百科页面的检测结果）。"""
from __future__ import annotations

import unittest

import deskmirror  # noqa: F401
from deskmirror.layout import Line, candidate_paragraphs, join_lines, split_by_text
from deskmirror.textutil import looks_untranslated, needs_translation


def blocks(rects_texts):
    rects = [r for r, _ in rects_texts]
    out = []
    for idx in candidate_paragraphs(rects):
        lines = [Line(rects_texts[i][0], rects_texts[i][1]) for i in idx]
        out.extend([[ln.text for ln in d.lines] for d in split_by_text(lines)])
    texts = [txt for _, txt in rects_texts]
    return sorted(out, key=lambda b: texts.index(b[0]))


class LayoutTest(unittest.TestCase):
    def test_paragraph_with_superscript_last_line(self) -> None:
        data = [((509, 493, 1199, 512), "Alexander Mitchell designed the first screw-pile lighthouse – his lighthouse was "
                                        "built on piles that"),
                ((508, 519, 1189, 538), "were screwed into the sandy or muddy seabed. Construction of his design began in "
                                        "1838 at the"),
                ((507, 540, 1165, 567), "mouth of the Thames and was known as the Maplin Sands lighthouse, and first lit in "
                                        "1841.[9]"),
                ((508, 569, 1219, 592), "Although its construction began later, the Wyre Light in Fleetwood, Lancashire, was "
                                        "the first to be lit"),
                ((506, 590, 599, 619), "(in 1840).[9]"),
                ((508, 648, 776, 673), "Lighting improvements [edit]"),
                ((509, 686, 1196, 706), "Until 1782 the source of illumination had generally been wood pyres or burning "
                                        "coal. The Argand"),
                ((509, 713, 1225, 732), "lamp, invented in 1782 by the Swiss scientist Aimé Argand revolutionized lighthouse "
                                        "illumination with"),
                ((508, 860, 667, 895), "for over a century.[12]")]
        b = blocks(data)
        self.assertEqual(len(b[0]), 5, b)               # 带 [9] 的段尾行并回本段
        self.assertEqual(b[1], ["Lighting improvements [edit]"])  # 标题单独
        self.assertEqual(len(b[2]), 2)

    def test_stacked_labels_and_lists(self) -> None:
        data = [((10, 10, 80, 30), "Small"), ((10, 36, 110, 56), "Standard"), ((10, 62, 80, 82), "Large"),
                ((10, 120, 400, 140), "• Guided tour of the north tower, week 1."),
                ((10, 148, 420, 168), "• Lecture on navigation history, week 2.")]
        b = blocks(data)
        self.assertEqual(len(b), 5, b)

    def test_join_lines(self) -> None:
        # 行尾连字符断开的单词接回去；中日文字行间不加空格
        self.assertEqual(join_lines([Line((0, 0, 1, 1), "source of illumi-"), Line((0, 0, 1, 1), "nation was")]),
                         "source of illumination was")
        self.assertEqual(join_lines([Line((0, 0, 1, 1), "日本語の"), Line((0, 0, 1, 1), "テキスト")]), "日本語のテキスト")

    def test_text_filters(self) -> None:
        self.assertFalse(needs_translation("设置", "zh-Hans"))
        self.assertTrue(needs_translation("Settings", "zh-Hans"))
        self.assertTrue(needs_translation("設定を開く", "zh-Hans"))
        self.assertFalse(needs_translation("12:30", "zh-Hans"))
        src = ("Record 13: The archive keeps letters, drawings and photographs related to this subject. "
               "Researchers may request copies, and most items can be viewed in the reading room on weekday afternoons.")
        self.assertTrue(looks_untranslated(src, "档案馆保存……研究人员可以申请副本， most items can be viewed in the "
                                                "reading room on weekday afternoons.", "zh-Hans"))
        self.assertFalse(looks_untranslated(src, "记录13：档案馆保存与此主题相关的信件、图纸和照片。", "zh-Hans"))


if __name__ == "__main__":
    unittest.main()
