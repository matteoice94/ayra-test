"""Hint per modelli piccoli: suggerisce il tool giusto in base al testo utente."""

from __future__ import annotations

import re

RULES = [
    (r"che finestra sto usando|which window", "get_active_window"),
    (r"programmi.*aperti|finestre.*aperte|list windows|cosa ho aperto|programmi aperti", "list_windows"),
    (r"struttura|controlli|pulsanti|ui tree|get_ui_tree", "get_ui_tree"),
    (r"descrivi (lo )?schermo|cosa vedi|describe screen", "describe_screen"),
    (r"\bleggi\b|cosa c.e scritto|cosa ho scritto|cosa dice|read window|read text", "read_window_text"),
    (r"\bapri\b|\bavvia\b|\blancia\b", "launch_app"),
]


def hint_for(user_text: str, vision_enabled: bool = False) -> str | None:
    text = (user_text or "").lower()
    for pattern, tool in RULES:
        if re.search(pattern, text):
            if tool == "describe_screen" and not vision_enabled:
                continue
            return tool
    return None
