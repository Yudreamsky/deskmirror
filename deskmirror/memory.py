"""译文记忆：

1. 数字模板（总是开着，只在内存里）：只有数字不同的文字（计时器、进度、血量、“3 天前”）套用已有译文，
   把数字换成新的，不再请求翻译服务。只有译文里按顺序原样出现了原文的每个数字，才记成模板；
   “1 day ago / 2 days ago”这种单复数不同的，原文模板本身就不同，不会混用。
2. 本地记忆（用户在设置里主动打开才用，默认关）：译文用当前 Windows 账户加密（DPAPI）存在本机，
   重启后相同的文字直接出译文。文件和配置放在一起，可随时清空。
"""
from __future__ import annotations

import collections
import json
import logging
import re
import time
import zlib
from pathlib import Path

from . import winapi

log = logging.getLogger(__name__)

# 数字：整数、小数、带千分位、时间 12:30、日期 2026-10-05、分数 120/150；前后不能紧挨着字母或数字
#（排除 v2、H2O、12m 这类和字母连在一起的）
_NUM = re.compile(r"(?<![A-Za-z\d])\d+(?:[.,:/\-]\d+)*(?![A-Za-z\d])")
_SLOT = "⟦{}⟧"          # ⟦0⟧：译文模板里的数字位置（正常文字里几乎不会出现）


def number_template(text: str) -> tuple[str, list[str]] | None:
    """把文字里的数字换成 # 得到模板；没有数字或几乎全是数字时返回 None（没有可套用的文字部分）。"""
    nums = _NUM.findall(text)
    if not nums:
        return None
    tmpl = _NUM.sub("#", text)
    if sum(ch.isalpha() for ch in tmpl) < 2:
        return None
    return tmpl, nums


def learn_template(src: str, translation: str) -> str | None:
    """原文和译文 → 译文模板（数字换成 ⟦i⟧）。译文里必须按顺序原样出现原文的每个数字，否则不学。"""
    t = number_template(src)
    if t is None:
        return None
    _tmpl, nums = t
    out, pos = [], 0
    for i, n in enumerate(nums):
        j = translation.find(n, pos)
        if j < 0:
            return None
        out.append(translation[pos:j])
        out.append(_SLOT.format(i))
        pos = j + len(n)
    out.append(translation[pos:])
    return "".join(out)


def fill_template(tmpl_translation: str, nums: list[str]) -> str | None:
    out = tmpl_translation
    for i, n in enumerate(nums):
        slot = _SLOT.format(i)
        if slot not in out:
            return None
        out = out.replace(slot, n)
    if "⟦" in out:
        return None
    return out


class TemplateCache:
    """数字模板缓存（只在内存里）：模板原文的缓存键 → 译文模板。"""

    def __init__(self, limit: int = 5000) -> None:
        self.limit = limit
        self._d: collections.OrderedDict[str, str] = collections.OrderedDict()

    def learn(self, key_of, src: str, translation: str) -> None:
        t = number_template(src)
        if t is None:
            return
        tt = learn_template(src, translation)
        if tt is None:
            return
        k = key_of(t[0])
        self._d[k] = tt
        self._d.move_to_end(k)
        while len(self._d) > self.limit:
            self._d.popitem(last=False)

    def lookup(self, key_of, src: str) -> str | None:
        t = number_template(src)
        if t is None:
            return None
        tt = self._d.get(key_of(t[0]))
        if tt is None:
            return None
        return fill_template(tt, t[1])

    def clear(self) -> None:
        self._d.clear()

    def __len__(self) -> int:
        return len(self._d)


class Memory:
    """本地记忆：按目标语言分开，缓存键 → 译文。加密后整体存成一个文件。"""

    VERSION = 1

    def __init__(self, path: Path, limit: int = 50000) -> None:
        self.path = path
        self.limit = limit
        self._d: dict[str, collections.OrderedDict[str, str]] = {}
        self.dirty = False
        self.last_save = time.perf_counter()

    def load(self) -> int:
        try:
            raw = self.path.read_bytes()
        except OSError:
            return 0
        try:
            data = json.loads(zlib.decompress(winapi.unprotect_bytes(raw)).decode("utf-8"))
        except (OSError, ValueError, zlib.error):
            log.warning("译文记忆文件读不出来（可能换了 Windows 账户），本次从空的开始")
            return 0
        if not isinstance(data, dict) or data.get("v") != self.VERSION:
            return 0
        for lang, items in (data.get("langs") or {}).items():
            if isinstance(items, dict):
                self._d[lang] = collections.OrderedDict((str(k), str(v)) for k, v in items.items())
        return self.count()

    def save(self) -> None:
        if not self.dirty:
            return
        data = {"v": self.VERSION, "langs": {lang: dict(d) for lang, d in self._d.items()}}
        blob = winapi.protect_bytes(zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"), 6))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(self.path)
        self.dirty = False
        self.last_save = time.perf_counter()

    def get(self, lang: str, key: str) -> str | None:
        d = self._d.get(lang)
        if d is None:
            return None
        v = d.get(key)
        if v is not None:
            d.move_to_end(key)
        return v

    def put(self, lang: str, key: str, translation: str) -> None:
        d = self._d.setdefault(lang, collections.OrderedDict())
        if d.get(key) == translation:
            return
        d[key] = translation
        d.move_to_end(key)
        while len(d) > self.limit:
            d.popitem(last=False)
        self.dirty = True

    def count(self) -> int:
        return sum(len(d) for d in self._d.values())

    def drop(self, match) -> int:
        """删掉原文（缓存键）满足 match 的记忆：术语表改了，含这些词的旧译文作废。"""
        n = 0
        for d in self._d.values():
            for k in [k for k in d if match(k)]:
                del d[k]
                n += 1
        if n:
            self.dirty = True
        return n

    def clear(self) -> None:
        self._d.clear()
        self.dirty = False
        try:
            self.path.unlink()
        except OSError:
            pass
