"""输入框翻译（PR #10 方案 B）：在别的软件的输入框里用母语打完字，连按三次空格（或按快捷键），整个框换成设置里选的语言；
再按一次换回原文，再按又换成译文（来回换用记着的字，不发请求、不花 token）。默认关。

- 听键盘：fieldkeys.SpaceListener（Raw Input，只听空格），什么时候算连按三次见 inputbox.Taps。
- 读字：UI Automation（uia.py）读有焦点的输入框，顺便看光标在不在最后、是不是密码框（密码框一概不碰）。
  读不到字的软件，连按三次空格不起作用（免得在游戏里、输入法选字时乱按 Ctrl+A）；按快捷键时借剪贴板复制出来读。
- 写回去：模拟 Ctrl+A、Ctrl+V 粘贴（浏览器版 0.7.1 的教训：绕开编辑器直接改字，聊天框看着换了，发出去的还是原文；
  系统级的粘贴，各种编辑器都按自己的规矩接）。剪贴板借用完放回原来的内容，借用的那一下不进剪贴板历史（clip.py）。
- 翻译期间框里又打了字、换了窗口，就不替换。原文和译文只放内存（最近 20 对），不写硬盘；用量照常计、日志只记数量。
- 默认不管浏览器（装了浏览器版的话它也会响应三次空格，两边会各换一次）、写代码的编辑器和命令行；设置里可以改。
"""
from __future__ import annotations

import copy
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from . import clip, fieldkeys, translator, winapi
from .config import AppConfig, LlmConfig
from .fieldkeys import VK_A, VK_C, VK_CONTROL, VK_RIGHT, VK_V
from .i18n import tr
from .inputbox import (MAX_CHARS, Memo, Taps, body_of, default_target, join_lines, source_of, split_lines,
                       strip_tail)

log = logging.getLogger(__name__)


@dataclass
class _Job:
    how: str                    # space 连按三次空格 / hotkey 快捷键
    hwnd: int                   # 触发时的前台窗口
    app: str                    # 它的程序名（用量日志）
    llm: LlmConfig
    native: str                 # 母语：输入框里打的就是它
    target: str
    hotkey: str
    budget_hit: bool


class FieldTranslator(QObject):
    tip = Signal(str, str, object, int)     # 提示, 样子（busy / ok / err）, 贴在哪（屏幕矩形）, 显示多久（毫秒，0 = 到下一条）
    used = Signal(object)                   # 一次请求的用量（只有数量）
    _tripled = Signal(int)                  # 听键盘的线程：连按了三次空格（前台窗口）
    _idle = Signal()                        # 后台线程处理完一次

    def __init__(self, cfg: AppConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.memo = Memo()
        self.taps = Taps()
        self.budget_hit = False             # 今天的 token 用到上限（云端服务）：不发新请求，来回换照常
        self.listener: fieldkeys.SpaceListener | None = None
        self.busy = False
        self.last = ""                      # 上一次的结果（调试、测试用）：swap / translated / changed / …
        self.runs = 0                       # 处理完了几次（测试等它用）
        self._jobs: queue.Queue = queue.Queue()
        self._pending: tuple[str, int] | None = None
        self._tripled.connect(self._on_tripled)          # 方法（不是 lambda）：回到界面线程里处理
        self._idle.connect(self._on_idle)
        self._worker = threading.Thread(target=self._loop, name="field-translate", daemon=True)
        self._worker.start()
        self.apply(cfg)

    # ------------------------------------------------------------------ 开关
    def apply(self, cfg: AppConfig) -> None:
        """换了设置：打开时开始听空格，关掉时不听。"""
        self.cfg = cfg
        if cfg.input.enabled and self.listener is None:
            self.listener = fieldkeys.SpaceListener(self._space, self.taps.space_up, self.taps.other)
            if self.listener.start_and_wait():
                log.info("输入框翻译：开始听空格")
        elif not cfg.input.enabled and self.listener is not None:
            self.listener.stop()
            self.listener = None
            log.info("输入框翻译：关掉，不再听键盘")

    def close(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        self._jobs.put(None)

    # ------------------------------------------------------------------ 触发
    def _space(self, t: float, hwnd: int, modifiers: bool) -> None:
        """听键盘的线程里：每按下一次空格。"""
        if self.taps.space(t, hwnd, modifiers):
            self._tripled.emit(hwnd)

    def _on_tripled(self, hwnd: int) -> None:
        self._start("space", hwnd)

    def hotkey(self) -> None:
        self._start("hotkey", fieldkeys.foreground()[0])

    def _on_idle(self) -> None:
        if self._pending is not None:
            how, hwnd = self._pending
            self._pending = None
            self._start(how, hwnd)

    def _start(self, how: str, hwnd: int) -> None:
        if not self.cfg.input.enabled:
            return
        if self.busy:
            # 正在处理上一下：记下最后这一下，处理完再看（输入法拿空格选字时多按的那一下、按快了的第四下）
            self._pending = (how, hwnd)
            return
        fg, pid = fieldkeys.foreground()
        if not fg or fg != hwnd or pid == os.getpid():
            return
        app = winapi.process_name(pid)
        if app.lower() in {a.lower() for a in self.cfg.input.skip_apps}:
            if how == "hotkey":
                self._tip(tr("{app} 在输入框翻译不管的程序里（设置 → 输入框翻译 里可以改）").format(app=app), "err",
                          fg, None, 4000)
            return
        native = self.cfg.target_lang
        self.busy = True
        self._jobs.put(_Job(how, fg, app, copy.deepcopy(self.cfg.llm), native,
                            self.cfg.input.target or default_target(native), self.cfg.hotkeys.input, self.budget_hit))

    # ------------------------------------------------------------------ 后台线程
    def _loop(self) -> None:
        from .uia import Uia
        self.uia = Uia()
        self.uia_ok = self.uia.init()
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                self._run(job)
            except Exception as e:  # noqa: BLE001
                log.exception("输入框翻译出错")
                self._tip(tr("内部错误：{name}").format(name=type(e).__name__), "err", job.hwnd, None, 4500)
            finally:
                self.runs += 1
                self.busy = False
                self._idle.emit()

    def _focused(self):
        try:
            return self.uia.focused(MAX_CHARS) if self.uia_ok else None
        except OSError:
            return None

    def _tip(self, text: str, level: str, hwnd: int, f, ms: int) -> None:
        anchor = fieldkeys.caret_rect(hwnd)
        if anchor is None and f is not None and f.rect[2] > f.rect[0]:
            anchor = (f.rect[0] + 8, f.rect[1], f.rect[0] + 9, f.rect[3])
        if anchor is None:
            x, y = winapi.cursor_pos()
            anchor = (x, y, x + 1, y + 16)
        self.tip.emit(text, level, anchor, ms)

    def _run(self, job: _Job) -> None:
        if job.how == "space":
            time.sleep(0.08)                 # 等第三个空格进到框里
        f = self._focused()
        for _ in range(3):
            # Chromium、Electron 第一次被 UI Automation 问到时才打开无障碍功能，头一下常读不到输入框：等一下再读
            if (f is not None and (f.password or f.text is not None)) or fieldkeys.foreground()[0] != job.hwnd:
                break
            time.sleep(0.25)
            f = self._focused()
        log.debug("输入框翻译：%s，控件 %s，%s读到字，光标在最后 %s", job.how, f.control if f else None,
                  "" if f is not None and f.text is not None else "没", f.caret_end if f else None)
        if f is not None and f.password:
            if job.how == "hotkey":
                self._tip(tr("密码框不翻译"), "err", job.hwnd, f, 3000)
            return
        if job.how == "space":
            # 只认读得到字、光标在最后、真的以三个空格结尾的输入框（输入法拿空格选字时框里不会多出三个空格）
            if f is None or f.text is None or f.readonly or f.caret_end is False:
                return
            if len(f.text) > MAX_CHARS:
                self._tip(tr("框里的字太多（超过 {n} 字），没有翻译").format(n=MAX_CHARS), "err", job.hwnd, f, 3500)
                return
            body = body_of(f.text)
            if body is None:
                return
            before, readable = f.text, True
        else:
            if not fieldkeys.wait_released():
                return
            readable = f is not None and f.text is not None and not f.readonly
            if readable:
                before = f.text
            elif f is not None and not f.editable and fieldkeys.caret_rect(job.hwnd) is None:
                self._tip(tr("这里没有能打字的输入框"), "err", job.hwnd, f, 3000)
                return
            else:
                before = self._copy_out(job)         # 读不到：借剪贴板复制出来读
                if before is None:
                    self._tip(tr("读不到框里的字"), "err", job.hwnd, f, 3500)
                    return
            if len(before) > MAX_CHARS:
                self._tip(tr("框里的字太多（超过 {n} 字），没有翻译").format(n=MAX_CHARS), "err", job.hwnd, f, 3500)
                return
            body = strip_tail(before)
            if not body.strip():
                self._tip(tr("框里没有字"), "err", job.hwnd, f, 3000)
                return
        key = f"{source_of(job.native)}>{job.target}"
        hit = self.memo.find(body, key)
        if hit is not None:
            pair, back = hit
            written = self._write(job, pair.orig if back else pair.trans, before, readable, f)
            if written is not None:
                self.memo.seen(pair, back, written)
                self.last = "back" if back else "swap"
                self._done(job, f, back)
            return
        if job.budget_hit:
            self._tip(tr("今天的 token 已用到上限，没有翻译（设置 → 范围与隐私 里可以调）"), "err", job.hwnd, f, 4500)
            return
        self._tip(tr("翻译中…"), "busy", job.hwnd, f, 0)
        lines, at, segs = split_lines(body)
        try:
            out = self._translate(job, segs)
        except translator.ServiceError as e:
            self.last = "failed"
            self._tip(tr("翻译失败：{error}").format(error=e), "err", job.hwnd, f, 5000)
            return
        trans, full = join_lines(lines, at, out)
        if not any(out):
            self.last = "failed"
            self._tip(tr("翻译失败：服务没有返回译文"), "err", job.hwnd, f, 5000)
            return
        if readable:
            now = self._focused()
            if now is None or now.text != before:   # 翻译的时候又打了字：不替换，免得冲掉新打的字
                self.last = "changed"
                self._tip(tr("框里的字变了，没有替换"), "err", job.hwnd, f, 3500)
                return
        written = self._write(job, trans, before, readable, f)
        if written is None:
            return
        pair = self.memo.add(body, trans, key, full)
        self.memo.seen(pair, False, written)
        self.last = "translated"
        self._done(job, f, False)

    def _done(self, job: _Job, f, back: bool) -> None:
        text = (tr("已换回原文 · 再连按三次空格（或 {key}）换成译文") if back
                else tr("已翻译 · 再连按三次空格（或 {key}）换回原文")).format(key=job.hotkey)
        self._tip(text, "ok", job.hwnd, f, 2600)

    def _translate(self, job: _Job, segs: list[str]) -> list[str | None]:
        out: list[str | None] = [None] * len(segs)
        source = source_of(job.native)
        client = translator.make_client(job.llm)
        t0 = time.perf_counter()
        try:
            usage = translator.stream_translate(job.llm, job.target, segs, lambda i, t: out.__setitem__(i, t), client,
                                                threading.Event(), source=source,
                                                prompt=translator.compose_prompt(job.target, source))
        finally:
            client.close()
        self.used.emit({"app": job.app, "segments": len(segs), "chars": sum(len(s) for s in segs),
                        "tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out, "cached": usage.cached,
                        "exact": usage.exact, "secs": time.perf_counter() - t0})
        return out

    # ------------------------------------------------------------------ 键盘、剪贴板
    @staticmethod
    def _press(*keys: int) -> None:
        fieldkeys.press(*keys)          # 我们按的都不是空格：听键盘那边只会“重新数”

    def _write(self, job: _Job, text: str, before: str, readable: bool, f) -> str | None:
        """用粘贴换掉整个框；返回写进去以后读回来的样子（读不了是空字符串），没换成返回 None。"""
        if not fieldkeys.wait_released():
            return None
        if fieldkeys.foreground()[0] != job.hwnd:
            self.last = "moved"
            self._tip(tr("窗口换了，没有替换"), "err", job.hwnd, f, 3500)
            return None
        try:
            saved = clip.save()
        except (OSError, MemoryError) as e:
            self._tip(tr("剪贴板用不了，没有替换：{error}").format(error=e), "err", job.hwnd, f, 4500)
            return None
        written: str | None = ""
        mine = clip.put_text(text)
        try:
            self._press(VK_CONTROL, VK_A)
            time.sleep(0.03)
            self._press(VK_CONTROL, VK_V)
            if readable:
                written = self._wait_changed(before)
                if written is None:
                    self.last = "ignored"
                    self._tip(tr("这个输入框没有接受粘贴，没有替换"), "err", job.hwnd, f, 4000)
            else:
                time.sleep(0.6)                      # 读不到框里的字：等它粘完再放回剪贴板
        finally:
            if clip.seq() == mine:                   # 这期间没人往剪贴板里放别的：放回原来的内容
                clip.restore(saved)
        return written

    def _wait_changed(self, before: str) -> str | None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.5:
            time.sleep(0.05)
            f = self._focused()
            if f is not None and f.text is not None and f.text != before:
                time.sleep(0.08)                     # 有的编辑器分两步写（先删再插）：等它稳下来
                g = self._focused()
                return g.text if g is not None and g.text is not None else f.text
        return None

    def _copy_out(self, job: _Job) -> str | None:
        """读不到框里的字（自己画界面的软件）：Ctrl+A、Ctrl+C 复制出来读，读完取消全选，剪贴板放回原来的内容。"""
        try:
            saved = clip.save()
        except (OSError, MemoryError):
            return None
        start = clip.seq()
        self._press(VK_CONTROL, VK_A)
        time.sleep(0.03)
        self._press(VK_CONTROL, VK_C)
        t0 = time.monotonic()
        while clip.seq() == start and time.monotonic() - t0 < 0.8:
            time.sleep(0.02)
        copied = clip.seq() != start
        text = clip.get_text() if copied else None
        self._press(VK_RIGHT)
        if copied:
            clip.restore(saved)
        return text
