"""Tool di percezione (read-only): testo finestra, albero UI, descrizione schermo."""

from __future__ import annotations

import win32gui

from ayra.config import Config
from ayra.perception import ocr, screen, uia, vision
from ayra.perception.guard import any_blocked_visible, is_blocked
from ayra.permissions import Permission
from ayra.tools import tool

_cfg: Config | None = None


def set_config(cfg: Config) -> None:
    global _cfg
    _cfg = cfg
    from ayra.tools import set_vision_enabled

    set_vision_enabled(bool(cfg.vision.enabled and (cfg.vision.model or "").strip()))


def _config() -> Config:
    if _cfg is not None:
        return _cfg
    from ayra.config import load_config

    return load_config()


def _vision_config():
    return _config().vision


@tool(
    "read_window_text",
    "Legge il TESTO visibile nella finestra attiva (o in una finestra indicata per titolo). "
    "Usalo quando l'utente chiede 'leggi', 'cosa c'è scritto', 'cosa ho scritto', 'cosa dice'.",
    {
        "type": "object",
        "properties": {
            "window": {"type": "string", "description": "Sottostringa del titolo della finestra (opzionale)."},
            "ocr": {"type": "string", "enum": ["auto", "never", "force"], "description": "OCR di fallback."},
        },
        "additionalProperties": False,
    },
    Permission.READ,
)
def read_window_text(window: str | None = None, ocr: str = "auto") -> dict:
    cfg = _config()
    result = uia.get_text(window, cfg)
    if not result.get("ok"):
        return result

    text = result.get("text", "") or ""
    source = "uia"
    rect = result.get("rect") or {}
    capture_rect = None
    if rect.get("right", 0) > rect.get("left", 0):
        capture_rect = {
            "left": rect["left"],
            "top": rect["top"],
            "width": rect["right"] - rect["left"],
            "height": rect["bottom"] - rect["top"],
        }

    if ocr in ("auto", "force") and (ocr == "force" or len(text) < cfg.perception.ocr_min_chars):
        # skip OCR if a blocked window overlaps the target
        if any_blocked_visible(cfg, capture_rect):
            return {
                "ok": True,
                "process": result.get("process", ""),
                "title": result.get("title", ""),
                "source": "uia",
                "text": text[: cfg.perception.max_chars],
                "truncated": bool(result.get("truncated", False)),
                "note": "OCR saltato: finestra sensibile visibile/sovrapposta.",
            }
        try:
            shot = screen.capture(capture_rect, 3000)
            from ayra.perception import ocr as _ocr_mod

            ocr_text = _ocr_mod.ocr_image(shot["path"])
            if ocr_text:
                text = (text + "\n" + ocr_text).strip() if text else ocr_text
                source = "uia+ocr" if result.get("text") else "ocr"
        except Exception as exc:
            if ocr == "force":
                return {"ok": False, "error": str(exc)}

    text = text[: cfg.perception.max_chars]
    return {
        "ok": True,
        "process": result.get("process", ""),
        "title": result.get("title", ""),
        "source": source,
        "text": text,
        "truncated": bool(result.get("truncated", False)),
    }


@tool(
    "get_ui_tree",
    "Elenca la STRUTTURA dei controlli di una finestra (pulsanti, menu, campi) con posizione. "
    "Usalo quando l'utente chiede 'struttura', 'controlli', 'pulsanti'.",
    {
        "type": "object",
        "properties": {
            "window": {"type": "string", "description": "Sottostringa del titolo (opzionale)."},
            "max_depth": {"type": "integer", "description": "Profondità massima (opzionale)."},
        },
        "additionalProperties": False,
    },
    Permission.READ,
)
def get_ui_tree(window: str | None = None, max_depth: int | None = None) -> dict:
    cfg = _config()
    return uia.get_tree(window, max_depth, cfg)


def _vision_summary(args: dict) -> str:
    from ayra.perception.vision import is_local

    cfg = _vision_config()
    if not is_local(cfg):
        return "Inviare uno screenshot a un servizio REMOTO per descriverlo. Confermare?"
    return "Descrivere lo schermo con il modello di visione locale."


@tool(
    "describe_screen",
    "Descrive con un modello di visione ciò che si vede sullo schermo o nella finestra attiva. "
    "Usalo quando l'utente chiede 'descrivi lo schermo', 'cosa vedi'.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Domanda specifica (opzionale)."},
            "scope": {"type": "string", "enum": ["window", "screen"], "description": "window o screen."},
        },
        "additionalProperties": False,
    },
    Permission.CONFIRM,
    summary=_vision_summary,
    auto_when=lambda args: __import__("ayra.perception.vision", fromlist=["is_local"]).is_local(_vision_config()),
)
def describe_screen(question: str | None = None, scope: str = "window") -> dict:
    cfg = _config()
    cfg_vision = cfg.vision
    if not cfg_vision.enabled or not (cfg_vision.model or "").strip():
        return {"ok": False, "error": (
            "Vision disabilitata. Per abilitarla imposta in config.yaml:\n"
            "vision:\n  enabled: true\n  base_url: http://localhost:11434/v1\n  model: <modello-con-vision>\n"
            "Esempio locale: ollama pull llava (o minicpm-v)."
        )}

    if scope == "window":
        from ayra.config import load_config
        from ayra.perception import target as target_mod

        tcfg = load_config()
        info = target_mod.resolve_target(None, tcfg)
        hwnd = info.get("hwnd")
        if hwnd:
            if is_blocked(info.get("process", ""), info.get("title", ""), cfg):
                return {"ok": False, "error": "blocked by privacy policy"}
            import win32gui as _w

            left, top, right, bottom = _w.GetWindowRect(hwnd)
            rect = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        else:
            rect = None
    else:
        rect = None

    if scope == "screen":
        from ayra.perception.guard import any_blocked_visible as abv
        if abv(cfg, None):
            return {"ok": False, "error": "blocked by privacy policy"}

    try:
        shot = screen.capture(rect, cfg_vision.max_side or 1280)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    ok, description = vision.describe(cfg_vision, shot["path"], question)
    if not ok:
        return {"ok": False, "error": description}
    return {"ok": True, "description": description, "image": shot["filename"]}
