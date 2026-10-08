"""用量日志：每次翻译请求记一行 JSON（logs/usage-年-月.jsonl），排查“token 花在哪了”。

只记数量和程序名，不记任何屏幕文字、窗口标题和译文：
    {"t": "2026-10-07T20:18:10", "host": "api.deepseek.com", "model": "deepseek-chat", "app": "chrome.exe",
     "segments": 1, "chars": 6, "refs": 0, "dialog": 0, "dynamic": false,
     "in": 440, "out": 7, "cached": 384, "exact": true, "secs": 1.8}

python -m deskmirror usage --log 汇总这份日志（按程序、按批大小、缓存命中率）。
"""
from __future__ import annotations

import collections
import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from . import ROOT

log = logging.getLogger(__name__)
_lock = threading.Lock()
# 每次请求都带的固定说明大约这么多 token：一批的字少到这个份上，钱主要花在说明上
OVERHEAD_TOKENS = 430


def log_dir() -> Path:
    return ROOT / "logs"


def host_of(base_url: str) -> str:
    return urlparse(base_url.strip() if "://" in base_url else "http://" + base_url.strip()).hostname or base_url


def write(**rec) -> None:
    """追加一条（写不进去就算了，不影响翻译）。"""
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    rec["in"], rec["out"] = rec.pop("tokens_in", 0), rec.pop("tokens_out", 0)
    rec["secs"] = round(float(rec.get("secs", 0.0)), 2)
    path = log_dir() / time.strftime("usage-%Y-%m.jsonl")
    try:
        with _lock:
            path.parent.mkdir(exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.debug("写用量日志失败：%s", e)


def read(day: str = "") -> list[dict]:
    """某一天（YYYY-MM-DD，空 = 今天）的记录。"""
    day = day or time.strftime("%Y-%m-%d")
    path = log_dir() / f"usage-{day[:7]}.jsonl"
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and str(r.get("t", "")).startswith(day):
            out.append(r)
    return out


def summarize(recs: list[dict]) -> dict:
    """汇总：总量、缓存命中率、按程序、按批大小（字数）、按小时。"""
    def bucket(chars: int) -> str:
        return "<50" if chars < 50 else "50-199" if chars < 200 else "200-499" if chars < 500 else "500+"

    tot = collections.Counter()
    by_app: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_size: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_hour: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in recs:
        c = collections.Counter(requests=1, chars=int(r.get("chars", 0)), tokens_in=int(r.get("in", 0)),
                                tokens_out=int(r.get("out", 0)), cached=int(r.get("cached", 0)),
                                dynamic=int(bool(r.get("dynamic"))))
        tot.update(c)
        by_app[r.get("app") or "(desktop)"].update(c)
        by_size[bucket(int(r.get("chars", 0)))].update(c)
        by_hour[str(r.get("t", ""))[11:13] or "?"].update(c)
    n = tot["requests"]
    return {
        "requests": n, "chars": tot["chars"], "tokens_in": tot["tokens_in"], "tokens_out": tot["tokens_out"],
        "cached": tot["cached"], "dynamic_requests": tot["dynamic"],
        "cache_hit_rate": round(tot["cached"] / tot["tokens_in"], 3) if tot["tokens_in"] else 0.0,
        "avg_in_per_request": round(tot["tokens_in"] / n) if n else 0,
        "avg_chars_per_request": round(tot["chars"] / n) if n else 0,
        # 固定说明大约占了输入的多少：批越小越高
        "overhead_share": round(min(1.0, OVERHEAD_TOKENS * n / tot["tokens_in"]), 3) if tot["tokens_in"] else 0.0,
        "by_app": {k: dict(v) for k, v in sorted(by_app.items(), key=lambda kv: -kv[1]["tokens_in"])},
        "by_batch_chars": {k: dict(by_size[k]) for k in ("<50", "50-199", "200-499", "500+") if k in by_size},
        "by_hour": {k: dict(v) for k, v in sorted(by_hour.items())},
    }
