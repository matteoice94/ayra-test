"""Livelli di permesso e flusso di conferma utente."""

from __future__ import annotations

import asyncio
import uuid
from enum import Enum
from typing import Any, Awaitable, Callable

Emit = Callable[[dict], Awaitable[None]]


class Permission(str, Enum):
    READ = "read"      # esegue subito, nessuna conferma
    CONFIRM = "confirm"  # chiede conferma all'utente
    AUTO = "auto"      # esegue subito, ma loggato in modo visibile


class PermissionManager:
    """Gestisce le conferme. Predisposto per kill switch e allowlist senza refactor."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self.enabled = True                 # kill switch futuro
        self.allowlist: set[str] = set()    # tool che bypassano la conferma
        self._pending: dict[str, asyncio.Future] = {}

    async def authorize(
        self,
        tool_name: str,
        permission: Permission,
        description: str,
        args: dict,
        emit: Emit,
    ) -> tuple[bool, str]:
        """Ritorna (permesso, motivo). Motivi: read, auto, allowlist, user, timeout, kill-switch."""
        if not self.enabled:
            return False, "kill-switch"
        if permission in (Permission.READ, Permission.AUTO):
            return True, permission.value
        if tool_name in self.allowlist:
            return True, "allowlist"

        request_id = uuid.uuid4().hex[:8]
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await emit(
            {
                "type": "confirm_request",
                "id": request_id,
                "tool": tool_name,
                "description": description,
                "args": args,
            }
        )
        try:
            allowed = await asyncio.wait_for(future, timeout=self.timeout)
        except asyncio.TimeoutError:
            return False, "timeout"
        finally:
            self._pending.pop(request_id, None)
        return bool(allowed), "user"

    def resolve(self, request_id: str, allow: bool) -> bool:
        """Chiamato dal server quando arriva confirm_response. False se la richiesta è scaduta."""
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(allow)
        return True

    def cancel_all(self) -> None:
        """Nega tutte le conferme pendenti (chiusura connessione)."""
        for future in self._pending.values():
            if not future.done():
                future.set_result(False)
        self._pending.clear()
