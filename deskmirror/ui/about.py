"""“关于”：版本、一句话介绍、作者邮箱、新手指南入口、项目主页、开源许可和用到的组件，最底下是打赏入口。

设置里的“关于”页和托盘菜单的“关于…”窗口共用这一份内容。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import CONTACT_EMAIL, HOMEPAGE, KOFI_URL, __version__, winapi
from ..i18n import tr, ui_lang

REWARD_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "wechat_reward.jpg"   # 作者的微信赞赏码


def _link(url: str, text: str = "") -> str:
    return f'<a href="{url}">{text or url}</a>'


class AboutPage(QWidget):
    guide_requested = Signal()      # “打开新手指南”
    update_requested = Signal()     # “检查更新”

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        head = QLabel(tr("<h3>桌面魔镜 DeskMirror</h3><p>版本 {version}</p>"
                         "<p>屏幕翻译工具：在网页、PDF、软件界面、游戏和视频字幕上，把译文贴在原文的位置。</p>")
                      .format(version=__version__))
        head.setWordWrap(True)
        lay.addWidget(head)
        row = QHBoxLayout()
        mail = QLabel(tr("作者邮箱：{link}").format(link=_link(f"mailto:{CONTACT_EMAIL}", CONTACT_EMAIL)))
        mail.setOpenExternalLinks(True)
        mail.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        row.addWidget(mail)
        self.copy_mail = QPushButton(tr("复制邮箱"))
        self.copy_mail.clicked.connect(self._copy_email)
        row.addWidget(self.copy_mail)
        row.addStretch(1)
        lay.addLayout(row)
        if HOMEPAGE:
            home = QLabel(tr("项目主页：{link}").format(link=_link(HOMEPAGE)))
            home.setOpenExternalLinks(True)
            home.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            lay.addWidget(home)
        grow = QHBoxLayout()
        guide = QPushButton(tr("打开新手指南"))
        guide.clicked.connect(self.guide_requested.emit)
        grow.addWidget(guide)
        check = QPushButton(tr("检查更新"))
        check.clicked.connect(self.update_requested.emit)
        grow.addWidget(check)
        grow.addStretch(1)
        lay.addLayout(grow)
        lic = QLabel(tr("开源许可：GPL-3.0。可以免费使用、修改；修改后再发布也要以同样的许可开源。"))
        lic.setWordWrap(True)
        lay.addWidget(lic)
        credits = QLabel(tr("用到的开源组件：Qt / PySide6（LGPL-3.0）、RapidOCR 与 PaddleOCR 识别模型（Apache-2.0）、"
                            "ONNX Runtime（MIT）、OpenCV（Apache-2.0）、NumPy（BSD-3-Clause）、httpx（BSD-3-Clause）、"
                            "mss（MIT）。感谢这些项目的作者。"))
        credits.setWordWrap(True)
        credits.setStyleSheet("color: #888;")
        lay.addWidget(credits)
        lay.addStretch(1)
        self.reward_dialog: RewardDialog | None = None
        if REWARD_IMAGE.exists() or KOFI_URL:       # 打赏入口放在最底下：不弹窗，不提醒
            tip = QHBoxLayout()
            thanks = QLabel(tr("桌面魔镜免费开源，所有功能都能用。\n如果它帮到了你，可以请作者喝杯咖啡。"))
            thanks.setWordWrap(True)
            tip.addWidget(thanks, 1)
            reward = QPushButton(tr("打赏作者…"))
            reward.clicked.connect(self._reward)
            tip.addWidget(reward)
            lay.addLayout(tip)

    def _copy_email(self) -> None:
        QGuiApplication.clipboard().setText(CONTACT_EMAIL)
        self.copy_mail.setText(tr("已复制"))

    def _reward(self) -> None:
        if self.reward_dialog is None:
            self.reward_dialog = RewardDialog(self.window())
        self.reward_dialog.show()
        self.reward_dialog.raise_()
        self.reward_dialog.activateWindow()


class RewardDialog(QDialog):
    """“打赏作者…”：微信赞赏码；填了 Ko-fi 地址再加一行（英文界面放在最前面）。完全自愿，不解锁任何功能。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("打赏作者"))
        lay = QVBoxLayout(self)
        kofi = None
        if KOFI_URL:
            kofi = QLabel(tr("海外用户：{link}（可用 PayPal 或银行卡）").format(link=_link(KOFI_URL, "Ko-fi")))
            kofi.setAlignment(Qt.AlignmentFlag.AlignCenter)
            kofi.setOpenExternalLinks(True)
            kofi.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            if ui_lang() != "zh":
                lay.addWidget(kofi)
        self.code = QLabel()
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(REWARD_IMAGE))
        if not pix.isNull():
            side = round(400 * self.logicalDpiX() / 96)     # 跟着系统缩放放大，手机隔着屏幕也扫得清
            self.code.setPixmap(pix.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            lay.addWidget(self.code)
            scan = QLabel(tr("用微信扫一扫"))
            scan.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(scan)
        note = QLabel(tr("完全自愿，不解锁任何功能，不打赏也一样用。"))
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)
        if kofi is not None and ui_lang() == "zh":
            lay.addWidget(kofi)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.button(QDialogButtonBox.StandardButton.Close).setText(tr("关闭"))
        bb.rejected.connect(self.close)
        lay.addWidget(bb)
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))


class AboutDialog(QDialog):
    """托盘菜单的“关于…”。"""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(tr("关于桌面魔镜"))
        self.resize(520, 400)
        lay = QVBoxLayout(self)
        self.page = AboutPage()
        lay.addWidget(self.page, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.button(QDialogButtonBox.StandardButton.Close).setText(tr("关闭"))
        bb.rejected.connect(self.close)
        lay.addWidget(bb)
        self.winId()
        winapi.exclude_from_capture(int(self.winId()))
