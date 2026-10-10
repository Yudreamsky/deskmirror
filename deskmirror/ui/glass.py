"""液态玻璃皮肤（#8）：魔镜的边框、标签、球画成苹果“液态玻璃”的样子。

玻璃的边缘像一圈弧形的厚玻璃：后面的画面在这一圈里被往外拉伸、沿着圆角弯过去（折射），越靠外沿取得越远；
红绿蓝各偏一点（色散）；外沿一道高光、靠里一道淡淡的暗影，看得出弧度；略微提亮、提一点饱和度。
边框玻璃的里沿不描线：位移、提亮、饱和度都往里渐渐减到零，平滑地融进镜内，只看得到外沿那一道弧形的边。
边框就是镜框外面一圈 BAND 宽的玻璃（也是拖它调整大小的地方）。标签和球是整块玻璃：边上一圈折射，
里面再磨砂一点（模糊）、蒙一层白；后面是深色画面时换成烟灰玻璃（看后面的亮度自动换，像苹果的玻璃那样随内容变）。

后面的画面来自截屏：魔镜自己的窗口都对截屏隐身，截到的正好是它们后面的东西（见 Backdrop）。
Lens 们只管“给定后面的画面，画出玻璃”：位移图按尺寸算一次缓存起来，之后每次只是取样、混色（毫秒级）。
色键窗口（Windows 10）画不了半透明：先把玻璃和后面的画面混好，整块不透明地画上去，边缘一样是平滑的。
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from .. import geom, winapi
from ..geom import Rect
from . import layered

# 边框：一圈 BAND 宽的玻璃，外沿圆角 RADIUS（里沿的圆角是 RADIUS − BAND）
BAND = 11
RADIUS = 18
SHIFT = 6.5          # 边框外沿处往里取样多远：边框底下的内容放大一倍半左右，外沿处弯折（再大就拉成色条了）
GAP = 6              # 标签浮在边框上方的间距
TAB_LENS = (9, 6.0, 1.0, 1.5)       # 标签：折射带宽、外沿取样距离、磨砂（模糊）、饱和度，照浏览器版
BALL_LENS = (15 / 46, 9 / 46, 0.5, 1.4)   # 球：折射带宽、取样距离按直径的比例
DISP = (1.10, 1.05, 1.0)    # 蓝、绿、红的位移倍数（cv2 的通道顺序是 BGR）：边上一丝色散
LIGHT = (-0.6, -0.8)        # 光从左上照来（指向光源）
POLL = 0.25          # 引擎没在截那块屏幕时（暂停、收成球），自己多久截一次看后面变没变（秒）
_LUMA = np.array([0.114, 0.587, 0.299], np.float32)
_KEY_BGR = (layered.KEY[2], layered.KEY[1], layered.KEY[0])

_active = False


def active() -> bool:
    """现在用的是不是液态玻璃皮肤（程序启动、改设置时由 set_active 设）。"""
    return _active


def set_active(on: bool) -> None:
    global _active
    _active = bool(on)


def _sdf(w: float, h: float, r: float, xs: np.ndarray, ys: np.ndarray):
    """圆角矩形 (0, 0, w, h)、圆角 r：像素中心离边缘多深（里面为正）和外法线 (nx, ny)。xs, ys 是像素坐标。"""
    hw, hh = w / 2, h / 2
    r = min(r, hw, hh)
    px, py = xs + 0.5 - hw, ys + 0.5 - hh
    qx, qy = np.abs(px) - (hw - r), np.abs(py) - (hh - r)
    ox, oy = np.maximum(qx, 0), np.maximum(qy, 0)
    ln = np.hypot(ox, oy)
    depth = r - ln - np.minimum(np.maximum(qx, qy), 0)
    corner = (qx > 0) & (qy > 0)
    lns = np.where(ln > 0, ln, 1)
    nx = np.where(corner, ox / lns, (qx >= qy).astype(np.float32)) * np.sign(px)
    ny = np.where(corner, oy / lns, (qx < qy).astype(np.float32)) * np.sign(py)
    return depth.astype(np.float32), nx.astype(np.float32), ny.astype(np.float32)


def _color_matrix(sat: float, lift: float) -> np.ndarray:
    """BGR 的 3×4 仿射矩阵：饱和度乘 sat，再往白里提 lift（0–1）。"""
    m = sat * np.eye(3, dtype=np.float32) + (1 - sat) * np.tile(_LUMA, (3, 1))
    return np.hstack([m * (1 - lift), np.full((3, 1), 255 * lift, np.float32)])


def _qimage(buf: np.ndarray) -> QImage:
    h, w = buf.shape[:2]
    return QImage(buf.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()


class Lens:
    """一块圆角矩形玻璃（w×h、圆角 r）里 area 这一块的折射：离外沿 bezel 以内的一圈往里取样，越靠外沿
    取得越远（外沿处 shift 像素）——后面的画面在边上被拉宽、沿圆角弯过去。三个颜色通道位移略有不同（色散）。
    ring：只有 bezel 宽的一圈（边框），里面透明；否则整块都是玻璃（标签、球）。
    shade：按离外沿多深加的明暗（外沿亮、靠里一道暗影），看得出弧度。"""

    def __init__(self, w: float, h: float, r: float, bezel: float, shift: float, area: tuple[int, int, int, int],
                 ring: bool = False, shade: float = 1.0) -> None:
        x0, y0, x1, y1 = area
        self.area = area
        self.ring = ring
        self.pad = int(math.ceil(shift * max(DISP))) + 2      # 取样会伸到 area 外面多远
        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        depth, nx, ny = _sdf(w, h, r, xs, ys)
        t = np.clip(1 - depth / bezel, 0, 1)
        # 弧形的边：越靠外沿坡越陡、取得越远（一半匀速放大，一半按圆弧在外沿急剧弯折）
        d = shift * (0.45 * t + 0.55 * (1 - np.sqrt(np.clip(1 - t * t, 0, 1))))
        bx, by = xs - x0 + self.pad, ys - y0 + self.pad
        self.maps = [(bx - nx * d * k, by - ny * d * k) for k in DISP]
        cover = np.clip(depth + 0.5, 0, 1)
        if ring:
            cover *= np.clip(bezel - depth + 0.5, 0, 1)
        self.cover = cover
        # 边框：提亮、饱和度从外沿往里渐渐减到零，里沿和镜内接得上，看不出一道线
        self.fade = (t ** 1.5)[..., None].astype(np.float32) if ring else None
        # 色键窗口里整块不透明画出去的范围：玻璃再往外一圈（外沿的抗锯齿、描边都落在里面）
        self.zone = (depth >= -1.5) & ((depth <= bezel + 0.5) if ring else True)
        # 明暗：外沿一层亮（朝光的一边更亮），离外沿约四成处一道淡淡的暗影
        facing = nx * LIGHT[0] + ny * LIGHT[1]
        lit = 0.45 + 0.55 * np.maximum(facing, 0) + 0.3 * np.maximum(-facing, 0)
        u = np.maximum(depth, 0)
        glow = 0.30 * np.exp(-u / 1.3) * lit
        dark = -0.13 * np.exp(-(((u - bezel * 0.42) / (bezel * 0.2)) ** 2))
        self.shade = ((glow + dark) * shade * (u < bezel + 1)).astype(np.float32)

    def patch_rect(self, ox: int, oy: int) -> Rect:
        """要取的背景范围（屏幕坐标）：玻璃左上角在屏幕 (ox, oy)。"""
        x0, y0, x1, y1 = self.area
        p = self.pad
        return (ox + x0 - p, oy + y0 - p, ox + x1 + p, oy + y1 + p)

    def _shading(self) -> tuple[np.ndarray, np.ndarray]:
        """明暗和透明度合成一次乘加（第一次用时算好）：提亮是往白里混（c·(1−s) + 255·s），压暗是 c·(1+s)；
        再乘上覆盖率，得到预乘透明度的颜色。"""
        if getattr(self, "_mul", None) is None:
            s = self.shade
            self._mul = ((1 - np.abs(s)) * self.cover)[..., None].astype(np.float32)
            self._add = (255 * np.maximum(s, 0) * self.cover)[..., None].astype(np.float32)
            self._alpha8 = np.clip(self.cover * 255 + 0.5, 0, 255).astype(np.uint8)
        return self._mul, self._add

    def render(self, patch: np.ndarray | None, sat: float = 1.25, lift: float = 0.05, blur: float = 0.0,
               flat: tuple[int, int, int, int] = (255, 255, 255, 90), solid: bool = False) -> QImage:
        """patch：patch_rect 那一块的背景（BGRA 或 BGR）；None（还没截到）时是一层淡淡的磨砂白（或烟灰）。
        返回预乘透明度的 ARGB32 图，大小和 area 一样。solid：色键窗口用，玻璃先和背景混好、不透明。"""
        x0, y0, x1, y1 = self.area
        h, w = y1 - y0, x1 - x0
        p = self.pad
        if patch is not None and patch.shape[:2] != (h + 2 * p, w + 2 * p):
            patch = None
        mul, add = self._shading()
        if patch is None:
            b, g, r, a = flat
            rgb = np.empty((h, w, 3), np.float32)
            rgb[:] = (b, g, r)
            k = (a / 255) * (self.fade if self.fade is not None else 1.0)
            alpha = self.cover * (k[..., 0] if self.fade is not None else k)
            glass_ = (rgb * mul + add) * k                       # 预乘透明度
        else:
            chans = cv2.split(patch)[:3]
            if blur > 0:
                chans = [cv2.GaussianBlur(c, (0, 0), blur) for c in chans]
            out = cv2.merge([cv2.remap(c, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                             for c, (mx, my) in zip(chans, self.maps)])
            adj = cv2.transform(out, _color_matrix(sat, lift))
            if self.fade is not None:                            # 边框：越往里越接近后面的原样
                base = out.astype(np.float32)
                adj = base + (adj - base) * self.fade
            glass_ = adj * mul
            glass_ += add
            alpha = self.cover
        buf = np.zeros((h, w, 4), np.uint8)
        if not solid:
            glass_ += 0.5
            buf[..., :3] = np.minimum(glass_, 255)
            buf[..., 3] = self._alpha8 if patch is not None else np.clip(alpha * 255 + 0.5, 0, 255)
            return _qimage(buf)
        if patch is not None:
            mixed = glass_ + patch[p:p + h, p:p + w, :3] * (1 - alpha[..., None])
            zone = self.zone
        else:
            mixed = glass_ / np.maximum(alpha[..., None], 1e-3)
            zone = alpha > 0.25
        px = np.clip(mixed + 0.5, 0, 255).astype(np.uint8)
        key = (px[..., 0] == _KEY_BGR[0]) & (px[..., 1] == _KEY_BGR[1]) & (px[..., 2] == _KEY_BGR[2])
        px[key, 0] -= 1                                   # 碰上色键的颜色挪开一点，不然那里会透明
        buf[zone, :3] = px[zone]
        buf[zone, 3] = 255
        return _qimage(buf)


def luma(patch: np.ndarray | None) -> float | None:
    """背景的平均亮度（0–1）：决定标签、球用白玻璃还是烟灰玻璃。"""
    if patch is None or patch.size == 0:
        return None
    small = patch[::4, ::4, :3].astype(np.float32)
    return float((small @ _LUMA).mean() / 255)


class Tone:
    """浅色（白玻璃、深色字）还是深色（烟灰玻璃、浅色字）：看后面的亮度，带一点回差，免得在临界处来回闪。"""

    def __init__(self) -> None:
        self.dark = False

    def update(self, lum: float | None) -> bool:
        """返回变没变。"""
        if lum is None:
            return False
        dark = lum < 0.42 if not self.dark else lum < 0.52
        changed = dark != self.dark
        self.dark = dark
        return changed


# ---------------------------------------------------------------------------------------------------- 边框
class Rim:
    """魔镜边框的玻璃：镜框外面一圈 BAND 宽，分成上下左右四条分别取样、重画（只有变了的那条要重画）。
    坐标都相对外框（镜框往外扩 BAND）的左上角。外沿的高光、主题色细圈按尺寸先画好，每条重画时叠上去：
    窗口重画时只是贴四张图（重画得勤，不能每次都描整圈圆角）。"""

    def __init__(self, mw: int, mh: int, color: QColor | None = None) -> None:
        self.size = (mw, mh)
        W, H = mw + 2 * BAND, mh + 2 * BAND
        self.outer = (W, H)
        c = RADIUS                           # 上下两条把圆角整个包进去
        parts = {"t": (0, 0, W, c), "b": (0, H - c, W, H), "l": (0, c, BAND, max(c, H - c)),
                 "r": (W - BAND, c, W, max(c, H - c))}
        self.lenses = {name: Lens(W, H, RADIUS, BAND, SHIFT, a, ring=True)
                       for name, a in parts.items() if a[3] > a[1] and a[2] > a[0]}
        self.images: dict[str, QImage] = {}
        self.color = QColor(color) if color is not None else QColor("#3D8BFD")
        self._edges: dict[str, QImage] = {}

    def _edge_layer(self, name: str) -> QImage:
        """这一条上的高光、描边（透明底），颜色、尺寸不变就一直用。"""
        img = self._edges.get(name)
        if img is None:
            x0, y0, x1, y1 = self.lenses[name].area
            img = QImage(x1 - x0, y1 - y0, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            W, H = self.outer
            paint_edges(p, QRectF(-x0, -y0, W, H), RADIUS, self.color)
            p.end()
            self._edges[name] = img
        return img

    def set_color(self, color: QColor) -> None:
        if QColor(color) != self.color:
            self.color = QColor(color)
            self._edges.clear()
            self.images.clear()

    def render(self, name: str, patch: np.ndarray | None, solid: bool = False) -> None:
        img = self.lenses[name].render(patch, sat=1.3, lift=0.05, solid=solid)
        p = QPainter(img)
        p.drawImage(0, 0, self._edge_layer(name))
        p.end()
        self.images[name] = img

    def part_rect(self, name: str, ox: float, oy: float) -> QRectF:
        x0, y0, x1, y1 = self.lenses[name].area
        return QRectF(ox + x0, oy + y0, x1 - x0, y1 - y0)

    def paint(self, p: QPainter, ox: float, oy: float, solid: bool = False, clip: QRectF | None = None) -> None:
        """画到外框左上角在 (ox, oy) 的位置（clip：只画和它相交的几条）。"""
        for name, lens in self.lenses.items():
            r = self.part_rect(name, ox, oy)
            if clip is not None and not r.intersects(clip):
                continue
            if name not in self.images:
                self.render(name, None, solid)
            p.drawImage(r.topLeft(), self.images[name])


def paint_edges(p: QPainter, r: QRectF, radius: float, color: QColor | None, dark: bool = False) -> None:
    """玻璃的外沿：最外一圈淡淡的主题色（看得出魔镜在哪），里面一道高光——左上最亮、右下次之，像光从左上照来。"""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if color is not None:
        c = QColor(color)
        c.setAlphaF(0.8)
        p.setPen(QPen(c, 1.2))
        p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), radius - 0.6, radius - 0.6)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    hi = 0.6 if dark else 1.0
    g.setColorAt(0.0, QColor(255, 255, 255, int(255 * hi)))
    g.setColorAt(0.3, QColor(255, 255, 255, int(255 * hi * 0.5)))
    g.setColorAt(0.7, QColor(255, 255, 255, int(255 * hi * 0.32)))
    g.setColorAt(1.0, QColor(255, 255, 255, int(255 * hi * 0.8)))
    p.setPen(QPen(g, 1.3))
    o = 1.85 if color is not None else 0.65
    p.drawRoundedRect(r.adjusted(o, o, -o, -o), radius - o, radius - o)
    p.restore()


# ---------------------------------------------------------------------------------------------------- 标签、球
class Pill:
    """一整块玻璃（标签是两头圆的长条，球是圆）：边上一圈折射，里面稍微磨砂、提饱和度，再蒙一层白（或烟灰）。"""

    def __init__(self, w: int, h: int, radius: float, bezel: float, shift: float, blur: float, sat: float,
                 ball: bool = False) -> None:
        self.size = (w, h)
        self.radius = radius
        self.ball = ball
        self.lens = Lens(w, h, radius, bezel, shift, (0, 0, w, h), shade=0.8)
        self.blur, self.sat = blur, sat
        self.image: QImage | None = None
        self.tone = Tone()

    @classmethod
    def tab(cls, w: int, h: int) -> Pill:
        bezel, shift, blur, sat = TAB_LENS
        return cls(w, h, h / 2, bezel, shift, blur, sat)

    @classmethod
    def bubble(cls, d: int) -> Pill:
        bezel, shift, blur, sat = BALL_LENS
        return cls(d, d, d / 2, bezel * d, shift * d, blur, sat, ball=True)

    def patch_rect(self, ox: int, oy: int) -> Rect:
        return self.lens.patch_rect(ox, oy)

    def render(self, patch: np.ndarray | None, solid: bool = False) -> bool:
        """返回颜色深浅换没换（换了上面的字也要换颜色）。"""
        changed = self.tone.update(luma(patch))
        self.image = self.lens.render(patch, sat=self.sat, lift=0.0, blur=self.blur, solid=solid,
                                      flat=(54, 50, 48, 170) if self.tone.dark else (252, 250, 250, 170))
        return changed

    def paint(self, p: QPainter, ox: float, oy: float, solid: bool = False) -> None:
        """玻璃本体：折射的底、一层白（或烟灰），上沿内高光、下沿内阴影、细边。"""
        w, h = self.size
        r = QRectF(ox, oy, w, h)
        if self.image is None:
            self.render(None, solid)
        dark = self.tone.dark
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        if not solid and not self.ball:
            # 下沿一道很淡的影子（只往下伸几个像素：标签外面一圈不能接鼠标）
            p.setPen(Qt.PenStyle.NoPen)
            for dy, a in ((1.0, 26), (2.2, 16), (3.4, 8)):
                p.setBrush(QColor(0, 0, 0, a if not dark else a * 2))
                p.drawRoundedRect(r.adjusted(0.5, dy, -0.5, dy), self.radius, self.radius)
        p.drawImage(QPointF(ox, oy), self.image)
        if self.ball:
            g = QRadialGradient(QPointF(ox + w * 0.3, oy + h * 0.18), max(w, h) * 1.2)
            if dark:
                g.setColorAt(0.0, QColor(120, 160, 230, 140))
                g.setColorAt(0.5, QColor(40, 60, 100, 77))
                g.setColorAt(1.0, QColor(20, 24, 34, 66))
            else:
                g.setColorAt(0.0, QColor(255, 255, 255, 128))
                g.setColorAt(0.46, QColor(255, 255, 255, 31))
                g.setColorAt(1.0, QColor(236, 240, 248, 20))
        else:
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            edge, mid = (QColor(72, 72, 78), QColor(30, 30, 34)) if dark else (QColor(255, 255, 255),
                                                                              QColor(250, 250, 252))
            for at, a in ((0.0, 0.30 if dark else 0.26), (0.34, 0.62), (0.66, 0.62), (1.0, 0.30 if dark else 0.26)):
                c = QColor(mid if 0 < at < 1 else edge)
                c.setAlphaF(a)
                g.setColorAt(at, c)
        p.fillPath(path, g)
        # 上沿内高光、下沿内阴影
        p.setClipPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 72 if dark else 235), 1.6 if self.ball else 1.2))
        p.drawRoundedRect(r.adjusted(0.6, 1.1, -0.6, 4), self.radius, self.radius)
        p.setPen(QPen(QColor(0, 0, 0, 60 if dark else 16), 2.5 if self.ball else 1.2))
        p.drawRoundedRect(r.adjusted(0.6, -4, -0.6, -1.1), self.radius, self.radius)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 64 if dark else 200), 1.0))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.radius - 0.5, self.radius - 0.5)
        if not dark and not self.ball and not solid:     # 色键窗口里画不到标签外面
            p.setPen(QPen(QColor(0, 0, 0, 22), 1.0))          # 白底上也看得出标签的轮廓
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), self.radius + 0.5, self.radius + 0.5)
        p.restore()


def paint_morph(p: QPainter, rect: QRectF, radius: float, k: float, color: QColor, dark: bool, dash: bool,
                solid: bool) -> None:
    """收成球、张开成魔镜途中的形状（玻璃样式，不折射：每帧都改大小，来不及取样）：一层渐浓的白（或烟灰）、
    白色的边和主题色的细圈；虚线框（从边上拖出来时）是主题色的虚线。"""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, not solid)
    p.setPen(Qt.PenStyle.NoPen)
    fill = QColor(40, 46, 60) if dark else QColor(236, 243, 255)
    if solid:
        if k >= 0.5:
            p.setBrush(fill)
            p.drawRoundedRect(rect, radius, radius)
    elif k > 0:
        fill.setAlphaF(min(1.0, (0.85 if dark else 0.92) * k))
        p.setBrush(fill)
        p.drawRoundedRect(rect, radius, radius)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if dash:
        pen = QPen(layered.solid(color) if solid else color, 2.0)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([3.0, 2.0])
        p.setPen(pen)
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), max(0.0, radius - 1), max(0.0, radius - 1))
    else:
        c = QColor(color)
        if not solid:
            c.setAlphaF(0.75)
        p.setPen(QPen(layered.solid(c) if solid else c, 1.2))
        p.drawRoundedRect(rect.adjusted(0.6, 0.6, -0.6, -0.6), max(0.0, radius - 0.6), max(0.0, radius - 0.6))
        p.setPen(QPen(QColor(255, 255, 255) if solid else QColor(255, 255, 255, 230), 1.5))
        p.drawRoundedRect(rect.adjusted(1.9, 1.9, -1.9, -1.9), max(0.0, radius - 1.9), max(0.0, radius - 1.9))
    p.restore()


# ---------------------------------------------------------------------------------------------------- 后面的画面
class Backdrop:
    """玻璃后面的屏幕画面。魔镜自己的窗口都对截屏隐身，截到的就是它们后面的东西。

    引擎正在截那块屏幕时，直接从它的截屏缓冲区复制，有没有变化也听它的（桌面复制给的变化范围），不多截一次；
    引擎没在截（暂停、收成球、别的屏幕）时，自己每 POLL 秒用 GDI 截一小块，和上次比一比。
    截图模式下魔镜对截屏可见，截到的会是魔镜自己：这期间不更新（frozen）。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.frozen = False
        self._mss = None
        self._seq = 0
        self._changed: list[Rect] | None = []
        self._seen: dict = {}            # (对象, 部位) → (范围, 上次截到的画面或 None, 时间)

    def begin(self) -> None:
        """每一轮开始时调用：取引擎上一轮以来报告的变化范围。"""
        try:
            self._seq, self._changed = self.engine.changes_since(self._seq)
        except AttributeError:
            self._changed = None

    def _live(self, rect: Rect):
        """引擎正在截 rect 所在的那块屏幕：返回那块屏幕（引擎的 Mon），否则 None。"""
        if not getattr(self.engine, "working", False):
            return None
        for m in list(getattr(self.engine, "mons", ())):
            if m.bgra is not None and geom.contains(m.rect, rect):
                return m
        return None

    def grab(self, rect: Rect) -> np.ndarray | None:
        """rect（屏幕坐标）的画面，BGRA；伸出那块屏幕的部分用边上的像素补。"""
        l, t, r, b = rect
        if r <= l or b <= t:
            return None
        m = self._live(rect)
        if m is not None:
            ll, tt, rr, bb = m.local(rect)
            with m.cap.lock:
                return m.bgra[tt:bb, ll:rr].copy()
        cx, cy = geom.center(rect)
        mons = winapi.monitors()
        mon = next((mo for mo in mons if geom.contains_pt(mo.rect, cx, cy)), None) or \
            min(mons, key=lambda mo: abs(geom.center(mo.rect)[0] - cx) + abs(geom.center(mo.rect)[1] - cy))
        c = geom.inter(rect, mon.rect)
        if geom.empty(c):
            return None
        try:
            if self._mss is None:
                import mss
                self._mss = mss.MSS()
            shot = self._mss.grab({"left": c[0], "top": c[1], "width": c[2] - c[0], "height": c[3] - c[1]})
        except Exception:  # noqa: BLE001 - 截不到（桌面切换、锁屏）：玻璃先不更新
            return None
        img = np.frombuffer(shot.bgra, np.uint8).reshape(c[3] - c[1], c[2] - c[0], 4)
        if c != rect:
            img = cv2.copyMakeBorder(img, c[1] - t, b - c[3], c[0] - l, r - c[2], cv2.BORDER_REPLICATE)
        return np.ascontiguousarray(img)

    def fresh(self, owner, part: str, rect: Rect, now: float, force: bool = False) -> np.ndarray | None:
        """这一块要不要重画：要就返回新截的画面，不用就返回 None。force：位置、大小刚变过，一定重取。
        引擎报告的变化只说明“可能变了”：魔镜自己的窗口重画时，桌面复制也会报告那一块变了（虽然截到的画面里
        没有它），所以截到以后还要和上次比一比，一样就不重画——不然玻璃重画、报告变化、再重画，停不下来。"""
        if self.frozen:
            return None
        key = (id(owner), part)
        last = self._seen.get(key)
        same = last is not None and last[0] == rect
        if self._live(rect) is not None:
            if same and not force and self._changed is not None and \
                    not any(geom.overlaps(rect, c) for c in self._changed):
                return None
        elif same and not force and now - last[2] < POLL:
            return None
        patch = self.grab(rect)
        if patch is None:
            return None
        if same and not force and last[1] is not None and np.array_equal(last[1], patch):
            self._seen[key] = (rect, last[1], now)
            return None
        self._seen[key] = (rect, patch, now)
        return patch

    def forget(self, owner) -> None:
        for key in [k for k in self._seen if k[0] == id(owner)]:
            del self._seen[key]

    def close(self) -> None:
        self._seen.clear()
        if self._mss is not None:
            try:
                self._mss.close()
            except Exception:  # noqa: BLE001
                pass
            self._mss = None

