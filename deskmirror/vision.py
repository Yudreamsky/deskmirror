"""看图翻译：把魔镜框里的画面发给能看图的模型（多模态），流式拿回译文。

用户按了才发（快捷键、标签上的“看图”），不在实时流程里：多模态模型慢（每张图几秒到十几秒），
也给不出精确到像素的文字位置，适合漫画、艺术字、图片里的字、识别不出的游戏字体。
默认用本机 Ollama（画面不出本机）；发给云端服务前由界面先问用户。
"""
from __future__ import annotations

import base64
import json
import threading
import time
from typing import Callable
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np

from .config import LANGUAGES, VisionConfig
from .i18n import tr
from .translator import _SOURCE_DESC, _TARGET_DESC, ServiceError, _http_error, make_client


def is_local(base_url: str) -> bool:
    """地址是不是本机（本机的服务不用每次问）。"""
    from .config import is_local_url
    return is_local_url(base_url)


def host_of(base_url: str) -> str:
    return urlparse(base_url.strip() if "://" in base_url else "http://" + base_url.strip()).hostname or base_url


def vision_prompt(target: str, source: str = "auto") -> str:
    lang = _TARGET_DESC.get(target, LANGUAGES.get(target, target))
    src = f" The text is mostly {_SOURCE_DESC[source]}." if source in _SOURCE_DESC else ""
    return (f"Read all the text in this screenshot and translate it into {lang}.{src} "
            "Output only the translation, in reading order (top to bottom, left to right; for manga or comics, "
            "follow the panels). Put each text area (paragraph, speech bubble, label, button, sign, sound effect) "
            "on its own line. Translate signs and sound effects too; keep only names, code and numbers as they are. "
            "If a line is already in the target language, repeat it. "
            f"If the image contains no text, describe what it shows in one or two sentences in {lang}.")


def encode_image(bgr: np.ndarray, max_side: int) -> tuple[str, int, int]:
    """缩到长边不超过 max_side（省时间、省费用），转成 JPEG 的 base64。返回 (base64, 宽, 高)。"""
    h, w = bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError(tr("图片编码失败"))
    return base64.b64encode(buf.tobytes()).decode("ascii"), bgr.shape[1], bgr.shape[0]


def build_request(cfg: VisionConfig, prompt: str, image_b64: str) -> tuple[str, dict, dict]:
    """(地址, 请求体, 请求头)。Ollama 原生接口把图放在 images 里；OpenAI 兼容接口用 data URL。"""
    base = cfg.base_url.strip().rstrip("/")
    if cfg.protocol == "ollama":
        payload = {"model": cfg.model, "stream": True, "think": False, "keep_alive": "30m",
                   "options": {"temperature": 0.2, "num_ctx": cfg.num_ctx},
                   "messages": [{"role": "user", "content": prompt, "images": [image_b64]}]}
        return f"{base}/api/chat", payload, {}
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    payload = {"model": cfg.model, "stream": True, "temperature": 0.2,
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}]}
    return f"{base}/chat/completions", payload, headers


def _no_vision(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in ("does not support image", "doesn't support image", "not support vision",
                                "image input", "multimodal", "vision is not", "unsupported content type"))


def stream_vision(cfg: VisionConfig, target: str, source: str, image_b64: str, on_text: Callable[[str], None],
                  cancel: threading.Event) -> float:
    """发一张图，译文一段段交给 on_text；返回用时（秒）。失败抛 ServiceError（说明是给用户看的）。"""
    if not cfg.base_url.strip():
        raise ServiceError(tr("还没有填写看图翻译的服务地址"), retryable=False)
    if not cfg.model.strip():
        raise ServiceError(tr("还没有填写看图翻译用的模型"), retryable=False)
    url, payload, headers = build_request(cfg, vision_prompt(target, source), image_b64)
    t0 = time.perf_counter()
    try:
        with make_client(cfg) as client:
            for attempt in range(2):
                with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        if attempt == 0 and "think" in payload and resp.status_code == 400 \
                                and "think" in resp.text.lower():
                            payload.pop("think")       # 这个模型不支持思考开关：去掉参数重发一次
                            continue
                        if _no_vision(resp.text):
                            raise ServiceError(tr("模型 {model} 不能看图，请在设置里换一个能看图的模型")
                                               .format(model=cfg.model), retryable=False)
                        raise _http_error(resp)
                    for line in resp.iter_lines():
                        if cancel.is_set():
                            return time.perf_counter() - t0
                        piece = _piece(cfg.protocol, line, cfg.model)
                        if piece:
                            on_text(piece)
                    break
    except httpx.TimeoutException:
        raise ServiceError(tr("看图翻译响应超时（多模态模型比较慢，可以稍后再试，或换一个快些的模型）")) from None
    except httpx.ConnectError:
        raise ServiceError(tr("连不上看图翻译的服务（服务没启动或地址不对）")) from None
    except (httpx.RemoteProtocolError, httpx.ReadError):
        raise ServiceError(tr("看图翻译的连接中途断开")) from None
    except httpx.HTTPError as e:
        raise ServiceError(tr("网络错误：{name}").format(name=type(e).__name__)) from None
    return time.perf_counter() - t0


def _piece(protocol: str, line: str, model: str) -> str:
    """流式响应的一行 → 新增的文字。"""
    if protocol == "ollama":
        if not line.strip():
            return ""
        data = json.loads(line)
        if data.get("error"):
            err = str(data["error"])
            if _no_vision(err):
                raise ServiceError(tr("模型 {model} 不能看图，请在设置里换一个能看图的模型").format(model=model),
                                   retryable=False)
            raise ServiceError(tr("服务报错：{detail}").format(detail=err[:120]))
        return (data.get("message") or {}).get("content", "")
    if not line.startswith("data:"):
        return ""
    data = line[5:].strip()
    if data == "[DONE]":
        return ""
    try:
        obj = json.loads(data)
    except ValueError:
        return ""
    if obj.get("error"):
        raise ServiceError(tr("服务报错：{detail}").format(detail=str(obj["error"])[:120]))
    choices = obj.get("choices") or []
    return ((choices[0].get("delta") or {}).get("content") or "") if choices else ""
