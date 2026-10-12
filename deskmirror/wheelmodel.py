"""滚轮曲线学习与预测（本地拟合，不用 LLM）。

每次滚轮之后，像素识别会逐帧量出这块画布实际移动了多少（带帧时间）。一次“滚动过程”
（相邻滚轮间隔不超过 0.35 秒）结束时：
- 总位移 / 总格数 → 这个软件“每格多少像素”（最近几次的中位数，按窗口类名分别学；软件每格滚的距离是定数，
  个别次数算偏了——比如滚动区域刚认出来、第一格没算进去——不会把它带偏）；
- 只滚了一格的过程 → 归一化的累计位移随时间的曲线（反应延迟 + 平滑动画的形状）。

预测：滚轮一来，按曲线算出“译文画到屏幕上那一刻”内容会在哪里，提前移动译文；
多格叠加近似处理。像素核对与预测明显不符（滚到底、软件不滚、曲线变了）就停止这次预测，
最近几次误差都大则暂停这个模型一段时间，回到纯视觉。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

GRID_MS = 4
HORIZON_MS = 700
GRID = np.arange(0, HORIZON_MS + GRID_MS, GRID_MS, dtype=np.float64)
EPISODE_GAP = 0.35          # 秒：滚轮/位移都停了这么久，一次滚动过程结束


@dataclass
class CurveModel:
    px_per_notch: float = 0.0           # 带符号：滚轮向上一格内容移动的像素（通常为正）
    n_scale: int = 0
    curve: np.ndarray = field(default_factory=lambda: np.zeros(GRID.size))
    n_curve: int = 0
    err: float = 0.0                    # 最近几次预测的相对误差（指数平均）
    paused_until: float = 0.0
    ratios: list = field(default_factory=list)   # 最近几次滚动过程量到的“每格像素”（取中位数）

    def ready(self, now: float) -> bool:
        return self.n_scale >= 2 and self.n_curve >= 2 and now >= self.paused_until and abs(self.px_per_notch) >= 2

    def frac(self, dt_ms: float) -> float:
        if dt_ms <= 0:
            return 0.0
        if dt_ms >= HORIZON_MS:
            return float(self.curve[-1]) if self.n_curve else 1.0
        return float(np.interp(dt_ms, GRID, self.curve))

    def displacement(self, wheels: list[tuple[float, float]], t: float) -> float:
        """到时刻 t 为止，这些滚轮（时间, 格数）累计带来的内容位移（像素，带符号）。"""
        return sum(self.px_per_notch * n * self.frac((t - tw) * 1000) for tw, n in wheels)

    def remaining(self, wheels: list[tuple[float, float]], f: float, actual: float):
        """在时刻 f 量到这次滚动已经走了 actual 像素：之后每个时刻还会再走多少（函数）。

        曲线是一格一格叠加的近似；软件连着收到几格时会重新瞄准终点，实际快慢和叠加的不一样。终点却是定的
        （格数 × 每格像素）：剩下的路按曲线的形状走，但拉伸到正好落在终点上——量到的比曲线慢，后面就走快些。"""
        p_f = self.displacement(wheels, f)
        end = max(tw for tw, _n in wheels) + HORIZON_MS / 1000
        rest = self.displacement(wheels, end) - p_f
        k = 1.0
        if abs(rest) >= 2:
            k = max(0.5, min(2.0, (self.displacement(wheels, end) - actual) / rest))
        return lambda t: (self.displacement(wheels, t) - p_f) * k


@dataclass
class Episode:
    cid: int
    key: str
    axis: str
    model_ready: bool
    wheels: list[tuple[float, float]] = field(default_factory=list)   # (时间, 格数)
    shifts: list[tuple[float, int]] = field(default_factory=list)     # (帧时间, 位移)
    last: float = 0.0
    predicting: bool = True
    canvas: object = None             # 对应的滚动画布（引擎里的 Canvas）

    def actual_until(self, t: float) -> float:
        return float(sum(s for ft, s in self.shifts if ft <= t))


def learn(model: CurveModel, ep: Episode) -> dict:
    """一次滚动过程结束后更新模型，返回本次的统计（给日志用）。"""
    n = sum(w for _t, w in ep.wheels)
    d = float(sum(s for _ft, s in ep.shifts))
    info = {"notches": n, "disp": d, "wheels": len(ep.wheels), "frames": len(ep.shifts)}
    if abs(n) < 0.5 or d == 0:
        return info
    # 预测误差：这次过程开始时模型已经可用，就看逐帧预测和实测差多少
    if ep.model_ready and ep.shifts:
        errs = [abs(model.displacement(ep.wheels, ft) - ep.actual_until(ft)) for ft, _s in ep.shifts]
        rel = float(np.mean(errs)) / max(8.0, abs(d))
        model.err = rel if model.err == 0 else 0.7 * model.err + 0.3 * rel
        info["pred_rel_err"] = round(rel, 3)
    ratio = d / n
    if model.n_scale >= 2 and (np.sign(ratio) != np.sign(model.px_per_notch) or abs(ratio) < 0.6 * abs(model.px_per_notch)):
        info["skipped"] = "clamped_or_inconsistent"  # 多半滚到了尽头，不拿来更新每格像素
        return info
    if not model.ratios and model.n_scale:
        model.ratios = [model.px_per_notch] * 3      # 以前存的只有平均值：当作三次（一次算偏的压不过它）
    model.ratios = (model.ratios + [float(ratio)])[-7:]
    model.px_per_notch = float(np.median(model.ratios))
    model.n_scale += 1
    if len(ep.wheels) == 1 and abs(d) >= 4 and len(ep.shifts) >= 2:
        tw = ep.wheels[0][0]
        times = np.array([(ft - tw) * 1000 for ft, _s in ep.shifts])
        cum = np.cumsum([s for _ft, s in ep.shifts]) / d
        # 位移在帧时间处是阶梯；曲线取阶梯的线性插值，帧前补 0
        xs = np.concatenate([[0.0], times])
        ys = np.concatenate([[0.0], cum])
        order = np.argsort(xs)
        c = np.interp(GRID, xs[order], ys[order], left=0.0, right=float(ys[order][-1]))
        model.curve = c if model.n_curve == 0 else 0.6 * model.curve + 0.4 * c
        model.n_curve += 1
    info["px_per_notch"] = round(model.px_per_notch, 2)
    info["n_curve"] = model.n_curve
    return info


def save_models(path, models: dict[str, CurveModel]) -> None:
    """学到的每格像素和曲线存盘（按窗口类名，只有数字），下次启动直接可用。"""
    import json
    data = {k: {"px_per_notch": round(m.px_per_notch, 3), "n_scale": m.n_scale, "n_curve": m.n_curve,
                "err": round(m.err, 4), "curve": [round(float(v), 4) for v in m.curve],
                "ratios": [round(float(v), 3) for v in m.ratios]}
            for k, m in models.items() if m.n_scale or m.n_curve}
    if data:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)


def load_models(path) -> dict[str, CurveModel]:
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, CurveModel] = {}
    for k, d in data.items() if isinstance(data, dict) else ():
        try:
            curve = np.array(d["curve"], dtype=np.float64)
            if curve.size != GRID.size:
                continue
            out[k] = CurveModel(float(d["px_per_notch"]), int(d["n_scale"]), curve, int(d["n_curve"]),
                                float(d.get("err", 0.0)), ratios=[float(v) for v in d.get("ratios", [])][-7:])
        except (KeyError, TypeError, ValueError):
            continue
    return out

