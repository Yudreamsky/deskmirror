"""设置窗口：左边一列分页（常用、翻译服务、翻译范围、截图、输入框翻译、快捷键、用量与省钱、隐私与记忆、术语表、
识别与显示、关于），每页太长时自己滚动，窗口不会比屏幕还高。快捷键点一下就能录（ui/keyedit.py），当场提示冲突。"""
from __future__ import annotations

import copy
import threading

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import autostart, winapi
from . import layered
from .about import AboutPage
from .icons import glyph
from .keyedit import HotkeyEdit, probe
from ..config import (DEFAULT_EXCLUDE_APPS, DEFAULT_EXCLUDE_TITLES, LANGUAGES, OPENAI_PRESETS, SCOPE_MODES,
                      SOURCE_LANGS, AppConfig, HotkeyConfig)
from ..i18n import N_, UI_LANGS, tr, ui_lang
from ..keys import normalize_hotkey, parse_modifiers
from ..translator import list_models, test_connection

# 分页：名字、标题、图标（Segoe Fluent Icons / Segoe MDL2 Assets 的字符）
PAGES = [("general", N_("常用"), 0xE80F), ("service", N_("翻译服务"), 0xE774), ("scope", N_("翻译范围"), 0xE71E),
         ("capture", N_("截图"), 0xE722), ("input", N_("输入框翻译"), 0xE70F), ("keys", N_("快捷键"), 0xE765),
         ("usage", N_("用量与省钱"), 0xE9D2), ("privacy", N_("隐私与记忆"), 0xE72E), ("glossary", N_("术语表"), 0xE82D),
         ("recog", N_("识别与显示"), 0xE7F4), ("about", N_("关于"), 0xE946)]
# 快捷键：设置名 → (说明, 只录修饰键)
HOTKEYS = {"drag_modifiers": (N_("按住后在镜内拖动"), True), "peek": (N_("按住显示原文"), False),
           "refresh": (N_("刷新镜框内区域"), False), "toggle_visible": (N_("隐藏 / 显示魔镜"), False),
           "history": (N_("历史面板"), False), "vision": (N_("看图翻译"), False),
           "input": (N_("翻译输入框（打开输入框翻译时）"), False), "capture": (N_("截图"), False),
           "pin": (N_("贴图"), False)}

_STYLE = """
QWidget#navPane { background: rgba(128, 128, 128, 0.07); }
QListWidget#nav { border: none; background: transparent; outline: 0; }
QListWidget#nav::item { padding: 7px 10px; margin: 1px 6px; border-radius: 6px; }
QListWidget#nav::item:hover { background: rgba(128, 128, 128, 0.13); }
QListWidget#nav::item:selected { background: rgba(128, 128, 128, 0.24); color: palette(text); }
QScrollArea, QWidget#page { background: transparent; }
QFrame#card { background: palette(base); border: 1px solid rgba(128, 128, 128, 0.30); border-radius: 8px; }
QLabel#title { font-size: 15pt; font-weight: 600; }
QLabel#cardTitle { font-weight: 600; }
"""


class _Relay(QObject):
    done = Signal(object, object)


def _lines(edit: QPlainTextEdit) -> list[str]:
    return [x.strip() for x in edit.toPlainText().replace("，", "\n").replace(",", "\n").splitlines() if x.strip()]


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: #888;")
    return lbl


def show_models(combo: QComboBox, res) -> str:
    """把“获取模型列表”的结果放进可编辑的模型下拉框（已填的名字不动），返回给用户看的结果。新手指南也用。"""
    names, err = res if isinstance(res, tuple) else ([], tr("出错了（{name}）").format(name=type(res).__name__))
    if not names:
        return tr("没取到模型列表：{error}。也可以直接手填模型名").format(error=err)
    cur = combo.currentText().strip()
    combo.clear()
    combo.addItems(names)
    combo.setCurrentText(cur)
    msg = tr("取到 {n} 个模型，已列在下拉框里，点一个即可").format(n=len(names))
    if cur and cur not in names:
        msg += tr("；当前填的“{model}”不在列表里，可能填错了").format(model=cur)
    combo.showPopup()       # 直接展开，免得看起来像没反应
    return msg


def _column() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    return w, lay


def _card(title: str = "") -> tuple[QFrame, QFormLayout]:
    box = QFrame()
    box.setObjectName("card")
    v = QVBoxLayout(box)
    v.setContentsMargins(16, 12, 16, 14)
    v.setSpacing(8)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        v.addWidget(t)
    f = QFormLayout()
    f.setHorizontalSpacing(14)
    f.setVerticalSpacing(9)
    f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    v.addLayout(f)
    return box, f


def _checked(text: str, on: bool, note: str = "") -> tuple[QCheckBox, QWidget]:
    """勾选框 + 下面一行小字说明（勾选框的字不会自动换行，长说明放下面）。"""
    box = QCheckBox(text)
    box.setChecked(on)
    if not note:
        return box, box
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(box)
    n = _note(note)
    n.setContentsMargins(24, 0, 0, 0)
    lay.addWidget(n)
    return box, w


class SettingsDialog(QDialog):
    guide_requested = Signal()      # “关于”页上的“打开新手指南”
    update_requested = Signal()     # “关于”页上的“检查更新”

    def __init__(self, cfg: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(tr("桌面魔镜 · 设置"))
        self.cfg = copy.deepcopy(cfg)
        self.clear_memory_requested = False
        self._relay = _Relay()
        self._relay.done.connect(self._on_async_done)
        self._keys: dict[str, list[HotkeyEdit]] = {}
        self._key_notes: dict[str, list[QLabel]] = {}
        self._probed: dict[str, bool] = {}
        self.setStyleSheet(_STYLE)
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(min(720, avail.width() - 40), min(440, avail.height() - 60))
        self.resize(min(920, avail.width() - 80), min(660, avail.height() - 80))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        pane = QWidget()
        pane.setObjectName("navPane")
        pane.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pl = QVBoxLayout(pane)
        pl.setContentsMargins(0, 12, 0, 12)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFixedWidth(190)
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pl.addWidget(self.nav)
        self.pages = QStackedWidget()
        builders = {"general": self._general_page, "service": self._service_page, "scope": self._scope_page,
                    "capture": self._capture_page, "input": self._input_page, "keys": self._keys_page,
                    "usage": self._usage_page, "privacy": self._privacy_page, "glossary": self._glossary_page,
                    "recog": self._recog_page, "about": self._about_page}
        ink = self.palette().color(QPalette.ColorRole.Text)
        self._page_keys = []
        for key, title, code in PAGES:
            it = QListWidgetItem(glyph(code, ink), tr(title))
            self.nav.addItem(it)
            self.pages.addWidget(self._scroll(tr(title), builders[key]()))
            self._page_keys.append(key)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        body.addWidget(pane)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: rgba(128, 128, 128, 0.35);")
        outer.addWidget(line)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(16, 8, 16, 12)
        self.restart_note = QLabel("")
        self.restart_note.setStyleSheet("color: #c80;")
        bottom.addWidget(self.restart_note, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText(tr("保存"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bottom.addWidget(bb)
        outer.addLayout(bottom)
        self._refresh_keys()
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))

    # ------------------------------------------------------------------ 框架
    def page_titles(self) -> list[str]:
        return [self.nav.item(i).text() for i in range(self.nav.count())]

    def show_page(self, key: str) -> None:
        if key in self._page_keys:
            self.nav.setCurrentRow(self._page_keys.index(key))

    @staticmethod
    def _scroll(title: str, content: QWidget) -> QScrollArea:
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(12)
        head = QLabel(title)
        head.setObjectName("title")
        lay.addWidget(head)
        lay.addWidget(content)
        lay.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidget(page)
        sa.viewport().setAutoFillBackground(False)
        return sa

    # ------------------------------------------------------------------ 各页
    def _general_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card(tr("语言"))
        self.source = QComboBox()
        for code, name in SOURCE_LANGS.items():
            self.source.addItem(tr(name), code)
        self.source.setCurrentIndex(max(0, self.source.findData(self.cfg.source_lang)))
        f.addRow(tr("原文"), self.source)
        self.target = QComboBox()
        for code, name in LANGUAGES.items():
            self.target.addItem(name, code)
        self.target.setCurrentIndex(list(LANGUAGES).index(self.cfg.target_lang))
        f.addRow(tr("译成"), self.target)
        self.ui_lang = QComboBox()
        for code, name in UI_LANGS.items():
            self.ui_lang.addItem(name, code)
        self.ui_lang.setCurrentIndex(max(0, self.ui_lang.findData(self.cfg.ui_lang or ui_lang())))
        f.addRow(tr("界面语言"), self.ui_lang)
        lay.addWidget(box)
        box, f = _card(tr("外观"))
        self.skin = QComboBox()
        self.skin.addItem(tr("经典"), "classic")
        self.skin.addItem(tr("液态玻璃"), "glass")
        self.skin.setCurrentIndex(max(0, self.skin.findData(self.cfg.style.skin)))
        self.skin.setToolTip(tr("液态玻璃：边框是一圈弧形的玻璃，后面的画面在边上被拉伸、弯折；"
                                "标签、球是半透明的玻璃，后面是深色画面时自动换成烟灰色"))
        f.addRow(tr("皮肤"), self.skin)
        lay.addWidget(box)
        box, f = _card(tr("启动"))
        self.autostart, row = _checked(tr("开机时自动启动"), autostart.enabled(),   # 以注册表为准（任务管理器里禁用了也算没开）
                                       tr("启动后收成球待命：点开或拖出来才开始识别、翻译。"))
        self.autostart_was = self.autostart.isChecked()
        f.addRow(row)
        self.update_check, row = _checked(tr("启动后检查有没有新版本"), self.cfg.update.auto_check,
                                          tr("一天最多一次，只访问 GitHub 取版本号，不发送屏幕内容；有新版只提示，点了才下载。"))
        f.addRow(row)
        lay.addWidget(box)
        return w

    def _service_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card(tr("翻译服务"))
        self.protocol = QComboBox()
        self.protocol.addItem(tr("Ollama 原生接口"), "ollama")
        self.protocol.addItem(tr("OpenAI 兼容接口（DeepSeek、通义、硅基流动、LM Studio…）"), "openai")
        self.protocol.setCurrentIndex(0 if self.cfg.llm.protocol == "ollama" else 1)
        f.addRow(tr("接入方式"), self.protocol)
        self.preset = QComboBox()
        self.preset.addItem(tr("（常用地址，选一个自动填入）"), None)
        for name, (url, model) in OPENAI_PRESETS.items():
            self.preset.addItem(tr(name), (url, model))
        self.preset.activated.connect(self._apply_preset)
        f.addRow(tr("常用服务"), self.preset)
        self.base_url = QLineEdit(self.cfg.llm.base_url)
        f.addRow(tr("服务地址"), self.base_url)
        mrow = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setCurrentText(self.cfg.llm.model)
        self.model.setMinimumWidth(240)
        mrow.addWidget(self.model, 1)
        self.fetch = QPushButton(tr("获取模型列表"))
        self.fetch.clicked.connect(self._fetch_models)
        mrow.addWidget(self.fetch)
        f.addRow(tr("模型"), mrow)
        self.api_key = QLineEdit(self.cfg.llm.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText(tr("本地 Ollama 不需要；云端服务填这里。只用 Windows 账户加密保存在本机"))
        f.addRow("API Key", self.api_key)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(self.cfg.llm.concurrency)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(5, 300)
        self.timeout.setValue(self.cfg.llm.timeout_s)
        self.timeout.setSuffix(tr(" 秒"))
        crow = QHBoxLayout()
        crow.addWidget(QLabel(tr("同时请求")))
        crow.addWidget(self.concurrency)
        crow.addSpacing(16)
        crow.addWidget(QLabel(tr("超时")))
        crow.addWidget(self.timeout)
        crow.addStretch(1)
        f.addRow(tr("并发与超时"), crow)
        trow = QHBoxLayout()
        self.test_btn = QPushButton(tr("测试连接"))
        self.test_btn.clicked.connect(self._test)
        trow.addWidget(self.test_btn)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        trow.addWidget(self.test_result, 1)
        f.addRow("", trow)
        f.addRow(_note(tr("用云端服务时，识别出的文字和所在窗口的标题会发给这个服务；哪些内容会翻译，见“翻译范围”。")))
        lay.addWidget(box)
        box, vf = _card(tr("看图翻译（要能看图的多模态模型）"))
        self.v_protocol = QComboBox()
        self.v_protocol.addItem(tr("Ollama 原生接口"), "ollama")
        self.v_protocol.addItem(tr("OpenAI 兼容接口"), "openai")
        self.v_protocol.setCurrentIndex(0 if self.cfg.vision.protocol == "ollama" else 1)
        vf.addRow(tr("接入方式"), self.v_protocol)
        self.v_base = QLineEdit(self.cfg.vision.base_url)
        vf.addRow(tr("服务地址"), self.v_base)
        self.v_model = QLineEdit(self.cfg.vision.model)
        vf.addRow(tr("模型"), self.v_model)
        self.v_key = QLineEdit(self.cfg.vision.api_key)
        self.v_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.v_key.setPlaceholderText(tr("本机 Ollama 不需要；只用 Windows 账户加密保存在本机"))
        vf.addRow("API Key", self.v_key)
        vf.addRow(_note(tr("按 {key} 或点魔镜标签上的“看图”，把镜框里的画面交给这里的模型来读、来翻，"
                           "适合漫画、艺术字、图片里的字。默认用本机 Ollama 的 gemma4:12b，画面不出本机；"
                           "发给云端服务前，每次都会先问你。").format(key=self.cfg.hotkeys.vision)))
        lay.addWidget(box)
        return w

    def _scope_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card(tr("预译范围"))
        self.scope_mode = QComboBox()
        for code, name in SCOPE_MODES.items():
            self.scope_mode.addItem(tr(name), code)
        self.scope_mode.setCurrentIndex(list(SCOPE_MODES).index(self.cfg.scope.mode))
        f.addRow(tr("预译范围"), self.scope_mode)
        self.near_px = QSpinBox()
        self.near_px.setRange(100, 3000)
        self.near_px.setSingleStep(80)
        self.near_px.setValue(self.cfg.scope.near_px)
        self.near_px.setSuffix(tr(" 像素"))
        f.addRow(tr("“镜框附近”指镜框外"), self.near_px)
        f.addRow(_note(tr("“整块屏幕”：魔镜所在屏幕上看得见的文字都在后台预先翻译，拖到哪里都能立刻看到译文，"
                          "但别的窗口里的文字也会发给翻译服务。另外两种只翻魔镜所在的窗口或镜框附近，"
                          "其余等魔镜移过去再翻，更省、也更不容易把无关内容发出去。")))
        lay.addWidget(box)
        box, f = _card(tr("不翻译的程序和窗口"))
        self.translate_chat, row = _checked(tr("聊天软件也翻译"), self.cfg.scope.translate_chat,
                                            tr("微信、QQ、钉钉、飞书、Telegram、WhatsApp 等；打开后聊天内容会发给翻译服务。"))
        f.addRow(row)
        self.ex_apps = QPlainTextEdit("\n".join(self.cfg.scope.exclude_apps))
        self.ex_apps.setMinimumHeight(110)
        f.addRow(tr("不翻译的程序\n（每行一个程序名）"), self.ex_apps)
        self.ex_titles = QPlainTextEdit("\n".join(self.cfg.scope.exclude_titles))
        self.ex_titles.setMinimumHeight(90)
        f.addRow(tr("窗口标题含这些词\n时不翻译（每行一个）"), self.ex_titles)
        reset = QPushButton(tr("恢复默认名单（聊天软件、密码管理器、网银和支付页面）"))
        reset.clicked.connect(self._reset_lists)
        f.addRow("", reset)
        f.addRow(_note(tr("名单里的窗口在送去识别之前就被遮掉：不识别、不翻译，不会发给任何翻译服务。"
                          "也可以右键托盘图标 →“不翻译魔镜下的这个程序”。"
                          "名单里的聊天软件只在打开“聊天软件也翻译”时照常翻（托盘菜单、右键魔镜标签也能随时开关），"
                          "密码管理器和网银、支付页面始终不翻。")))
        lay.addWidget(box)
        return w

    def _capture_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card(tr("快捷键"))
        self._key_rows(f, ["capture", "pin"])
        f.addRow(_note(tr("截图：框选屏幕上的一块，可以标注、复制、保存、贴到屏幕、原位翻译，或者直接变成魔镜。"
                          "贴图：把剪贴板里的图或文字贴在屏幕最上层，剪贴板里没有就贴最近一次截图。")))
        lay.addWidget(box)
        cap = self.cfg.capture
        box, f = _card(tr("框选"))
        self.cap_after = QComboBox()
        for code, name in (("toolbar", N_("弹出工具栏")), ("copy", N_("直接复制")), ("pin", N_("直接贴到屏幕"))):
            self.cap_after.addItem(tr(name), code)
        self.cap_after.setCurrentIndex(max(0, self.cap_after.findData(cap.after)))
        f.addRow(tr("框选完"), self.cap_after)
        self.cap_snap, row = _checked(tr("自动框住窗口、按钮、段落"), cap.snap,
                                      tr("鼠标停在哪就框住哪，滚轮换大一层或小一层；按住拖动就自己画框。"))
        f.addRow(row)
        self.cap_mag, row = _checked(tr("显示放大镜、坐标和颜色"), cap.magnifier, tr("按 C 复制光标处的颜色。"))
        f.addRow(row)
        lay.addWidget(box)
        box, f = _card(tr("保存"))
        drow = QHBoxLayout()
        self.cap_dir = QLineEdit(cap.save_dir)
        self.cap_dir.setPlaceholderText(tr("默认：“图片”里的“桌面魔镜”文件夹"))
        drow.addWidget(self.cap_dir, 1)
        pick = QPushButton(tr("选择…"))
        pick.clicked.connect(self._pick_dir)
        drow.addWidget(pick)
        f.addRow(tr("保存到"), drow)
        self.cap_format = QComboBox()
        self.cap_format.addItem("PNG", "png")
        self.cap_format.addItem("JPG", "jpg")
        self.cap_format.setCurrentIndex(max(0, self.cap_format.findData(cap.format)))
        f.addRow(tr("格式"), self.cap_format)
        f.addRow(_note(tr("点“保存”才写到这个文件夹；贴图和截图历史只放在内存里，退出就没了。"
                          "魔镜标签上的截图按钮也存到这里。")))
        lay.addWidget(box)
        return w

    def _input_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card()
        self.input_on = QCheckBox(tr("打开输入框翻译"))
        self.input_on.setChecked(self.cfg.input.enabled)
        f.addRow(self.input_on)
        f.addRow(_note(tr("在别的软件的输入框里用母语打完字，连按三次空格（或按快捷键 {key}），整个框换成下面选的语言；"
                          "再连按三次换回原文，再按又换成译文。来回换用记着的字，不再请求翻译。Ctrl+Z 能撤回。")
                       .format(key=self.cfg.hotkeys.input)))
        self.input_target = QComboBox()
        self.input_target.addItem(tr("自动：母语是英文时译成简体中文，否则译成英文"), "")
        for code, name in LANGUAGES.items():
            self.input_target.addItem(name, code)
        self.input_target.setCurrentIndex(max(0, self.input_target.findData(self.cfg.input.target)))
        f.addRow(tr("翻译成"), self.input_target)
        self.input_skip = QPlainTextEdit("\n".join(self.cfg.input.skip_apps))
        self.input_skip.setFixedHeight(110)
        f.addRow(tr("不管的程序"), self.input_skip)
        f.addRow(_note(tr("默认不管浏览器（装了桌面魔镜浏览器版的话，它在网页里也会响应三次空格，两边会各换一次）、"
                          "写代码的编辑器和命令行（连按空格很常见）。")))
        lay.addWidget(box)
        box, f = _card(tr("隐私"))
        f.addRow(_note(tr("只听空格和 Ctrl、Alt、Shift、Win 键，别的按键不看、不记。框里的字和译文只放在内存里（最近 20 对），"
                          "不写硬盘。写回去时借用剪贴板粘贴，粘完放回你原来的内容，借用的那一下不进剪贴板历史。密码框一概不碰。"
                          "读不到框里的字的软件，连按三次空格不起作用；按快捷键时会用 Ctrl+A、Ctrl+C 复制出来读"
                          "（这时你的字会进剪贴板历史）。")))
        lay.addWidget(box)
        return w

    def _keys_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card()
        self._key_rows(f, list(HOTKEYS))
        reset = QPushButton(tr("恢复默认快捷键"))
        reset.clicked.connect(self._reset_keys)
        f.addRow("", reset)
        f.addRow(_note(tr("点一下再按新的组合键（别的程序占着的也录得到，录的时候不会触发它）；Esc 取消，"
                          "Backspace 清空（不用这个快捷键）。设置窗口开着时，魔镜的快捷键暂时不起作用。")))
        lay.addWidget(box)
        return w

    def _usage_page(self) -> QWidget:
        w, lay = _column()
        u = self.cfg.usage
        box, f = _card(tr("今天"))
        self.usage_label = QLabel(tr("今天（{date}）发给翻译服务 {requests} 次请求、{chars} 字，"
                                     "输入 {tin} token、输出 {tout} token（只统计数量，不记录内容）")
                                  .format(date=u.date or "—", requests=u.requests, chars=u.chars,
                                          tin=f"{u.tokens_in:,}", tout=f"{u.tokens_out:,}"))
        self.usage_label.setWordWrap(True)
        f.addRow(self.usage_label)
        self.show_meter = QCheckBox(tr("魔镜标签上显示今天用掉的 token（↑ 输入 ↓ 输出）"))
        self.show_meter.setChecked(self.cfg.guard.show_meter)
        f.addRow(self.show_meter)
        lay.addWidget(box)
        g = self.cfg.guard
        box, f = _card(tr("省钱"))
        self.idle_min = QSpinBox()
        self.idle_min.setRange(0, 240)
        self.idle_min.setValue(g.idle_min)
        self.idle_min.setSuffix(tr(" 分钟"))
        self.idle_min.setSpecialValueText(tr("不管"))
        f.addRow(tr("没碰键盘鼠标"), self.idle_min)
        f.addRow(_note(tr("超过这么久没碰键盘鼠标，就只翻镜框里的文字，不在后台预译屏幕上别处的（动一下就恢复）。"
                          "镜框里的字幕照常翻译，看视频不受影响。")))
        self.pause_locked = QCheckBox(tr("锁屏、屏保时完全停下（不截屏、不识别、不翻译）"))
        self.pause_locked.setChecked(g.pause_when_locked)
        f.addRow(self.pause_locked)
        self.daily_tokens = QSpinBox()
        self.daily_tokens.setRange(0, 2_000_000_000)
        self.daily_tokens.setSingleStep(100_000)
        self.daily_tokens.setGroupSeparatorShown(True)
        self.daily_tokens.setValue(g.daily_tokens)
        self.daily_tokens.setSuffix(" token")
        self.daily_tokens.setSpecialValueText(tr("不限"))
        f.addRow(tr("每天最多用"), self.daily_tokens)
        f.addRow(_note(tr("只限云端服务（本机 Ollama 不花钱、不限）：今天发出去和收回来的 token 加起来到了这个数，"
                          "就停止翻译新的文字，已有译文照常显示，明天自动恢复。")))
        lay.addWidget(box)
        return w

    def _privacy_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card(tr("译文记忆"))
        self.memory_on = QCheckBox(tr("记住译文：加密保存在本机，下次遇到相同的文字直接用（默认关闭）"))
        self.memory_on.setChecked(self.cfg.memory.enabled)
        f.addRow(self.memory_on)
        self.memory_clear = QPushButton(tr("清空记住的译文"))
        self.memory_clear.clicked.connect(self._clear_memory)
        f.addRow(self.memory_clear)
        f.addRow(_note(tr("会把屏幕上识别出的原文和译文存进本机文件（只有当前 Windows 账户能解开）。"
                          "只有数字不同的文字（计时器、进度、血量）不管开不开，都会套用已有译文、不再请求翻译。")))
        lay.addWidget(box)
        box, f = _card(tr("什么会发出去"))
        f.addRow(_note(tr("识别出的文字和所在窗口的标题会发给翻译服务（用本机 Ollama 时不出本机）；“翻译范围”里排除的程序"
                          "不识别、不发送。截图只在点“原位翻译”时才把选区里识别出的文字发出去，截下的图不发送。"
                          "魔镜、译文和设置窗口对截屏隐身：别的截图、录屏软件截不到它们。")))
        lay.addWidget(box)
        return w

    def _glossary_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card()
        f.addRow(_note(tr("人名、地名、游戏里的专有名词：在这里写好译法，翻译时必须照用（不分大小写）。"
                          "译法和原文一样表示保持不译。“只用于程序”填程序名（如 game.exe），空着表示所有程序都用。"
                          "改了术语表后，含这些词的已有译文会重新翻译。")))
        self.gloss = QTableWidget(0, 3)
        self.gloss.setHorizontalHeaderLabels([tr("原文里的词"), tr("译法"), tr("只用于程序（可空）")])
        self.gloss.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.gloss.setMinimumHeight(260)
        for g in self.cfg.glossary:
            self._add_term(g.get("src", ""), g.get("dst", ""), g.get("app", ""))
        f.addRow(self.gloss)
        row = QHBoxLayout()
        add = QPushButton(tr("添加一行"))
        add.clicked.connect(lambda: self._add_term("", "", ""))
        rm = QPushButton(tr("删除所选行"))
        rm.clicked.connect(self._remove_terms)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        f.addRow(row)
        self.consistency, crow = _checked(tr("保持术语前后一致（推荐）"), self.cfg.llm.consistency,
                                          tr("翻译时附上这个窗口里含同样词语的已有译文作参考，没写进术语表的词也沿用同样的译法。"
                                             "发给翻译服务的文字会多一些（实测约多 15%）。"))
        f.addRow(crow)
        lay.addWidget(box)
        return w

    def _recog_page(self) -> QWidget:
        w, lay = _column()
        box, f = _card(tr("识别"))
        self.device = QComboBox()
        self.device.addItem(tr("显卡（DirectML，快）"), "gpu")
        self.device.addItem(tr("CPU（玩游戏时不和游戏抢显卡）"), "cpu")
        self.device.setCurrentIndex(0 if self.cfg.ocr.device == "gpu" else 1)
        f.addRow(tr("文字识别"), self.device)
        self.all_monitors = QCheckBox(tr("处理所有屏幕（默认只处理魔镜所在的屏幕，更快、更省资源）"))
        self.all_monitors.setChecked(self.cfg.track.all_monitors)
        f.addRow(tr("屏幕范围"), self.all_monitors)
        self.wheel_predict = QCheckBox(tr("用滚轮学习滚动曲线，让译文和原文同步起步（以画面核对为准）"))
        self.wheel_predict.setChecked(self.cfg.track.wheel_predict)
        f.addRow(tr("滚动跟随"), self.wheel_predict)
        f.addRow(_note(tr("识别设备、屏幕范围和滚动跟随的更改在下次启动时生效。")))
        lay.addWidget(box)
        box, f = _card(tr("显示"))
        self.min_font = QSpinBox()
        self.min_font.setRange(8, 32)
        self.min_font.setValue(self.cfg.style.min_font_px)
        self.min_font.setSuffix(tr(" 像素"))
        f.addRow(tr("最小字号"), self.min_font)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.3, 1.0)
        self.opacity.setSingleStep(0.05)
        self.opacity.setValue(self.cfg.style.plate_opacity)
        if layered.colorkey():
            self.opacity.setEnabled(False)             # 色键窗口画不了半透明，见 layered.py
            self.opacity.setToolTip(tr("这台电脑（Windows 10）上底板总是不透明"))
        f.addRow(tr("底板不透明度"), self.opacity)
        lay.addWidget(box)
        return w

    def _about_page(self) -> QWidget:
        page = AboutPage()
        page.guide_requested.connect(self.guide_requested.emit)
        page.update_requested.connect(self.update_requested.emit)
        return page

    # ------------------------------------------------------------------ 快捷键
    def _key_rows(self, f: QFormLayout, names: list[str]) -> None:
        """一行一个快捷键：录入框 + 冲突提示。截图页和快捷键页上的同一个快捷键是两个框，改一个另一个跟着变。"""
        for name in names:
            label, mods_only = HOTKEYS[name]
            edit = HotkeyEdit(getattr(self.cfg.hotkeys, name), mods_only)
            note = QLabel("")
            note.setWordWrap(True)
            note.setStyleSheet("color: #c80;")
            edit.changed.connect(lambda v, n=name: self._key_changed(n, v))
            edit.hint.connect(lambda msg, n=name, lbl=note: self._key_hint(n, lbl, msg))
            self._keys.setdefault(name, []).append(edit)
            self._key_notes.setdefault(name, []).append(note)
            row = QHBoxLayout()
            row.addWidget(edit)
            row.addWidget(note, 1)
            f.addRow(tr(label), row)

    def key_value(self, name: str) -> str:
        return self._keys[name][0].value()

    def _key_changed(self, name: str, value: str) -> None:
        for e in self._keys[name]:
            e.set_value(value)
        self._refresh_keys()

    def _key_hint(self, name: str, lbl: QLabel, msg: str) -> None:
        if msg:
            lbl.setText(msg)
        else:
            self._refresh_keys()

    def _reset_keys(self) -> None:
        d = HotkeyConfig()
        for name in self._keys:
            self._key_changed(name, getattr(d, name))

    def key_problem(self, name: str) -> str:
        """这个快捷键有什么问题（格式不对、和魔镜别的快捷键重复、被别的程序占着）；没问题是空串。"""
        value = self.key_value(name)
        if HOTKEYS[name][1]:
            try:
                parse_modifiers(value)
            except ValueError as e:
                return str(e)
            return ""
        if not value.strip():
            return ""
        try:
            norm = normalize_hotkey(value)
        except ValueError as e:
            return str(e)
        for other, (label, mods_only) in HOTKEYS.items():
            if other == name or mods_only or other not in self._keys:
                continue
            try:
                same = normalize_hotkey(self.key_value(other)) == norm
            except ValueError:
                same = False
            if same:
                return tr("和“{name}”重复了").format(name=tr(label))
        if norm not in self._probed:
            self._probed[norm] = probe(norm)
        if not self._probed[norm]:
            return tr("被别的程序占着")
        return ""

    def _refresh_keys(self) -> None:
        for name, notes in self._key_notes.items():
            msg = self.key_problem(name)
            for lbl in notes:
                lbl.setText(msg)
                lbl.setToolTip(tr("换一个，或者先在那个程序里把它关掉") if msg == tr("被别的程序占着") else "")

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

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("截图保存到哪个文件夹"), self.cap_dir.text().strip())
        if d:
            self.cap_dir.setText(d)

    def _clear_memory(self) -> None:
        self.clear_memory_requested = True
        self.memory_clear.setText(tr("已清空（保存后生效）"))
        self.memory_clear.setEnabled(False)

    def _reset_lists(self) -> None:
        self.ex_apps.setPlainText("\n".join(DEFAULT_EXCLUDE_APPS))
        self.ex_titles.setPlainText("\n".join(DEFAULT_EXCLUDE_TITLES))

    def _add_term(self, src: str, dst: str, app: str) -> None:
        r = self.gloss.rowCount()
        self.gloss.insertRow(r)
        for c, v in enumerate((src, dst, app)):
            self.gloss.setItem(r, c, QTableWidgetItem(v))

    def _remove_terms(self) -> None:
        for r in sorted({i.row() for i in self.gloss.selectedIndexes()}, reverse=True):
            self.gloss.removeRow(r)

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
        c.scope.translate_chat = self.translate_chat.isChecked()
        c.update.auto_check = self.update_check.isChecked()
        c.memory.enabled = self.memory_on.isChecked()
        c.guard.idle_min = self.idle_min.value()
        c.guard.pause_when_locked = self.pause_locked.isChecked()
        c.guard.daily_tokens = self.daily_tokens.value()
        c.guard.show_meter = self.show_meter.isChecked()
        terms = []
        for r in range(self.gloss.rowCount()):
            vals = [(self.gloss.item(r, k).text().strip() if self.gloss.item(r, k) else "") for k in range(3)]
            if vals[0] and vals[1]:
                terms.append({"src": vals[0], "dst": vals[1], "app": vals[2]})
        c.glossary = terms
        c.llm.consistency = self.consistency.isChecked()
        c.target_lang = self.target.currentData()
        c.ui_lang = self.ui_lang.currentData()
        c.ocr.device = self.device.currentData()
        c.source_lang = self.source.currentData()
        c.track.all_monitors = self.all_monitors.isChecked()
        c.track.wheel_predict = self.wheel_predict.isChecked()
        c.style.min_font_px = self.min_font.value()
        c.style.plate_opacity = float(self.opacity.value())
        c.style.skin = self.skin.currentData()
        for name in self._keys:
            setattr(c.hotkeys, name, self.key_value(name).strip())
        c.input.enabled = self.input_on.isChecked()
        c.input.target = self.input_target.currentData()
        c.input.skip_apps = _lines(self.input_skip)
        c.vision.protocol = self.v_protocol.currentData()
        c.vision.base_url = self.v_base.text().strip()
        c.vision.model = self.v_model.text().strip()
        c.vision.api_key = self.v_key.text().strip()
        c.capture.after = self.cap_after.currentData()
        c.capture.snap = self.cap_snap.isChecked()
        c.capture.magnifier = self.cap_mag.isChecked()
        c.capture.save_dir = self.cap_dir.text().strip()
        c.capture.format = self.cap_format.currentData()
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
        self.test_result.setText(tr("正在测试…（本地模型第一次加载可能要十几秒）"))
        self._run_async("test", lambda: test_connection(cfg.llm, cfg.target_lang))

    def _fetch_models(self) -> None:
        cfg = self.collect()
        self.fetch.setEnabled(False)
        self.test_result.setText(tr("正在获取模型列表…"))
        self._run_async("models", lambda: list_models(cfg.llm))

    def _on_async_done(self, tag: str, res) -> None:
        if tag == "test":
            self.test_btn.setEnabled(True)
            if isinstance(res, Exception):
                self.test_result.setText(tr("测试出错：{name}").format(name=type(res).__name__))
            else:
                ok, msg = res
                self.test_result.setText(("✅ " if ok else "❌ ") + msg)
        elif tag == "models":
            self.fetch.setEnabled(True)
            self.test_result.setText(show_models(self.model, res))
