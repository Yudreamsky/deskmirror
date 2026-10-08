"""场景模型：画布树和文字块。

画布树：桌面（根）→ 顶层窗口 → 滚动画布（可以嵌套）。每个画布有自己的“内容坐标”，
offset 把内容坐标平移到父画布坐标；viewport 是它在父画布坐标里的可见范围。
窗口移动只改窗口画布的 offset，局部滚动只改对应滚动画布的 offset，二者互不叠加。
文字块挂在最深的画布上，屏幕位置 = 块的内容坐标 + 一路向上的 offset 之和；
可见范围 = 一路向上的 viewport 求交，再与窗口未被遮挡的部分求交。
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import numpy as np

from . import geom
from .geom import Rect

_ids = itertools.count(1)
BIG: Rect = (-1_000_000, -1_000_000, 1_000_000, 1_000_000)


@dataclass(eq=False)
class Canvas:
    kind: str                         # desktop | window | scroll
    parent: Canvas | None
    offset: list[int]
    viewport: Rect | None             # 父画布坐标
    hwnd: int = 0
    axis: str = ""
    cid: int = field(default_factory=lambda: next(_ids))
    children: list[Canvas] = field(default_factory=list)
    blocks: dict[int, Block] = field(default_factory=dict)
    created: float = field(default_factory=time.perf_counter)
    last_move: float = 0.0
    last_scroll_ok: float = 0.0           # 窗口画布：最近一次在它里面识别出滚动的时间
    alive: bool = True
    motion: list = field(default_factory=list)   # 滚动画布：最近几帧的 (帧时间, 位移, 与上一处理帧的间隔)

    def screen_offset(self) -> tuple[int, int]:
        ox = oy = 0
        c: Canvas | None = self
        while c is not None:
            ox += c.offset[0]
            oy += c.offset[1]
            c = c.parent
        return ox, oy

    def screen_clip(self) -> Rect:
        clip = BIG
        c: Canvas | None = self
        while c is not None:
            if c.viewport is not None:
                px, py = c.parent.screen_offset() if c.parent is not None else (0, 0)
                clip = geom.inter(clip, geom.shift(c.viewport, px, py))
            c = c.parent
        return clip

    def window(self) -> Canvas | None:
        c: Canvas | None = self
        while c is not None and c.kind != "window":
            c = c.parent
        return c

    def depth(self) -> int:
        d, c = 0, self.parent
        while c is not None:
            d, c = d + 1, c.parent
        return d

    def descendants(self):
        for ch in self.children:
            yield ch
            yield from ch.descendants()

    def to_content(self, screen_rect: Rect) -> Rect:
        ox, oy = self.screen_offset()
        return geom.shift(screen_rect, -ox, -oy)

    def to_screen(self, content_rect: Rect) -> Rect:
        ox, oy = self.screen_offset()
        return geom.shift(content_rect, ox, oy)


@dataclass(eq=False)
class Block:
    canvas: Canvas
    rect: Rect                        # 画布内容坐标
    lines: list[tuple[Rect, str]]     # 画布内容坐标
    text: str
    key: str                          # 译文缓存键
    ref: np.ndarray                   # 识别时这块区域的灰度图，用于核对对应关系
    bg: tuple[int, int, int]
    fg: tuple[int, int, int]
    line_h: int
    em: float = 0.0                   # 估计的原文字号（像素），排版用
    bid: int = field(default_factory=lambda: next(_ids))
    state: str = "pending"            # pending / translating / done / failed / skip
    translation: str = ""
    error: str = ""
    attempts: int = 0
    retry_at: float = 0.0
    version: int = 1                  # 译文或排版空间变化时加一，界面据此重绘缓存
    ok_rect: Rect | None = None       # 最近一次确认过像素对应关系时的屏幕位置
    room_bottom: int = 0              # 排版时最多可以向下延伸到的内容坐标
    extra_w: int = 0                  # 译文放不下时最多可以向右借用的空白宽度（相对原文块右边，跟着块一起移动）
    extra_max: int = 0                # 一个英文词都放不下时最多能伸多宽：只看右边的字，不看底色（宁可盖住一点图案也不拆词）
    plain_below: int = -1             # 原文块下面有多高是同色、静止的空白：译文向下多占几行时先只用这片（-1 = 不限）
    created: float = field(default_factory=time.perf_counter)
    job_id: int = 0
    dynamic: bool = False             # 在动态背景上（视频字幕、游戏画面）：深色底板白字，按笔画核对
    born_dynamic: bool = False        # 一出现就在动态区域（字幕、游戏文字）：换句时旧译文保留到新译文顶掉
    counter: bool = False             # 计数器（倒计时、计数、血量：同一位置只有数字在变）：数字一变先留着旧译文，新数字的译文一出来就顶掉
    vertical: bool = False            # 竖排（漫画气泡）：向右、向下借地方时更严，不盖住气泡的弧形边框
    cols: list = field(default_factory=list)   # 竖排时每个字的墨迹（相对块左上角）：底板只盖这些字和译文
    lum_fg: tuple = (0, 0, 0)         # 识别时取样的文字色 / 底色（笔画核对用，不随显示样式改变）
    lum_bg: tuple = (255, 255, 255)
    held_until: float = 0.0           # 动态区域：原文换了但新译文还没好时，旧译文保留到这个时刻
    hold_start: float = 0.0
    hold_rect: Rect | None = None
    replaces: list = field(default_factory=list)   # 这块译好后要顶掉的旧块
    refind_at: float = 0.0            # 对不上时在附近重新找这段的下一次时间（找不到就逐步放慢）
    refind_n: int = 0
    missed: int = 0                   # 像素没变、重新识别却没报出来的次数（短词置信度差一点）：连着三次才删
    ink: Rect | None = None           # 原文墨迹的范围（相对块左上角）：译文按字的边对齐，不按检测框的边
    em_raw: float = 0.0               # 这块自己估的字号；em 是和同一列、同一排的块统一过的
    align: str = "left"               # 原文怎么对齐：left / right（参数名贴着输入框）/ center（图标下的名字、下拉框里的字）
    align_n: int = 0                  # 有几块和它对齐、支持这个判断（0 = 没有旁证，按默认）
    label: bool = False               # 界面上的短标签（按钮、菜单项、参数名）：译文不折行
    grad: tuple | None = None         # 底是上下渐变（按钮、下拉框）：(上沿颜色, 下沿颜色)，底板照着画
    extra_left: int = 0               # 右对齐、居中的译文放不下时最多可以向左借用的空白宽度

    def screen_rect(self) -> Rect:
        return self.canvas.to_screen(self.rect)

    def verified_here(self) -> bool:
        return self.ok_rect is not None and self.ok_rect == self.screen_rect()


@dataclass(frozen=True)
class DrawItem:
    """交给界面线程的一块译文；界面按 (bid, version) 缓存排版结果。"""
    bid: int
    version: int
    rect: Rect                        # 原文块的屏幕位置
    room: Rect                        # 可用于排版的最大范围（屏幕坐标）
    clips: tuple[Rect, ...]           # 所属画布可见范围 ∩ 窗口未遮挡部分
    text: str
    bg: tuple[int, int, int]
    fg: tuple[int, int, int]
    line_h: int
    n_lines: int
    em: float = 0.0
    ref: np.ndarray | None = field(default=None, compare=False, repr=False)  # 识别时的原文灰度图（核对用）
    src: str = field(default="", compare=False, repr=False)                  # 原文（历史面板、调试通道用）
    stretch: int = 0                  # 一个英文词都放不下时，底板最多能伸到的右边界（屏幕坐标；0 = 不伸）
    soft: int | None = None           # 向下多占几行时最好不超过的下边界：再往下是边框、图片、在动的画面（屏幕坐标；None = 不限）
    vertical: bool = False            # 原文是竖排（漫画气泡）：句末标点就在框里，底板不用往右多盖
    # 竖排原文每个字的墨迹（相对原文块左上角）：底板只盖这些字和译文实际占的地方，不铺满整块——
    # 几列长短不一、一列两头是窄的标点时，方底板的角会伸出椭圆气泡、盖掉弧形边框
    cols: tuple[Rect, ...] = ()
    align: str = "left"               # 原文的对齐：left / right / center（译文照样对齐）
    ink: Rect | None = None           # 原文墨迹的范围（相对原文块左上角）
    label: bool = False               # 界面上的短标签：译文不折行（放不下先缩小、压扁，再不行就截断）
    grad: tuple | None = None         # 底板上下渐变：(上沿颜色, 下沿颜色)，按原文块的上下边画


@dataclass(frozen=True)
class Snapshot:
    items: tuple[DrawItem, ...]
    pending: tuple[tuple[Rect, tuple[Rect, ...]], ...]   # 已识别、译文还没好（或失败）的块：显示等待提示用
    status: dict
    stamp: float
