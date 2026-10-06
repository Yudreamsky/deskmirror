"""跟踪引擎（独立线程）：采集 → 变化分类 → 画布与文字块维护 → 识别/翻译调度 → 发布快照。

变化分类的顺序：
1. 窗口位置变了：按窗口几何移动整个窗口画布（窗口移动只在这里施加一次）。
2. 窗口内的变化区域：先找整块平移（局部滚动），确认后只移动这块滚动画布，
   新露出的条带进识别队列；平移解释不了的残余当作内容变化。
3. 内容变化：受影响的文字块立刻重新核对像素，不一致就隐藏；该区域静止后重新识别。

识别和翻译都按“魔镜内 → 镜框外一圈圈向外”的顺序调度；位置维护不等识别和翻译。
"""
from __future__ import annotations

import collections
import zlib
import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from . import geom, pixels, textutil, winapi
from .capture import open_capture
from .config import AppConfig, ocr_lang_for
from .geom import Rect
from .i18n import tr
from .layout import Line, font_em
from .consistency import RefHistory
from .memory import Memory, TemplateCache, number_template
from .ocr_worker import OcrBlockOut, OcrClient, OcrJob
from .scene import Block, Canvas, DrawItem, Snapshot
from .translator import Batch, TranslatorPool
from .wheelmodel import EPISODE_GAP, CurveModel, Episode, learn, load_models, save_models

log = logging.getLogger(__name__)
TILE = pixels.TILE
VOLATILE_S = 1.5   # 连续变化超过这么久才算动态背景（视频、游戏画面）；窗口改大小的重绘一般 1 秒内结束


def _bbox(rects: list[Rect]) -> Rect:
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


def _lum(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (tuple, set)):
        return list(o)
    return str(o)


@dataclass
class Mon:
    idx: int
    info: winapi.Monitor
    cap: object
    origin: tuple[int, int]
    size: tuple[int, int]
    prev: np.ndarray
    cur: np.ndarray
    bgra: np.ndarray | None = None
    needs: np.ndarray | None = None       # 每格“最后一次变化”的时间；0 表示不需要识别
    heat: np.ndarray | None = None        # 每格最近被“无故变化”触发识别的次数（衰减）：动画、闪烁区域会越来越热
    by_change: np.ndarray | None = None   # 这格的待识别是不是内容变化引起的（滚动新露出的不算）
    last_decay: float = 0.0
    last_chg: np.ndarray | None = None    # 每格最近一次“内容变化”的时间（识别后不清零）
    chg_start: np.ndarray | None = None   # 这一轮连续变化从什么时候开始（判断动态背景）
    last_ocr: np.ndarray | None = None    # 每格最近一次被识别的时间
    snap_backoff: np.ndarray | None = None  # 动态区域抓拍识别的间隔倍数（抓不到字就放慢）
    vol_proc: float = 0.0                 # 上次处理动态区域变化的时间（限流到约 10 次/秒）
    ready: bool = False
    frames: int = 0
    last_ft: float = 0.0                  # 最近处理的一帧的采集时间
    seq: int = 0                          # 处理完的帧数（行哈希复用用：只认紧挨着的上一次处理）

    @property
    def rect(self) -> Rect:
        return self.info.rect

    def local(self, r: Rect) -> Rect:
        return geom.shift(r, -self.origin[0], -self.origin[1])


@dataclass
class JobState:
    job: OcrJob
    mon: Mon
    rect: Rect                            # 屏幕坐标
    gray: np.ndarray
    bgr: np.ndarray
    offsets: dict[int, tuple[int, int]]   # 提交时各画布的屏幕偏移
    clips: dict[int, Rect]                # 提交时各画布的可见范围
    canvases: list[Canvas]
    z_then: list[tuple[int, Rect]]        # 提交时的窗口 Z 序和位置
    submitted: float
    touched: set[int] = field(default_factory=set)
    blocks_before: list[tuple[int, Rect]] = field(default_factory=list)  # (bid, 提交时屏幕位置)
    snapshot: bool = False                # 动态区域的抓拍识别
    stale: int = 0                        # 因识别期间画面变了而丢掉的结果数
    tiles: tuple | None = None            # 识别范围对应的格子（行起止、列起止）


@dataclass
class Inflight:
    batch: Batch
    received: set[int] = field(default_factory=set)


def _term_in(term: str, text: str) -> bool:
    """术语是否出现在文字里：两头是字母或数字的（英文等）按整词找，“art” 不算出现在 “start” 里；
    中日韩文字没有词边界，直接找。"""
    i = text.find(term)
    while i >= 0:
        j = i + len(term)
        if not ((term[0].isalnum() and term[0].isascii() and i > 0 and text[i - 1].isalnum())
                or (term[-1].isalnum() and term[-1].isascii() and j < len(text) and text[j].isalnum())):
            return True
        i = text.find(term, i + 1)
    return False


class Engine(threading.Thread):
    def __init__(self, cfg: AppConfig, publish: Callable[[Snapshot], None]) -> None:
        super().__init__(name="deskmirror-engine", daemon=True)
        self.cfg = cfg
        self._publish_cb = publish
        self.inbox: queue.Queue[tuple] = queue.Queue()
        self._stop_evt = threading.Event()
        self._mirror: Rect = tuple(cfg.mirror_rect) if cfg.mirror_rect else (0, 0, 0, 0)   # 主魔镜（定显示器）
        self._mirrors: list[Rect] = [self._mirror]                                          # 所有显示中的魔镜
        self.mons: list[Mon] = []
        self.desktop = Canvas("desktop", None, [0, 0], None)
        self.win_canvas: dict[int, Canvas] = {}
        self.z_order: list[int] = []
        self.win_rects: dict[int, Rect] = {}
        self.visible: dict[int, list[Rect]] = {}
        self.desktop_visible: list[Rect] = []
        self.blocks: dict[int, Block] = {}
        self.by_key: dict[str, set[int]] = collections.defaultdict(set)
        self._idx_valid = False
        self._idx_bids = np.zeros(0, np.int64)
        self._idx_rects = np.zeros((0, 4), np.int64)
        self.cache: collections.OrderedDict[str, str] = collections.OrderedDict()
        self.templates = TemplateCache()      # 只有数字不同的文字套用已有译文（只在内存里）
        self.overrides: dict[str, str] = {}   # 用户改过的译文（缓存键 → 译文），优先于一切
        self.refs = RefHistory()              # 译过的段落：给后面的请求作参考，术语前后一致（只在内存里）
        self._langs = (cfg.source_lang, cfg.target_lang)   # 引擎当前按哪对语言工作（用户改了就对比着处理）
        # 每个窗口最近翻译过的字幕 / 对话行（时间, 原文, 译文）：新的一句带上前几句作上下文（只在内存里）
        self.dialog: dict[int, collections.deque] = {}
        self.memory: Memory | None = None     # 本地记忆（用户打开才有）
        self._mem_saving = False
        self._mem_thread: threading.Thread | None = None
        self.ocr: OcrClient | None = None
        self.ocr_state = "starting"
        self.ocr_busy: JobState | None = None
        self.jobs: dict[int, JobState] = {}
        self._job_ids = 0
        self.pool: TranslatorPool | None = None
        self.inflight: dict[int, Inflight] = {}
        self._batch_ids = 0
        self.retry_single: set[str] = set()   # 漏译半句的原文：下次单独重译一次
        self.service = {"state": "idle", "message": "", "fails": 0, "until": 0.0, "paused": False,
                        "last_ok": 0.0, "requests": 0, "slow": False}
        self._dirty = True
        self._last_publish = 0.0
        self._last_windows = 0.0
        self._last_trans_sched = 0.0
        self._last_verify_sweep = 0.0
        self._no_shift_until: dict[tuple, float] = {}
        self._frame_moved: dict[int, tuple[str, int]] = {}   # 这一帧里已经移动过的画布：cid → (方向, 位移)
        self._hashes: dict[tuple, tuple] = {}                # (显示器, 窗口) → (帧号, 那一帧当前帧的行哈希)
        self._frame_tiles: tuple | None = None               # 正在处理的一帧：(显示器, 像素真的变了的格子)
        self.win_pids: dict[int, int] = {}
        self._proc_names: dict[int, str] = {}
        self._excluded: set[int] = set()                     # 排除名单里的窗口：不识别、不翻译
        self._last_privacy = 0.0
        self._ok_pending: dict[int, Rect] = {}               # 这一帧移动前确认过、等同帧其他块佐证的块
        self.metrics: dict = collections.defaultdict(float)
        self.metrics_log = os.environ.get("DESKMIRROR_METRICS")
        self._metrics_fh = None
        self.started = time.perf_counter()
        self._cur_frame_t = 0.0
        self._prev_frame_t = 0.0
        self._vel_shown: set[int] = set()     # 正按速度外推显示的画布（停下后要撤回外推）
        self.working = True                   # 用户点了“暂停”就是 False：不截屏、不识别、不翻译（魔镜框还在）
        self._geo_frame_t = 0.0
        self._last_others = 0.0
        self._all_infos: list[winapi.Monitor] = []
        self._last_mon_check = 0.0
        self._switch_to: tuple[str, float] | None = None
        self.wheel = None
        self.wheel_models: dict[str, CurveModel] = {}
        self.episodes: dict[int, Episode] = {}
        self._win_class: dict[int, str] = {}
        self.error = ""
        self._ko_fallback = ""        # 韩文识别模型没下载成功时的提示（重新就绪后清掉）

    # ------------------------------------------------------------------ 线程外调用
    def set_mirror(self, rect: Rect) -> None:
        self.set_mirrors([rect])

    def set_mirrors(self, rects: list[Rect]) -> None:
        """第一个是主魔镜。整体赋值，跟踪线程读到的总是一致的一组。"""
        rects = [tuple(r) for r in rects] or [self._mirror]
        self._mirrors = rects
        self._mirror = rects[0]

    def _ring(self, r: Rect) -> float:
        """离最近的魔镜有多远（魔镜里为 0）：识别、翻译、核对都先做近的。"""
        return min(geom.ring_distance(r, m) for m in self._mirrors)

    def request_refresh(self, rect: Rect) -> None:
        self.inbox.put(("refresh", rect))

    def update_llm(self, cfg: AppConfig) -> None:
        self.inbox.put(("llm", cfg))

    def set_working(self, on: bool) -> None:
        """暂停 / 继续整个跟踪（截屏、识别、翻译）。"""
        self.inbox.put(("work", on))

    def pause_translation(self, on: bool) -> None:
        self.inbox.put(("pause", on))

    def stop(self) -> None:
        self._stop_evt.set()

    # ------------------------------------------------------------------ 主循环
    def run(self) -> None:
        try:
            self._setup()
        except Exception as e:  # noqa: BLE001
            log.exception("引擎初始化失败")
            self.error = tr("初始化失败：{error}").format(error=e)
            self._publish(force=True)
            self._shutdown()
            return
        errors: collections.deque[float] = collections.deque(maxlen=20)
        try:
            while not self._stop_evt.is_set():
                try:
                    got = self._tick()
                except Exception as e:  # noqa: BLE001
                    # 单次出错不能让跟踪停下；短时间内反复出错才放弃，并在魔镜上说明。
                    log.exception("引擎处理出错")
                    errors.append(time.perf_counter())
                    if len(errors) == errors.maxlen and errors[-1] - errors[0] < 10:
                        self.error = tr("内部错误，跟踪已停止：{name}（请重启魔镜）").format(name=type(e).__name__)
                        self._publish(force=True)
                        break
                    got = False
                if not got:
                    time.sleep(0.002)
        finally:
            self._shutdown()

    def _check_monitor_switch(self, now: float) -> None:
        """单屏模式：魔镜拖到另一块屏幕并停留半秒后，改为处理那块屏幕（译文缓存保留）。"""
        if self.cfg.track.all_monitors or now - self._last_mon_check < 0.2:
            return
        self._last_mon_check = now
        info = self._mirror_monitor()
        if self.mons and info.device == self.mons[0].info.device:
            self._switch_to = None
            return
        if self._switch_to is None or self._switch_to[0] != info.device:
            self._switch_to = (info.device, now)
            return
        if now - self._switch_to[1] < 0.5:
            return
        self._switch_to = None
        for m in self.mons:
            try:
                m.cap.close()
            except Exception:  # noqa: BLE001
                pass
        if self.ocr_busy is not None:
            self.jobs.pop(self.ocr_busy.job.job_id, None)
            self.ocr_busy = None
        self.mons = [self._make_mon(0, info)]
        for b in list(self.blocks.values()):
            if not geom.overlaps(b.screen_rect(), info.rect):
                self._delete_block(b, "monitor")  # 不再处理的屏幕上的块：没法再核对，删掉（译文缓存还在）
        self._metric("monitor_switch", device=info.device)
        log.info("改为处理魔镜所在的屏幕 %s", info.device)
        self._scene_changed()

    def _tick(self) -> bool:
        prof = self.metrics
        t0 = time.perf_counter()
        self._drain_inbox()
        if not self.working:
            # 暂停：只收消息（在途的识别、翻译结果照常进缓存），不截屏、不识别、不发新请求、不发布
            self._maybe_save_memory(t0)
            time.sleep(0.05)
            return True
        self._check_monitor_switch(t0)
        t1 = time.perf_counter()
        if t1 - self._last_windows >= 0.02:
            self._refresh_windows()
        self._refresh_privacy(t1)
        t2 = time.perf_counter()
        got = False
        focus = self._focus_monitor()
        wait = 0.0
        # 魔镜所在的显示器优先：它的帧一处理完、位置一变就立刻发布，不等其他显示器；
        # 其他显示器每秒最多处理约 30 帧（它们的变化不在魔镜里，晚几十毫秒没关系）。
        others_due = t2 - self._last_others >= 0.033
        if others_due:
            self._last_others = t2
        for m in sorted(self.mons, key=lambda mm: mm is not focus):
            if m is not focus and not others_due:
                continue
            try:
                tw = time.perf_counter()
                fr = m.cap.grab(timeout_ms=5 if m is focus else 0)
                wait += time.perf_counter() - tw
            except Exception as e:  # noqa: BLE001
                log.warning("显示器 %s 采集出错：%s", m.idx, e)
                fr = None
            if fr is not None:
                self._on_frame(m, fr)
                got = True
                if m is focus and self._geo_frame_t:
                    self._publish(force=True)
        t3 = time.perf_counter()
        self._verify_sweep()
        t4 = time.perf_counter()
        self._schedule_ocr()
        t5 = time.perf_counter()
        if t5 - self._last_trans_sched >= 0.05:
            self._schedule_translation()
        if self.episodes:
            self._update_episodes(t5)
        self._maybe_save_memory(t5)
        if self._vel_shown and self._velocity_stale(t5):
            self._dirty = True
            self._publish(force=True)   # 滚动停了：撤回按速度外推的那一段
        t6 = time.perf_counter()
        # 预测进行中：即使没有新帧也按 120Hz 发布，让译文沿曲线连续移动
        self._publish(force=bool(self.episodes or self._vel_shown) and t6 - self._last_publish >= 1 / 120)
        t7 = time.perf_counter()
        # 各环节累计耗时（毫秒），用于找出拖慢跟随的部分
        prof["p_ticks"] += 1
        prof["p_inbox"] += (t1 - t0) * 1000
        prof["p_windows"] += (t2 - t1) * 1000
        prof["p_grab_wait"] += wait * 1000
        prof["p_frames"] += (t3 - t2 - wait) * 1000
        prof["p_sweep"] += (t4 - t3) * 1000
        prof["p_ocr_sched"] += (t5 - t4) * 1000
        prof["p_tr_sched"] += (t6 - t5) * 1000
        prof["p_publish"] += (t7 - t6) * 1000
        prof["p_tick_max"] = max(prof["p_tick_max"], (t7 - t0 - wait) * 1000)
        return got

    def _make_mon(self, i: int, info: winapi.Monitor) -> Mon:
        cap = open_capture(info.device, info.rect, self.cfg.track.prefer_dxgi)
        w, h = info.rect[2] - info.rect[0], info.rect[3] - info.rect[1]
        th, tw = -(-h // TILE), -(-w // TILE)
        now = time.perf_counter()
        needs = np.full((th, tw), now - 10.0)  # 刚开始处理的屏幕：整屏都等着识别
        mon = Mon(i, info, cap, (info.rect[0], info.rect[1]), (w, h), np.zeros((h, w), np.uint8),
                  np.zeros((h, w), np.uint8), None, needs, np.zeros((th, tw), np.float32),
                  np.zeros((th, tw), bool), now)
        mon.last_chg = np.zeros((th, tw))
        mon.chg_start = np.zeros((th, tw))
        mon.last_ocr = np.zeros((th, tw))
        mon.snap_backoff = np.ones((th, tw), np.float32)
        return mon

    def _mirror_monitor(self) -> winapi.Monitor:
        cx, cy = geom.center(self._mirror)
        for info in self._all_infos:
            if geom.contains_pt(info.rect, cx, cy):
                return info
        return self._all_infos[0]

    def _setup(self) -> None:
        self._all_infos = winapi.monitors()
        if not self._mirror or geom.area(self._mirror) == 0:
            r = self._all_infos[0].work
            cw, ch = (r[2] - r[0]) // 2, (r[3] - r[1]) // 2
            self._mirror = (r[0] + cw // 2, r[1] + ch // 2, r[0] + cw // 2 + cw, r[1] + ch // 2 + ch)
            self._mirrors = [self._mirror]
        # 默认只处理魔镜所在的那块屏幕；设置里可以打开“所有屏幕”。
        infos = self._all_infos if self.cfg.track.all_monitors else [self._mirror_monitor()]
        for i, info in enumerate(infos):
            self.mons.append(self._make_mon(i, info))
        self._start_ocr()

    def _start_ocr(self) -> None:
        self.ocr_state = "starting"
        self.ocr = OcrClient(self.cfg.ocr.device, self.cfg.ocr.threads, lambda msg: self.inbox.put(("ocr", msg)),
                             ocr_lang_for(self.cfg.source_lang))
        self.pool = TranslatorPool(self.cfg.llm, lambda ev: self.inbox.put(("tr", ev)))
        self.wheel_models = load_models(self._wheel_path())
        self._sync_memory()
        if self.cfg.track.wheel_predict:
            from .wheel import WheelListener
            self.wheel = WheelListener(lambda *a: self.inbox.put(("wheel", a)))
            if not self.wheel.start_and_wait():
                self.wheel = None
        if self.metrics_log:
            self._metrics_fh = open(self.metrics_log, "a", encoding="utf-8", buffering=1)  # 逐行写，核对时读得到最新的
        log.info("引擎启动：%d 个显示器，采集方式 %s", len(self.mons), [type(m.cap).__name__ for m in self.mons])

    def _wheel_path(self):
        from .config import config_path
        return config_path().with_name("deskmirror_wheel.json")   # 和配置文件放在一起（测试时在临时目录）

    def _shutdown(self) -> None:
        if self.wheel is not None:
            self.wheel.stop()
        try:
            save_models(self._wheel_path(), self.wheel_models)   # 学到的滚轮曲线下次直接用（只有数字）
        except OSError:
            log.debug("滚轮曲线保存失败", exc_info=True)
        self._wait_memory_save()
        if self.memory is not None:
            try:
                self.memory.save()
            except OSError:
                log.warning("译文记忆保存失败")
        if self.pool is not None:
            self.pool.close()
        if self.ocr is not None:
            self.ocr.close()
        for m in self.mons:
            try:
                m.cap.close()
            except Exception:  # noqa: BLE001
                pass
        if self._metrics_fh:
            self._metrics_fh.close()
            self._metrics_fh = None
        log.info("引擎已停止")

    def _metric(self, kind: str, **data) -> None:
        if self._metrics_fh:
            data["t"] = round(time.perf_counter() - self.started, 4)
            data["kind"] = kind
            try:
                self._metrics_fh.write(json.dumps(data, ensure_ascii=False, default=_jsonable) + "\n")
            except (TypeError, ValueError, OSError):
                log.debug("指标写入失败", exc_info=True)

    def _focus_monitor(self) -> Mon | None:
        m = self._monitor_for(self._mirror)
        return m or (self.mons[0] if self.mons else None)

    def _monitor_for(self, r: Rect) -> Mon | None:
        cx, cy = geom.center(r)
        for m in self.mons:
            if geom.contains_pt(m.rect, cx, cy):
                return m
        return None

    def _scene_changed(self) -> None:
        self._dirty = True
        self._idx_valid = False

    # ------------------------------------------------------------------ 收件箱
    def _drain_inbox(self) -> None:
        for _ in range(500):
            try:
                msg = self.inbox.get_nowait()
            except queue.Empty:
                return
            kind = msg[0]
            if kind == "ocr":
                self._on_ocr(msg[1])
            elif kind == "tr":
                self._on_translation(msg[1])
            elif kind == "refresh":
                self._refresh(msg[1])
            elif kind == "llm":
                self._replace_llm(msg[1])
            elif kind == "wheel":
                if self.working:              # 暂停时的滚动不记：画面没在跟踪，继续时重新核对
                    self._on_wheel(*msg[1])
            elif kind == "work":
                self._set_working(bool(msg[1]))
            elif kind == "langs":
                self._apply_languages()
            elif kind == "override":
                self._override(msg[1], msg[2])
            elif kind == "glossary":
                self._glossary_changed(msg[1])
            elif kind == "memory_clear":
                # 先等后台保存写完，免得刚删掉的文件又被写回来；记忆关着时也删掉以前存下的文件
                self._wait_memory_save()
                (self.memory or Memory(self._memory_path())).clear()
                self._dirty = True
            elif kind == "pause":
                # 暂停/恢复发送翻译请求（测试用；在途的请求照常完成）
                self.service["paused"] = bool(msg[1])
                if not msg[1]:
                    self.service["until"] = 0.0
                self._dirty = True

    # ------------------------------------------------------------------ 窗口
    def _refresh_windows(self) -> None:
        self._last_windows = time.perf_counter()
        wins = winapi.top_level_windows(skip_pid=os.getpid())
        self.win_pids = {w.hwnd: w.pid for w in wins}
        seen = set()
        changed = False
        for w in wins:
            seen.add(w.hwnd)
            c = self.win_canvas.get(w.hwnd)
            if c is None or not c.alive:
                c = Canvas("window", self.desktop, [w.rect[0], w.rect[1]], w.rect, hwnd=w.hwnd)
                self.desktop.children.append(c)
                self.win_canvas[w.hwnd] = c
                changed = True
                continue
            old = c.viewport
            if old != w.rect:
                changed = True
                if (old[2] - old[0], old[3] - old[1]) == (w.rect[2] - w.rect[0], w.rect[3] - w.rect[1]):
                    self._move_window(c, w.rect[0] - old[0], w.rect[1] - old[1])
                else:
                    self._resize_window(c, w.rect)
        for hwnd in list(self.win_canvas):
            if hwnd not in seen:
                if not winapi.user32.IsWindow(hwnd):
                    self._drop_canvas(self.win_canvas.pop(hwnd))
                changed = True  # 最小化或被系统隐藏的窗口保留缓存，回来时重新核对
        order = [w.hwnd for w in wins]
        if changed or order != self.z_order:
            self.z_order = order
            self.win_rects = {w.hwnd: w.rect for w in wins}
            self._compute_visibility()
            self._scene_changed()

    # ------------------------------------------------------------------ 翻译范围与排除名单
    def _refresh_privacy(self, now: float) -> None:
        """每半秒：哪些窗口在排除名单里（按程序名或标题）。新被排除的窗口，已有的块全部删掉。"""
        if now - self._last_privacy < 0.5:
            return
        self._last_privacy = now
        sc = self.cfg.scope
        apps = {a.lower() for a in sc.exclude_apps}
        words = [w.lower() for w in sc.exclude_titles]
        if len(self._proc_names) > 1024:
            self._proc_names.clear()
        ex: set[int] = set()
        for hwnd, pid in self.win_pids.items():
            name = self._proc_names.get(pid)
            if name is None:
                name = self._proc_names[pid] = winapi.process_name(pid).lower()
            if name in apps or (words and any(w in winapi.window_title(hwnd).lower() for w in words)):
                ex.add(hwnd)
        newly = ex - self._excluded
        released = self._excluded - ex
        changed = ex != self._excluded
        self._excluded = ex
        for hwnd in newly:
            c = self.win_canvas.get(hwnd)
            if c is not None:
                for b in list(self._subtree_blocks(c)):
                    self._delete_block(b, "excluded")
        for hwnd in released:
            # 移出名单的窗口：之前被跳过的内容重新排队识别
            for m in self.mons:
                for v in self.visible.get(hwnd, ()):
                    r = geom.inter(v, m.rect)
                    if not geom.empty(r):
                        self._mark_needs(m, r, by_change=False)
        if changed:
            self._scene_changed()

    def _visible_mask(self, b: Block, sr: Rect):
        """块露在所属窗口未遮挡部分里的像素（核对只看这些）。全部露出返回 None；露出不到四分之一返回 False。"""
        win = b.canvas.window()
        vis = self.visible.get(win.hwnd, ()) if win is not None else self.desktop_visible
        parts = [geom.inter(v, sr) for v in vis if geom.overlaps(v, sr)]
        area = sum(geom.area(p) for p in parts)
        total = geom.area(sr)
        if total == 0 or area >= total:
            return None
        if area < 0.25 * total:
            return False
        mask = np.zeros((sr[3] - sr[1], sr[2] - sr[0]), bool)
        for p in parts:
            # 往里收 3 像素：±2 像素的偏移核对时，边上不会碰到挡在上面的窗口
            l, t, r, bb = p[0] - sr[0] + 3, p[1] - sr[1] + 3, p[2] - sr[0] - 3, p[3] - sr[1] - 3
            if r > l and bb > t:
                mask[t:bb, l:r] = True
        return mask

    def _visible_frac(self, b: Block, sr: Rect) -> float:
        """块在它所属窗口未被遮挡部分里的面积占比。"""
        win = b.canvas.window()
        vis = self.visible.get(win.hwnd, ()) if win is not None else self.desktop_visible
        a = geom.area(sr)
        return sum(geom.area(geom.inter(v, sr)) for v in vis) / a if a else 0.0

    def _windows_in_mirror(self) -> set[int]:
        """各个魔镜里露出来的窗口（0 代表桌面本身）。"""
        out: set[int] = set()
        for mirror in self._mirrors:
            out |= {hwnd for hwnd in self.z_order if any(geom.overlaps(v, mirror) for v in self.visible.get(hwnd, ()))}
            if any(geom.overlaps(d, mirror) for d in self.desktop_visible):
                out.add(0)
        return out

    def _in_scope(self, b: Block, sr: Rect, under: set[int] | None = None) -> bool:
        """这块现在可以发给翻译服务吗：不在排除名单里，且在当前的预译范围内（范围外的先等着，魔镜过来再译）。"""
        win = b.canvas.window()
        hwnd = win.hwnd if win is not None else 0
        if hwnd in self._excluded:
            return False
        mode = self.cfg.scope.mode
        if mode == "near":
            return any(geom.overlaps(sr, geom.expand(mr, self.cfg.scope.near_px)) for mr in self._mirrors)
        if mode == "window":
            return hwnd in (under if under is not None else self._windows_in_mirror())
        return True

    def _moving_clips(self, now: float) -> list[Rect]:
        """刚刚（0.15 秒内）还在滚动的画布的可见范围。"""
        return [c.screen_clip() for wc in self.win_canvas.values() for c in wc.descendants()
                if c.kind == "scroll" and c.alive and now - c.last_move < 0.15]

    def _moving_mask(self, m: Mon, now: float) -> np.ndarray | None:
        clips = self._moving_clips(now)
        if not clips:
            return None
        mask = np.zeros(m.needs.shape, bool)
        for r in clips:
            self._fill_tiles(mask, m, r, True)
        return mask

    def _fill_tiles(self, mask: np.ndarray, m: Mon, r: Rect, value: bool) -> None:
        l, t, rr, bb = m.local(r)
        tl, tt = max(0, l // TILE), max(0, t // TILE)
        tr, tb = min(mask.shape[1], -(-rr // TILE)), min(mask.shape[0], -(-bb // TILE))
        if tr > tl and tb > tt:
            mask[tt:tb, tl:tr] = value

    def _scope_masks(self, m: Mon) -> tuple[np.ndarray | None, np.ndarray | None]:
        """(预译范围内的格子, 排除名单窗口占的格子)；None 表示不限制 / 没有。"""
        scope = None
        mode = self.cfg.scope.mode
        if mode in ("window", "near"):
            scope = np.zeros(m.needs.shape, bool)
            if mode == "near":
                for mr in self._mirrors:
                    self._fill_tiles(scope, m, geom.expand(mr, self.cfg.scope.near_px), True)
            else:
                for hwnd in self._windows_in_mirror():
                    for r in (self.visible.get(hwnd, ()) if hwnd else self.desktop_visible):
                        self._fill_tiles(scope, m, r, True)
        excl = None
        if self._excluded:
            excl = np.zeros(m.needs.shape, bool)
            for hwnd in self._excluded:
                for r in self.visible.get(hwnd, ()):
                    self._fill_tiles(excl, m, r, True)
        return scope, excl

    def _compute_visibility(self) -> None:
        above: list[Rect] = []
        self.visible = {}
        for hwnd in self.z_order:
            r = self.win_rects[hwnd]
            vis = [r]
            for a in above:
                vis = geom.subtract_all(vis, a)
                if not vis:
                    break
            self.visible[hwnd] = vis
            above.append(r)
        desk = [m.rect for m in self.mons]
        for a in above:
            desk = geom.subtract_all(desk, a)
        self.desktop_visible = desk

    def _move_window(self, c: Canvas, dx: int, dy: int) -> None:
        c.offset[0] += dx
        c.offset[1] += dy
        c.viewport = geom.shift(c.viewport, dx, dy)
        c.last_move = time.perf_counter()
        # 窗口内容随窗口整体平移；每块在新位置重新核对（采集帧可能比窗口几何晚一帧）。
        for b in self._subtree_blocks(c):
            b.ok_rect = None
        self._metric("window_move", hwnd=c.hwnd, dx=dx, dy=dy)
        self._scene_changed()

    def _resize_window(self, c: Canvas, rect: Rect) -> None:
        old = c.viewport
        c.offset[0] += rect[0] - old[0]
        c.offset[1] += rect[1] - old[1]
        c.viewport = rect
        c.last_move = time.perf_counter()
        # 改变大小可能重新换行：滚动画布的范围不再可信，块逐个核对，对不上的等重新识别。
        for ch in list(c.children):
            self._collapse_canvas(ch)
        for b in self._subtree_blocks(c):
            b.ok_rect = None
        self._metric("window_resize", hwnd=c.hwnd, rect=rect)
        self._scene_changed()

    def _collapse_canvas(self, s: Canvas) -> None:
        """撤掉一个滚动画布：它的块回到父画布（换算坐标），子画布一并撤掉。"""
        for ch in list(s.children):
            self._collapse_canvas(ch)
        parent = s.parent
        ox, oy = s.offset
        for b in list(s.blocks.values()):
            b.canvas = parent
            b.rect = geom.shift(b.rect, ox, oy)
            b.lines = [(geom.shift(lr, ox, oy), t) for lr, t in b.lines]
            b.room_bottom += oy
            b.ok_rect = None
            parent.blocks[b.bid] = b
        s.blocks.clear()
        s.alive = False
        if parent is not None and s in parent.children:
            parent.children.remove(s)
        self._scene_changed()

    def _drop_canvas(self, c: Canvas) -> None:
        for ch in list(c.children):
            self._drop_canvas(ch)
        for b in list(c.blocks.values()):
            self._delete_block(b, "window_gone")
        c.alive = False
        if c.parent is not None and c in c.parent.children:
            c.parent.children.remove(c)

    def _subtree_blocks(self, c: Canvas):
        yield from c.blocks.values()
        for d in c.descendants():
            yield from d.blocks.values()

    def _window_at(self, x: float, y: float) -> Canvas:
        for hwnd in self.z_order:
            r = self.win_rects.get(hwnd)
            if r is not None and geom.contains_pt(r, x, y):
                return self.win_canvas[hwnd]
        return self.desktop

    def _deepest_canvas(self, root: Canvas, r: Rect) -> Canvas:
        """包含矩形中心的最深画布。"""
        cx, cy = geom.center(r)
        best, best_depth = root, root.depth()
        stack = [(ch, best_depth + 1) for ch in root.children]
        while stack:
            c, d = stack.pop()
            if not c.alive:
                continue
            if geom.contains_pt(c.screen_clip(), cx, cy):
                if d > best_depth:
                    best, best_depth = c, d
                stack.extend((ch, d + 1) for ch in c.children)
        return best

    # ------------------------------------------------------------------ 块索引
    def _index(self) -> tuple[np.ndarray, np.ndarray]:
        if not self._idx_valid:
            bids, rects = [], []
            offs: dict[int, tuple[int, int]] = {}
            for b in self.blocks.values():
                c = b.canvas
                o = offs.get(c.cid)
                if o is None:
                    o = offs[c.cid] = c.screen_offset()
                bids.append(b.bid)
                r = b.rect
                rects.append((r[0] + o[0], r[1] + o[1], r[2] + o[0], r[3] + o[1]))
            self._idx_bids = np.array(bids, np.int64)
            self._idx_rects = np.array(rects, np.int64).reshape(-1, 4)
            self._idx_valid = True
        return self._idx_bids, self._idx_rects

    def _blocks_in(self, r: Rect) -> list[Block]:
        bids, rects = self._index()
        if not len(bids):
            return []
        hit = (rects[:, 0] < r[2]) & (r[0] < rects[:, 2]) & (rects[:, 1] < r[3]) & (r[1] < rects[:, 3])
        return [self.blocks[int(i)] for i in bids[hit] if int(i) in self.blocks]

    # ------------------------------------------------------------------ 帧分析
    def _on_frame(self, m: Mon, fr) -> None:
        t0 = time.perf_counter()
        self._cur_frame_t = fr.time
        self._prev_frame_t = m.last_ft or fr.time
        m.bgra = fr.image
        m.last_ft = fr.time
        m.frames += 1
        w, h = m.size
        regions = []
        for r in ([(0, 0, w, h)] if fr.full else fr.dirty):
            l, t, rr, b = r
            l, t = max(0, l // TILE * TILE), max(0, t // TILE * TILE)
            rr, b = min(w, -(-rr // TILE) * TILE), min(h, -(-b // TILE) * TILE)
            if rr > l and b > t:
                regions.append((l, t, rr, b))
        if not regions:
            return
        tiles_full = np.zeros(m.needs.shape, bool)
        for l, t, rr, b in regions:
            m.cur[t:b, l:rr] = pixels.to_gray(fr.image[t:b, l:rr])
            if m.ready:
                (al, at, _ar, _ab), tiles = pixels.changed_tiles(m.prev, m.cur, (l, t, rr, b))
                if tiles.size:
                    tiles_full[at // TILE:at // TILE + tiles.shape[0], al // TILE:al // TILE + tiles.shape[1]] |= tiles
        if not m.ready:
            m.prev[:] = m.cur
            m.ready = True
            self._dirty = True
            return
        t_diff = time.perf_counter()
        self._frame_tiles = (m, tiles_full)
        comps = pixels.components(tiles_full, (0, 0), dilate=1)
        scrolls = 0
        self._prof_frame = collections.defaultdict(float)
        self._frame_moved = {}
        self._ok_pending = {}
        # 大的变化区域先处理：一次滚动被切成几块时，先由最大的一块确定位移，其余各块据此对照
        for comp in sorted(comps, key=geom.area, reverse=True):
            comp = geom.inter(comp, (0, 0, w, h))
            if not geom.empty(comp):
                scrolls += self._classify_change(m, comp)
        t_cls = time.perf_counter()
        self._frame_tiles = None
        for l, t, rr, b in regions:
            m.prev[t:b, l:rr] = m.cur[t:b, l:rr]
        m.seq += 1
        dt = time.perf_counter() - t0
        self.metrics["frames"] += 1
        self.metrics["frame_ms_sum"] += dt * 1000
        if comps:
            pf = {k: round(v * 1000, 2) for k, v in self._prof_frame.items()}
            self._metric("frame", mon=m.idx, comps=len(comps), scrolls=scrolls, ms=round(dt * 1000, 2),
                         lag_ms=round((time.perf_counter() - fr.time) * 1000, 2),
                         diff_ms=round((t_diff - t0) * 1000, 2), cls_ms=round((t_cls - t_diff) * 1000, 2), **pf)

    def _classify_change(self, m: Mon, comp_local: Rect) -> int:
        """按窗口切开变化区域，逐块判断是局部滚动还是内容变化；返回识别出的滚动次数。"""
        comp = geom.shift(comp_local, *m.origin)
        scrolls = 0
        remaining = [comp]
        for hwnd in self.z_order:
            if not remaining:
                break
            wr = self.win_rects.get(hwnd)
            if wr is None:
                continue
            parts = [geom.inter(r, wr) for r in remaining if geom.overlaps(r, wr)]
            if not parts:
                continue
            remaining = geom.subtract_all(remaining, wr)
            c = self.win_canvas[hwnd]
            parts = [p for p in parts if not geom.empty(p) and self._part_changed(m, p)]
            box = _bbox(parts) if len(parts) > 1 else None
            if box is not None and sum(geom.area(p) for p in parts) >= 0.75 * geom.area(box):
                # 同一个变化区域在这个窗口里被压在上面的小窗口（弹窗、浮动面板）切成了几块：合起来一次判断。
                # 分开判断时各块各建滚动画布、切线上的段落被删；合起来以后，上面那个窗口没变的像素只是
                # “原地不动”的内容，不影响找平移，标记待识别时也只标真正变了的格子。
                # 压在上面的窗口很大时不合并（那样合起来的范围大半是别的窗口，会把它的滚动认成这个窗口的）。
                parts = [box]
            for part in parts:
                now = time.perf_counter()
                since_move = now - c.last_move
                if since_move < 0.15:
                    self._content_changed(m, part, track_volatile=False)  # 窗口刚移动/改大小：交给逐块核对
                    continue
                # 刚滚动过的窗口：识别偶尔失败的帧也不算“持续变化”，否则连续滚动会被误判成动态背景
                scrolling = now - c.last_scroll_ok < 2.0
                if since_move >= 1.0 and not scrolling and self._volatile_frac(m, part) >= 0.6:
                    # 动态背景（视频、游戏画面）：不做平移分析；内容核对每秒约 10 次就够，省下 CPU。
                    # 正在滚动的区域不会被判成动态（平移解释掉的变化不计入“持续变化”）。
                    now = time.perf_counter()
                    if now - m.vol_proc >= 0.1:
                        m.vol_proc = now
                        self._content_changed(m, part)
                    else:
                        self._mark_needs(m, part)
                    continue
                scrolls += self._try_scroll(m, c, part, track_volatile=since_move >= 1.0 and not scrolling)
        for part in remaining:
            if not geom.empty(part):
                self._content_changed(m, part)
        return scrolls

    def _part_changed(self, m: Mon, part: Rect) -> bool:
        """这一块里有没有像素真的变了的格子（变化区域是外接矩形，可能带进压在上面、其实没变的窗口）。"""
        if self._frame_tiles is None or self._frame_tiles[0] is not m:
            return True
        l, t, rr, b = m.local(part)
        tl, tt = max(0, l // TILE), max(0, t // TILE)
        tr, tb = -(-rr // TILE), -(-b // TILE)
        return bool(self._frame_tiles[1][tt:tb, tl:tr].any())

    def _explained_by_frame_shift(self, m: Mon, wc: Canvas, part: Rect, track_volatile: bool) -> bool:
        """这一帧同一窗口里已经确认过的滚动能不能解释这块变化（同一次滚动被切成几块，这块自己太小、
        或大半是视频认不出来时）。能解释就按那次滚动处理：块沿用确认、待识别标记跟着走，只有残余算内容变化。"""
        for c in wc.descendants():
            mv = self._frame_moved.get(c.cid)
            if mv is None or not c.alive:
                continue
            axis, s = mv
            region = geom.inter(part, c.screen_clip())
            if geom.empty(region) or geom.area(region) < 0.5 * geom.area(part):
                continue
            res = pixels.residual_tiles(m.prev, m.cur, m.local(region), axis, s)
            if sum(geom.area(r) for r in res) > 0.5 * geom.area(region):
                continue
            resid = [geom.shift(rr, *m.origin) for rr in res]
            if c.parent is not None:
                self._adopt(c, c.parent, c.parent.to_content(region), axis, s, shifted=True, avoid=resid)
            self._confirm_pending(region, s, axis)
            self._shift_needs(m, region, axis, s)
            for rr in resid:
                self._content_changed(m, rr, track_volatile)
            for rest in geom.subtract(part, region):
                if not geom.empty(rest):
                    self._content_changed(m, rest, track_volatile)
            self.metrics["scroll_parts_explained"] += 1
            return True
        return False

    def _try_scroll(self, m: Mon, wc: Canvas, part: Rect, track_volatile: bool = True) -> int:
        key = (wc.hwnd, part[0] // 64, part[1] // 64, part[2] // 64, part[3] // 64)
        now = time.perf_counter()
        if self._frame_moved and self._explained_by_frame_shift(m, wc, part, track_volatile):
            return 0
        if self._no_shift_until.get(key, 0) > now:
            self._content_changed(m, part, track_volatile)
            return 0
        local = m.local(part)
        t0 = time.perf_counter()
        # 上一帧对同一区域算过的当前帧行哈希，就是这一帧的上一帧行哈希（处理完一帧后 prev 等于那一帧的 cur）
        hk = (m.idx, wc.hwnd)
        prevh = self._hashes.get(hk)
        hashes = {"prev": prevh[1] if prevh is not None and prevh[0] == m.seq else None}
        res = pixels.detect_shift(m.prev, m.cur, local, axis="v", hashes=hashes)
        self.metrics["hash_reuse"] += hashes["prev"] is not None
        if "cur" in hashes:
            self._hashes[hk] = (m.seq + 1, hashes["cur"])
        if res is None:
            res = pixels.detect_shift(m.prev, m.cur, local, axis="h")
        dt = time.perf_counter() - t0
        self._prof("detect_ms", dt)
        if res is None:
            if geom.area(part) > 200_000:
                # 大片持续变化又不是滚动（视频、动画）：短时间内不再做平移分析，省下算力。
                self._no_shift_until[key] = now + 0.4
                if len(self._no_shift_until) > 512:
                    self._no_shift_until = {k: v for k, v in self._no_shift_until.items() if v > now}
            self._content_changed(m, part, track_volatile)
            return 0
        vp = geom.shift(res.viewport, *m.origin)
        across = (vp[2] - vp[0]) if res.axis == "v" else (vp[3] - vp[1])
        along = (vp[3] - vp[1]) if res.axis == "v" else (vp[2] - vp[0])
        if across < 48 or along < (160 if res.axis == "h" else 40):
            # 太窄的“平移”多半是进度条、加载动画、侧边滑入效果：当内容变化处理，不建滚动画布。
            self._content_changed(m, part, track_volatile)
            return 0
        t_apply = time.perf_counter()
        canvas = self._apply_scroll(m, wc, vp, res.axis, res.shift)
        self._prof("apply_ms", time.perf_counter() - t_apply)
        if canvas is None:
            if abs(res.shift) <= 2:
                self._small_motion(m, part, res, track_volatile)
            else:
                self._content_changed(m, part, track_volatile)
            return 0
        t_res = time.perf_counter()
        if res.entering:
            self._mark_needs(m, geom.shift(res.entering, *m.origin), by_change=False)
        for rr in pixels.residual_tiles(m.prev, m.cur, res.viewport, res.axis, res.shift):
            self._content_changed(m, geom.shift(rr, *m.origin), track_volatile)
        for rest in geom.subtract(part, vp):
            if not geom.empty(rest):
                self._content_changed(m, rest, track_volatile)  # 变化区域里平移没覆盖到的部分（滚动条等）
        self._prof("resid_ms", time.perf_counter() - t_res)
        self.metrics["scrolls"] += 1
        self._metric("scroll", axis=res.axis, shift=res.shift, vp=vp, votes=res.votes, changed=res.changed,
                     bands=res.bands, ms=round(dt * 1000, 2), cid=canvas.cid,
                     ft=round(self._cur_frame_t - self.started, 4))
        return 1

    def _prof(self, key: str, seconds: float) -> None:
        pf = getattr(self, "_prof_frame", None)
        if pf is not None:
            pf[key] += seconds

    def _small_motion(self, m: Mon, part: Rect, res: pixels.ShiftResult, track_volatile: bool) -> None:
        """1~2 像素的整体平移（平滑滚动的头尾帧，还没有滚动画布时）：证据不足以建画布，但变化已经被它解释了。
        范围内的块各自做 ±2 像素校正，只有平移解释不了的残余算内容变化——否则一开始滚动，整个窗口都会被
        当成内容变化重新识别一遍，识别结果稍有出入的段落就会被换掉、重新翻译。"""
        vp = geom.shift(res.viewport, *m.origin)
        for b in self._blocks_in(vp):
            if b.ok_rect is not None and geom.contains(vp, b.screen_rect()) and not self._verify(b):
                b.ok_rect = None
                self._dirty = True
        if res.entering:
            self._mark_needs(m, geom.shift(res.entering, *m.origin), by_change=False)
        for rr in pixels.residual_tiles(m.prev, m.cur, res.viewport, res.axis, res.shift):
            self._content_changed(m, geom.shift(rr, *m.origin), track_volatile)
        for rest in geom.subtract(part, vp):
            if not geom.empty(rest):
                self._content_changed(m, rest, track_volatile)
        self.metrics["small_motion"] += 1

    def _find_scroll_canvas(self, m: Mon, wc: Canvas, vp: Rect, axis: str, s: int) -> tuple[Canvas | None, str]:
        """这次平移属于哪个已知画布：同一个（可能需要扩大范围）、它里面新的一块、还是全新的。"""
        cands = []
        for c in wc.descendants():
            if c.kind != "scroll" or not c.alive or c.axis != axis:
                continue
            cvp = geom.shift(c.viewport, *c.parent.screen_offset())
            ia = geom.area(geom.inter(cvp, vp))
            if ia <= 0:
                continue
            ac, av = geom.area(cvp), geom.area(vp)
            cands.append((ia / (ac + av - ia), ia / av, ia / ac, c, cvp))
        if not cands:
            return None, "new"
        iou, fv, fc, c, cvp = max(cands, key=lambda x: x[0])
        if iou >= 0.5:
            return c, "same"
        # 已知画布比这次大、并包住了它：外面若只有空白，就是整块在动；外面有原地不动的内容，说明里面另有独立区域。
        for iou, fv, fc, c, cvp in sorted(cands, key=lambda x: -x[3].depth()):
            if fv >= 0.8 and fc < 0.8:
                region = m.local(geom.inter(cvp, m.rect))
                inner = m.local(vp)
                if axis == "v":
                    st, mv = pixels.static_rows(m.prev, m.cur, region, inner, s)
                else:
                    st, mv = pixels.static_rows(m.prev.T, m.cur.T, (region[1], region[0], region[3], region[2]),
                                                (inner[1], inner[0], inner[3], inner[2]), s)
                if st <= max(2, mv // 4):
                    return c, "same"
                return None, "nested"
        for iou, fv, fc, c, cvp in cands:
            if fc >= 0.8 and geom.area(cvp) >= 0.4 * geom.area(vp):
                return c, "grow"  # 以前只看到它的一部分
        return None, "new"

    def _apply_scroll(self, m: Mon, wc: Canvas, vp: Rect, axis: str, s: int) -> Canvas | None:
        now = time.perf_counter()
        canvas, how = self._find_scroll_canvas(m, wc, vp, axis, s)
        # 同一次滚动可能被切成几块分别识别出来（变化区域被压在上面的窗口切开、或中间隔着大片没变的空白）：
        # 每个画布每帧只能移动一次，否则译文会被移两遍、全部对不上而被隐藏。
        done = self._moved_with(canvas if canvas is not None else self._deepest_canvas(wc, vp), axis, s)
        if done is not None:
            if done is canvas and abs(s) > 2:
                canvas.viewport = geom.union(canvas.viewport, canvas.parent.to_content(vp))
                self._adopt(canvas, canvas.parent, canvas.parent.to_content(vp), axis, s, shifted=True)
            self._confirm_pending(vp, s, axis)
            self._shift_needs(m, vp, axis, s)
            self._scene_changed()
            return done
        if canvas is not None and canvas.cid in self._frame_moved:
            return None  # 同一帧里同一画布出现两种位移：证据矛盾，这块当内容变化处理
        if canvas is not None:
            if abs(s) > 2:
                # 1~2 像素的位移（平滑滚动的首尾帧）证据弱，只用来移动已知画布，不扩大它的范围
                canvas.viewport = geom.union(canvas.viewport, canvas.parent.to_content(vp))
                # 这次确认在动的范围里还挂在父画布上的块（画布以前只看到一部分时识别的）：一起滚动
                self._adopt(canvas, canvas.parent, canvas.parent.to_content(vp), axis, s, shifted=False)
        elif abs(s) <= 2:
            return None  # 证据太弱，不为它新建画布；当内容变化处理
        elif now - wc.last_move < 1.0:
            return None  # 窗口刚移动/改大小，画面在重排，不是滚动
        else:
            parent = self._deepest_canvas(wc, vp)
            pvp = parent.to_content(vp)
            sib = self._moved_sibling(parent, axis, s)
            if sib is not None:
                # 同一次滚动被压在上面的窗口切成了几块：这块并进同一帧已经移动的兄弟画布（同一个滚动区域），
                # 不另建画布——否则几块各自为政，跨在边界上的段落会被删掉、识别结果对不上原来的块
                self._merge_into(sib, parent, pvp, vp, axis, s)
                self._shift_needs(m, vp, axis, s)
                self._scene_changed()
                return sib
            # 真实的滚动会让整行文字一起移动：新画布的边如果从已有文字块中间切过去，多半是重复内容造成的误判
            cut = inside = 0
            for b in parent.blocks.values():
                if not geom.overlaps(pvp, b.rect):
                    continue
                inside += 1
                if axis == "v" and (b.rect[0] < pvp[0] - 6 or b.rect[2] > pvp[2] + 6):
                    cut += 1
                elif axis == "h" and (b.rect[1] < pvp[1] - 6 or b.rect[3] > pvp[3] + 6):
                    cut += 1
            if cut >= 2 and cut >= 0.3 * inside:
                self._metric("canvas_rejected", vp=vp, cut=cut, inside=inside, axis=axis)
                return None
            # 识别出的滚动范围按墨迹算，比较保守：大部分在范围内、只是行尾伸出去一点的块属于这块区域，
            # 把范围放宽到包住它们（同一行字不会跨在两个独立区域上），不删掉重新识别。
            k0, k1 = (0, 2) if axis == "v" else (1, 3)
            a0, a1 = (1, 3) if axis == "v" else (0, 2)
            for b in parent.blocks.values():
                br = b.rect
                if geom.overlaps(pvp, br) and not geom.contains(pvp, br) and pvp[a0] <= br[a0] and br[a1] <= pvp[a1] \
                        and min(br[k1], pvp[k1]) - max(br[k0], pvp[k0]) >= 0.6 * (br[k1] - br[k0]):
                    ext = list(pvp)
                    ext[k0], ext[k1] = min(pvp[k0], br[k0] - 2), max(pvp[k1], br[k1] + 2)
                    pvp = tuple(ext)
            vp = parent.to_screen(pvp)
            canvas = Canvas("scroll", parent, [0, 0], pvp, axis=axis)
            for b in list(parent.blocks.values()):
                if geom.contains(pvp, b.rect):
                    del parent.blocks[b.bid]
                    b.canvas = canvas
                    canvas.blocks[b.bid] = b
                elif geom.overlaps(pvp, b.rect):
                    self._delete_block(b, "straddle")  # 跨在滚动边界上的块：一半动一半不动，只能重新识别
            for ch in list(parent.children):
                if ch.viewport is not None and geom.contains(pvp, ch.viewport):
                    parent.children.remove(ch)
                    ch.parent = canvas
                    canvas.children.append(ch)
            parent.children.append(canvas)
            self._metric("canvas_new", cid=canvas.cid, axis=axis, vp=vp, hwnd=wc.hwnd, how=how,
                         parent=parent.cid)
        # 只有“旧位置已确认、且新旧位置都在这次确认平移的范围内”的块直接沿用确认；旧位置确认过、但不在
        # 这块范围里的先记下，同一帧别的块确认了同样的平移就照样沿用，都没有再等逐块核对。
        moved = list(self._subtree_blocks(canvas))
        old_rects = {b.bid: b.screen_rect() for b in moved}
        k = 1 if axis == "v" else 0
        for d in canvas.descendants():
            # 里面的子画布这一帧先按同样的位移动过：它其实只是跟着这块一起动，撤销它自己的移动
            if self._frame_moved.get(d.cid) == (axis, s):
                d.offset[k] -= s
                del self._frame_moved[d.cid]
                ep_d = self.episodes.get(d.cid)
                if ep_d is not None and ep_d.shifts and ep_d.shifts[-1] == (self._cur_frame_t, s):
                    ep_d.shifts.pop()
        canvas.offset[k] += s
        self._frame_moved[canvas.cid] = (axis, s)
        canvas.last_move = now
        wc.last_scroll_ok = now
        ep = self.episodes.get(canvas.cid)
        if ep is not None:
            ep.shifts.append((self._cur_frame_t, s))
            ep.last = max(ep.last, self._cur_frame_t)
        canvas.motion.append((self._cur_frame_t, s, max(0.001, self._cur_frame_t - self._prev_frame_t)))
        del canvas.motion[:-6]
        for b in moved:
            old, new = old_rects[b.bid], b.screen_rect()
            if b.ok_rect == old and geom.contains(vp, old) and geom.contains(vp, new):
                b.ok_rect = new
            else:
                if b.ok_rect == old:
                    self._ok_pending[b.bid] = new
                b.ok_rect = None
        if not self._geo_frame_t:
            self._geo_frame_t = self._cur_frame_t
        self._shift_needs(m, vp, axis, s)
        self._scene_changed()
        return canvas

    def _moved_sibling(self, parent: Canvas, axis: str, s: int) -> Canvas | None:
        for ch in parent.children:
            if ch.kind == "scroll" and ch.alive and self._frame_moved.get(ch.cid) == (axis, s):
                return ch
        return None

    def _merge_into(self, canvas: Canvas, parent: Canvas, pvp: Rect, vp: Rect, axis: str, s: int) -> None:
        """把父画布上这块范围（pvp，父画布坐标）并进 canvas：canvas 这一帧已经移动过 s。"""
        canvas.viewport = geom.union(canvas.viewport, pvp)
        self._adopt(canvas, parent, pvp, axis, s, shifted=True)
        self._confirm_pending(vp, s, axis)
        self._metric("canvas_merge", cid=canvas.cid, vp=vp)

    def _adopt(self, canvas: Canvas, parent: Canvas, pvp: Rect, axis: str, s: int, shifted: bool,
               avoid: list[Rect] | None = None) -> int:
        """父画布上落在 pvp（父画布坐标）里的块和子画布改挂到 canvas 下：它们和 canvas 一起滚动。

        shifted=True：canvas 这一帧已经移动过 s，接过来的块也算跟着移动了 s（移动前确认过的等同帧佐证）；
        shifted=False：在移动之前接管，屏幕位置不变，随后由调用方统一移动。avoid 里的屏幕矩形（平移解释
        不了的残余）碰到的块不接管——那里的内容不是跟着滚的。"""
        ox, oy = canvas.screen_offset()
        if shifted:
            bx, by = (ox, oy - s) if axis == "v" else (ox - s, oy)   # 这一帧移动之前 canvas 的屏幕偏移
        else:
            bx, by = ox, oy
        px, py = parent.screen_offset()
        dx, dy = ((0, s) if axis == "v" else (s, 0)) if shifted else (0, 0)
        n = 0
        for b in list(parent.blocks.values()):
            if not geom.contains(pvp, b.rect):
                continue
            old = b.screen_rect()
            if avoid and any(geom.overlaps(old, a) for a in avoid):
                continue
            del parent.blocks[b.bid]
            b.canvas = canvas
            b.rect = geom.shift(old, -bx, -by)
            b.lines = [(geom.shift(lr, px - bx, py - by), t) for lr, t in b.lines]
            b.room_bottom += py - by
            canvas.blocks[b.bid] = b
            if shifted:
                if b.ok_rect == old:
                    self._ok_pending[b.bid] = geom.shift(old, dx, dy)
                b.ok_rect = None
            n += 1
        for ch in list(parent.children):
            if ch is not canvas and ch.viewport is not None and geom.contains(pvp, ch.viewport):
                parent.children.remove(ch)
                ch.parent = canvas
                # 换到 canvas 底下后屏幕位置不变（shifted 时再随这一帧的滚动移动 s，和接过来的块一致）
                ch.viewport = geom.shift(ch.viewport, px - bx, py - by)
                ch.offset[0] += px - bx
                ch.offset[1] += py - by
                canvas.children.append(ch)
        if n:
            self._idx_valid = False
        return n

    def _moved_with(self, c: Canvas | None, axis: str, s: int) -> Canvas | None:
        """c 或它外层的滚动画布这一帧是否已经按同样的位移移动过；是就返回那个画布。"""
        while c is not None and c.kind == "scroll":
            if self._frame_moved.get(c.cid) == (axis, s):
                return c
            c = c.parent
        return None

    def _confirm_pending(self, vp: Rect, s: int, axis: str) -> None:
        """同一帧里另一块也确认了同样的平移：落在这块范围里的、移动前确认过的块照样沿用确认。"""
        dx, dy = (0, s) if axis == "v" else (s, 0)
        for bid, new in list(self._ok_pending.items()):
            b = self.blocks.get(bid)
            if b is None:
                del self._ok_pending[bid]
                continue
            if b.screen_rect() == new and geom.contains(vp, new) and geom.contains(vp, geom.shift(new, -dx, -dy)):
                b.ok_rect = new
                del self._ok_pending[bid]

    def _shift_needs(self, m: Mon, vp: Rect, axis: str, s: int) -> None:
        """待识别标记跟着内容走（按格对齐，取上下两种取整的并集）；“一直在变”的记录也跟着走——
        否则视频滚走以后，滚到它原来位置上的网页文字会被当成在动态画面上（深色底板、旧译文保留）。"""
        l, t, r, b = m.local(vp)
        tl, tt = max(0, l // TILE), max(0, t // TILE)
        tr, tb = min(m.needs.shape[1], -(-r // TILE)), min(m.needs.shape[0], -(-b // TILE))
        if tr <= tl or tb <= tt:
            return
        k = int(round(s / TILE))
        if k:
            for arr in (m.last_chg, m.chg_start):
                sub = arr[tt:tb, tl:tr]
                src_v = sub.copy() if axis == "v" else sub.T.copy()
                dst_v = sub if axis == "v" else sub.T
                n = src_v.shape[0]
                dst_v[:] = 0.0                          # 新露出的格子没有“在变”的历史
                if 0 < k < n:
                    dst_v[k:] = src_v[:n - k]
                elif -n < k < 0:
                    dst_v[:n + k] = src_v[-k:]
        src = m.needs[tt:tb, tl:tr].copy()
        if not src.any():
            return
        out = np.zeros_like(src)
        s_src, s_out = (src, out) if axis == "v" else (src.T, out.T)
        n = s_src.shape[0]
        for k in {s // TILE, -((-s) // TILE)}:
            if 0 <= k < n:
                s_out[k:] = np.maximum(s_out[k:], s_src[:n - k])
            elif -n < k < 0:
                s_out[:n + k] = np.maximum(s_out[:n + k], s_src[-k:])
        m.needs[tt:tb, tl:tr] = out

    def _mark_needs(self, m: Mon, r: Rect, when: float | None = None, by_change: bool = True,
                    track_volatile: bool = True) -> None:
        l, t, rr, b = m.local(r)
        tl, tt = max(0, l // TILE), max(0, t // TILE)
        tr, tb = min(m.needs.shape[1], -(-rr // TILE)), min(m.needs.shape[0], -(-b // TILE))
        if tr > tl and tb > tt:
            now = time.perf_counter()
            sl = (slice(tt, tb), slice(tl, tr))
            sel = None
            if by_change and when is None and self._frame_tiles is not None and self._frame_tiles[0] is m:
                # 处理一帧时传进来的多是变化区域的外接矩形：只标这一帧里像素真的变了的格子。外接矩形里
                # 没变的部分（比如压在播放中的视频上的小窗口）不能当成“在变”，否则会被反复识别、误判成动态区域
                sel = self._frame_tiles[1][sl]
                if not sel.any():
                    return
            if sel is None:
                m.needs[sl] = now if when is None else when
                m.by_change[sl] = by_change
            else:
                m.needs[sl][sel] = now
                m.by_change[sl][sel] = True
            if by_change and when is None and track_volatile:
                # 连续变化（间隔不超过 0.6 秒）算同一轮；持续够久就是动态背景（视频、游戏画面）
                lc = m.last_chg[sl]
                cs = m.chg_start[sl]
                if sel is None:
                    cs[now - lc > 0.6] = now
                    lc[:] = now
                else:
                    cs[(now - lc > 0.6) & sel] = now
                    lc[sel] = now

    def _volatile_mask(self, m: Mon, now: float) -> np.ndarray:
        return (now - m.last_chg < 0.6) & (now - m.chg_start >= VOLATILE_S)

    def _volatile_frac(self, m: Mon, r: Rect, recent: float = 0.6) -> float:
        l, t, rr, b = m.local(r)
        tl, tt = max(0, l // TILE), max(0, t // TILE)
        tr, tb = min(m.needs.shape[1], -(-rr // TILE)), min(m.needs.shape[0], -(-b // TILE))
        if tr <= tl or tb <= tt:
            return 0.0
        now = time.perf_counter()
        vol = (now - m.last_chg[tt:tb, tl:tr] < recent) & (now - m.chg_start[tt:tb, tl:tr] >= VOLATILE_S)
        return float(vol.mean())

    def _is_volatile(self, m: Mon, r: Rect) -> bool:
        l, t, rr, b = m.local(r)
        tl, tt = max(0, l // TILE), max(0, t // TILE)
        tr, tb = min(m.needs.shape[1], -(-rr // TILE)), min(m.needs.shape[0], -(-b // TILE))
        if tr <= tl or tb <= tt:
            return False
        now = time.perf_counter()
        return bool(((now - m.last_chg[tt:tb, tl:tr] < 1.5) & (now - m.chg_start[tt:tb, tl:tr] >= VOLATILE_S)).any())

    def _verify_strokes(self, ref: np.ndarray, m: Mon, sr: Rect, fg: tuple, bg: tuple, em: float) -> bool:
        return pixels.verify_strokes(ref, m.cur, m.local(sr), _lum(fg), _lum(bg), max(8, int(em * 0.8)))

    def _busy_behind(self, m: Mon, sr: Rect, fg: tuple, bg: tuple) -> bool:
        """块后面现在的底是不是花的（视频、游戏场景）：是才改用深色底板。"""
        l, t, r, b = m.local(sr)
        h, w = m.cur.shape
        patch = m.cur[max(0, t):min(h, b), max(0, l):min(w, r)]
        return pixels.busy_background(patch, _lum(fg), _lum(bg))

    def _content_changed(self, m: Mon, r: Rect, track_volatile: bool = True) -> None:
        """内容变化：受影响的块立即核对，对不上就隐藏；区域静止后重新识别。

        变化很小、完全落在仍然核对一致的块里（比如闪烁的光标）时不重新识别。
        """
        covered = 0
        all_ok = True
        for b in self._blocks_in(r):
            if b.ok_rect is None:
                all_ok = False
                continue
            if self._verify(b):
                covered += geom.area(geom.inter(b.screen_rect(), r))
            else:
                b.ok_rect = None
                all_ok = False
                self._dirty = True
        if not (all_ok and covered >= 0.8 * geom.area(r) and geom.area(r) <= 24 * TILE * TILE):
            self._mark_needs(m, r, track_volatile=track_volatile)

    def _verify(self, b: Block) -> bool:
        """在块的预测位置核对像素；允许 ±2 像素的小偏差（顺带校正）。"""
        sr = b.screen_rect()
        m = self._monitor_for(sr)
        if m is None or not m.ready or not geom.contains(m.rect, sr):
            return False
        clip = b.canvas.screen_clip()
        if geom.area(geom.inter(sr, clip)) < 0.6 * geom.area(sr):
            return False  # 大半在画布外：不显示，也不核对
        vmask = self._visible_mask(b, sr)
        if vmask is False:
            return b.ok_rect == sr   # 几乎全被别的窗口挡住：没法核对，维持原判断（反正画出来也被裁掉）
        ok, dx, dy = pixels.verify_patch(b.ref, m.cur, m.local(sr), mask=vmask)
        if not ok and self._is_volatile(m, sr) and self._verify_strokes(b.ref, m, sr, b.lum_fg, b.lum_bg, b.em):
            # 动态背景上的字：背景在动，笔画没变，仍然有效（不更新参考图）。
            # 底真的花才换深色底板；只是被误判在动态区域的网页文字保持原来的底色。
            if not b.dynamic and self._busy_behind(m, sr, b.lum_fg, b.lum_bg):
                b.dynamic = True
                b.bg, b.fg = (24, 24, 28), (245, 245, 245)
                b.version += 1
            b.ok_rect = sr
            b.held_until = 0.0
            return True
        if ok:
            if dx or dy:
                b.rect = geom.shift(b.rect, dx, dy)
                b.lines = [(geom.shift(lr, dx, dy), t) for lr, t in b.lines]
                b.room_bottom += dy
                b.version += 1
                self._idx_valid = False
            b.ok_rect = b.screen_rect()
            b.held_until = 0.0
            b.refind_n = 0
        else:
            self._start_hold(b, sr)
        return ok

    def _refind(self, b: Block) -> bool:
        """块在预测位置对不上时先别丢：沿滚动方向在附近按整段的样子找一找（先比较各行的明暗剖面挑出候选位置，
        再逐像素核对），找到就把块和译文挪过去。滚动识别漏了几帧、平滑滚动的位置没跟上时，译文不会因此消失；
        像素完全一致才挪，所以不会挪到别的文字上（一模一样的重复文字挪过去，译文也一样）。"""
        sr = b.screen_rect()
        m = self._monitor_for(sr)
        if m is None or not m.ready:
            return False
        clip = geom.inter(b.canvas.screen_clip(), m.rect)
        h, w = b.ref.shape
        if h < 6 or w < 12 or geom.empty(clip) or float(b.ref.std()) < 6:
            return False  # 太小或几乎没有笔画的块到处都“对得上”，不找
        vertical = b.canvas.axis != "h"
        reach = 640
        if vertical:
            box = (sr[0], max(clip[1], sr[1] - reach), sr[2], min(clip[3], sr[3] + reach))
        else:
            box = (max(clip[0], sr[0] - reach), sr[1], min(clip[2], sr[2] + reach), sr[3])
        if not geom.contains(m.rect, box) or (box[3] - box[1] < h + 2 if vertical else box[2] - box[0] < w + 2):
            return False
        lb = m.local(box)
        area = m.cur[lb[1]:lb[3], lb[0]:lb[2]]
        ref = b.ref
        if not vertical:
            area, ref = area.T, ref.T
        # 每行切成 8 段取平均作为“剖面”，在搜索范围里滑动比较，挑出最像的几个位置
        sig_ref = cv2.resize(ref.astype(np.float32), (8, ref.shape[0]), interpolation=cv2.INTER_AREA)
        sig_area = cv2.resize(area.astype(np.float32), (8, area.shape[0]), interpolation=cv2.INTER_AREA)
        score = cv2.matchTemplate(sig_area, sig_ref, cv2.TM_SQDIFF).ravel()
        pred = (sr[1] - box[1]) if vertical else (sr[0] - box[0])
        hits: list[int] = []
        tried: list[int] = []
        # 一模一样的重复文字（列表里反复出现的频道名、按钮）剖面得分相同：同分时先试离预测位置近的
        dist = np.abs(np.arange(score.size) - pred)
        for o in np.lexsort((dist, np.round(score, 3)))[:24]:
            o = int(o)
            if any(abs(o - t) < 4 for t in tried):
                continue
            tried.append(o)
            if len(tried) > 4:
                break
            cand = (sr[0], box[1] + o, sr[2], box[1] + o + h) if vertical else (box[0] + o, sr[1], box[0] + o + w, sr[3])
            ok, dx, dy = pixels.verify_patch(b.ref, m.cur, m.local(cand))
            if ok:
                hits.append(o + (dy if vertical else dx))
        if not hits:
            return False
        o = min(hits, key=lambda v: abs(v - pred))
        d = o - pred
        if d == 0:
            return False
        ddx, ddy = (0, d) if vertical else (d, 0)
        b.rect = geom.shift(b.rect, ddx, ddy)
        b.lines = [(geom.shift(lr, ddx, ddy), t) for lr, t in b.lines]
        b.room_bottom += ddy
        b.version += 1
        b.ok_rect = b.screen_rect()
        b.held_until = 0.0
        b.refind_n = 0
        self._idx_valid = False
        self.metrics["refind_ok"] += 1
        self._metric("refind", bid=b.bid, d=d, axis="v" if vertical else "h")
        return True

    def _retire_replaced(self, b: Block) -> None:
        for old_bid in b.replaces:
            old = self.blocks.get(old_bid)
            if old is not None:
                self._delete_block(old, "replaced")
        b.replaces = []

    def _start_hold(self, b: Block, sr: Rect) -> None:
        """动态区域（字幕、游戏文字）的旧译文先保留，等新句子的译文准备好直接顶掉；
        字幕消失（下一次抓拍没有字）或最多保留 subtitle_hold_ms 后撤下。网页、文档不保留。"""
        if b.born_dynamic and b.state == "done" and b.held_until == 0.0 and b.ok_rect is not None:
            b.hold_start = time.perf_counter()
            b.held_until = b.hold_start + self.cfg.track.subtitle_hold_ms / 1000
            b.hold_rect = sr
            self._dirty = True

    def _verify_sweep(self) -> None:
        """挑一些暂时没确认、但应该可见的块重新核对（遮挡解除、窗口移动后、滚回来的内容）。"""
        now = time.perf_counter()
        if now - self._last_verify_sweep < 0.025:
            return
        self._last_verify_sweep = now
        cands = []
        for b in self.blocks.values():
            sr = b.screen_rect()
            if b.ok_rect is not None:
                if b.ok_rect == sr:
                    continue
                b.ok_rect = None
            if b.state == "skip" or not geom.overlaps(sr, b.canvas.screen_clip()):
                continue
            cands.append((self._ring(sr), b))
        if not cands:
            return
        cands.sort(key=lambda x: x[0])
        budget = time.perf_counter() + 0.006
        for _d, b in cands:
            if self._verify(b):
                self._dirty = True
            elif b.canvas.kind != "desktop" and not b.born_dynamic and b.refind_n < 8 and now >= b.refind_at:
                # 预测位置对不上：先在附近找这段，找不到再逐步放慢（字真的没了的话，重新识别时会删掉这块）
                if self._refind(b):
                    self._dirty = True
                else:
                    b.refind_n += 1
                    b.refind_at = now + 0.25 * b.refind_n
            if time.perf_counter() > budget:
                break

    # ------------------------------------------------------------------ 识别调度
    def _schedule_ocr(self) -> None:
        if self.ocr is None or self.ocr_state != "ready" or self.ocr_busy is not None:
            return
        now = time.perf_counter()
        stable = self.cfg.track.stable_ms / 1000
        best = None
        for m in self.mons:
            if not m.ready:
                continue
            pending = m.needs > 0
            if not pending.any():
                continue
            if now - m.last_decay >= 1.0:
                m.heat *= np.float32(0.8 ** (now - m.last_decay))
                m.last_decay = now
            # 反复无故变化的格子（动画、闪烁）要静止更久才重新识别；滚动新露出的内容不受影响。
            ready = pending & (now - m.needs >= stable * (1.0 + np.minimum(m.heat, 20.0)))
            # 魔镜附近一直在变的区域（视频字幕、游戏画面）永远等不到静止：按间隔抓拍识别，
            # 抓不到字就逐步放慢（最慢 8 秒一次）。只做魔镜附近，镜外的动态内容反正很快就变。
            due = np.zeros_like(ready)
            volm = None
            for mirror in self._mirrors:
                near_mirror = geom.inter(geom.expand(mirror, 64), m.rect)
                if geom.empty(near_mirror):
                    continue
                ml, mt, mr, mb = m.local(near_mirror)
                sl = (slice(max(0, mt // TILE), -(-mb // TILE)), slice(max(0, ml // TILE), -(-mr // TILE)))
                if volm is None:
                    volm = self._volatile_mask(m, now)
                vol = volm[sl]
                if vol.any():
                    due[sl] |= pending[sl] & vol & (now - m.last_ocr[sl] >= self.cfg.track.dynamic_ms / 1000
                                                    * m.snap_backoff[sl])
            busy = pending & ~ready & ~due
            if busy.any() and ready.any():
                # 紧挨着还在变化的格子先不识别（滚动途中截到半行）；远处已经静止的照常识别。
                # 旁边一直在变（视频、动画、流式输出的窗口）时不能永远等：静止超过 3 秒的照样识别。
                near = cv2.dilate(busy.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
                ready = ready & (~near | (now - m.needs >= 3.0))
            # 动态区域的抓拍（不受“旁边还在变”的限制，它本身就一直在变）和普通识别分开成块：
            # 连成一片会被扩成整个窗口宽，每次又在旁边识别到字，抓拍间隔永远不放慢
            ready &= ~due
            moving = self._moving_mask(m, now)
            scope, excl = self._scope_masks(m)
            if excl is not None:
                m.needs[excl] = 0          # 排除名单里的窗口：不识别
            for mask in (ready, due):
                if moving is not None:
                    mask &= ~moving        # 正在滚动的区域先不识别：停下再识别，免得结果一出来就过时
                if excl is not None:
                    mask &= ~excl
                if scope is not None:
                    mask &= scope          # 预译范围外的先不识别，魔镜过来再说
            for mask, snap in ((ready, False), (due, True)):
                if not mask.any():
                    continue
                for comp in pixels.components(mask, m.origin, dilate=1):
                    # 跨了几个窗口的待识别区域按窗口分开识别：并排的窗口连成一片时，不必按所有窗口的宽度识别一大块
                    for piece in self._split_by_window(m, comp, mask):
                        d = self._ring(piece)
                        if best is None or d < best[0]:
                            best = (d, m, piece, snap)
        if best is not None:
            _d, m, comp, snap = best
            # 动态区域的抓拍（找视频字幕、游戏文字）只识别那块区域本身，不扩到整个窗口宽：
            # 否则每秒一次的抓拍会把旁边整片网页、别的窗口都重新识别一遍，挤占新内容的识别。
            if snap:
                rect = geom.inter(geom.expand(comp, 24), m.rect)
                win = self._window_at(*geom.center(comp))
                if win.viewport is not None:
                    rect = geom.inter(rect, win.viewport)  # 不要带进旁边窗口或桌面的半截文字
            else:
                rect = self._ocr_region(m, comp)
            if any(geom.overlaps(rect, r) for r in self._moving_clips(time.perf_counter())):
                return  # 识别范围扩进了正在滚动的区域：等滚动停下再识别，免得结果一出来就过时
            self._submit_ocr(m, rect, snap, comp)
            # 识别范围覆盖到的格子都算处理过（含边角不完整的格子），避免同一任务反复提交；
            # 没覆盖到的部分留着，下一轮单独识别。
            covered = geom.inter(rect, comp)
            if not geom.empty(covered):
                self._clear_needs(m, covered, outward=True)

    def _split_by_window(self, m: Mon, comp: Rect, mask: np.ndarray) -> list[Rect]:
        """按窗口（从上到下）切开一块待识别区域：每个窗口露在其中、确实有待识别格子（mask）的部分，
        取这些格子的外接矩形；剩下的是桌面。外接矩形只是碰到、里面却没有待识别格子的窗口不切出来——
        否则会反复识别那个窗口，真正待识别的格子却一直清不掉。"""
        def tiles_box(r: Rect) -> Rect | None:
            # 只算中心落在 r 里的格子：跨在窗口边上的格子（比如半格是视频、半格是压在上面的弹窗）归下面那个窗口
            l, t, rr, b = m.local(r)
            tl, tt = max(0, -(-(l - TILE // 2) // TILE)), max(0, -(-(t - TILE // 2) // TILE))
            tr, tb = min(mask.shape[1], -(-(rr - TILE // 2) // TILE)), min(mask.shape[0], -(-(b - TILE // 2) // TILE))
            if tr <= tl or tb <= tt:
                return None
            ys, xs = np.nonzero(mask[tt:tb, tl:tr])
            if ys.size == 0:
                return None
            box = (m.origin[0] + (tl + int(xs.min())) * TILE, m.origin[1] + (tt + int(ys.min())) * TILE,
                   m.origin[0] + (tl + int(xs.max()) + 1) * TILE, m.origin[1] + (tt + int(ys.max()) + 1) * TILE)
            return geom.inter(box, r)

        pieces: list[Rect] = []
        rest = [comp]
        for hwnd in self.z_order:
            wr = self.win_rects.get(hwnd)
            if wr is None or not any(geom.overlaps(r, wr) for r in rest):
                continue
            boxes = [b for b in (tiles_box(geom.inter(r, wr)) for r in rest if geom.overlaps(r, wr))
                     if b is not None and not geom.empty(b)]
            if boxes:
                pieces.append(_bbox(boxes))
            rest = geom.subtract_all(rest, wr)
            if not rest:
                break
        for r in rest:
            b = tiles_box(r) if not geom.empty(r) else None
            if b is not None and not geom.empty(b):
                pieces.append(b)
        return pieces

    def _ocr_region(self, m: Mon, comp: Rect) -> Rect:
        """识别区域：上下各留 32 像素余量；左右扩到涉及的每个窗口的整宽（没有窗口就到显示器边），
        保证区域边界不会从一行文字中间切过去——切开的半行会被当成新文字块，替换掉原来的整行。
        """
        r = geom.inter(geom.expand(comp, 32), m.rect)
        # 预译范围是“魔镜所在的窗口”时，也不往范围外的窗口扩（那些窗口反正不翻，不必识别）
        allowed = self._windows_in_mirror() if self.cfg.scope.mode == "window" else None
        for _ in range(4):
            grown = r
            for hwnd in self.z_order:
                if allowed is not None and hwnd not in allowed:
                    continue
                wr = self.win_rects.get(hwnd)
                # 只看在这里露出来的窗口（被挡住的窗口在这一片没有可见文字，不必按它的宽度扩）
                if wr is not None and hwnd not in self._excluded \
                        and any(geom.overlaps(v, r) for v in self.visible.get(hwnd, ())):
                    grown = (min(grown[0], wr[0]), grown[1], max(grown[2], wr[2]), grown[3])
            for d in (self.desktop_visible if allowed is None or 0 in allowed else ()):
                if geom.overlaps(d, r):
                    # 桌面上的字（图标名）都很短：顺着露出的桌面向两边扩一些就够，不必扩到整块屏幕
                    grown = (min(grown[0], max(d[0], r[0] - 300)), grown[1], max(grown[2], min(d[2], r[2] + 300)), grown[3])
            grown = geom.inter(grown, m.rect)
            if grown == r:
                break
            r = grown
        # 紧挨着上下边界的已有文字块一并重新识别：内容一条条滚进来时，同一段会被分几次识别成碎片，
        # 这样新露出的行能和上面（或下面）已有的行合成完整的一段，再整体翻译。
        top, bottom = r[1], r[3]
        for b in self._blocks_in((r[0], r[1] - 14, r[2], r[3] + 14)):
            sr = b.screen_rect()
            if sr[1] < r[1] <= sr[3] + 14 and r[1] - sr[1] <= 600:
                top = min(top, sr[1] - 4)
            if sr[1] - 14 <= r[3] < sr[3] and sr[3] - r[3] <= 600:
                bottom = max(bottom, sr[3] + 4)
        return geom.inter((r[0], top, r[2], bottom), m.rect)

    def _submit_ocr(self, m: Mon, rect: Rect, snap: bool = False, piece: Rect | None = None) -> None:
        l, t, r, b = m.local(rect)
        if r - l < 8 or b - t < 8:
            self._clear_needs(m, rect)
            return
        bgr = np.ascontiguousarray(m.bgra[t:b, l:r, :3])
        gray = m.cur[t:b, l:r].copy()
        for hwnd in self._excluded:
            # 排除名单里的窗口在送去识别前就涂掉：这些内容不会被识别，更不会发给翻译服务
            for v in self.visible.get(hwnd, ()):
                c = geom.inter(v, rect)
                if not geom.empty(c):
                    sl = (slice(c[1] - rect[1], c[3] - rect[1]), slice(c[0] - rect[0], c[2] - rect[0]))
                    bgr[sl] = 128
                    gray[sl] = 128
        self._job_ids += 1
        near = min(self._mirrors, key=lambda mr: geom.ring_distance(rect, mr))
        job = OcrJob(self._job_ids, bgr, (rect[0], rect[1]), near, self.cfg.track.ring_px)
        allc = [self.desktop]
        for c in self.win_canvas.values():
            if c.alive and geom.overlaps(c.viewport, rect):
                allc.append(c)
                allc.extend(d for d in c.descendants() if d.alive)
        z_then = [(h, self.win_rects[h]) for h in self.z_order if h in self.win_rects]
        st = JobState(job, m, rect, gray, bgr, {c.cid: c.screen_offset() for c in allc},
                      {c.cid: c.screen_clip() for c in allc}, allc, z_then, time.perf_counter())
        for bl in self._blocks_in(rect):
            sr = bl.screen_rect()
            # 只记识别时看得见的块：被别的窗口挡住的块识别不到是正常的，不能据此当成“字没了”删掉
            if geom.contains(rect, sr) and self._visible_frac(bl, sr) >= 0.9:
                st.blocks_before.append((bl.bid, sr))
        self.jobs[job.job_id] = st
        self.ocr_busy = st
        tl, tt = max(0, l // TILE), max(0, t // TILE)
        tr, tb = -(-r // TILE), -(-b // TILE)
        st.snapshot = snap     # 动态区域的抓拍：没抓到字就放慢下一次（见 _finish_job）
        st.tiles = (tt, tb, tl, tr)
        m.last_ocr[tt:tb, tl:tr] = st.submitted
        m.heat[tt:tb, tl:tr] += m.by_change[tt:tb, tl:tr] & (m.needs[tt:tb, tl:tr] > 0)
        self._clear_needs(m, rect)
        self.ocr.submit(job)
        self.metrics["ocr_jobs"] += 1
        self._metric("ocr_submit", job=job.job_id, rect=rect, area=geom.area(rect), snap=snap, piece=piece)

    def _cool(self, m: Mon, rect: Rect) -> None:
        l, t, rr, b = m.local(rect)
        m.heat[max(0, t // TILE):-(-b // TILE), max(0, l // TILE):-(-rr // TILE)] = 0

    def _clear_needs(self, m: Mon, rect: Rect, outward: bool = False) -> None:
        l, t, rr, b = m.local(rect)
        if outward:
            tl, tt = max(0, l // TILE), max(0, t // TILE)
            tr, tb = min(m.needs.shape[1], -(-rr // TILE)), min(m.needs.shape[0], -(-b // TILE))
        else:
            tl, tt = max(0, -(-l // TILE)), max(0, -(-t // TILE))
            tr, tb = min(m.needs.shape[1], rr // TILE), min(m.needs.shape[0], b // TILE)
        if tr > tl and tb > tt:
            m.needs[tt:tb, tl:tr] = 0

    def _on_ocr(self, msg: tuple) -> None:
        kind, job_id, data = msg
        if kind == "ready":
            self.ocr_state = "ready"
            log.info("识别进程就绪（%s，%s）", data.get("device"), data.get("lang", "default"))
            if data.get("wanted", "default") != data.get("lang", "default"):
                self.error = self._ko_fallback = tr("韩文识别模型没能下载，暂时用默认模型（检查网络后重新选一次韩文）")
            elif self._ko_fallback and self.error == self._ko_fallback:
                self.error = self._ko_fallback = ""
            self._dirty = True
            return
        if kind == "fatal":
            self.ocr_state = "error"
            self.error = tr("文字识别启动失败")
            log.error("识别进程失败：%s", data)
            self._dirty = True
            return
        st = self.jobs.get(job_id)
        if st is None:
            return
        if kind == "blocks":
            for ob in data:
                self._accept_block(st, ob)
            self._scene_changed()
        elif kind == "error":
            log.warning("识别任务出错：%s", data)
        elif kind == "done":
            self._finish_job(st, data)

    def _finish_job(self, st: JobState, info: dict) -> None:
        # 提交时在区域内、这次识别没再出现的旧块：原文已经没了，删除。
        for bid, _sr0 in st.blocks_before:
            b = self.blocks.get(bid)
            if b is None or bid in st.touched or b.created > st.submitted:
                continue
            if b.held_until > 0 and st.submitted < b.hold_start:
                # 换句之前就开始的识别看到的是旧画面，不能据此判定“字幕消失了”；保留中的旧译文不动
                continue
            off0 = st.offsets.get(b.canvas.cid)
            if off0 is None:
                continue
            ox, oy = b.canvas.screen_offset()
            if st.stale and (ox, oy) != tuple(off0):
                continue  # 识别期间这块跟着画布动过、又有结果因过时被丢：“没识别到”不可信，不删
            if geom.contains(st.rect, geom.shift(b.screen_rect(), off0[0] - ox, off0[1] - oy)):
                self._delete_block(b, "ocr_not_seen")
        if getattr(st, "snapshot", False) and getattr(st, "tiles", None):
            # 动态区域的抓拍：没抓到字就放慢下一次，抓到了就恢复正常间隔
            tt, tb, tl, tr = st.tiles
            bo = st.mon.snap_backoff[tt:tb, tl:tr]
            if info.get("blocks", 0) == 0:
                bo[:] = np.minimum(8.0, bo * 2)
            else:
                bo[:] = 1.0   # 抓到字（哪怕是没变的字幕）就保持每秒一次：字幕换句要尽快发现
        self.jobs.pop(st.job.job_id, None)
        if self.ocr_busy is st:
            self.ocr_busy = None
        self.metrics["ocr_s"] += info.get("total_s", 0)
        self._metric("ocr_done", job=st.job.job_id, wait=round(time.perf_counter() - st.submitted, 3),
                     **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in info.items() if k != "size"})
        self._scene_changed()

    def _owner_then(self, st: JobState, x: float, y: float) -> Canvas:
        """提交识别时 (x, y) 处的画布：当时最上层的窗口里，最深的滚动画布。"""
        root = self.desktop
        for hwnd, r in st.z_then:
            if geom.contains_pt(r, x, y):
                c = self.win_canvas.get(hwnd)
                if c is not None and c.alive and c.cid in st.clips:
                    root = c
                break
        best, best_depth = root, root.depth()
        for c in st.canvases:
            if c.kind != "scroll" or not c.alive or c.window() is not root:
                continue
            clip = st.clips.get(c.cid)
            d = c.depth()
            if clip is not None and geom.contains_pt(clip, x, y) and d > best_depth:
                best, best_depth = c, d
        return best

    def _accept_block(self, st: JobState, ob: OcrBlockOut) -> None:
        text = ob.text.strip()
        if not text:
            return
        r0 = ob.rect
        canvas = self._owner_then(st, *geom.center(r0))
        if not canvas.alive:
            return
        owner = canvas.window()
        if owner is not None and owner.hwnd in self._excluded:
            return
        off0 = st.offsets.get(canvas.cid, canvas.screen_offset())
        ox, oy = canvas.screen_offset()
        r_now = geom.shift(r0, ox - off0[0], oy - off0[1])
        jl, jt = st.rect[0], st.rect[1]
        ref = st.gray[r0[1] - jt:r0[3] - jt, r0[0] - jl:r0[2] - jl].copy()
        if ref.size == 0:
            return
        if canvas.kind == "scroll":
            # 露在滚动画布边缘、被裁了一截的行先不收，滚进来以后再识别。
            clip = st.clips.get(canvas.cid)
            if clip is not None:
                if canvas.axis == "v" and (r0[1] <= clip[1] + 1 or r0[3] >= clip[3] - 1):
                    return
                if canvas.axis == "h" and (r0[0] <= clip[0] + 1 or r0[2] >= clip[2] - 1):
                    return
            # 画布范围按墨迹算、偏保守：行尾伸出画布侧边一点的块属于这块区域，放宽范围，免得译文被裁掉一截
            vpc, pr = canvas.viewport, canvas.parent.to_content(r_now)
            k0, k1 = (0, 2) if canvas.axis == "v" else (1, 3)
            if (pr[k0] < vpc[k0] or pr[k1] > vpc[k1]) \
                    and min(pr[k1], vpc[k1]) - max(pr[k0], vpc[k0]) >= 0.6 * (pr[k1] - pr[k0]):
                ext = list(vpc)
                ext[k0], ext[k1] = min(vpc[k0], pr[k0] - 2), max(vpc[k1], pr[k1] + 2)
                canvas.viewport = tuple(ext)
                self._scene_changed()
        m = self._monitor_for(r_now)
        verified: Rect | None = None
        bg_moving = False   # 识别期间字后面的画面变了、笔画还在：字在一直变化的画面上（字幕、游戏）
        if m is not None and m.ready and geom.contains(m.rect, r_now) and geom.overlaps(r_now, canvas.screen_clip()):
            ok, dx, dy = pixels.verify_patch(ref, m.cur, m.local(r_now))
            if not ok and self._is_volatile(m, r_now):
                # 动态背景：按笔画核对（颜色先用当时截图估计）
                sub = st.bgr[r0[1] - jt:r0[3] - jt, r0[0] - jl:r0[2] - jl]
                lr0 = [(ln.rect[0] - r0[0], ln.rect[1] - r0[1], ln.rect[2] - r0[0], ln.rect[3] - r0[1]) for ln in ob.lines]
                bg0, fg0 = textutil.sample_colors(sub, lr0)
                em0 = max(font_em(Line(ln.rect, ln.text)) for ln in ob.lines)
                ok = self._verify_strokes(ref, m, r_now, fg0, bg0, em0)
                bg_moving = ok
                dx = dy = 0
            if not ok:
                self.metrics["ocr_stale"] += 1
                st.stale += 1
                return  # 识别期间这里变了：丢掉，变化检测会重新安排识别
            r_now = geom.shift(r_now, dx, dy)
            verified = r_now
        content = canvas.to_content(r_now)
        dx, dy = content[0] - r0[0], content[1] - r0[1]
        lines = [(geom.shift(ln.rect, dx, dy), ln.text) for ln in ob.lines]
        key = textutil.cache_key(text)
        # 这次的结果只是把已有的块重新分了组（几行合成一段、一段拆成几行，或者只识别到其中一部分），
        # 而这些块的像素都没变：原样保留，不换块、不重新翻译。含有已有块没盖住的新行时才按新的分组替换
        # （滚动进来的新行和上面的旧行合成完整的一段再翻译）。
        olds = [o for o in canvas.blocks.values() if geom.overlaps(o.rect, content)
                and geom.area(geom.inter(o.rect, content)) >= 0.5 * min(geom.area(o.rect), geom.area(content))]
        if olds and not any(o.key == key for o in olds) \
                and all(any(geom.area(geom.inter(o.rect, lr)) >= 0.8 * geom.area(lr) for o in olds) for lr, _t in lines) \
                and all(o.ok_rect is not None and o.ok_rect == o.screen_rect() and self._verify(o) for o in olds):
            st.touched.update(o.bid for o in olds)
            self.metrics["ocr_regroup_kept"] += 1
            return
        replaced: list[Block] = []
        number_tick = False      # 同一位置只是数字变了（计时器、计数、血量）
        tmpl = number_template(text)
        # 与已有块去重：同位置同文字沿用原块（保留译文），文字变了就替换。
        for old in list(canvas.blocks.values()):
            if not geom.overlaps(old.rect, content):
                continue
            ia = geom.area(geom.inter(old.rect, content))
            if ia < 0.5 * min(geom.area(old.rect), geom.area(content)):
                continue
            same_place = (geom.area(geom.inter(old.rect, content))
                          >= 0.8 * max(geom.area(old.rect), geom.area(content)))
            if same_place and tmpl is not None and old.key != key:
                ot = number_template(old.text)
                if ot is not None and textutil.cache_key(ot[0]) == textutil.cache_key(tmpl[0]):
                    number_tick = True
            if old.key != key and same_place and old.ok_rect is not None and self._verify(old):
                # 像素和上次识别时完全一样，只是这次 OCR 结果差了一两个字：沿用旧块和旧译文，
                # 不为“同样的内容”再发一次翻译请求。
                st.touched.add(old.bid)
                return
            if old.key == key and abs(old.rect[0] - content[0]) <= 3 and abs(old.rect[1] - content[1]) <= 3:
                # 同一段文字重新识别：仍然对得上的旧块原样保留（不让译文跟着检测框抖动 1~3 像素），
                # 旧块对不上了才换成这次的位置和参考图。
                if old.ok_rect is None or old.ok_rect != old.screen_rect() or not self._verify(old):
                    old.ref = ref
                    old.rect = content
                    old.lines = lines
                    old.ok_rect = verified
                    old.version += 1
                    self._idx_valid = False
                st.touched.add(old.bid)
                return
            if old.born_dynamic and old.state == "done" and key not in self.cache:
                # 新句子还没译好：旧译文先留着，新译文一到就顶掉（见 _retire_replaced）
                if old.held_until == 0.0:
                    old.hold_start = time.perf_counter()
                    old.held_until = old.hold_start + self.cfg.track.subtitle_hold_ms / 1000
                    old.hold_rect = old.screen_rect()
                replaced.append(old)
                st.touched.add(old.bid)
                continue
            self._delete_block(old, "ocr_overlap")
        crop_l, crop_t = r0[0] - jl, r0[1] - jt
        pad = 3
        ol, ot = max(0, crop_l - pad), max(0, crop_t - pad)
        sub = st.bgr[ot:crop_t + ref.shape[0] + pad, ol:crop_l + ref.shape[1] + pad]
        line_local = [(ln.rect[0] - jl - ol, ln.rect[1] - jt - ot, ln.rect[2] - jl - ol, ln.rect[3] - jt - ot)
                      for ln in ob.lines]
        bg, fg = textutil.sample_colors(sub, line_local)
        hs = sorted(lr[3] - lr[1] for lr, _ in lines)
        # 字号取各行“正文字高”的偏低中位数：带上标的行、没有上下伸字母的行都不会把字号带偏
        ems = sorted(font_em(Line(lr, t)) for lr, t in lines)
        b = Block(canvas, content, lines, text, key, ref, bg, fg, hs[len(hs) // 2], ems[(len(ems) - 1) // 2],
                  job_id=st.job.job_id, lum_fg=fg, lum_bg=bg)
        b.ok_rect = verified
        b.room_bottom = content[3]
        win = canvas.window()
        recently_scrolled = win is not None and time.perf_counter() - win.last_scroll_ok < 2.0
        if m is not None and not recently_scrolled and self._volatile_frac(m, r_now, recent=1.5) >= 0.5:
            # 一出现就在一直变化的区域里（字幕、游戏文字）：换句时旧译文保留到新译文顶掉。
            # 但整个窗口都被当成“在变”、字后面的画面却既不花、识别期间也没变（比如滚动没跟上的网页）不算，
            # 否则网页文字会顶着过时的旧译文。深色底板只给底真的花的字（视频、游戏场景）。
            busy = pixels.busy_background(ref, _lum(fg), _lum(bg))
            still_changing = self._volatile_frac(m, r_now, recent=0.3) >= 0.5   # 动画、视频此刻还在动
            area = geom.inter(win.viewport if win is not None else m.rect, m.rect)
            if busy or bg_moving or still_changing or self._volatile_frac(m, area, recent=1.5) < 0.6:
                b.born_dynamic = True
            if busy:
                b.dynamic = True
                b.bg, b.fg = (24, 24, 28), (245, 245, 245)
        if not textutil.needs_translation(text, self.cfg.target_lang) or textutil.looks_like_code(text):
            b.state = "skip"
        elif (hit := self._cached(key, text)) is not None:
            b.translation = hit
            b.state = "skip" if textutil.cache_key(b.translation) == key else "done"
            self.metrics["cache_hits"] += 1
            if number_tick and m is not None:
                # 只是数字变了、译文直接套用：这里是计数器而不是动画，不算“无故变化”，
                # 下次数字再变时不用等更久才识别（否则每变一次，新数字的译文要晚一秒多才出来）
                self._cool(m, r_now)
                self.metrics["number_ticks"] += 1
        canvas.blocks[b.bid] = b
        self.blocks[b.bid] = b
        self.by_key[key].add(b.bid)
        st.touched.add(b.bid)
        if replaced:
            if b.state in ("done", "skip"):
                for old in replaced:
                    self._delete_block(old, "replaced")
            else:
                b.replaces = [old.bid for old in replaced]
        self._update_room(canvas, b, m)
        self._trim_cache()

    def _update_room(self, canvas: Canvas, b: Block, m: Mon | None = None) -> None:
        """排版时向下延伸的上限：到下方最近的块为止，最多再延伸两个行高。
        向右：译文在原文那么宽的地方放不下时（中日文译成英文常这样），可以借用右边的空白——到右边最近的块为止，
        而且那片地方得一直是和底色一样的纯色（不盖住图片、边框、视频画面），最多借原宽度的两倍。"""
        limit = b.rect[3] + 2 * b.line_h
        for o in canvas.blocks.values():
            if o is b or not (o.rect[0] < b.rect[2] and b.rect[0] < o.rect[2]):
                continue
            if o.rect[1] >= b.rect[3]:
                limit = min(limit, o.rect[1] - 2)
            elif b.rect[1] >= o.rect[3] and o.room_bottom > b.rect[1] - 2:
                o.room_bottom = max(o.rect[3], b.rect[1] - 2)
                o.version += 1
        b.room_bottom = max(b.rect[3], limit)
        gap = max(8, b.line_h // 2)
        right = b.rect[2] + min(2 * (b.rect[2] - b.rect[0]), 900)
        nearest = b.rect[2] + 900                                 # 右边最近的块（不看底色）
        for o in canvas.blocks.values():
            if o is b:
                continue
            if o.rect[0] >= b.rect[2] - 2 and o.rect[1] < b.room_bottom and b.rect[1] < o.rect[3]:
                nearest = min(nearest, o.rect[0] - gap)
            elif (o.extra_w or o.extra_max) and b.rect[0] >= o.rect[2] - 2 and b.rect[1] < o.room_bottom \
                    and o.rect[1] < b.rect[3]:
                # 新块占了左边那块原来能借的地方
                og = max(8, o.line_h // 2)
                room = max(0, b.rect[0] - og - o.rect[2])
                if o.extra_w > room or o.extra_max > room:
                    o.extra_w, o.extra_max = min(o.extra_w, room), min(o.extra_max, room)
                    o.version += 1
        right = min(right, nearest)
        if b.dynamic or m is None:
            b.extra_w = b.extra_max = 0
            return
        sr = b.screen_rect()
        clip_room = b.canvas.screen_clip()[2] - 4 - sr[2]                 # 不伸出所在画布的可见范围
        b.extra_max = max(0, min(nearest - b.rect[2], clip_room))
        if right <= b.rect[2] or self._volatile_frac(m, (sr[2], sr[1], sr[2] + right - b.rect[2], sr[3]), 1.5) > 0.3:
            b.extra_w = 0      # 右边在动（视频、动画）：底板不能盖上去，哪怕颜色看着一样
        else:
            b.extra_w = self._plain_right(m, b, right - b.rect[2])

    def _plain_right(self, m: Mon, b: Block, most: int) -> int:
        """原文块右边有多宽是和底色一样的纯色（逐列看块所在的那几行），不超出所在画布的可见范围。
        只看块本身的行：下面可借的行常常跨过对话框、面板的边框，一并检查的话哪儿都借不到。"""
        sr = b.screen_rect()
        clip = b.canvas.screen_clip()
        right = min(sr[2] + most, clip[2] - 4)
        h, w = m.cur.shape
        l, t, r, bb = m.local((sr[2], sr[1], right, sr[3]))
        l, t, r, bb = max(0, l), max(0, t), min(w, r), min(h, bb)
        if r - l < 4 or bb <= t:
            return 0
        # 一列里大部分像素都是底色才算空白：半透明面板后面透出来的零星星点、细浪线不算，边框、图片那种整列都不一样的才挡住
        off = (np.abs(m.cur[t:bb, l:r].astype(np.int16) - int(round(_lum(b.lum_bg)))) > 28).mean(axis=0)
        bad = np.flatnonzero(off > 0.15)
        return max(0, int(bad[0]) - 6) if bad.size else r - l     # 碰到图案、边框就停，离它留一点

    def _delete_block(self, b: Block, why: str = "") -> None:
        if self._metrics_fh and b.bid in self.blocks:
            self._metric("block_del", bid=b.bid, why=why, rect=b.screen_rect(), ok=b.ok_rect is not None,
                         age=round(time.perf_counter() - b.created, 2))
        b.canvas.blocks.pop(b.bid, None)
        if self.blocks.pop(b.bid, None) is not None:
            ids = self.by_key.get(b.key)
            if ids is not None:
                ids.discard(b.bid)
                if not ids:
                    del self.by_key[b.key]
        self._scene_changed()

    def _trim_cache(self) -> None:
        limit = self.cfg.track.max_cache_blocks
        if len(self.blocks) > limit:
            # 先丢最久、且当前没有确认可见的块
            victims = sorted((b for b in self.blocks.values() if b.ok_rect is None), key=lambda b: b.created)
            for b in victims[:len(self.blocks) - limit]:
                self._delete_block(b)
        while len(self.cache) > self.cfg.track.max_cache_texts:
            self.cache.popitem(last=False)

    # ------------------------------------------------------------------ 翻译调度
    def _schedule_translation(self) -> None:
        self._last_trans_sched = time.perf_counter()
        if self.pool is None:
            return
        svc = self.service
        now = time.perf_counter()
        if svc["paused"] or now < svc["until"]:
            return
        if len(self.inflight) >= self.cfg.llm.concurrency:
            return
        under = self._windows_in_mirror() if self.cfg.scope.mode == "window" else None
        cands = []
        n_tmpl = len(self.templates)
        for b in self.blocks.values():
            if b.state == "failed" and b.attempts < 3 and b.retry_at <= now:
                b.state = "pending"
            if b.state != "pending":
                continue
            hit = self._cached(b.key, b.text)
            if hit is not None:
                self._apply_hit(b, hit)
                continue
            sr = b.screen_rect()
            if not self._in_scope(b, sr, under):
                continue
            on_screen = b.ok_rect is not None or geom.overlaps(sr, b.canvas.screen_clip())
            cands.append((0 if on_screen else 1, self._ring(sr), b))
        if cands and len(self.templates) != n_tmpl:
            # 这一轮从记忆里取到的译文刚学会了数字模板：排在前面没命中的、只差数字的文字再试一次
            rest = []
            for c in cands:
                hit = self._cached(c[2].key, c[2].text)
                if hit is None:
                    rest.append(c)
                else:
                    self._apply_hit(c[2], hit)
            cands = rest
        if not cands:
            return
        cands.sort(key=lambda x: (x[0], x[1]))
        # 一批只放同一个窗口的文字：窗口标题作为背景交给模型（比如 CSS 文档里的属性名不翻译）
        win = cands[0][2].canvas.window()
        hwnd = win.hwnd if win is not None else 0
        texts, keys, chars = [], [], 0
        dynamic = False
        for _o, _d, b in cands:
            bw = b.canvas.window()
            if (bw.hwnd if bw is not None else 0) != hwnd:
                continue
            if b.key in keys:
                continue
            dynamic = dynamic or b.born_dynamic
            single = b.key in self.retry_single
            full = chars + len(b.text) > self.cfg.llm.max_batch_chars or len(texts) >= self.cfg.llm.max_batch_items
            if texts and (single or full):
                break
            texts.append(b.text)
            keys.append(b.key)
            chars += len(b.text)
            if single:
                break  # 需要单独重译的一块自己一批
        for key in keys:
            for bid in self.by_key.get(key, ()):
                b = self.blocks.get(bid)
                if b is not None and b.state == "pending":
                    b.state = "translating"
        self._batch_ids += 1
        context = winapi.window_title(hwnd)[:120] if hwnd else "Windows desktop (icon labels, file and app names)"
        app = self._app_of(hwnd)
        refs = self.refs.select(texts, keys, hwnd, app) if self.cfg.llm.consistency else []
        batch = Batch(self._batch_ids, texts, keys, self.cfg.target_lang, context,
                      self._glossary_terms(hwnd, texts), refs, hwnd, app, self.cfg.source_lang,
                      self._dialog_context(hwnd, keys) if dynamic else [])
        self.inflight[batch.batch_id] = Inflight(batch)
        svc["requests"] += 1
        svc["chars"] = svc.get("chars", 0) + chars
        svc["state"] = "busy"
        self.pool.submit(batch)
        ref_chars = sum(len(s) + len(d) for s, d in refs)
        self.metrics["ref_chars"] += ref_chars
        self._metric("tr_submit", batch=batch.batch_id, n=len(texts), chars=chars, hwnd=hwnd,
                     keys=[zlib.crc32(k.encode("utf-8")) for k in keys], refs=len(refs), ref_chars=ref_chars,
                     dialog=len(batch.dialog))
        self._dirty = True

    def _on_translation(self, ev: tuple) -> None:
        kind = ev[0]
        if kind == "segment":
            _k, batch_id, idx, text = ev
            inf = self.inflight.get(batch_id)
            if inf is None or idx >= len(inf.batch.keys):
                return
            inf.received.add(idx)
            key = inf.batch.keys[idx]
            if key not in self.retry_single and textutil.looks_untranslated(inf.batch.texts[idx], text,
                                                                           inf.batch.target):
                # 模型把半句英文原样留下了：不进缓存，这一块下次单独重译一次（再不行就接受）
                self.retry_single.add(key)
                for bid in self.by_key.get(key, ()):
                    b = self.blocks.get(bid)
                    if b is not None and b.state == "translating":
                        b.state = "pending"
                self.metrics["partial_retry"] += 1
                return
            self.retry_single.discard(key)
            self.cache[key] = text
            self.cache.move_to_end(key)
            self.templates.learn(textutil.cache_key, inf.batch.texts[idx], text)
            if self.memory is not None:
                self.memory.put(self.cfg.target_lang, key, text)
            same = textutil.cache_key(text) == key  # 模型原样返回（名称、代码、已是目标语言）：不遮盖原文
            if not same:
                self.refs.add(key, inf.batch.texts[idx], text, inf.batch.hwnd, inf.batch.app)
                if any(b.born_dynamic for b in (self.blocks.get(i) for i in self.by_key.get(key, ())) if b):
                    hist = self.dialog.setdefault(inf.batch.hwnd, collections.deque(maxlen=6))
                    hist.append((time.perf_counter(), inf.batch.texts[idx], text))
            # 迟到的结果按原文对号入座：文字已经变了的块拿不到它，只进缓存。
            for bid in list(self.by_key.get(key, ())):
                b = self.blocks.get(bid)
                if b is not None and b.state in ("translating", "pending", "failed"):
                    b.translation = text
                    b.state = "skip" if same else "done"
                    b.error = ""
                    b.version += 1
                    self._retire_replaced(b)
            self._dirty = True
        elif kind == "batch_done":
            _k, batch_id, err, secs = ev
            inf = self.inflight.pop(batch_id, None)
            if inf is None:
                return
            svc = self.service
            now = time.perf_counter()
            missing = [k for i, k in enumerate(inf.batch.keys) if i not in inf.received]
            if err is None:
                svc.update(fails=0, state="ok", message="", last_ok=now, slow=secs > 8)
                msg = tr("模型漏掉了这段")
                retry = now + 5.0
            else:
                svc["fails"] += 1
                backoff = min(60.0, 2.0 ** min(svc["fails"], 6))
                svc.update(until=now + backoff, state="error", message=str(err))
                if not getattr(err, "retryable", True):
                    svc["paused"] = True
                msg = str(err)
                retry = now + backoff
                log.warning("翻译批次失败：%s（%.1f 秒）", err, secs)
            for key in missing:
                for bid in self.by_key.get(key, ()):
                    b = self.blocks.get(bid)
                    if b is not None and b.state == "translating":
                        b.state = "failed"
                        b.error = msg
                        b.attempts += 1
                        b.retry_at = retry
            self._metric("tr_done", batch=batch_id, ok=err is None, secs=round(secs, 3), missing=len(missing))
            self._dirty = True

    def _cached(self, key: str, text: str) -> str | None:
        """已有的译文：用户改过的 → 内存缓存 → 本地记忆 → 只有数字不同的已有译文（套模板）。"""
        v = self.overrides.get(key)
        if v is not None:
            return v
        v = self.cache.get(key)
        if v is not None:
            self.cache.move_to_end(key)
            return v
        if self.memory is not None:
            v = self.memory.get(self.cfg.target_lang, key)
            if v is not None:
                self.cache[key] = v
                self.templates.learn(textutil.cache_key, text, v)   # 只差数字的其他文字也能直接套用
                self.metrics["memory_hits"] += 1
                return v
        v = self.templates.lookup(textutil.cache_key, text)
        if v is not None:
            self.cache[key] = v
            self.metrics["template_hits"] += 1
        return v

    def _apply_hit(self, b: Block, hit: str) -> None:
        b.translation = hit
        b.state = "skip" if textutil.cache_key(hit) == b.key else "done"
        b.version += 1
        self._dirty = True

    def _override(self, key: str, text: str) -> None:
        """用户改了一段译文：这段文字现在和以后都用新译文（打开了译文记忆时也记进去）。"""
        self.overrides[key] = text
        self.cache[key] = text
        self.refs.update(key, text)
        if self.memory is not None:
            self.memory.put(self.cfg.target_lang, key, text)
        for bid in self.by_key.get(key, ()):
            b = self.blocks.get(bid)
            if b is not None:
                b.translation = text
                b.state = "done"
                b.version += 1
        self._dirty = True

    def _dialog_context(self, hwnd: int, keys: list[str]) -> list[tuple[str, str]]:
        """同一窗口 30 秒内最近的 3 句字幕 / 对话（不含这一批本身），从早到晚。"""
        now = time.perf_counter()
        skip = set(keys)
        lines = [(s, t) for ts, s, t in self.dialog.get(hwnd, ())
                 if now - ts <= 30 and textutil.cache_key(s) not in skip]
        return lines[-3:]

    def _app_of(self, hwnd: int) -> str:
        """窗口所属程序的文件名（小写，如 msedge.exe）；桌面本身是空字符串。"""
        return self._proc_names.get(self.win_pids.get(hwnd, -1), "") if hwnd else ""

    def _glossary_terms(self, hwnd: int, texts: list[str]) -> list[tuple[str, str]]:
        """这批文字里出现的术语（全局的，加上只用于这个窗口所属程序的）。"""
        if not self.cfg.glossary:
            return []
        app = self._app_of(hwnd)
        low = [t.lower() for t in texts]
        out = []
        for g in self.cfg.glossary:
            ga = g.get("app", "").lower()
            if ga and app not in (ga, ga + ".exe"):
                continue
            if any(_term_in(g["src"].lower(), t) for t in low):
                out.append((g["src"], g["dst"]))
        return out[:40]

    def _glossary_changed(self, terms: list[str]) -> None:
        """术语表改了：含这些词的已有译文作废，重新翻译（用户改过的译文不动）。"""
        low = [t.lower() for t in terms if t]
        if not low:
            return
        stale = [k for k in self.cache if k not in self.overrides and any(t in k.lower() for t in low)]
        for k in stale:
            del self.cache[k]
            for bid in self.by_key.get(k, ()):
                b = self.blocks.get(bid)
                if b is not None and b.state in ("done", "skip", "failed"):
                    b.state = "pending"
                    b.attempts = 0
                    b.version += 1
        if self.memory is not None:
            self.memory.drop(lambda k: any(t in k.lower() for t in low))
        self.refs.drop(lambda src: any(t in src.lower() for t in low))   # 旧译法不能再当参考
        self.templates.clear()
        self._dirty = True

    @staticmethod
    def _memory_path():
        from .config import config_path
        return config_path().with_name("deskmirror_memory.bin")   # 和配置文件放在一起（测试时在临时目录）

    def _sync_memory(self) -> None:
        """按设置打开或关掉本地记忆（关掉只是不再读写；清空要用户点“清空”）。"""
        want = self.cfg.memory.enabled
        if want and self.memory is None:
            self.memory = Memory(self._memory_path())
            n = self.memory.load()
            log.info("译文记忆已打开：%d 条", n)
        elif not want and self.memory is not None:
            self._wait_memory_save()
            try:
                self.memory.save()
            except OSError:
                pass
            self.memory = None

    def _wait_memory_save(self) -> None:
        t = self._mem_thread
        if t is not None and t.is_alive():
            t.join(5.0)

    def _maybe_save_memory(self, now: float) -> None:
        """每分钟最多存一次：在引擎线程里复制一份，加密写盘放到后台线程，不卡跟随。"""
        mem = self.memory
        if mem is None or not mem.dirty or self._mem_saving or now - mem.last_save < 60:
            return
        self._mem_saving = True
        mem.last_save = now
        snap = Memory(mem.path, mem.limit)
        snap._d = {lang: collections.OrderedDict(d) for lang, d in mem._d.items()}
        snap.dirty = True
        mem.dirty = False

        def work():
            try:
                snap.save()
            except OSError:
                log.warning("译文记忆保存失败")
                mem.dirty = True
            finally:
                self._mem_saving = False
        self._mem_thread = threading.Thread(target=work, name="memory-save", daemon=True)
        self._mem_thread.start()

    def _replace_llm(self, cfg: AppConfig) -> None:
        old = self.pool
        self.cfg = cfg
        self._sync_memory()
        self.pool = TranslatorPool(cfg.llm, lambda ev: self.inbox.put(("tr", ev)))
        if old is not None:
            threading.Thread(target=old.close, daemon=True).start()
        self.inflight.clear()
        self.service.update(state="idle", message="", fails=0, until=0.0, paused=False)
        for b in self.blocks.values():
            if b.state in ("translating", "failed"):
                b.state = "pending"
                b.attempts = 0
        self._dirty = True

    def set_languages(self) -> None:
        """用户改了原文语言或译成的语言（配置已经改好）：立即生效。"""
        self.inbox.put(("langs",))

    def _apply_languages(self) -> None:
        """译成的语言变了：已有译文全部作废、重新翻译。原文换成或换出韩文：换识别模型，屏幕上的字全部重新识别。"""
        src, dst = self.cfg.source_lang, self.cfg.target_lang
        old_src, old_dst = self._langs
        self._langs = (src, dst)
        log.info("语言：%s → %s", src, dst)
        self._metric("langs", source=src, target=dst)
        if dst != old_dst:
            self._reset_translations()
        if ocr_lang_for(src) != ocr_lang_for(old_src):
            self._restart_ocr()
        self._dirty = True

    def _reset_translations(self) -> None:
        """换了译成的语言：旧语言的译文（缓存、模板、参考、改过的译文）都不能再用；在途的结果回来也不要。"""
        self.cache.clear()
        self.dialog.clear()
        self.templates.clear()
        self.refs = RefHistory()
        self.overrides.clear()
        self.retry_single.clear()
        self.inflight.clear()
        dst = self.cfg.target_lang
        for b in self.blocks.values():
            need = textutil.needs_translation(b.text, dst) and not textutil.looks_like_code(b.text)
            b.state = "pending" if need else "skip"
            b.translation = ""
            b.attempts = 0
            b.version += 1

    def _restart_ocr(self) -> None:
        """换识别模型：旧模型认出来的块都作废（比如韩文被默认模型认成乱码），整块屏幕重新识别；译文缓存保留。"""
        if self.ocr is not None:
            self.ocr.close()
        self.jobs.clear()
        self.ocr_busy = None
        for b in list(self.blocks.values()):
            self._delete_block(b, "ocr_lang")
        past = time.perf_counter() - 10.0
        for m in self.mons:
            self._mark_needs(m, m.rect, when=past)
        self._start_ocr()

    def _set_working(self, on: bool) -> None:
        if on == self.working:
            return
        self.working = on
        log.info("继续工作" if on else "已暂停")
        self._metric("working", on=on)
        if on:
            # 暂停期间画面可能全变了：所有段落先当作没核对过，重新核对对得上的才显示（没变的很快就回来）；
            # 魔镜里再像点 ⟳ 一样刷新一遍。译文缓存都在，同样的文字不会再请求翻译。
            self.episodes.clear()
            self._vel_shown = set()
            for b in self.blocks.values():
                b.ok_rect = None
            for mr in self._mirrors:
                self._refresh(mr)
        self._dirty = True

    def _refresh(self, rect: Rect) -> None:
        """刷新镜框内区域：重新核对、重新识别，失败的翻译重试；不动其他区域的缓存。"""
        past = time.perf_counter() - 10.0
        for m in self.mons:
            r = geom.inter(rect, m.rect)
            if not geom.empty(r):
                self._mark_needs(m, r, when=past)
        for b in self._blocks_in(rect):
            b.ok_rect = None
            if b.state == "failed":
                b.state = "pending"
                b.attempts = 0
        if self.service["paused"] or self.service["until"] > time.perf_counter():
            self.service.update(paused=False, until=0.0)
        self._metric("refresh", rect=rect)
        self._dirty = True

    # ------------------------------------------------------------------ 滚轮预测
    def _wheel_key(self, hwnd: int) -> str:
        k = self._win_class.get(hwnd)
        if k is None:
            k = self._win_class[hwnd] = winapi.window_class(hwnd) or "?"
        return k

    def _on_wheel(self, t: float, x: int, y: int, notches: float, horiz: bool, ctrl: bool, shift: bool) -> None:
        """滚轮：找到光标下、方向一致的最深滚动画布，记进这次滚动过程。Ctrl+滚轮多是缩放，不管。"""
        if ctrl:
            return
        axis = "h" if (horiz or shift) else "v"
        wc = self._window_at(x, y)
        if wc is self.desktop:
            return
        target, best = None, -1
        stack = [(ch, 1) for ch in wc.children]
        while stack:
            c, d = stack.pop()
            if not c.alive or not geom.contains_pt(c.screen_clip(), x, y):
                continue
            if c.kind == "scroll" and c.axis == axis and d > best:
                target, best = c, d
            stack.extend((ch, d + 1) for ch in c.children)
        if target is None:
            return
        key = f"{self._wheel_key(wc.hwnd)}:{axis}"
        model = self.wheel_models.setdefault(key, CurveModel())
        ep = self.episodes.get(target.cid)
        if ep is None:
            ep = self.episodes[target.cid] = Episode(target.cid, key, axis, model.ready(t))
            ep.canvas = target
        # 水平滚轮的正方向是向右，与竖直滚轮相反；统一成“内容移动方向”的符号
        ep.wheels.append((t, -notches if horiz else notches))
        ep.last = max(ep.last, t)
        self._dirty = True

    def _update_episodes(self, now: float) -> None:
        for cid, ep in list(self.episodes.items()):
            if now - ep.last <= EPISODE_GAP:
                continue
            del self.episodes[cid]
            model = self.wheel_models.get(ep.key)
            if model is None:
                continue
            info = learn(model, ep)
            if model.n_scale >= 3 and model.err > 0.35:
                model.paused_until = now + 30.0  # 预测总是不准：暂停一会儿，回到纯视觉
                model.err = 0.0
                info["paused"] = True
            self._metric("wheel_episode", key=ep.key, **info)

    VEL_STOP = 0.035       # 秒：这么久没有新的位移就当停了
    VEL_MAX_PX = 160

    def _velocity_ahead(self, c: Canvas, now: float, horizon: float) -> float:
        """按最近两帧的速度和加减速，估计再过 horizon 秒内容还会移动多少像素（带符号）。

        只在最近两帧同方向都在动时外推（一次性的跳转不外推）；正在减速时最多推到预计停下的位置，
        避免平滑滚动收尾时译文冲过头。"""
        mo = c.motion
        if len(mo) < 2 or now - mo[-1][0] > self.VEL_STOP:
            return 0.0
        (t0, s0, d0), (t1, s1, d1) = mo[-2], mo[-1]
        if s0 == 0 or s1 == 0 or (s0 > 0) != (s1 > 0) or t1 - t0 > 0.06:
            return 0.0
        v0, v1 = s0 / d0, s1 / d1
        a = (v1 - v0) / max(0.004, (d0 + d1) / 2)
        if a * v1 < 0:                       # 减速：到停下为止
            t_stop = -v1 / a
            h = min(horizon, t_stop)
            x = v1 * h + 0.5 * a * h * h
        else:                                # 匀速或加速：加速部分打折，免得噪声放大
            x = v1 * horizon + 0.25 * a * horizon * horizon
            x = min(abs(x), 1.5 * abs(v1) * horizon) * (1 if v1 > 0 else -1)
        return max(-self.VEL_MAX_PX, min(self.VEL_MAX_PX, x))

    def _velocity_extras(self, now: float) -> dict[int, tuple[int, int]]:
        """没有滚轮曲线可用时（键盘、拖滚动条、触控板、还没学到曲线的滚轮），按最近的滚动速度把译文
        提前放到“显示出来那一刻”原文应在的位置：滚动途中跟得更紧；一停下就撤回（见 _velocity_stale）。"""
        out: dict[int, tuple[int, int]] = {}
        shown: set[int] = set()
        lead = self.cfg.track.display_lead_ms / 1000
        for wc in self.win_canvas.values():
            for c in wc.descendants():
                if c.kind != "scroll" or not c.alive or not c.motion:
                    continue
                horizon = (now - c.motion[-1][0]) + lead     # 依据的那一帧到“显示出来”还要多久
                extra = self._velocity_ahead(c, now, horizon)
                if abs(extra) >= 1:
                    e = int(round(extra))
                    out[c.cid] = (0, e) if c.axis == "v" else (e, 0)
                    shown.add(c.cid)
        self._vel_shown = shown
        return out

    def _velocity_stale(self, now: float) -> bool:
        for wc in self.win_canvas.values():
            for c in wc.descendants():
                if c.cid in self._vel_shown and (not c.motion or now - c.motion[-1][0] > self.VEL_STOP):
                    return True
        return False

    def _prediction_extras(self, now: float) -> dict[int, tuple[int, int]]:
        extras: dict[int, tuple[int, int]] = {}
        lead = self.cfg.track.display_lead_ms / 1000
        for cid, ep in self.episodes.items():
            if not ep.predicting or not ep.wheels:
                continue
            canvas = getattr(ep, "canvas", None)
            model = self.wheel_models.get(ep.key)
            if canvas is None or not canvas.alive or model is None or not model.ready(now):
                continue
            m = self._monitor_for(canvas.screen_clip())
            f = m.last_ft if m is not None and m.last_ft else self._cur_frame_t
            p_f = model.displacement(ep.wheels, f)
            actual = ep.actual_until(f)
            # 像素实测和预测明显不符（滚到底、软件没滚、曲线变了）：这次过程不再预测
            if f - ep.wheels[0][0] > 0.06 and abs(actual - p_f) > max(12.0, 0.5 * abs(p_f)):
                ep.predicting = False
                continue
            extra = max(-250.0, min(250.0, model.displacement(ep.wheels, now + lead) - p_f))
            if abs(extra) >= 0.5:
                e = int(round(extra))
                extras[cid] = (0, e) if ep.axis == "v" else (e, 0)
        return extras

    # ------------------------------------------------------------------ 快照
    def _publish(self, force: bool = False) -> None:
        now = time.perf_counter()
        if not force and (not self._dirty or now - self._last_publish < 1 / 90):
            return
        self._dirty = False
        self._last_publish = now
        items: list[DrawItem] = []
        pending: list = []
        canvases: list = []
        groups: list[tuple[Canvas, list[Rect]]] = []
        for hwnd in self.z_order:
            c = self.win_canvas.get(hwnd)
            if c is not None:
                groups.append((c, self.visible.get(hwnd, [])))
        groups.append((self.desktop, self.desktop_visible))
        counts: collections.Counter = collections.Counter()
        extras = self._prediction_extras(now) if self.episodes else {}
        for cid, e in self._velocity_extras(now).items():
            extras.setdefault(cid, e)   # 有滚轮曲线预测的画布以滚轮为准
        for root, vis in groups:
            if not vis:
                continue
            stack = [(root, 0, 0)]
            while stack:
                c, ex, ey = stack.pop()
                pe = extras.get(c.cid)
                if pe is not None:
                    ex, ey = ex + pe[0], ey + pe[1]
                # 桌面画布的子节点是各个窗口，它们已经单独按 Z 序处理过
                stack.extend((ch, ex, ey) for ch in c.children if ch.alive and ch.kind != "window")
                clip = c.screen_clip()
                if c.kind == "scroll":
                    canvases.append((c.cid, clip, c.axis))
                if not c.blocks:
                    continue
                clips = tuple(geom.clip_list(vis, clip))
                if not clips:
                    continue
                ox, oy = c.screen_offset()
                for b in c.blocks.values():
                    counts[b.state] += 1
                    r = b.rect
                    sr = (r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)
                    if b.state == "skip":
                        continue
                    if b.ok_rect != sr:
                        if not (b.held_until > now and b.hold_rect == sr):
                            continue
                    if ex or ey:
                        # 滚轮预测：内容正在动，按学到的曲线把译文提前放到“显示出来那一刻”的位置
                        sr = (sr[0] + ex, sr[1] + ey, sr[2] + ex, sr[3] + ey)
                    if b.state == "done" and b.translation:
                        room = (sr[0], sr[1], sr[2] + b.extra_w, max(r[3], b.room_bottom) + oy + ey)
                        items.append(DrawItem(b.bid, b.version, sr, room, clips, b.translation, b.bg, b.fg,
                                              b.line_h, len(b.lines), b.em, b.ref, b.text,
                                              stretch=sr[2] + b.extra_max if b.extra_max else 0))
                    elif any(geom.overlaps(c, sr) for c in clips):
                        # 只报露出来的：被别的窗口整块挡住的不算“在翻译”（范围外的窗口永远不会翻译）
                        pending.append((sr, clips, b.state == "failed"))
        svc = self.service
        status = {
            "ocr": self.ocr_state if self.ocr_busy is None else "busy",
            "ocr_device": self.ocr.device if self.ocr else "",
            "service": svc["state"], "service_msg": svc["message"], "paused": svc["paused"],
            "slow": svc["slow"], "requests": svc["requests"], "inflight": len(self.inflight), "working": self.working,
            "blocks": len(self.blocks), "done": counts["done"],
            "pending": counts["pending"] + counts["translating"], "failed": counts["failed"],
            "canvases": tuple(canvases), "error": self.error,
            "needs": int(sum(int((m.needs > 0).sum()) for m in self.mons if m.needs is not None)),
            "scrolls": int(self.metrics["scrolls"]), "cache_hits": int(self.metrics["cache_hits"]),
            "monitors": [m.info.device for m in self.mons],
            "sent_chars": svc.get("chars", 0),
            "memory_count": self.memory.count() if self.memory is not None else None,
            "excluded_in_mirror": any(geom.overlaps(v, mr) for mr in self._mirrors
                                      for hwnd in self._excluded for v in self.visible.get(hwnd, ())),
        }
        if self._geo_frame_t or extras:
            # 从“屏幕上内容动了的那一帧”到“新位置交给界面”的耗时
            t_pub = time.perf_counter()
            focus = self._focus_monitor()
            base = focus.last_ft if focus is not None and focus.last_ft else self._cur_frame_t
            if self._geo_frame_t:
                lat = (t_pub - self._geo_frame_t) * 1000
                self.metrics["pub_n"] += 1
                self.metrics["pub_lat_ms_sum"] += lat
                self.metrics["pub_lat_ms_max"] = max(self.metrics["pub_lat_ms_max"], lat)
            self._metric("pub", lat_ms=round((t_pub - base) * 1000, 2), items=len(items),
                         ft=round(base - self.started, 4),
                         preds={str(k): (v[1] if v[0] == 0 else v[0]) for k, v in extras.items()})
            self._geo_frame_t = 0.0
        self._publish_cb(Snapshot(tuple(items), tuple(pending), status, now))
