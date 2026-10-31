"""Client LLM OpenAI-compatible: streaming SSE, tool calling nativo, fallback JSON."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from .config import LLMConfig


class LLMError(Exception):
    """Errore LLM già tradotto in un messaggio mostrabile all'utente."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class LLMEvent:
    type: str  # "text" | "tool_calls"
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)


def _endpoint(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def _http_error(status: int, body: str, base_url: str, model: str) -> LLMError:
    detail = " ".join(body.split())[:200]
    if status == 401:
        return LLMError("auth", "API key rifiutata (401). Controlla llm.api_key o la variabile AYRA_LLM_API_KEY.")
    if status == 403:
        return LLMError("auth", "Accesso negato (403). La key non ha i permessi per questo modello.")
    if status == 404:
        return LLMError("model", f"Endpoint o modello non trovato (404): {base_url} / {model}. Controlla llm.base_url e llm.model.")
    if status == 429:
        return LLMError("rate_limit", "Troppe richieste o quota esaurita (429). Aspetta un minuto, cambia modello o passa a uno locale.")
    if status >= 500:
        return LLMError("server", f"Il servizio LLM ha risposto {status}. Riprova più tardi.")
    return LLMError("http", f"Errore LLM ({status}): {detail}")


def _friendly_connect(base_url: str) -> str:
    return (
        f"Non riesco a raggiungere il modello su {base_url}. "
        "Se usi Ollama, controlla che sia avviato (ollama serve) e che llm.base_url sia corretto."
    )


async def _raw_stream(cfg: LLMConfig, payload: dict) -> AsyncIterator[dict]:
    """Emette i chunk JSON grezzi del provider, sia SSE sia risposta non-streaming."""
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    timeout = httpx.Timeout(cfg.timeout, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", _endpoint(cfg.base_url), json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise _http_error(resp.status_code, body, cfg.base_url, cfg.model)

                if "event-stream" not in resp.headers.get("content-type", ""):
                    body = (await resp.aread()).decode("utf-8", "replace")
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError as exc:
                        raise LLMError("bad_response", f"Risposta non valida dal modello: {body[:200]}") from exc
                    yield _as_chunk(data)
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue
    except httpx.ConnectError as exc:
        raise LLMError("unreachable", _friendly_connect(cfg.base_url)) from exc
    except httpx.TimeoutException as exc:
        raise LLMError(
            "timeout",
            f"Il modello non ha risposto entro {cfg.timeout:.0f}s. Prova un modello più piccolo o aumenta llm.timeout.",
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError("network", f"Connessione al modello interrotta ({type(exc).__name__}).") from exc


def _as_chunk(data: dict) -> dict:
    """Normalizza una risposta non-streaming nella forma di un chunk SSE."""
    choices = data.get("choices") or []
    if not choices:
        return {"choices": [{}]}
    message = choices[0].get("message") or {}
    calls = message.get("tool_calls") or []
    for index, call in enumerate(calls):
        call.setdefault("index", index)
    return {"choices": [{"delta": {"content": message.get("content"), "tool_calls": calls}}]}


def _merge_tool_delta(buffer: dict[int, dict], delta: dict) -> None:
    has_index = "index" in delta
    index = delta.get("index", 0)
    incoming_id = delta.get("id") or ""
    if (
        not has_index
        and index in buffer
        and buffer[index].get("name")
        and incoming_id
        and incoming_id != buffer[index].get("id")
    ):
        index = (max(buffer) + 1) if buffer else 0
    slot = buffer.setdefault(index, {"id": "", "name": "", "arguments": ""})
    if incoming_id:
        slot["id"] = incoming_id
    function = delta.get("function") or {}
    if function.get("name"):
        slot["name"] += function["name"]
    if function.get("arguments"):
        slot["arguments"] += function["arguments"]


def _finalize_tool_calls(buffer: dict[int, dict]) -> list[dict]:
    calls = []
    for index in sorted(buffer):
        slot = buffer[index]
        if not slot["name"]:
            continue
        calls.append(
            {
                "id": slot["id"] or f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
            }
        )
    return calls


_FENCE = re.compile(r"```[A-Za-z0-9_+-]*")


def _json_objects(text: str) -> list[str]:
    """Estrae gli oggetti JSON bilanciati dal testo, ignorando il rumore attorno."""
    found, depth, start = [], 0, None
    for position, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = position
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                found.append(text[start : position + 1])
                start = None
    return found


def _normalize_call(obj: dict) -> dict | None:
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("tool_calls"), list) and obj["tool_calls"]:
        return _normalize_call(obj["tool_calls"][0])

    function = obj.get("function") if isinstance(obj.get("function"), dict) else {}
    name = obj.get("tool") or obj.get("name") or function.get("name")
    args = obj.get("args", obj.get("arguments", obj.get("parameters", function.get("arguments", {}))))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(args, dict):
        args = {}
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name.strip(), "arguments": json.dumps(args, ensure_ascii=False)},
    }


def parse_tool_call(text: str) -> dict | None:
    """Trova una tool call JSON nel testo, tollerando code fence e testo extra."""
    cleaned = _FENCE.sub("", text)
    for candidate in _json_objects(cleaned):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        call = _normalize_call(obj)
        if call:
            return call
    return None


async def stream_chat(cfg: LLMConfig, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[LLMEvent]:
    """Genera eventi text/tool_calls. In fallback il testo è bufferizzato per non mostrare JSON."""
    native = bool(cfg.supports_tools and tools)
    payload: dict = {"model": cfg.model, "messages": messages, "stream": True, "temperature": 0.2}
    if native:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    text_parts: list[str] = []
    tool_buffer: dict[int, dict] = {}

    async for chunk in _raw_stream(cfg, payload):
        choices = chunk.get("choices") or [{}]
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if content:
            if native:
                yield LLMEvent("text", text=content)
            else:
                text_parts.append(content)
        if native:
            for tool_delta in delta.get("tool_calls") or []:
                _merge_tool_delta(tool_buffer, tool_delta)

    if native:
        if tool_buffer:
            yield LLMEvent("tool_calls", tool_calls=_finalize_tool_calls(tool_buffer))
        return

    full_text = "".join(text_parts)
    call = parse_tool_call(full_text)
    if call:
        yield LLMEvent("tool_calls", tool_calls=[call])
    elif full_text.strip():
        yield LLMEvent("text", text=full_text)
