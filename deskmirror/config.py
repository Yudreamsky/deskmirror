"""配置：dataclass + JSON。API Key 用 Windows DPAPI 加密后存盘，不进源码、版本库和日志。

配置文件默认在项目根目录 deskmirror.json（已被 .gitignore 排除）；测试时用环境变量
DESKMIRROR_CONFIG 指向临时文件，不碰用户的真实配置。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from . import ROOT, winapi
from .i18n import N_

log = logging.getLogger(__name__)

# 译文语言（也是新手指南第 1 步的“母语”）：各用自己的文字写，任何界面语言下都这样显示
LANGUAGES: dict[str, str] = {
    "zh-Hans": "简体中文",
    "zh-Hant": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "id": "Bahasa Indonesia",
}

# 原文语言：自动识别，或手动指定（告诉模型原文是什么语言；韩文还要换识别模型）
SOURCE_LANGS: dict[str, str] = {
    "auto": N_("自动识别"),
    "en": N_("英文"),
    "id": N_("印尼文"),
    "ja": N_("日文"),
    "ko": N_("韩文（换用韩文识别模型）"),
    "zh": N_("中文"),
}
# 魔镜标签上的简称：“英→中”（显示时 tr）
SOURCE_SHORT = {"auto": N_("自动"), "en": N_("英"), "id": N_("印尼"), "ja": N_("日"), "ko": N_("韩"), "zh": N_("中")}
TARGET_SHORT = {"zh-Hans": N_("中"), "zh-Hant": N_("繁"), "en": N_("英"), "ja": N_("日"), "ko": N_("韩"),
                "id": N_("印尼")}


def ocr_lang_for(source: str) -> str:
    """原文语言对应的识别模型：默认模型认中文、英文、日文（印尼文等拉丁字母也行）；韩文要换韩文模型
    （RapidOCR 第一次用时从 ModelScope 下载并校验，约 14 MB）。"""
    return "korean" if source == "ko" else "default"

# OpenAI 兼容接口的常见地址，只用于设置页一键填入；用户可以改成任意服务。名称显示时 tr。
OPENAI_PRESETS: dict[str, tuple[str, str]] = {
    "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
    N_("通义千问（阿里云百炼）"): ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    N_("硅基流动"): ("https://api.siliconflow.cn/v1", ""),
    "OpenAI": ("https://api.openai.com/v1", ""),
    N_("Ollama（OpenAI 兼容）"): ("http://127.0.0.1:11434/v1", "gemma4:12b"),
    N_("LM Studio（本地）"): ("http://127.0.0.1:1234/v1", ""),
}


@dataclass
class LlmConfig:
    protocol: str = "ollama"          # ollama：Ollama 原生接口；openai：OpenAI 兼容 /chat/completions
    base_url: str = "http://127.0.0.1:11434"
    model: str = "gemma4:12b"
    api_key: str = ""                 # 内存里是明文；存盘时加密
    temperature: float = 0.2
    timeout_s: float = 45.0
    concurrency: int = 1              # 同时在途的请求数
    max_batch_chars: int = 1000       # 一次请求最多合并多少字的文字块（实测 8~10 段吞吐已到顶）
    max_batch_items: int = 10         # 一次请求最多合并多少个文字块
    disable_thinking: bool = True     # 关掉模型的“思考”：Ollama 传 think=false，OpenAI 兼容接口传 thinking=disabled（DeepSeek 默认开）
    num_ctx: int = 4096               # Ollama 每次必须一致，否则会重新加载模型
    keep_alive: str = "30m"
    consistency: bool = True          # 术语前后一致：附上本窗口里含同样词语的已有译文作参考（请求会长一些）
    gather_ms: int = 600              # 已有请求在途时，零星的新文字最多等这么久凑成一批再发（每次请求都要带约 430 token
                                      # 的固定说明，一两行字单独发很不划算）；0 = 不等


@dataclass
class OcrConfig:
    device: str = "gpu"               # gpu：DirectML；cpu
    threads: int = 8                  # 8 线程最快；-1 会用到能效核反而更慢


@dataclass
class HotkeyConfig:
    # 默认值避开了常见软件爱占用的组合（Ctrl+Alt+A/L/M/R/W 等）；注册失败时托盘会提示，可在设置里改。
    drag_modifiers: str = "Ctrl+Alt"  # 按住后在镜内拖动即可移动魔镜
    peek: str = "Ctrl+Alt+O"          # 按住显示原文，松开恢复译文
    refresh: str = "Ctrl+Alt+T"       # 刷新镜框内区域
    toggle_visible: str = "Ctrl+Alt+H"  # 隐藏 / 显示魔镜
    history: str = "Ctrl+Alt+Y"       # 历史面板：最近的原文和译文
    vision: str = "Ctrl+Alt+V"        # 看图翻译：把镜框里的画面发给能看图的模型


@dataclass
class StyleConfig:
    font_family: str = "Microsoft YaHei UI"
    min_font_px: int = 11             # 放不下时最多缩到这么小；再放不下就截断并标出“…”
    min_scale: float = 0.75           # 相对原文字号最多缩小到 75%
    min_squash: float = 0.6           # 英文等放不下时最多横向压扁到原宽的 60%：先压到八成（几乎看不出来）再缩字号，
                                      # 更扁的只在快要伸出去、要缩得更小时才用；中日韩文字最多压到八成
    plate_opacity: float = 1.0        # 原位底板的不透明度（1 = 完全盖住原文）
    border_color: str = "#3D8BFD"


@dataclass
class TrackConfig:
    stable_ms: int = 350              # 区域静止多久后才识别新文字（快速滚动时先不识别）
    dynamic_ms: int = 1000            # 魔镜附近持续变化的区域（视频字幕、游戏画面）多久抓拍识别一次
    subtitle_hold_ms: int = 4000      # 字幕换句时旧译文最多保留多久（新译文一到立即顶掉；网页文档不保留）
    ring_px: int = 240                # 螺旋调度每一圈的宽度
    max_cache_blocks: int = 6000      # 已识别文字块（含暂时看不见的）上限
    max_cache_texts: int = 20000      # 译文缓存（按原文）上限，只在内存里
    prefer_dxgi: bool = True
    all_monitors: bool = False        # 默认只处理魔镜所在的屏幕；打开后处理所有屏幕
    wheel_predict: bool = True        # 用滚轮学到的曲线提前移动译文（像素识别仍是最终依据）
    display_lead_ms: int = 12         # 预测到“译文实际显示出来”的提前量：绘制 + 一帧合成


# 默认不识别、不翻译的程序和窗口：聊天软件、密码管理器、网银和支付页面。屏幕上的这些内容不进识别，
# 更不会发给翻译服务（用云端服务时尤其要紧）。用户可以在设置里增删。
# 聊天软件：默认不翻（私人聊天不发出去）；和外国同事、朋友聊天时打开“翻译聊天软件”就照常翻
CHAT_APPS = [
    "WeChat.exe", "Weixin.exe", "WeChatAppEx.exe", "WXWork.exe", "QQ.exe", "TIM.exe", "DingTalk.exe",
    "Feishu.exe", "Lark.exe", "Telegram.exe", "WhatsApp.exe", "Signal.exe", "LINE.exe", "Discord.exe",
]
CHAT_TITLES = ["WhatsApp"]           # 网页版
DEFAULT_EXCLUDE_APPS = CHAT_APPS + [
    "KeePass.exe", "KeePassXC.exe", "1Password.exe", "Bitwarden.exe", "Dashlane.exe", "Enpass.exe",
]
DEFAULT_EXCLUDE_TITLES = [
    "网上银行", "网银", "手机银行", "Online Banking", "支付宝", "Alipay", "PayPal", "微信支付",
    "WhatsApp", "LastPass", "Bitwarden", "1Password", "KeePass",
]
SCOPE_MODES: dict[str, str] = {        # 显示时 tr
    "screen": N_("整块屏幕（拖到哪里译文都已备好）"),
    "window": N_("只翻魔镜所在的窗口"),
    "near": N_("只翻镜框附近"),
}


@dataclass
class ScopeConfig:
    mode: str = "screen"              # screen：魔镜所在屏幕全部预译；window：魔镜里露出的窗口；near：镜框附近
    near_px: int = 480                # near：镜框外多远以内也预译
    exclude_apps: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE_APPS))
    exclude_titles: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE_TITLES))
    translate_chat: bool = False      # 名单里的聊天软件也照常翻（和外国同事聊天时打开）；密码管理器、网银仍不翻


@dataclass
class VisionConfig:
    """看图翻译用的模型（要能看图的多模态模型）。和翻译服务分开设：常用的翻译服务（如 DeepSeek）不收图片。"""
    protocol: str = "ollama"          # ollama：Ollama 原生接口；openai：OpenAI 兼容接口
    base_url: str = "http://127.0.0.1:11434"
    model: str = "gemma4:12b"         # 本机的 gemma4 能看图，画面不出本机
    api_key: str = ""                 # 云端服务才要；内存里是明文，存盘时加密
    timeout_s: float = 120.0          # 多模态模型慢
    max_side: int = 1600              # 发图前把长边缩到这么大（省时间、省费用）
    num_ctx: int = 4096               # 和翻译用同一个 Ollama 模型时要一致，否则 Ollama 会重新加载模型


@dataclass
class GlossaryEntry:
    src: str = ""                     # 原文里的词（不分大小写）
    dst: str = ""                     # 必须用的译法；和原文一样表示“保持不译”
    app: str = ""                     # 只用于这个程序（如 game.exe）；空表示所有程序


@dataclass
class MemoryConfig:
    enabled: bool = False             # 记住译文（加密存在本机，下次相同的文字直接用）；用户主动打开才用


@dataclass
class UsageConfig:
    """当天发给翻译服务的请求数、字数和 token（只有数量，不含任何文字）。"""
    date: str = ""
    requests: int = 0
    chars: int = 0
    tokens_in: int = 0                # 输入 token（发过去的：提示词、原文、参考译文）
    tokens_out: int = 0               # 输出 token（模型写的译文）
    tokens_cached: int = 0            # 输入里命中服务商缓存的（便宜得多）
    estimated: bool = False           # 其中有服务没报用量、按字数估算的


@dataclass
class GuardConfig:
    """省钱保护：人不在电脑前时少发请求，一天的 token 用到上限就停。"""
    idle_min: int = 5                 # 这么多分钟没碰键盘鼠标：只翻镜框里的，不在后台预译别处；0 = 不管
    pause_when_locked: bool = True    # 锁屏、屏保时完全停下（不截屏、不识别、不翻译）
    daily_tokens: int = 1_000_000     # 云端服务一天最多用这么多 token（输入 + 输出），到了就停；0 = 不限。本机服务不限
    show_meter: bool = True           # 魔镜标签上显示今天用掉的 token（↑ 输入 ↓ 输出）


@dataclass
class UpdateConfig:
    auto_check: bool = True           # 每天第一次启动时在后台看一下有没有新版本（只访问 GitHub，不发任何内容）
    last_check: str = ""              # 上次自动检查的日期


@dataclass
class AppConfig:
    source_lang: str = "auto"
    target_lang: str = "zh-Hans"
    ui_lang: str = ""                 # 界面语言 zh / en；空 = 还没定（第一次启动按 Windows 的语言猜）
    mirror_rect: list[int] = field(default_factory=list)  # [left, top, right, bottom]，物理像素
    extra_mirrors: list[list[int]] = field(default_factory=list)   # 另外开的魔镜（最多 3 个）
    first_run_tip: bool = True
    llm: LlmConfig = field(default_factory=LlmConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    style: StyleConfig = field(default_factory=StyleConfig)
    track: TrackConfig = field(default_factory=TrackConfig)
    scope: ScopeConfig = field(default_factory=ScopeConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    glossary: list[dict] = field(default_factory=list)   # [{src, dst, app}]，用户填写的术语表
    usage: UsageConfig = field(default_factory=UsageConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)


def is_local_url(base_url: str) -> bool:
    """服务地址是不是本机（本机服务不花钱、不受 token 上限限制；看图翻译发本机也不用每次问）。"""
    from urllib.parse import urlparse
    host = (urlparse(base_url.strip() if "://" in base_url else "http://" + base_url.strip()).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1") or host.endswith(".localhost")


def config_path() -> Path:
    env = os.environ.get("DESKMIRROR_CONFIG")
    return Path(env) if env else ROOT / "deskmirror.json"


def _load_into(cls, data: Any):
    obj = cls()
    if not isinstance(data, dict):
        return obj
    for f in fields(cls):
        if f.name not in data:
            continue
        current = getattr(obj, f.name)
        value = data[f.name]
        if is_dataclass(current):
            setattr(obj, f.name, _load_into(type(current), value))
        elif isinstance(current, bool):
            if isinstance(value, bool):
                setattr(obj, f.name, value)
        elif isinstance(current, (int, float)) and not isinstance(current, bool):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(obj, f.name, type(current)(value))
        elif isinstance(current, str):
            if isinstance(value, str):
                setattr(obj, f.name, value)
        elif isinstance(current, list):
            if isinstance(value, list):
                setattr(obj, f.name, value)
    return obj


_SECRET_PREFIX = "dpapi:"


def _encrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _SECRET_PREFIX + winapi.protect(value)
    except OSError:
        log.warning("API Key 加密失败，本次不保存 Key")
        return ""


def _decrypt(value: str) -> str:
    if not value.startswith(_SECRET_PREFIX):
        return value  # 手写进配置的明文 Key，下次保存时加密
    try:
        return winapi.unprotect(value[len(_SECRET_PREFIX):])
    except (OSError, ValueError):
        log.warning("API Key 解密失败（可能换了电脑或 Windows 账户），请在设置里重新填写")
        return ""


def validate(cfg: AppConfig) -> AppConfig:
    if cfg.llm.protocol not in ("ollama", "openai"):
        cfg.llm.protocol = "ollama"
    if cfg.ocr.device not in ("gpu", "cpu"):
        cfg.ocr.device = "gpu"
    if cfg.source_lang not in SOURCE_LANGS:
        cfg.source_lang = "auto"
    if cfg.vision.protocol not in ("ollama", "openai"):
        cfg.vision.protocol = "ollama"
    cfg.vision.timeout_s = max(10.0, min(600.0, float(cfg.vision.timeout_s)))
    cfg.vision.max_side = max(512, min(3000, int(cfg.vision.max_side)))
    if cfg.target_lang not in LANGUAGES:
        cfg.target_lang = "zh-Hans"
    if cfg.ui_lang not in ("", "zh", "en"):
        cfg.ui_lang = ""
    cfg.llm.concurrency = max(1, min(8, cfg.llm.concurrency))
    cfg.llm.timeout_s = max(5.0, min(300.0, cfg.llm.timeout_s))
    cfg.llm.max_batch_chars = max(200, min(6000, cfg.llm.max_batch_chars))
    cfg.llm.max_batch_items = max(1, min(32, cfg.llm.max_batch_items))
    cfg.llm.gather_ms = max(0, min(5000, cfg.llm.gather_ms))
    cfg.style.min_font_px = max(8, min(32, cfg.style.min_font_px))
    cfg.style.min_scale = max(0.4, min(1.0, cfg.style.min_scale))
    cfg.style.min_squash = max(0.5, min(1.0, cfg.style.min_squash))
    cfg.style.plate_opacity = max(0.3, min(1.0, cfg.style.plate_opacity))
    cfg.track.stable_ms = max(100, min(3000, cfg.track.stable_ms))
    cfg.track.ring_px = max(60, min(2000, cfg.track.ring_px))
    cfg.guard.idle_min = max(0, min(240, cfg.guard.idle_min))
    cfg.guard.daily_tokens = max(0, cfg.guard.daily_tokens)
    terms = []
    for g in cfg.glossary if isinstance(cfg.glossary, list) else []:
        if isinstance(g, dict) and str(g.get("src", "")).strip() and str(g.get("dst", "")).strip():
            terms.append({"src": str(g["src"]).strip(), "dst": str(g["dst"]).strip(),
                          "app": str(g.get("app", "")).strip()})
    cfg.glossary = terms[:500]
    if cfg.scope.mode not in SCOPE_MODES:
        cfg.scope.mode = "screen"
    cfg.scope.near_px = max(100, min(3000, cfg.scope.near_px))
    for name in ("exclude_apps", "exclude_titles"):
        seen, out = set(), []
        for v in getattr(cfg.scope, name):
            v = v.strip() if isinstance(v, str) else ""
            if v and v.lower() not in seen:
                seen.add(v.lower())
                out.append(v)
        setattr(cfg.scope, name, out)
    if not (isinstance(cfg.mirror_rect, list) and len(cfg.mirror_rect) == 4
            and all(isinstance(v, int) for v in cfg.mirror_rect)
            and cfg.mirror_rect[2] - cfg.mirror_rect[0] >= 80 and cfg.mirror_rect[3] - cfg.mirror_rect[1] >= 60):
        cfg.mirror_rect = []
    cfg.extra_mirrors = [list(r) for r in (cfg.extra_mirrors if isinstance(cfg.extra_mirrors, list) else [])
                         if isinstance(r, list) and len(r) == 4 and all(isinstance(v, int) for v in r)
                         and r[2] - r[0] >= 80 and r[3] - r[1] >= 60][:3]
    return cfg


def load() -> AppConfig:
    path = config_path()
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("配置文件损坏，已改用默认设置（原文件另存为 .broken）")
            try:
                path.replace(path.with_suffix(".broken.json"))
            except OSError:
                pass
            data = {}
    cfg = _load_into(AppConfig, data)
    cfg.llm.api_key = _decrypt(cfg.llm.api_key)
    cfg.vision.api_key = _decrypt(cfg.vision.api_key)
    return validate(cfg)


def save(cfg: AppConfig) -> None:
    data = asdict(cfg)
    data["llm"]["api_key"] = _encrypt(cfg.llm.api_key)
    data["vision"]["api_key"] = _encrypt(cfg.vision.api_key)
    path = config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
