"""Tool lancio applicazioni: allowlist, PATH, collegamenti Start Menu."""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..permissions import Permission
from . import tool

# Nomi italiani/comuni -> eseguibile reale. Il modello riceve "blocco note", non "notepad".
ALIASES = {
    "blocco note": "notepad",
    "notepad": "notepad",
    "calcolatrice": "calc",
    "calculator": "calc",
    "paint": "mspaint",
    "esplora file": "explorer",
    "file explorer": "explorer",
    "prompt dei comandi": "cmd",
    "terminale": "wt",
    "powershell": "powershell",
    "task manager": "taskmgr",
    "gestione attività": "taskmgr",
    "impostazioni": "ms-settings:",
}

START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]
_URI = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)

_allowlist: set[str] = set()
_lnk_cache: dict[str, Path] | None = None


def set_allowlist(names: list[str]) -> None:
    """App che l'utente ha dichiarato sempre permesse (bypassano la conferma)."""
    global _allowlist
    _allowlist = {name.strip().lower() for name in names if name and name.strip()}


def _start_menu_links() -> dict[str, Path]:
    global _lnk_cache
    if _lnk_cache is None:
        links: dict[str, Path] = {}
        for base in START_MENU_DIRS:
            if not base.exists():
                continue
            for path in base.rglob("*.lnk"):
                links.setdefault(path.stem.lower(), path)
        _lnk_cache = links
    return _lnk_cache


def _resolve(name: str) -> tuple[str, str] | None:
    """Ritorna (comando, via) oppure None. Ordine: percorso, URI, PATH, Start Menu."""
    raw = name.strip().strip('"')
    if not raw:
        return None
    target = ALIASES.get(raw.lower(), raw)

    path = Path(target)
    if path.is_absolute() and path.exists():
        return str(path), "path"
    if _URI.match(target):
        return target, "uri"

    executable = shutil.which(target) or shutil.which(target + ".exe")
    if executable:
        return executable, "path"

    links = _start_menu_links()
    key = target.lower()
    if key in links:
        return str(links[key]), "start_menu"
    matches = difflib.get_close_matches(key, links.keys(), n=1, cutoff=0.75)
    if matches:
        return str(links[matches[0]]), "start_menu"
    return None


def is_allowlisted(name: str) -> bool:
    """True se il nome (o il percorso risolto) è in launch.allowlist."""
    key = (name or "").strip().strip('"').lower()
    if not key:
        return False
    if key in _allowlist or ALIASES.get(key, key) in _allowlist:
        return True
    resolved = _resolve(name)
    return bool(resolved and resolved[0].lower() in _allowlist)


def _suggestions(name: str) -> list[str]:
    links = _start_menu_links()
    return difflib.get_close_matches(name.lower(), links.keys(), n=5, cutoff=0.4)


def _summary(args: dict) -> str:
    return f"Avviare l'applicazione «{args.get('name', '?')}»"


@tool(
    "launch_app",
    "Avvia un'applicazione di Windows per nome (es. 'blocco note', 'paint') o per percorso completo.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nome dell'app o percorso completo dell'eseguibile."},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    Permission.CONFIRM,
    summary=_summary,
    auto_when=lambda args: is_allowlisted(str(args.get("name", ""))),
)
def launch_app(name: str) -> dict:
    resolved = _resolve(name)
    if not resolved:
        return {
            "ok": False,
            "error": f"Non trovo nessuna applicazione chiamata «{name}».",
            "suggestions": _suggestions(name),
            "hint": "Usa il nome esatto o il percorso completo dell'eseguibile.",
        }

    target, via = resolved
    try:
        if _URI.match(target) or target.lower().endswith(".lnk"):
            os.startfile(target)
        else:
            subprocess.Popen([target], close_fds=True)
    except OSError as exc:
        return {"ok": False, "error": f"Avvio fallito: {exc}", "path": target}

    return {"ok": True, "launched": name, "path": target, "via": via}
