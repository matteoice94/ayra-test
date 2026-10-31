"""Loop agente: LLM -> tool -> LLM, fino a max_steps."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from .config import Config
from .llm import LLMError, LLMEvent, stream_chat
from .permissions import Permission, PermissionManager
from .tools import describe, get_tool, openai_tools, run_tool

Emit = Callable[[dict], Awaitable[None]]

FALLBACK_INSTRUCTIONS = (
    "\n\nSTRUMENTI DISPONIBILI (il modello non supporta tool calling nativo):\n"
    "Se ti serve usare uno strumento, rispondi SOLO con un oggetto JSON nel formato:\n"
    '{{"tool": "<nome>", "args": {{<argomenti>}}}}\n'
    "Non aggiungere altro testo. Dopo il risultato riceverai un messaggio 'RISULTATO TOOL ...'.\n"
    "Strumenti:\n{tools}\n"
)


class Agent:
    def __init__(self, cfg: Config, permissions: PermissionManager | None = None):
        self.cfg = cfg
        self.permissions = permissions or PermissionManager()
        self.history: list[dict] = []

    async def handle(self, text: str, emit: Emit) -> None:
        self.history.append({"role": "user", "content": text})
        self._trim()
        try:
            await self._loop(emit)
        except LLMError as exc:
            await emit({"type": "error", "kind": exc.kind, "message": exc.message})
        except Exception as exc:  # mai far cadere il server
            await emit({"type": "error", "kind": "internal", "message": f"Errore interno: {type(exc).__name__}: {exc}"})
        finally:
            await emit({"type": "done"})

    async def _loop(self, emit: Emit) -> None:
        native = bool(self.cfg.llm.supports_tools)
        for step_index in range(self.cfg.agent.max_steps):
            messages = [self._system_message()] + self.history
            if step_index == 0:
                from .agent_hints import hint_for

                last_user = ""
                for m in reversed(self.history):
                    if m.get("role") == "user":
                        last_user = m.get("content", "")
                        break
                hint = hint_for(last_user, getattr(self.cfg.vision, "enabled", False))
                if hint:
                    messages = messages + [
                        {
                            "role": "system",
                            "content": (
                                f"Per questa richiesta devi chiamare lo strumento {hint} ora. "
                                "Non chiedere all'utente di aspettare e non descrivere cosa farai. "
                                "Se l'utente nomina un'applicazione (es. Blocco note, Discord) passala nel parametro window."
                            ),
                        }
                    ]
            text_parts: list[str] = []
            calls: list[dict] = []

            async for event in stream_chat(self.cfg.llm, messages, openai_tools() if native else None):
                if event.type == "text":
                    text_parts.append(event.text)
                    await emit({"type": "token", "text": event.text})
                elif event.type == "tool_calls":
                    calls = event.tool_calls

            if calls:
                self._append_assistant_tool_message(text_parts, calls, native)
                for call in calls:
                    await self._run_call(call, emit, native)
                continue

            answer = "".join(text_parts).strip()
            self.history.append({"role": "assistant", "content": answer})
            return

        await emit(
            {
                "type": "token",
                "text": f"\n\n[Interrotto: raggiunto il limite di {self.cfg.agent.max_steps} passi.]",
            }
        )

    async def _run_call(self, call: dict, emit: Emit, native: bool) -> None:
        name = call["function"]["name"]
        raw_args = call["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}

        await emit({"type": "tool_call", "id": call["id"], "name": name, "args": args})

        spec = get_tool(name)
        if spec is None:
            ok, result = False, f"tool sconosciuto: {name}"
            description = f"Eseguire il tool sconosciuto «{name}»"
        else:
            description = describe(spec, args)
            permission = spec.permission
            if spec.auto_when and spec.auto_when(args):
                permission = Permission.AUTO

            allowed, reason = await self.permissions.authorize(name, permission, description, args, emit)
            if not allowed:
                ok, result = False, "denied by user"
                if reason == "timeout":
                    result = "denied by user (timeout)"
            else:
                ok, result = await run_tool(name, args)

        await emit({"type": "tool_result", "id": call["id"], "name": name, "ok": ok, "result": result})

        if native:
            self.history.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        else:
            self.history.append({"role": "assistant", "content": json.dumps({"tool": name, "args": args}, ensure_ascii=False)})
            self.history.append(
                {
                    "role": "user",
                    "content": f"RISULTATO TOOL {name} ({'ok' if ok else 'errore'}):\n{result}\n\nRispondi ora all'utente usando questo risultato. Se ti serve un altro strumento, usa lo stesso formato JSON.",
                }
            )

    def _append_assistant_tool_message(self, text_parts: list[str], calls: list[dict], native: bool) -> None:
        text = "".join(text_parts).strip()
        if native:
            self.history.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {"id": c["id"], "type": "function", "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or "{}"}}
                        for c in calls
                    ],
                }
            )
            return
        if text:
            self.history.append({"role": "assistant", "content": text})

    def _system_message(self) -> dict:
        prompt = self.cfg.agent.system_prompt.strip()
        if not self.cfg.llm.supports_tools:
            tools_text = json.dumps(
                [{"name": t["function"]["name"], "description": t["function"]["description"], "parameters": t["function"]["parameters"]} for t in openai_tools()],
                ensure_ascii=False,
                indent=2,
            )
            prompt += FALLBACK_INSTRUCTIONS.format(tools=tools_text)
        return {"role": "system", "content": prompt}

    def _trim(self) -> None:
        limit = self.cfg.agent.history_messages
        if len(self.history) <= limit:
            return
        self.history = self.history[-limit:]
        while self.history and self.history[0].get("role") == "tool":
            self.history.pop(0)
        while self.history and self.history[0].get("role") == "assistant" and self.history[0].get("tool_calls"):
            self.history.pop(0)
