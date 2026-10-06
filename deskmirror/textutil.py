"""文字判断与颜色取样。"""
from __future__ import annotations

import re
import unicodedata

import numpy as np

_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_KANA = re.compile(r"[぀-ヿㇰ-ㇿ]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def cache_key(text: str) -> str:
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def needs_translation(text: str, target: str) -> bool:
    """原文已经是目标语言、或只有数字符号时不翻译，也不遮盖原文。"""
    letters = _LETTER.findall(text)
    if len(letters) < 2:
        return False
    n = len(letters)
    han = len(_HAN.findall(text))
    kana = len(_KANA.findall(text))
    hangul = len(_HANGUL.findall(text))
    latin = len(_LATIN.findall(text))
    if target in ("zh-Hans", "zh-Hant"):
        return not (han / n >= 0.5 and kana == 0 and hangul == 0)
    if target == "ja":
        return not (kana > 0 or han / n >= 0.5)
    if target == "ko":
        return not (hangul / n >= 0.5)
    if target == "en":
        return not (latin / n >= 0.8)
    return True


def sample_colors(bgr: np.ndarray, line_rects: list[tuple[int, int, int, int]]) -> tuple[tuple, tuple]:
    """估计文字块的背景色和文字色（RGB）。bgr 是块所在区域的截图，line_rects 是行在其中的坐标。"""
    h, w = bgr.shape[:2]
    if h < 2 or w < 2:
        return (255, 255, 255), (0, 0, 0)
    border = np.concatenate([bgr[0, :], bgr[-1, :], bgr[:, 0], bgr[:, -1]]).reshape(-1, 3).astype(np.int32)
    bg = np.median(border, axis=0)
    inner = []
    for l, t, r, b in line_rects:
        patch = bgr[max(0, t):min(h, b), max(0, l):min(w, r)]
        if patch.size:
            inner.append(patch.reshape(-1, 3))
    if inner:
        px = np.concatenate(inner).astype(np.int32)
        dist = np.abs(px - bg).sum(axis=1)
        # 取与底色反差最大的那部分像素：正文黑字里夹着蓝色链接时，取到的是正文的颜色
        far = dist >= max(60, int(np.percentile(dist, 97) * 0.85))
        fg = np.median(px[far], axis=0) if far.sum() >= 8 else None
    else:
        fg = None
    bg_rgb = (int(bg[2]), int(bg[1]), int(bg[0]))
    if fg is None:
        lum = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
        fg_rgb = (0, 0, 0) if lum > 128 else (255, 255, 255)
    else:
        fg_rgb = (int(fg[2]), int(fg[1]), int(fg[0]))
    return bg_rgb, _ensure_contrast(bg_rgb, fg_rgb)


def _lum(c: tuple) -> float:
    def ch(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ensure_contrast(bg: tuple, fg: tuple) -> tuple:
    """文字和底板对比度太低时（取样失败、细字体）改用黑或白，保证可读。"""
    lb, lf = _lum(bg), _lum(fg)
    ratio = (max(lb, lf) + 0.05) / (min(lb, lf) + 0.05)
    if ratio >= 3.0:
        return fg
    return (0, 0, 0) if lb > 0.4 else (255, 255, 255)


_ASC = set("bdfhklt")
_DESC = set("gjpqy")


def em_height(box_h: float, text: str) -> float:
    """从检测框高度估计原文字号（em）。

    西文行的检测框高度取决于有没有上伸（b d h k l t、大写、数字）和下伸（g j p q y）字母：
    同样字号的 "summer" 比 "Highway" 矮不少。不按字形校正的话，同一列表里的译文会忽大忽小。
    中日韩文字基本占满字身，直接用框高。
    """
    if _HAN.search(text) or _KANA.search(text) or _HANGUL.search(text):
        return float(box_h)
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return float(box_h)
    asc = any(c in _ASC or c.isupper() for c in letters) or any(c.isdigit() for c in text)
    desc = any(c in _DESC for c in letters)
    f = 1.0 if asc and desc else 0.84 if asc else 0.80 if desc else 0.64
    return box_h / f


_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]+")


def looks_untranslated(src: str, out: str, target: str) -> bool:
    """译成中日韩文字时，译文里还留着原文的一大串英文单词：多半是模型漏译了半句。

    专有名词、产品名通常只有两三个词；连续保留 5 个以上原文单词、且占原文四分之一以上才算漏译。
    """
    if target not in ("zh-Hans", "zh-Hant", "ja", "ko"):
        return False
    src_words = [w.lower() for w in _WORD.findall(src)]
    if len(src_words) < 8:
        return False
    out_words = [w.lower() for w in _WORD.findall(out)]
    if len(out_words) < 5:
        return False
    joined = " " + " ".join(src_words) + " "
    best = run = 0
    for i in range(len(out_words)):
        run = 0
        for j in range(i, len(out_words)):
            if (" " + " ".join(out_words[i:j + 1]) + " ") in joined:
                run = j - i + 1
            else:
                break
        best = max(best, run)
    return best >= 5 and best >= 0.25 * len(src_words)


_CODE_CHARS = re.compile(r"[{};=<>]|::|=>|\(\)|\w+\(|^\s*(?:def|class|import|return|const|let|var|function)\b")


def looks_like_code(text: str) -> bool:
    """像程序代码的块不翻译、不遮盖：译了也会被重新排版，反而看不清原来的缩进和换行。"""
    hits = len(_CODE_CHARS.findall(text))
    words = max(1, len(text.split()))
    return hits >= 3 and hits / words >= 0.25
