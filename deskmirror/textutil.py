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
# 识别模型常把片假名的长音“ー”认成减号、破折号或汉字“一”（セーブ → セ-ブ）：夹在片假名中间、或在片假名词尾的改回来
_KATA = "ァ-ヺー"
_LONG_VOWEL = re.compile(rf"(?<=[{_KATA}])[-‐-―−－一](?=[{_KATA}]|\s|$)")


def fix_ocr(text: str) -> str:
    """识别结果的小修正：片假名中间被认成“-”“一”的长音改回“ー”（不然术语表对不上，模型也常原样返回）。"""
    return _LONG_VOWEL.sub("ー", text)


# 标点前后的空格：识别时常常时有时无（“와, 여기서”/“와,여기서”），算同一句，不为它多翻译一次
_PUNCT_SPACE = re.compile(r"\s*([,.!?:;\u3001\u3002])\s*")


def cache_key(text: str) -> str:
    t = _SPACES.sub(" ", unicodedata.normalize("NFKC", text)).strip()
    return _PUNCT_SPACE.sub(r"\1", t)


# 印尼文里很常见、英文里几乎不出现的词：拉丁字母的文字靠它们分辨是不是印尼文
_ID_WORDS = frozenset("yang dan untuk dengan tidak adalah ini itu dari pada akan atau juga dalam kami anda bisa sudah "
                      "harus jika kepada oleh telah belum karena saat setelah sebelum semua tersebut".split())
_WORDS = re.compile(r"[A-Za-z]+")


def looks_indonesian(text: str) -> bool:
    """拉丁字母写的文字像不像印尼文：常见印尼文虚词出现两个以上（短句一个就算）。"""
    words = [w.lower() for w in _WORDS.findall(text)]
    hits = {w for w in words if w in _ID_WORDS}
    return len(hits) >= 2 or (len(words) <= 4 and len(hits) == 1)


def has_words(text: str) -> bool:
    """至少两个字母（任何文字）：不是纯数字、符号。"""
    return len(_LETTER.findall(text)) >= 2


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
        return not (latin / n >= 0.8) or looks_indonesian(text)
    if target == "id":
        return not (latin / n >= 0.8 and looks_indonesian(text))
    return True


def _inner_background(px: np.ndarray) -> np.ndarray | None:
    """行框里面最多的那种颜色（粗分成 8 级一档）：界面的标签页、按钮、高亮条里，字本身占不到一半，
    剩下的就是字紧挨着的底色。"""
    if len(px) < 16:
        return None
    q = px // 32
    codes = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    counts = np.bincount(codes, minlength=512)
    top = int(np.argmax(counts))
    if counts[top] < 0.4 * len(px):
        return None
    return np.median(px[codes == top], axis=0)


def sample_colors(bgr: np.ndarray, line_rects: list[tuple[int, int, int, int]]) -> tuple[tuple, tuple]:
    """估计文字块的背景色和文字色（RGB）。bgr 是块所在区域的截图，line_rects 是行在其中的坐标。"""
    h, w = bgr.shape[:2]
    if h < 2 or w < 2:
        return (255, 255, 255), (0, 0, 0)
    border = np.concatenate([bgr[0, :], bgr[-1, :], bgr[:, 0], bgr[:, -1]]).reshape(-1, 3).astype(np.int32)
    bg = np.median(border, axis=0)
    inside = [bgr[max(0, t):min(h, b), max(0, l):min(w, r)].reshape(-1, 3) for l, t, r, b in line_rects]
    inside = [p for p in inside if p.size]
    if inside:
        ib = _inner_background(np.concatenate(inside).astype(np.int32))
        # 框外一圈碰到了标签页、按钮的深色边框或别的面板（框里的底色和外圈差得多）：用框里的底色，
        # 不然底板成了一块黑方块（Houdini 的工具架标签）
        if ib is not None and np.abs(ib - bg).sum() > 36:
            bg = ib
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


def plate_gradient(bgr: np.ndarray, line_rects: list[tuple[int, int, int, int]], bg: tuple,
                   fg: tuple) -> tuple[tuple, tuple] | None:
    """按钮、下拉框常是上浅下深的渐变：返回 (上沿颜色, 下沿颜色)（RGB），底板照着画；纯色的返回 None。
    取所有行合起来的框里最上、最下两行不是字的像素（检测框比字高出一点，那几行基本是底）。"""
    h, w = bgr.shape[:2]
    l, t = max(0, min(r[0] for r in line_rects)), max(0, min(r[1] for r in line_rects))
    r_, b = min(w, max(r[2] for r in line_rects)), min(h, max(r[3] for r in line_rects))
    if r_ - l < 6 or b - t < 6:
        return None
    bg_bgr = np.array(bg[::-1], np.int32)
    fg_bgr = np.array(fg[::-1], np.int32)

    def edge(rows: np.ndarray) -> np.ndarray | None:
        px = rows.reshape(-1, 3).astype(np.int32)
        keep = np.abs(px - bg_bgr).sum(axis=1) < np.abs(px - fg_bgr).sum(axis=1)      # 离底色比离字色近的
        return np.median(px[keep], axis=0) if keep.sum() >= 8 else None

    top, bottom = edge(bgr[t:t + 2, l:r_]), edge(bgr[b - 2:b, l:r_])
    if top is None or bottom is None or not 14 <= int(np.abs(top - bottom).sum()) <= 150:
        return None
    return (int(top[2]), int(top[1]), int(top[0])), (int(bottom[2]), int(bottom[1]), int(bottom[0]))


_ASCENDING = re.compile(r"[bdfhklt0-9A-Z]")


def line_ink(bgr: np.ndarray, line_rects: list[tuple[int, int, int, int]], texts: list[str], bg: tuple,
             fg: tuple) -> list[tuple[int, int, int, int, float] | None]:
    """各行文字的墨迹范围 (左, 上, 右, 下) 和按笔画估的原文字号（像素；0 = 估不出）。
    检测框四周的留白随字数、字母形状变（“Line”“Camera”这种短词留白占比大）：按框宽、框高估字号会忽大忽小，
    对齐也要按字的边、不按框的边。字号按整行墨迹的高度换算：同时有上伸字母（含大写、数字）和下伸字母时约占
    0.94 个字号，只有上伸 0.72，只有下伸 0.74，都没有（x 高）0.52，中日韩文字 0.88。
    bgr 是块所在区域的截图，bg / fg 是 RGB。"""
    lb = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    lf = 0.299 * fg[0] + 0.587 * fg[1] + 0.114 * fg[2]
    if abs(lf - lb) < 40:
        return [None] * len(line_rects)
    gray = bgr[..., 0] * 0.114 + bgr[..., 1] * 0.587 + bgr[..., 2] * 0.299
    sign = 1.0 if lf > lb else -1.0
    thr = max(20.0, 0.45 * abs(lf - lb))
    h, w = gray.shape
    out: list[tuple[int, int, int, int, float] | None] = []
    for (l, t, r, b), text in zip(line_rects, texts):
        l, t, r, b = max(0, l), max(0, t), min(w, r), min(h, b)
        patch = gray[t:b, l:r]
        if patch.size == 0:
            out.append(None)
            continue
        mask = (patch - lb) * sign > thr
        mask[mask.mean(axis=1) > 0.85] = False         # 横贯整行的下划线、边框线不是字
        rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
        if len(rows) < 3 or len(cols) < 2:
            out.append(None)
            continue
        top, bottom = int(rows[0]), int(rows[-1]) + 1
        # 整行墨迹的总高度占字号的比例取决于有没有上伸字母（含大写、数字）和下伸字母（g j p q y）
        t_ = text.strip()
        if _HAN.search(t_) or _KANA.search(t_) or _HANGUL.search(t_):
            share = 0.88
        elif any(c.isalpha() for c in t_):
            asc, desc = bool(_ASCENDING.search(t_)), any(c in _DESC for c in t_)
            share = 0.94 if asc and desc else 0.72 if asc else 0.74 if desc else 0.52
        else:
            share = 0.0
        px = (bottom - top) / share if share else 0.0
        if px and not 0.3 * (b - t) <= px <= 1.6 * (b - t):
            px = 0.0                                # 和框高差得离谱：多半是把图标、边框也当成了字
        out.append((l + int(cols[0]), t + top, l + int(cols[-1]) + 1, t + bottom, round(px, 2)))
    return out


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


_SHORTCUT = re.compile(
    r"^(?:(?:(?:ctrl|control|alt|shift|cmd|command|win|meta|option|opt|super)\s*[+\-]\s*)+"
    r"(?:[a-z0-9]|f\d{1,2}|del(?:ete)?|esc(?:ape)?|enter|return|tab|space|backspace|home|end|pgup|pgdn|"
    r"page ?up|page ?down|ins(?:ert)?|up|down|left|right|plus|minus|[\[\]\\/;',.`=+\-])|f\d{1,2})$", re.I)


def looks_like_shortcut(text: str) -> bool:
    """菜单里的快捷键（Ctrl+C、Alt+Shift+F4、F2）：不翻译、不遮盖，原样留着。"""
    return bool(_SHORTCUT.match(" ".join(text.split())))


_CODE_CHARS = re.compile(r"[{};=<>]|::|=>|\(\)|\w+\(|^\s*(?:def|class|import|return|const|let|var|function)\b")


def looks_like_code(text: str) -> bool:
    """像程序代码的块不翻译、不遮盖：译了也会被重新排版，反而看不清原来的缩进和换行。"""
    hits = len(_CODE_CHARS.findall(text))
    words = max(1, len(text.split()))
    return hits >= 3 and hits / words >= 0.25
