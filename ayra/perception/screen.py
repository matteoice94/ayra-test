"""Screenshot con mss + Pillow, salvati in %TEMP%\\ayra\\shots."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import mss
from PIL import Image


SHOTS_DIR = Path(os.environ.get("TEMP", ".")) / "ayra" / "shots"
MAX_KEEP = 5


def _clip(rect: dict, bounds: dict) -> dict:
    left = max(bounds["left"], rect["left"])
    top = max(bounds["top"], rect["top"])
    right = min(bounds["left"] + bounds["width"], rect["left"] + rect["width"])
    bottom = min(bounds["top"] + bounds["height"], rect["top"] + rect["height"])
    return {"left": left, "top": top, "width": max(0, right - left), "height": max(0, bottom - top)}


def capture(rect: dict | None = None, max_side: int = 1280) -> dict:
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        virtual = sct.monitors[0]
        if rect:
            target = _clip(rect, virtual)
        else:
            target = sct.monitors[1] if len(sct.monitors) > 1 else virtual
        if target["width"] <= 0 or target["height"] <= 0:
            raise ValueError("rettangolo di cattura vuoto o fuori schermo")
        shot = sct.grab(target)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)

    filename = f"shot_{uuid.uuid4().hex[:8]}.jpg"
    path = SHOTS_DIR / filename
    image.save(path, "JPEG", quality=80)

    # keep only last 5
    shots = sorted(SHOTS_DIR.glob("shot_*.jpg"), key=lambda p: p.stat().st_mtime)
    for old in shots[:-MAX_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass

    return {"path": str(path), "filename": filename, "width": image.width, "height": image.height}


def cleanup_all() -> None:
    """Cancella tutti gli screenshot salvati."""
    if not SHOTS_DIR.exists():
        return
    for p in SHOTS_DIR.iterdir():
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
