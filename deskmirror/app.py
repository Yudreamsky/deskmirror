"""程序入口：托盘、快捷键、魔镜边框与覆盖层的联动、设置与退出。"""
from __future__ import annotations

import collections
import ctypes
import json
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")  # 全程用物理像素，和截屏坐标一致

from . import ROOT, __version__, autostart as boot, config, geom, i18n, winapi  # noqa: E402
from .i18n import N_, tr  # noqa: E402

log = logging.getLogger("deskmirror")


PAUSED_TEXT = N_("已暂停：不识别、不翻译（点“继续”恢复）")
BALL_TIP = N_("魔镜收起来了，翻译已停下。点一下回到原来的地方，或者拖出来放到要翻译的地方。")


def _qimage_bgr(img):
    """截图（QImage，RGB32，内存里是 BGRA）转成 numpy 的 BGR 数组。"""
    import numpy as np
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine() // 4, 4)
    return arr[:, :w, :3].copy()


def _host_of(url: str) -> str:
    """翻译服务地址里的主机名（给用户看的提示用）。"""
    from urllib.parse import urlparse
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url


def _short_num(n: int) -> str:
    """12345 → 12.3k，像网速那样短。"""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k" if n < 100_000 else f"{n // 1000}k"
    return f"{n / 1_000_000:.2f}M"


def _setup_logging() -> None:
    logdir = ROOT / "logs"
    logdir.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(logdir / "deskmirror.log", maxBytes=1_000_000, backupCount=3,
                                              encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(sh)


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
_k32.CreateEventW.restype = ctypes.c_void_p
_k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_k32.WaitForSingleObject.restype = ctypes.c_uint32


def _single_instance() -> object | None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, "Local\\DeskMirror.Instance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def _wait_for_exit(pid: int, timeout_ms: int = 20000) -> None:
    """等旧进程退出（它占着“只能开一个”的锁），最多等 20 秒。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenProcess(0x00100000, False, pid)        # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(h, timeout_ms)
        k32.CloseHandle(h)


def main() -> int:
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        from .cli import main as cli_main          # DeskMirror.exe config …：输出接到启动它的命令行窗口上
        return cli_main(sys.argv[1:])
    # 1.2.0 之前的源码版（b613547）git pull 完会带着这个变量启动新版本，先退出旧的：等它退出再启动，不然会提示“已经在运行”
    wait = os.environ.pop("DESKMIRROR_WAIT_PID", "")
    if wait.isdigit():
        _wait_for_exit(int(wait))
    autostart = "--autostart" in sys.argv[1:]          # 开机自启：魔镜都收成球待命
    _setup_logging()
    # 跟踪线程有不少 Python 代码；缩短 GIL 切换间隔，界面线程（画译文、拖魔镜）不会被它长时间挡住。
    sys.setswitchinterval(0.002)
    winapi.set_dpi_awareness()
    mutex = _single_instance()
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QMenu, QMessageBox, QSystemTrayIcon

    from .engine import Engine
    from .fieldtrans import FieldTranslator
    from .hotkeys import HoldShortcut, HotkeyManager, modifiers_down, parse_modifiers
    from .ui import glass, layered
    from .ui.dock import Docker
    from .ui.mirror import MirrorFrame
    from .ui.overlay import Overlay, UiState
    from .ui.render import Renderer
    from .ui.about import AboutDialog
    from .ui.guide import GuideDialog
    from .ui.history import HistoryPanel
    from .ui.vision import VisionPanel
    from .ui.settings import SettingsDialog
    from .ui.update import UpdateDialog
    from . import updater

    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    cfg = config.load()
    if not cfg.ui_lang:
        if cfg.first_run_tip:
            # 第一次启动：按 Windows 的语言猜母语（译文语言），界面跟着用中文或英文；新手指南第 1 步可以改
            cfg.target_lang = i18n.native_from_locale(i18n.system_locale())
            cfg.ui_lang = i18n.ui_lang_for(cfg.target_lang)
        else:
            cfg.ui_lang = "zh"          # 以前的版本只有中文界面
    i18n.set_ui_lang(cfg.ui_lang)
    qapp.setApplicationName(tr("桌面魔镜"))
    if mutex is None:
        QMessageBox.information(None, tr("桌面魔镜"), tr("魔镜已经在运行了（看看右下角托盘图标）。"))
        return 0

    def make_icon() -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(cfg.style.border_color))
        p.setPen(QColor(255, 255, 255))
        p.drawRoundedRect(4, 4, 56, 56, 12, 12)
        f = QFont("Microsoft YaHei UI")
        f.setPixelSize(36)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect(), 0x84, "镜")
        p.end()
        return QIcon(pm)

    class App(QObject):
        snapshot_ready = Signal(object)
        vision_piece = Signal(str)            # 看图翻译：后台线程拿到的一段译文
        vision_done = Signal(str, float)      # 看图翻译结束：(出错说明, 用时)
        update_found = Signal(object)         # 启动后自动检查查到了新版本（updater.Release）

        def __init__(self) -> None:
            super().__init__()
            self.cfg = cfg
            self.state = UiState(Renderer(cfg.style, binary=layered.colorkey()))
            self.state.frame_color = QColor(cfg.style.border_color)
            glass.set_active(cfg.style.skin == "glass")
            self.backdrop = glass.Backdrop(None)               # 液态玻璃取后面的画面（引擎建好后接上）
            mons = winapi.monitors()
            self.overlays = [Overlay(m, self.state) for m in mons]
            rect = tuple(cfg.mirror_rect) if cfg.mirror_rect else self._default_rect(mons)
            self.state.mirror = rect
            self.frames: list[MirrorFrame] = []
            self.frame = self._new_frame(rect)                 # 主魔镜（不能关，只能隐藏）
            for r in cfg.extra_mirrors:
                self._new_frame(tuple(r))
            self._last_shot = ""
            self.engine = Engine(cfg, self.snapshot_ready.emit)
            self.backdrop.engine = self.engine
            self._sync_mirrors()
            self.snapshot_ready.connect(self._on_snapshot)
            self.hotkeys = HotkeyManager(qapp)
            self.hotkeys.activated.connect(self._on_hotkey)
            self.peek = HoldShortcut(self)
            self.peek.changed.connect(self._on_peek)
            self.history = HistoryPanel()
            self.vision_panel = VisionPanel()
            self.vision_piece.connect(self.vision_panel.append)
            self.vision_done.connect(self.vision_panel.finish)
            self.vision_panel.retry_requested.connect(lambda: self.look(region=self._look_region))
            self.vision_panel.cancel_requested.connect(self._cancel_look)
            self._look_cancel: threading.Event | None = None
            self._look_region: tuple | None = None
            self.history.edit_requested.connect(lambda key, src, text: self.engine.inbox.put(("override", key, text)))
            self._hist_seen: set[tuple[int, int]] = set()
            self._drag_mods = []
            self.tip = QLabel(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                              | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                              | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.tip.setStyleSheet("QLabel{background:#202329;color:#f2f4f8;border:1px solid #3d8bfd;"
                                   "border-radius:6px;padding:8px;font:14px 'Microsoft YaHei UI';}")
            self.tip.setWordWrap(True)
            self.tip.setMaximumWidth(560)
            self.tip.winId()
            winapi.exclude_from_capture(int(self.tip.winId()))
            # 输入框翻译的小提示：贴在别的软件的输入框光标下面（“翻译中…”“已翻译 · 再连按三次空格换回原文”）
            self.field_tip = QLabel(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                                    | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                                    | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.field_tip.winId()
            winapi.exclude_from_capture(int(self.field_tip.winId()))
            self._field_tip_timer = QTimer(self, singleShot=True, timeout=self.field_tip.hide)
            self._tip_bid = 0
            self._hover_since = 0.0
            self.tray = QSystemTrayIcon(make_icon())
            self.tray.setToolTip(tr("桌面魔镜"))
            self._usage_seen = (0, 0, 0, 0, 0)   # 引擎累计的请求数、字数、输入 / 输出 / 命中缓存的 token（本次运行）
            self._usage_tip = ""
            self._budget_hit: bool | None = False   # 今天的 token 用到上限了（None：还没告诉引擎）
            self._away = False               # 锁屏 / 屏保中：完全停下
            self._frugal = False             # 好一会儿没碰键盘鼠标：只翻镜框里的
            self._menu: QMenu | None = None
            self._build_menu()
            self.tray.activated.connect(self._on_tray)
            self._message_action = None         # 点托盘提示时做什么（截图后打开文件夹、有新版本时打开检查更新）
            self._message_until = 0.0
            self.tray.messageClicked.connect(self._on_message_clicked)
            self.tray.show()
            self.field = FieldTranslator(cfg)
            self.field.tip.connect(self._show_field_tip)
            self.field.used.connect(self._count_field_usage)
            self._register_keys()
            self._engine_on = False
            self._restore_docks()
            for o in self.overlays:
                o.show()
            for f in self.frames:
                if not f.dock.docked:
                    f.show()
            if winapi.capture_failures:
                log.warning("有 %d 个窗口没能对截屏隐身（错误码 %s）", len(winapi.capture_failures),
                            sorted(set(winapi.capture_failures)))
                QTimer.singleShot(3000, lambda: self.tray.showMessage(tr("桌面魔镜"), tr(
                    "这台电脑上魔镜没能对截屏隐身，可能会把自己画的译文又当成原文识别。"
                    "麻烦把程序文件夹里 logs 下的日志发给作者。"), QSystemTrayIcon.MessageIcon.Warning, 15000))
            self.timer = QTimer(self)
            self.timer.setInterval(16)
            self.timer.timeout.connect(self._tick)
            self.timer.start()
            self._last_topmost = 0.0
            self._glass_t = 0.0
            self._glass_ms: collections.deque = collections.deque(maxlen=600)   # 每轮玻璃检查、重画用了多久（调试）
            self._settings: SettingsDialog | None = None
            self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self._save)
            # 用量每 5 分钟落一次盘（只有数量），中途崩溃也不至于丢掉一整天的统计
            self._usage_saved = (cfg.usage.requests, cfg.usage.chars)
            self._usage_timer = QTimer(self, interval=300_000, timeout=self._save_usage)
            self._usage_timer.start()
            # 配置文件被别的程序（命令行、AI 助手）改了：停稳一会儿再重新载入（自己存的不算）
            self._cfg_stamp = self._cfg_seen = self._config_stamp()
            self._last_cfg_check = 0.0
            self._reload_timer = QTimer(self, singleShot=True, interval=600, timeout=self._reload_config)
            # 命令行 update 会用这个事件请正在运行的魔镜退出
            self._quit_event = _k32.CreateEventW(None, True, False, updater.QUIT_EVENT)
            self.update_dialog: UpdateDialog | None = None
            self._start_update_checks()
            self._guard_timer = QTimer(self, interval=1000, timeout=self._guard_tick)
            self._guard_timer.start()
            if not self._all_docked():
                self._start_engine()          # 都收成球了：等第一次展开再启动（识别模型那时才载入，开机更快）
            self._update_meter()
            qapp.aboutToQuit.connect(self.shutdown)
            self.debug = None
            port = os.environ.get("DESKMIRROR_DEBUG_PORT")
            if port:
                from .debugctl import DebugServer
                self.debug = DebugServer(int(port), self._debug_cmd)
            autoquit = os.environ.get("DESKMIRROR_AUTOQUIT")
            if autoquit:
                QTimer.singleShot(int(float(autoquit) * 1000), self.quit_app)
            self.recorder = None                # 调试用的录制（record_start / record_stop）
            self._record_native: set[int] = set()   # 录制时暂时不对截屏隐身的窗口（record_native）
            self._record_styles: dict = {}           # 录制时临时放大字号的窗口：hwnd → (窗口, 原来的样式表)
            self.guide: GuideDialog | None = None
            self.about: AboutDialog | None = None
            if cfg.first_run_tip:
                QTimer.singleShot(1200, self.open_guide)     # 第一次启动：新手指南（看完或关掉就不再自动打开）
            try:
                if boot.refresh():
                    log.info("程序挪了地方：开机启动项改成现在的路径")
            except OSError as e:
                log.warning("开机启动项更新失败：%s", e)

        # -------------------------------------------------------------- 托盘菜单、界面语言
        def _build_menu(self) -> None:
            """托盘菜单（换界面语言时整个重建）。"""
            menu = QMenu()
            self.act_toggle = QAction(tr("显示魔镜") if self.state.hidden else tr("隐藏魔镜"), menu)
            self.act_toggle.triggered.connect(self.toggle_visible)
            menu.addAction(self.act_toggle)
            self.act_pause = QAction(tr("继续翻译") if self.state.paused else tr("暂停（框留着，不识别、不翻译）"), menu)
            self.act_pause.triggered.connect(self.toggle_pause)
            menu.addAction(self.act_pause)
            menu.addAction(tr("刷新镜框内区域"), self.refresh)
            menu.addAction(tr("新建一个魔镜"), self.add_mirror)
            menu.addAction(tr("截原图（镜框内原样）"), lambda: self.take_shot("orig"))
            menu.addAction(tr("截译图（镜框内带译文）"), lambda: self.take_shot("trans"))
            self.act_shotmode = self._shotmode_action(menu)
            menu.addAction(self.act_shotmode)
            menu.addAction(tr("看图翻译（把镜框里的画面交给能看图的模型）"), self.look)
            menu.addSeparator()
            scope_menu = menu.addMenu(tr("预译范围"))
            self.scope_actions = {}
            for code, name in config.SCOPE_MODES.items():
                act = QAction(tr(name), scope_menu)
                act.setCheckable(True)
                act.setChecked(self.cfg.scope.mode == code)
                act.triggered.connect(lambda _=False, c=code: self.set_scope(c))
                scope_menu.addAction(act)
                self.scope_actions[code] = act
            menu.addAction(tr("不翻译魔镜下的这个程序"), self.exclude_app_under_mirror)
            self.act_chat = self._chat_action(menu)
            menu.addAction(self.act_chat)
            menu.addAction(tr("历史记录…（最近的原文和译文）"), self.toggle_history)
            menu.addAction(tr("新手指南…"), self.open_guide)
            menu.addAction(tr("设置…"), self.open_settings)
            self.act_debug = QAction(tr("显示识别到的滚动区域（调试）"), menu)
            self.act_debug.setCheckable(True)
            self.act_debug.setChecked(self.state.debug)
            self.act_debug.toggled.connect(self._on_debug)
            menu.addAction(self.act_debug)
            menu.addSeparator()
            menu.addAction(tr("检查更新…"), lambda: self.open_update())
            menu.addAction(tr("关于…"), self.open_about)
            menu.addAction(tr("退出"), self.quit_app)
            old, self._menu = self._menu, menu
            self.tray.setContextMenu(menu)
            if old is not None:
                old.deleteLater()

        def quit_app(self) -> None:
            """退出程序。Qt 6 退出时会先关掉所有窗口：新手指南这时被关掉不算看过，下次启动还会弹出。"""
            if self.guide is not None:
                self.guide.blockSignals(True)
            qapp.quit()

        def apply_ui_lang(self, lang: str) -> None:
            """换界面语言：托盘菜单、魔镜标签、历史和看图窗口马上换；关于、设置、新手指南下次打开时按新语言建。"""
            self.cfg.ui_lang = lang
            i18n.set_ui_lang(lang)
            qapp.setApplicationName(tr("桌面魔镜"))
            self._build_menu()
            for f in self.frames:
                f.set_lang_label(self._lang_label())
                f.retranslate()
            self.history.retranslate()
            self.vision_panel.retranslate()
            if self.about is not None:
                self.about.close()
                self.about.deleteLater()
                self.about = None
            self._usage_tip = ""                 # 托盘提示、标签上的状态按新语言重写
            snap = self.state.snapshot
            if snap is not None:
                self._count_engine_usage()
                self._update_status(snap)
            elif self.state.paused:
                for f in self.frames:
                    f.set_status(tr(PAUSED_TEXT), "paused")
            self._save_timer.start()

        def _guide_language(self, native: str) -> None:
            """新手指南第 1 步选了母语：译文语言换成它，界面语言跟着换（中文或英文）。"""
            ui = i18n.ui_lang_for(native)
            if ui != self.cfg.ui_lang:
                self.apply_ui_lang(ui)
            self.set_languages(self.cfg.source_lang, native)

        # -------------------------------------------------------------- 多个魔镜、跟随窗口
        def _new_frame(self, rect: tuple) -> MirrorFrame:
            f = MirrorFrame(rect, self.cfg.style.border_color)
            f.backdrop = self.backdrop
            f.dock = Docker(f, self.state.shapes, self.state.balls)
            f.dock.backdrop = self.backdrop
            f.dock.docked_changed.connect(lambda on, f=f: self._on_docked(f, on))
            f.dock.repaint.connect(self._repaint_screen)
            f.dock.committed.connect(self._save_mirrors)
            f.rect_changed.connect(lambda r, final, f=f: self._on_frame_rect(f, r, final))
            f.refresh_clicked.connect(lambda f=f: self.refresh(f))
            f.settings_clicked.connect(self.open_settings)
            f.hide_clicked.connect(self.toggle_visible)
            f.shot_clicked.connect(lambda kind, f=f: self.take_shot(kind, f))
            f.menu_requested.connect(lambda pos, f=f: self._frame_menu(f, pos))
            f.pause_clicked.connect(self.toggle_pause)
            f.set_paused(self.state.paused)
            f.lang_clicked.connect(self._lang_menu)
            f.look_clicked.connect(lambda f=f: self.look(f))
            f.set_lang_label(self._lang_label())
            f.shown_rect = rect                                  # 上次画过译文的范围（移动后要擦掉）
            self.frames.append(f)
            return f

        def _active_frames(self) -> list[MirrorFrame]:
            return [f for f in self.frames if not f.suspended and not f.dock.docked]

        def _all_docked(self) -> bool:
            return all(f.dock.docked for f in self.frames)

        def _sync_mirrors(self) -> None:
            """把各个魔镜的位置交给覆盖层和跟踪引擎（第一个是主魔镜）。收成球的不算；正在变形的，
            译文由覆盖层按形状裁剪（state.shapes），引擎照样按它的位置先翻。"""
            active = self._active_frames()
            self.state.mirror = self.frame.mirror
            self.state.mirrors = [f.mirror for f in active if f.dock.live is None]
            main = self.frame if self.frame in active else (active[0] if active else self.frame)
            self.engine.set_mirrors([main.mirror] + [f.mirror for f in active if f is not main])

        def _start_engine(self) -> None:
            if not self._engine_on:
                self._engine_on = True
                self.engine.start()

        def _restore_docks(self) -> None:
            """上次收成球的魔镜照样收着；开机自启时所有魔镜都收成球待命（点开或拖出来才开始截屏、识别）。"""
            saved = self.cfg.docks
            for i, f in enumerate(self.frames):
                spot = saved[i] if i < len(saved) and saved[i] else None
                if spot or autostart:
                    f.dock.dock_now(spot)

        def _on_docked(self, f: MirrorFrame, docked: bool) -> None:
            """魔镜收成球：它那里不再显示译文；所有魔镜都收起来了就停下截屏、识别、翻译（不花 token）。
            展开（点球、从边上拖出来）：接着工作，像点了“继续”一样重新核对画面。"""
            self._sync_mirrors()
            self._apply_working()
            if not docked:
                self._start_engine()
                if not self.state.paused and not self.state.shot_mode and not self._away:
                    f.set_status(tr("继续工作，正在核对画面…"), "busy")
            for o in self.overlays:
                o.repaint_mirror(f.shown_rect)
            f.shown_rect = f.mirror

        def _repaint_screen(self, box: tuple) -> None:
            for o in self.overlays:
                o.repaint_rect(box)

        def add_mirror(self) -> None:
            if len(self.frames) >= 4:
                self.tray.showMessage(tr("桌面魔镜"), tr("最多同时开 4 个魔镜。"),
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
                return
            base = self.frames[-1].mirror
            w, h = min(640, base[2] - base[0]), min(360, base[3] - base[1])
            scr = winapi.monitors()[0].work
            for m in winapi.monitors():
                if geom.contains_pt(m.rect, *geom.center(base)):
                    scr = m.work
            x = min(base[0] + 60, scr[2] - w - 20)
            y = min(base[1] + 60, scr[3] - h - 20)
            f = self._new_frame((x, y, x + w, y + h))
            self._update_meter()
            if not self.state.hidden:
                f.show()
            self._sync_mirrors()
            self._apply_working()
            self._start_engine()
            self._save_mirrors()
            for o in self.overlays:
                o.repaint_mirror()

        def close_mirror(self, f: MirrorFrame) -> None:
            if f is self.frame:
                return
            old = f.mirror
            self.frames.remove(f)
            self.backdrop.forget(f)
            self.backdrop.forget(f.dock)
            f.dock.close()
            f.close()
            self._sync_mirrors()
            self._apply_working()
            self._save_mirrors()
            for o in self.overlays:
                o.repaint_mirror(old)

        def _keep_mirrors(self, cfg) -> None:
            """魔镜的位置、收没收成球是程序自己记的：换设置、重新载入时照搬现在的。"""
            cfg.mirror_rect = list(self.frame.mirror)
            cfg.extra_mirrors = [list(f.mirror) for f in self.frames[1:]]
            cfg.docks = [f.dock.saved() for f in self.frames]

        def _save_mirrors(self) -> None:
            self._keep_mirrors(self.cfg)
            self._save_timer.start()

        def _frame_menu(self, f: MirrorFrame, pos) -> None:
            menu = QMenu()
            if f.bound is None:
                menu.addAction(tr("跟随下面的窗口（窗口移动、缩放时魔镜跟着走）"), lambda: self.bind_mirror(f))
            else:
                menu.addAction(tr("取消跟随窗口"), lambda: self.unbind_mirror(f))
            menu.addAction(tr("新建一个魔镜"), self.add_mirror)
            menu.addAction(self._chat_action(menu))
            menu.addAction(self._shotmode_action(menu))
            if f is not self.frame:
                menu.addAction(tr("关闭这个魔镜"), lambda: self.close_mirror(f))
            menu.exec(pos)

        def _chat_action(self, parent) -> QAction:
            act = QAction(tr("翻译聊天软件（和外国同事、朋友聊天时打开）"), parent)
            act.setCheckable(True)
            act.setChecked(self.cfg.scope.translate_chat)
            act.toggled.connect(self.set_translate_chat)
            return act

        def _shotmode_action(self, parent) -> QAction:
            act = QAction(tr("让截图工具截到魔镜（期间译文不更新）"), parent)
            act.setCheckable(True)
            act.setChecked(self.state.shot_mode)
            act.toggled.connect(self.set_shot_mode)
            return act

        def set_shot_mode(self, on: bool) -> None:
            """截图模式：魔镜和译文暂时让截图、录屏软件截得到。魔镜自己也靠截屏看字，这期间看到的会是自己画的译文，
            所以先停下识别和翻译、译文定住不动，等一下再放开隐身；关掉时先恢复隐身，等一下再接着识别（重新核对画面）。"""
            if on == self.state.shot_mode:
                return
            self.state.shot_mode = on
            if self.act_shotmode.isChecked() != on:
                self.act_shotmode.blockSignals(True)
                self.act_shotmode.setChecked(on)
                self.act_shotmode.blockSignals(False)
            if on:
                self.engine.set_working(False)
                QTimer.singleShot(250, lambda: self.state.shot_mode and winapi.set_capture_visible(True))
                msg = tr("截图模式：现在截图、录屏软件能截到魔镜和译文了。这期间译文不会更新，"
                         "截完在托盘菜单或右键魔镜标签里关掉。")
            else:
                winapi.set_capture_visible(False)
                QTimer.singleShot(300, lambda: self.state.shot_mode or self._apply_working())
                msg = tr("已关闭截图模式：魔镜重新对截屏隐身，接着识别、翻译。")
                for f in self.frames:
                    f.set_status(tr("继续工作，正在核对画面…"), "busy")
            self._update_status(None)
            self.tray.showMessage(tr("桌面魔镜"), msg, QSystemTrayIcon.MessageIcon.Information, 6000)

        def set_translate_chat(self, on: bool) -> None:
            """聊天软件默认不翻（私人聊天不发出去）；和外国同事聊天时打开，聊完关掉。密码管理器、网银始终不翻。"""
            if on == self.cfg.scope.translate_chat:
                return
            self.cfg.scope.translate_chat = on
            if self.act_chat.isChecked() != on:
                self.act_chat.blockSignals(True)
                self.act_chat.setChecked(on)
                self.act_chat.blockSignals(False)
            self._save()
            if on:
                local = self.cfg.llm.protocol == "ollama" and any(
                    h in self.cfg.llm.base_url for h in ("127.0.0.1", "localhost", "[::1]"))
                where = tr("用的是本机 Ollama，聊天内容不出本机。") if local else                     tr("聊天内容会发给翻译服务（{host}）。").format(host=_host_of(self.cfg.llm.base_url))
                msg = tr("已打开：微信、QQ、钉钉、飞书、Telegram、WhatsApp 等聊天窗口也会翻译。{where}聊完可以在托盘菜单或右键魔镜标签里关掉。"
                         ).format(where=where)
            else:
                msg = tr("已关闭：聊天软件的窗口不再识别、不再翻译。")
            self.tray.showMessage(tr("桌面魔镜"), msg, QSystemTrayIcon.MessageIcon.Information, 6000)

        def bind_mirror(self, f: MirrorFrame) -> bool:
            """让魔镜跟随它中心下面的那个窗口：记下魔镜在窗口里的相对位置，窗口移动、缩放时按比例跟着走。"""
            cx, cy = geom.center(f.mirror)
            for w in winapi.top_level_windows(skip_pid=os.getpid(), with_titles=True):
                if geom.contains_pt(w.rect, cx, cy):
                    wr = w.rect
                    W, H = max(1, wr[2] - wr[0]), max(1, wr[3] - wr[1])
                    m = f.mirror
                    rel = ((m[0] - wr[0]) / W, (m[1] - wr[1]) / H, (m[2] - wr[0]) / W, (m[3] - wr[1]) / H)
                    f.bound = (w.hwnd, rel, wr)
                    f.set_pinned(True)
                    self.tray.showMessage(tr("桌面魔镜"), tr("魔镜正跟随窗口：{title}").format(title=w.title[:40] or w.cls),
                                          QSystemTrayIcon.MessageIcon.Information, 3000)
                    return True
            self.tray.showMessage(tr("桌面魔镜"), tr("魔镜下面没有找到窗口。"), QSystemTrayIcon.MessageIcon.Warning, 3000)
            return False

        def unbind_mirror(self, f: MirrorFrame) -> None:
            f.bound = None
            f.set_pinned(False)
            if f.suspended:
                f.suspended = False
                if not self.state.hidden and not f.dock.docked:
                    f.show()
                self._sync_mirrors()

        def _follow_windows(self) -> None:
            """跟随窗口的魔镜：窗口动了就按相对位置跟着走；窗口最小化时收起，关掉了就取消跟随。"""
            changed = False
            for f in list(self.frames):
                if f.bound is None or f.dock.docked or f.dock.busy:
                    continue
                hwnd, rel, last = f.bound
                wr = winapi.window_rect(hwnd)
                if wr is None:
                    self.unbind_mirror(f)
                    self.tray.showMessage(tr("桌面魔镜"), tr("跟随的窗口已关闭，魔镜不再跟随。"),
                                          QSystemTrayIcon.MessageIcon.Information, 3000)
                    continue
                gone = winapi.window_minimized(hwnd)
                if gone != f.suspended:
                    f.suspended = gone
                    f.setVisible(not gone and not self.state.hidden)
                    changed = True
                if gone or wr == last:
                    continue
                W, H = wr[2] - wr[0], wr[3] - wr[1]
                new = (int(round(wr[0] + rel[0] * W)), int(round(wr[1] + rel[1] * H)),
                       int(round(wr[0] + rel[2] * W)), int(round(wr[1] + rel[3] * H)))
                f.bound = (hwnd, rel, wr)
                if new != f.mirror and new[2] - new[0] >= 80 and new[3] - new[1] >= 60:
                    old = f.mirror
                    f.set_mirror(new)
                    f.shown_rect = new
                    for o in self.overlays:
                        o.repaint_mirror(old)
                    changed = True
            if changed:
                self._sync_mirrors()

        def _frame_at(self, x: int, y: int) -> MirrorFrame | None:
            for f in self._active_frames():
                if geom.contains_pt(geom.expand(f.mirror, 2), x, y):
                    return f
            return None

        @staticmethod
        def _default_rect(mons) -> tuple:
            r = mons[0].work
            cw, ch = (r[2] - r[0]) * 2 // 5, (r[3] - r[1]) * 2 // 5
            x, y = r[0] + ((r[2] - r[0]) - cw) // 2, r[1] + ((r[3] - r[1]) - ch) // 2
            return (x, y, x + cw, y + ch)

        def _register_keys(self) -> None:
            hk = self.cfg.hotkeys
            errors = self.hotkeys.register({"peek": hk.peek, "refresh": hk.refresh, "toggle": hk.toggle_visible,
                                            "history": hk.history, "vision": hk.vision,
                                            # 输入框翻译打开时才占用它的快捷键
                                            "input": hk.input if self.cfg.input.enabled else ""})
            try:
                self._drag_mods = parse_modifiers(hk.drag_modifiers)
            except ValueError as e:
                errors.append(str(e))
                self._drag_mods = []
            if errors:
                self.tray.showMessage(tr("部分快捷键不可用"), "\n".join(errors), QSystemTrayIcon.MessageIcon.Warning, 8000)
                log.warning("快捷键：%s", errors)

        def _on_tray(self, reason) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                self.toggle_visible()

        # -------------------------------------------------------------- 事件
        def _on_snapshot(self, snap) -> None:
            self.state.snapshot = snap
            if not self.state.hidden and not self.state.paused:
                for o in self.overlays:
                    o.repaint_mirror()
            self._update_status(snap)
            self._count_engine_usage()
            if not self.state.paused:
                self._feed_history(snap)

        def _lang_label(self) -> str:
            return f"{tr(config.SOURCE_SHORT[self.cfg.source_lang])}→{tr(config.TARGET_SHORT[self.cfg.target_lang])}"

        def _lang_menu(self, pos) -> None:
            """标签上的语言按钮：手动指定原文语言和译成的语言，立即生效。"""
            menu = QMenu()
            menu.addSection(tr("原文"))
            for code, name in config.SOURCE_LANGS.items():
                act = menu.addAction(tr(name), lambda c=code: self.set_languages(c, self.cfg.target_lang))
                act.setCheckable(True)
                act.setChecked(code == self.cfg.source_lang)
            menu.addSection(tr("译成"))
            for code, name in config.LANGUAGES.items():
                act = menu.addAction(name, lambda c=code: self.set_languages(self.cfg.source_lang, c))
                act.setCheckable(True)
                act.setChecked(code == self.cfg.target_lang)
            menu.exec(pos)

        def set_languages(self, source: str, target: str) -> None:
            if (source, target) == (self.cfg.source_lang, self.cfg.target_lang):
                return
            self.cfg.source_lang, self.cfg.target_lang = source, target
            self.engine.set_languages()
            for f in self.frames:
                f.set_lang_label(self._lang_label())
            self._save_timer.start()

        def look(self, f: MirrorFrame | None = None, region: tuple | None = None) -> None:
            """看图翻译：把镜框里的画面（原样，不带译文）发给能看图的模型，结果在弹出窗口里一段段出来。
            发给本机以外的服务前，每次都先问。"""
            from . import vision
            vc = self.cfg.vision
            region = tuple(region or (f or self.frame).mirror)
            local = vision.is_local(vc.base_url)
            if not local and not self._confirm(
                    tr("这张截图会发给 {host}（模型 {model}），截图里看得见的内容都会发出去。\n\n要发送吗？")
                    .format(host=vision.host_of(vc.base_url), model=vc.model)):
                return
            try:
                img = self._grab_region(region, translated=False)
            except Exception as e:  # noqa: BLE001
                self.tray.showMessage(tr("桌面魔镜"), tr("截图失败：{error}").format(error=e),
                                      QSystemTrayIcon.MessageIcon.Warning, 4000)
                return
            self._cancel_look()                     # 上一次还没完：不要了
            cancel = self._look_cancel = threading.Event()
            self._look_region = region
            who = (tr("本机 {model}").format(model=vc.model) if local
                   else tr("{host} 的 {model}").format(host=vision.host_of(vc.base_url), model=vc.model))
            self.vision_panel.start(img, who)
            bgr = _qimage_bgr(img)
            target, source = self.cfg.target_lang, self.cfg.source_lang

            def work() -> None:
                err, secs = "", 0.0
                try:
                    b64, _w, _h = vision.encode_image(bgr, vc.max_side)
                    secs = vision.stream_vision(vc, target, source, b64,
                                                lambda s: None if cancel.is_set() else self.vision_piece.emit(s),
                                                cancel)
                except vision.ServiceError as e:
                    err = str(e)
                except Exception as e:  # noqa: BLE001
                    log.exception("看图翻译出错")
                    err = tr("内部错误：{name}").format(name=type(e).__name__)
                if not cancel.is_set():
                    self.vision_done.emit(err, secs)
            threading.Thread(target=work, name="vision", daemon=True).start()

        def _cancel_look(self) -> None:
            if self._look_cancel is not None:
                self._look_cancel.set()
                self._look_cancel = None

        def _confirm(self, text: str) -> bool:
            box = QMessageBox(QMessageBox.Icon.Question, tr("桌面魔镜"), text,
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            box.button(QMessageBox.StandardButton.Yes).setText(tr("发送"))
            box.button(QMessageBox.StandardButton.No).setText(tr("不发"))
            return box.exec() == QMessageBox.StandardButton.Yes

        def open_guide(self) -> None:
            """新手指南：选翻译服务、讲清楚怎么用。第 2 步、第 4 步的选择立即生效。"""
            if self.guide is not None and self.guide.isVisible():
                self.guide.raise_()
                self.guide.activateWindow()
                return
            g = self.guide = GuideDialog(self.cfg)
            g.apply_language.connect(self._guide_language)
            g.apply_llm.connect(self._guide_llm)
            g.apply_scope.connect(self.set_scope)
            g.guide_done.connect(self._guide_done)
            g.show()
            g.raise_()

        def open_about(self) -> None:
            if self.about is None:
                self.about = AboutDialog()
                self.about.page.guide_requested.connect(self.open_guide)
                self.about.page.update_requested.connect(lambda: self.open_update())
            self.about.show()
            self.about.raise_()
            self.about.activateWindow()

        def _guide_llm(self, llm) -> None:
            self.cfg.llm = llm
            self.engine.update_llm(self.cfg)
            self._save_timer.start()

        def _guide_done(self) -> None:
            if self.cfg.first_run_tip:
                self.cfg.first_run_tip = False
                self._save_timer.start()

        def toggle_pause(self) -> None:
            """暂停：魔镜框还在，不截屏、不识别、不翻译（不花翻译费用），也不画译文；继续时重新核对画面。"""
            paused = self.state.paused = not self.state.paused
            self._apply_working()
            self.act_pause.setText(tr("继续翻译") if paused else tr("暂停（框留着，不识别、不翻译）"))
            status = (tr(PAUSED_TEXT), "paused") if paused else (tr("继续工作，正在核对画面…"), "busy")
            for f in self.frames:
                f.set_paused(paused)
                f.set_status(*status)
            self.tip.hide()
            for o in self.overlays:
                o.repaint_mirror()

        def _feed_history(self, snap) -> None:
            """镜内出现的译文记进历史面板（同一块同一版本只记一次）。"""
            from .textutil import cache_key
            mirrors = self.state.mirrors or [self.state.mirror]
            for it in snap.items:
                if (it.bid, it.version) in self._hist_seen or not any(geom.overlaps(it.rect, m) for m in mirrors):
                    continue
                self._hist_seen.add((it.bid, it.version))
                self.history.add(cache_key(it.src), it.src, it.text)
            if len(self._hist_seen) > 20000:
                self._hist_seen.clear()

        def toggle_history(self) -> None:
            if self.history.isVisible():
                self.history.hide()
            else:
                self.history.show()
                self.history.raise_()

        def _count_usage(self, s: dict) -> None:
            """当天发给翻译服务的请求数、字数和 token（只有数量），显示在托盘提示和魔镜标签上，跨重启累计。"""
            now = (int(s.get("requests", 0)), int(s.get("sent_chars", 0)), int(s.get("tok_in", 0)),
                   int(s.get("tok_out", 0)), int(s.get("tok_cached", 0)))
            delta = [a - b for a, b in zip(now, self._usage_seen)]
            if any(d < 0 for d in delta):    # 引擎重建过：从头计
                delta = [max(0, a) for a in now]
            self._usage_seen = now
            u = self.cfg.usage
            today = time.strftime("%Y-%m-%d")
            if u.date != today:
                u.date, u.requests, u.chars, u.estimated = today, 0, 0, False
                u.tokens_in = u.tokens_out = u.tokens_cached = 0
            if any(delta):
                u.requests += delta[0]
                u.chars += delta[1]
                u.tokens_in += delta[2]
                u.tokens_out += delta[3]
                u.tokens_cached += delta[4]
            if s.get("tok_est") and delta[2]:
                u.estimated = True
            self._check_budget()
            local = config.is_local_url(self.cfg.llm.base_url)
            where = tr("本机") if local else _host_of(self.cfg.llm.base_url)
            tip = tr("桌面魔镜 · 今天发给翻译服务（{where}）{requests} 次、{chars} 字，↑{tin} ↓{tout} token").format(
                where=where, requests=u.requests, chars=u.chars, tin=_short_num(u.tokens_in),
                tout=_short_num(u.tokens_out))
            if tip != self._usage_tip:
                self._usage_tip = tip
                self.tray.setToolTip(tip)
            self._update_meter()

        def _update_meter(self) -> None:
            """魔镜标签上的 token 用量（像网速监控：↑ 输入 ↓ 输出），鼠标停在上面看明细。"""
            u, g = self.cfg.usage, self.cfg.guard
            approx = "≈" if u.estimated else ""
            text = f"{approx}↑{_short_num(u.tokens_in)} ↓{_short_num(u.tokens_out)}" if g.show_meter else ""
            local = config.is_local_url(self.cfg.llm.base_url)
            lines = [tr("今天（{date}）用掉的 token：输入 {tin}，输出 {tout}").format(
                         date=u.date or time.strftime("%Y-%m-%d"), tin=f"{u.tokens_in:,}", tout=f"{u.tokens_out:,}"),
                     tr("翻译服务：{where} · {model}").format(
                         where=tr("本机") if local else _host_of(self.cfg.llm.base_url), model=self.cfg.llm.model),
                     tr("请求 {requests} 次，原文 {chars} 字").format(requests=u.requests, chars=u.chars)]
            if u.tokens_cached:
                lines.insert(1, tr("输入里命中服务商缓存 {cached}（{pct}%，按低得多的价格计费）").format(
                    cached=f"{u.tokens_cached:,}", pct=round(100 * u.tokens_cached / max(1, u.tokens_in))))
            lines.append(tr("每次请求的明细：logs 文件夹里的 usage-*.jsonl（只有数量，没有文字）"))
            if u.estimated:
                lines.append(tr("≈：服务没有报用量的部分是按字数估算的"))
            if local:
                lines.append(tr("本机服务不花钱，不受每日上限限制"))
            elif g.daily_tokens:
                lines.append(tr("每日上限 {limit} token，到了就停（设置 → 范围与隐私）").format(limit=f"{g.daily_tokens:,}"))
            tip = "\n".join(lines)
            for f in self.frames:
                f.set_meter(text, tip)

        def _count_field_usage(self, u: dict) -> None:
            """输入框翻译用掉的 token 也算进今天的用量（和每日上限）；用量日志照样只记数量。"""
            from . import usagelog
            self._count_engine_usage()                  # 先按日期换天
            us = self.cfg.usage
            us.requests += 1
            us.chars += int(u["chars"])
            us.tokens_in += int(u["tokens_in"])
            us.tokens_out += int(u["tokens_out"])
            us.tokens_cached += int(u["cached"])
            if not u["exact"]:
                us.estimated = True
            self._count_engine_usage()                  # 托盘提示、标签上的用量、每日上限
            usagelog.write(model=self.cfg.llm.model, host=usagelog.host_of(self.cfg.llm.base_url), app=u["app"],
                           kind="input", segments=u["segments"], chars=u["chars"], tokens_in=u["tokens_in"],
                           tokens_out=u["tokens_out"], cached=u["cached"], exact=u["exact"], secs=u["secs"])

        def _show_field_tip(self, text: str, level: str, anchor, ms: int) -> None:
            """输入框翻译的提示：贴在输入框光标下面（下面放不下就放上面），过一会儿自己消失。"""
            color = {"busy": "#3d8bfd", "ok": "#3fb950", "err": "#e5534b"}.get(level, "#3d8bfd")
            t = self.field_tip
            t.setStyleSheet("QLabel{background:#202329;color:#f2f4f8;border:1px solid %s;border-radius:6px;"
                            "padding:5px 9px;font:13px 'Microsoft YaHei UI';}" % color)
            t.setText(text)
            t.adjustSize()
            x, y = int(anchor[0]), int(anchor[3]) + 6
            for m in winapi.monitors():
                if geom.contains_pt(m.rect, anchor[0], anchor[1]):
                    l, top, r, b = m.work
                    if y + t.height() > b:
                        y = int(anchor[1]) - 6 - t.height()
                    x = max(l, min(x, r - t.width()))
                    y = max(top, y)
                    break
            t.move(x, y)
            t.show()
            if ms:
                self._field_tip_timer.start(ms)
            else:
                self._field_tip_timer.stop()

        def _check_budget(self) -> None:
            """云端服务今天的 token 用到上限：停止发新的翻译请求（已有译文照常显示），换天或调高上限后自动恢复。"""
            u, limit = self.cfg.usage, self.cfg.guard.daily_tokens
            hit = (limit > 0 and not config.is_local_url(self.cfg.llm.base_url)
                   and u.date == time.strftime("%Y-%m-%d") and u.tokens_in + u.tokens_out >= limit)
            if hit == self._budget_hit:
                return
            was, self._budget_hit = self._budget_hit, hit
            self.engine.set_budget_hit(hit)
            self.field.budget_hit = hit
            if hit and was is False:          # 改了别的设置重新判断时不重复提示
                log.warning("今天的 token 已用到上限 %d", limit)
                self.tray.showMessage(tr("桌面魔镜"), tr(
                    "今天发给翻译服务的 token 已经用到上限（{limit}），先停止翻译新的文字。"
                    "可以在 设置 → 范围与隐私 里调高或关掉上限，明天自动恢复。").format(limit=f"{limit:,}"),
                    QSystemTrayIcon.MessageIcon.Warning, 10000)

        def _apply_working(self) -> None:
            """截屏、识别、翻译要不要跑：用户暂停、截图模式、锁屏 / 屏保、魔镜都收成球时都停下。"""
            self.engine.set_working(not self.state.paused and not self.state.shot_mode and not self._away
                                    and not self._all_docked())

        def _guard_tick(self) -> None:
            """省钱保护：锁屏、屏保时完全停下；一段时间没碰键盘鼠标就只翻镜框里的（不在后台预译别处）。"""
            g = self.cfg.guard
            try:
                away = g.pause_when_locked and winapi.away()
                idle = winapi.idle_seconds()
            except OSError:
                return
            if away != self._away:
                self._away = away
                log.info("锁屏 / 屏保：停下" if away else "回来了：继续")
                self._apply_working()
                self._update_status(self.state.snapshot)
            frugal = g.idle_min > 0 and idle >= g.idle_min * 60
            if frugal != self._frugal:
                self._frugal = frugal
                self.engine.set_frugal(frugal)
            self._count_engine_usage()

        def _count_engine_usage(self) -> None:
            """直接读引擎的计数（暂停时引擎不发快照，暂停前发出的请求回来了也要记上）。"""
            svc = self.engine.service
            self._count_usage({"requests": svc["requests"], "sent_chars": svc.get("chars", 0),
                               "tok_in": svc["tok_in"], "tok_out": svc["tok_out"], "tok_cached": svc["tok_cached"],
                               "tok_est": svc["tok_est"]})

        def _update_status(self, snap) -> None:
            if self.state.paused:
                for f in self.frames:
                    f.set_status(tr(PAUSED_TEXT), "paused")
                return
            if self.state.shot_mode:
                for f in self.frames:
                    f.set_status(tr("截图模式：译文暂停更新"), "paused")
                return
            if self._away:
                for f in self.frames:
                    f.set_status(tr("锁屏或屏保中：已停下，回来自动继续"), "paused")
                return
            if snap is None:
                return
            for f in self._active_frames():
                f.set_status(*self._status_for(snap, f.mirror))

        def _status_for(self, snap, mirror) -> tuple[str, str]:
            s = snap.status
            # 只数在这个魔镜里露出来的部分
            shown = [failed for sr, cl, failed in snap.pending
                     if any(geom.overlaps(c, sr) and geom.overlaps(geom.inter(c, sr), mirror) for c in cl)]
            in_pending = sum(1 for failed in shown if not failed)
            in_failed = sum(1 for failed in shown if failed)
            if s.get("error"):
                text, level = s["error"], "error"
            elif s.get("ocr") == "starting":
                text, level = tr("正在启动文字识别…"), "busy"
            elif s.get("paused"):
                text, level = tr("翻译已暂停：{msg}（点 ⟳ 重试或改设置）").format(msg=s.get("service_msg")), "error"
            elif s.get("budget"):
                text, level = tr("今天的 token 已用到上限，停止翻译新文字（设置里可调）"), "error"
            elif s.get("service") == "error":
                text, level = tr("翻译服务出错，稍后自动重试：{msg}").format(msg=s.get("service_msg")), "warn"
            elif in_failed:
                text, level = tr("{n} 块翻译失败，点 ⟳ 重试").format(n=in_failed), "warn"
            elif in_pending:
                text, level = tr("翻译中：镜内还有 {n} 块").format(n=in_pending), "busy"
            elif s.get("needs", 0) and s.get("ocr") == "busy":
                text, level = tr("正在识别桌面文字…"), "busy"
            else:
                text, level = tr("就绪 · 已翻译 {n} 块").format(n=s.get("done", 0)), "ok"
            if s.get("slow") and level == "ok":
                text, level = text + tr(" · 服务较慢"), "warn"
            if s.get("frugal") and level in ("ok", "busy"):
                text += tr(" · 你不在：只翻镜框里的（省钱）")
            if s.get("chat_in_mirror") and level in ("ok", "busy"):
                text += tr(" · 聊天窗口默认不翻译（右键标签可打开）")
            elif s.get("excluded_in_mirror") and level in ("ok", "busy"):
                text += tr(" · 镜内有不翻译的窗口（排除名单）")
            return text, level

        def _on_rect(self, rect, final: bool) -> None:
            self._on_frame_rect(self.frame, rect, final)

        def _on_frame_rect(self, f: MirrorFrame, rect, final: bool) -> None:
            old, f.shown_rect = f.shown_rect, rect
            self._sync_mirrors()
            for o in self.overlays:
                o.repaint_mirror(old)
            if f.bound is not None and final:
                # 跟随窗口时用户手动挪了魔镜：按新位置重新记相对位置
                hwnd, _rel, wr = f.bound
                W, H = max(1, wr[2] - wr[0]), max(1, wr[3] - wr[1])
                f.bound = (hwnd, ((rect[0] - wr[0]) / W, (rect[1] - wr[1]) / H, (rect[2] - wr[0]) / W,
                                  (rect[3] - wr[1]) / H), wr)
            if final:
                self._save_mirrors()

        def _on_hotkey(self, action: str) -> None:
            if action == "peek":
                self.peek.start(self.cfg.hotkeys.peek)
            elif action == "refresh":
                self.refresh()
            elif action == "toggle":
                self.toggle_visible()
            elif action == "history":
                self.toggle_history()
            elif action == "vision":
                self.look()
            elif action == "input":
                self.field.hotkey()

        def _on_peek(self, on: bool) -> None:
            self.state.peek = on
            for o in self.overlays:
                o.repaint_mirror()

        def _on_debug(self, on: bool) -> None:
            self.state.debug = on
            for o in self.overlays:
                o.repaint_mirror()

        def refresh(self, f: MirrorFrame | None = None) -> None:
            for fr in ([f] if f is not None else self._active_frames()):
                self.engine.request_refresh(fr.mirror)

        def set_scope(self, code: str) -> None:
            self.cfg.scope.mode = code
            for c, act in self.scope_actions.items():
                act.setChecked(c == code)
            self._save()

        def exclude_app_under_mirror(self) -> None:
            """把魔镜中心下面那个窗口的程序加进“不翻译”名单。"""
            cx, cy = geom.center(self.state.mirror)
            name = ""
            for w in winapi.top_level_windows(skip_pid=os.getpid()):
                if geom.contains_pt(w.rect, cx, cy):
                    name = winapi.process_name(w.pid)
                    break
            if not name:
                self.tray.showMessage(tr("桌面魔镜"), tr("魔镜下面没有找到窗口（或拿不到它的程序名）。"),
                                      QSystemTrayIcon.MessageIcon.Warning, 4000)
                return
            if name.lower() not in {a.lower() for a in self.cfg.scope.exclude_apps}:
                self.cfg.scope.exclude_apps = self.cfg.scope.exclude_apps + [name]
                self._save()
            self.tray.showMessage(tr("桌面魔镜"),
                                  tr("已把 {name} 加入不翻译名单：它的窗口不再识别和翻译。可在 设置 → 范围与隐私 里移除。")
                                  .format(name=name), QSystemTrayIcon.MessageIcon.Information, 5000)

        def take_shot(self, kind: str, f: MirrorFrame | None = None) -> None:
            """截下镜框内的画面：原图（屏幕原样）或译图（叠上译文，和镜里看到的一样）。
            复制到剪贴板，同时存到“图片”里的“桌面魔镜”文件夹（用户点按钮才保存）。"""
            from pathlib import Path

            from PySide6.QtCore import QStandardPaths
            region = (f or self.frame).mirror
            try:
                img = self._grab_region(region, translated=(kind == "trans"))
            except Exception as e:  # noqa: BLE001
                log.warning("截图失败：%s", e)
                self.tray.showMessage(tr("截图失败"), str(e), QSystemTrayIcon.MessageIcon.Warning, 5000)
                return
            qapp.clipboard().setImage(img)
            pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
            folder = (Path(pics) if pics else ROOT) / tr("桌面魔镜")
            stem = time.strftime((tr("魔镜译图") if kind == "trans" else tr("魔镜原图")) + "_%Y%m%d_%H%M%S")
            try:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{stem}.png"
                n = 2
                while path.exists():
                    path = folder / f"{stem}_{n}.png"
                    n += 1
                saved = img.save(str(path))
            except OSError:
                saved = False
            title = tr("已截译图") if kind == "trans" else tr("已截原图")
            if saved:
                self._last_shot = str(path)
                log.info("已保存截图：%s", path)
                self._on_click_message(self._open_last_shot)
                self.tray.showMessage(title, tr("已复制到剪贴板，并保存到 {path}（点这条提示打开文件夹）").format(path=path),
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
            else:
                self.tray.showMessage(title, tr("已复制到剪贴板；保存到 {folder} 失败。").format(folder=folder),
                                      QSystemTrayIcon.MessageIcon.Warning, 5000)

        def _on_click_message(self, action) -> None:
            """接下来这条托盘提示被点了做什么（只在它显示的这一会儿有效）。"""
            self._message_action, self._message_until = action, time.monotonic() + 20

        def _on_message_clicked(self) -> None:
            if self._message_action is not None and time.monotonic() < self._message_until:
                self._message_action()

        # -------------------------------------------------------------- 更新
        def _start_update_checks(self) -> None:
            """启动后：报一下刚才的更新结果，过一会儿清掉更新留下的文件，按设置在后台查一次新版本。"""
            done = updater.take_result()
            if done:
                log.info("已从 %s 更新到 %s", done.get("from"), done.get("to"))
                QTimer.singleShot(2000, lambda: self.tray.showMessage(tr("桌面魔镜"), tr(
                    "已更新到 {new}（原来是 {old}）。").format(new=done.get("to", ""), old=done.get("from", "")),
                    QSystemTrayIcon.MessageIcon.Information, 6000))
            QTimer.singleShot(30_000, lambda: threading.Thread(target=updater.cleanup, daemon=True).start())
            self.update_found.connect(self._on_update_found)
            QTimer.singleShot(15_000, self._auto_check_update)

        def _auto_check_update(self) -> None:
            """一天最多查一次；有新版本只在托盘提示，点了才打开检查更新的窗口（下载要用户再点）。"""
            today = time.strftime("%Y-%m-%d")
            if not self.cfg.update.auto_check or self.cfg.update.last_check == today:
                return
            self.cfg.update.last_check = today
            self._save_timer.start()
            skip = self.cfg.update.skip_version

            def work() -> None:
                try:
                    rel = updater.latest_release()
                except updater.UpdateError as e:
                    log.info("自动检查更新没成功：%s", e)
                    return
                if updater.is_newer(rel.version) and rel.version != skip:
                    self.update_found.emit(rel)
            threading.Thread(target=work, daemon=True).start()

        def _on_update_found(self, rel) -> None:
            log.info("有新版本 %s", rel.version)
            self._on_click_message(lambda: self.open_update(rel))
            self.tray.showMessage(tr("桌面魔镜"), tr("有新版本 {new}（现在是 {old}）：点这条提示看看更新了什么。").format(
                new=rel.version, old=__version__), QSystemTrayIcon.MessageIcon.Information, 10_000)

        def open_update(self, release=None, auto_start: bool = False) -> None:
            if self.update_dialog is not None and self.update_dialog.isVisible():
                self.update_dialog.raise_()
                self.update_dialog.activateWindow()
                return
            dlg = UpdateDialog(release)
            dlg.auto_start = auto_start
            dlg.install_ready.connect(self._install_update)
            dlg.skip_requested.connect(self._skip_update)
            self.update_dialog = dlg
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            if auto_start and dlg.release is not None:
                dlg._show_release()

        def _install_update(self, new_app) -> None:
            """下载、解压好了（源码版是用户确认了）：起助手进程，自己退出，由它换上新版本再打开。"""
            try:
                updater.start_helper(new_app, os.getpid(), restart=True)
            except OSError as e:
                log.exception("起不来更新助手")
                QMessageBox.warning(None, tr("桌面魔镜"), tr("没法开始更新：{error}").format(error=e))
                return
            log.info("交给更新助手换新版本，退出")
            QTimer.singleShot(300, self.quit_app)

        def _skip_update(self, version: str) -> None:
            self.cfg.update.skip_version = version
            self._save_timer.start()

        def _open_last_shot(self) -> None:
            if self._last_shot and os.path.exists(self._last_shot):
                import subprocess
                subprocess.Popen(["explorer", "/select,", self._last_shot])

        def _grab_region(self, region: tuple, translated: bool, with_frame: bool = False):
            """截屏（本程序的窗口对截屏隐身，截到的就是原样）；translated 时用同一套绘制代码叠上译文，
            with_frame 时再叠上魔镜边框——就是用户此刻看到的画面。"""
            import mss
            import numpy as np
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QImage
            l, t, r, b = region
            with mss.MSS() as s:
                shot = s.grab({"left": l, "top": t, "width": r - l, "height": b - t})
            arr = np.frombuffer(shot.bgra, np.uint8).reshape(b - t, r - l, 4).copy()
            img = QImage(arr.data, r - l, b - t, (r - l) * 4, QImage.Format.Format_RGB32).copy()
            widgets = (list(self.overlays) if translated else []) + \
                ([fr.visual() for fr in self.frames if fr.isVisible()] if with_frame else [])
            if widgets:
                p = QPainter(img)
                for w in widgets:
                    g = w.geometry()
                    wr = (g.x(), g.y(), g.x() + g.width(), g.y() + g.height())
                    c = geom.inter(wr, region)
                    if geom.empty(c):
                        continue
                    pm = layered.grab(w, QRect(c[0] - wr[0], c[1] - wr[1], c[2] - c[0], c[3] - c[1]))
                    p.drawPixmap(c[0] - l, c[1] - t, pm)
                p.end()
            return img

        def toggle_visible(self) -> None:
            self.state.hidden = not self.state.hidden
            for f in self.frames:
                f.dock.set_hidden(self.state.hidden)
                f.setVisible(not self.state.hidden and not f.suspended and not f.dock.docked)
            self.act_toggle.setText(tr("显示魔镜") if self.state.hidden else tr("隐藏魔镜"))
            for o in self.overlays:
                o.update()

        def open_settings(self) -> None:
            if self._settings is not None and self._settings.isVisible():
                self._settings.raise_()
                return
            dlg = SettingsDialog(self.cfg)
            dlg.guide_requested.connect(self.open_guide)
            dlg.update_requested.connect(lambda: self.open_update())
            self._settings = dlg

            def done(result: int) -> None:
                if result:
                    new = config.validate(dlg.collect())
                    self._keep_mirrors(new)
                    new.usage = self.cfg.usage      # 设置窗口打开期间的用量照样累计
                    new.update.skip_version = self.cfg.update.skip_version
                    self.apply_config(new, clear_memory=dlg.clear_memory_requested)
                    if dlg.autostart.isChecked() != dlg.autostart_was:
                        self.set_autostart(dlg.autostart.isChecked())
                self._settings = None
            dlg.finished.connect(done)
            dlg.show()

        def set_autostart(self, on: bool) -> None:
            """开机自动启动：写进 / 删掉 Windows 的启动项（不在配置文件里）。"""
            try:
                boot.set_enabled(on)
            except OSError as e:
                log.warning("开机启动项写不进去：%s", e)
                self.tray.showMessage(tr("桌面魔镜"), tr("开机启动没设上：{error}").format(error=e),
                                      QSystemTrayIcon.MessageIcon.Warning, 6000)
                return
            log.info("开机自动启动：%s", "打开" if on else "关闭")

        def apply_config(self, new, save: bool = True, clear_memory: bool = False) -> None:
            """换上新的设置（设置窗口点了确定，或者配置文件被命令行改了），能马上生效的马上生效。"""
            if not new.ui_lang:
                new.ui_lang = i18n.ui_lang_for(new.target_lang)
            new.update.last_check = self.cfg.update.last_check      # 程序自己记的
            langs_changed = (new.source_lang, new.target_lang) != (self.cfg.source_lang, self.cfg.target_lang)
            ui_changed = new.ui_lang != i18n.ui_lang()
            need_restart = any(config.get_key(new, k) != config.get_key(self.cfg, k) for k in config.RESTART_KEYS)
            old_terms = {(g["src"], g["dst"], g.get("app", "")) for g in self.cfg.glossary}
            new_terms = {(g["src"], g["dst"], g.get("app", "")) for g in new.glossary}
            changed = sorted({t[0] for t in old_terms ^ new_terms})
            self.cfg.__dict__.update(new.__dict__)
            if changed:      # 配置换好之后再通知：重新翻译时一定用新术语表
                self.engine.inbox.put(("glossary", changed))
            for c, act in self.scope_actions.items():
                act.setChecked(c == self.cfg.scope.mode)
            self.act_chat.blockSignals(True)
            self.act_chat.setChecked(self.cfg.scope.translate_chat)
            self.act_chat.blockSignals(False)
            self.state.renderer.set_style(self.cfg.style)
            self.state.frame_color = QColor(self.cfg.style.border_color)
            for f in self.frames:
                if f.color != QColor(self.cfg.style.border_color):
                    f.color = QColor(self.cfg.style.border_color)
                    f.update()
            self._apply_skin()
            self.engine.update_llm(self.cfg)
            if clear_memory:
                self.engine.inbox.put(("memory_clear", None))
            if langs_changed:
                self.engine.set_languages()
                for f in self.frames:
                    f.set_lang_label(self._lang_label())
            if ui_changed:
                self.apply_ui_lang(self.cfg.ui_lang)
            self.field.apply(self.cfg)
            self._register_keys()
            self._budget_hit = None             # 上限可能改了：重新判断，并且一定告诉引擎
            self._check_budget()
            self._update_meter()
            if save:
                self._save()
            for o in self.overlays:
                o.update()                      # 球的颜色也可能换了
            if need_restart:
                self.tray.showMessage(tr("桌面魔镜"), tr("识别设备、屏幕范围和滚动跟随的更改在下次启动时生效。"),
                                      QSystemTrayIcon.MessageIcon.Information, 5000)

        def _tick(self) -> None:
            now = time.perf_counter()
            self._follow_windows()
            mods = bool(self._drag_mods) and modifiers_down(self._drag_mods) and not self.state.hidden
            under = self._frame_at(*winapi.cursor_pos()) if mods else None
            for f in self.frames:
                f.set_grab_mode(mods and (f is under or f._drag is not None))
            self._hover_tip(now)
            self._glass_tick(now)
            if now - self._last_cfg_check > 1.0:
                self._last_cfg_check = now
                self._check_config_file()
                if self._quit_event and _k32.WaitForSingleObject(self._quit_event, 0) == 0:
                    log.info("命令行请魔镜退出（要更新）")
                    self.quit_app()
            if now - self._last_topmost > 2.0:
                self._last_topmost = now
                for o in self.overlays:
                    winapi.keep_topmost(int(o.winId()))
                if not self.state.hidden:
                    for f in self._active_frames():
                        winapi.keep_topmost(int(f.winId()))
                        if f.visual() is not f:                  # 色键窗口：看得见的那层压在接鼠标的那层上面
                            winapi.keep_topmost(int(f.visual().winId()))
                    for f in self.frames:
                        if f.dock.docked and f.dock.ball.isVisible():
                            winapi.keep_topmost(int(f.dock.ball.winId()))

        def _glass_tick(self, now: float) -> None:
            """液态玻璃：边框、标签、球后面的画面变了就重新折射（截图模式下魔镜截得到自己，不更新）。"""
            if not glass.active() or now - self._glass_t < 1 / 30:       # 后面一直在变（滚动、视频）时每秒最多 30 次
                return
            self._glass_t = now
            self.backdrop.frozen = self.state.shot_mode
            self.backdrop.begin()
            if self.state.hidden:
                return
            for f in self.frames:
                f.glass_refresh(now)
                f.dock.glass_refresh(now)
            self._glass_ms.append((time.perf_counter() - now) * 1000)

        def _apply_skin(self) -> None:
            """换皮肤（经典 / 液态玻璃）：边框宽度、标签位置跟着变，全部重画。"""
            on = self.cfg.style.skin == "glass"
            if on == glass.active():
                return
            glass.set_active(on)
            log.info("皮肤：%s", "液态玻璃" if on else "经典")
            if not on:
                self.backdrop.close()
                self.state.balls.clear()
            for f in self.frames:
                f._rim = f._pill = None
                f._layout()
                f.visual().update()
                f.dock.glass_refresh(time.perf_counter(), force=True)
            for o in self.overlays:
                o.update()

        def _hover_tip(self, now: float) -> None:
            """鼠标停在被截断的译文上时，显示全文；停在标签上的 token 用量上时，显示明细。"""
            snap = self.state.snapshot
            x, y = winapi.cursor_pos()
            meter = next((f for f in self._active_frames() if f.meter_hovered and f.isVisible()), None)
            if meter is not None:
                if self._tip_bid != -1:
                    self._tip_bid = -1
                    self.tip.setText(meter.meter_tip)
                    self.tip.adjustSize()
                    self._place_tip(x, y)
                    self.tip.show()
                return
            if self._tip_bid == -1:
                self._tip_bid = 0
                self.tip.hide()
            ball = next((f.dock for f in self.frames if f.dock.docked and f.dock.hover_t and not f.dock.busy
                         and f.dock.ball.isVisible()), None)
            if ball is not None:
                # 鼠标停在收起的球上：说一下怎么用
                if self._tip_bid != -2 and now - ball.hover_t > 0.6:
                    self._tip_bid = -2
                    self.tip.setText(tr(BALL_TIP))
                    self.tip.adjustSize()
                    self._place_tip(x, y)
                    self.tip.show()
                return
            if self._tip_bid == -2:
                self._tip_bid = 0
                self.tip.hide()
            target = None
            if snap is not None and not self.state.peek and not self.state.hidden and not self.state.paused \
                    and self._frame_at(x, y) is not None:
                for item in snap.items:
                    if geom.contains_pt(item.room, x, y):
                        r = self.state.renderer.get(item)
                        if r.truncated:
                            target = item
                        break
            if target is None:
                self._hover_since = 0.0
                if self.tip.isVisible():
                    self.tip.hide()
                self._tip_bid = 0
                return
            if self._tip_bid != target.bid:
                self._tip_bid = target.bid
                self._hover_since = now
                self.tip.hide()
                return
            if not self.tip.isVisible() and now - self._hover_since > 0.35:
                self.tip.setText(target.text)
                self.tip.adjustSize()
                self._place_tip(x, y)
                self.tip.show()

        def _place_tip(self, x: int, y: int) -> None:
            """提示放在鼠标右下方；贴着屏幕右边、下边时放到另一侧，别伸出屏幕。"""
            w, h = self.tip.width(), self.tip.height()
            tx, ty = x + 16, y + 20
            for m in winapi.monitors():
                if geom.contains_pt(m.rect, x, y):
                    l, t, r, b = m.work
                    if tx + w > r:
                        tx = x - 12 - w
                    if ty + h > b:
                        ty = y - 12 - h
                    tx, ty = max(l, tx), max(t, ty)
                    break
            self.tip.move(tx, ty)

        def _save_usage(self) -> None:
            u = self.cfg.usage
            if (u.requests, u.chars) != self._usage_saved:
                self._usage_saved = (u.requests, u.chars)
                self._save()

        def _save(self) -> None:
            stamp = self._config_stamp()
            if stamp is not None and stamp != self._cfg_stamp:
                self._reload_config()      # 文件刚被别的程序改过、还没载入：先载入，别把它的改动盖掉
            try:
                config.save(self.cfg)
            except OSError as e:
                log.warning("保存配置失败：%s", e)
            self._cfg_stamp = self._cfg_seen = self._config_stamp()

        @staticmethod
        def _config_stamp() -> tuple | None:
            try:
                st = config.config_path().stat()
                return st.st_mtime_ns, st.st_size
            except OSError:
                return None

        def _check_config_file(self) -> None:
            stamp = self._config_stamp()
            if stamp is not None and stamp != self._cfg_stamp and stamp != self._cfg_seen:
                self._cfg_seen = stamp
                self._reload_timer.start()          # 还在接着改的话重新计时

        def _reload_config(self) -> None:
            """配置文件被别的程序改了（命令行 deskmirror config set 等）：重新载入，能马上生效的马上生效。
            魔镜的位置、当天用量是程序自己记的，用内存里最新的。"""
            self._reload_timer.stop()
            try:
                json.loads(config.config_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # 正在用编辑器改、还没改完（格式不对）：先不载入，照旧用现在的设置，等它下次存好
                self._cfg_stamp = self._cfg_seen = self._config_stamp()
                log.warning("配置文件被改过但格式不对，没有载入")
                return
            new = config.load()
            self._keep_mirrors(new)
            new.usage = self.cfg.usage
            self._cfg_stamp = self._cfg_seen = self._config_stamp()
            log.info("配置文件被别的程序改过，已重新载入")
            self.apply_config(new, save=False)
            self.tray.showMessage(tr("桌面魔镜"), tr("设置已按配置文件更新（命令行或 AI 助手改的）。"),
                                  QSystemTrayIcon.MessageIcon.Information, 4000)

        # -------------------------------------------------------------- 调试控制（自动化测试用）
        def _debug_cmd(self, req: dict) -> dict:
            cmd = req.get("cmd")
            snap = self.state.snapshot
            if cmd == "status":
                st = dict(snap.status) if snap else {}
                st["canvases"] = [list(c[1]) + [c[2], c[0]] for c in st.get("canvases", ())]
                st["usage"] = {"date": self.cfg.usage.date, "requests": self.cfg.usage.requests,
                               "chars": self.cfg.usage.chars}
                return {"mirror": list(self.state.mirror), "status": st,
                        "items": len(snap.items) if snap else 0, "pending": len(snap.pending) if snap else 0,
                        "stamp": snap.stamp if snap else 0, "peek": self.state.peek,
                        "hidden": self.state.hidden, "paused": self.state.paused, "grab": self.frame.grab_mode,
                        "shot_mode": self.state.shot_mode, "colorkey": layered.colorkey(),
                        "skin": "glass" if glass.active() else "classic",
                        "glass_ms": ({"n": len(gm), "avg": round(sum(gm) / len(gm), 2), "max": round(max(gm), 2),
                                      "p95": round(sorted(gm)[int(len(gm) * 0.95)], 2)}
                                     if (gm := list(self._glass_ms)) else None),
                        "frame_hwnds": [[int(f.winId()), int(f.visual().winId())] for f in self.frames],
                        "engine_on": self._engine_on, "working": self.engine.working,
                        "mirrors": [{"rect": list(f.mirror), "bound": f.bound[0] if f.bound else 0,
                                     "suspended": f.suspended, "visible": f.isVisible(), "docked": f.dock.docked,
                                     "edge": f.dock.edge, "tucked": f.dock.tucked, "busy": f.dock.busy,
                                     "ghost": f.ghost, "ball": [f.dock.ball.x(), f.dock.ball.y(),
                                                                f.dock.ball.x() + f.dock.ball.width(),
                                                                f.dock.ball.y() + f.dock.ball.height()],
                                     "ball_visible": f.dock.ball.isVisible(), "saved": f.dock.saved(),
                                     "shape": ([round(v, 1) for v in (sh.x, sh.y, sh.w, sh.h, sh.k)]
                                               if (sh := f.dock.shape()) is not None else None),
                                     "window": [f.x(), f.y(), f.x() + f.width(), f.y() + f.height()],
                                     "glass": {"renders": f.glass_renders, "ball_renders": f.dock.glass_renders,
                                               "dark": bool(f._pill is not None and f._pill.tone.dark),
                                               "ball_at": (list(gb.at) if (gb := self.state.balls.get(id(f.dock)))
                                                           is not None and gb.at is not None else None)}}
                                    for f in self.frames]}
            if cmd == "cfg":
                # 程序此刻用的设置（测热载入用）；API Key 不给
                return {k: config.get_key(self.cfg, k) for k in req.get("keys", ()) if not k.endswith("api_key")}
            if cmd == "update":
                # 打开检查更新的窗口；auto：查到新版本就直接下载、安装（测试用）
                self.open_update(auto_start=bool(req.get("auto")))
                return {"ok": True}
            if cmd == "shotmode":
                self.set_shot_mode(bool(req.get("on", True)))
                return {"ok": True}
            if cmd == "mirror":
                rect = tuple(int(v) for v in req["rect"])
                self.frame.set_mirror(rect)
                self._on_rect(rect, bool(req.get("final", True)))
                return {"ok": True}
            if cmd == "override":
                from .textutil import cache_key
                self.engine.inbox.put(("override", cache_key(req["src"]), req["text"]))
                return {"ok": True}
            if cmd == "glossary":
                old = {g["src"] for g in self.cfg.glossary}
                import copy
                new = copy.deepcopy(self.cfg)
                new.glossary = list(req.get("terms") or [])
                self.cfg.glossary = config.validate(new).glossary
                changed = sorted(old | {g["src"] for g in self.cfg.glossary})
                if changed:
                    self.engine.inbox.put(("glossary", changed))
                return {"ok": True, "n": len(self.cfg.glossary)}
            if cmd == "memory":
                # 和设置窗口点“确定”同一顺序：先换配置（打开/关掉记忆），再清空
                if "enabled" in req:
                    self.cfg.memory.enabled = bool(req["enabled"])
                    self.engine.update_llm(self.cfg)
                if req.get("clear"):
                    self.engine.inbox.put(("memory_clear", None))
                return {"ok": True}
            if cmd == "history":
                es = self.history.entries
                return {"n": len(es), "latest": [{"src": e.src[:80], "text": e.text[:80]} for e in es[:10]]}
            if cmd == "add_mirror":
                self.add_mirror()
                f = self.frames[-1]
                if req.get("rect"):
                    r = tuple(int(v) for v in req["rect"])
                    f.set_mirror(r)
                    self._on_frame_rect(f, r, True)
                return {"ok": True, "index": len(self.frames) - 1}
            if cmd == "close_mirror":
                i = int(req.get("index", -1))
                if 0 < i < len(self.frames):
                    self.close_mirror(self.frames[i])
                return {"ok": True, "count": len(self.frames)}
            if cmd == "bind_mirror":
                f = self.frames[int(req.get("index", 0))]
                if req.get("off"):
                    self.unbind_mirror(f)
                    return {"ok": True}
                return {"ok": self.bind_mirror(f), "hwnd": f.bound[0] if f.bound else 0}
            if cmd == "peek":
                self._on_peek(bool(req.get("on")))
                return {"ok": True}
            if cmd == "scope":
                # 测试脚本改预译范围、排除名单（与设置窗口改的是同一份配置）
                import copy
                new = copy.deepcopy(self.cfg)
                for k, v in (req.get("set") or {}).items():
                    setattr(new.scope, k, v)
                self.cfg.scope = config.validate(new).scope
                return {"ok": True, "scope": {k: getattr(self.cfg.scope, k) for k in ("mode", "near_px")}}
            if cmd == "now":
                return {"t": round(time.perf_counter() - self.engine.started, 4)}  # 与指标日志里的 t 同一时间轴
            if cmd == "refresh":
                self.refresh()
                return {"ok": True}
            if cmd == "quit":
                QTimer.singleShot(0, self.quit_app)
                return {"ok": True}
            if cmd == "settings_snapshot":
                # 设置窗口对截屏隐身：用它自己的渲染结果出图（测试看界面用）
                dlg = SettingsDialog(self.cfg)
                dlg.tabs.setCurrentIndex(int(req.get("tab", 0)))
                dlg.show()
                qapp.processEvents()
                ok = dlg.grab().save(req["path"])
                dlg.close()
                return {"ok": bool(ok), "path": req["path"]}
            if cmd == "blocks_of":
                # 某个窗口（0 = 桌面本身）下的文字块概况，排查“同样内容反复请求”用
                hwnd = int(req.get("hwnd", 0))
                out = []
                for b in list(self.engine.blocks.values()):
                    win = b.canvas.window()
                    if (win.hwnd if win is not None else 0) != hwnd:
                        continue
                    d = {"bid": b.bid, "rect": list(b.screen_rect()), "state": b.state, "ok": b.ok_rect is not None,
                         "created": round(b.created - self.engine.started, 1), "dyn": b.born_dynamic, "counter": b.counter}
                    if req.get("text"):
                        d["text"] = b.text[:60]
                    out.append(d)
                return {"n": len(out), "blocks": out[: int(req.get("limit", 50))]}
            if cmd == "cache_get":
                from .textutil import cache_key
                return {"items": {s: self.engine.cache.get(cache_key(s)) for s in req.get("src", [])}}
            if cmd == "about":
                from .ui.about import REWARD_IMAGE
                self.open_about()
                # 打包后的 exe 要能读 JPG（Qt 的图片插件）
                return {"ok": True, "visible": self.about.isVisible(), "reward_image": not QPixmap(str(REWARD_IMAGE)).isNull()}
            if cmd == "http_check":
                # 打包后的 exe 要能连 HTTPS（SSL 库、根证书）：只取模型列表，不发任何文字
                from .translator import list_models
                names, err = list_models(config.LlmConfig(protocol="openai", base_url=req["url"]))
                return {"models": len(names), "err": err}
            if cmd == "guide":
                self.open_guide()
                if "page" in req and self.guide is not None:
                    self.guide.pages.setCurrentIndex(int(req["page"]))
                if req.get("pick") and self.guide is not None:
                    self.guide.lang_buttons[req["pick"]].click()     # 像用户在第 1 步点了这种语言
                return {"ok": True, "title": self.guide.windowTitle() if self.guide is not None else ""}
            if cmd == "look":
                self.look(region=tuple(req["region"]) if req.get("region") else None)
                return {"ok": True}
            if cmd == "look_result":
                p = self.vision_panel
                return {"running": p.running, "status": p.status.text(), "text": p.text.toPlainText()}
            if cmd == "langs":
                self.set_languages(req.get("source", self.cfg.source_lang), req.get("target", self.cfg.target_lang))
                return {"ok": True, "label": self._lang_label()}
            if cmd == "ui_lang":
                # 换界面语言（和设置里改的是同一处）；顺便返回托盘菜单的字，测试核对用
                if req.get("lang"):
                    self.apply_ui_lang(req["lang"])
                return {"ok": True, "lang": i18n.ui_lang(), "label": self._lang_label(),
                        "menu": [a.text() for a in self._menu.actions() if a.text()],
                        "status": self.frame.status}
            if cmd == "pause_all":
                if bool(req.get("on")) != self.state.paused:
                    self.toggle_pause()
                return {"ok": True, "paused": self.state.paused}
            if cmd == "pause_tr":
                self.engine.pause_translation(bool(req.get("on")))
                return {"ok": True}
            if cmd == "llm":
                import copy
                new = copy.deepcopy(self.cfg)
                for k, v in (req.get("set") or {}).items():
                    setattr(new.llm, k, v)
                new = config.validate(new)
                self.cfg.llm = new.llm
                self.engine.update_llm(self.cfg)
                return {"ok": True, "llm": {k: getattr(self.cfg.llm, k) for k in ("protocol", "base_url", "model")}}
            if cmd == "metrics":
                out = {k: v for k, v in self.engine.metrics.items()}
                import numpy as np
                for name in ("paint_lat", "paint_ms"):
                    arr = np.array(getattr(self.state, name), float)
                    if arr.size:
                        out[name] = {"n": int(arr.size), "p50": float(np.percentile(arr, 50)),
                                     "p95": float(np.percentile(arr, 95)), "max": float(arr.max())}
                if req.get("reset_ui"):
                    self.state.paint_lat.clear()
                    self.state.paint_ms.clear()
                return out
            if cmd == "items":
                region = tuple(req.get("region") or self.state.mirror)
                out = []
                for it in (snap.items if snap else ()):
                    if geom.overlaps(it.rect, region):
                        d = {"bid": it.bid, "v": it.version, "rect": list(it.rect), "clips": [list(c) for c in it.clips],
                             "bg": list(it.bg)}
                        if req.get("text"):
                            d["text"] = it.text
                            d["src"] = it.src
                        if req.get("plates"):
                            # 译文底板实际画多大（译文长时会向下延伸、会缩小字号）
                            img = self.state.renderer.get(it)
                            x, y = it.rect[0] + img.dx, it.rect[1] + img.dy
                            d["plate"] = [x, y, x + img.width, y + img.height]
                            d["truncated"] = img.truncated
                            d["room"] = list(it.room)
                            d["font_px"] = img.font_px
                            d["squash"] = img.squash
                            d["em"] = round(it.em, 1)
                            d["cols"] = [list(c) for c in it.cols]     # 竖排各列字的墨迹（相对原文块）
                            d["align"], d["label"] = it.align, it.label
                            d["ink"] = list(it.ink) if it.ink else None  # 原文墨迹（相对原文块）
                        if req.get("refs") and it.ref is not None:
                            import base64
                            import cv2
                            ok, buf = cv2.imencode(".png", it.ref)
                            if ok:
                                d["ref"] = base64.b64encode(buf.tobytes()).decode("ascii")
                        out.append(d)
                return {"items": out}
            if cmd == "needs_in":
                region = tuple(req.get("region") or self.state.mirror)
                n = 0
                for m in self.engine.mons:
                    r = geom.inter(region, m.rect)
                    if geom.empty(r) or m.needs is None:
                        continue
                    l, t, rr, b = m.local(r)
                    sl = (slice(t // 16, -(-b // 16)), slice(l // 16, -(-rr // 16)))
                    sub = m.needs[sl]
                    pend = sub > 0
                    if req.get("skip_volatile"):
                        # 一直在变的区域（播放中的视频）永远等不到静止，等待“翻译完”时不算它
                        pend &= ~self.engine._volatile_mask(m, time.perf_counter())[sl]
                    n += int(pend.sum())
                    if req.get("list"):
                        import numpy as np
                        ys, xs = np.nonzero(sub > 0)
                        tiles = [(m.origin[0] + (l // 16 + int(x)) * 16, m.origin[1] + (t // 16 + int(y)) * 16)
                                 for y, x in zip(ys[:40], xs[:40])]
                        heat = [round(float(m.heat[t // 16 + int(y), l // 16 + int(x)]), 2) for y, x in zip(ys[:40], xs[:40])]
                        return {"n": n, "tiles": tiles, "heat": heat}
                return {"n": n}
            if cmd == "pending_in":
                region = tuple(req.get("region") or self.state.mirror)
                # 和标签上的“镜内还有 N 块”同一口径：只数在这个区域里露出来的部分
                n = sum(1 for sr, cl, _failed in (snap.pending if snap else ())
                        if any(geom.overlaps(c, sr) and geom.overlaps(geom.inter(c, sr), region) for c in cl))
                return {"n": n}
            if cmd == "pending_blocks":
                # 区域内还没译好的块（排查“一直显示翻译中”用）；text 只在调试时要
                region = tuple(req.get("region") or self.state.mirror)
                out = []
                for b in list(self.engine.blocks.values()):
                    sr = b.screen_rect()
                    if b.state in ("done", "skip") or not geom.overlaps(sr, region):
                        continue
                    win = b.canvas.window()
                    out.append({"bid": b.bid, "state": b.state, "rect": list(sr), "hwnd": win.hwnd if win else 0,
                                "canvas": b.canvas.kind, "ok": b.ok_rect == sr, "attempts": b.attempts,
                                "in_scope": self.engine._in_scope(b, sr),
                                "text": b.text[:40] if req.get("text") else ""})
                return {"n": len(out), "blocks": out[:50]}
            if cmd == "composite":
                return self._composite(req["path"], tuple(req.get("region") or self.state.mirror), bool(req.get("orig")))
            if cmd == "record_start":
                # 按用户看到的样子录视频（演示、宣传片的实录素材）；见 recorder.py
                from .recorder import Recorder
                if self.recorder is not None:
                    return {"error": "already recording"}
                self.recorder = Recorder(req["path"], tuple(int(v) for v in req["region"]), int(req.get("fps", 60)),
                                         self._record_background, self._record_layers,
                                         req.get("codec", "h264_nvenc"), int(req.get("quality", 14)), self)
                return {"ok": True}
            if cmd == "record_cursor":
                if self.recorder is not None:
                    self.recorder.cursor = tuple(req["pos"]) if req.get("pos") else None
                return {"ok": True}
            if cmd == "record_native":
                # 录制时让这个窗口照原样（标题栏、阴影）进截屏，不再另外叠画。
                # 它进了截屏就会被当成桌面内容：只能放在不翻译的地方，别盖住要翻译的窗口。
                w = {"vision": self.vision_panel, "guide": self.guide, "settings": self._settings,
                     "about": self.about, "history": self.history}.get(req.get("window"))
                if w is None:
                    return {"error": "no such window"}
                hwnd = int(w.winId())
                if req.get("on", True):
                    winapi.include_in_capture(hwnd)
                    self._record_native.add(hwnd)
                    if req.get("rect"):
                        x0, y0, x1, y1 = (int(v) for v in req["rect"])
                        w.setGeometry(x0, y0, x1 - x0, y1 - y0)      # 窗口内容区（不含标题栏）
                    if req.get("font_pt"):
                        # 录到视频里字太小看不清：只在录制时把这个窗口的字放大，停止录制时恢复原样
                        self._record_styles.setdefault(hwnd, (w, w.styleSheet()))
                        w.setStyleSheet(f"* {{ font-size: {float(req['font_pt'])}pt; }}")
                else:
                    winapi.exclude_from_capture(hwnd)
                    self._record_native.discard(hwnd)
                    if hwnd in self._record_styles:
                        sw, style = self._record_styles.pop(hwnd)
                        sw.setStyleSheet(style)
                    if req.get("close"):
                        w.hide()
                return {"ok": True}
            if cmd == "record_stop":
                if self.recorder is None:
                    return {"error": "not recording"}
                stats, self.recorder = self.recorder.stop(), None
                self._restore_capture_exclusion()
                return stats
            if cmd == "shot":
                self.take_shot(req.get("kind", "trans"))
                return {"ok": True, "path": self._last_shot}
            if cmd == "buttons":
                # 标签上各按钮、抓手的屏幕位置（测试脚本用真实鼠标去点、去拖）
                f = self.frames[int(req.get("index", 0))]
                ox, oy = f._origin
                out = {n: [r.left() + ox, r.top() + oy, r.right() + 1 + ox, r.bottom() + 1 + oy]
                       for n, r in f._buttons.items()}
                g = f._grip_rect()
                out["grip"] = [g.left() + ox, g.top() + oy, g.right() + 1 + ox, g.bottom() + 1 + oy]
                out["tab"] = list(f._tab)
                return out
            if cmd == "dock":
                # 不要动画直接收成球（spot：{"edge", "x", "y"}，不给就吸到近的一边）；unfold：点开
                f = self.frames[int(req.get("index", 0))]
                if req.get("unfold"):
                    f.dock.unfold()
                else:
                    f.dock.dock_now(req.get("spot"))
                return {"ok": True, "docked": f.dock.docked}
            if cmd == "field":
                # 输入框翻译的状态（测试用）；set：改输入框翻译的设置；hotkey：像按了快捷键一样翻译前台的输入框
                if req.get("set"):
                    import copy
                    new = copy.deepcopy(self.cfg)
                    for k, v in req["set"].items():
                        setattr(new.input, k, v)
                    self.cfg.input = config.validate(new).input
                    self.field.apply(self.cfg)
                    self._register_keys()
                if req.get("hotkey"):
                    self.field.hotkey()
                lst = self.field.listener
                return {"enabled": self.cfg.input.enabled, "listening": bool(lst and lst.ok), "busy": self.field.busy,
                        "memo": len(self.field.memo.pairs), "last": self.field.last, "runs": self.field.runs,
                        "uia": getattr(self.field, "uia_ok", False),
                        "tip": self.field_tip.text() if self.field_tip.isVisible() else ""}
            if cmd == "dock_trace":
                # 吸边动画最近的帧（时间与 now 同一时间轴、形状），验收时量帧间隔、看形状怎么变
                f = self.frames[int(req.get("index", 0))]
                since = float(req.get("since", 0)) + self.engine.started
                rows = [[round(t - self.engine.started, 4), *rest] for t, *rest in f.dock.trace if t >= since]
                if req.get("clear"):
                    f.dock.trace.clear()
                return {"frames": rows}
            return {"error": f"unknown cmd {cmd}"}

        def _record_background(self, region: tuple):
            """录制用的背景：引擎刚截好的屏幕画面（拿着截屏的锁复制一份），不在引擎截的屏上就自己截。"""
            import numpy as np
            for m in self.engine.mons:
                if m.bgra is not None and geom.contains(m.rect, region):
                    l, t, r, b = m.local(region)
                    with m.cap.lock:
                        return m.bgra[t:b, l:r].copy()        # 一定要复制：整行宽时切片是原缓冲区的视图
            import mss
            with mss.MSS() as s:
                shot = s.grab({"left": region[0], "top": region[1], "width": region[2] - region[0],
                               "height": region[3] - region[1]})
            return np.frombuffer(shot.bgra, np.uint8).reshape(region[3] - region[1], region[2] - region[0], 4).copy()

        def _record_layers(self) -> list:
            """录制时叠在屏幕画面上的窗口，从下到上：译文层、魔镜边框、打开着的窗口、提示框。"""
            wins = list(self.overlays) + [f.visual() for f in self.frames if f.isVisible()]
            for w in (self.vision_panel, self.history, self.guide, self.about, self._settings, self.tip):
                if w is not None and w.isVisible() and int(w.winId()) not in self._record_native:
                    wins.append(w)
            return wins

        def _restore_capture_exclusion(self) -> None:
            for hwnd in self._record_native:
                winapi.exclude_from_capture(hwnd)
            self._record_native.clear()
            for sw, style in self._record_styles.values():
                sw.setStyleSheet(style)
            self._record_styles.clear()

        def _composite(self, path: str, region: tuple, orig: bool = False) -> dict:
            """用户此刻看到的画面（截屏 + 译文 + 边框），测试看效果用；orig 时只要屏幕原样（排查识别用）。"""
            (self._grab_region(region, translated=False) if orig else
             self._grab_region(region, translated=True, with_frame=True)).save(path)
            return {"ok": True, "path": path}

        def shutdown(self) -> None:
            log.info("正在退出")
            self.timer.stop()
            self._guard_timer.stop()
            self._count_engine_usage()
            self.hotkeys.unregister_all()
            self._keep_mirrors(self.cfg)
            self._save()
            if self.debug is not None:
                self.debug.close()
            self.engine.stop()
            if self._engine_on:
                self.engine.join(6.0)
            for o in self.overlays:
                o.close()
            for f in self.frames:
                f.dock.close()
                f.close()
            self.tip.close()
            self.field.close()
            self.field_tip.close()
            self.history.close()
            if self.guide is not None:
                self.guide.blockSignals(True)      # 退出程序时关掉的不算看过，下次还会弹出
                self.guide.close()
            if self.about is not None:
                self.about.close()
            self._cancel_look()
            if self.recorder is not None:
                self.recorder.stop()
            self.vision_panel.close()
            self.tray.hide()
            log.info("已退出")

    app = App()
    signal.signal(signal.SIGINT, lambda *_, a=app: a.quit_app())
    # 让 Python 有机会处理 Ctrl+C
    keepalive = QTimer()
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)
    code = qapp.exec()
    signal.signal(signal.SIGINT, signal.SIG_DFL)      # 放开上面对 app 的引用
    del app
    return code
