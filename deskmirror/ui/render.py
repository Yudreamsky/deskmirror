"""把一块译文排版成图片：在原文字块位置画底板遮住原文，再写译文。

排版只取决于文字块本身（位置、行高、可向下延伸的空间），与魔镜位置无关：
拖动或缩放魔镜只改变裁剪，不会重新排版；同一 (bid, version) 只排一次。

放不下时依次：横向压扁到八成、缩小字号（不小于原字号的 min_scale 且不小于 min_font_px）、向右借用右边的纯色空白
（引擎算好的 room 右边，不超过右边的文字块；中日文译成英文常需要），谁的字大用谁 → 向下占用下方同色的空白
（不超过相邻文字块）→ 再压扁（最扁 min_squash，中日韩文字最多八成）放进原来的高度 → 下面是边框、图片、在动的画面时
再缩小一些（最小到原字号的六成），还不行才盖过去 → 仍放不下就截断并在末尾标“…”，鼠标停留时显示全文。
借来的地方用多少占多少，底板只比最长的一行宽一点。
竖排的漫画气泡：底板只盖原来的每个字和译文实际占的地方（不铺满整块，免得方角伸出椭圆气泡、盖掉边框），
横排的译文每行居中。
译文照原文的对齐摆（引擎看同一列的块判断）：右对齐的参数名贴着输入框，图标下的名字、下拉框里的字居中，
从原文笔画的边开始（不从检测框的边）；放不下时右对齐的向左借、居中的向两边借。界面上的短标签不折行：
放不下先压扁、缩小，再不行就截断。
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QRegion, QTextLayout, QTextOption

from ..config import StyleConfig
from ..scene import DrawItem
from .layered import KEY

PAD = 2
_EASY_SQUASH = 0.8   # 横向压扁到八成几乎看不出来：先压扁，再缩字号
# 句末的全角标点（。，、；：！？」』）】》…），按码点写，免得被当成要翻译的界面文字
_CJK_END = "".join(map(chr, (0x3002, 0xFF0C, 0x3001, 0xFF1B, 0xFF1A, 0xFF01, 0xFF1F, 0x300D, 0x300F, 0xFF09,
                             0x3011, 0x300B, 0x2026)))


@dataclass
class Rendered:
    image: QImage
    dx: int                  # 图片左上角相对原文字块左上角的偏移
    dy: int
    width: int
    height: int
    truncated: bool
    font_px: int
    squash: float = 1.0      # 横向压扁的比例（1 = 没压）


def _wrap(text: str, font: QFont, width: float) -> list[tuple[int, int]]:
    """按宽度换行，返回每行在 text 中的 (起点, 长度)。中文可以在任意字之间换行。"""
    layout = QTextLayout(text, font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(opt)
    layout.beginLayout()
    spans = []
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        spans.append((line.textStart(), line.textLength()))
    layout.endLayout()
    return spans


# 竖着排时标点换成竖排的写法（不然“，”在字的左下、“——”和长音还是横着的）；按码点写，免得被当成要翻译的界面文字
_VERT = {chr(a): chr(b) for a, b in (
    (0xFF0C, 0xFE10), (0x3001, 0xFE11), (0x3002, 0xFE12), (0xFF1A, 0xFE13), (0xFF1B, 0xFE14), (0x2026, 0xFE19),
    (0x2014, 0xFE31), (0x2015, 0xFE31), (0x30FC, 0xFF5C), (0xFF08, 0xFE35), (0xFF09, 0xFE36), (0x300C, 0xFE41),
    (0x300D, 0xFE42), (0x300E, 0xFE43), (0x300F, 0xFE44), (0xFF5E, 0xFE34), (0x7E, 0xFE34), (0x2C, 0xFE10),
    (0x2E, 0xFE12), (0x3A, 0xFE13), (0x3B, 0xFE14), (0x28, 0xFE35), (0x29, 0xFE36), (0x21, 0xFF01), (0x3F, 0xFF1F))}
# 竖着排时尽量在这些标点后面换列：！？。，、；… 和半角的 ! ? . , ;
_BREAK_AFTER = set(map(chr, (0xFF01, 0xFF1F, 0x3002, 0xFF0C, 0x3001, 0xFF1B, 0x2026, 0x21, 0x3F, 0x2E, 0x2C, 0x3B)))


def _vertical_columns(text: str, per_col: int) -> list[list[str]]:
    """竖着排：标点换成竖排的写法，按每列 per_col 个字分列，尽量在标点后面换列（一句放得进一整列就不从中间断开）。"""
    phrases: list[list[str]] = [[]]
    for c in text:
        if c.isspace():
            continue
        phrases[-1].append(_VERT.get(c, c))
        if c in _BREAK_AFTER:
            phrases.append([])
    cols: list[list[str]] = [[]]
    for ph in phrases:
        if not ph:
            continue
        if len(cols[-1]) + len(ph) <= per_col:
            cols[-1] += ph
        elif len(ph) <= per_col:
            cols.append(list(ph))
        else:
            for c in ph:
                if len(cols[-1]) >= per_col:
                    cols.append([])
                cols[-1].append(c)
    return [c for c in cols if c]


def _fill_plates(p: QPainter, rects: list[tuple[float, float, float, float]], color: QColor) -> None:
    """几块底板合成一块再填色：重叠的地方不会因为半透明叠了两层而更深。"""
    region = QRegion()
    for x0, y0, x1, y1 in rects:
        l, t, r, b = math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)
        if r > l and b > t:
            region = region.united(QRegion(l, t, r - l, b - t))
    p.save()
    p.setClipRegion(region)
    p.fillRect(QRectF(0, 0, p.device().width(), p.device().height()), color)
    p.restore()


def _col_plates(item: DrawItem) -> list[tuple[float, float, float, float]]:
    """竖排原文每个字的底板（图片坐标：图片左上角在原文块左上角往外 PAD 处），四边各多盖 PAD。"""
    return [(c[0], c[1], c[2] + 2 * PAD, c[3] + 2 * PAD) for c in item.cols]


def _squashes(lo: float) -> list[float]:
    """从不压（1）到 lo 每次压 5%。"""
    n = max(0, int(round((1.0 - lo) / 0.05)))
    return [round(1.0 - i * 0.05, 2) for i in range(n + 1)]


def _mostly_cjk(text: str) -> bool:
    chars = [c for c in text if not c.isspace()]
    return sum(ord(c) >= 0x2E80 for c in chars) * 2 > len(chars)


def _balanced(text: str, n: int, font: QFont, width: float) -> list[tuple[int, int]] | None:
    """分成 n 行、每行差不多长（照原文分两行写的名字：柏拉图 / 立体）：西文在词之间分，中日韩文字在字之间分。
    只分两行；哪种分法都有一行放不下就返回 None。"""
    if n != 2 or len(text) < 2:
        return None
    fm = QFontMetricsF(font)
    cuts = [i for i, c in enumerate(text) if c == " "] if " " in text else list(range(1, len(text)))
    best = None
    for k in cuts:
        a, b = text[:k].rstrip(), text[k:].lstrip()
        if not a or not b:
            continue
        w = max(fm.horizontalAdvance(a), fm.horizontalAdvance(b))
        key = (round(w, 1), -len(a))                  # 一样宽时第一行长一点（几何体 / 灯光）
        if w <= width and (best is None or key < best[0]):
            best = (key, [(0, len(a)), (len(text) - len(b), len(b))])
    return best[1] if best else None


def _wordchar(c: str) -> bool:
    """拉丁字母、数字这类靠空格分词的文字（中日文的字之间本来就能换行）。"""
    return c.isalnum() and ord(c) < 0x2E80


def _tail(text: str, spans: list[tuple[int, int]], px: int, font: QFont) -> float:
    """最后一行占多高：汉字约 1.08 个字号；有 g、p、y 这类下伸字母时按字体实际高度，免得字脚被底板裁掉。"""
    if spans:
        a, n = spans[-1]
        if any(c in "gjpqy,;()" for c in text[a:a + n]):
            return QFontMetricsF(font).height()
    return px * 1.08


_CLOSING = set(",.!?;:)]}'\"%")


def _breaks_word(text: str, spans: list[tuple[int, int]]) -> bool:
    """换行把一个英文词拆成了两半（比如 Captai / n），或者把词后面的标点挤到了下一行开头（leaving / !）。"""
    for a, n in spans[:-1]:
        e = a + n
        if 0 < e < len(text) and _wordchar(text[e - 1]) and (_wordchar(text[e]) or text[e] in _CLOSING):
            return True
    return False


def _binarize(img: QImage) -> QImage:
    """色键窗口用：每个像素要么全透明、要么不透明（半透明的边按一半为界），碰上色键颜色的挪开一点。"""
    w, h = img.width(), img.height()
    if not w or not h:
        return img
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    alpha = a[..., 3].astype(np.uint32)
    keep = alpha >= 128
    out = np.zeros((h, w, 4), np.uint8)
    for ch in range(3):          # 预乘过的颜色还原成原色
        c = a[..., ch].astype(np.uint32)
        out[..., ch] = np.where(keep, np.minimum(255, (c * 255 + alpha // 2) // np.maximum(alpha, 1)), 0)
    out[..., 3] = np.where(keep, 255, 0)
    hit = keep & (out[..., 0] == KEY[2]) & (out[..., 1] == KEY[1]) & (out[..., 2] == KEY[0])    # 内存里是 BGRA
    out[..., 0][hit] = KEY[2] - 1
    return QImage(out.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()


class Renderer:
    def __init__(self, style: StyleConfig, binary: bool = False) -> None:
        self.binary = binary         # 色键窗口（Windows 10）：图片只要全透明或不透明，底板总是不透明
        self.style = self._effective(style)
        self._cache: dict[int, tuple[int, tuple, Rendered]] = {}

    def _effective(self, style: StyleConfig) -> StyleConfig:
        return dataclasses.replace(style, plate_opacity=1.0) if self.binary else style

    def set_style(self, style: StyleConfig) -> None:
        self.style = self._effective(style)
        self._cache.clear()

    def get(self, item: DrawItem) -> Rendered:
        sig = (item.rect[2] - item.rect[0], item.rect[3] - item.rect[1], item.room[2] - item.room[0],
               item.room[3] - item.room[1], None if item.soft is None else item.soft - item.rect[1])
        hit = self._cache.get(item.bid)
        if hit is not None and hit[0] == item.version and hit[1] == sig:
            return hit[2]
        r = self._render(item)
        if self.binary:
            r.image = _binarize(r.image)
        self._cache[item.bid] = (item.version, sig, r)
        return r

    def prune(self, live: set[int]) -> None:
        if len(self._cache) > 2 * max(256, len(live)):
            for bid in [b for b in self._cache if b not in live]:
                del self._cache[bid]

    def _render_vertical(self, item: DrawItem, text: str, w: int, h: int, base_px: int, lo_px: int) -> Rendered | None:
        """竖排气泡的中日文译文也竖着排：从上往下、从右往左，尽量在标点后面换列，和原来的漫画一样。
        放不下（最小到原字号的六成）返回 None，改成横排。"""
        st = self.style
        font = QFont(st.font_family)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        for px in range(base_px, lo_px - 1, -1):
            step = px * 1.02                                 # 竖着排的字距（和漫画里一样紧）
            per_col = int((h + 2) // step)
            if per_col < 1:
                continue
            cols = _vertical_columns(text, per_col)
            col_w = px * 1.3
            need_w = len(cols) * col_w - (col_w - px)
            if need_w > w + 2:
                continue
            font.setPixelSize(px)
            fm = QFontMetricsF(font)
            img = QImage(w + 2 * PAD, h + 2 * PAD, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            bg = QColor(*item.bg)
            bg.setAlphaF(st.plate_opacity)
            right = PAD + (w + need_w) / 2 - px              # 最右一列的左边（几列在原文的地方左右居中）
            glyphs = []
            for i, col in enumerate(cols):
                x = right - i * col_w
                for j, ch in enumerate(col):
                    glyphs.append((ch, x + (px - fm.horizontalAdvance(ch)) / 2,
                                   PAD + j * step + (step - fm.height()) / 2 + fm.ascent()))
            if item.cols:
                # 底板只盖原文的字和译文的字（各自的墨迹）
                ink = [(gx, gy, fm.boundingRect(ch)) for ch, gx, gy in glyphs]
                _fill_plates(p, _col_plates(item) + [(gx + br.left() - PAD, gy + br.top() - PAD, gx + br.right() + PAD,
                                                      gy + br.bottom() + PAD) for gx, gy, br in ink], bg)
            else:
                p.fillRect(QRectF(0, 0, img.width(), img.height()), bg)
            p.setFont(font)
            p.setPen(QColor(*item.fg))
            for ch, gx, gy in glyphs:
                p.drawText(QPointF(gx, gy), ch)
            p.end()
            return Rendered(img, -PAD, -PAD, img.width(), img.height(), False, px)
        return None

    def _render(self, item: DrawItem) -> Rendered:
        st = self.style
        w = max(8, item.rect[2] - item.rect[0])
        h = max(6, item.rect[3] - item.rect[1])
        # 放不下时可以借的空白：左对齐的向右借，右对齐的向左借（右边多半是输入框），居中的两边借一样多
        right_room = max(0, item.room[2] - item.rect[2]) if item.align != "right" else 0
        left_room = max(0, item.rect[0] - item.room[0]) if item.align != "left" else 0
        if item.align == "center":
            right_room = left_room = min(right_room, left_room)
        wide = w + left_room + right_room
        room_h = max(h, item.room[3] - item.room[1])
        # 下面同色、静止的空白有多高：再往下是面板边框、图片、在动的画面
        soft_h = room_h if item.soft is None else min(room_h, max(h, item.soft - item.rect[1]))
        n_orig = max(1, item.n_lines)
        base_px = max(9, min(160, round((item.em or item.line_h) * 0.74)))
        if not item.vertical and _mostly_cjk(item.text):
            # 中日韩文字比 min_font_px 还小就糊成一团（4K 屏上软件界面的小字常只有 10 像素）：至少写这么大
            base_px = max(base_px, st.min_font_px)
        min_px = min(base_px, max(st.min_font_px, round(base_px * st.min_scale)))
        floor_px = min(min_px, max(st.min_font_px, round(base_px * 0.6)))
        orig_pitch = (h - item.line_h) / (n_orig - 1) if n_orig > 1 else item.line_h * 1.25
        font = QFont(st.font_family)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        text = " ".join(item.text.split())
        if item.vertical and text and _mostly_cjk(text):
            r = self._render_vertical(item, text, w, h, base_px, floor_px)
            if r is not None:
                return r
        if not text:
            # 只要一块底板（字幕换句时垫在新句子下面，挡住还没译好的原文）
            img = QImage(w + 2 * PAD, h + 2 * PAD, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            bg = QColor(*item.bg)
            bg.setAlphaF(st.plate_opacity)
            p = QPainter(img)
            p.fillRect(QRectF(0, 0, img.width(), img.height()), bg)
            p.end()
            return Rendered(img, -PAD, -PAD, w + 2 * PAD, h + 2 * PAD, False, 0)

        # 横向压扁：压到八成几乎看不出来，先压扁再缩字号；更扁的（最扁 min_squash）只在快要伸出去、要缩得更小时才用。
        # 中日韩文字压扁了难看，最多压到八成
        hard = _EASY_SQUASH if _mostly_cjk(text) else min(_EASY_SQUASH, max(0.3, st.min_squash))
        easy = _squashes(_EASY_SQUASH)
        full = _squashes(hard)

        def in_height(px: int, sx: float, width: float, split_ok: bool):
            font.setPixelSize(px)
            spans = _wrap(text, font, width / sx)           # 压扁 sx 倍画，就能按宽 width / sx 换行
            if not split_ok and _breaks_word(text, spans):
                return None
            if item.label and len(spans) > 1:               # 短标签不折行；原文本来就分两行写的，照样平均分两行
                spans = _balanced(text, n_orig, font, width / sx) if n_orig == 2 else None
                if spans is None:
                    return None
            pitch = max(px * 1.18, min(orig_pitch, px * 1.7)) if n_orig > 1 else px * 1.25
            # 汉字实际占高约 1.0~1.1 个字号；按 1.3 倍留量会让矮检测框（没有下伸字母的行）的译文被无谓缩小
            need = (len(spans) - 1) * pitch + _tail(text, spans, px, font)
            return (px, spans, pitch, h, False, sx) if need <= h + 3 else None

        def below(px: int, sx: float, width: float, split_ok: bool, limit_h: int):
            font.setPixelSize(px)
            spans = _wrap(text, font, width / sx)
            if not split_ok and _breaks_word(text, spans):
                return None
            if item.label and len(spans) > 1:
                return None
            pitch = px * 1.18
            need = (len(spans) - 1) * pitch + max(px * 1.15, _tail(text, spans, px, font))
            return (px, spans, pitch, int(need + 0.999), False, sx) if need <= limit_h + 2 else None

        def search(fit, pxs, sxs):
            """字号从大到小；同一字号先看压到最扁放不放得下（放不下就换小一号），放得下再找最不扁的那个。"""
            for px in pxs:
                if fit(px, sxs[-1]) is None:
                    continue
                for sx in sxs:
                    r = fit(px, sx)
                    if r is not None:
                        return r
            return None

        main_px = range(base_px, min_px - 1, -1)
        chosen = None
        for split_ok in (False, True):                      # 先找不用把英文单词拆开的排法
            # 原文那么大的地方 / 向右借空白（高度不变）：压扁一点、缩字号
            here = search(lambda px, sx: in_height(px, sx, w, split_ok), main_px, easy)
            right = search(lambda px, sx: in_height(px, sx, wide, split_ok), main_px, easy) if wide > w else None
            # 两种都行时谁的字大用谁（一样大比谁压得少）：向右借能少缩字号就借，一样就不借
            chosen = right if right and (not here or (right[0], right[5]) > (here[0], here[5])) else here
            # 向下借空白（宽度也用借来的）
            chosen = chosen or search(lambda px, sx: below(px, sx, wide, split_ok, soft_h), main_px, easy)
            if not chosen and hard < _EASY_SQUASH:
                # 再压扁一些（最扁到 min_squash）放进原来的高度：短标签、名牌、倒计时不用缩得更小，也不伸出去
                chosen = search(lambda px, sx: in_height(px, sx, wide, split_ok), main_px, full)
            if not chosen and soft_h < room_h:
                # 下面是面板边框、图片、在动的画面：宁可再缩小一点放进原来的高度（最小到原字号的六成），
                # 还放不下才盖过去。不然游戏里的倒计时、按钮会伸出面板，而且字号差一点就在一行和两行之间来回跳
                chosen = (search(lambda px, sx: in_height(px, sx, wide, split_ok), range(min_px - 1, floor_px - 1, -1), full)
                          or search(lambda px, sx: below(px, sx, wide, split_ok, room_h), main_px, easy))
            if chosen or split_ok:
                break
            # 有个词比能用的宽度还长（短标签译成英文常见）：底板放宽到正好放下这个词（不越过右边的字），
            # 还不够就再缩一点字号（最小到原字号的六成），都不行才拆词
            font.setPixelSize(min_px)
            word = max((QFontMetricsF(font).horizontalAdvance(t) for t in text.split()), default=0.0)
            if word + 4 > wide:
                cap = max(wide, item.stretch - item.rect[0]) if item.stretch else wide
                wider = max(wide, min(int(word + 0.999) + 4, cap))
                chosen = search(lambda px, sx: below(px, sx, wider, False, room_h), main_px, [1.0]) if wider > wide else None
                for px in range(min_px - 1, max(st.min_font_px, round(base_px * 0.6)) - 1, -1):
                    if chosen:
                        break
                    font.setPixelSize(px)
                    spans = _wrap(text, font, wider)
                    need = (len(spans) - 1) * px * 1.18 + max(px * 1.15, _tail(text, spans, px, font))
                    if not _breaks_word(text, spans) and need <= room_h + 2:
                        chosen = (px, spans, px * 1.18, int(need + 0.999), False, 1.0)
                if chosen:
                    wide = wider
                    break
        if chosen is None and item.label:
            # 短标签缩到最小、压到最扁还放不下：一行截断，鼠标停上去看全文
            px, sx = floor_px, full[-1]
            font.setPixelSize(px)
            over = QFontMetricsF(font).horizontalAdvance(text) * sx > wide
            chosen = (px, [(0, len(text))], px * 1.18, h, over, sx)
        if chosen is None:
            px = min_px
            font.setPixelSize(px)
            spans = _wrap(text, font, wide)
            pitch = px * 1.18
            max_lines = max(1, int((room_h - px * 1.15) // pitch) + 1)
            chosen = (px, spans[:max_lines], pitch, room_h, len(spans) > max_lines, 1.0)
        px, spans, pitch, used_h, truncated, sx = chosen
        font.setPixelSize(px)
        fm = QFontMetricsF(font)
        plate_w = w
        if wide > w:
            # 借来的地方用多少占多少：底板只比最长的一行宽一点
            longest = max((fm.horizontalAdvance(text[a:a + n].rstrip()) * sx for a, n in spans), default=0.0)
            plate_w = wide if truncated else max(w, min(wide, int(longest + 0.999) + 3))
        end = item.src.rstrip()[-1:]
        if end and end in _CJK_END and not item.vertical and item.align == "left":
            # 识别框常常没把句末的全角标点框进去：底板往右多盖大半个字，免得旁边露出一个“。”
            plate_w = max(plate_w, w + round(item.line_h * 0.6))
        # 底板相对原文块左边从哪儿开始：右对齐的向左伸，居中的两边各伸一半
        x0p = w - plate_w if item.align == "right" else (w - plate_w) // 2 if item.align == "center" else 0
        ink = item.ink or (0, 0, w, h)
        img_w, img_h = plate_w + 2 * PAD, max(h, used_h) + 2 * PAD
        img = QImage(img_w, img_h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bg = QColor(*item.bg)
        bg.setAlphaF(st.plate_opacity)
        p.setFont(font)
        p.setPen(QColor(*item.fg))
        # 单行：在原文字块里竖直居中；多行：第一行对齐原文第一行，行距贴近原文。
        # 原文只有一行、译文缩小字号排成几行塞进原来的高度（小名牌里的“Captain / Mina”）：整段竖直居中，
        # 不然按原文那一行往下排，第二行会掉出底板、被裁掉半截
        if len(spans) == 1:
            top = PAD + max(0.0, (max(h, used_h) - fm.height()) / 2)
        elif n_orig == 1 and used_h <= h:
            top = PAD + max(0.0, (h - ((len(spans) - 1) * pitch + fm.height())) / 2)
        else:
            top = PAD + max(0.0, (item.line_h - fm.height()) / 2)
        drawn = []
        for i, (start, length) in enumerate(spans):
            line = text[start:start + length].rstrip()
            if truncated and i == len(spans) - 1:
                line = fm.elidedText(line + "……", Qt.TextElideMode.ElideRight, plate_w / sx)
                if not line.endswith("…"):
                    line = line[:-1] + "…"
            adv = fm.horizontalAdvance(line) * sx
            if item.cols:
                x = PAD + max(0.0, (plate_w - adv) / 2)        # 竖排气泡里的横排译文：每行居中
            else:
                # 照原文的对齐，笔画对笔画（字形两边各有一点留白）；放不下时在底板里尽量靠那一边
                tb = fm.tightBoundingRect(line)
                il, ir = tb.left() * sx, tb.right() * sx
                want = (ink[2] - ir if item.align == "right" else (ink[0] + ink[2] - il - ir) / 2
                        if item.align == "center" else ink[0] - il)
                x = PAD + max(0.0, min(want - x0p, plate_w - adv))
            drawn.append((line, x, top + i * pitch, adv))
        if item.cols:
            _fill_plates(p, _col_plates(item) + [(x - PAD, y0 - PAD, x + adv + PAD, y0 + fm.height() + PAD)
                                                 for _line, x, y0, adv in drawn], bg)
        elif item.grad:
            # 按钮、下拉框上浅下深：底板照着原文块上下边的颜色画渐变
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(0, PAD, 0, PAD + h)
            for stop, rgb in ((0.0, item.grad[0]), (1.0, item.grad[1])):
                c = QColor(*rgb)
                c.setAlphaF(st.plate_opacity)
                g.setColorAt(stop, c)
            p.fillRect(QRectF(0, 0, img_w, img_h), g)
        else:
            p.fillRect(QRectF(0, 0, img_w, img_h), bg)
        for line, x, y0, _adv in drawn:
            y = y0 + fm.ascent()
            if sx < 1.0:
                p.save()
                p.translate(x, y)
                p.scale(sx, 1.0)                    # 横向压扁（字高不变）
                p.drawText(QPointF(0, 0), line)
                p.restore()
            else:
                p.drawText(QPointF(x, y), line)
        if truncated:
            # 右下角小三角：这块没显示全，鼠标停在上面可以看全文
            c = QColor(*item.fg)
            c.setAlphaF(0.75)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            from PySide6.QtGui import QPolygonF
            p.drawPolygon(QPolygonF([QPointF(img_w - 1, img_h - 9), QPointF(img_w - 1, img_h - 1),
                                     QPointF(img_w - 9, img_h - 1)]))
        p.end()
        return Rendered(img, x0p - PAD, -PAD, img_w, img_h, truncated, px, sx)
