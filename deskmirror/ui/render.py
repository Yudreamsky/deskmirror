"""把一块译文排版成图片：在原文字块位置画底板遮住原文，再写译文。

排版只取决于文字块本身（位置、行高、可向下延伸的空间），与魔镜位置无关：
拖动或缩放魔镜只改变裁剪，不会重新排版；同一 (bid, version) 只排一次。

放不下时依次：缩小字号（不小于原字号的 min_scale 且不小于 min_font_px）→ 向下占用
下方空白（不超过相邻文字块）→ 仍放不下就截断并在末尾标“…”，鼠标停留时显示全文。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QTextLayout, QTextOption

from ..config import StyleConfig
from ..scene import DrawItem

PAD = 2


@dataclass
class Rendered:
    image: QImage
    dx: int                  # 图片左上角相对原文字块左上角的偏移
    dy: int
    width: int
    height: int
    truncated: bool
    font_px: int


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


class Renderer:
    def __init__(self, style: StyleConfig) -> None:
        self.style = style
        self._cache: dict[int, tuple[int, tuple, Rendered]] = {}

    def set_style(self, style: StyleConfig) -> None:
        self.style = style
        self._cache.clear()

    def get(self, item: DrawItem) -> Rendered:
        sig = (item.rect[2] - item.rect[0], item.rect[3] - item.rect[1], item.room[3] - item.room[1])
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
        room_h = max(h, item.room[3] - item.room[1])
        n_orig = max(1, item.n_lines)
        base_px = max(9, min(160, round((item.em or item.line_h) * 0.74)))
        min_px = min(base_px, max(st.min_font_px, round(base_px * st.min_scale)))
        orig_pitch = (h - item.line_h) / (n_orig - 1) if n_orig > 1 else item.line_h * 1.25
        font = QFont(st.font_family)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        text = " ".join(item.text.split())
        chosen = None
        for px in range(base_px, min_px - 1, -1):
            font.setPixelSize(px)
            spans = _wrap(text, font, w)
            pitch = max(px * 1.18, min(orig_pitch, px * 1.7)) if n_orig > 1 else px * 1.25
            # 汉字实际占高约 1.0~1.1 个字号；按 1.3 倍留量会让矮检测框（没有下伸字母的行）的译文被无谓缩小
            need = (len(spans) - 1) * pitch + px * 1.08
            if need <= h + 3:
                chosen = (px, spans, pitch, h, False)
                break
        if chosen is None:
            for px in range(base_px, min_px - 1, -1):
                font.setPixelSize(px)
                spans = _wrap(text, font, w)
                pitch = px * 1.18
                need = (len(spans) - 1) * pitch + px * 1.15
                if need <= room_h + 2:
                    chosen = (px, spans, pitch, int(need + 0.999), False)
                    break
        if chosen is None:
            px = min_px
            font.setPixelSize(px)
            spans = _wrap(text, font, w)
            pitch = px * 1.18
            max_lines = max(1, int((room_h - px * 1.15) // pitch) + 1)
            chosen = (px, spans[:max_lines], pitch, room_h, len(spans) > max_lines)
        px, spans, pitch, used_h, truncated = chosen
        font.setPixelSize(px)
        fm = QFontMetricsF(font)
        img_w, img_h = w + 2 * PAD, max(h, used_h) + 2 * PAD
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
        if len(spans) == 1:
            top = PAD + max(0.0, (max(h, used_h) - fm.height()) / 2)
        else:
            top = PAD + max(0.0, (item.line_h - fm.height()) / 2)
        for i, (start, length) in enumerate(spans):
            line = text[start:start + length].rstrip()
            if truncated and i == len(spans) - 1:
                line = fm.elidedText(line + "……", Qt.TextElideMode.ElideRight, w)
                if not line.endswith("…"):
                    line = line[:-1] + "…"
            y = top + i * pitch + fm.ascent()
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
        return Rendered(img, -PAD, -PAD, img_w, img_h, truncated, px)
