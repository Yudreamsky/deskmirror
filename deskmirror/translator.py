"""可更换的翻译服务：Ollama 原生接口或任意 OpenAI 兼容接口。

本地程序负责坐标、画布、缓存有效性和裁剪；这里只把一批文字块交给 LLM 翻译。
一批里的文字块编号 [1] [2] … 发出去，按编号解析回来；流式返回时每个编号段落
完整后才交回（下一个编号出现或流结束），界面因此总是整块替换，不会逐字跳动。

日志不记录原文和译文；API Key 不进日志。
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from .config import LANGUAGES, LlmConfig
from .i18n import tr

log = logging.getLogger(__name__)

_TARGET_DESC = {
    "zh-Hans": "Simplified Chinese (简体中文)",
    "zh-Hant": "Traditional Chinese (繁體中文)",
    "en": "English",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "id": "Indonesian (Bahasa Indonesia)",
}
_SOURCE_DESC = {"en": "English", "id": "Indonesian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese"}

_SEG = re.compile(r"^\s*\[(\d{1,3})\]\s?(.*)$")
_THINK = re.compile(r"<think>.*?</think>", re.S)


def system_prompt(target: str, source: str = "auto") -> str:
    lang = _TARGET_DESC.get(target, LANGUAGES.get(target, target))
    src = (f"The user says the text is mostly {_SOURCE_DESC[source]}; read it as {_SOURCE_DESC[source]}. "
           if source in _SOURCE_DESC else "")
    return (
        f"You translate on-screen text into {lang}. The text comes from OCR of a computer screen: web pages, "
        f"documents, app interfaces, games. {src}Each input segment starts with a number like [1].\n"
        "Rules:\n"
        f"- Output every segment in the same order, each starting with its own number, e.g. [1] <{lang} text>.\n"
        "- Never merge, split, skip or reorder segments; one output segment per input segment.\n"
        "- Translate naturally and concisely, as UI/reading text. Keep names, code, URLs, file paths, numbers "
        "and units as they are.\n"
        "- Code identifiers stay unchanged: CSS properties, function/variable names, commands, keys, file names "
        "(e.g. overflow-x, opacity, padding, getElementById, npm install). Neighbouring segments often come "
        "from the same list; if they look like a list of identifiers, keep them all as they are.\n"
        f"- If a segment is already {lang}, or is only symbols/numbers, repeat it unchanged.\n"
        "- A first line 'Window: ...' is the title of the window the text comes from. Use it only as "
        "context (e.g. a CSS reference page, a game, a PDF); never translate or output it.\n"
        "- A 'Glossary:' section lists required translations ('term = translation'). Whenever a term appears, "
        "use exactly that translation (if it equals the term, keep the term untranslated). Never output the "
        "glossary itself.\n"
        "- A 'Previous lines:' section shows the subtitle or dialogue lines shown just before these, oldest first "
        "('source => translation'). Use them only as context, to keep names, pronouns and tone consistent; "
        "never translate or output them.\n"
        "- A 'Reference:' section shows earlier translations from the same window ('source => translation'). "
        "Translate the same terms, names and defined words exactly as they were translated there, so the "
        "terminology stays consistent. The Glossary wins if they differ. Never translate or output the "
        "reference lines.\n"
        "- Silently fix obvious OCR mistakes. Output only the numbered translations, nothing else."
    )


def compose_prompt(target: str, source: str) -> str:
    """输入框翻译：用户自己用母语写的话（聊天、邮件、评论），译成要发出去的语言。原文语言是确定的（用户的母语）。"""
    lang = _TARGET_DESC.get(target, LANGUAGES.get(target, target))
    src = _SOURCE_DESC.get(source, "the user's own language")
    return (
        f"You translate what the user is typing in a text box (a chat message, an email, a comment, a search) "
        f"from {src} into {lang}, so they can send it. Each input segment starts with a number like [1]; "
        "the segments are consecutive lines of the same message.\n"
        "Rules:\n"
        f"- Output every segment in the same order, each starting with its own number, e.g. [1] <{lang} text>.\n"
        "- Never merge, split, skip or reorder segments; one output segment per input segment.\n"
        "- Write it the way a native speaker would type that kind of message: keep the meaning, the tone, the level "
        "of politeness, emoji and punctuation style. Don't add greetings, notes or explanations.\n"
        "- Keep names, @mentions, #tags, URLs, email addresses, code, numbers and units as they are.\n"
        f"- If a segment is already {lang}, repeat it unchanged.\n"
        "- Output only the numbered translations, nothing else."
    )


def build_user_message(texts: list[str], context: str = "", glossary: list[tuple[str, str]] | None = None,
                       refs: list[tuple[str, str]] | None = None, dialog: list[tuple[str, str]] | None = None) -> str:
    body = "\n".join(f"[{i + 1}] {t.replace(chr(10), ' ')}" for i, t in enumerate(texts))
    head = []
    if context:
        head.append(f"Window: {context}")
    if glossary:
        head.append("Glossary:\n" + "\n".join(f"{s} = {d}" for s, d in glossary))
    if refs:
        head.append("Reference:\n" + "\n".join(f"{s.replace(chr(10), ' ')} => {d.replace(chr(10), ' ')}"
                                                for s, d in refs))
    if dialog:
        head.append("Previous lines:\n" + "\n".join(f"{s.replace(chr(10), ' ')} => {d.replace(chr(10), ' ')}"
                                                     for s, d in dialog))
    return "\n\n".join(head + [body]) if head else body


class SegmentParser:
    """增量解析 “[n] 译文” 流；第 n 段在看到下一个编号或结束时才算完整。

    原始流先去掉 <think>…</think> 思考段（只会出现在开头），再按行解析。
    """

    def __init__(self, count: int, on_segment: Callable[[int, str], None]) -> None:
        self.count = count
        self.on_segment = on_segment
        self.raw = ""
        self.fed = 0
        self.buf = ""
        self.current: int | None = None
        self.parts: list[str] = []
        self.done: set[int] = set()

    def feed_raw(self, piece: str) -> None:
        self.raw += piece
        cleaned = _clean(self.raw)
        if len(cleaned) > self.fed:
            self.feed(cleaned[self.fed:])
            self.fed = len(cleaned)

    def feed(self, chunk: str) -> None:
        self.buf += chunk
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._line(line)

    def _line(self, line: str) -> None:
        m = _SEG.match(line)
        if m and 1 <= int(m.group(1)) <= self.count:
            self._finish()
            self.current = int(m.group(1)) - 1
            self.parts = [m.group(2)]
        elif self.current is not None and line.strip():
            self.parts.append(line.strip())

    def _finish(self) -> None:
        if self.current is not None and self.current not in self.done:
            text = " ".join(p.strip() for p in self.parts if p.strip()).strip()
            if text:
                self.done.add(self.current)
                self.on_segment(self.current, text)
        self.current = None
        self.parts = []

    def close(self) -> None:
        if self.buf:
            self._line(self.buf)
            self.buf = ""
        self._finish()


class ServiceError(Exception):
    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _http_error(resp: httpx.Response) -> ServiceError:
    code = resp.status_code
    try:
        detail = resp.json()
        detail = detail.get("error", detail)
        if isinstance(detail, dict):
            detail = detail.get("message", "")
    except ValueError:
        detail = ""
    detail = str(detail)[:120]
    if code in (401, 403):
        return ServiceError(tr("密钥无效或没有权限（HTTP {code}）").format(code=code), retryable=False)
    if code == 402:
        return ServiceError(tr("账户余额不足（HTTP 402）：到服务商那里充值后点 ⟳ 继续"), retryable=False)
    if code == 404:
        return ServiceError(tr("地址或模型不存在（HTTP 404）{detail}").format(detail=detail), retryable=False)
    if code == 429:
        return ServiceError(tr("请求太频繁或额度用完（HTTP 429）"))
    return ServiceError(tr("服务返回错误 HTTP {code} {detail}").format(code=code, detail=detail),
                        retryable=code >= 500)


# 不认附加参数（"thinking"、"stream_options"）的 OpenAI 兼容服务（按服务地址记住）：这次运行里不再带，
# 免得每批都先报错再重发
_NO_EXTRA_PARAMS: set[str] = set()

_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯豈-﫿＀-￯]")


def estimate_tokens(text: str) -> int:
    """服务没报用量时按字数估算 token：中日韩文字约一字一个，其余约四个字符一个。"""
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk + 3) // 4


@dataclass
class Usage:
    """一次请求用掉的 token：输入（发过去的）、输出（模型写的）；exact=False 表示服务没报、是按字数估的。"""
    tokens_in: int = 0
    tokens_out: int = 0
    exact: bool = False
    cached: int = 0                   # 输入里命中服务商缓存的部分（DeepSeek、OpenAI 按低得多的价格计费）


def _clean(text: str) -> str:
    text = _THINK.sub("", text)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text


def stream_translate(cfg: LlmConfig, target: str, texts: list[str], on_segment: Callable[[int, str], None],
                     client: httpx.Client, cancel: threading.Event, context: str = "",
                     glossary: list[tuple[str, str]] | None = None, refs: list[tuple[str, str]] | None = None,
                     source: str = "auto", dialog: list[tuple[str, str]] | None = None, prompt: str = "") -> Usage:
    """发一批文字块，流式解析；全部完成后返回这次用掉的 token。失败抛 ServiceError。

    context 是这批文字所在窗口的标题，帮模型判断场景（比如 CSS 文档里的属性名不该翻译）。
    prompt：换掉默认的系统说明（输入框翻译用 compose_prompt）。
    """
    messages = [{"role": "system", "content": prompt or system_prompt(target, source)},
                {"role": "user", "content": build_user_message(texts, context, glossary, refs, dialog)}]
    parser = SegmentParser(len(texts), on_segment)
    usage = Usage()

    def finish() -> Usage:
        if not usage.exact:      # 服务没报用量（或中途取消）：按发出去和收回来的字数估
            usage.tokens_in = sum(estimate_tokens(m["content"]) for m in messages)
            usage.tokens_out = estimate_tokens(parser.raw)
        return usage
    base = cfg.base_url.strip().rstrip("/")
    if not base:
        raise ServiceError(tr("还没有填写翻译服务地址"), retryable=False)
    if not cfg.model.strip():
        raise ServiceError(tr("还没有填写模型名"), retryable=False)
    try:
        if cfg.protocol == "ollama":
            payload = {"model": cfg.model, "messages": messages, "stream": True, "keep_alive": cfg.keep_alive,
                       "options": {"temperature": cfg.temperature, "num_ctx": cfg.num_ctx}}
            if cfg.disable_thinking:
                payload["think"] = False
            for attempt in range(2):
                with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        if attempt == 0 and "think" in payload and resp.status_code == 400 \
                                and "think" in resp.text.lower():
                            payload.pop("think")  # 这个模型不支持思考开关：去掉参数重发一次
                            continue
                        raise _http_error(resp)
                    for line in resp.iter_lines():
                        if cancel.is_set():
                            return finish()
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise ServiceError(tr("服务报错：{detail}").format(detail=str(data["error"])[:120]))
                        piece = (data.get("message") or {}).get("content", "")
                        if piece:
                            parser.feed_raw(piece)
                        if data.get("done"):
                            if isinstance(data.get("prompt_eval_count"), int) or isinstance(data.get("eval_count"), int):
                                usage.tokens_in = int(data.get("prompt_eval_count") or 0)
                                usage.tokens_out = int(data.get("eval_count") or 0)
                                usage.exact = True
                            break
                    break
        else:
            headers = {"Content-Type": "application/json"}
            if cfg.api_key:
                headers["Authorization"] = f"Bearer {cfg.api_key}"
            payload = {"model": cfg.model, "messages": messages, "temperature": cfg.temperature, "stream": True}
            extras = base not in _NO_EXTRA_PARAMS
            if extras:
                payload["stream_options"] = {"include_usage": True}   # 最后一段带上这次用掉的 token
                if cfg.disable_thinking:
                    # DeepSeek 等服务默认开“思考”：翻译用不着，关掉快得多、也省钱（思考的字数按输出计费）
                    payload["thinking"] = {"type": "disabled"}
            for attempt in range(2):
                with client.stream("POST", f"{base}/chat/completions", json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        if attempt == 0 and extras and resp.status_code in (400, 422):
                            # 可能是不认附加参数：去掉重发一次，成功就记住这个服务
                            payload.pop("thinking", None)
                            payload.pop("stream_options", None)
                            continue
                        raise _http_error(resp)
                    if attempt == 1:
                        _NO_EXTRA_PARAMS.add(base)
                    for line in resp.iter_lines():
                        if cancel.is_set():
                            return finish()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        if obj.get("error"):
                            raise ServiceError(tr("服务报错：{detail}").format(detail=str(obj["error"])[:120]))
                        u = obj.get("usage")
                        if isinstance(u, dict) and isinstance(u.get("prompt_tokens"), int):
                            usage.tokens_in = u["prompt_tokens"]
                            usage.tokens_out = int(u.get("completion_tokens") or 0)
                            usage.exact = True
                            # DeepSeek：prompt_cache_hit_tokens；OpenAI 等：prompt_tokens_details.cached_tokens
                            details = u.get("prompt_tokens_details") or {}
                            usage.cached = int(u.get("prompt_cache_hit_tokens")
                                               or (details.get("cached_tokens") if isinstance(details, dict) else 0)
                                               or 0)
                        choices = obj.get("choices") or []
                        if choices:
                            piece = (choices[0].get("delta") or {}).get("content") or ""
                            if piece:
                                parser.feed_raw(piece)
                    break
    except httpx.TimeoutException:
        raise ServiceError(tr("翻译服务响应超时")) from None
    except httpx.ConnectError:
        raise ServiceError(tr("连不上翻译服务（服务没启动或地址不对）")) from None
    except (httpx.RemoteProtocolError, httpx.ReadError):
        raise ServiceError(tr("翻译服务连接中途断开（服务重启或网络不稳）")) from None
    except httpx.HTTPError as e:
        raise ServiceError(tr("网络错误：{name}").format(name=type(e).__name__)) from None
    parser.close()
    return finish()


def make_client(cfg: LlmConfig, timeout_s: float | None = None) -> httpx.Client:
    # 连接超时短，读超时按设置；整批没完成也不会无限挂着。如实标明客户端身份（不用 HTTP 库的默认名）。
    from . import HOMEPAGE, __version__
    return httpx.Client(timeout=httpx.Timeout(timeout_s or cfg.timeout_s, connect=5.0), trust_env=False,
                        headers={"User-Agent": f"DeskMirror/{__version__} (screen translator; +{HOMEPAGE})"})


def test_connection(cfg: LlmConfig, target: str) -> tuple[bool, str]:
    """设置页的“测试连接”：发一句短文，返回 (是否成功, 给用户看的说明)。"""
    got: dict[int, str] = {}
    t0 = time.perf_counter()
    try:
        with make_client(cfg) as client:
            stream_translate(cfg, target, ["Hello, world!", "Open settings"], lambda i, s: got.__setitem__(i, s),
                             client, threading.Event())
    except ServiceError as e:
        return False, str(e)
    dt = time.perf_counter() - t0
    if len(got) < 2:
        return False, tr("服务有回应，但没有按编号返回译文（用时 {secs:.1f} 秒）；可换一个模型试试").format(secs=dt)
    return True, tr("连接成功，用时 {secs:.1f} 秒：{a} / {b}").format(secs=dt, a=got.get(0, ""), b=got.get(1, ""))


def list_models(cfg: LlmConfig) -> tuple[list[str], str]:
    """设置页的“获取模型列表”：返回 (模型名, 没取到时给用户看的原因)。"""
    base = cfg.base_url.strip().rstrip("/")
    if not base:
        return [], tr("先填服务地址")
    try:
        with make_client(cfg, timeout_s=8.0) as c:
            if cfg.protocol == "ollama":
                r = c.get(f"{base}/api/tags")
            else:
                headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
                r = c.get(f"{base}/models", headers=headers)
            if r.status_code in (401, 403):
                return [], (tr("还没填 API Key") if not cfg.api_key
                            else tr("密钥不对或没有权限（HTTP {code}）").format(code=r.status_code))
            if r.status_code == 404:
                return [], tr("这个地址没有模型列表接口（HTTP 404），检查服务地址和接入方式")
            r.raise_for_status()
            data = r.json()
            if cfg.protocol == "ollama":
                names = [str(m["name"]) for m in data.get("models", [])]
            else:
                names = [str(m["id"]) for m in data.get("data", [])]
            return sorted(names), ("" if names else tr("服务返回的模型列表是空的"))
    except httpx.ConnectError:
        return [], tr("连不上服务，检查服务地址和网络")
    except httpx.TimeoutException:
        return [], tr("服务响应超时")
    except httpx.HTTPStatusError as e:
        return [], tr("服务返回错误（HTTP {code}）").format(code=e.response.status_code)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return [], tr("服务返回的内容不是模型列表")


# --------------------------------------------------------------------- 工作线程

@dataclass
class Batch:
    batch_id: int
    texts: list[str]
    keys: list[str]                      # 每段的缓存键（规范化原文）
    target: str
    context: str = ""                    # 所在窗口的标题
    glossary: list = field(default_factory=list)   # [(原文词, 译法)]：这批文字里出现的术语
    refs: list = field(default_factory=list)       # [(原文, 译文)]：本窗口里含同样词语的已有译文（术语前后一致）
    hwnd: int = 0                                  # 文字所在的窗口和程序（记参考用）
    app: str = ""
    source: str = "auto"                           # 用户指定的原文语言
    dialog: list = field(default_factory=list)     # [(原文, 译文)]：同一窗口刚刚出现过的几句字幕 / 对话（上下文）
    created: float = field(default_factory=time.perf_counter)


class TranslatorPool:
    """固定数量的工作线程；调用方保证在途批次不超过 concurrency。"""

    def __init__(self, cfg: LlmConfig, on_event: Callable[[tuple], None]) -> None:
        self.cfg = cfg
        self._on_event = on_event
        self._q: queue.Queue[Batch | None] = queue.Queue()
        self._cancel = threading.Event()
        self._threads = []
        self._clients: list[httpx.Client] = []
        for i in range(cfg.concurrency):
            t = threading.Thread(target=self._run, name=f"translate-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def submit(self, batch: Batch) -> None:
        self._q.put(batch)

    def _run(self) -> None:
        client = make_client(self.cfg)
        self._clients.append(client)
        try:
            while not self._cancel.is_set():
                batch = self._q.get()
                if batch is None or self._cancel.is_set():
                    break
                t0 = time.perf_counter()
                try:
                    usage = stream_translate(self.cfg, batch.target, batch.texts,
                                             lambda i, s, b=batch: self._on_event(("segment", b.batch_id, i, s)),
                                             client, self._cancel, batch.context, batch.glossary, batch.refs,
                                             batch.source, batch.dialog)
                    self._on_event(("batch_done", batch.batch_id, None, time.perf_counter() - t0, usage))
                except ServiceError as e:
                    self._on_event(("batch_done", batch.batch_id, e, time.perf_counter() - t0))
                except Exception as e:  # noqa: BLE001 - 不能让工作线程死掉
                    log.exception("翻译线程异常")
                    self._on_event(("batch_done", batch.batch_id,
                                    ServiceError(tr("内部错误：{name}").format(name=type(e).__name__)),
                                    time.perf_counter() - t0))
        finally:
            client.close()

    def close(self) -> None:
        self._cancel.set()
        for client in list(self._clients):
            try:
                client.close()  # 打断在途的请求
            except Exception:  # noqa: BLE001
                pass
        for _ in self._threads:
            self._q.put(None)
        for t in self._threads:
            t.join(2.0)
