"""把检测到的文字行分组成文字块（段落），识别、翻译、排版都以文字块为单位。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .geom import Rect, union
from .textutil import em_height

_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_LIST_MARK = re.compile(r"^\s*(?:[•·●◦▪■□►▶‣\-–—*]|\(?\d{1,3}[.)、]|\(?[a-zA-Z][.)]\s|[一二三四五六七八九十]+[、.])")


@dataclass
class Line:
    rect: Rect
    text: str = ""
    score: float = 0.0


@dataclass
class BlockDraft:
    lines: list[Line] = field(default_factory=list)

    @property
    def rect(self) -> Rect:
        r = self.lines[0].rect
        for ln in self.lines[1:]:
            r = union(r, ln.rect)
        return r


def _h(r: Rect) -> int:
    return r[3] - r[1]


def candidate_paragraphs(rects: list[Rect]) -> list[list[int]]:
    """几何上可能属于同一段的行（宽松分组）；识别后再按文字线索细分。

    行尾的上标引用（维基百科的 [12]）、带下划线的链接会把检测框往上撑高，但行底仍按行距对齐。
    所以按“行间空隙”和“行底到行底的行距”判断，不直接比框高：段内自动换行的空隙小、行距规整；
    段落之间、列表项之间、标题与正文之间的空隙明显更大。
    """
    n = len(rects)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(n), key=lambda i: (rects[i][1], rects[i][0]))
    for pos, i in enumerate(order):
        a = rects[i]
        ha = _h(a)
        best, best_gap = -1, None
        for j in order[pos + 1:]:
            b = rects[j]
            if b[1] > a[3] + ha:
                break
            hb = _h(b)
            href = min(ha, hb)            # 矮的那个更接近正文字高（高的可能带上标）
            if max(ha, hb) > 2.0 * href:
                continue
            gap = b[1] - a[3]
            pitch = b[3] - a[3]
            if gap < -0.6 * href or gap > 0.5 * href:
                continue
            if not (0.9 * href <= pitch <= 1.9 * href):
                continue
            ov = min(a[2], b[2]) - max(a[0], b[0])
            narrow = min(a[2] - a[0], b[2] - b[0])
            aligned = abs(a[0] - b[0]) <= 1.2 * href
            if ov < 0.5 * narrow and not (aligned and ov > 0):
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap = j, gap
        if best >= 0:
            parent[find(best)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in order:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


_SUPERSCRIPT = re.compile(r"\[\s*\d{1,3}\s*\]|\[[a-z]\]|[¹²³⁰-₟®™†‡*]")


def body_height(ln: Line) -> float:
    """行的“正文字高”：带上标引用的行框被撑高约三成，按比例扣掉。"""
    h = em_height(_h(ln.rect), ln.text)
    return h * 0.75 if _SUPERSCRIPT.search(ln.text) else h


def char_width(ln: Line) -> float | None:
    """西文行的平均字符宽度（像素/字）：同一段里非常稳定，不受上标、下划线、行框高度波动影响。"""
    t = ln.text.strip()
    if len(t) < 10 or _CJK.search(t):
        return None
    return (ln.rect[2] - ln.rect[0]) / len(t)


# 常见西文无衬线字体平均字宽约 0.5 个字号，检测框高约 1.35 个字号：换算回“框高”口径，和 em_height 一致
_CW_TO_EM = 2.6


def font_em(ln: Line) -> float:
    """估计原文字号（检测框高度口径）：字数够的西文行按字宽，否则按校正后的框高。"""
    cw = char_width(ln)
    return _CW_TO_EM * cw if cw is not None else body_height(ln)


def split_by_text(lines: list[Line]) -> list[BlockDraft]:
    """按文字线索细分一个候选段落：只有上一行写满（发生了自动换行）才把下一行接进来。"""
    lines = sorted(lines, key=lambda ln: (ln.rect[1], ln.rect[0]))
    lines = [ln for ln in lines if ln.text.strip()]
    if not lines:
        return []
    max_w = max(ln.rect[2] - ln.rect[0] for ln in lines)
    blocks: list[BlockDraft] = [BlockDraft([lines[0]])]
    for prev, ln in zip(lines, lines[1:]):
        prev_full = (prev.rect[2] - prev.rect[0]) >= 0.72 * max_w
        # 字号差得多的不并：两行字数都够时比平均字宽（很稳），否则比校正后的框高（波动大，放宽）
        cp, cn = char_width(prev), char_width(ln)
        if cp is not None and cn is not None:
            similar = max(cp, cn) <= 1.2 * min(cp, cn)
        else:
            ep, en = body_height(prev), body_height(ln)
            similar = max(ep, en) <= 1.35 * min(ep, en)
        # 竖排的短标签（菜单、选项、目录）每行各是一项：上一行本身够长才可能是自动换行，
        # 或者下一行以小写字母开头、明显是句子的延续
        long_enough = len(prev.text.strip()) >= 20 or _CJK.search(prev.text) is not None
        continues = ln.text.strip()[:1].islower()
        if similar and not _LIST_MARK.match(ln.text) and ((prev_full and long_enough) or continues):
            blocks[-1].lines.append(ln)
        else:
            blocks.append(BlockDraft([ln]))
    return blocks




def join_lines(lines: list[Line]) -> str:
    """把块内各行连成一句话：西文行间补空格，连字符断词接回去；中日韩文字直接相连。"""
    out = ""
    for ln in lines:
        t = ln.text.strip()
        if not out:
            out = t
            continue
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and t[:1].islower():
            out = out[:-1] + t
        elif _CJK.search(out[-1:]) and _CJK.search(t[:1]):
            out += t
        else:
            out += " " + t
    return out
