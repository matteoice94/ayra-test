"""Risoluzione finestra target: esclude la finestra di Ayra stessa."""

from __future__ import annotations

import win32gui
import win32process
import psutil

from ayra.tools.window import NOISE_CLASSES


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def _is_ayra(title: str, cfg) -> bool:
    self_title = getattr(cfg.perception, "self_title", "Ayra")
    return (self_title or "").lower() in (title or "").lower()


def _valid(hwnd, cfg) -> bool:
    if not win32gui.IsWindowVisible(hwnd):
        return False
    if win32gui.GetClassName(hwnd) in NOISE_CLASSES:
        return False
    title = win32gui.GetWindowText(hwnd) or ""
    if not title.strip():
        return False
    if _is_ayra(title, cfg):
        return False
    return True


def resolve_target(window_substr: str | None, cfg) -> dict:
    self_title = getattr(cfg.perception, "self_title", "Ayra")
    windows = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)

    if window_substr:
        needle = window_substr.strip().lower()
        for hwnd in windows:
            if not _valid(hwnd, cfg):
                continue
            title = win32gui.GetWindowText(hwnd) or ""
            if needle in title.lower():
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                return {
                    "hwnd": hwnd,
                    "title": title,
                    "process": _process_name(pid),
                    "minimized": bool(win32gui.IsIconic(hwnd)),
                    "via": "match",
                }
        return {"hwnd": None, "title": "", "process": "", "minimized": False, "via": "match"}

    # foreground
    fg = win32gui.GetForegroundWindow()
    fg_title = win32gui.GetWindowText(fg) or ""
    if fg and _valid(fg, cfg) and self_title.lower() not in fg_title.lower():
        _, pid = win32process.GetWindowThreadProcessId(fg)
        return {
            "hwnd": fg,
            "title": fg_title,
            "process": _process_name(pid),
            "minimized": bool(win32gui.IsIconic(fg)),
            "via": "foreground",
        }

    # foreground is Ayra (or invalid): pick next valid in z-order
    started = False
    for hwnd in windows:
        if hwnd == fg:
            started = True
            continue
        if not started:
            continue
        if not _valid(hwnd, cfg):
            continue
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return {
            "hwnd": hwnd,
            "title": title,
            "process": _process_name(pid),
            "minimized": bool(win32gui.IsIconic(hwnd)),
            "via": "previous",
        }

    # fallback: first valid window
    for hwnd in windows:
        if not _valid(hwnd, cfg):
            continue
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return {
            "hwnd": hwnd,
            "title": title,
            "process": _process_name(pid),
            "minimized": bool(win32gui.IsIconic(hwnd)),
            "via": "previous",
        }

    return {"hwnd": None, "title": "", "process": "", "minimized": False, "via": "previous"}