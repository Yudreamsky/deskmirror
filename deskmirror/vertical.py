"""竖排文字（漫画气泡、竖排的书）：横排的识别模型认不了竖着的一列字。

做法：把一列字按字与字之间的空白切成单字，从左到右排成一行再交给识别模型。
竖排里写成一整条竖线的长音（ー）、破折号（—）转成横的放进去；模型常把它认成“一”“-”，
而切字时已经知道哪些是竖线：认出来的像横线的字正好和竖线一样多，就按顺序换成长音或破折号，
对不上时在竖线处把这一列分成几段分别识别再接起来。几列连成一段时从右往左读。
"""
from __future__ import annotations

import cv2
import numpy as np

from .geom import Rect

# 识别结果里可能是竖线（长音、破折号）认出来的字
_BARLIKE = set("一-_—ー－‐−~～|｜")


def is_column(r: Rect) -> bool:
    """细高的检测框：竖排的一列字。"""
    w, h = r[2] - r[0], r[3] - r[1]
    return w >= 12 and h >= 1.8 * w


def join_columns(rects: list[Rect]) -> list[Rect]:
    """同一列被检测成上下几截（比如句末的“！”单独一个框）：左右重叠、上下挨着的接成一列。"""
    cols = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                a, b = cols[i], cols[j]
                wa, wb = a[2] - a[0], b[2] - b[0]
                overlap = min(a[2], b[2]) - max(a[0], b[0])
                gap = max(a[1], b[1]) - min(a[3], b[3])
                if overlap >= 0.6 * min(wa, wb) and gap < 0.5 * max(wa, wb):
                    cols[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del cols[j]
                    changed = True
                    break
            if changed:
                break
    return [(c[0], c[1], c[2], c[3]) for c in cols]


def group_columns(cols: list[Rect]) -> list[list[Rect]]:
    """几列连成一段（一个气泡里的话）：左右挨着、上下有重叠的列，按从右往左的顺序。"""
    groups: list[list[Rect]] = []
    for r in sorted(cols, key=lambda c: -c[2]):
        for g in groups:
            last = g[-1]
            overlap = min(last[3], r[3]) - max(last[1], r[1])
            if last[0] - r[2] < 0.8 * (last[2] - last[0]) and overlap > 0.3 * min(last[3] - last[1], r[3] - r[1]):
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


def _runs(on: np.ndarray) -> list[list[int]]:
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append([start, i])
            start = None
    if start is not None:
        out.append([start, len(on)])
    return out


def _beyond(line: np.ndarray, far: bool, upright: bool) -> np.ndarray:
    """气泡边框的一笔连同它外侧的整片：横的弧线外侧是它下面（far）或上面，竖的弧线外侧是它右边（far）或左边。"""
    h, w = line.shape
    ys, xs = np.nonzero(line)
    if upright:
        ys, xs, h, w = xs, ys, w, h                  # 竖的按行看：每行从弧线往外
    if far:
        edge = np.full(w, h)
        np.minimum.at(edge, xs, ys)
        out = np.arange(h)[:, None] >= edge[None, :]
    else:
        edge = np.full(w, -1)
        np.maximum.at(edge, xs, ys)
        out = np.arange(h)[:, None] <= edge[None, :]
    return out.T if upright else out


def column_cells(crop: np.ndarray) -> tuple[list[np.ndarray], list[bool], int, list[Rect]]:
    """一列字的截图（BGR）→ 单字方格、每格是不是一整条竖线（已转成横的）、底色、
    每个字的墨迹范围（相对截图；不含框进来的气泡边框，含“！”的点这类小点）。"""
    gray = crop.mean(axis=2)
    h, w = gray.shape
    bg = int(np.median(np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])))
    ink = np.abs(gray - bg) > 60
    # 字离气泡边框近时，检测框常把一段弧形边框框进去：从上下边伸进来、横跨大半列宽（或从角上斜穿过去）、
    # 或者左右横穿整列的细线是边框，连同它外侧（气泡外面的网点纸、背景）整片不要；贴着框边的零星几个像素（碎点）也不要。
    # 按连通的笔画算，和字分开：贴着边框的“！”的点还在。列靠近气泡左右两侧时弧线较陡，按线细不细判断
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    drop = np.zeros_like(ink)
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        thin = bh < 0.3 * w or area < 0.15 * w * max(bw, bh)
        at_tb, at_lr = y == 0 or y + bh == h, x == 0 or x + bw == w
        if thin and ((at_tb and (bw > 0.6 * w or at_lr)) or (x == 0 and bw == w)):
            drop |= _beyond(lab == i, x + bw / 2 > w / 2 if bh > bw else y + bh / 2 > h / 2, bh > bw)
        elif (at_tb or at_lr) and area <= max(2, 0.003 * w * w):
            drop |= lab == i
    if drop.any():
        ink &= ~drop
        crop = crop.copy()                           # 别改动调用方的整张截图
        crop[drop] = bg
    segs = []
    for a, b in _runs(ink.any(axis=1)):
        g = ink[a:b]
        cols = np.flatnonzero(g.any(axis=0))
        bw = cols[-1] - cols[0] + 1 if cols.size else 0
        if g.sum() < 0.01 * w * w:
            continue                                    # 杂点
        if (a == 0 or b == h) and b - a < 0.3 * w and bw > 0.6 * w:
            continue                                    # 贴着上下边的气泡边框碎片（扁、宽）
        segs.append([a, b])
    # 一个字里上下分开的薄的一笔（“！”的点、“う”头上的一横、“二”的横）：并给离它更近的那一段——
    # 同一个字里的空隙比字与字之间小
    changed = True
    while changed:
        changed = False
        for i, (a, b) in enumerate(segs):
            if b - a >= 0.22 * w:
                continue
            best = None
            for j in (i - 1, i + 1):
                if 0 <= j < len(segs):
                    o = segs[j]
                    gap = max(o[0] - b, a - o[1])
                    if gap < 0.3 * w and max(b, o[1]) - min(a, o[0]) <= 1.1 * w and (best is None or gap < best[0]):
                        best = (gap, j)
            if best is not None:
                j = best[1]
                segs[j] = [min(a, segs[j][0]), max(b, segs[j][1])]
                del segs[i]
                changed = True
                break
    cells: list[np.ndarray] = []
    bars: list[bool] = []
    for a, b in segs:
        gi = ink[a:b]
        cols = np.flatnonzero(gi.any(axis=0))
        c0, c1 = (int(cols[0]), int(cols[-1]) + 1) if cols.size else (0, w)
        g = crop[a:b, c0:c1]
        bar = (b - a) > 0.45 * w and (c1 - c0) < 0.28 * w and bool(gi[:, c0:c1].any(axis=1).all())
        if bar:
            g = np.rot90(g, 1)                          # 竖排的长音、破折号：转成横的
        bh, bw = g.shape[:2]
        side = max(w, bh, bw)
        cell = np.full((side, side, 3), bg, np.uint8)
        ox = (side - bw) // 2
        # 小字（小写假名、标点）贴底边，和横排时一样，模型才分得清“ゃ”和“や”；正常大小的字、横线竖直居中
        oy = side - bh - max(1, side // 10) if bh < 0.6 * w and not bar else (side - bh) // 2
        cell[oy:oy + bh, ox:ox + bw] = g
        cells.append(cell)
        bars.append(bar)
    # 每个字的墨迹范围：底板按字盖（一列两头常是窄的“！”“…”，按整列最宽的字画方底板，角会伸到弯进来的气泡边框上）。
    # 挨着的小点也算上：太小、切字时当杂点丢掉的“！”的点、“。”也要被底板盖住
    lo, hi = (segs[0][0] - 0.5 * w, segs[-1][1] + 0.5 * w) if segs else (0, 0)
    spare = [r for r in _runs(ink.any(axis=1))
             if r[1] > lo and r[0] < hi and not any(s[0] <= r[0] and r[1] <= s[1] for s in segs)]
    boxes: list[Rect] = []
    for a, b in sorted(segs + spare):
        xs = np.flatnonzero(ink[a:b].any(axis=0))
        if xs.size:
            boxes.append((int(xs[0]), a, int(xs[-1]) + 1, b))
    return cells, bars, bg, boxes


def row_image(cells: list[np.ndarray], bg: int) -> np.ndarray:
    """方格从左到右拼成一行。"""
    h = max(c.shape[0] for c in cells)
    gap = np.full((h, max(2, h // 8), 3), bg, np.uint8)
    parts = []
    for c in cells:
        if c.shape[0] < h:
            pad = np.full((h, c.shape[1], 3), bg, np.uint8)
            pad[h - c.shape[0]:] = c
            c = pad
        parts += [c, gap]
    return np.concatenate(parts[:-1], axis=1)


def split_at_bars(cells: list[np.ndarray], bars: list[bool]) -> list[list[np.ndarray]]:
    """按竖线把方格分成几段（竖线本身不要）。"""
    runs: list[list[np.ndarray]] = [[]]
    for c, bar in zip(cells, bars):
        if bar:
            runs.append([])
        else:
            runs[-1].append(c)
    return runs


def fill_bars(text: str, n_bars: int) -> str | None:
    """整列识别的结果里像横线的字正好和竖线一样多：按顺序换成长音或破折号；对不上返回 None。"""
    pos = [i for i, ch in enumerate(text) if ch in _BARLIKE]
    if len(pos) != n_bars:
        return None
    ch = bar_char(text)
    out = list(text)
    for i in pos:
        out[i] = ch
    return "".join(out)


def bar_char(text: str) -> str:
    """竖线是什么：有假名就是长音“ー”，没有（中文竖排）就是破折号“—”。"""
    return "ー" if any("ぁ" <= ch <= "ヿ" for ch in text) else "—"
