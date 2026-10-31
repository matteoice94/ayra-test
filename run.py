"""Entry point: avvia Ayra con `python run.py`."""

from __future__ import annotations

import atexit
import ctypes
import logging
import secrets
import shutil
import threading
import webbrowser
from pathlib import Path

import uvicorn

from ayra.config import CONFIG_PATH, EXAMPLE_PATH, load_config
from ayra.perception.screen import cleanup_all
from ayra.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    cleanup_all()
    atexit.register(cleanup_all)

    if not CONFIG_PATH.exists() and EXAMPLE_PATH.exists():
        shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
        print("Creato config.yaml da config.example.yaml. Controlla modello e provider.")

    cfg = load_config()
    token = secrets.token_urlsafe(24)
    app = create_app(cfg, token)

    url = f"http://127.0.0.1:{cfg.server.port}/?token={token}"
    print(f"Ayra in ascolto su {url}")

    threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        uvicorn.run(app, host="127.0.0.1", port=cfg.server.port, log_level="info", access_log=False)
    except OSError as exc:
        print(f"Impossibile avviare il server sulla porta {cfg.server.port}: {exc}")


if __name__ == "__main__":
    main()
