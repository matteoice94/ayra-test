"""Registro dei tool: una sola definizione genera schema LLM ed esecuzione."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable

from ..permissions import Permission

MAX_RESULT_CHARS = 6000
_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    permission: Permission
    func: Callable[..., Any]
    summary: Callable[[dict], str] | None = None
    auto_when: Callable[[dict], bool] | None = None


_REGISTRY: dict[str, ToolSpec] = {}
_VISION_ENABLED: bool = False


def set_vision_enabled(enabled: bool) -> None:
    global _VISION_ENABLED
    _VISION_ENABLED = bool(enabled)


def tool(
    name: str,
    description: str,
    parameters: dict,
    permission: Permission,
    summary: Callable[[dict], str] | None = None,
    auto_when: Callable[[dict], bool] | None = None,
):
    """Decorator che registra un tool. `summary` rende leggibile la conferma."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if name in _REGISTRY:
            raise ValueError(f"tool duplicato: {name}")
        _REGISTRY[name] = ToolSpec(name, description, parameters, permission, func, summary, auto_when)
        return func

    return decorator


def get_tool(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def all_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def openai_tools() -> list[dict]:
    """Schemi nel formato atteso da /chat/completions."""
    result = []
    for spec in _REGISTRY.values():
        if spec.name == "describe_screen" and not _VISION_ENABLED:
            continue
        result.append(
            {
                "type": "function",
                "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters},
            }
        )
    return result


def describe(spec: ToolSpec, args: dict) -> str:
    if spec.summary:
        try:
            return spec.summary(args)
        except Exception:
            pass
    return f"Eseguire {spec.name} con {json.dumps(args, ensure_ascii=False)}"


def _validate(spec: ToolSpec, args: dict) -> None:
    if not isinstance(args, dict):
        raise ValueError("gli argomenti devono essere un oggetto JSON")
    schema = spec.parameters or {}
    properties = schema.get("properties") or {}
    missing = set(schema.get("required") or []) - args.keys()
    if missing:
        raise ValueError(f"argomenti mancanti: {', '.join(sorted(missing))}")
    for key, value in args.items():
        prop = properties.get(key)
        if prop is None:
            if schema.get("additionalProperties", True) is False:
                raise ValueError(f"argomento sconosciuto: {key}")
            continue
        expected = _TYPES.get(prop.get("type"))
        if expected and not isinstance(value, expected):
            raise ValueError(f"'{key}' deve essere di tipo {prop.get('type')}")


async def run_tool(name: str, args: dict) -> tuple[bool, str]:
    """Esegue un tool e ritorna (ok, risultato testuale per l'LLM). Non solleva mai."""
    spec = _REGISTRY.get(name)
    if spec is None:
        return False, f"tool sconosciuto: {name} (disponibili: {', '.join(_REGISTRY)})"
    try:
        _validate(spec, args)
        if inspect.iscoroutinefunction(spec.func):
            result = await spec.func(**args)
        else:
            result = await asyncio.to_thread(spec.func, **args)
    except (TypeError, ValueError) as exc:
        return False, f"argomenti non validi per {name}: {exc}"
    except Exception as exc:
        return False, f"{name} è fallito: {type(exc).__name__}: {exc}"

    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n… (risultato troncato)"
    return True, text


# Import in fondo: i moduli si registrano da soli al caricamento.
from . import launch, perception, window  # noqa: E402,F401
