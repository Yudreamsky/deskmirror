"""贴图（hotkeys.pin，默认 Ctrl+2；截图工具栏上的“贴到屏幕”）：一张图钉在屏幕最上层。

拖动挪位置；滚轮缩放；Ctrl+滚轮调透明度；双击或 Esc 关掉；右键：复制、保存、原位翻译 / 显示原文、识别文字、
原始大小、关闭、关闭所有贴图。贴图截屏截得到（共享屏幕、录屏时别人也看得到），只放在内存里，退出就没了。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QTextDocument
from PySide6.QtWidgets import QMenu, QWidget

from ..geom import Rect
from ..i18n import tr
from .intrans import InPlace, qimage_bgr
from .screens import screen_at
from .snip import PinData

BORDER = QColor(61, 139, 253, 190)


def to_logical(x: int, y: int) -> tuple[QPoint, float]:
    scr, mon, dpr = screen_at(x, y)
    g = scr.geometry()
    return QPoint(g.x() + int(round((x - mon.rect[0]) / dpr)), g.y() + int(round((y - mon.rect[1]) / dpr))), dpr


def text_card(text: str, scale: float = 1.0) -> QImage:
    """剪贴板里的文字贴到屏幕上：画成一张白底的卡片。"""
    doc = QTextDocument()
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(int(round(15 * scale)))
    doc.setDefaultFont(f)
    doc.setPlainText(text.strip()[:4000])
    doc.setTextWidth(560 * scale)
    w = min(560 * scale, doc.idealWidth())
    doc.setTextWidth(w)
    pad = int(round(12 * scale))
    img = QImage(int(w) + 2 * pad, int(doc.size().height()) + 2 * pad, QImage.Format.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.translate(pad, pad)
    doc.drawContents(p)
    p.end()
    return img


class PinWindow(QWidget):
    def __init__(self, pins: "Pins", data: PinData, pos: QPoint, dpr: float) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.pins = pins
        self.data = data
        self.image = data.image
        self.other = data.alt                    # 另一种样子：原文 ↔ 译文
        self.showing_tr = data.showing_translation
        self.dpr = dpr
        self.zoom = 1.0
        self._drag: QPoint | None = None
        self._inplace: InPlace | None = None
        self.setToolTip(tr("贴图：拖动挪位置，滚轮缩放，Ctrl+滚轮调透明度，双击关掉，右键更多"))
        self._fit()
        self.move(pos - QPoint(1, 1))

    def _fit(self, anchor: QPointF | None = None) -> None:
        """按缩放比例改窗口大小；anchor（窗口里的点）在屏幕上的位置不变。"""
        w = self.image.width() / self.dpr * self.zoom + 2
        h = self.image.height() / self.dpr * self.zoom + 2
        old = self.size()
        if anchor is not None and old.width() > 0:
            fx, fy = anchor.x() / old.width(), anchor.y() / old.height()
            self.setGeometry(int(round(self.x() + anchor.x() - fx * w)), int(round(self.y() + anchor.y() - fy * h)),
                             int(round(w)), int(round(h)))
        else:
            self.resize(QSize(int(round(w)), int(round(h))))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 1.0)
        p.drawImage(QRectF(1, 1, self.width() - 2, self.height() - 2), self.image)
        p.setPen(QPen(BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.close()

    def wheelEvent(self, e) -> None:
        d = e.angleDelta().y()
        if not d:
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.setWindowOpacity(max(0.2, min(1.0, self.windowOpacity() + (0.1 if d > 0 else -0.1))))
            return
        self.zoom = max(0.1, min(8.0, self.zoom * (1.1 if d > 0 else 1 / 1.1)))
        self._fit(e.position())
        self.update()

    def keyPressEvent(self, e) -> None:
        ctrl = e.modifiers() & Qt.KeyboardModifier.ControlModifier
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        elif ctrl and e.key() == Qt.Key.Key_C:
            self.copy()
        elif ctrl and e.key() == Qt.Key.Key_S:
            self.pins.save_requested.emit(self.image)
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e) -> None:
        m = QMenu(self)
        m.addAction(tr("复制"), self.copy)
        m.addAction(tr("保存"), lambda: self.pins.save_requested.emit(self.image))
        if self.other is not None:
            m.addAction(tr("显示原文") if self.showing_tr else tr("显示译文"), self.swap)
        elif self._inplace is None:
            m.addAction(tr("原位翻译"), self.translate)
        m.addAction(tr("识别文字"), self.ocr)
        m.addSeparator()
        m.addAction(tr("原始大小"), self.actual_size)
        m.addAction(tr("关闭"), self.close)
        if len(self.pins.items) > 1:
            m.addAction(tr("关闭所有贴图"), self.pins.close_all)
        m.exec(e.globalPos())

    def copy(self) -> None:
        QGuiApplication.clipboard().setImage(self.image)

    def actual_size(self) -> None:
        self.zoom = 1.0
        self._fit()
        self.update()

    def swap(self) -> None:
        if self.other is None:
            return
        self.image, self.other = self.other, self.image
        self.showing_tr = not self.showing_tr
        self._fit()
        self.update()

    def translate(self) -> None:
        """原位翻译这张贴图（截图时没翻过的）：翻好后可以在原文、译文之间换。"""
        if self.pins.services is None:
            return
        job = InPlace(self.pins.services, self.pins.style(), self.image, (self.data.rect[0], self.data.rect[1]),
                      self.data.hwnd, self.data.masks or [])
        job.updated.connect(self._on_inplace)
        job.status.connect(lambda msg: self.setToolTip(msg or tr("贴图：拖动挪位置，滚轮缩放，Ctrl+滚轮调透明度，"
                                                                 "双击关掉，右键更多")))
        self._inplace = job
        job.start()

    def _on_inplace(self) -> None:
        job = self._inplace
        if job is None or job.result is None:
            return
        if self.other is None and not self.showing_tr:
            self.other = self.image              # 第一次：原文留作另一种样子，换上译文
            self.showing_tr = True
        if self.showing_tr:
            self.image = job.result              # 一段段译好就一段段换上
        else:
            self.other = job.result
        self.update()

    def ocr(self) -> None:
        if self.pins.services is None:
            return
        found: list = []
        rect = self.data.rect

        def on_ocr(kind: str, data) -> None:
            if kind == "blocks":
                found.extend(b for b in data if b.text.strip())
            elif kind == "done" and found:
                found.sort(key=lambda b: (b.rect[1] // 12, b.rect[0]))
                self.pins.text_requested.emit("\n".join(b.text for b in found), rect)
        self.pins.services.ocr(qimage_bgr(self.image), (rect[0], rect[1]), on_ocr)

    def closeEvent(self, e) -> None:
        if self._inplace is not None:
            self._inplace.cancel()
        if self in self.pins.items:
            self.pins.items.remove(self)
        super().closeEvent(e)


class Pins(QObject):
    """所有贴图；最近几次截图也记着（剪贴板里没东西时 Ctrl+2 贴最近一次）。都只在内存里。"""
    save_requested = Signal(QImage)
    text_requested = Signal(str, object)         # 识别出的字，贴图的位置

    HISTORY = 20

    def __init__(self, services=None, style=None) -> None:
        super().__init__()
        self.services = services
        self.style = style or (lambda: None)
        self.items: list[PinWindow] = []
        self.history: list[PinData] = []

    def remember(self, data: PinData) -> None:
        self.history.append(data)
        del self.history[:-self.HISTORY]

    def pin(self, data: PinData, at: tuple[int, int] | None = None) -> PinWindow:
        x, y = at if at is not None else (data.rect[0], data.rect[1])
        pos, dpr = to_logical(x, y)
        w = PinWindow(self, data, pos, dpr)
        self.items.append(w)
        w.show()
        w.raise_()
        # 拿焦点：Esc、Ctrl+C 马上能用；也免得截图界面一关，Windows 把焦点交给别的窗口、置顶的那个盖到贴图上面
        w.activateWindow()
        return w

    def pin_clipboard(self, cursor: tuple[int, int]) -> PinWindow | None:
        """剪贴板里的图（或文字）贴在鼠标那里；剪贴板里没有就贴最近一次截图（在原来的位置）。"""
        cb = QGuiApplication.clipboard()
        md = cb.mimeData()
        _scr, _mon, dpr = screen_at(*cursor)
        if md is not None and md.hasImage():
            img = cb.image()
            if not img.isNull():
                img = img.convertToFormat(QImage.Format.Format_RGB32)
                return self.pin(PinData(img, (cursor[0], cursor[1], cursor[0] + img.width(), cursor[1] + img.height())))
        if md is not None and md.hasText() and md.text().strip():
            img = text_card(md.text(), dpr)
            return self.pin(PinData(img, (cursor[0], cursor[1], cursor[0] + img.width(), cursor[1] + img.height())))
        if self.history:
            return self.pin(self.history[-1])
        return None

    def close_all(self) -> None:
        for w in list(self.items):
            w.close()
