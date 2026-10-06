"""设置窗口：翻译服务（地址、模型、密钥、连接测试）、翻译范围与隐私、识别与显示、快捷键。"""
from __future__ import annotations

import copy
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import winapi
from .about import AboutPage
from ..config import (DEFAULT_EXCLUDE_APPS, DEFAULT_EXCLUDE_TITLES, LANGUAGES, OPENAI_PRESETS, SCOPE_MODES,
                      SOURCE_LANGS, AppConfig)
from ..translator import list_models, test_connection


class _Relay(QObject):
    done = Signal(object, object)


def _lines(edit: QPlainTextEdit) -> list[str]:
    return [x.strip() for x in edit.toPlainText().replace("，", "\n").replace(",", "\n").splitlines() if x.strip()]


class SettingsDialog(QDialog):
    guide_requested = Signal()      # “关于”页上的“打开新手指南”
    def __init__(self, cfg: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("桌面魔镜 · 设置")
        self.cfg = copy.deepcopy(cfg)
        self.clear_memory_requested = False
        self._relay = _Relay()
        self._relay.done.connect(self._on_async_done)
        self.setMinimumWidth(600)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self.tabs.addTab(self._service_tab(), "翻译服务")
        self.tabs.addTab(self._privacy_tab(), "范围与隐私")
        self.tabs.addTab(self._glossary_tab(), "术语表")
        self.tabs.addTab(self._general_tab(), "识别与显示")
        self.tabs.addTab(self._keys_tab(), "快捷键")
        self.tabs.addTab(self._about_tab(), "关于")

        self.restart_note = QLabel("")
        self.restart_note.setStyleSheet("color: #c80;")
        lay.addWidget(self.restart_note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))

    # ------------------------------------------------------------------ 各页
    def _service_tab(self) -> QWidget:
        page = QWidget()
        f = QFormLayout(page)
        self.protocol = QComboBox()
        self.protocol.addItem("Ollama 原生接口", "ollama")
        self.protocol.addItem("OpenAI 兼容接口（DeepSeek、通义、硅基流动、LM Studio…）", "openai")
        self.protocol.setCurrentIndex(0 if self.cfg.llm.protocol == "ollama" else 1)
        f.addRow("接入方式", self.protocol)
        self.preset = QComboBox()
        self.preset.addItem("（常用地址，选一个自动填入）", None)
        for name, (url, model) in OPENAI_PRESETS.items():
            self.preset.addItem(name, (url, model))
        self.preset.activated.connect(self._apply_preset)
        f.addRow("常用服务", self.preset)
        self.base_url = QLineEdit(self.cfg.llm.base_url)
        f.addRow("服务地址", self.base_url)
        mrow = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setCurrentText(self.cfg.llm.model)
        self.model.setMinimumWidth(260)
        mrow.addWidget(self.model, 1)
        self.fetch = QPushButton("获取模型列表")
        self.fetch.clicked.connect(self._fetch_models)
        mrow.addWidget(self.fetch)
        f.addRow("模型", mrow)
        self.api_key = QLineEdit(self.cfg.llm.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("本地 Ollama 不需要；云端服务填这里。只用 Windows 账户加密保存在本机")
        f.addRow("API Key", self.api_key)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(self.cfg.llm.concurrency)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(5, 300)
        self.timeout.setValue(self.cfg.llm.timeout_s)
        self.timeout.setSuffix(" 秒")
        crow = QHBoxLayout()
        crow.addWidget(QLabel("同时请求"))
        crow.addWidget(self.concurrency)
        crow.addSpacing(16)
        crow.addWidget(QLabel("超时"))
        crow.addWidget(self.timeout)
        crow.addStretch(1)
        f.addRow("并发与超时", crow)
        trow = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test)
        trow.addWidget(self.test_btn)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        trow.addWidget(self.test_result, 1)
        f.addRow("", trow)
        note = QLabel("提示：用云端服务时，屏幕上识别出的文字和所在窗口的标题会发送给该服务。"
                      "哪些内容会被翻译，见“范围与隐私”。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        f.addRow("", note)
        vg = QGroupBox("看图翻译（要能看图的多模态模型）")
        vf = QFormLayout(vg)
        self.v_protocol = QComboBox()
        self.v_protocol.addItem("Ollama 原生接口", "ollama")
        self.v_protocol.addItem("OpenAI 兼容接口", "openai")
        self.v_protocol.setCurrentIndex(0 if self.cfg.vision.protocol == "ollama" else 1)
        vf.addRow("接入方式", self.v_protocol)
        self.v_base = QLineEdit(self.cfg.vision.base_url)
        vf.addRow("服务地址", self.v_base)
        self.v_model = QLineEdit(self.cfg.vision.model)
        vf.addRow("模型", self.v_model)
        self.v_key = QLineEdit(self.cfg.vision.api_key)
        self.v_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.v_key.setPlaceholderText("本机 Ollama 不需要；只用 Windows 账户加密保存在本机")
        vf.addRow("API Key", self.v_key)
        vnote = QLabel("按 Ctrl+Alt+V 或点魔镜标签上的“看图”，把镜框里的画面交给这里的模型来读、来翻，"
                       "适合漫画、艺术字、图片里的字。默认用本机 Ollama 的 gemma4:12b，画面不出本机；"
                       "发给云端服务前，每次都会先问你。")
        vnote.setWordWrap(True)
        vnote.setStyleSheet("color: #888;")
        vf.addRow(vnote)
        f.addRow(vg)
        return page

    def _privacy_tab(self) -> QWidget:
        page = QWidget()
        f = QFormLayout(page)
        self.scope_mode = QComboBox()
        for code, name in SCOPE_MODES.items():
            self.scope_mode.addItem(name, code)
        self.scope_mode.setCurrentIndex(list(SCOPE_MODES).index(self.cfg.scope.mode))
        f.addRow("预译范围", self.scope_mode)
        self.near_px = QSpinBox()
        self.near_px.setRange(100, 3000)
        self.near_px.setSingleStep(80)
        self.near_px.setValue(self.cfg.scope.near_px)
        self.near_px.setSuffix(" 像素")
        f.addRow("“镜框附近”指镜框外", self.near_px)
        scope_note = QLabel("“整块屏幕”：魔镜所在屏幕上看得见的文字都在后台预先翻译，拖到哪里都能立刻看到译文，"
                            "但别的窗口里的文字也会发给翻译服务。另外两种只翻魔镜所在的窗口或镜框附近，"
                            "其余等魔镜移过去再翻，更省、也更不容易把无关内容发出去。")
        scope_note.setWordWrap(True)
        scope_note.setStyleSheet("color: #888;")
        f.addRow("", scope_note)
        self.ex_apps = QPlainTextEdit("\n".join(self.cfg.scope.exclude_apps))
        self.ex_apps.setMinimumHeight(110)
        f.addRow("不翻译的程序\n（每行一个程序名）", self.ex_apps)
        self.ex_titles = QPlainTextEdit("\n".join(self.cfg.scope.exclude_titles))
        self.ex_titles.setMinimumHeight(90)
        f.addRow("窗口标题含这些词\n时不翻译（每行一个）", self.ex_titles)
        reset = QPushButton("恢复默认名单（聊天软件、密码管理器、网银和支付页面）")
        reset.clicked.connect(self._reset_lists)
        f.addRow("", reset)
        ex_note = QLabel("名单里的窗口在送去识别之前就被遮掉：不识别、不翻译，不会发给任何翻译服务。"
                         "也可以右键托盘图标 →“不翻译魔镜下的这个程序”。")
        ex_note.setWordWrap(True)
        ex_note.setStyleSheet("color: #888;")
        f.addRow("", ex_note)
        self.memory_on = QCheckBox("记住译文：加密保存在本机，下次遇到相同的文字直接用（默认关闭）")
        self.memory_on.setChecked(self.cfg.memory.enabled)
        mrow = QHBoxLayout()
        mrow.addWidget(self.memory_on, 1)
        self.memory_clear = QPushButton("清空记住的译文")
        self.memory_clear.clicked.connect(self._clear_memory)
        mrow.addWidget(self.memory_clear)
        f.addRow("译文记忆", mrow)
        mem_note = QLabel("会把屏幕上识别出的原文和译文存进本机文件（只有当前 Windows 账户能解开）。"
                          "只有数字不同的文字（计时器、进度、血量）不管开不开，都会套用已有译文、不再请求翻译。")
        mem_note.setWordWrap(True)
        mem_note.setStyleSheet("color: #888;")
        f.addRow("", mem_note)
        u = self.cfg.usage
        self.usage_label = QLabel(f"今天（{u.date or '—'}）发给翻译服务 {u.requests} 次请求、{u.chars} 字"
                                  "（只统计数量，不记录内容）")
        f.addRow("用量", self.usage_label)
        return page

    def _glossary_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        note = QLabel("人名、地名、游戏里的专有名词：在这里写好译法，翻译时必须照用（不分大小写）。"
                      "译法和原文一样表示保持不译。“只用于程序”填程序名（如 game.exe），空着表示所有程序都用。"
                      "改了术语表后，含这些词的已有译文会重新翻译。")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.gloss = QTableWidget(0, 3)
        self.gloss.setHorizontalHeaderLabels(["原文里的词", "译法", "只用于程序（可空）"])
        self.gloss.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for g in self.cfg.glossary:
            self._add_term(g.get("src", ""), g.get("dst", ""), g.get("app", ""))
        lay.addWidget(self.gloss, 1)
        self.consistency = QCheckBox("保持术语前后一致（推荐）")
        self.consistency.setChecked(self.cfg.llm.consistency)
        lay.addWidget(self.consistency)
        cnote = QLabel("翻译时附上这个窗口里含同样词语的已有译文作参考，没写进术语表的词也沿用同样的译法。"
                       "发给翻译服务的文字会多一些（实测约多 15%）。")
        cnote.setWordWrap(True)
        cnote.setStyleSheet("color: #888;")
        lay.addWidget(cnote)
        row = QHBoxLayout()
        add = QPushButton("添加一行")
        add.clicked.connect(lambda: self._add_term("", "", ""))
        rm = QPushButton("删除所选行")
        rm.clicked.connect(self._remove_terms)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        lay.addLayout(row)
        return page

    def _add_term(self, src: str, dst: str, app: str) -> None:
        r = self.gloss.rowCount()
        self.gloss.insertRow(r)
        for c, v in enumerate((src, dst, app)):
            self.gloss.setItem(r, c, QTableWidgetItem(v))

    def _remove_terms(self) -> None:
        for r in sorted({i.row() for i in self.gloss.selectedIndexes()}, reverse=True):
            self.gloss.removeRow(r)

    def _general_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        gen = QGroupBox("翻译与识别")
        g = QFormLayout(gen)
        self.source = QComboBox()
        for code, name in SOURCE_LANGS.items():
            self.source.addItem(name, code)
        self.source.setCurrentIndex(max(0, self.source.findData(self.cfg.source_lang)))
        g.addRow("原文", self.source)
        self.target = QComboBox()
        for code, name in LANGUAGES.items():
            self.target.addItem(name, code)
        self.target.setCurrentIndex(list(LANGUAGES).index(self.cfg.target_lang))
        g.addRow("译成", self.target)
        self.device = QComboBox()
        self.device.addItem("显卡（DirectML，快）", "gpu")
        self.device.addItem("CPU（玩游戏时不和游戏抢显卡）", "cpu")
        self.device.setCurrentIndex(0 if self.cfg.ocr.device == "gpu" else 1)
        g.addRow("文字识别", self.device)
        self.all_monitors = QCheckBox("处理所有屏幕（默认只处理魔镜所在的屏幕，更快、更省资源）")
        self.all_monitors.setChecked(self.cfg.track.all_monitors)
        g.addRow("屏幕范围", self.all_monitors)
        self.wheel_predict = QCheckBox("用滚轮学习滚动曲线，让译文和原文同步起步（以画面核对为准）")
        self.wheel_predict.setChecked(self.cfg.track.wheel_predict)
        g.addRow("滚动跟随", self.wheel_predict)
        lay.addWidget(gen)
        look = QGroupBox("显示")
        lf = QFormLayout(look)
        self.min_font = QSpinBox()
        self.min_font.setRange(8, 32)
        self.min_font.setValue(self.cfg.style.min_font_px)
        self.min_font.setSuffix(" 像素")
        lf.addRow("最小字号", self.min_font)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.3, 1.0)
        self.opacity.setSingleStep(0.05)
        self.opacity.setValue(self.cfg.style.plate_opacity)
        lf.addRow("底板不透明度", self.opacity)
        lay.addWidget(look)
        lay.addStretch(1)
        return page

    def _keys_tab(self) -> QWidget:
        page = QWidget()
        kf = QFormLayout(page)
        self.k_drag = QLineEdit(self.cfg.hotkeys.drag_modifiers)
        kf.addRow("按住后在镜内拖动", self.k_drag)
        self.k_peek = QLineEdit(self.cfg.hotkeys.peek)
        kf.addRow("按住显示原文", self.k_peek)
        self.k_refresh = QLineEdit(self.cfg.hotkeys.refresh)
        kf.addRow("刷新镜框内区域", self.k_refresh)
        self.k_toggle = QLineEdit(self.cfg.hotkeys.toggle_visible)
        kf.addRow("隐藏 / 显示魔镜", self.k_toggle)
        self.k_history = QLineEdit(self.cfg.hotkeys.history)
        kf.addRow("历史面板", self.k_history)
        self.k_vision = QLineEdit(self.cfg.hotkeys.vision)
        kf.addRow("看图翻译", self.k_vision)
        return page

    def _about_tab(self) -> QWidget:
        page = AboutPage()
        page.guide_requested.connect(self.guide_requested.emit)
        return page

    # ------------------------------------------------------------------ 动作
    def _apply_preset(self, idx: int) -> None:
        data = self.preset.itemData(idx)
        if not data:
            return
        url, model = data
        self.protocol.setCurrentIndex(1)
        self.base_url.setText(url)
        if model:
            self.model.setCurrentText(model)

    def _clear_memory(self) -> None:
        self.clear_memory_requested = True
        self.memory_clear.setText("已清空（保存后生效）")
        self.memory_clear.setEnabled(False)

    def _reset_lists(self) -> None:
        self.ex_apps.setPlainText("\n".join(DEFAULT_EXCLUDE_APPS))
        self.ex_titles.setPlainText("\n".join(DEFAULT_EXCLUDE_TITLES))

    def collect(self) -> AppConfig:
        c = self.cfg
        c.llm.protocol = self.protocol.currentData()
        c.llm.base_url = self.base_url.text().strip()
        c.llm.model = self.model.currentText().strip()
        c.llm.api_key = self.api_key.text().strip()
        c.llm.concurrency = self.concurrency.value()
        c.llm.timeout_s = float(self.timeout.value())
        c.scope.mode = self.scope_mode.currentData()
        c.scope.near_px = self.near_px.value()
        c.scope.exclude_apps = _lines(self.ex_apps)
        c.scope.exclude_titles = _lines(self.ex_titles)
        c.memory.enabled = self.memory_on.isChecked()
        terms = []
        for r in range(self.gloss.rowCount()):
            vals = [(self.gloss.item(r, k).text().strip() if self.gloss.item(r, k) else "") for k in range(3)]
            if vals[0] and vals[1]:
                terms.append({"src": vals[0], "dst": vals[1], "app": vals[2]})
        c.glossary = terms
        c.llm.consistency = self.consistency.isChecked()
        c.target_lang = self.target.currentData()
        c.ocr.device = self.device.currentData()
        c.source_lang = self.source.currentData()
        c.track.all_monitors = self.all_monitors.isChecked()
        c.track.wheel_predict = self.wheel_predict.isChecked()
        c.style.min_font_px = self.min_font.value()
        c.style.plate_opacity = float(self.opacity.value())
        c.hotkeys.drag_modifiers = self.k_drag.text().strip()
        c.hotkeys.peek = self.k_peek.text().strip()
        c.hotkeys.refresh = self.k_refresh.text().strip()
        c.hotkeys.toggle_visible = self.k_toggle.text().strip()
        c.hotkeys.history = self.k_history.text().strip()
        c.hotkeys.vision = self.k_vision.text().strip()
        c.vision.protocol = self.v_protocol.currentData()
        c.vision.base_url = self.v_base.text().strip()
        c.vision.model = self.v_model.text().strip()
        c.vision.api_key = self.v_key.text().strip()
        return copy.deepcopy(c)

    def _run_async(self, tag: str, fn) -> None:
        def work():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                res = e
            self._relay.done.emit(tag, res)
        threading.Thread(target=work, daemon=True).start()

    def _test(self) -> None:
        cfg = self.collect()
        self.test_btn.setEnabled(False)
        self.test_result.setText("正在测试…（本地模型第一次加载可能要十几秒）")
        self._run_async("test", lambda: test_connection(cfg.llm, cfg.target_lang))

    def _fetch_models(self) -> None:
        cfg = self.collect()
        self.fetch.setEnabled(False)
        self.test_result.setText("正在获取模型列表…")
        self._run_async("models", lambda: list_models(cfg.llm))

    def _on_async_done(self, tag: str, res) -> None:
        if tag == "test":
            self.test_btn.setEnabled(True)
            if isinstance(res, Exception):
                self.test_result.setText(f"测试出错：{type(res).__name__}")
            else:
                ok, msg = res
                self.test_result.setText(("✅ " if ok else "❌ ") + msg)
        elif tag == "models":
            self.fetch.setEnabled(True)
            names, err = res if isinstance(res, tuple) else ([], f"出错了（{type(res).__name__}）")
            if names:
                cur = self.model.currentText().strip()
                self.model.clear()
                self.model.addItems(names)
                self.model.setCurrentText(cur)
                msg = f"取到 {len(names)} 个模型，已列在下拉框里，点一个即可"
                if cur and cur not in names:
                    msg += f"；当前填的“{cur}”不在列表里，可能填错了"
                self.test_result.setText(msg)
                self.model.showPopup()       # 直接展开，免得看起来像没反应
            else:
                self.test_result.setText(f"没取到模型列表：{err}。也可以直接手填模型名")
