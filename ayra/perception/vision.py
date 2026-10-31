"""Client opzionale per modelli di visione (OpenAI-compatible)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ayra.config import VisionConfig


class VisionError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def is_local(cfg: VisionConfig) -> bool:
    host = (urlparse(cfg.base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _endpoint(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def describe(cfg: VisionConfig, image_path: str, question: str | None = None) -> tuple[bool, str]:
    if not cfg.enabled or not (cfg.model or "").strip():
        return False, (
            "Vision disabilitata. Per abilitarla imposta in config.yaml:\n"
            "vision:\n  enabled: true\n  base_url: http://localhost:11434/v1\n  model: <modello-con-vision>\n"
            "Esempio locale: ollama pull llava (o minicpm-v)."
        )

    path = Path(image_path)
    if not path.exists():
        return False, f"Immagine non trovata: {image_path}"

    try:
        data = path.read_bytes()
    except OSError as exc:
        return False, f"Impossibile leggere l'immagine: {exc}"

    mime = "image/jpeg"
    b64 = base64.b64encode(data).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    prompt = (question or "").strip() or "Descrivi brevemente ciò che vedi in questa immagine."
    payload = {
        "model": cfg.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "stream": False,
        "temperature": 0.2,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    try:
        with httpx.Client(timeout=httpx.Timeout(cfg.timeout, connect=10.0)) as client:
            resp = client.post(_endpoint(cfg.base_url), json=payload, headers=headers)
    except httpx.ConnectError:
        return False, f"Modello di visione non raggiungibile su {cfg.base_url}."
    except httpx.TimeoutException:
        return False, f"Il modello di visione non ha risposto entro {cfg.timeout:.0f}s."
    except httpx.HTTPError as exc:
        return False, f"Connessione al modello di visione interrotta ({type(exc).__name__})."

    if resp.status_code >= 400:
        if resp.status_code == 401:
            return False, "API key del modello di visione rifiutata (401)."
        if resp.status_code == 429:
            return False, "Troppe richieste al modello di visione (429)."
        return False, f"Errore modello di visione ({resp.status_code}): {resp.text[:200]}"

    try:
        data = resp.json()
        return True, (data["choices"][0]["message"]["content"] or "").strip() or "(nessuna descrizione)"
    except (KeyError, IndexError, ValueError):
        return False, "Risposta non valida dal modello di visione."
