"""Provider adapters for the in-app AI chat (W12, slice 1).

Stdlib only (urllib), no new dependencies. One attempt per call: NO automatic retry, so content is never
sent twice behind the user's back. The API key goes only into a request header (never a URL), redirects are
refused (a redirect could carry the header to a third host), non-local hosts must use https, and no error text
ever contains the key.

Content passed in here must already be anonymized and checked by the outbound guard (`guard.py`, slice 3).
This module knows nothing about the vault: it only speaks the wire protocols.

Public surface:
    Provider(kind, base_url, api_key, model)
    stream_chat(provider, messages, system="", max_tokens=1024, timeout=60, cancel=None) -> iterator of events
        ("delta", text) | ("usage", {"input": n, "output": n}) | ("done", reason)
    complete(...) -> (text, usage)           # same, collected
    list_models(provider, timeout) -> [model ids]
    test_connection(provider, timeout) -> {"ok": bool, "code": str, "message": str, "models": n}
Errors: LLMError(code, message). Codes: auth, rate_limit, network, timeout, refused, bad_request, server,
config, cancelled.
"""

from __future__ import annotations

import http.client
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator

KINDS = ("anthropic", "openai", "gemini", "openrouter", "custom")
DEFAULT_BASE = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "openrouter": "https://openrouter.ai/api",
}
# Curated fallback lists, used when the provider cannot list models. Names are examples the user can override.
CURATED_MODELS = {
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"],
    "openai": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o"],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash"],
    "openrouter": ["anthropic/claude-sonnet-4.5", "openai/gpt-4.1"],
    "custom": [],
}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
ANTHROPIC_VERSION = "2023-06-01"
USER_AGENT = "Anonymizer-chat/1"


class LLMError(Exception):
    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Provider:
    kind: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    def __repr__(self) -> str:       # the key must never reach a log through repr
        return f"Provider(kind={self.kind!r}, base_url={self.base_url!r}, model={self.model!r}, api_key=***)"

    @property
    def base(self) -> str:
        return (self.base_url or DEFAULT_BASE.get(self.kind, "")).rstrip("/")

    @property
    def is_local(self) -> bool:
        host = urllib.parse.urlsplit(self.base).hostname or ""
        return host in LOCAL_HOSTS or host.endswith(".localhost")


def validate(provider: Provider) -> None:
    if provider.kind not in KINDS:
        raise LLMError("config", "Неизвестный тип провайдера")
    parts = urllib.parse.urlsplit(provider.base)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LLMError("config", "Адрес сервера указан неверно")
    if parts.scheme == "http" and not provider.is_local:
        raise LLMError("config", "Для удалённых серверов разрешён только https (http допустим только для этого компьютера)")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise LLMError("config", "В адресе сервера не должно быть логина, пароля и параметров")
    from . import policy
    policy.enforce_host(provider.base)            # P1: optional administrator allow-list; no policy file = no restriction
    if provider.kind != "custom" and not provider.api_key:
        raise LLMError("auth", "Для этого провайдера не сохранён ключ API")
    if provider.kind == "custom" and not provider.is_local and not provider.api_key:
        raise LLMError("auth", "Для внешнего адреса нужен ключ API")


def scrub(text: str, provider: Provider) -> str:
    """Remove the key (and anything key-shaped) from text that may be shown or logged."""
    if provider.api_key:
        text = text.replace(provider.api_key, "***")
    return re.sub(r"(sk-|key-|AIza)[A-Za-z0-9_\-]{12,}", "***", text)


# -- transport ------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _opener(local: bool = False) -> urllib.request.OpenerDirector:
    """Local endpoints bypass any system proxy; remote ones follow the system proxy settings."""
    return urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}) if local else urllib.request.ProxyHandler())


def _headers(provider: Provider, streaming: bool) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT,
               "Accept": "text/event-stream" if streaming else "application/json"}
    if provider.kind == "anthropic":
        headers["x-api-key"] = provider.api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
    elif provider.kind == "gemini":
        headers["x-goog-api-key"] = provider.api_key
    elif provider.api_key:
        headers["Authorization"] = "Bearer " + provider.api_key
    return headers


def _http_error(provider: Provider, status: int, body: bytes) -> LLMError:
    detail = ""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        err = data.get("error", data) if isinstance(data, dict) else {}
        detail = err.get("message", "") if isinstance(err, dict) else str(err)
    except ValueError:
        pass
    detail = scrub(detail or "", provider)[:300]
    if status in (401, 403):
        return LLMError("auth", "Провайдер не принял ключ API (401/403)", status)
    if status == 429:
        return LLMError("rate_limit", "Достигнут лимит запросов или квоты провайдера (429)", status)
    if status == 408 or status == 504:
        return LLMError("timeout", "Провайдер не ответил вовремя", status)
    if status in (400, 404, 413, 422):
        return LLMError("bad_request", ("Провайдер отклонил запрос: " + detail) if detail else
                        "Провайдер отклонил запрос (название модели или размер?)", status)
    if status >= 500:
        return LLMError("server", "Ошибка на стороне провайдера (%d)" % status, status)
    return LLMError("server", "Неожиданный ответ провайдера (%d)" % status, status)


def _request(provider: Provider, url: str, payload: dict | None, timeout: float, streaming: bool):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=_headers(provider, streaming),
                                     method="POST" if payload is not None else "GET")
    try:
        return _opener(provider.is_local).open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(65536)
        except Exception:
            pass
        if 300 <= exc.code < 400:
            raise LLMError("config", "Сервер перенаправил запрос; перенаправления отклоняются из соображений безопасности", exc.code)
        raise _http_error(provider, exc.code, body) from None
    except (TimeoutError, http.client.HTTPException) as exc:
        raise LLMError("timeout" if isinstance(exc, TimeoutError) else "network",
                       "Провайдер не ответил вовремя" if isinstance(exc, TimeoutError)
                       else "Соединение с провайдером прервалось") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise LLMError("timeout", "Провайдер не ответил вовремя") from None
        if isinstance(exc.reason, ssl.SSLError):
            raise LLMError("network", "Не удалось установить защищённое соединение с провайдером (сертификат или TLS)") from None
        raise LLMError("network", "Не удаётся связаться с провайдером (сеть или адрес)") from None
    except OSError:
        raise LLMError("network", "Не удаётся связаться с провайдером (сеть или адрес)") from None


# -- request building -----------------------------------------------------------------------------


def _clean_messages(messages: list[dict]) -> list[dict]:
    out = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise LLMError("config", "Некорректное сообщение в переписке")
        out.append({"role": role, "content": content})
    if not out or out[-1]["role"] != "user":
        raise LLMError("config", "Последнее сообщение должно быть от пользователя")
    return out


def build_request(provider: Provider, messages: list[dict], system: str, max_tokens: int, stream: bool) -> tuple[str, dict]:
    """(url, json body). Exposed so the dry run and the outbound guard see exactly what would be sent."""
    messages = _clean_messages(messages)
    base = provider.base
    max_tokens = max(1, int(max_tokens))
    if provider.kind == "anthropic":
        body = {"model": provider.model, "max_tokens": max_tokens, "messages": messages, "stream": stream}
        if system:
            body["system"] = system
        return base + "/v1/messages", body
    if provider.kind == "gemini":
        contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in messages]
        body = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        name = urllib.parse.quote(provider.model, safe="")
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"{base}/v1beta/models/{name}:{action}", body
    # openai, openrouter, custom (OpenAI-compatible, Ollama, LM Studio)
    chat = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": provider.model, "messages": chat, "max_tokens": max_tokens, "stream": stream}
    if stream:
        body["stream_options"] = {"include_usage": True}
    root = base if base.rstrip("/").endswith("/v1") else base + "/v1"
    return root + "/chat/completions", body


# -- response parsing -----------------------------------------------------------------------------


def _sse(response, cancel: Callable[[], bool] | None) -> Iterator[tuple[str, str]]:
    event, data = "", []
    for raw in response:
        if cancel and cancel():
            raise LLMError("cancelled", "Остановлено")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, "\n".join(data)


def _parse_stream(provider: Provider, response, cancel) -> Iterator[tuple[str, object]]:
    usage = {"input": 0, "output": 0}
    reason = "stop"
    for event, raw in _sse(response, cancel):
        if raw.strip() == "[DONE]":
            break
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("error") and provider.kind != "gemini" or (provider.kind == "gemini" and "error" in data):
            err = data["error"]
            message = scrub(str(err.get("message", "")) if isinstance(err, dict) else str(err), provider)[:300]
            raise LLMError("server", "Провайдер сообщил об ошибке во время ответа" + (": " + message if message else ""))
        if provider.kind == "anthropic":
            kind = data.get("type") or event
            if kind == "content_block_delta":
                text = (data.get("delta") or {}).get("text")
                if text:
                    yield "delta", text
            elif kind == "message_start":
                usage["input"] = ((data.get("message") or {}).get("usage") or {}).get("input_tokens", 0)
            elif kind == "message_delta":
                usage["output"] = (data.get("usage") or {}).get("output_tokens", usage["output"])
                reason = (data.get("delta") or {}).get("stop_reason") or reason
        elif provider.kind == "gemini":
            for cand in data.get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    if part.get("text"):
                        yield "delta", part["text"]
                reason = cand.get("finishReason") or reason
            meta = data.get("usageMetadata") or {}
            if meta:
                usage = {"input": meta.get("promptTokenCount", 0), "output": meta.get("candidatesTokenCount", 0)}
        else:
            for choice in data.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield "delta", text
                reason = choice.get("finish_reason") or reason
            if data.get("usage"):
                usage = {"input": data["usage"].get("prompt_tokens", 0), "output": data["usage"].get("completion_tokens", 0)}
    if reason in ("content_filter", "SAFETY", "RECITATION", "refusal"):
        raise LLMError("refused", "Модель отказалась отвечать на этот запрос")
    yield "usage", usage
    yield "done", reason


def _parse_whole(provider: Provider, data: dict) -> tuple[str, dict, str]:
    if provider.kind == "anthropic":
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        usage = data.get("usage") or {}
        return text, {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}, data.get("stop_reason") or "stop"
    if provider.kind == "gemini":
        cand = (data.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [])
        meta = data.get("usageMetadata") or {}
        return text, {"input": meta.get("promptTokenCount", 0), "output": meta.get("candidatesTokenCount", 0)}, cand.get("finishReason") or "stop"
    choice = (data.get("choices") or [{}])[0]
    usage = data.get("usage") or {}
    return ((choice.get("message") or {}).get("content") or "",
            {"input": usage.get("prompt_tokens", 0), "output": usage.get("completion_tokens", 0)},
            choice.get("finish_reason") or "stop")


# -- public API -----------------------------------------------------------------------------------


def stream_chat(provider: Provider, messages: list[dict], system: str = "", max_tokens: int = 1024,
                timeout: float = 60.0, cancel: Callable[[], bool] | None = None, stream: bool = True
                ) -> Iterator[tuple[str, object]]:
    """One request, one attempt. Yields ("delta", text), then ("usage", {...}), ("done", reason)."""
    validate(provider)
    if not provider.model:
        raise LLMError("config", "Сначала выберите модель")
    url, body = build_request(provider, messages, system, max_tokens, stream)
    response = _request(provider, url, body, timeout, stream)
    try:
        if stream:
            try:
                yield from _parse_stream(provider, response, cancel)
            except (TimeoutError, OSError, http.client.HTTPException):
                raise LLMError("network", "Соединение прервалось во время ответа; уже полученный текст сохранён") from None
        else:
            try:
                data = json.loads(response.read(20_000_000).decode("utf-8", "replace"))
            except ValueError:
                raise LLMError("server", "Ответ провайдера не удалось разобрать") from None
            text, usage, reason = _parse_whole(provider, data if isinstance(data, dict) else {})
            if reason in ("content_filter", "SAFETY", "refusal"):
                raise LLMError("refused", "Модель отказалась отвечать на этот запрос")
            yield "delta", text
            yield "usage", usage
            yield "done", reason
    finally:
        response.close()


def complete(provider: Provider, messages: list[dict], system: str = "", max_tokens: int = 1024,
             timeout: float = 60.0, stream: bool = True) -> tuple[str, dict]:
    text, usage = [], {}
    for kind, value in stream_chat(provider, messages, system, max_tokens, timeout, stream=stream):
        if kind == "delta":
            text.append(value)
        elif kind == "usage":
            usage = value
    return "".join(text), usage


def list_models(provider: Provider, timeout: float = 15.0) -> list[str]:
    validate(provider)
    base = provider.base
    if provider.kind == "anthropic":
        url = base + "/v1/models"
    elif provider.kind == "gemini":
        url = base + "/v1beta/models"
    else:
        url = (base if base.endswith("/v1") else base + "/v1") + "/models"
    response = _request(provider, url, None, timeout, False)
    try:
        data = json.loads(response.read(5_000_000).decode("utf-8", "replace"))
    except ValueError:
        raise LLMError("server", "Список моделей не удалось прочитать") from None
    finally:
        response.close()
    items = data.get("data") if isinstance(data, dict) and "data" in data else (data.get("models") if isinstance(data, dict) else [])
    ids = []
    for item in items or []:
        name = item.get("id") or item.get("name") or ""
        ids.append(name.split("/", 1)[1] if provider.kind == "gemini" and name.startswith("models/") else name)
    return sorted({i for i in ids if i})


def test_connection(provider: Provider, timeout: float = 15.0) -> dict:
    """Never raises: returns a plain-language result. The model list doubles as the key check."""
    try:
        models = list_models(provider, timeout)
        return {"ok": True, "code": "ok", "message": "Connected", "models": models}
    except LLMError as exc:
        if exc.code == "bad_request" and provider.model:      # some providers have no list endpoint
            return {"ok": False, "code": exc.code, "message": exc.message, "models": CURATED_MODELS.get(provider.kind, [])}
        return {"ok": False, "code": exc.code, "message": exc.message, "models": []}
