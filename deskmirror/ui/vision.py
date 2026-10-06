"""看图翻译的结果窗口：截下的画面缩略图 + 模型一段段返回的译文，可复制、重看。

只在内存里；关掉窗口就取消还没完成的请求。窗口对截屏隐身，不会被自己识别进去。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .. import winapi


class VisionPanel(QWidget):
    retry_requested = Signal()
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("桌面魔镜 · 看图翻译")
        self.resize(560, 640)
        lay = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setMinimumHeight(120)
        lay.addWidget(self.thumb)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        copy_btn = QPushButton("复制译文")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText()))
        row.addWidget(copy_btn)
        self.retry = QPushButton("重新看一次")
        self.retry.clicked.connect(self.retry_requested.emit)
        row.addWidget(self.retry)
        row.addStretch(1)
        lay.addLayout(row)
        note = QLabel("把魔镜框里的画面交给能看图的模型来读、来翻：适合漫画、艺术字、图片里的字。"
                      "比实时翻译慢，结果只在这个窗口里，不存盘。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)
        self.running = False
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))

    def start(self, image: QImage, who: str) -> None:
        """开始一次：显示缩略图，清空上次的结果。who 是给用户看的“发给了谁”。"""
        self.running = True
        self.retry.setEnabled(False)
        self.text.clear()
        self.thumb.setPixmap(QPixmap.fromImage(image).scaled(
            520, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.status.setText(f"正在看图…（{who}，通常几秒到十几秒）")
        self.show()
        self.raise_()

    def append(self, piece: str) -> None:
        cur = self.text.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(piece)
        self.text.setTextCursor(cur)

    def finish(self, error: str, secs: float) -> None:
        self.running = False
        self.retry.setEnabled(True)
        if error:
            self.status.setText(f"没看成：{error}")
        else:
            self.status.setText(f"完成，用时 {secs:.1f} 秒。")

    def closeEvent(self, ev) -> None:  # noqa: N802
        if self.running:
            self.cancel_requested.emit()
        super().closeEvent(ev)
