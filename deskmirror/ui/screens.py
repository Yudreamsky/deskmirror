"""Qt 的屏幕（QScreen）和 Windows 的显示器（winapi.Monitor）对上号。

QScreen.name() 有的是“\\\\.\\DISPLAY1”，有的是显示器型号（“MSI MAG323UPF”），不能按名字对；Qt 6 里每块屏幕的左上角
用的是 Windows 的原始坐标（只有大小按缩放比例换算），按左上角对，对不上再按名字。
"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication

from .. import geom, winapi


def qscreen_for(mon: winapi.Monitor):
    screens = QGuiApplication.screens()
    for s in screens:
        g = s.geometry()
        if (g.x(), g.y()) == (mon.rect[0], mon.rect[1]):
            return s
    for s in screens:
        if s.name() == mon.device:
            return s
    return None


def screen_at(x: int, y: int):
    """屏幕物理坐标 → (QScreen, 那块屏幕的 winapi.Monitor, 缩放比例：物理像素 / Qt 的逻辑像素)。"""
    mons = winapi.monitors()
    mon = next((m for m in mons if geom.contains_pt(m.rect, x, y)), mons[0])
    scr = qscreen_for(mon) or QGuiApplication.primaryScreen()
    return scr, mon, (mon.rect[2] - mon.rect[0]) / max(1, scr.geometry().width())
