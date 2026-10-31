"""Probe CLI per testare la percezione senza LLM. Uso: python scripts/probe.py [--delay N] active|windows|read \"<title>\"|tree \"<title>\"|screen"""

from __future__ import annotations

import argparse
import json
import time

from ayra.config import load_config
from ayra.tools.perception import set_config
from ayra.tools import perception as P
from ayra.tools.window import get_active_window, list_windows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=0)
    parser.add_argument("cmd", choices=["active", "windows", "read", "tree", "screen"])
    parser.add_argument("title", nargs="?")
    args = parser.parse_args()

    if args.delay:
        time.sleep(args.delay)

    cfg = load_config()
    set_config(cfg)

    if args.cmd == "active":
        result = get_active_window()
    elif args.cmd == "windows":
        result = list_windows()
    elif args.cmd == "read":
        result = P.read_window_text(window=args.title)
    elif args.cmd == "tree":
        result = P.get_ui_tree(window=args.title)
    else:
        result = P.describe_screen(scope="screen")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
