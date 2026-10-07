"""Windows 10 上的透明窗口：色键窗口。

译文层和魔镜边框本来是逐像素半透明的窗口（Qt 的 WA_TranslucentBackground，系统里是 UpdateLayeredWindow 那种分层窗口）。
Windows 11 能让这种窗口对截屏隐身；Windows 10 不支持（SetWindowDisplayAffinity 报错码 8，其实不是内存不够），
截屏里就会有魔镜自己画的译文，又被当成原文识别、翻译。

这时改用色键窗口（SetLayeredWindowAttributes 那种分层窗口，Windows 10 也能隐身）：窗口先整个涂成 KEY 这个颜色，
这个颜色的像素完全透明、鼠标点击穿过去，其余像素完全不透明。所以没有半透明：译文图片按透明度二值化，底板总是不透明。
魔镜边框拆成两个窗口：看得见的边线和标签（鼠标穿透），和整体只有 1/255 不透明度、看不见但接得住鼠标的那个
（可抓取的边、标签、按住拖动键时的框内），见 mirror.py。

启动时用一个和译文层一样设置的小窗口试一下能不能隐身，决定用哪种；DESKMIRROR_COLORKEY=1 / 0 可以强制。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QWidget

from .. import winapi

log = logging.getLogger(__name__)

KEY = (255, 0, 254)          # 色键：网页、软件里几乎见不到的颜色（画出来的底板碰上了会挪开一点）
_colorkey: bool | None = None


def colorkey() -> bool:
    """这台电脑的界面要不要用色键窗口（第一次调用时试一下，要先有 QApplication）。"""
    global _colorkey
    if _colorkey is None:
        forced = os.environ.get("DESKMIRROR_COLORKEY", "")
        if forced in ("0", "1"):
            _colorkey = forced == "1"
            log.info("透明窗口：按环境变量%s色键窗口", "用" if _colorkey else "不用")
        else:
            _colorkey = not _translucent_can_hide()
            if _colorkey:
                log.info("透明窗口：这台电脑（Windows 10？）不能让半透明窗口对截屏隐身，改用色键窗口")
    return _colorkey


def _translucent_can_hide() -> bool:
    w = QWidget(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    try:
        return winapi.can_exclude(int(w.winId()))
    finally:
        w.destroy()
        w.deleteLater()


def apply(w: QWidget, alpha: int | None = None) -> None:
    """把窗口设成色键窗口。alpha=None：先完全透明，第一次画完再显示（不然刚出现时可能闪一下黑屏）；
    alpha=1：看不见但接得住鼠标。"""
    hwnd = int(w.winId())
    if alpha is None:
        winapi.set_color_key(hwnd, KEY, 0)
        w._colorkey_hidden = True
    else:
        winapi.set_color_key(hwnd, KEY, alpha)


def painted(w: QWidget) -> None:
    """窗口画完一次以后调用：从“先完全透明”换成正常的色键窗口。"""
    if getattr(w, "_colorkey_hidden", False):
        w._colorkey_hidden = False
        QTimer.singleShot(0, lambda: winapi.set_color_key(int(w.winId()), KEY))


def key_color() -> QColor:
    return QColor(*KEY)


def solid(c: QColor) -> QColor:
    """色键窗口里只能画不透明的颜色（半透明会和色键混成一圈杂色）；正好是色键的挪开一点。"""
    c = QColor(c)
    c.setAlpha(255)
    if (c.red(), c.green(), c.blue()) == KEY:
        c.setBlue(KEY[2] - 1)
    return c


def grab(w: QWidget, rect: QRect) -> QPixmap:
    """截下窗口的一块画面（截译图、录制时叠到屏幕画面上）；色键窗口里色键的地方当透明。"""
    pm = w.grab(rect)
    if _colorkey:
        pm.setMask(pm.createMaskFromColor(key_color(), Qt.MaskMode.MaskInColor))
    return pm
