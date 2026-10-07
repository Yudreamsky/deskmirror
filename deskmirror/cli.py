"""命令行：不开界面就能查看和修改全部设置、测试服务、看用量、更新。给人用，也给 AI 助手（agent）用。

    python -m deskmirror config list            所有设置（API Key 只显示有没有填）
    python -m deskmirror config get llm.model
    python -m deskmirror config set llm.model deepseek-chat
    python -m deskmirror config set llm.api_key -          API Key 从标准输入读（不留在命令行历史里）
    python -m deskmirror config set llm.api_key --env DEEPSEEK_API_KEY
    python -m deskmirror config reset guard.daily_tokens  恢复默认
    python -m deskmirror config schema          每一项的类型、默认值、说明（JSON）
    python -m deskmirror models [--vision]      服务商现有的模型
    python -m deskmirror test                   发一句短文测试翻译服务
    python -m deskmirror usage                  今天的请求数、字数、token
    python -m deskmirror usage --log [日期]     按每次请求的日志汇总：哪个程序、多大的批、缓存命中多少
    python -m deskmirror status                 版本、配置文件位置、魔镜是不是正在运行
    python -m deskmirror update [--check]       检查 / 安装新版本（源码版）

加 --json 输出机器好读的 JSON。正在运行的魔镜一秒内就会读到改过的配置，不用重启
（识别设备、屏幕范围、滚动跟随除外）。输出用英文，方便各种 agent 读；不会打印 API Key。
"""
from __future__ import annotations

import argparse
import ast
import copy
import ctypes
import json
import os
import sys
from dataclasses import MISSING, fields, is_dataclass

from . import __version__, config

SECRETS = {"llm.api_key", "vision.api_key"}
# 程序自己记的状态：可以看，不让改（改了也会被运行中的魔镜盖掉）
READONLY = {"usage", "update.last_check", "first_run_tip"}

# 给 agent 看的说明（英文）。没写的项看 config.py 里的注释。
HELP = {
    "source_lang": "Source language: " + ", ".join(config.SOURCE_LANGS),
    "target_lang": "Translate into: " + ", ".join(config.LANGUAGES),
    "ui_lang": "Interface language: zh / en ('' = guess from Windows)",
    "mirror_rect": "Main mirror rectangle [left, top, right, bottom] in physical pixels",
    "extra_mirrors": "Extra mirrors (up to 3), each [left, top, right, bottom]",
    "llm.protocol": "ollama (native Ollama API) or openai (any OpenAI-compatible /chat/completions)",
    "llm.base_url": "Service URL, e.g. https://api.deepseek.com or http://127.0.0.1:11434",
    "llm.model": "Model name; list them with: python -m deskmirror models",
    "llm.api_key": "API key (stored encrypted with Windows DPAPI). Set with '-' to read stdin, or --env VAR",
    "llm.concurrency": "Parallel requests (1-8)",
    "llm.disable_thinking": "Turn off model 'thinking' (faster, cheaper)",
    "llm.consistency": "Send earlier translations as reference so terms stay consistent (~15% more tokens)",
    "scope.mode": "What gets pre-translated: " + ", ".join(config.SCOPE_MODES) + " (screen costs the most)",
    "scope.near_px": "For scope.mode=near: how far around the mirror",
    "scope.exclude_apps": "Programs never captured or translated (process names)",
    "scope.exclude_titles": "Windows whose title contains any of these are never translated",
    "scope.translate_chat": "Also translate chat apps in the exclude list",
    "memory.enabled": "Remember translations on disk (encrypted)",
    "guard.idle_min": "Minutes without keyboard/mouse input before only the mirror is translated (0 = off)",
    "guard.pause_when_locked": "Stop completely while the screen is locked or the screensaver runs",
    "guard.daily_tokens": "Daily token cap for cloud services, input + output (0 = unlimited)",
    "guard.show_meter": "Show today's token usage on the mirror tab",
    "update.auto_check": "Check GitHub for a new version once a day",
    "glossary": 'Required translations: JSON list of {"src": ..., "dst": ..., "app": ""}',
    "vision.protocol": "Vision model API for 'look' translation: ollama or openai",
}


# ---------------------------------------------------------------- 配置项
def _flatten(obj, prefix: str = "") -> dict:
    out = {}
    for f in fields(obj):
        v = getattr(obj, f.name)
        key = prefix + f.name
        if is_dataclass(v):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _default_of(key: str):
    return _flatten(config.AppConfig())[key]


def _show(key: str, value):
    if key in SECRETS:
        return "(set)" if value else ""
    return value


def _parse(key: str, raw: str, current):
    """命令行上的字符串 → 和默认值同类型的值。"""
    if isinstance(current, bool):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{key} expects true/false")
    if isinstance(current, int):
        return int(raw.replace("_", "").replace(",", ""))
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        raw = raw.strip()
        if raw.startswith("["):
            try:
                v = json.loads(raw)
            except ValueError:
                v = ast.literal_eval(raw)
            if not isinstance(v, list):
                raise ValueError(f"{key} expects a JSON list")
            return v
        return [x.strip() for x in raw.split(",") if x.strip()]
    return raw


def _set(cfg: config.AppConfig, key: str, value) -> None:
    *path, name = key.split(".")
    obj = cfg
    for p in path:
        obj = getattr(obj, p)
    setattr(obj, name, value)


def _get(cfg: config.AppConfig, key: str):
    obj = cfg
    for p in key.split("."):
        obj = getattr(obj, p)
    return obj


def _check_key(key: str, flat: dict) -> None:
    if key not in flat:
        near = [k for k in flat if key.split(".")[-1] in k][:5]
        raise SystemExit(f"error: unknown setting '{key}'" + (f" (did you mean: {', '.join(near)}?)" if near else "")
                         + "\nsee: python -m deskmirror config list")


def _writable(key: str) -> bool:
    return not any(key == r or key.startswith(r + ".") for r in READONLY)


# ---------------------------------------------------------------- 输出
def _out(args, data, text: str | None = None) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(text if text is not None else (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False,
                                                                                            indent=2)))


def _running() -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = ctypes.c_void_p
    k32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
    h = k32.OpenMutexW(0x00100000, False, "Local\\DeskMirror.Instance")
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


def _note_running() -> str:
    return ("DeskMirror is running and picks up the change within a second." if _running()
            else "DeskMirror is not running; the change applies on next start.")


# ---------------------------------------------------------------- 各命令
def cmd_config(args) -> int:
    cfg = config.load()
    flat = _flatten(cfg)
    if args.action == "path":
        _out(args, {"path": str(config.config_path())}, str(config.config_path()))
        return 0
    if args.action == "list":
        data = {k: _show(k, v) for k, v in flat.items()}
        if args.json:
            _out(args, data)
        else:
            for k, v in data.items():
                print(f"{k} = {json.dumps(v, ensure_ascii=False)}")
        return 0
    if args.action == "schema":
        defaults = _flatten(config.AppConfig())
        data = [{"key": k, "type": type(defaults[k]).__name__, "default": _show(k, defaults[k]),
                 "value": _show(k, v), "writable": _writable(k), "help": HELP.get(k, "")}
                for k, v in flat.items()]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not args.key:
        raise SystemExit(f"error: config {args.action} needs a KEY")
    key = args.key
    _check_key(key, flat)
    if args.action == "get":
        _out(args, {"key": key, "value": _show(key, flat[key])}, json.dumps(_show(key, flat[key]), ensure_ascii=False))
        return 0
    if not _writable(key):
        raise SystemExit(f"error: {key} is kept by DeskMirror itself and can't be set")
    if args.action == "reset":
        value = copy.deepcopy(_default_of(key))
    else:
        if args.env:
            raw = os.environ.get(args.env)
            if raw is None:
                raise SystemExit(f"error: environment variable {args.env} is not set")
        elif args.value == "-" or (args.value is None and key in SECRETS):
            raw = sys.stdin.readline().rstrip("\r\n")
        elif args.value is None:
            raise SystemExit("error: config set needs a VALUE (use '-' to read it from stdin)")
        else:
            raw = args.value
        try:
            value = _parse(key, raw, _default_of(key))
        except (ValueError, SyntaxError) as e:
            raise SystemExit(f"error: {e}") from None
    _set(cfg, key, value)
    cfg = config.validate(cfg)
    final = _get(cfg, key)
    config.save(cfg)
    adjusted = final != value
    data = {"ok": True, "key": key, "value": _show(key, final), "adjusted": adjusted, "running": _running()}
    msg = f"{key} = {json.dumps(_show(key, final), ensure_ascii=False)}"
    if adjusted:
        msg += f"  (adjusted from {json.dumps(_show(key, value), ensure_ascii=False)} to the allowed range)"
    _out(args, data, msg + "\n" + _note_running())
    return 0


def cmd_models(args) -> int:
    from .translator import list_models
    cfg = config.load()
    llm = cfg.vision if args.vision else cfg.llm
    probe = config.LlmConfig(protocol=llm.protocol, base_url=llm.base_url, api_key=llm.api_key)
    names, err = list_models(probe)
    _out(args, {"models": names, "current": llm.model, "error": err},
         "\n".join(("* " if n == llm.model else "  ") + n for n in names) if names else f"error: {err}")
    return 0 if names else 1


def cmd_test(args) -> int:
    from .translator import test_connection
    cfg = config.load()
    ok, msg = test_connection(cfg.llm, cfg.target_lang)
    _out(args, {"ok": ok, "message": msg, "base_url": cfg.llm.base_url, "model": cfg.llm.model},
         ("OK: " if ok else "FAILED: ") + msg)
    return 0 if ok else 1


def cmd_usage(args) -> int:
    if args.log is not None:
        return _usage_log(args)
    cfg = config.load()
    u, g = cfg.usage, cfg.guard
    data = {"date": u.date, "requests": u.requests, "chars": u.chars, "tokens_in": u.tokens_in,
            "tokens_out": u.tokens_out, "tokens_cached": u.tokens_cached, "estimated": u.estimated, "daily_tokens_limit": g.daily_tokens,
            "local_service": config.is_local_url(cfg.llm.base_url), "running": _running()}
    text = (f"{u.date or '-'}: {u.requests} requests, {u.chars} chars, "
            f"in {u.tokens_in:,} (cached {u.tokens_cached:,}) / out {u.tokens_out:,} tokens{' (partly estimated)' if u.estimated else ''}")
    text += f"\ndaily cap: {g.daily_tokens:,} tokens" if g.daily_tokens else "\ndaily cap: unlimited"
    if data["running"]:
        text += "\n(DeskMirror is running: it saves usage every 5 minutes, so this may lag a little)"
    _out(args, data, text)
    return 0


def _usage_log(args) -> int:
    """按每次请求的日志（logs/usage-年-月.jsonl）汇总一天：钱花在哪个程序、多大的批、缓存命中多少。"""
    from . import usagelog
    recs = usagelog.read(args.log)
    s = usagelog.summarize(recs)
    s["day"] = args.log or __import__("time").strftime("%Y-%m-%d")
    if args.tail:
        s["last"] = recs[-args.tail:]
    if args.json:
        _out(args, s)
        return 0
    if not recs:
        print(f"no requests logged for {s['day']} (log: {usagelog.log_dir()})")
        return 0
    print(f"{s['day']}: {s['requests']} requests, in {s['tokens_in']:,} (cached {s['cached']:,} = "
          f"{s['cache_hit_rate']:.0%}) / out {s['tokens_out']:,} tokens")
    print(f"average request: {s['avg_chars_per_request']} chars of text, {s['avg_in_per_request']} input tokens; "
          f"the fixed instructions (~{usagelog.OVERHEAD_TOKENS} tokens/request) are ~{s['overhead_share']:.0%} "
          "of input")
    print("\nby program:")
    for app, c in list(s["by_app"].items())[:10]:
        print(f"  {app:<28} {c['requests']:>5} req  in {c['tokens_in']:>9,}  out {c['tokens_out']:>8,}")
    print("\nby batch size (chars of text per request):")
    for k, c in s["by_batch_chars"].items():
        print(f"  {k:<8} {c['requests']:>5} req  in {c['tokens_in']:>9,}  out {c['tokens_out']:>8,}")
    print("\nby hour:")
    for h, c in s["by_hour"].items():
        print(f"  {h}:00  {c['requests']:>5} req  in {c['tokens_in']:>9,}  out {c['tokens_out']:>8,}")
    for r in s.get("last", []):
        print(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_status(args) -> int:
    from . import updater
    data = {"version": __version__, "config": str(config.config_path()), "running": _running(),
            "install": "git" if updater.is_git_checkout() else ("exe" if getattr(sys, "frozen", False) else "source")}
    _out(args, data, "\n".join(f"{k}: {v}" for k, v in data.items()))
    return 0


def cmd_update(args) -> int:
    from . import updater
    info = updater.check()
    if args.check or info.error or not info.newer:
        text = info.error or (("update available: " + (f"{info.behind} new commit(s)" if info.kind == "git"
                                                         else f"{info.current} -> {info.latest}"))
                              if info.newer else f"up to date ({info.current})")
        if info.commits:
            text += "\n" + "\n".join("  - " + c for c in info.commits)
        _out(args, info.as_dict(), text)
        return 1 if info.error else 0
    if info.kind != "git":
        _out(args, {**info.as_dict(), "download": updater.RELEASES_PAGE},
             f"new version {info.latest}: download it from {updater.RELEASES_PAGE} and unzip over the old folder")
        return 0
    ok, msg = updater.apply_git()
    running = _running()
    _out(args, {"ok": ok, "message": msg, "running": running},
         msg + ("\nRestart DeskMirror to use the new version (tray icon -> Exit, then start.bat)." if ok and running
                else ""))
    return 0 if ok else 1


def _attach_console() -> None:
    """打包成窗口程序（没有控制台）时，把输出接到启动它的命令行窗口上。"""
    if sys.stdout is not None:
        return
    if ctypes.WinDLL("kernel32").AttachConsole(-1):
        sys.stdout = open("CONOUT$", "w", encoding="utf-8")     # noqa: SIM115
        sys.stderr = sys.stdout


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m deskmirror",
                                description="DeskMirror command line: view and change every setting, test the "
                                            "translation service, check usage and update. Run without arguments "
                                            "to start the app.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config", help="list / get / set / reset settings")
    c.add_argument("action", choices=["list", "get", "set", "reset", "schema", "path"])
    c.add_argument("key", nargs="?")
    c.add_argument("value", nargs="?")
    c.add_argument("--env", help="config set: read the value from this environment variable (for API keys)")
    m = sub.add_parser("models", help="list the models the configured service offers")
    m.add_argument("--vision", action="store_true", help="the 'look' (vision) service instead")
    sub.add_parser("test", help="send a short test translation")
    us = sub.add_parser("usage", help="today's requests, characters and tokens")
    us.add_argument("--log", nargs="?", const="", metavar="YYYY-MM-DD",
                    help="summarize the per-request usage log for a day (default today): by program, batch size, "
                         "hour, cache hits")
    us.add_argument("--tail", type=int, default=0, help="with --log: also print the last N requests")
    sub.add_parser("status", help="version, config file, whether DeskMirror is running")
    u = sub.add_parser("update", help="check for / install a new version")
    u.add_argument("--check", action="store_true", help="only check")
    for sp in sub.choices.values():
        sp.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str]) -> int:
    _attach_console()
    try:
        sys.stdout.reconfigure(encoding="utf-8")     # 中文模型名、错误说明在 GBK 控制台上也不乱码
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    from . import i18n
    i18n.set_ui_lang(config.load().ui_lang or "en")
    return {"config": cmd_config, "models": cmd_models, "test": cmd_test, "usage": cmd_usage,
            "status": cmd_status, "update": cmd_update}[args.cmd](args)
