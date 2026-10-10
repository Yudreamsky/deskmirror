"""输入框翻译的规则（不碰窗口、不联网，方便测）：什么时候算“连按三次空格”、框里的字怎么分段、记着的原文和译文怎么来回换。

照浏览器版 0.6.0 / 0.7.1（extension/content/field.js）：
- 每两下空格之间不超过 0.5 秒；按住不放的自动连发不算；带 Ctrl、Alt、Shift、Win 的空格不算；按了别的键、换了窗口重新数。
- 三个空格前面要有字，而且不在行首（行首连按空格多半是在缩进）；输入法拿空格选字时框里不会多出三个空格，
  所以触发后还要读一下框里的字，确认真的以三个空格（半角、不换行空格或全角空格）结尾。
- 输入框里打的一定是母语（用户定的），请求里直接说明原文是什么语言。
- 最近 20 对原文和译文只放在内存里：框里是记着的译文 → 换回原文；是记着的原文、目标语言没变、上次译全了 →
  直接换成译文，不发请求；都不是 → 当新写的，重新翻译。比较时去掉零宽字符、把连续空白并成一个。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

GAP = 0.5               # 两下空格之间最多隔多久（秒）
MAX_CHARS = 4000        # 框里的字超过这么多就不翻（聊天、评论框用不了这么多；多半是在文档、代码里）
MEMO_SIZE = 20

_TRIPLE = re.compile(r"[ \u00a0\u3000]{3}$")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff]")
_SPACES = re.compile(r"\s+")
_LEAD = re.compile(r"^[ \t\u00a0\u3000]*")
_TAIL = re.compile(r"[ \t\n\u00a0\u3000]+$")


def norm(s: str) -> str:
    """比较用：去掉零宽字符，连续的空白并成一个（编辑器会改空白、换行）。"""
    return _SPACES.sub(" ", _ZERO_WIDTH.sub("", s)).strip()


def default_target(native: str) -> str:
    """输入框翻译成什么（设置里没选时）：母语是英文就译成简体中文，否则译成英文。"""
    return "zh-Hans" if native == "en" else "en"


def source_of(native: str) -> str:
    """母语（译文语言的代码）→ 告诉模型原文是什么语言用的代码。"""
    return "zh" if native.startswith("zh") else native


def body_of(text: str) -> str | None:
    """连按三次空格触发时：框里的字去掉末尾三个空格；不该翻（没以三个空格结尾、空的、在行首缩进）返回 None。"""
    if not _TRIPLE.search(text):
        return None
    body = text[:-3]
    if not body.strip() or not body.split("\n")[-1].strip():
        return None
    return body


def strip_tail(text: str) -> str:
    """按快捷键触发时：去掉末尾的空白（包括之前连按的空格）。"""
    return _TAIL.sub("", text)


def split_lines(body: str) -> tuple[list[str], list[int], list[str]]:
    """按行分段：(所有行, 有字的行号, 要翻的段)。空行原样留着，每行开头的缩进留着。"""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    at = [i for i, line in enumerate(lines) if line.strip()]
    return lines, at, [lines[i].strip() for i in at]


def join_lines(lines: list[str], at: list[int], out: list[str | None]) -> tuple[str, bool]:
    """把译文放回各行（缩进照旧）；返回 (整段译文, 是不是每段都译出来了)。没译出来的段保留原文。"""
    res = list(lines)
    full = True
    for k, i in enumerate(at):
        t = out[k] if k < len(out) else None
        if t is None or not t.strip():
            full = False
            continue
        res[i] = _LEAD.match(lines[i]).group(0) + t.strip()
    return "\n".join(res), full


@dataclass
class _Pair:
    orig: str
    trans: str
    key: str                    # 原文语言>目标语言
    full: bool                  # 每段都译出来了（没译全的下次重翻）
    o: set[str] = field(default_factory=set)      # 认作原文的样子（规范化后）
    t: set[str] = field(default_factory=set)      # 认作译文的样子


class Memo:
    """最近 20 对原文和译文（只在内存里），再连按三次空格来回换。"""

    def __init__(self) -> None:
        self.pairs: list[_Pair] = []

    def find(self, body: str, key: str) -> tuple[_Pair, bool] | None:
        """框里是记着的译文 → (那一对, True 换回原文)；是记着的原文、方向没变、上次译全了 → (那一对, False 换成译文)。"""
        n = norm(body)
        for p in self.pairs:
            if n in p.t:
                return p, True
            if p.key == key and p.full and n in p.o:
                return p, False
        return None

    def add(self, orig: str, trans: str, key: str, full: bool) -> _Pair:
        p = _Pair(orig, trans, key, full, {norm(orig)}, {norm(trans)})
        self.pairs.insert(0, p)
        del self.pairs[MEMO_SIZE:]
        return p

    def seen(self, p: _Pair, back: bool, written: str) -> None:
        """写进去以后读回来的样子也记下（编辑器会改空白、换行），并把这一对挪到最前面。"""
        if written:
            (p.o if back else p.t).add(norm(written))
        if p in self.pairs:
            self.pairs.remove(p)
        self.pairs.insert(0, p)


class Taps:
    """数连按的空格（由听键盘的线程调用）：最近三下都连着就返回 True。按第四下也算：输入法拿第一下空格选字时，
    框里只多了两个空格，用户自然会再按一下。"""

    def __init__(self, gap: float = GAP) -> None:
        self.gap = gap
        self._taps: list[float] = []
        self._down = False
        self._window = 0

    def space(self, t: float, window: int, modifiers: bool) -> bool:
        if self._down:                    # 按住不放的自动连发：不算，也不打断
            return False
        self._down = True
        if modifiers:
            self._taps = []
            return False
        if window != self._window or (self._taps and t - self._taps[-1] > self.gap):
            self._taps = []
        self._window = window
        self._taps = self._taps[-2:] + [t]
        return len(self._taps) == 3

    def space_up(self) -> None:
        self._down = False

    def other(self) -> None:
        """按了别的键（打字、退格、方向键……）：重新数。"""
        self._taps = []
