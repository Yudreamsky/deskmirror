"""本地文字识别子进程。

识别放在独立进程：RapidOCR 的前后处理有不少 Python 代码，放在主进程会抢 GIL，
拖慢魔镜拖动和滚动跟随；显卡运行库出问题也不会带崩界面。

一个任务 = 一块屏幕区域。子进程先检测整块区域里的所有文字行，按几何关系分成候选段落，
再按“离魔镜由近到远”的顺序分批识别，每识别完一批就把完整的文字块发回主进程。
"""
from __future__ import annotations

import logging
import math
import multiprocessing as mp
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field

import numpy as np

from .geom import Rect, ring_distance

log = logging.getLogger(__name__)


@dataclass
class OcrJob:
    job_id: int
    image: np.ndarray            # BGR，区域截图
    origin: tuple[int, int]      # 区域左上角的虚拟桌面坐标
    focus: Rect                  # 提交时魔镜的位置，用来排识别顺序
    ring_px: int = 240
    meta: dict = field(default_factory=dict)


@dataclass
class OcrLineOut:
    rect: Rect                   # 虚拟桌面坐标
    text: str
    score: float


@dataclass
class OcrBlockOut:
    rect: Rect
    lines: list[OcrLineOut]
    text: str


# --------------------------------------------------------------------- 子进程端

def _make_engine(device: str, threads: int, lang: str = "default"):
    import deskmirror
    if device == "gpu":
        deskmirror.use_directml_runtime()
    import onnxruntime as ort
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    params = {
        "Global.use_cls": False,
        "Global.log_level": "error",
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Rec.rec_batch_num": 16 if device == "gpu" else 6,
    }
    if lang == "korean":
        # 检测模型通用；只换识别模型。没有时 RapidOCR 从 ModelScope 下载并按 SHA256 校验
        params.update({"Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5,
                       "Rec.model_type": ModelType.MOBILE})
    engine = RapidOCR(params=params)
    actual = "cpu"
    if device == "gpu" and "DmlExecutionProvider" in ort.get_available_providers():
        try:
            for task in (engine.text_det, engine.text_rec):
                wrapper = task.session
                prev = wrapper.session
                path = getattr(prev, "_model_path", None)
                opts = prev.get_session_options()
                opts.enable_mem_pattern = False  # DirectML 要求
                opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                sess = ort.InferenceSession(path, sess_options=opts,
                                            providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                                            provider_options=[{"device_id": "0"}, {}])
                if sess.get_providers()[0] != "DmlExecutionProvider":
                    raise RuntimeError("DirectML 会话退回了 CPU")
                wrapper.session = sess
            actual = "gpu"
        except Exception:  # noqa: BLE001
            engine = RapidOCR(params=params)
            actual = "cpu"
    return engine, actual


def _detect(engine, img: np.ndarray) -> list[Rect]:
    """原分辨率检测（RapidOCR 默认会把 4K 截图缩到 2000 像素，小字会漏）。"""
    det = engine.text_det
    h, w = img.shape[:2]
    ph, pw = -(-h // 32) * 32, -(-w // 32) * 32
    if (ph, pw) != (h, w):
        pad = np.empty((ph, pw, 3), np.uint8)
        pad[:h, :w] = img
        pad[h:, :] = img[h - 1:h, :].mean(axis=(0, 1)) if h else 0
        pad[:h, w:] = img[:, w - 1:w] if w else 0
        img = pad
    x = (img.astype(np.float32) * (1 / 127.5) - 1.0).transpose(2, 0, 1)[None]
    preds = det.session(x)
    boxes, _scores = det.postprocess_op(preds, (ph, pw))
    out: list[Rect] = []
    for box in boxes:
        x0, y0 = float(box[:, 0].min()), float(box[:, 1].min())
        x1, y1 = float(box[:, 0].max()), float(box[:, 1].max())
        x0, y0 = max(0, int(math.floor(x0))), max(0, int(math.floor(y0)))
        x1, y1 = min(w, int(math.ceil(x1))), min(h, int(math.ceil(y1)))
        if x1 - x0 >= 4 and y1 - y0 >= 6:
            out.append((x0, y0, x1, y1))
    return out


def _recognize(engine, img: np.ndarray, rects: list[Rect]) -> list[tuple[str, float]]:
    from rapidocr.ch_ppocr_rec import TextRecInput

    crops = []
    h, w = img.shape[:2]
    for x0, y0, x1, y1 in rects:
        crops.append(np.ascontiguousarray(img[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]))
    res = engine.text_rec(TextRecInput(img=crops))
    return [(t or "", float(s)) for t, s in zip(res.txts or [], res.scores or [])]


def _priority(rect: Rect, focus: Rect, ring_px: int) -> tuple[int, float]:
    """以魔镜为中心的螺旋顺序：先镜内，再一圈圈往外；同一圈按角度顺时针。"""
    d = ring_distance(rect, focus)
    ring = 0 if d <= 0 else 1 + int(d // ring_px)
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    fx, fy = (focus[0] + focus[2]) / 2, (focus[1] + focus[3]) / 2
    ang = math.atan2(cx - fx, -(cy - fy)) % (2 * math.pi)
    return ring, ang


def _process(engine, job: OcrJob, out_q) -> None:
    from .layout import Line, candidate_paragraphs, join_lines, split_by_text

    t0 = time.perf_counter()
    img = job.image
    ox, oy = job.origin
    rects = _detect(engine, img)
    t_det = time.perf_counter() - t0
    paras = candidate_paragraphs(rects)
    para_rects = []
    for idx in paras:
        r = rects[idx[0]]
        for i in idx[1:]:
            q = rects[i]
            r = (min(r[0], q[0]), min(r[1], q[1]), max(r[2], q[2]), max(r[3], q[3]))
        para_rects.append(r)
    focus = (job.focus[0] - ox, job.focus[1] - oy, job.focus[2] - ox, job.focus[3] - oy)
    order = sorted(range(len(paras)), key=lambda k: _priority(para_rects[k], focus, job.ring_px))
    # 按段落分批识别：一批约 48 行；每批完成后立即把这些段落的文字块发回去。
    batch: list[int] = []
    n_lines = 0
    n_blocks = 0

    def flush() -> None:
        nonlocal batch, n_lines, n_blocks
        if not batch:
            return
        line_rects = [rects[i] for k in batch for i in paras[k]]
        texts = _recognize(engine, img, line_rects)
        pos = 0
        blocks: list[OcrBlockOut] = []
        for k in batch:
            lines = []
            for i in paras[k]:
                text, score = texts[pos]
                pos += 1
                letters = sum(1 for c in text if c.isalnum())
                # 很短的结果多半是图标、图片纹理被认成了字：要求更高的置信度
                need = 0.88 if letters <= 3 else 0.6
                if score >= need and text.strip():
                    lines.append(Line(rects[i], text, score))
            for draft in split_by_text(lines):
                out_lines = [OcrLineOut((ln.rect[0] + ox, ln.rect[1] + oy, ln.rect[2] + ox, ln.rect[3] + oy),
                                        ln.text, ln.score) for ln in draft.lines]
                r = draft.rect
                blocks.append(OcrBlockOut((r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy), out_lines,
                                          join_lines(draft.lines)))
        n_blocks += len(blocks)
        n_lines += len(line_rects)
        out_q.put(("blocks", job.job_id, blocks))
        batch = []

    count = 0
    for k in order:
        batch.append(k)
        count += len(paras[k])
        if count >= 48:
            flush()
            count = 0
    flush()
    out_q.put(("done", job.job_id, {"det_s": t_det, "total_s": time.perf_counter() - t0, "lines": n_lines,
                                     "blocks": n_blocks, "size": img.shape[:2]}))


def worker_main(in_q, out_q, device: str, threads: int, lang: str = "default") -> None:
    try:
        try:
            engine, actual = _make_engine(device, threads, lang)
            used = lang
        except Exception:  # noqa: BLE001
            if lang == "default":
                raise
            # 换语言失败（比如第一次用时下载不了模型）：先用默认模型，状态里说明
            out_q.put(("error", 0, traceback.format_exc(limit=3)))
            engine, actual = _make_engine(device, threads)
            used = "default"
        out_q.put(("ready", 0, {"device": actual, "lang": used, "wanted": lang}))
    except Exception:  # noqa: BLE001
        out_q.put(("fatal", 0, traceback.format_exc(limit=3)))
        return
    while True:
        job = in_q.get()
        if job is None:
            break
        try:
            _process(engine, job, out_q)
        except Exception:  # noqa: BLE001
            out_q.put(("error", job.job_id, traceback.format_exc(limit=3)))
            out_q.put(("done", job.job_id, {}))


# --------------------------------------------------------------------- 主进程端

class OcrClient:
    """管理识别子进程；结果用回调交给调用方（在内部读取线程里调用）。"""

    def __init__(self, device: str, threads: int, on_message, lang: str = "default") -> None:
        ctx = mp.get_context("spawn")
        self._in = ctx.Queue()
        self._out = ctx.Queue()
        self._proc = ctx.Process(target=worker_main, args=(self._in, self._out, device, threads, lang), daemon=True,
                                 name="deskmirror-ocr")
        self._on_message = on_message
        self._stop = threading.Event()
        self.device = "starting"
        self._proc.start()
        self._reader = threading.Thread(target=self._read, name="ocr-reader", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._out.get(timeout=0.2)
            except queue.Empty:
                if not self._proc.is_alive() and not self._stop.is_set():
                    self._on_message(("fatal", 0, "识别进程意外退出"))
                    return
                continue
            except (EOFError, OSError):
                return
            if msg[0] == "ready":
                self.device = msg[2]["device"]
            self._on_message(msg)

    def submit(self, job: OcrJob) -> None:
        self._in.put(job)

    def alive(self) -> bool:
        return self._proc.is_alive()

    def close(self, timeout: float = 3.0) -> None:
        self._stop.set()
        try:
            self._in.put(None)
        except (OSError, ValueError):
            pass
        self._proc.join(timeout)
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(1.0)
        for q in (self._in, self._out):
            try:
                q.cancel_join_thread()
                q.close()
            except (OSError, ValueError):
                pass
