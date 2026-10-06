"""程序入口：托盘、快捷键、魔镜边框与覆盖层的联动、设置与退出。"""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import signal
import sys
import time

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")  # 全程用物理像素，和截屏坐标一致

from . import ROOT, config, geom, winapi  # noqa: E402

log = logging.getLogger("deskmirror")


PAUSED_TEXT = "已暂停：不识别、不翻译（点“继续”恢复）"


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


def _single_instance() -> object | None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, "Local\\DeskMirror.Instance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def main() -> int:
    _setup_logging()
    # 跟踪线程有不少 Python 代码；缩短 GIL 切换间隔，界面线程（画译文、拖魔镜）不会被它长时间挡住。
    sys.setswitchinterval(0.002)
    winapi.set_dpi_awareness()
    mutex = _single_instance()
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QMenu, QMessageBox, QSystemTrayIcon

    from .engine import Engine
    from .hotkeys import HoldShortcut, HotkeyManager, modifiers_down, parse_modifiers
    from .ui.mirror import MirrorFrame
    from .ui.overlay import Overlay, UiState
    from .ui.render import Renderer
    from .ui.history import HistoryPanel
    from .ui.settings import SettingsDialog

    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName("桌面魔镜")
    if mutex is None:
        QMessageBox.information(None, "桌面魔镜", "魔镜已经在运行了（看看右下角托盘图标）。")
        return 0
    cfg = config.load()

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

        def __init__(self) -> None:
            super().__init__()
            self.cfg = cfg
            self.state = UiState(Renderer(cfg.style))
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
            self._sync_mirrors()
            self.snapshot_ready.connect(self._on_snapshot)
            self.hotkeys = HotkeyManager(qapp)
            self.hotkeys.activated.connect(self._on_hotkey)
            self.peek = HoldShortcut(self)
            self.peek.changed.connect(self._on_peek)
            self.history = HistoryPanel()
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
            self._tip_bid = 0
            self._hover_since = 0.0
            self.tray = QSystemTrayIcon(make_icon())
            self.tray.setToolTip("桌面魔镜")
            self._usage_seen = (0, 0)       # 引擎累计的请求数、字数（本次运行）
            self._usage_tip = ""
            menu = QMenu()
            self.act_toggle = QAction("隐藏魔镜", menu)
            self.act_toggle.triggered.connect(self.toggle_visible)
            menu.addAction(self.act_toggle)
            self.act_pause = QAction("暂停（框留着，不识别、不翻译）", menu)
            self.act_pause.triggered.connect(self.toggle_pause)
            menu.addAction(self.act_pause)
            menu.addAction("刷新镜框内区域", self.refresh)
            menu.addAction("新建一个魔镜", self.add_mirror)
            menu.addAction("截原图（镜框内原样）", lambda: self.take_shot("orig"))
            menu.addAction("截译图（镜框内带译文）", lambda: self.take_shot("trans"))
            menu.addSeparator()
            scope_menu = menu.addMenu("预译范围")
            self.scope_actions = {}
            for code, name in config.SCOPE_MODES.items():
                act = QAction(name, scope_menu)
                act.setCheckable(True)
                act.setChecked(cfg.scope.mode == code)
                act.triggered.connect(lambda _=False, c=code: self.set_scope(c))
                scope_menu.addAction(act)
                self.scope_actions[code] = act
            menu.addAction("不翻译魔镜下的这个程序", self.exclude_app_under_mirror)
            menu.addAction("历史记录…（最近的原文和译文）", self.toggle_history)
            menu.addAction("设置…", self.open_settings)
            self.act_debug = QAction("显示识别到的滚动区域（调试）", menu)
            self.act_debug.setCheckable(True)
            self.act_debug.toggled.connect(self._on_debug)
            menu.addAction(self.act_debug)
            menu.addSeparator()
            menu.addAction("退出", qapp.quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._on_tray)
            self.tray.messageClicked.connect(self._open_last_shot)
            self.tray.show()
            self._register_keys()
            for o in self.overlays:
                o.show()
            for f in self.frames:
                f.show()
            self.timer = QTimer(self)
            self.timer.setInterval(16)
            self.timer.timeout.connect(self._tick)
            self.timer.start()
            self._last_topmost = 0.0
            self._settings: SettingsDialog | None = None
            self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self._save)
            # 用量每 5 分钟落一次盘（只有数量），中途崩溃也不至于丢掉一整天的统计
            self._usage_saved = (cfg.usage.requests, cfg.usage.chars)
            self._usage_timer = QTimer(self, interval=300_000, timeout=self._save_usage)
            self._usage_timer.start()
            self.engine.start()
            qapp.aboutToQuit.connect(self.shutdown)
            self.debug = None
            port = os.environ.get("DESKMIRROR_DEBUG_PORT")
            if port:
                from .debugctl import DebugServer
                self.debug = DebugServer(int(port), self._debug_cmd)
            autoquit = os.environ.get("DESKMIRROR_AUTOQUIT")
            if autoquit:
                QTimer.singleShot(int(float(autoquit) * 1000), qapp.quit)
            if cfg.first_run_tip:
                self.tray.showMessage("桌面魔镜已启动",
                                      "拖标签移动、拖边框调整大小；按住 Ctrl+Alt 在镜内拖动也能移动。"
                                      f"按住 {cfg.hotkeys.peek} 看原文，{cfg.hotkeys.refresh} 刷新镜内区域。"
                                      "托盘图标右键可退出。", QSystemTrayIcon.MessageIcon.Information, 8000)
                cfg.first_run_tip = False
                self._save_timer.start()

        # -------------------------------------------------------------- 多个魔镜、跟随窗口
        def _new_frame(self, rect: tuple) -> MirrorFrame:
            f = MirrorFrame(rect, self.cfg.style.border_color)
            f.rect_changed.connect(lambda r, final, f=f: self._on_frame_rect(f, r, final))
            f.refresh_clicked.connect(lambda f=f: self.refresh(f))
            f.settings_clicked.connect(self.open_settings)
            f.hide_clicked.connect(self.toggle_visible)
            f.shot_clicked.connect(lambda kind, f=f: self.take_shot(kind, f))
            f.menu_requested.connect(lambda pos, f=f: self._frame_menu(f, pos))
            f.pause_clicked.connect(self.toggle_pause)
            f.set_paused(self.state.paused)
            f.lang_clicked.connect(self._lang_menu)
            f.set_lang_label(self._lang_label())
            f.shown_rect = rect                                  # 上次画过译文的范围（移动后要擦掉）
            self.frames.append(f)
            return f

        def _active_frames(self) -> list[MirrorFrame]:
            return [f for f in self.frames if not f.suspended]

        def _sync_mirrors(self) -> None:
            """把各个魔镜的位置交给覆盖层和跟踪引擎（第一个是主魔镜）。"""
            self.state.mirror = self.frame.mirror
            self.state.mirrors = [f.mirror for f in self._active_frames()]
            self.engine.set_mirrors([self.frame.mirror] + [f.mirror for f in self._active_frames() if f is not self.frame])

        def add_mirror(self) -> None:
            if len(self.frames) >= 4:
                self.tray.showMessage("桌面魔镜", "最多同时开 4 个魔镜。", QSystemTrayIcon.MessageIcon.Information, 4000)
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
            if not self.state.hidden:
                f.show()
            self._sync_mirrors()
            self._save_mirrors()
            for o in self.overlays:
                o.repaint_mirror()

        def close_mirror(self, f: MirrorFrame) -> None:
            if f is self.frame:
                return
            old = f.mirror
            self.frames.remove(f)
            f.close()
            self._sync_mirrors()
            self._save_mirrors()
            for o in self.overlays:
                o.repaint_mirror(old)

        def _save_mirrors(self) -> None:
            self.cfg.mirror_rect = list(self.frame.mirror)
            self.cfg.extra_mirrors = [list(f.mirror) for f in self.frames[1:]]
            self._save_timer.start()

        def _frame_menu(self, f: MirrorFrame, pos) -> None:
            menu = QMenu()
            if f.bound is None:
                menu.addAction("跟随下面的窗口（窗口移动、缩放时魔镜跟着走）", lambda: self.bind_mirror(f))
            else:
                menu.addAction("取消跟随窗口", lambda: self.unbind_mirror(f))
            menu.addAction("新建一个魔镜", self.add_mirror)
            if f is not self.frame:
                menu.addAction("关闭这个魔镜", lambda: self.close_mirror(f))
            menu.exec(pos)

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
                    self.tray.showMessage("桌面魔镜", f"魔镜正跟随窗口：{w.title[:40] or w.cls}",
                                          QSystemTrayIcon.MessageIcon.Information, 3000)
                    return True
            self.tray.showMessage("桌面魔镜", "魔镜下面没有找到窗口。", QSystemTrayIcon.MessageIcon.Warning, 3000)
            return False

        def unbind_mirror(self, f: MirrorFrame) -> None:
            f.bound = None
            f.set_pinned(False)
            if f.suspended:
                f.suspended = False
                if not self.state.hidden:
                    f.show()
                self._sync_mirrors()

        def _follow_windows(self) -> None:
            """跟随窗口的魔镜：窗口动了就按相对位置跟着走；窗口最小化时收起，关掉了就取消跟随。"""
            changed = False
            for f in list(self.frames):
                if f.bound is None:
                    continue
                hwnd, rel, last = f.bound
                wr = winapi.window_rect(hwnd)
                if wr is None:
                    self.unbind_mirror(f)
                    self.tray.showMessage("桌面魔镜", "跟随的窗口已关闭，魔镜不再跟随。",
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
                                            "history": hk.history})
            try:
                self._drag_mods = parse_modifiers(hk.drag_modifiers)
            except ValueError as e:
                errors.append(str(e))
                self._drag_mods = []
            if errors:
                self.tray.showMessage("部分快捷键不可用", "\n".join(errors), QSystemTrayIcon.MessageIcon.Warning, 8000)
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
            self._count_usage(snap.status)
            if not self.state.paused:
                self._feed_history(snap)

        def _lang_label(self) -> str:
            return f"{config.SOURCE_SHORT[self.cfg.source_lang]}→{config.TARGET_SHORT[self.cfg.target_lang]}"

        def _lang_menu(self, pos) -> None:
            """标签上的语言按钮：手动指定原文语言和译成的语言，立即生效。"""
            menu = QMenu()
            menu.addSection("原文")
            for code, name in config.SOURCE_LANGS.items():
                act = menu.addAction(name, lambda c=code: self.set_languages(c, self.cfg.target_lang))
                act.setCheckable(True)
                act.setChecked(code == self.cfg.source_lang)
            menu.addSection("译成")
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

        def toggle_pause(self) -> None:
            """暂停：魔镜框还在，不截屏、不识别、不翻译（不花翻译费用），也不画译文；继续时重新核对画面。"""
            paused = self.state.paused = not self.state.paused
            self.engine.set_working(not paused)
            self.act_pause.setText("继续翻译" if paused else "暂停（框留着，不识别、不翻译）")
            status = (PAUSED_TEXT, "paused") if paused else ("继续工作，正在核对画面…", "busy")
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
            """当天发给翻译服务的请求数和字数（只有数量），显示在托盘提示里，跨重启累计。"""
            req, chars = int(s.get("requests", 0)), int(s.get("sent_chars", 0))
            d_req, d_chars = req - self._usage_seen[0], chars - self._usage_seen[1]
            if d_req < 0 or d_chars < 0:     # 引擎重建过（换了翻译服务）：从头计
                d_req, d_chars = max(0, req), max(0, chars)
            self._usage_seen = (req, chars)
            u = self.cfg.usage
            today = time.strftime("%Y-%m-%d")
            if u.date != today:
                u.date, u.requests, u.chars = today, 0, 0
            if d_req or d_chars:
                u.requests += d_req
                u.chars += d_chars
            host = self.cfg.llm.base_url.split("//")[-1].split("/")[0]
            where = "本机" if host.startswith(("127.0.0.1", "localhost")) else host
            tip = f"桌面魔镜 · 今天发给翻译服务（{where}）{u.requests} 次、{u.chars} 字"
            if tip != self._usage_tip:
                self._usage_tip = tip
                self.tray.setToolTip(tip)

        def _update_status(self, snap) -> None:
            if self.state.paused:
                for f in self.frames:
                    f.set_status(PAUSED_TEXT, "paused")
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
                text, level = "正在启动文字识别…", "busy"
            elif s.get("paused"):
                text, level = f"翻译已暂停：{s.get('service_msg')}（点 ⟳ 重试或改设置）", "error"
            elif s.get("service") == "error":
                text, level = f"翻译服务出错，稍后自动重试：{s.get('service_msg')}", "warn"
            elif in_failed:
                text, level = f"{in_failed} 块翻译失败，点 ⟳ 重试", "warn"
            elif in_pending:
                text, level = f"翻译中：镜内还有 {in_pending} 块", "busy"
            elif s.get("needs", 0) and s.get("ocr") == "busy":
                text, level = "正在识别桌面文字…", "busy"
            else:
                text, level = f"就绪 · 已翻译 {s.get('done', 0)} 块", "ok"
            if s.get("slow") and level == "ok":
                text, level = text + " · 服务较慢", "warn"
            if s.get("excluded_in_mirror") and level in ("ok", "busy"):
                text += " · 镜内有不翻译的窗口（排除名单）"
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
                self.tray.showMessage("桌面魔镜", "魔镜下面没有找到窗口（或拿不到它的程序名）。",
                                      QSystemTrayIcon.MessageIcon.Warning, 4000)
                return
            if name.lower() not in {a.lower() for a in self.cfg.scope.exclude_apps}:
                self.cfg.scope.exclude_apps = self.cfg.scope.exclude_apps + [name]
                self._save()
            self.tray.showMessage("桌面魔镜", f"已把 {name} 加入不翻译名单：它的窗口不再识别和翻译。可在 设置 → 范围与隐私 里移除。",
                                  QSystemTrayIcon.MessageIcon.Information, 5000)

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
                self.tray.showMessage("截图失败", str(e), QSystemTrayIcon.MessageIcon.Warning, 5000)
                return
            qapp.clipboard().setImage(img)
            pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
            folder = (Path(pics) if pics else ROOT) / "桌面魔镜"
            stem = time.strftime(("魔镜译图" if kind == "trans" else "魔镜原图") + "_%Y%m%d_%H%M%S")
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
            what = "译图" if kind == "trans" else "原图"
            if saved:
                self._last_shot = str(path)
                log.info("已保存%s截图：%s", what, path)
                self.tray.showMessage(f"已截{what}", f"已复制到剪贴板，并保存到 {path}（点这条提示打开文件夹）",
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
            else:
                self.tray.showMessage(f"已截{what}", f"已复制到剪贴板；保存到 {folder} 失败。",
                                      QSystemTrayIcon.MessageIcon.Warning, 5000)

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
                ([fr for fr in self.frames if fr.isVisible()] if with_frame else [])
            if widgets:
                p = QPainter(img)
                for w in widgets:
                    g = w.geometry()
                    wr = (g.x(), g.y(), g.x() + g.width(), g.y() + g.height())
                    c = geom.inter(wr, region)
                    if geom.empty(c):
                        continue
                    pm = w.grab(QRect(c[0] - wr[0], c[1] - wr[1], c[2] - c[0], c[3] - c[1]))
                    p.drawPixmap(c[0] - l, c[1] - t, pm)
                p.end()
            return img

        def toggle_visible(self) -> None:
            self.state.hidden = not self.state.hidden
            for f in self.frames:
                f.setVisible(not self.state.hidden and not f.suspended)
            self.act_toggle.setText("显示魔镜" if self.state.hidden else "隐藏魔镜")
            for o in self.overlays:
                o.repaint_mirror()

        def open_settings(self) -> None:
            if self._settings is not None and self._settings.isVisible():
                self._settings.raise_()
                return
            dlg = SettingsDialog(self.cfg)
            self._settings = dlg

            def done(result: int) -> None:
                if result:
                    new = config.validate(dlg.collect())
                    langs_changed = (new.source_lang, new.target_lang) != (self.cfg.source_lang, self.cfg.target_lang)
                    need_restart = (new.ocr.device != self.cfg.ocr.device
                                    or new.track.all_monitors != self.cfg.track.all_monitors
                                    or new.track.wheel_predict != self.cfg.track.wheel_predict)
                    new.mirror_rect = list(self.frame.mirror)
                    new.extra_mirrors = [list(f.mirror) for f in self.frames[1:]]
                    new.usage = self.cfg.usage      # 设置窗口打开期间的用量照样累计
                    old_terms = {(g["src"], g["dst"], g.get("app", "")) for g in self.cfg.glossary}
                    new_terms = {(g["src"], g["dst"], g.get("app", "")) for g in new.glossary}
                    changed = sorted({t[0] for t in old_terms ^ new_terms})
                    self.cfg.__dict__.update(new.__dict__)
                    if changed:      # 配置换好之后再通知：重新翻译时一定用新术语表
                        self.engine.inbox.put(("glossary", changed))
                    for c, act in self.scope_actions.items():
                        act.setChecked(c == self.cfg.scope.mode)
                    self.state.renderer.set_style(self.cfg.style)
                    self.engine.update_llm(self.cfg)
                    if dlg.clear_memory_requested:
                        self.engine.inbox.put(("memory_clear", None))
                    if langs_changed:
                        self.engine.set_languages()
                        for f in self.frames:
                            f.set_lang_label(self._lang_label())
                    self._register_keys()
                    self._save()
                    for o in self.overlays:
                        o.repaint_mirror()
                    if need_restart:
                        self.tray.showMessage("桌面魔镜", "识别设备、屏幕范围和滚动跟随的更改在下次启动时生效。",
                                              QSystemTrayIcon.MessageIcon.Information, 5000)
                self._settings = None
            dlg.finished.connect(done)
            dlg.show()

        def _tick(self) -> None:
            now = time.perf_counter()
            self._follow_windows()
            mods = bool(self._drag_mods) and modifiers_down(self._drag_mods) and not self.state.hidden
            under = self._frame_at(*winapi.cursor_pos()) if mods else None
            for f in self.frames:
                f.set_grab_mode(mods and (f is under or f._drag is not None))
            self._hover_tip(now)
            if now - self._last_topmost > 2.0:
                self._last_topmost = now
                for o in self.overlays:
                    winapi.keep_topmost(int(o.winId()))
                if not self.state.hidden:
                    for f in self._active_frames():
                        winapi.keep_topmost(int(f.winId()))

        def _hover_tip(self, now: float) -> None:
            """鼠标停在被截断的译文上时，显示全文。"""
            snap = self.state.snapshot
            x, y = winapi.cursor_pos()
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
                self.tip.move(x + 16, y + 20)
                self.tip.show()

        def _save_usage(self) -> None:
            u = self.cfg.usage
            if (u.requests, u.chars) != self._usage_saved:
                self._usage_saved = (u.requests, u.chars)
                self._save()

        def _save(self) -> None:
            try:
                config.save(self.cfg)
            except OSError as e:
                log.warning("保存配置失败：%s", e)

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
                        "mirrors": [{"rect": list(f.mirror), "bound": f.bound[0] if f.bound else 0,
                                     "suspended": f.suspended, "visible": f.isVisible()} for f in self.frames]}
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
                QTimer.singleShot(0, qapp.quit)
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
                         "created": round(b.created - self.engine.started, 1)}
                    if req.get("text"):
                        d["text"] = b.text[:60]
                    out.append(d)
                return {"n": len(out), "blocks": out[: int(req.get("limit", 50))]}
            if cmd == "cache_get":
                from .textutil import cache_key
                return {"items": {s: self.engine.cache.get(cache_key(s)) for s in req.get("src", [])}}
            if cmd == "langs":
                self.set_languages(req.get("source", self.cfg.source_lang), req.get("target", self.cfg.target_lang))
                return {"ok": True, "label": self._lang_label()}
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
                return self._composite(req["path"], tuple(req.get("region") or self.state.mirror))
            if cmd == "shot":
                self.take_shot(req.get("kind", "trans"))
                return {"ok": True, "path": self._last_shot}
            if cmd == "buttons":
                # 标签上各按钮的屏幕位置（测试脚本用真实鼠标去点）
                ox, oy = self.frame._origin
                return {n: [r.left() + ox, r.top() + oy, r.right() + 1 + ox, r.bottom() + 1 + oy]
                        for n, r in self.frame._buttons.items()}
            return {"error": f"unknown cmd {cmd}"}

        def _composite(self, path: str, region: tuple) -> dict:
            """用户此刻看到的画面（截屏 + 译文 + 边框），测试看效果用。"""
            self._grab_region(region, translated=True, with_frame=True).save(path)
            return {"ok": True, "path": path}

        def shutdown(self) -> None:
            log.info("正在退出")
            self.timer.stop()
            self.hotkeys.unregister_all()
            self.cfg.mirror_rect = list(self.frame.mirror)
            self.cfg.extra_mirrors = [list(f.mirror) for f in self.frames[1:]]
            self._save()
            if self.debug is not None:
                self.debug.close()
            self.engine.stop()
            self.engine.join(6.0)
            for o in self.overlays:
                o.close()
            for f in self.frames:
                f.close()
            self.tip.close()
            self.history.close()
            self.tray.hide()
            log.info("已退出")

    app = App()
    signal.signal(signal.SIGINT, lambda *_: qapp.quit())
    # 让 Python 有机会处理 Ctrl+C
    keepalive = QTimer()
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)
    code = qapp.exec()
    del app
    return code
