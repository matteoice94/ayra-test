"""Privacy guard: blocca la lettura di app sensibili."""

from __future__ import annotations

import os

from ayra.config import Config


def is_blocked(process_name: str, title: str, cfg: Config | None = None) -> bool:
    p = (process_name or "").strip().lower()
    t = (title or "").strip().lower()
    processes = (cfg.perception.blocklist_processes if cfg else []) or []
    titles = (cfg.perception.blocklist_titles if cfg else []) or []
    for name in processes:
        if name and name.strip().lower() == p:
            return True
    for fragment in titles:
        if fragment and fragment.strip().lower() in t:
            return True
    return False


def any_blocked_visible(cfg: Config | None, target_rect: dict | None = None) -> bool:
    """True se esiste una finestra bloccata visibile (non minimizzata).

    Se target_rect è dato, conta solo le finestre bloccate che si sovrappongono
    al rettangolo (per saltare l'OCR su screenshot che le includono).
    """
    try:
        import win32gui
        import win32process
        import psutil
    except Exception:
        return False

    found = {"v": False}

    def to_rect(r):
        if "right" in r:
            return r["left"], r["top"], r["right"], r["bottom"]
        return r["left"], r["top"], r["left"] + r["width"], r["top"] + r["height"]

    target = to_rect(target_rect) if target_rect else None

    def cb(hwnd, _):
        if found["v"]:
            return True
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.IsIconic(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd) or ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid).name()
        except Exception:
            proc = ""
        if not is_blocked(proc, title, cfg):
            return True
        if target is None:
            found["v"] = True
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        tl, tt, tr, tb = target
        if left < tr and right > tl and top < tb and bottom > tt:
            found["v"] = True
            return False
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        return False
    return found["v"]
