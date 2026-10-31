"""Server FastAPI: WebSocket chat, token, controllo Origin, static UI."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent import Agent
from .config import Config, ROOT
from .perception.screen import SHOTS_DIR
from .tools import launch as launch_tool
from .tools import perception as perception_tool

log = logging.getLogger("ayra")

UI_DIR = ROOT / "ui"

# Origin consentite. L'origine dell'estensione Opera viene aggiunta qui quando sarà pronta.
OPERA_EXTENSION_ORIGINS: list[str] = []


def create_app(cfg: Config, token: str) -> FastAPI:
    launch_tool.set_allowlist(cfg.launch.allowlist)
    perception_tool.set_config(cfg)

    allowed_origins = {
        f"http://127.0.0.1:{cfg.server.port}",
        f"http://localhost:{cfg.server.port}",
    }
    allowed_origins |= set(OPERA_EXTENSION_ORIGINS)

    app = FastAPI(title="Ayra", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

    def require_token(request: Request) -> None:
        supplied = request.query_params.get("token") or request.headers.get("x-ayra-token")
        if not supplied or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="token non valido o mancante")

    @app.get("/health")
    async def health(request: Request):
        require_token(request)
        from .tools import all_tools

        return {
            "ok": True,
            "model": cfg.llm.model,
            "supports_tools": cfg.llm.supports_tools,
            "tools": [spec.name for spec in all_tools()],
        }

    @app.get("/")
    async def index(request: Request):
        require_token(request)
        return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/shots/{name}")
    async def shot(name: str, request: Request):
        require_token(request)
        if not name or "/" in name or "\\" in name or ".." in name:
            raise HTTPException(status_code=400, detail="nome non valido")
        path = SHOTS_DIR / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="non trovato")
        return FileResponse(path)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        origin = websocket.headers.get("origin", "")
        if origin and origin not in allowed_origins:
            await websocket.close(code=1008)
            return
        # Se Origin è assente (client non-browser), accettiamo: il token resta l'autenticazione.
        supplied = websocket.query_params.get("token")
        if not supplied or not hmac.compare_digest(supplied, token):
            await websocket.close(code=1008)
            return

        await websocket.accept()
        agent = Agent(cfg)
        send_lock = asyncio.Lock()

        async def emit(event: dict) -> None:
            try:
                async with send_lock:
                    await websocket.send_json(event)
            except Exception:
                pass

        run_task: asyncio.Task | None = None
        try:
            while True:
                message = await websocket.receive_json()
                kind = message.get("type")
                if kind == "user":
                    text = (message.get("text") or "").strip()
                    if not text:
                        continue
                    if run_task is not None and not run_task.done():
                        await emit({"type": "error", "kind": "busy", "message": "Sto ancora elaborando la richiesta precedente."})
                        continue
                    run_task = asyncio.create_task(agent.handle(text, emit))
                elif kind == "confirm":
                    resolved = agent.permissions.resolve(str(message.get("id", "")), bool(message.get("allow")))
                    if not resolved:
                        await emit({"type": "error", "kind": "confirm", "message": "Richiesta di conferma scaduta o sconosciuta."})
                elif kind == "reset":
                    agent.history.clear()
                    await emit({"type": "system", "text": "Nuova conversazione."})
                else:
                    await emit({"type": "error", "kind": "protocol", "message": f"Tipo di messaggio sconosciuto: {kind}"})
        except WebSocketDisconnect:
            pass
        finally:
            agent.permissions.cancel_all()
            if run_task is not None and not run_task.done():
                run_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await run_task

    return app
