"""术语前后一致：同一个窗口里已经译过的段落，挑几段含有同样关键词的，作为参考和新的一批一起发给模型，
让同一个词沿用同样的译法（比如 Employer 前面译成“业主”，后面不会变成“雇主”）。

用户的术语表优先；这里管的是没写进术语表的词。只在内存里，退出即清空。
只参考同一个窗口或同一个程序里译过的文字：游戏里的 Engineer 不会带偏投标文件里的 Engineer。
"""
from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass

# 常见虚词和泛用词：不算“术语”，也不作为挑参考的理由
_STOP = frozenset("""
a about above accordance according after again against all along also although am among an and another any are
around as at available be because been before being below between both but by can cannot click could did do does
doing done down due during each either else ensure every example few following for from further had has have having
he her here hers him his how however i if in including information into is it its itself just less made make many
may me might more most must my near need neither no nor not now of off on once one only onto or other others our out
over own per please provide provided regarding related relevant required respect same shall she should since so some
such than that the their them then there these they this those though through thus to too toward under unless until
up upon us used using very via was we were what when where whether which while who whom whose why will with within
without would yet you your
""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]|[A-Z]{2,}")
_HAN_KANA = re.compile(r"[゠-ヿ㐀-䶿一-鿿]{2,}")   # 汉字、片假名（不含平假名）
_HANGUL = re.compile(r"[가-힯]{2,}")


def _stem(w: str) -> str:
    """复数还原成单数（purlins → purlin），两种写法能对上。"""
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w


def key_terms(text: str) -> frozenset[str]:
    """文字里可能是术语的词：
    - 英文实词（小写、复数还原）；句中首字母大写的另记一个“!词”（the Engineer：合同里的定义词、专有名词）；
    - 大写缩写（EPC、BOQ）；相邻的首字母大写词组（performance security）；
    - 汉字和片假名按相邻两字，韩文按词。"""
    out: set[str] = set()
    prev = ""
    for m in _WORD.finditer(text):
        w = m.group()
        lw = _stem(w.lower())
        if len(w) >= 2 and w.isupper():
            out.add(w)
        elif len(lw) >= 4 and lw not in _STOP:
            out.add(lw)
            before = text[:m.start()].rstrip()
            if w[0].isupper() and before and (before[-1].isalnum() or before[-1] in ",-"):
                out.add("!" + lw)
        cap = w[0].isupper() and lw not in _STOP
        if cap and prev:
            out.add(prev + " " + lw)
        prev = lw if cap else ""
    for run in _HAN_KANA.findall(text):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    out.update(_HANGUL.findall(text))
    return frozenset(out)


@dataclass(eq=False)
class _Ref:
    src: str
    tr: str
    hwnd: int
    app: str
    terms: frozenset[str]


class RefHistory:
    """译过的段落（原文的缓存键 → 原文、译文、所在窗口和程序、关键词）。"""

    def __init__(self, limit: int = 3000) -> None:
        self.limit = limit
        self._d: collections.OrderedDict[str, _Ref] = collections.OrderedDict()

    def __len__(self) -> int:
        return len(self._d)

    def add(self, key: str, src: str, tr: str, hwnd: int, app: str) -> None:
        terms = key_terms(src)
        if not terms:
            return
        self._d[key] = _Ref(src, tr, hwnd, app, terms)
        self._d.move_to_end(key)
        while len(self._d) > self.limit:
            self._d.popitem(last=False)

    def update(self, key: str, tr: str) -> None:
        """用户改了这段译文：以后参考改过的。"""
        r = self._d.get(key)
        if r is not None:
            r.tr = tr

    def drop(self, match) -> None:
        """删掉原文满足 match 的参考（术语表改了，含这些词的旧译法不能再当参考）。"""
        for k in [k for k, r in self._d.items() if match(r.src)]:
            del self._d[k]

    def select(self, texts: list[str], keys: list[str], hwnd: int, app: str,
               max_refs: int = 3, max_chars: int = 600) -> list[tuple[str, str]]:
        """给一批新文字挑参考：含有同样关键词、越少见的词越优先，同一个窗口的优先；短的优先，总长有上限。"""
        want = frozenset().union(*(key_terms(t) for t in texts)) if texts else frozenset()
        if not want:
            return []
        skip = set(keys)
        pool = [r for k, r in self._d.items() if k not in skip and (r.hwnd == hwnd or (app and r.app == app))]
        cands = [r for r in pool if r.terms & want]
        if not cands:
            return []
        # 词的分量：在这个窗口（程序）译过的段落里出现得越少越重；通篇都有的术语（Employer）照样算，它最需要前后一致。
        # 句中大写的词、词组、缩写像定义词和专有名词，一个就够附上参考；普通小写词要够少见才算。总分量要够 1。
        df: collections.Counter[str] = collections.Counter()
        for r in pool:
            df.update(r.terms & want)
        n = len(pool)
        weight = {t: (1 + math.log(n / c)) * (1.5 if t[0] == "!" or " " in t or t.isupper() else 0.6)
                  for t, c in df.items()}
        chosen: list[_Ref] = []
        covered: set[str] = set()
        used = 0
        while len(chosen) < max_refs:
            best, best_score = None, 0.0
            for r in cands:
                if r in chosen:
                    continue
                gain = sum(weight.get(t, 0.0) for t in (r.terms & want) - covered)
                size = len(r.src) + len(r.tr)
                if gain < 1.0 or used + size > max_chars:
                    continue
                score = gain * (1.5 if r.hwnd == hwnd else 1.0) / (1 + size / 300)
                if score > best_score:
                    best, best_score = r, score
            if best is None:
                break
            chosen.append(best)
            covered |= best.terms & want
            used += len(best.src) + len(best.tr)
        return [(r.src, r.tr) for r in chosen]
