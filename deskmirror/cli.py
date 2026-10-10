"""命令行：不打开界面就能看、改全部设置（AI 助手、脚本用），还能列出模型、测试翻译服务、管理术语表、看用量、更新。

    python -m deskmirror config list          （打包版：DeskMirrorCLI.exe config list）

改的是配置文件 deskmirror.json，正在运行的魔镜一秒内自动重新载入（少数几项要重启，会提示）。
加 --json 输出 JSON（只用 ASCII，任何代码页下都不乱码）。API Key 只显示前后几位；设置时值写成 -（从标准输入读）
或 --env 变量名（从环境变量读），不留在命令行和历史记录里。不开网络端口：能改这个文件的程序才能改设置。
"""
from __future__ import annotations

import copy
import ctypes
import difflib
import getpass
import json
import os
import re
import sys
import time
from dataclasses import fields, is_dataclass
from pathlib import Path

from . import __version__, autostart, config, i18n, keys
from .config import OPENAI_PRESETS, AppConfig, LlmConfig
from .i18n import N_, tr

SECRETS = ("llm.api_key", "vision.api_key")
RESTART = config.RESTART_KEYS
READONLY = {
    "mirror_rect": N_("魔镜的位置：拖魔镜来改"),
    "extra_mirrors": N_("另外开的魔镜：在魔镜标签上右键来开、关"),
    "docks": N_("收成球的魔镜：拖到屏幕边缘来收，点一下球或者拖出来展开"),
    "glossary": N_("术语表：用 glossary 命令改"),
    "usage": N_("当天用量：程序自己记"),
    "update.last_check": N_("上次自动检查更新的日期：程序自己记"),
}
DOCS = {
    "source_lang": N_("原文语言：auto = 自动识别；也可以指定（ko 会换用韩文识别模型）"),
    "target_lang": N_("译成的语言（你的母语）"),
    "ui_lang": N_("界面语言：zh、en；空着 = 按译成的语言自动选"),
    "first_run_tip": N_("启动时弹出新手指南（看完自动关掉）"),
    "llm.protocol": N_("翻译服务的接口：ollama = 本机 Ollama；openai = OpenAI 兼容接口（DeepSeek、通义千问、OpenAI 等）"),
    "llm.base_url": N_("翻译服务的地址，比如 https://api.deepseek.com、http://127.0.0.1:11434"),
    "llm.model": N_("翻译用的模型名（models 命令列出服务现有的模型）"),
    "llm.api_key": N_("翻译服务的 API Key（本机 Ollama 不用填）；用 Windows 账户加密存在本机"),
    "llm.temperature": N_("译文的随机程度，越低越稳定"),
    "llm.timeout_s": N_("一次翻译请求最多等多少秒"),
    "llm.concurrency": N_("同时发出的翻译请求数（本机 Ollama 用 1，云端服务 2～4）"),
    "llm.max_batch_chars": N_("一次请求最多合并多少字"),
    "llm.max_batch_items": N_("一次请求最多合并多少段文字"),
    "llm.disable_thinking": N_("关掉模型的“思考”（翻译用不着，更快）"),
    "llm.num_ctx": N_("Ollama 的上下文长度（和看图翻译用同一个模型时要一样）"),
    "llm.keep_alive": N_("Ollama 把模型留在显存里多久，比如 30m"),
    "llm.consistency": N_("术语前后一致：附上本窗口里含同样词语的已有译文作参考"),
    "llm.gather_ms": N_("已有请求在途时，零星的新文字最多等多少毫秒凑成一批再发（每次请求都带约 430 token 的固定说明）；"
                        "0 = 不等"),
    "ocr.device": N_("文字识别用显卡（gpu，DirectML）还是 cpu"),
    "ocr.threads": N_("用 CPU 识别时的线程数"),
    "hotkeys.drag_modifiers": N_("按住它在镜框里任意位置拖动就能移动魔镜，比如 Ctrl+Alt"),
    "hotkeys.peek": N_("按住看原文"),
    "hotkeys.refresh": N_("镜框内重新识别、重新翻译"),
    "hotkeys.toggle_visible": N_("隐藏 / 显示魔镜"),
    "hotkeys.history": N_("历史面板（回看刚才的字幕、对话）"),
    "hotkeys.vision": N_("看图翻译"),
    "hotkeys.input": N_("翻译正在打字的输入框，再按一次换回原文（打开输入框翻译时才有）"),
    "style.font_family": N_("译文的字体"),
    "style.min_font_px": N_("放不下时字最小缩到多少像素"),
    "style.min_scale": N_("放不下时最多缩到原字号的多少"),
    "style.min_squash": N_("放不下时最多横向压扁到原宽的多少"),
    "style.plate_opacity": N_("底板不透明度（1 = 完全盖住原文；Windows 10 上总是 1）"),
    "style.border_color": N_("魔镜边框的颜色，比如 #3D8BFD"),
    "track.stable_ms": N_("区域静止多久后才识别新文字（毫秒）"),
    "track.dynamic_ms": N_("视频、游戏画面多久抓拍识别一次（毫秒）"),
    "track.subtitle_hold_ms": N_("字幕换句时旧译文最多留多久（毫秒）"),
    "track.ring_px": N_("预先翻译时由近到远每一圈多宽（像素）"),
    "track.max_cache_blocks": N_("记住的文字块最多多少个"),
    "track.max_cache_texts": N_("内存里的译文缓存最多多少条"),
    "track.prefer_dxgi": N_("用 DXGI 截屏（更快；关掉改用 GDI）"),
    "track.all_monitors": N_("处理所有屏幕（默认只处理魔镜所在的屏幕）"),
    "track.wheel_predict": N_("滚动时用学到的滚轮曲线提前移动译文"),
    "track.display_lead_ms": N_("滚动预测的提前量（毫秒）"),
    "scope.mode": N_("预先翻译的范围：screen = 整块屏幕；window = 魔镜所在的窗口；near = 镜框附近"),
    "scope.near_px": N_("near 时镜框外多远以内也预先翻译（像素）"),
    "scope.exclude_apps": N_("不翻译的程序（exe 文件名，逗号分隔）"),
    "scope.exclude_titles": N_("窗口标题里带这些字就不翻译（逗号分隔）"),
    "scope.translate_chat": N_("聊天软件也翻译（默认不翻；密码管理器、网银始终不翻）"),
    "memory.enabled": N_("记住译文：加密存在本机，同样的文字下次直接用"),
    "vision.protocol": N_("看图翻译的接口：ollama 或 openai"),
    "vision.base_url": N_("看图翻译服务的地址"),
    "vision.model": N_("看图翻译用的模型（要能看图），比如 gemma4:12b"),
    "vision.api_key": N_("看图翻译服务的 API Key（本机 Ollama 不用填）"),
    "vision.timeout_s": N_("看图翻译最多等多少秒"),
    "vision.max_side": N_("发图前把长边缩到多少像素"),
    "vision.num_ctx": N_("Ollama 的上下文长度"),
    "guard.idle_min": N_("这么多分钟没碰键盘鼠标，就只翻镜框里的文字，不在后台预译别处（0 = 不管）"),
    "guard.pause_when_locked": N_("锁屏、屏保时完全停下（不截屏、不识别、不翻译）"),
    "guard.daily_tokens": N_("云端服务一天最多用多少 token（输入 + 输出），到了就停止翻译新文字；0 = 不限。本机服务不限"),
    "guard.show_meter": N_("魔镜标签上显示今天用掉的 token（↑ 输入 ↓ 输出）"),
    "update.auto_check": N_("启动后检查有没有新版本（一天最多一次，只访问 GitHub；有新版只提示）"),
    "input.enabled": N_("输入框翻译：在别的软件的输入框里打完母语，连按三次空格（或按 hotkeys.input），整个框换成"
                        "另一种语言，再按换回原文；要听键盘（只听空格），默认关"),
    "input.target": N_("输入框翻译成什么语言；空着 = 母语是英文时译成简体中文，否则译成英文"),
    "input.skip_apps": N_("输入框翻译不管的程序（exe 文件名，逗号分隔）；默认是浏览器（浏览器版自己会翻）、写代码的编辑器和命令行"),
    "update.skip_version": N_("自动检查时不再提示的版本号（检查更新窗口里点了“跳过这个版本”）"),
}
# 不在配置文件里的设置：开机自动启动存在 Windows 的启动项里（以它为准）
VIRTUAL = {"autostart": N_("开机时自动启动桌面魔镜（启动后收成球待命，点开或拖出来才开始识别）；"
                           "写在 Windows 的启动项里，不在配置文件里")}
# service 命令的服务名 → 预设（显示名、接口、地址、默认模型）；OpenAI 兼容的从 config.OPENAI_PRESETS 取
_PRESET_IDS = {"deepseek": "DeepSeek", "qwen": N_("通义千问（阿里云百炼）"), "siliconflow": N_("硅基流动"),
               "openai": "OpenAI", "ollama-openai": N_("Ollama（OpenAI 兼容）"), "lmstudio": N_("LM Studio（本地）")}
SERVICES = {"ollama": (N_("本机 Ollama"), "ollama", "http://127.0.0.1:11434", "gemma4:12b")}
SERVICES.update({sid: (name, "openai", *OPENAI_PRESETS[name]) for sid, name in _PRESET_IDS.items()})


class CliError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _prog() -> str:
    return "DeskMirrorCLI.exe" if getattr(sys, "frozen", False) else "python -m deskmirror"


def usage() -> str:
    return tr(
        "桌面魔镜命令行（{version}）：不打开界面就能看、改设置，改完正在运行的魔镜一秒内自动生效。\n\n"
        "  {p} config list                     全部设置\n"
        "  {p} config get 名字                  一项设置，比如 llm.model\n"
        "  {p} config set 名字 值 [名字 值…]     改设置；值写 - 从标准输入读，写 --env 变量名 从环境变量读\n"
        "                                        （API Key 这样传，不留在命令行里）\n"
        "  {p} config reset 名字                恢复默认值\n"
        "  {p} config keys                     每项设置的说明、能取的值（config schema：同样的内容，输出 JSON）\n"
        "  {p} config path                     配置文件在哪\n"
        "  {p} service [服务名]                 列出预设的翻译服务 / 换成其中一个（deepseek、qwen、openai、ollama…）\n"
        "  {p} models [--vision]               翻译服务（或看图翻译服务）现有的模型\n"
        "  {p} test                            试一下翻译服务能不能用（会翻译一句很短的话）\n"
        "  {p} glossary list | add 原文 译文 [--app 程序.exe] | remove 原文 [--app 程序.exe]\n"
        "  {p} usage [--log [日期]] [--tail N]   今天的请求数、字数、token；--log 按每次请求的日志汇总（哪个程序、\n"
        "                                        多大的批、命中缓存多少）\n"
        "  {p} status                          版本、配置文件在哪、魔镜在不在运行、能怎么更新\n"
        "  {p} update [--check] [--yes]        检查新版本 / 下载并换上新版本（正在运行的魔镜会自动退出、重新打开）\n"
        "  {p} version\n\n"
        "加 --json 输出 JSON（给程序、AI 助手读）。"
    ).format(version=__version__, p=_prog())


# ---------------------------------------------------------------------------------------------------- 设置项
def all_keys(obj: object | None = None, prefix: str = "") -> list[str]:
    """全部设置的名字（按配置文件里的顺序），包括只读的。"""
    obj = AppConfig() if obj is None else obj
    out = []
    for f in fields(obj):
        value = getattr(obj, f.name)
        out += all_keys(value, prefix + f.name + ".") if is_dataclass(value) else [prefix + f.name]
    return out


def _readonly(key: str) -> str:
    return READONLY.get(key) or READONLY.get(key.split(".")[0], "")


def settable_keys() -> list[str]:
    return [k for k in all_keys() if not _readonly(k)] + list(VIRTUAL)


def _value(cfg: AppConfig, key: str) -> object:
    if key == "autostart":
        return autostart.enabled()
    return config.get_key(cfg, key)


def _default(key: str) -> object:
    return False if key in VIRTUAL else config.get_key(AppConfig(), key)


def _check_key(key: str) -> None:
    if key in settable_keys():
        return
    why = _readonly(key)
    if why:
        raise CliError(tr("{key} 不能用命令改（{why}）").format(key=key, why=tr(why)))
    near = difflib.get_close_matches(key, settable_keys(), n=3)
    hint = tr("；是不是：{keys}").format(keys=", ".join(near)) if near else ""
    raise CliError(tr("没有这项设置：{key}{hint}（config keys 列出全部）").format(key=key, hint=hint))


def mask(secret: str) -> str:
    """API Key 只露出前 3 位和后 4 位。"""
    if not secret:
        return ""
    return f"{secret[:3]}…{secret[-4:]}" if len(secret) >= 12 else "…"


def _shown(key: str, value: object) -> object:
    """给人看、给 JSON 的值（API Key 遮住）。"""
    return mask(str(value)) if key in SECRETS else value


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _kind(default: object) -> str:
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "number"
    if isinstance(default, list):
        return "list"
    return "text"


def parse_value(key: str, raw: str) -> object:
    default = _default(key)
    s = raw.strip()
    kind = _kind(default)
    if kind == "bool":
        if s.lower() in ("true", "1", "yes", "on"):
            return True
        if s.lower() in ("false", "0", "no", "off"):
            return False
        raise CliError(tr("{key} 是开关，只能是 true 或 false").format(key=key))
    if kind in ("int", "number"):
        try:
            return int(s) if kind == "int" else float(s)
        except ValueError:
            raise CliError(tr("{key} 要填{what}").format(key=key, what=tr("整数") if kind == "int" else tr("数字")))
    if kind == "list":
        if s.startswith("["):
            try:
                value = json.loads(s)
            except ValueError:
                value = None
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                raise CliError(tr("{key} 要填 JSON 字符串数组，或者用逗号分隔").format(key=key))
            return value
        return [v.strip() for v in re.split(r"[,\n]", s.replace("，", ",")) if v.strip()]
    return s


def check_value(key: str, value: object) -> None:
    """格式检查（取值范围在 apply_value 里按 config.validate 查）。"""
    try:
        if key == "hotkeys.drag_modifiers":
            keys.parse_modifiers(str(value))
        elif key.startswith("hotkeys.") and value:
            keys.parse_hotkey(str(value))
    except ValueError as e:
        raise CliError(str(e))
    if key == "style.border_color" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(value)):
        raise CliError(tr("颜色要写成 #RRGGBB，比如 #3D8BFD"))
    if key.endswith(".base_url") and not str(value).startswith(("http://", "https://")):
        raise CliError(tr("地址要以 http:// 或 https:// 开头"))
    if key in ("llm.model", "vision.model") and not value:
        raise CliError(tr("模型名不能为空"))


def apply_value(cfg: AppConfig, key: str, value: object) -> None:
    """改一项设置；超出范围、不在可选值里就报错（不悄悄改成别的值）。"""
    check_value(key, value)
    trial = copy.deepcopy(cfg)
    config.set_key(trial, key, value)
    config.validate(trial)
    if config.get_key(trial, key) != value:
        if key in config.CHOICES:
            allowed = ", ".join(repr(v) if v == "" else v for v in config.CHOICES[key])
            raise CliError(tr("{key} 只能是：{allowed}").format(key=key, allowed=allowed))
        if key in config.RANGES:
            lo, hi = config.RANGES[key]
            raise CliError(tr("{key} 要在 {lo} 到 {hi} 之间").format(key=key, lo=lo, hi=hi))
        raise CliError(tr("{key} 不接受这个值").format(key=key))
    config.set_key(cfg, key, value)


def _read_secret(key: str) -> str:
    if sys.stdin is None:
        raise CliError(tr("没有标准输入，读不到 {key}").format(key=key))
    if sys.stdin.isatty():
        return getpass.getpass(tr("输入 {key}（输入时不显示）：").format(key=key))
    return sys.stdin.read().strip()


# ---------------------------------------------------------------------------------------------------- 输出
def _running() -> bool:
    """魔镜正在运行吗（看它启动时建的互斥量）。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    k32.OpenMutexW.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenMutexW(0x00100000, False, "Local\\DeskMirror.Instance")     # SYNCHRONIZE
    if h:
        k32.CloseHandle(h)
    return bool(h)


def _emit(as_json: bool, obj: dict, text: str) -> None:
    if as_json:
        print(json.dumps({"ok": True, **obj}, ensure_ascii=True))
    elif text:
        print(text)


def _saved(cfg: AppConfig, changed: list[str], as_json: bool, text: str) -> int:
    if any(k not in VIRTUAL for k in changed):
        config.save(cfg)
    running = _running()
    restart = sorted(k for k in changed if k in RESTART)
    notes = [tr("正在运行的魔镜一秒内会自动载入。") if running else tr("魔镜没在运行，下次启动时生效。")]
    if all(k in VIRTUAL for k in changed):
        notes = [tr("已写进 Windows 的启动项，下次开机生效。")]
    if restart and running:
        notes.append(tr("{keys} 要重启魔镜才生效。").format(keys=", ".join(restart)))
    _emit(as_json, {"changed": {k: _shown(k, _value(cfg, k)) for k in changed}, "running": running,
                    "restart_needed": restart}, text + "\n" + "".join(notes))
    return 0


# ---------------------------------------------------------------------------------------------------- 命令
def cmd_config(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    if not args:
        raise CliError(usage(), 2)
    sub, rest = args[0], args[1:]
    if sub == "path":
        _emit(as_json, {"path": str(config.config_path())}, str(config.config_path()))
        return 0
    if sub == "list":
        values = {k: _shown(k, _value(cfg, k)) for k in settable_keys()}
        _emit(as_json, {"path": str(config.config_path()), "settings": values},
              "\n".join(f"{k} = {_text(v)}" for k, v in values.items()))
        return 0
    if sub == "get":
        if len(rest) != 1:
            raise CliError(tr("用法：config get 名字"), 2)
        key = rest[0]
        _check_key(key)
        value = _shown(key, _value(cfg, key))
        _emit(as_json, {"key": key, "value": value}, _text(value))
        return 0
    if sub in ("keys", "schema"):            # schema：同样的内容，总是输出 JSON
        as_json = as_json or sub == "schema"
        out, lines = [], []
        for key in settable_keys():
            default = _default(key)
            item = {"key": key, "type": _kind(default), "default": _shown(key, default),
                    "value": _shown(key, _value(cfg, key)), "description": tr(DOCS.get(key) or VIRTUAL.get(key, "")),
                    "restart": key in RESTART}
            if key in config.CHOICES:
                item["choices"] = list(config.CHOICES[key])
            if key in config.RANGES:
                item["range"] = list(config.RANGES[key])
            out.append(item)
            extra = (" | ".join(v or "''" for v in item["choices"]) if "choices" in item else
                     "{0} ~ {1}".format(*item["range"]) if "range" in item else "")
            lines.append(f"{key}  [{item['type']}{'; ' + extra if extra else ''}]  = {_text(item['value'])}\n"
                         f"    {item['description']}" + (tr("（要重启）") if item["restart"] else ""))
        _emit(as_json, {"keys": out}, "\n".join(lines))
        return 0
    if sub == "set":
        pairs, i = [], 0
        while i < len(rest):
            if i + 1 >= len(rest):
                raise CliError(tr("用法：config set 名字 值 [名字 值…]"), 2)
            if rest[i + 1] == "--env":
                if i + 2 >= len(rest):
                    raise CliError(tr("--env 后面要跟环境变量名"), 2)
                pairs.append((rest[i], "--env", rest[i + 2]))
                i += 3
            else:
                pairs.append((rest[i], "", rest[i + 1]))
                i += 2
        if not pairs:
            raise CliError(tr("用法：config set 名字 值 [名字 值…]"), 2)
        changed = []
        for key, how, raw in pairs:
            _check_key(key)
            if how == "--env":
                if raw not in os.environ:
                    raise CliError(tr("没有这个环境变量：{name}").format(name=raw))
                raw = os.environ[raw]
            elif raw == "-":
                raw = _read_secret(key)
            value = parse_value(key, raw)
            if key == "autostart":
                _set_autostart(bool(value))
            else:
                apply_value(cfg, key, value)
            changed.append(key)
        return _saved(cfg, changed, as_json, "\n".join(tr("已改：{key} = {value}").format(
            key=k, value=_text(_shown(k, _value(cfg, k)))) for k in changed))
    if sub == "reset":
        if len(rest) != 1:
            raise CliError(tr("用法：config reset 名字"), 2)
        key = rest[0]
        _check_key(key)
        if key == "autostart":
            _set_autostart(False)
        else:
            config.set_key(cfg, key, copy.deepcopy(config.get_key(AppConfig(), key)))
        return _saved(cfg, [key], as_json, tr("已恢复默认：{key} = {value}").format(
            key=key, value=_text(_shown(key, _value(cfg, key)))))
    raise CliError(tr("config 没有这个子命令：{sub}").format(sub=sub) + "\n\n" + usage(), 2)


def _set_autostart(on: bool) -> None:
    try:
        autostart.set_enabled(on)
    except OSError as e:
        raise CliError(tr("开机启动没设上：{error}").format(error=e))


def cmd_service(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    if not args:
        items = [{"id": sid, "name": tr(name), "protocol": proto, "base_url": url, "model": model,
                  "current": cfg.llm.protocol == proto and cfg.llm.base_url.rstrip("/") == url.rstrip("/")}
                 for sid, (name, proto, url, model) in SERVICES.items()]
        _emit(as_json, {"services": items}, "\n".join(
            f"{'*' if it['current'] else ' '} {it['id']:14} {it['name']}  {it['base_url']}  {it['model']}"
            for it in items))
        return 0
    sid = args[0].lower()
    if sid not in SERVICES:
        raise CliError(tr("没有这个预设服务：{sid}（不带参数列出全部）").format(sid=args[0]))
    name, proto, url, model = SERVICES[sid]
    other_host = cfg.llm.base_url.rstrip("/") != url.rstrip("/")
    cfg.llm.protocol, cfg.llm.base_url = proto, url
    if model or other_host:
        cfg.llm.model = model
    cfg.llm.concurrency = 1 if proto == "ollama" else max(cfg.llm.concurrency, 2)
    notes = [tr("翻译服务换成了 {name}（{url}）。").format(name=tr(name), url=url)]
    local = "127.0.0.1" in url
    if not cfg.llm.model:
        notes.append(tr("这个服务没有默认模型：先用 models 命令看看有哪些，再 config set llm.model 名字。"))
    if not local and not cfg.llm.api_key:
        notes.append(tr("还要设 API Key：config set llm.api_key -（从标准输入读）。"))
    elif not local and other_host:
        notes.append(tr("API Key 还是原来那个服务的，换了服务商要重新设：config set llm.api_key -。"))
    return _saved(cfg, ["llm.protocol", "llm.base_url", "llm.model", "llm.concurrency"], as_json, "\n".join(notes))


def _service_config(cfg: AppConfig, vision: bool) -> LlmConfig:
    if not vision:
        return cfg.llm
    v = cfg.vision
    return LlmConfig(protocol=v.protocol, base_url=v.base_url, model=v.model, api_key=v.api_key)


def cmd_models(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    from .translator import list_models
    llm = _service_config(cfg, "--vision" in args)
    names, err = list_models(llm)
    if err:
        raise CliError(tr("没取到模型列表：{error}").format(error=err))
    _emit(as_json, {"models": names, "current": llm.model},
          "\n".join(("* " if n == llm.model else "  ") + n for n in names))
    return 0


def cmd_test(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    from .translator import test_connection
    ok, msg = test_connection(cfg.llm, cfg.target_lang)
    if not ok:
        raise CliError(msg)
    _emit(as_json, {"message": msg}, msg)
    return 0


def _app_option(args: list[str]) -> tuple[list[str], str]:
    if "--app" in args:
        i = args.index("--app")
        if i + 1 >= len(args):
            raise CliError(tr("--app 后面要跟程序名，比如 game.exe"), 2)
        return args[:i] + args[i + 2:], args[i + 1].strip()
    return args, ""


def cmd_glossary(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    sub, rest = (args[0], args[1:]) if args else ("list", [])
    rest, app = _app_option(rest)
    terms = cfg.glossary
    if sub == "list":
        _emit(as_json, {"glossary": terms}, "\n".join(
            f"{g['src']} → {g['dst']}" + (f"  [{g['app']}]" if g.get("app") else "") for g in terms)
            or tr("（术语表是空的）"))
        return 0
    if sub == "add":
        if len(rest) != 2 or not rest[0].strip() or not rest[1].strip():
            raise CliError(tr("用法：glossary add 原文 译文 [--app 程序.exe]"), 2)
        src, dst = rest[0].strip(), rest[1].strip()
        cfg.glossary = [g for g in terms if not (g["src"].lower() == src.lower() and g.get("app", "") == app)]
        cfg.glossary.append({"src": src, "dst": dst, "app": app})
        if len(cfg.glossary) > 500:
            raise CliError(tr("术语表最多 500 条"))
        return _saved(cfg, ["glossary"], as_json, tr("已加入术语表：{src} → {dst}").format(src=src, dst=dst))
    if sub == "remove":
        if len(rest) != 1:
            raise CliError(tr("用法：glossary remove 原文 [--app 程序.exe]"), 2)
        src = rest[0].strip().lower()
        left = [g for g in terms if not (g["src"].lower() == src and g.get("app", "") == app)]
        if len(left) == len(terms):
            raise CliError(tr("术语表里没有：{src}").format(src=rest[0]))
        cfg.glossary = left
        return _saved(cfg, ["glossary"], as_json, tr("已从术语表删掉：{src}").format(src=rest[0]))
    raise CliError(tr("glossary 没有这个子命令：{sub}").format(sub=sub), 2)


def cmd_usage(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    if "--log" in args:
        return _usage_log(args, as_json)
    u, limit = cfg.usage, cfg.guard.daily_tokens
    local, running = config.is_local_url(cfg.llm.base_url), _running()
    info = {"date": u.date, "requests": u.requests, "chars": u.chars, "tokens_in": u.tokens_in,
            "tokens_out": u.tokens_out, "tokens_cached": u.tokens_cached, "estimated": u.estimated,
            "daily_tokens_limit": limit, "local_service": local, "running": running}
    lines = [tr("{date}：请求 {requests} 次、原文 {chars} 字；输入 {tin} token（命中缓存 {cached}），输出 {tout} token").format(
        date=u.date or "-", requests=u.requests, chars=u.chars, tin=f"{u.tokens_in:,}",
        cached=f"{u.tokens_cached:,}", tout=f"{u.tokens_out:,}")]
    if u.estimated:
        lines.append(tr("≈：服务没有报用量的部分是按字数估算的"))
    if local:
        lines.append(tr("本机服务不花钱，不受每日上限限制"))
    else:
        lines.append(tr("每日上限：{limit} token").format(limit=f"{limit:,}") if limit else tr("每日上限：不限"))
    if running:
        lines.append(tr("魔镜正在运行：用量每 5 分钟存一次盘，这里的数可能慢一点"))
    _emit(as_json, info, "\n".join(lines))
    return 0


def _usage_log(args: list[str], as_json: bool) -> int:
    """按每次请求的日志（logs/usage-年-月.jsonl）汇总一天：钱花在哪个程序、多大的批、缓存命中多少。"""
    from . import usagelog
    i = args.index("--log")
    day = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
    if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise CliError(tr("日期要写成 年-月-日，比如 2026-10-07"), 2)
    tail = _option(args, "--tail") if "--tail" in args else "0"
    if not tail.isdigit():
        raise CliError(tr("--tail 后面要跟条数"), 2)
    recs = usagelog.read(day)
    sm = usagelog.summarize(recs)
    sm["day"] = day or time.strftime("%Y-%m-%d")
    if int(tail):
        sm["last"] = recs[-int(tail):]
    if as_json or not recs:
        _emit(as_json, sm, tr("{day} 没有记下翻译请求（日志在 {folder}）").format(day=sm["day"], folder=usagelog.log_dir()))
        return 0
    lines = [tr("{day}：请求 {requests} 次，输入 {tin} token（命中缓存 {cached}，{rate:.0%}），输出 {tout} token").format(
                 day=sm["day"], requests=sm["requests"], tin=f"{sm['tokens_in']:,}", cached=f"{sm['cached']:,}",
                 rate=sm["cache_hit_rate"], tout=f"{sm['tokens_out']:,}"),
             tr("平均每次请求：原文 {chars} 字、输入 {tin} token；每次都带的固定说明（约 {overhead} token）大约占输入的 {share:.0%}")
             .format(chars=sm["avg_chars_per_request"], tin=sm["avg_in_per_request"], overhead=usagelog.OVERHEAD_TOKENS,
                     share=sm["overhead_share"])]
    row = tr("{requests:>6} 次  输入 {tin:>10}  输出 {tout:>9}")
    for title, groups, limit in ((tr("按程序："), sm["by_app"], 10), (tr("按一批的字数："), sm["by_batch_chars"], None),
                                 (tr("按小时："), sm["by_hour"], None)):
        lines += ["", title]
        for name, c in list(groups.items())[:limit]:
            name = f"{name}:00" if groups is sm["by_hour"] else name
            lines.append(f"  {name:<28}" + row.format(requests=c["requests"], tin=f"{c['tokens_in']:,}",
                                                      tout=f"{c['tokens_out']:,}"))
    lines += [json.dumps(r, ensure_ascii=True) for r in sm.get("last", [])]
    print("\n".join(lines))
    return 0


def cmd_status(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    from . import updater
    method, reason = updater.install_method()
    running = _running()
    info = {"version": __version__, "config": str(config.config_path()), "running": running, "install": method,
            "install_note": reason}
    how = {"package": tr("在程序里直接更新"), "git": tr("git pull（源码版）")}.get(method, reason)
    _emit(as_json, info, "\n".join([
        tr("版本：{version}").format(version=__version__), tr("配置文件：{path}").format(path=info["config"]),
        tr("魔镜正在运行") if running else tr("魔镜没在运行"), tr("更新方式：{how}").format(how=how)]))
    return 0


def _option(args: list[str], name: str) -> str:
    if name not in args or args.index(name) + 1 >= len(args):
        raise CliError(tr("{name} 后面要跟一个值").format(name=name), 2)
    return args[args.index(name) + 1]


def _helper_logging(folder: Path) -> None:
    """助手进程没有窗口：过程记到 logs\\update.log。"""
    import logging
    (folder / "logs").mkdir(exist_ok=True)
    handler = logging.FileHandler(folder / "logs" / "update.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


def _wait_closed(seconds: float = 30.0) -> bool:
    end = time.monotonic() + seconds
    while _running():
        if time.monotonic() > end:
            return False
        time.sleep(0.3)
    return True


def cmd_update(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    from . import updater
    if "--apply" in args or "--apply-source" in args:           # 助手进程（由旧版本启动，没有窗口）
        restart, old_version = "--restart" in args, _option(args, "--from")
        wait_pid = int(_option(args, "--wait"))
        try:
            if "--apply" in args:
                target = Path(_option(args, "--apply"))
                _helper_logging(target)
                updater.apply_package(Path(sys.executable).resolve().parent, target, wait_pid, restart, old_version)
            else:
                _helper_logging(updater.program_dir())
                updater.apply_source(updater.program_dir(), wait_pid, restart, old_version)
        except updater.UpdateError as e:
            updater.message_box(str(e))
            return 1
        return 0
    try:
        rel = updater.latest_release()
    except updater.UpdateError as e:
        raise CliError(str(e))
    method, reason = updater.install_method()
    newer = updater.is_newer(rel.version)
    info = {"current": __version__, "latest": rel.version, "newer": newer, "method": method, "reason": reason,
            "page": rel.page, "notes": rel.notes}
    if not newer or "--check" in args:
        if not newer:
            text = tr("已经是最新版本（{version}）。").format(version=__version__)
        else:
            text = tr("有新版本 {latest}（现在 {current}）。").format(latest=rel.version, current=__version__)
            text += "\n" + (tr("自动更新：{p} update --yes").format(p=_prog()) if method != "manual" else
                            tr("{reason}。请到发布页下载：{page}").format(reason=reason, page=rel.page))
            text += "\n\n" + rel.notes.strip()
        _emit(as_json, info, text)
        return 0
    if method == "manual":
        raise CliError(tr("{reason}。请到发布页下载：{page}").format(reason=reason, page=rel.page))
    if "--yes" not in args:
        if as_json or sys.stdin is None or not sys.stdin.isatty():
            raise CliError(tr("确认要更新就加上 --yes"), 2)
        if input(tr("更新到 {version}？[y/N] ").format(version=rel.version)).strip().lower() not in ("y", "yes"):
            return 1
    running = _running()
    try:
        new_app = None
        if method == "package":
            def progress(done: int, total: int) -> None:
                if not as_json and sys.stdout.isatty() and total:
                    print(f"\r{done * 100 // total:3d}%  {done / 1e6:.0f} / {total / 1e6:.0f} MB", end="", flush=True)
            zip_path = updater.download(rel, updater.stage(), progress)
            if not as_json and sys.stdout.isatty():
                print()
            new_app = updater.extract(zip_path, updater.stage() / "new")
    except updater.UpdateError as e:
        raise CliError(str(e))
    if running:
        updater.request_quit()
        if not _wait_closed():
            raise CliError(tr("魔镜没有退出，没法更新：请在托盘图标上右键 → 退出，再试一次"))
    updater.start_helper(new_app, os.getpid(), restart=running)
    _emit(as_json, {**info, "restart": running}, tr("正在换上 {version}，几秒后完成{tail}（结果记在 logs\\update.log）。").format(
        version=rel.version, tail=tr("，魔镜会自动重新打开") if running else ""))
    return 0


def cmd_version(cfg: AppConfig, args: list[str], as_json: bool) -> int:
    _emit(as_json, {"version": __version__}, __version__)
    return 0


COMMANDS = {"config": cmd_config, "service": cmd_service, "models": cmd_models, "test": cmd_test,
            "glossary": cmd_glossary, "usage": cmd_usage, "status": cmd_status, "update": cmd_update,
            "version": cmd_version}


def _own_console() -> bool:
    """双击打开的（控制台窗口只属于自己）：显示完说明等按回车再关，不然一闪就没了。"""
    try:
        k32 = ctypes.WinDLL("kernel32")
        return k32.GetConsoleProcessList((ctypes.c_uint32 * 2)(), 2) == 1
    except (OSError, AttributeError):
        return False


def _attach_console() -> None:
    """DeskMirror.exe 是窗口程序，没有控制台：带参数运行时把输出接到启动它的命令行窗口上（推荐用 DeskMirrorCLI.exe）。"""
    k32 = ctypes.WinDLL("kernel32")
    if not getattr(sys, "frozen", False) or k32.GetConsoleWindow():
        return
    if k32.AttachConsole(-1):                   # ATTACH_PARENT_PROCESS
        sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")     # noqa: SIM115


def main(argv: list[str]) -> int:
    _attach_console()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")     # 输出到管道时，控制台代码页里没有的字（比如韩文模型名）不至于报错
        except (AttributeError, ValueError):
            pass
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    cfg = config.load()
    i18n.set_ui_lang(cfg.ui_lang or i18n.ui_lang_for(i18n.native_from_locale(i18n.system_locale())))
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        if not argv and _own_console():
            input(tr("按回车键关闭"))
        return 0
    handler = COMMANDS.get(argv[0])
    try:
        if handler is None:
            raise CliError(tr("没有这个命令：{cmd}").format(cmd=argv[0]) + "\n\n" + usage(), 2)
        return handler(cfg, argv[1:], as_json)
    except CliError as e:
        if as_json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=True))
        else:
            print(tr("出错了：{error}").format(error=e), file=sys.stderr)
        return e.code
