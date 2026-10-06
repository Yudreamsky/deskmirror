"""历史面板：最近在魔镜里出现过的原文和译文（字幕、游戏对话一闪而过时回看用），可搜索、复制、改译文。

只在内存里，退出即清空；不写日志、不存盘。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import winapi

MAX_ENTRIES = 500


@dataclass(eq=False)
class Entry:
    t: float
    src: str
    text: str
    key: str


class HistoryPanel(QWidget):
    edit_requested = Signal(str, str, str)    # (缓存键, 原文, 新译文)：用户改了译文

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("桌面魔镜 · 历史")
        self.resize(640, 720)
        self.entries: list[Entry] = []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索原文或译文")
        self.search.textChanged.connect(self._refill)
        top.addWidget(self.search, 1)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.list.itemDoubleClicked.connect(lambda _it: self._edit())
        lay.addWidget(self.list, 1)
        btns = QHBoxLayout()
        for text, fn in (("复制译文", lambda: self._copy(False)), ("复制原文和译文", lambda: self._copy(True)),
                         ("改译文…", self._edit), ("清空", self._clear)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)
        note = QLabel("最近在魔镜里出现过的文字（最新的在上面），只保存在内存里，退出即清空。双击一条可以改译文。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))

    # ------------------------------------------------------------------ 数据
    def add(self, key: str, src: str, text: str) -> None:
        """记一条；同一段文字最近已经记过就只挪到最前面（滚动来回、字幕重复不会刷屏）。

        面板开着时逐条插到列表顶上，不整表重建：用户正选着的条目、正在看的位置都不变。"""
        for i, e in enumerate(self.entries[:30]):
            if e.key == key and e.text == text:
                e.t = time.time()
                if i:
                    self.entries.insert(0, self.entries.pop(i))
                if self.isVisible():
                    self._to_top(e)
                return
        e = Entry(time.time(), src, text, key)
        self.entries.insert(0, e)
        dropped = self.entries[MAX_ENTRIES:]
        del self.entries[MAX_ENTRIES:]
        if self.isVisible():
            if self._matches(e, self._query()):
                self._insert_top(self._item(e))
            gone = set(map(id, dropped))
            while self.list.count() and id(self._entry(self.list.count() - 1)) in gone:
                self.list.takeItem(self.list.count() - 1)

    def update_text(self, key: str, text: str) -> None:
        for e in self.entries:
            if e.key == key:
                e.text = text
        if self.isVisible():
            for row in range(self.list.count()):
                e = self._entry(row)
                if e.key == key:
                    self.list.item(row).setText(self._label(e))

    # ------------------------------------------------------------------ 界面
    def _query(self) -> str:
        return self.search.text().strip().lower()

    def _matches(self, e: Entry, q: str) -> bool:
        return not q or q in e.src.lower() or q in e.text.lower()

    @staticmethod
    def _label(e: Entry) -> str:
        return f"{e.text}\n    {e.src}\n    {time.strftime('%H:%M:%S', time.localtime(e.t))}"

    def _item(self, e: Entry) -> QListWidgetItem:
        it = QListWidgetItem(self._label(e))
        it.setData(Qt.ItemDataRole.UserRole, e)
        return it

    def _entry(self, row: int) -> Entry:
        return self.list.item(row).data(Qt.ItemDataRole.UserRole)

    def _insert_top(self, it: QListWidgetItem, row_was: int | None = None) -> None:
        """插到最上面；用户往下翻着看旧条目时，眼前这一屏不动。"""
        sb = self.list.verticalScrollBar()
        v = sb.value()
        self.list.insertItem(0, it)
        if v > 0 and (row_was is None or row_was >= v):
            sb.setValue(v + 1)

    def _to_top(self, e: Entry) -> None:
        for row in range(self.list.count()):
            if self._entry(row) is e:
                it = self.list.item(row)
                it.setText(self._label(e))
                if row:
                    sel = it.isSelected()
                    self.list.takeItem(row)
                    self._insert_top(it, row)
                    it.setSelected(sel)
                return

    def _refill(self) -> None:
        q = self._query()
        self.list.clear()
        for e in self.entries:
            if self._matches(e, q):
                self.list.addItem(self._item(e))

    def showEvent(self, ev) -> None:  # noqa: N802
        self._refill()
        super().showEvent(ev)

    def _selected(self) -> list[Entry]:
        items = self.list.selectedItems() or ([self.list.item(0)] if self.list.count() else [])
        return [it.data(Qt.ItemDataRole.UserRole) for it in items if it is not None]

    def _copy(self, with_src: bool) -> None:
        es = self._selected()
        if not es:
            return
        if with_src:
            text = "\n\n".join(f"{e.src}\n{e.text}" for e in es)
        else:
            text = "\n".join(e.text for e in es)
        QGuiApplication.clipboard().setText(text)

    def _clear(self) -> None:
        self.entries.clear()
        self._refill()

    def _edit(self) -> None:
        es = self._selected()
        if not es:
            return
        e = es[0]
        dlg = EditDialog(e.src, e.text, self)
        if dlg.exec():
            new = dlg.value()
            if new and new != e.text:
                self.edit_requested.emit(e.key, e.src, new)
                self.update_text(e.key, new)


class EditDialog(QDialog):
    """改一段译文：改完后这段文字（以后再出现也一样）都用新译文。"""

    def __init__(self, src: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("改译文")
        self.resize(560, 300)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("原文："))
        s = QPlainTextEdit(src)
        s.setReadOnly(True)
        s.setMaximumHeight(90)
        lay.addWidget(s)
        lay.addWidget(QLabel("译文（改完后，这段文字以后再出现也用这个译文）："))
        self.edit = QPlainTextEdit(text)
        lay.addWidget(self.edit, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))

    def value(self) -> str:
        return self.edit.toPlainText().strip()
