"""原位翻译一张截图：识别（排除名单里的窗口先涂掉）→ 翻译（经引擎：缓存里有的直接用，用量照记、上限照管）
→ 用魔镜同一套排版画上底板和译文，一段一段地出来。截图界面和贴图都用它。"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QImage, QPainter

from .. import snap, textutil
from ..geom import Rect
from ..i18n import tr
from ..scene import DrawItem
from .render import Renderer

log = logging.getLogger(__name__)


def qimage_bgr(img: QImage) -> np.ndarray:
    """QImage → numpy BGR（高, 宽, 3）。"""
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return np.ascontiguousarray(arr[:, :w * 4].reshape(h, w, 4)[:, :, :3])


class InPlace(QObject):
    updated = Signal()          # 又画上了一段译文
    status = Signal(str)        # 正在识别… / 正在翻译… / 出错的说明；"" = 好了

    def __init__(self, services, style, image: QImage, origin: tuple[int, int], hwnd: int = 0,
                 masks: list[Rect] | None = None) -> None:
        super().__init__()
        self.services = services
        self.image = image                  # 原图
        self.bgr = qimage_bgr(image)
        self.origin = origin                # 原图左上角当时在屏幕上的位置：识别结果、排除区域都是屏幕坐标
        self.hwnd = hwnd                    # 原图主要来自哪个窗口（翻译时把窗口标题当背景、按程序用术语表）
        self.masks = masks or []
        self.result: QImage | None = None
        self.blocks: list = []
        self.busy = False
        self.alive = True
        self._renderer = Renderer(style)

    def start(self) -> None:
        self.busy = True
        self.status.emit(tr("正在识别…"))
        found: list = []

        def on_ocr(kind: str, data) -> None:
            if not self.alive:
                return
            if kind == "blocks":
                found.extend(b for b in data if not b.weak and b.text.strip())
            elif kind == "error":
                self.busy = False
                self.status.emit(str(data))
            elif kind == "done":
                self._translate(found)
        self.services.ocr(snap.masked(self.bgr, self.origin, self.masks), self.origin, on_ocr)

    def cancel(self) -> None:
        self.alive = False

    def _translate(self, blocks: list) -> None:
        if not blocks:
            self.busy = False
            self.status.emit(tr("没认出字"))
            return
        self.blocks = blocks
        self.result = self.image.convertToFormat(QImage.Format.Format_RGB32)
        self.updated.emit()
        self.status.emit(tr("正在翻译…"))

        def on_tr(kind: str, data) -> None:
            if not self.alive:
                return
            if kind == "segment":
                self._draw(*data)
            elif kind == "done":
                self.busy = False
                self.status.emit("")
            elif kind == "error":
                self.busy = False
                self.status.emit(tr("翻译失败：{error}").format(error=data))
        self.services.translate([b.text for b in blocks], self.hwnd, on_tr)

    def _item(self, i: int, b, text: str) -> DrawItem:
        ox, oy = self.origin
        h, w = self.bgr.shape[:2]
        right, bottom = ox + w, oy + h
        r = b.rect
        lines = [ln.rect for ln in b.lines] or [r]
        region = self.bgr[max(0, r[1] - oy):max(0, r[3] - oy), max(0, r[0] - ox):max(0, r[2] - ox)]
        rel = [(lr[0] - r[0], lr[1] - r[1], lr[2] - r[0], lr[3] - r[1]) for lr in lines]
        bg, fg = textutil.sample_colors(region, rel) if region.size else ((255, 255, 255), (0, 0, 0))
        line_h = max(6, int(np.median([lr[3] - lr[1] for lr in lines])))
        room = [r[0], r[1], right, min(bottom, r[3] + line_h)]
        for o in self.blocks:                     # 往右、往下借地方时不盖到别的字
            q = o.rect
            if o is b:
                continue
            if q[1] < room[3] and q[3] > r[1] and q[0] >= r[2]:
                room[2] = min(room[2], q[0] - 2)
            if q[0] < r[2] and q[2] > r[0] and q[1] >= r[3]:
                room[3] = min(room[3], q[1] - 2)
        room = (room[0], room[1], max(room[2], r[2]), max(room[3], r[3]))
        return DrawItem(bid=i + 1, version=1, rect=r, room=room, clips=((ox, oy, right, bottom),), text=text, bg=bg,
                        fg=fg, line_h=line_h, n_lines=len(lines), src=b.text,
                        vertical=bool(getattr(b, "vertical", False)))

    def _draw(self, i: int, text: str) -> None:
        if self.result is None or i >= len(self.blocks):
            return
        b = self.blocks[i]
        if textutil.cache_key(text) == textutil.cache_key(b.text):
            return                                # 本来就是译成的语言：原样留着
        try:
            item = self._item(i, b, text)
            rd = self._renderer.get(item)
        except Exception:  # noqa: BLE001
            log.exception("截图译文排版出错")
            return
        p = QPainter(self.result)
        p.drawImage(QPointF(b.rect[0] - self.origin[0] + rd.dx, b.rect[1] - self.origin[1] + rd.dy), rd.image)
        p.end()
        self.updated.emit()
