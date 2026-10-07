"""录制（调试用）：把用户此刻看到的画面——屏幕 + 译文 + 魔镜边框——按固定帧率录成视频，做演示、宣传片的实录素材。

普通录屏软件录不到魔镜：魔镜和译文层对截屏隐身（不然程序会把自己的译文又识别一遍）。这里在程序里自己合成：
背景直接用引擎已经截好的屏幕画面（DXGI，拿着截屏的锁复制那一块，不再另外截屏），再把译文层、魔镜边框、
打开着的窗口画上去，交给 ffmpeg 用显卡编码（单独的线程写管道，不卡界面）。
赶不上的帧用上一帧补上，保证视频时长和真实时间一致；补了多少帧会如实报告。
只能通过调试通道（DESKMIRROR_DEBUG_PORT）使用。
"""
from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import threading
import time
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from . import geom
from .geom import Rect
from .ui import layered

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000


def encoder_args(codec: str, quality: int) -> list[str]:
    if codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(quality), "-pix_fmt", "yuv420p"]


class Recorder(QObject):
    def __init__(self, path: str, region: Rect, fps: int, background: Callable[[Rect], np.ndarray],
                 layers: Callable[[], list], codec: str = "h264_nvenc", quality: int = 14, parent=None) -> None:
        super().__init__(parent)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found")
        self.path, self.region, self.fps = path, region, fps
        self.w, self.h = region[2] - region[0], region[3] - region[1]
        self.background, self.layers = background, layers
        self.cursor: tuple[int, int] | None = None          # 屏幕坐标；None = 不画鼠标
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{self.w}x{self.h}",
               "-r", str(fps), "-i", "-", *encoder_args(codec, quality), "-movflags", "+faststart", path]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        self.q: queue.Queue = queue.Queue(maxsize=30)
        self.writer = threading.Thread(target=self._write, name="recorder", daemon=True)
        self.writer.start()
        self.compose_ms: list[float] = []
        self.dups = 0
        self.last = -1
        self.t0 = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(3)                           # 勤看表：到了下一帧的时刻就合成一帧
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self) -> None:
        n = int((time.perf_counter() - self.t0) * self.fps)
        if n <= self.last:
            return
        t = time.perf_counter()
        frame = self._compose()
        self.compose_ms.append((time.perf_counter() - t) * 1000)
        k = n - self.last
        self.dups += k - 1
        self.last = n
        for _ in range(k):
            self.q.put(frame)

    def _compose(self) -> np.ndarray:
        l, t, r, b = self.region
        bg = self.background(self.region)
        img = QImage(bg.data, self.w, self.h, self.w * 4, QImage.Format.Format_RGB32)
        p = QPainter(img)
        for w in self.layers():
            g = w.geometry()
            wr = (g.x(), g.y(), g.x() + g.width(), g.y() + g.height())
            c = geom.inter(wr, self.region)
            if geom.empty(c):
                continue
            # 译文层、魔镜边框是透明窗口：先画到透明图上再叠，别把底下的画面擦掉
            p.drawPixmap(c[0] - l, c[1] - t, layered.grab(w, QRect(c[0] - wr[0], c[1] - wr[1], c[2] - c[0],
                                                                    c[3] - c[1])))
        if self.cursor is not None:
            self._paint_cursor(p, self.cursor[0] - l, self.cursor[1] - t)
        p.end()
        return bg

    @staticmethod
    def _paint_cursor(p: QPainter, x: float, y: float) -> None:
        path = QPainterPath(QPointF(x, y))
        for dx, dy in ((0, 34), (8, 26), (14, 40), (20, 37), (14, 24), (25, 24)):
            path.lineTo(x + dx, y + dy)
        path.closeSubpath()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(20, 20, 24), 2.4))
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(path)

    def _write(self) -> None:
        stdin = self.proc.stdin
        while True:
            fr = self.q.get()
            if fr is None:
                break
            try:
                stdin.write(memoryview(fr))
            except (BrokenPipeError, OSError):
                log.warning("录制：ffmpeg 已退出")
                break
        try:
            stdin.close()
        except OSError:
            pass

    def stop(self) -> dict:
        self.timer.stop()
        self.q.put(None)
        self.writer.join(30)
        code = self.proc.wait(60)
        ms = sorted(self.compose_ms) or [0.0]
        frames = self.last + 1
        return {"path": self.path, "ok": code == 0, "frames": frames, "seconds": round(frames / self.fps, 2),
                "duplicated": self.dups, "compose_ms": {"p50": round(ms[len(ms) // 2], 1),
                                                        "p95": round(ms[int(len(ms) * 0.95)], 1),
                                                        "max": round(ms[-1], 1)}}
