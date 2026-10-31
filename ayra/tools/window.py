"""Tool finestre: finestra attiva e elenco delle finestre visibili."""

from __future__ import annotations

import psutil
import win32gui
import win32process

from ..permissions import Permission
from . import tool

# Finestre di sistema che non interessano all'utente.
NOISE_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow",

    "DV2ControlHost",
    "MsgrIMEWindowClass",
    "SysShadow",
    "TaskListThumbnailWnd",
    "IME",
    "ForegroundStaging",
    "MultitaskingViewFrame",
    "XamlExplorerHostIslandWindow",
}
MAX_WINDOWS = 60


def _process_info(pid: int) -> tuple[str, str]:
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        try:
            exe = proc.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            exe = ""
        return name, exe
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return "", ""


@tool(
    "get_active_window",
    "Restituisce la finestra attualmente in primo piano (quella che l'utente sta usando). Usala quando chiede 'che finestra sto usando' o simili.",
    {"type": "object", "properties": {}, "additionalProperties": False},
    Permission.READ,
)
def get_active_window() -> dict:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return {"ok": False, "error": "Nessuna finestra in primo piano (desktop o schermata di blocco)."}

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process, exe = _process_info(pid)
    title = win32gui.GetWindowText(hwnd)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    result = {
        "ok": True,
        "title": title,
        "class": win32gui.GetClassName(hwnd),
        "process": process,
        "pid": pid,
        "exe": exe,
        "rect": {"left": left, "top": top, "right": right, "bottom": bottom, "width": right - left, "height": bottom - top},
        "minimized": bool(win32gui.IsIconic(hwnd)),
    }
    if "ayra" in (title or "").lower():
        from ayra.config import load_config
        from ayra.perception import target as target_mod

        cfg = load_config()
        info = target_mod.resolve_target(None, cfg)
        if info.get("hwnd"):
            result["user_window"] = {"title": info["title"], "process": info["process"]}
    return result


@tool(
    "list_windows",
    "Elenca tutte le finestre visibili aperte, con titolo e processo. Usala per 'che programmi ho aperti'.",
    {"type": "object", "properties": {}, "additionalProperties": False},
    Permission.READ,
)
def list_windows() -> dict:
    found: list[dict] = []

    def collect(hwnd: int, _extra) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title or win32gui.GetClassName(hwnd) in NOISE_CLASSES:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process, _exe = _process_info(pid)
        if not process:
            return True
        found.append({"title": title, "process": process, "pid": pid})
        return True

    win32gui.EnumWindows(collect, None)

    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for item in found:
        key = (item["title"], item["process"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    unique.sort(key=lambda window: (window["process"].lower(), window["title"].lower()))
    return {
        "ok": True,
        "count": len(unique),
        "windows": unique[:MAX_WINDOWS],
        "truncated": len(unique) > MAX_WINDOWS,
    }
