"""新手指南：第一次启动时弹出，分 6 步：选母语、魔镜是什么、选翻译服务、怎么用、隐私和费用、完成。

以后可以从托盘菜单或设置的“关于”页再打开。第 1 步选的母语（译文语言；界面跟着换成中文或英文）、
第 3 步选的翻译服务、第 5 步选的预译范围都立即生效。窗口对截屏隐身，不会被魔镜自己识别、翻译。
"""
from __future__ import annotations

import copy
import threading

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import i18n, winapi
from ..config import LANGUAGES, OPENAI_PRESETS, SCOPE_MODES, AppConfig, LlmConfig
from ..i18n import tr
from ..translator import list_models, test_connection

OLLAMA_URL = "http://127.0.0.1:11434"
P_LANG, P_WELCOME, P_SERVICE, P_USAGE, P_PRIVACY, P_DONE = range(6)
STEPS = 6

# 第 2 步示意图里的“网页”：中文界面是英文原文 → 中文译文，英文界面反过来
_DEMO_ZH = ("Harbour Guide", [("The bridge is closed today.", None), ("Take the northern road.", None),
                              ("The harbour is 3 km away.", "港口在 3 公里外。"),
                              ("Boats leave every hour.", "船每小时开一班。")])
_DEMO_EN = ("港口指南", [("今天这座桥封了。", None), ("请走北边那条路。", None),
                       ("港口在 3 公里外。", "The harbour is 3 km away."),
                       ("船每小时开一班。", "Boats leave every hour.")])

_LANG_BUTTON_CSS = ("QPushButton{padding:8px;border:1px solid #c8ccd4;border-radius:8px;background:#ffffff;}"
                    "QPushButton:hover{border-color:#3d8bfd;}"
                    "QPushButton:checked{border:2px solid #3d8bfd;background:#e8f1ff;font-weight:bold;}")


def ollama_status(names: list[str], err: str, model: str) -> tuple[bool, str]:
    """本机 Ollama 的检查结果 → (能用, 给用户看的说明)。"""
    if err:
        return False, tr("没连上本机的 Ollama：请先到 https://ollama.com 下载安装并打开它。"
                         "装好后在命令行运行 ollama pull {model}，再点“重新检查”。").format(model=model)
    if model not in names and f"{model}:latest" not in names:
        return False, tr("Ollama 在运行，但还没有模型 {model}：请在命令行运行 ollama pull {model}"
                         "（gemma4:12b 约 7.6 GB，需要显存较大的独立显卡），下载完再点“重新检查”。").format(model=model)
    return True, tr("本机 Ollama 和模型 {model} 都准备好了，文字不出本机，不花钱。").format(model=model)


def _font_for(text: str, px: int) -> QFont:
    f = QFont("Microsoft YaHei UI" if any(0x4E00 <= ord(ch) <= 0x9FFF for ch in text) else "Segoe UI")
    f.setPixelSize(px)
    return f


class _Relay(QObject):
    done = Signal(str, object)


class _Picture(QWidget):
    """第 2 步的示意图：镜框外照常是桌面，镜框里同一位置换成译文。"""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(560, 214)

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0 = (self.width() - 540) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(233, 238, 243))
        p.drawRoundedRect(QRectF(x0, 0, 540, 210), 10, 10)
        win = QRectF(x0 + 20, 12, 500, 186)
        p.setBrush(QColor(255, 255, 255))
        p.drawRoundedRect(win, 6, 6)
        p.setBrush(QColor(208, 215, 226))
        p.drawRoundedRect(QRectF(win.left(), win.top(), win.width(), 22), 6, 6)
        title, lines = _DEMO_ZH if i18n.ui_lang() == "zh" else _DEMO_EN
        p.setFont(_font_for(title, 13))
        p.setPen(QColor(60, 70, 85))
        p.drawText(QRectF(win.left() + 10, win.top() + 2, 300, 18), Qt.AlignmentFlag.AlignVCenter, title)
        # 上面两行在镜框外：照常是原文；下面两行在镜框里：同一位置换成译文
        ys = [32, 58, 118, 144]
        for (src, _dst), y in zip(lines, ys):
            p.setFont(_font_for(src, 15))
            p.setPen(QColor(30, 35, 45))
            p.drawText(QRectF(win.left() + 18, win.top() + y, 300, 24), Qt.AlignmentFlag.AlignVCenter, src)
        mirror = QRectF(win.left() + 8, win.top() + 112, win.width() - 16, 62)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawRect(mirror)
        for (_src, dst), y in zip(lines, ys):
            if dst:
                p.setFont(_font_for(dst, 15))
                p.setPen(QColor(30, 35, 45))
                p.drawText(QRectF(win.left() + 18, win.top() + y, 300, 24), Qt.AlignmentFlag.AlignVCenter, dst)
        p.setPen(QPen(QColor(61, 139, 253), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(mirror)
        tab = QRectF(mirror.left() - 1, mirror.top() - 20, 120, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(35, 38, 46, 235))
        p.drawRoundedRect(tab, 4, 4)
        tf = QFont("Microsoft YaHei UI")
        tf.setPixelSize(12)
        p.setFont(tf)
        p.setPen(QColor(235, 238, 245))
        name = tr("魔镜")
        p.drawText(tab.adjusted(8, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, name)
        p.setPen(QColor(120, 220, 140))
        p.drawText(tab.adjusted(18 + QFontMetrics(tf).horizontalAdvance(name), 0, 0, 0),
                   Qt.AlignmentFlag.AlignVCenter, tr("就绪"))
        p.setFont(_font_for(tr("← 镜框外：照常是你的桌面"), 13))
        wrap = Qt.AlignmentFlag.AlignVCenter.value | Qt.TextFlag.TextWordWrap.value
        p.setPen(QColor(110, 120, 135))
        p.drawText(QRectF(win.left() + 300, win.top() + 32, 190, 50), wrap, tr("← 镜框外：照常是你的桌面"))
        p.setPen(QColor(40, 110, 230))
        p.drawText(QRectF(win.left() + 300, win.top() + 118, 190, 50), wrap, tr("← 镜框里：同一位置换成译文"))
        p.end()


class GuideDialog(QDialog):
    apply_language = Signal(str)    # 第 1 步选定的母语（译文语言代码）
    apply_llm = Signal(object)      # LlmConfig：第 3 步选定的翻译服务
    apply_scope = Signal(str)       # 第 5 步选定的预译范围
    guide_done = Signal()           # 看完或关掉

    def __init__(self, cfg: AppConfig) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(660, 600)
        self.cfg = cfg
        self.llm = copy.deepcopy(cfg.llm)
        self.native = cfg.target_lang
        self._relay = _Relay()
        self._relay.done.connect(self._on_check_done)
        lay = QVBoxLayout(self)
        self.step_label = QLabel()
        self.step_label.setStyleSheet("color: #888;")
        lay.addWidget(self.step_label)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._language())
        self._build_pages()
        lay.addWidget(self.pages, 1)
        nav = QHBoxLayout()
        self.skip = QPushButton()
        self.skip.clicked.connect(self.close)
        nav.addWidget(self.skip)
        nav.addStretch(1)
        self.back = QPushButton()
        self.back.clicked.connect(lambda: self._go(-1))
        nav.addWidget(self.back)
        self.next = QPushButton()
        self.next.setDefault(True)
        self.next.clicked.connect(lambda: self._go(1))
        nav.addWidget(self.next)
        lay.addLayout(nav)
        self._retranslate()
        self.finished.connect(lambda _r: self.guide_done.emit())   # 按 Esc 关掉也算看过
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))

    # ------------------------------------------------------------------ 页面
    @staticmethod
    def _page(title: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        v = QVBoxLayout(w)
        h = QLabel(f"<h2>{title}</h2>")
        v.addWidget(h)
        return w, v

    @staticmethod
    def _text(html: str) -> QLabel:
        t = QLabel(html)
        t.setWordWrap(True)
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setOpenExternalLinks(True)
        return t

    def _build_pages(self) -> None:
        """第 1 步之后的各页（按当前界面语言建；换了界面语言就重建）。"""
        while self.pages.count() > 1:
            w = self.pages.widget(1)
            self.pages.removeWidget(w)
            w.deleteLater()
        for build in (self._welcome, self._service, self._usage, self._privacy, self._done):
            self.pages.addWidget(build())

    def _language(self) -> QWidget:
        w, v = self._page(i18n.LANG_PAGE_TITLE)          # 这时还没选语言：标题两种语言都写
        grid = QGridLayout()
        grid.setSpacing(10)
        group = QButtonGroup(self)
        self.lang_buttons: dict[str, QPushButton] = {}
        for i, (code, name) in enumerate(LANGUAGES.items()):     # 每种语言用它自己的文字写
            b = QPushButton(name)
            b.setCheckable(True)
            b.setMinimumHeight(56)
            f = b.font()
            f.setPointSizeF(f.pointSizeF() * 1.4)
            b.setFont(f)
            b.setStyleSheet(_LANG_BUTTON_CSS)
            group.addButton(b)
            b.clicked.connect(lambda _=False, c=code: self._pick_language(c))
            grid.addWidget(b, i // 2, i % 2)
            self.lang_buttons[code] = b
        v.addLayout(grid)
        self.lang_note = self._text("")
        v.addWidget(self.lang_note)
        v.addStretch(1)
        self.lang_buttons[self.native if self.native in LANGUAGES else "en"].setChecked(True)
        return w

    def _welcome(self) -> QWidget:
        w, v = self._page(tr("欢迎使用桌面魔镜"))
        v.addWidget(_Picture())
        v.addWidget(self._text(tr(
            "<p>桌面上那个蓝色的框就是<b>魔镜</b>：框外是你平常的桌面，框里是同一位置换成译文的样子。</p>"
            "<ul><li>把魔镜拖到想看的地方就行，网页、PDF、软件、游戏、视频字幕都一样。</li>"
            "<li>后台会提前翻译整块屏幕，所以拖到哪里，译文马上就在。</li>"
            "<li>拖动、缩放魔镜不会重新翻译，也不会多花钱。</li></ul>"
            "<p>接下来 3 分钟，把翻译服务设好，就能用了。</p>")))
        v.addStretch(1)
        return w

    def _service(self) -> QWidget:
        w, v = self._page(tr("第一件事：选一个翻译服务"))
        v.addWidget(self._text(tr("魔镜把屏幕上的文字交给翻译服务来翻。二选一：")))
        self.use_local = QRadioButton(tr("本机 Ollama（免费，文字不出本机；需要显存较大的独立显卡）"))
        self.use_cloud = QRadioButton(tr("云端服务（DeepSeek、通义千问等；按用量收费，一般电脑都能用）"))
        group = QButtonGroup(self)
        group.addButton(self.use_local)
        group.addButton(self.use_cloud)
        v.addWidget(self.use_local)
        self.local_status = self._text("")
        row = QHBoxLayout()
        row.addWidget(self.local_status, 1)
        self.recheck = QPushButton(tr("重新检查"))
        self.recheck.clicked.connect(self._check_local)
        row.addWidget(self.recheck)
        box = QWidget()
        box.setLayout(row)
        box.setContentsMargins(24, 0, 0, 0)
        v.addWidget(box)
        v.addWidget(self.use_cloud)
        cloud = QWidget()
        cf = QFormLayout(cloud)
        cf.setContentsMargins(24, 0, 0, 0)
        self.preset = QComboBox()
        for name, (url, model) in OPENAI_PRESETS.items():
            if "127.0.0.1" not in url:
                self.preset.addItem(tr(name), (url, model))
        self.preset.currentIndexChanged.connect(self._preset_changed)
        cf.addRow(tr("服务"), self.preset)
        self.model = QLineEdit()
        cf.addRow(tr("模型"), self.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(tr("在服务商网站申请；只用 Windows 账户加密保存在本机"))
        cf.addRow("API Key", self.key)
        trow = QHBoxLayout()
        self.test = QPushButton(tr("测试连接"))
        self.test.clicked.connect(self._test_cloud)
        trow.addWidget(self.test)
        self.cloud_status = self._text("")
        trow.addWidget(self.cloud_status, 1)
        cf.addRow("", trow)
        v.addWidget(cloud)
        v.addStretch(1)
        local = self.llm.protocol == "ollama"
        (self.use_local if local else self.use_cloud).setChecked(True)
        if not local:
            idx = next((i for i in range(self.preset.count())
                        if self.preset.itemData(i)[0].rstrip("/") == self.llm.base_url.rstrip("/")), -1)
            if idx >= 0:
                self.preset.setCurrentIndex(idx)
            self.model.setText(self.llm.model)
            self.key.setText(self.llm.api_key)
        else:
            self._preset_changed(self.preset.currentIndex())
        self._check_local()
        return w

    def _usage(self) -> QWidget:
        w, v = self._page(tr("魔镜怎么用"))
        hk = self.cfg.hotkeys
        v.addWidget(self._text(tr(
            "<p><b>移动、调整大小：</b>拖魔镜上方的深色标签移动，拖蓝色边框调整大小；"
            "按住 <b>{drag}</b> 在镜框里任意位置拖也能移动。"
            "镜框里照常能点、能选文字、能滚动，操作的是下面的软件。</p>"
            "<p><b>标签上的按钮：</b></p>"
            "<table cellspacing='4'>"
            "<tr><td><b>暂停</b></td><td>框留着，不识别、不翻译（不花钱），再点一下继续</td></tr>"
            "<tr><td><b>自动→中</b></td><td>指定原文和译成的语言，比如英→中、印尼→中、韩→中</td></tr>"
            "<tr><td><b>截原图 / 截译图</b></td><td>截下镜框里的画面（原样 / 带译文），复制到剪贴板</td></tr>"
            "<tr><td><b>看图</b></td><td>把镜框里的画面交给能看图的模型来翻：漫画、艺术字、图片里的字</td></tr>"
            "<tr><td><b>⟳</b></td><td>镜框里重新识别、重新翻译</td></tr>"
            "<tr><td><b>⚙</b> / <b>—</b></td><td>设置 / 隐藏魔镜</td></tr></table>"
            "<p><b>快捷键：</b>按住 <b>{peek}</b> 看原文；<b>{toggle}</b> 隐藏 / 显示；"
            "<b>{history}</b> 历史（回看刚才的字幕、对话）；<b>{vision}</b> 看图翻译。</p>"
            "<p>右键魔镜的标签还能：再开一个魔镜、让魔镜跟着下面的窗口走。</p>").format(
                drag=hk.drag_modifiers, peek=hk.peek, toggle=hk.toggle_visible, history=hk.history,
                vision=hk.vision)))
        v.addStretch(1)
        return w

    def _privacy(self) -> QWidget:
        w, v = self._page(tr("隐私和费用"))
        v.addWidget(self._text(tr(
            "<ul><li>用云端服务时，识别出的文字会发给它（按字数收费）。本机 Ollama 则完全不出本机。</li>"
            "<li>聊天软件、密码管理器、网银窗口默认不识别、不翻译，可在设置里增减。和外国同事、朋友聊天时，右键魔镜的标签勾选“翻译聊天软件”，聊完再关掉。</li>"
            "<li>日志不记屏幕上的文字；“记住译文”默认关闭。今天发了多少字，托盘图标的提示里能看到。</li></ul>"
            "<p><b>预先翻译多大范围：</b></p>")))
        self.scope = QComboBox()
        for code, name in SCOPE_MODES.items():
            self.scope.addItem(tr(name), code)
        self.scope.setCurrentIndex(max(0, self.scope.findData(self.cfg.scope.mode)))
        v.addWidget(self.scope)
        v.addWidget(self._text(tr(
            "<p style='color:#888'>“整块屏幕”拖到哪里都马上有译文，但别的窗口里的文字也会发出去；"
            "用云端服务又在意隐私或花费时，建议选“只翻魔镜所在的窗口”。以后可在托盘菜单里随时改。</p>")))
        v.addStretch(1)
        return w

    def _done(self) -> QWidget:
        w, v = self._page(tr("准备好了"))
        self.summary = self._text("")
        v.addWidget(self.summary)
        v.addWidget(self._text(tr(
            "<p>把魔镜拖到想翻译的地方，等一两秒，译文就会出现在原文的位置。</p>"
            "<p>以后想再看这份指南：右键托盘图标（右下角蓝色“镜”字）→ <b>新手指南</b>，"
            "或者 设置 → 关于。退出魔镜也在托盘菜单里。</p>")))
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ 语言
    def _pick_language(self, code: str) -> None:
        """第 1 步点了一种语言：译文语言立即换；界面语言跟着变了，就把后面各页按新语言重建。"""
        if code == self.native:
            return
        self.native = code
        ui = i18n.ui_lang_for(code)
        changed = ui != i18n.ui_lang()
        if changed:
            i18n.set_ui_lang(ui)
        self.apply_language.emit(code)
        if changed:
            self._build_pages()
            self._retranslate()

    def _retranslate(self) -> None:
        self.setWindowTitle(tr("桌面魔镜 · 新手指南"))
        self.skip.setText(tr("跳过"))
        self.back.setText(tr("上一步"))
        self.lang_note.setText(tr("译文会显示成这种语言；选中文时界面用中文，选其他语言时界面用英文。"
                                  "以后可以在 设置 → 识别与显示 里分别修改。"))
        self._go(0)

    # ------------------------------------------------------------------ 翻页
    def _go(self, d: int) -> None:
        i = self.pages.currentIndex()
        if d > 0 and i == P_SERVICE:
            self._apply_service()
        if d > 0 and i == P_PRIVACY:
            code = self.scope.currentData()
            if code != self.cfg.scope.mode:
                self.apply_scope.emit(code)
        if d > 0 and i == STEPS - 1:
            self.close()
            return
        i = max(0, min(STEPS - 1, i + d))
        self.pages.setCurrentIndex(i)
        self.step_label.setText(tr("新手指南 · 第 {n} 步，共 {total} 步").format(n=i + 1, total=STEPS))
        self.back.setEnabled(i > 0)
        self.next.setText(tr("开始使用") if i == STEPS - 1 else tr("下一步"))
        if i == STEPS - 1:
            self.summary.setText(tr("<p>译文语言：<b>{lang}</b>；翻译服务：<b>{service}</b>；预译范围：<b>{scope}</b>。</p>")
                                 .format(lang=LANGUAGES.get(self.native, self.native), service=self._service_name(),
                                         scope=tr(SCOPE_MODES.get(self.scope.currentData(), ""))))

    def _service_name(self) -> str:
        if self.use_local.isChecked():
            return tr("本机 Ollama（{model}）").format(
                model=self.llm.model if self.llm.protocol == "ollama" else "gemma4:12b")
        return tr("{service}（{model}）").format(service=self.preset.currentText(), model=self.model.text().strip())

    def collect_llm(self) -> LlmConfig:
        """按第 3 步的选择得出翻译服务设置（其他参数沿用原来的）。"""
        llm = copy.deepcopy(self.llm)
        if self.use_local.isChecked():
            if llm.protocol != "ollama":
                llm.protocol, llm.base_url, llm.model, llm.concurrency = "ollama", OLLAMA_URL, "gemma4:12b", 1
        else:
            url, _model = self.preset.currentData()
            llm.protocol, llm.base_url = "openai", url
            llm.model = self.model.text().strip()
            llm.api_key = self.key.text().strip()
            llm.concurrency = max(llm.concurrency, 2)
        return llm

    def _apply_service(self) -> None:
        llm = self.collect_llm()
        if (llm.protocol, llm.base_url, llm.model, llm.api_key) != \
                (self.llm.protocol, self.llm.base_url, self.llm.model, self.llm.api_key):
            self.llm = llm
            self.apply_llm.emit(copy.deepcopy(llm))

    def _preset_changed(self, idx: int) -> None:
        data = self.preset.itemData(idx)
        if data and data[1]:
            self.model.setText(data[1])

    # ------------------------------------------------------------------ 检查
    def _run(self, tag: str, fn) -> None:
        def work() -> None:
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                res = e
            self._relay.done.emit(tag, res)
        threading.Thread(target=work, daemon=True).start()

    def _check_local(self) -> None:
        self.local_status.setText(tr("正在检查本机的 Ollama…"))
        model = self.llm.model if self.llm.protocol == "ollama" else "gemma4:12b"
        probe = LlmConfig(protocol="ollama", base_url=OLLAMA_URL if self.llm.protocol != "ollama"
                          else self.llm.base_url)
        self._run("local", lambda: (list_models(probe), model))

    def _test_cloud(self) -> None:
        self.cloud_status.setText(tr("正在测试…"))
        llm = self.collect_llm() if self.use_cloud.isChecked() else None
        if llm is None:
            self.use_cloud.setChecked(True)
            llm = self.collect_llm()
        self._run("cloud", lambda: test_connection(llm, self.cfg.target_lang))

    def _on_check_done(self, tag: str, res) -> None:
        if tag == "local":
            if isinstance(res, Exception):
                ok, msg = False, tr("检查出错：{name}").format(name=type(res).__name__)
            else:
                (names, err), model = res
                ok, msg = ollama_status(names, err, model)
            self.local_status.setText(("✅ " if ok else "⚠️ ") + msg)
        elif tag == "cloud":
            if isinstance(res, Exception):
                self.cloud_status.setText(tr("测试出错：{name}").format(name=type(res).__name__))
            else:
                ok, msg = res
                self.cloud_status.setText(("✅ " if ok else "❌ ") + msg)

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.guide_done.emit()
        super().closeEvent(ev)
