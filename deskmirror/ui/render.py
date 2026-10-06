"""把一块译文排版成图片：在原文字块位置画底板遮住原文，再写译文。

排版只取决于文字块本身（位置、行高、可向下延伸的空间），与魔镜位置无关：
拖动或缩放魔镜只改变裁剪，不会重新排版；同一 (bid, version) 只排一次。

放不下时依次：横向压扁到八成、缩小字号（不小于原字号的 min_scale 且不小于 min_font_px）、向右借用右边的纯色空白
（引擎算好的 room 右边，不超过右边的文字块；中日文译成英文常需要），谁的字大用谁 → 向下占用下方同色的空白
（不超过相邻文字块）→ 再压扁（最扁 min_squash，中日韩文字最多八成）放进原来的高度 → 下面是边框、图片、在动的画面时
再缩小一些（最小到原字号的六成），还不行才盖过去 → 仍放不下就截断并在末尾标“…”，鼠标停留时显示全文。
借来的地方用多少占多少，底板只比最长的一行宽一点。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QTextLayout, QTextOption

from ..config import StyleConfig
from ..scene import DrawItem

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


def _squashes(lo: float) -> list[float]:
    """从不压（1）到 lo 每次压 5%。"""
    n = max(0, int(round((1.0 - lo) / 0.05)))
    return [round(1.0 - i * 0.05, 2) for i in range(n + 1)]


def _mostly_cjk(text: str) -> bool:
    chars = [c for c in text if not c.isspace()]
    return sum(ord(c) >= 0x2E80 for c in chars) * 2 > len(chars)


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


def _breaks_word(text: str, spans: list[tuple[int, int]]) -> bool:
    """换行把一个英文词拆成了两半（比如 Captai / n）。"""
    for a, n in spans[:-1]:
        e = a + n
        if 0 < e < len(text) and _wordchar(text[e - 1]) and _wordchar(text[e]):
            return True
    return False


class Renderer:
    def __init__(self, style: StyleConfig) -> None:
        self.style = style
        self._cache: dict[int, tuple[int, tuple, Rendered]] = {}

    def set_style(self, style: StyleConfig) -> None:
        self.style = style
        self._cache.clear()

    def get(self, item: DrawItem) -> Rendered:
        sig = (item.rect[2] - item.rect[0], item.rect[3] - item.rect[1], item.room[2] - item.room[0],
               item.room[3] - item.room[1], None if item.soft is None else item.soft - item.rect[1])
        hit = self._cache.get(item.bid)
        if hit is not None and hit[0] == item.version and hit[1] == sig:
            return hit[2]
        r = self._render(item)
        self._cache[item.bid] = (item.version, sig, r)
        return r

    def prune(self, live: set[int]) -> None:
        if len(self._cache) > 2 * max(256, len(live)):
            for bid in [b for b in self._cache if b not in live]:
                del self._cache[bid]

    def _render(self, item: DrawItem) -> Rendered:
        st = self.style
        w = max(8, item.rect[2] - item.rect[0])
        h = max(6, item.rect[3] - item.rect[1])
        wide = max(w, item.room[2] - item.rect[0])          # 放不下时最多可以向右借到这么宽
        room_h = max(h, item.room[3] - item.room[1])
        # 下面同色、静止的空白有多高：再往下是面板边框、图片、在动的画面
        soft_h = room_h if item.soft is None else min(room_h, max(h, item.soft - item.rect[1]))
        n_orig = max(1, item.n_lines)
        base_px = max(9, min(160, round((item.em or item.line_h) * 0.74)))
        min_px = min(base_px, max(st.min_font_px, round(base_px * st.min_scale)))
        floor_px = min(min_px, max(st.min_font_px, round(base_px * 0.6)))
        orig_pitch = (h - item.line_h) / (n_orig - 1) if n_orig > 1 else item.line_h * 1.25
        font = QFont(st.font_family)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        text = " ".join(item.text.split())

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
            pitch = max(px * 1.18, min(orig_pitch, px * 1.7)) if n_orig > 1 else px * 1.25
            # 汉字实际占高约 1.0~1.1 个字号；按 1.3 倍留量会让矮检测框（没有下伸字母的行）的译文被无谓缩小
            need = (len(spans) - 1) * pitch + _tail(text, spans, px, font)
            return (px, spans, pitch, h, False, sx) if need <= h + 3 else None

        def below(px: int, sx: float, width: float, split_ok: bool, limit_h: int):
            font.setPixelSize(px)
            spans = _wrap(text, font, width / sx)
            if not split_ok and _breaks_word(text, spans):
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
        if end and end in _CJK_END:
            # 识别框常常没把句末的全角标点框进去：底板往右多盖大半个字，免得旁边露出一个“。”
            plate_w = max(plate_w, w + round(item.line_h * 0.6))
        img_w, img_h = plate_w + 2 * PAD, max(h, used_h) + 2 * PAD
        img = QImage(img_w, img_h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bg = QColor(*item.bg)
        bg.setAlphaF(st.plate_opacity)
        p.fillRect(QRectF(0, 0, img_w, img_h), bg)
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
        for i, (start, length) in enumerate(spans):
            line = text[start:start + length].rstrip()
            if truncated and i == len(spans) - 1:
                line = fm.elidedText(line + "……", Qt.TextElideMode.ElideRight, plate_w / sx)
                if not line.endswith("…"):
                    line = line[:-1] + "…"
            y = top + i * pitch + fm.ascent()
            if sx < 1.0:
                p.save()
                p.translate(PAD, y)
                p.scale(sx, 1.0)                    # 横向压扁（字高不变）
                p.drawText(QPointF(0, 0), line)
                p.restore()
            else:
                p.drawText(QPointF(PAD, y), line)
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
        return Rendered(img, -PAD, -PAD, img_w, img_h, truncated, px, sx)
