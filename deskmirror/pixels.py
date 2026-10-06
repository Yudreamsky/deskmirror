"""像素级判断：变化区域、整块平移（滚动）识别、文字块核对。

全部是纯 numpy / OpenCV 运算，不依赖窗口和界面，便于用录下来的真实帧离线测试。

滚动识别的思路：把候选区域按列切成若干竖条，每条每一行算一个精确哈希；当前帧的
某一行在上一帧同一竖条里找到唯一相同的行，就为“内容移动了多少行”投一票。真实滚动时
同一画布内各竖条的票会集中在同一个位移上；固定的标题、侧栏、滚动条不会给这个位移
投票，因此能把实际滚动的范围从同一个窗口里分出来。鼠标滚轮事件不参与判断。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .geom import Rect

TILE = 16
_RNG = np.random.default_rng(20261005)
# float32 精确表示 2^24 以内的整数：竖条最宽 72 像素，255 * 900 * 72 < 2^24，
# 所以矩阵乘法得到的是精确的整数哈希（比 float64 快一倍）。
_WEIGHTS = _RNG.integers(1, 900, size=4096).astype(np.float32)


def to_gray(bgra: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgra, cv2.COLOR_BGRA2GRAY)


def changed_tiles(prev: np.ndarray, cur: np.ndarray, rect: Rect) -> tuple[Rect, np.ndarray]:
    """比较 rect（会对齐到 TILE 网格）内两帧，返回 (对齐后的矩形, 每格是否有像素变化)。"""
    h, w = prev.shape[:2]
    l = max(0, rect[0] // TILE * TILE)
    t = max(0, rect[1] // TILE * TILE)
    r = min(w, -(-rect[2] // TILE) * TILE)
    b = min(h, -(-rect[3] // TILE) * TILE)
    if r <= l or b <= t:
        return (l, t, l, t), np.zeros((0, 0), bool)
    return (l, t, r, b), _tile_any(cv2.absdiff(prev[t:b, l:r], cur[t:b, l:r]), 0)


def _tile_any(diff: np.ndarray, thresh: int) -> np.ndarray:
    """每个 TILE×TILE 格里是否有超过 thresh 的差异（二值化后按格求平均，比 reshape 求最大快一倍）。"""
    hh, ww = diff.shape
    th, tw = -(-hh // TILE), -(-ww // TILE)
    if hh % TILE or ww % TILE:
        pad = np.zeros((th * TILE, tw * TILE), np.uint8)
        pad[:hh, :ww] = diff
        diff = pad
    _, m = cv2.threshold(diff, thresh, 255, cv2.THRESH_BINARY)
    return cv2.resize(m, (tw, th), interpolation=cv2.INTER_AREA) > 0


def components(tiles: np.ndarray, origin: tuple[int, int], dilate: int = 1) -> list[Rect]:
    """把相邻的变化格合成连通区域（像素矩形）。"""
    if tiles.size == 0 or not tiles.any():
        return []
    m = tiles.astype(np.uint8)
    if dilate:
        m = cv2.dilate(m, np.ones((2 * dilate + 1, 2 * dilate + 1), np.uint8))
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = []
    ox, oy = origin
    for i in range(1, n):
        x, y, w, h = (int(v) for v in stats[i][:4])
        out.append((ox + x * TILE, oy + y * TILE, ox + (x + w) * TILE, oy + (y + h) * TILE))
    return out


@dataclass
class ShiftResult:
    axis: str                  # "v" 竖直滚动 / "h" 水平滚动
    shift: int                 # 内容移动的像素数：竖直时正数表示内容向下移（往上滚）
    viewport: Rect             # 这次确认参与平移的范围（显示器坐标）
    votes: int                 # 支持这个位移的行数
    changed: int               # 区域内变化过的有效行数
    entering: Rect | None      # 新露出的条带
    bands: int                 # 同意这个位移的竖条数


def _band_layout(width: int, band: int) -> tuple[int, int]:
    nb = max(1, int(round(width / band)))
    return nb, (width // nb) & ~1  # 偶数宽：哈希时隔列取样


def _row_hashes(img: np.ndarray, nb: int, bw: int) -> tuple[np.ndarray, np.ndarray]:
    rows = img.shape[0]
    half = bw // 2
    # 隔列取样：滚动是竖向平移，横向少看一半列不影响“两行是否相同”的判别，转换和乘法省一半。
    blk = img[:, :nb * bw:2].astype(np.float32).reshape(rows, nb, half)
    w = _WEIGHTS[:half]
    hashes = blk @ w
    # 整条同色的行哈希恰好等于“颜色值 × 权重和”；用它判断“这一行有没有内容”，省掉逐行求最大最小值。
    informative = hashes != blk[:, :, 0] * np.float32(w.sum())
    return hashes, informative


def _vote(hp: np.ndarray, ip: np.ndarray, hq: np.ndarray, changed: np.ndarray, rows: int, nb: int) -> np.ndarray:
    """每条竖条里：上一帧唯一出现的行哈希 → 当前帧变化行里同样的哈希 → 为“位移 = 行号差”投一票。
    返回 (竖条, 2*rows+1) 的票数。所有竖条一次算完（哈希是 2^24 以内的整数，和竖条号拼成一个键）。"""
    span = 2 * rows + 1
    pr, pj = np.nonzero(ip)
    qr, qj = np.nonzero(changed)
    if pr.size == 0 or qr.size == 0:
        return np.zeros((nb, span), np.int64)
    kp = hp[pr, pj].astype(np.int64) * 1024 + pj
    order = np.argsort(kp, kind="stable")
    ks = kp[order]
    cut = np.flatnonzero(ks[1:] != ks[:-1]) + 1
    starts = np.concatenate(([0], cut))
    ends = np.concatenate((cut, [ks.size]))
    single = (ends - starts) == 1                    # 同一竖条里只出现一次的行，才能定位
    uk = ks[starts[single]]
    urow = pr[order[starts[single]]]
    if uk.size == 0:
        return np.zeros((nb, span), np.int64)
    kq = hq[qr, qj].astype(np.int64) * 1024 + qj
    pos = np.searchsorted(uk, kq)
    pos[pos >= uk.size] = uk.size - 1
    hit = uk[pos] == kq
    flat = qj[hit] * span + (qr[hit] - urow[pos[hit]]) + rows
    return np.bincount(flat, minlength=nb * span).reshape(nb, span)


DYN_RUN = 40   # 竖条里连续这么多行都变了、又对不上平移：当成一直在变的大块（视频、动画）


def _long_runs(mask: np.ndarray, min_len: int) -> np.ndarray:
    """mask（行 × 竖条）里纵向连续为真、长度不少于 min_len 的段。"""
    rows, nb = mask.shape
    m = np.zeros((rows + 2, nb), np.int8)
    m[1:-1] = mask
    d = np.diff(m, axis=0).T            # 按竖条排列：同一竖条里的段起点和终点按行号依次出现，可以逐个配对
    sc, sr = np.nonzero(d == 1)
    ec, er = np.nonzero(d == -1)
    long = (er - sr) >= min_len
    out = np.zeros((rows + 1, nb), np.int32)
    np.add.at(out, (sr[long], sc[long]), 1)
    np.add.at(out, (er[long], ec[long]), -1)
    return np.cumsum(out, axis=0)[:rows] > 0


def detect_shift(prev: np.ndarray, cur: np.ndarray, region: Rect, *, axis: str = "v", band: int = 48,
                 min_votes: int = 6, hashes: dict | None = None) -> ShiftResult | None:
    """在 region 内寻找整块平移。prev/cur 是整个显示器的灰度图。

    hashes：调用方保存的行哈希。若其中 "prev" 是上一帧同一区域（同样分条）的当前帧哈希，就直接当本次的
    上一帧哈希用（连续滚动时区域通常不变，省掉一半哈希计算）；本次当前帧的哈希写回 "cur"。
    """
    l, t, r, b = region
    if axis == "h":
        res = detect_shift(prev.T, cur.T, (t, l, b, r), axis="v", band=band, min_votes=min_votes)
        if res is None:
            return None
        vl, vt, vr, vb = res.viewport
        ent = res.entering
        return ShiftResult("h", res.shift, (vt, vl, vb, vr), res.votes, res.changed,
                           (ent[1], ent[0], ent[3], ent[2]) if ent else None, res.bands)
    if r - l < 16 or b - t < 24:
        return None
    P = prev[t:b, l:r]
    Q = cur[t:b, l:r]
    nb, bw = _band_layout(r - l, band)
    reuse = hashes.get("prev") if hashes is not None else None
    if reuse is not None and reuse[0] == (l, t, r, b, nb, bw):
        hp, ip = reuse[1], reuse[2]
    else:
        hp, ip = _row_hashes(P, nb, bw)
    hq, iq = _row_hashes(Q, nb, bw)
    if hashes is not None:
        hashes["cur"] = ((l, t, r, b, nb, bw), hq, iq)
    rows = b - t
    same = hp == hq
    changed_inf = iq & ~same
    n_changed = int(changed_inf.sum())
    if n_changed < min_votes:
        return None
    votes = _vote(hp, ip, hq, changed_inf, rows, nb)
    total = votes.sum(axis=0)
    total[rows] = 0  # 位移 0 = 没动
    best = int(total.argmax())
    best_votes = int(total[best])
    if best_votes < min_votes:
        return None
    s = best - rows
    # 投票只用“唯一”的行（重复的行无法定位）；位移选定后再逐条直接核对：
    # 平移 s 后相同的变化行占多数的竖条就算同意，这样重复内容多的区域（列表、模板化段落）也能认出来。
    lo, hi = max(0, s), min(rows, rows + s)
    expl = np.zeros_like(changed_inf)
    if hi > lo:
        expl[lo:hi] = (hq[lo:hi] == hp[lo - s:hi - s]) & changed_inf[lo:hi]
    # 页面里正在播放的视频、动画跟着页面一起移动，但每帧内容都不同，平移永远对不上。它们是成片连续的
    # “变了又对不上”的行（文字改动会被行距隔开，连不成这么长）；判断竖条是否同意这次平移时不算这些行，
    # 否则视频所在的整栏文字都会被当成没滚动，隐藏后重新识别。
    unexpl = changed_inf & ~expl
    chg = changed_inf
    if int(unexpl.sum(axis=0).max()) >= DYN_RUN:
        chg = changed_inf & ~_long_runs(unexpl, DYN_RUN)
    band_changed = chg.sum(axis=0)
    direct = expl.sum(axis=0)
    n_eff = int(band_changed.sum())
    agree = ((votes[:, best] >= 2) & (votes[:, best] * 2 >= band_changed)) | \
            ((band_changed >= 3) & (direct * 10 >= band_changed * 6))
    if not agree.any() or int(direct.sum()) * 3 < n_eff:
        return None
    if n_changed - n_eff > n_eff:
        # 大部分变化都是对不上平移的大块：平移证据必须足够强、足够集中（换页时偶然对上的行很少，位移也很分散）
        if best_votes < 40 or best_votes * 2 < int(total.sum()):
            return None
    cols = np.nonzero(agree)[0]
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    # 在同意的竖条里逐行判断：平移后相同（moved）还是原地不动且有内容（static，固定标题等）。
    sub_q = hq[:, c0:c1]
    sub_p = hp[:, c0:c1]
    sub_iq = iq[:, c0:c1]
    # 原地也相同的行（按钮竖边框、表格竖线这类上下相邻行一样的结构）平移 1~2 像素后同样对得上，
    # 不能据此算“动了”：只有“原地变了、平移后一致”的才算移动，只有“原地一致、平移后不一致”的才算固定。
    same0 = (sub_q == sub_p) & sub_iq
    moved = np.zeros(rows, bool)
    shifted_eq = np.zeros_like(same0)
    lo, hi = max(0, s), min(rows, rows + s)  # 当前帧行 y 对应上一帧 y - s
    if hi > lo:
        shifted_eq[lo:hi] = (sub_q[lo:hi] == sub_p[lo - s:hi - s]) & sub_iq[lo:hi]
        moved[lo:hi] = (shifted_eq[lo:hi] & ~same0[lo:hi]).any(axis=1)
    static = (same0 & ~shifted_eq).any(axis=1) & ~moved
    mrows = np.nonzero(moved)[0]
    if mrows.size == 0:
        return None
    top, bottom = int(mrows.min()), int(mrows.max()) + 1
    # 左右边界逐列细化：竖条宽 48 像素，可能跨在两栏的分界上。逐列数“平移后一致、原地却变了”的行
    # （在动）和“原地一致、平移后不一致”的行（没动）；两样都不是的行（视频画面、新内容）不参与。
    # 只保留明显在动、而且这一列有内容的列，边界精确到像素；空白边距不算进去（裁剪时宁可保守）。
    x0, x1 = c0 * bw, c1 * bw
    mr = mrows[(mrows - s >= 0) & (mrows - s < rows)]

    def col_moving(ys: np.ndarray, a: int, b_: int) -> np.ndarray:
        q = Q[ys, x0 + a:x0 + b_]
        sm = q == P[ys - s, x0 + a:x0 + b_]
        st = q == P[ys, x0 + a:x0 + b_]
        n_move = (sm & ~st).sum(axis=0)
        n_still = (st & ~sm).sum(axis=0)
        has_ink = q.max(axis=0) != q.min(axis=0)
        return (n_move >= 1) & (n_still * 8 <= n_move) & has_ink

    if mr.size >= 3:
        # 逐列统计不需要每一行，均匀取样省时间；取样可能漏掉只有一两行字伸到的边缘列，边缘外侧再用全部行看一遍
        ms = mr if mr.size <= 256 else mr[np.linspace(0, mr.size - 1, 256).astype(np.int64)]
        moving = np.nonzero(col_moving(ms, 0, x1 - x0))[0]
        if moving.size:
            lo_c, hi_c = int(moving.min()), int(moving.max())
            if ms.size < mr.size:
                if hi_c + 1 < x1 - x0:
                    ext = np.nonzero(col_moving(mr, hi_c + 1, x1 - x0))[0]
                    if ext.size:
                        hi_c += 1 + int(ext.max())
                if lo_c > 0:
                    ext = np.nonzero(col_moving(mr, 0, lo_c))[0]
                    if ext.size:
                        lo_c = int(ext.min())
            # 边界取在有墨迹的列外侧 6 像素：文字检测框比墨迹宽几像素，太贴会裁掉段首字母
            base = x0
            x0 = max(0, base + lo_c - 6)
            x1 = min(r - l, base + hi_c + 1 + 6)
    # 新露出的条带：内容上移（s<0）时在下方，下移时在上方；遇到固定内容即停。
    entering = None
    if s < 0:
        end = min(rows, bottom + (-s))
        st = np.nonzero(static[bottom:end])[0]
        if st.size:
            end = bottom + int(st.min())
        if end > bottom:
            entering = (l + x0, t + bottom, l + x1, t + end)
            bottom = end
    elif s > 0:
        start = max(0, top - s)
        st = np.nonzero(static[start:top])[0]
        if st.size:
            start = start + int(st.max()) + 1
        if start < top:
            entering = (l + x0, t + start, l + x1, t + top)
            top = start
    viewport = (l + x0, t + top, l + x1, t + bottom)
    return ShiftResult("v", s, viewport, best_votes, n_changed, entering, int(agree.sum()))


def residual_tiles(prev: np.ndarray, cur: np.ndarray, viewport: Rect, axis: str, s: int) -> list[Rect]:
    """平移解释不了的变化（滚动条、同时发生的内容变化），按格返回矩形。"""
    l, t, r, b = viewport
    if axis == "v":
        lo, hi = max(t, t + s), min(b, b + s)
        if hi <= lo:
            return [viewport]
        a = cur[lo:hi, l:r]
        p = prev[lo - s:hi - s, l:r]
        origin = (l, lo)
    else:
        lo, hi = max(l, l + s), min(r, r + s)
        if hi <= lo:
            return [viewport]
        a = cur[t:b, lo:hi]
        p = prev[t:b, lo - s:hi - s]
        origin = (lo, t)
    return components(_tile_any(cv2.absdiff(a, p), 24), origin, dilate=0)


def _acceptable(diff_mask: np.ndarray) -> bool:
    """差异是否可以忽略：完全一致，或只是一根闪烁的文字光标（≤3 像素宽的竖线）。

    文字本身哪怕只改了一个数字也会在字形处留下一团差异，这时必须判定为不一致，
    不能用“差得不多”继续显示旧译文。
    """
    if not diff_mask.any():
        return True
    cols = np.nonzero(diff_mask.any(axis=0))[0]
    if cols.size <= 3 and cols[-1] - cols[0] <= 3:
        rows = np.nonzero(diff_mask.any(axis=1))[0]
        return rows.size >= 0.5 * diff_mask.shape[0] or rows.size >= 8
    return False


def verify_patch(ref: np.ndarray, gray: np.ndarray, rect: Rect, search: int = 2,
                 mask: np.ndarray | None = None) -> tuple[bool, int, int]:
    """核对 rect 处的当前像素是否仍是 ref（识别时的灰度截图）；允许 ±search 像素的小偏差。

    mask（与 ref 同形状）只比较为真的像素：块被别的窗口挡住一部分时，只核对露出来的部分。
    返回 (是否一致, 最佳 dx, 最佳 dy)。超出屏幕的部分不比较。
    """
    h, w = gray.shape[:2]
    l, t, r, b = rect
    if r - l != ref.shape[1] or b - t != ref.shape[0]:
        return False, 0, 0
    best = (1 << 30, 0, 0, None)
    for dy in sorted(range(-search, search + 1), key=abs):
        for dx in sorted(range(-search, search + 1), key=abs):
            x0, y0, x1, y1 = l + dx, t + dy, r + dx, b + dy
            cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
            if cx1 - cx0 < 4 or cy1 - cy0 < 4:
                continue
            a = gray[cy0:cy1, cx0:cx1]
            p = ref[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
            diff = cv2.absdiff(a, p) > 40
            if mask is not None:
                diff &= mask[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
            bad = int(np.count_nonzero(diff))
            if bad == 0:
                return True, dx, dy
            if bad < best[0]:
                best = (bad, dx, dy, diff)
    if best[3] is None:
        return False, 0, 0
    return _acceptable(best[3]), best[1], best[2]


_K3 = np.ones((3, 3), np.uint8)


def verify_strokes(ref: np.ndarray, gray: np.ndarray, rect: Rect, fg_lum: float, bg_lum: float,
                   cell: int, search: int = 2) -> bool:
    """动态背景（游戏、视频字幕）上的文字核对：只看文字笔画在不在，不管背景怎么变。

    - 按识别时的文字色/底色亮度取“墨迹”像素；当前画面里原来的笔画要基本都还在（允许 1 像素偏差）；
    - 逐个字宽大小的格子检查：哪怕只换了一个字（比如血量数字），那一格的笔画会大面积缺失，判为不一致；
    - 笔画外围一圈不能也变成同色（字幕消失、背景恰好变亮时会这样）。
    """
    if abs(fg_lum - bg_lum) < 40:
        return False
    thr = (fg_lum + bg_lum) / 2
    bright = fg_lum > bg_lum
    ref_ink = (ref > thr) if bright else (ref < thr)
    n_ref = int(ref_ink.sum())
    if n_ref < 12:
        return False
    ring = cv2.dilate(ref_ink.astype(np.uint8), _K3, iterations=2).astype(bool) & ~ref_ink
    ref_near = cv2.dilate(ref_ink.astype(np.uint8), _K3).astype(bool)
    h, w = gray.shape[:2]
    l, t, r, b = rect
    for dy in sorted(range(-search, search + 1), key=abs):
        for dx in sorted(range(-search, search + 1), key=abs):
            x0, y0, x1, y1 = l + dx, t + dy, r + dx, b + dy
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                continue
            cur = gray[y0:y1, x0:x1]
            cur_ink = (cur > thr) if bright else (cur < thr)
            near = cv2.dilate(cur_ink.astype(np.uint8), _K3).astype(bool)
            missing = ref_ink & ~near
            extra = cur_ink & ~ref_near     # 离原有笔画超过 1 像素的新墨迹：多出来的笔画
            if missing.sum() > 0.15 * n_ref:
                continue
            if ring.any() and (cur_ink & ring).sum() > 0.45 * ring.sum():
                continue
            ok = True
            for cy in range(0, ref.shape[0], cell):
                for cx in range(0, ref.shape[1], cell):
                    sub_ref = ref_ink[cy:cy + cell, cx:cx + cell]
                    k = int(sub_ref.sum())
                    if k < 10:
                        continue
                    # 原有笔画大面积缺失，或多出了笔画（3 改成 8 这种包含关系也能发现）
                    if missing[cy:cy + cell, cx:cx + cell].sum() > 0.3 * k \
                            or extra[cy:cy + cell, cx:cx + cell].sum() > 0.04 * k + 8:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                return True
    return False


def busy_background(patch: np.ndarray, fg_lum: float, bg_lum: float) -> bool:
    """文字后面的底是不是“花”的（视频画面、游戏场景）：去掉笔画及其周围后，剩下的像素起伏大不大。

    只有底真的花，译文才改用深色底板白字；网页、文档上的字哪怕被误判成在动态区域，也保持原来的底色。
    """
    if patch.size < 64:
        return False
    rest = patch.ravel()
    if abs(fg_lum - bg_lum) >= 40:
        thr = (fg_lum + bg_lum) / 2
        ink = (patch > thr) if fg_lum > bg_lum else (patch < thr)
        near = cv2.dilate(ink.astype(np.uint8), _K3, iterations=2).astype(bool)
        rest = patch[~near]
    if rest.size < 32:
        return False
    return float(rest.std()) > 22


def static_rows(prev: np.ndarray, cur: np.ndarray, region: Rect, exclude: Rect, s: int) -> tuple[int, int]:
    """region 内、exclude 行范围以外的行里：原地不动且有内容的行数，和按位移 s 对得上的行数。

    用来判断一个已知的大滚动画布是整体在动（外面只有空白），还是里面另有一块独立区域在滚。
    只看 exclude 的列范围（竖直滚动）。
    """
    l, t, r, b = region
    cl, cr = max(l, exclude[0]), min(r, exclude[2])
    if cr - cl < 8:
        return 0, 0
    rows = [y for y in range(t, b) if not (exclude[1] <= y < exclude[3])]
    if not rows:
        return 0, 0
    ys = np.array(rows)
    q = cur[ys, cl:cr]
    p0 = prev[ys, cl:cr]
    informative = q.max(axis=1) != q.min(axis=1)
    same0 = (q == p0).all(axis=1)
    src = ys - s
    ok = (src >= 0) & (src < prev.shape[0])
    sameS = np.zeros(len(ys), bool)
    if ok.any():
        sameS[ok] = (q[ok] == prev[src[ok], cl:cr]).all(axis=1)
    static = informative & same0 & ~sameS
    moved = informative & sameS & ~same0
    return int(static.sum()), int(moved.sum())
