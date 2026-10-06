"""矩形工具。矩形一律用 (left, top, right, bottom)，右边和下边不含。"""
from __future__ import annotations

Rect = tuple[int, int, int, int]


def area(r: Rect) -> int:
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def empty(r: Rect) -> bool:
    return r[2] <= r[0] or r[3] <= r[1]


def inter(a: Rect, b: Rect) -> Rect:
    return max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])


def overlaps(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def union(a: Rect, b: Rect) -> Rect:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def contains(outer: Rect, inner: Rect) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def contains_pt(r: Rect, x: float, y: float) -> bool:
    return r[0] <= x < r[2] and r[1] <= y < r[3]


def shift(r: Rect, dx: int, dy: int) -> Rect:
    return r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy


def expand(r: Rect, m: int) -> Rect:
    return r[0] - m, r[1] - m, r[2] + m, r[3] + m


def center(r: Rect) -> tuple[float, float]:
    return (r[0] + r[2]) / 2, (r[1] + r[3]) / 2


def subtract(r: Rect, cut: Rect) -> list[Rect]:
    """r 去掉 cut 后剩下的部分（最多四块）。"""
    if not overlaps(r, cut):
        return [r]
    out = []
    l, t, rr, b = r
    cl, ct, cr, cb = inter(r, cut)
    if t < ct:
        out.append((l, t, rr, ct))
    if cb < b:
        out.append((l, cb, rr, b))
    if l < cl:
        out.append((l, ct, cl, cb))
    if cr < rr:
        out.append((cr, ct, rr, cb))
    return out


def subtract_all(rects: list[Rect], cut: Rect) -> list[Rect]:
    out: list[Rect] = []
    for r in rects:
        out.extend(subtract(r, cut))
    return out


def clip_list(rects: list[Rect], clip: Rect) -> list[Rect]:
    out = []
    for r in rects:
        c = inter(r, clip)
        if not empty(c):
            out.append(c)
    return out


def ring_distance(r: Rect, focus: Rect) -> float:
    """矩形到焦点矩形的切比雪夫距离：0 表示相交；用于以魔镜为中心按圈排序。"""
    dx = max(focus[0] - r[2], r[0] - focus[2], 0)
    dy = max(focus[1] - r[3], r[1] - focus[3], 0)
    return float(max(dx, dy))
