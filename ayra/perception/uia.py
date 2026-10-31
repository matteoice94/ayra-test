"""UI Automation (uiautomation): testo e albero dei controlli."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import uiautomation as auto

from ayra.config import Config
from ayra.perception.guard import is_blocked


DECORATIVE = {"Pane", "Group", "Thumb", "ScrollBar"}


from ayra.perception import target as target_mod


def _find_window(window_substr: str | None, cfg):
    info = target_mod.resolve_target(window_substr, cfg)
    hwnd = info.get("hwnd")
    if not hwnd:
        return None, info
    try:
        ctrl = auto.ControlFromHandle(hwnd)
    except Exception:
        ctrl = None
    return ctrl, info


def _process_name(ctrl) -> str:
    try:
        import psutil

        return psutil.Process(ctrl.ProcessId).name()
    except Exception:
        return ""


def _rect(ctrl):
    try:
        r = ctrl.BoundingRectangle
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return (0, 0, 0, 0)


@dataclass
class WalkState:
    nodes: int = 0
    max_nodes: int = 150
    max_depth: int = 8
    deadline: float = 0.0
    truncated: bool = False


from collections import deque


def _walk(root, state: WalkState, depth: int, out: list):
    # BFS: prima i controlli superficiali, poi i profondi.
    queue = deque()
    queue.append((root, depth))
    while queue:
        if state.nodes >= state.max_nodes or time.time() > state.deadline:
            state.truncated = True
            break
        node, d = queue.popleft()
        if d > state.max_depth:
            continue
        state.nodes += 1
        out.append((d, node))
        if d >= state.max_depth:
            continue
        for child in (node.GetChildren() or []):
            queue.append((child, d + 1))


def _collect_text(nodes, cfg, focused_text=None):
    collected = []
    seen = set()
    if focused_text and focused_text not in seen:
        seen.add(focused_text)
        collected.append(((0, 0, 0, 0), focused_text))
    for _depth, c in nodes:
        try:
            pass
        except Exception:
            pass
        try:
            if c.IsPassword:
                text = "[hidden]"
            else:
                # TextPattern first for document/edit/text controls
                from_pattern = False
                text = ""
                try:
                    tp_pat = c.GetTextPattern()
                    if tp_pat is not None:
                        tr = tp_pat.DocumentRange
                        if tr is not None:
                            t = (tr.GetText(cfg.perception.max_chars) or "").strip()
                            if t:
                                text = t
                                from_pattern = True
                except Exception:
                    text = ""
                if not text:
                    try:
                        vp = c.GetValuePattern()
                        if vp is not None:
                            v = (vp.Value or "").strip()
                            if v:
                                text = v
                                from_pattern = True
                    except Exception:
                        pass
                name_only = (c.Name or "").strip()
                if not text and name_only:
                    text = name_only
                    from_pattern = False
                # offscreen: drop if text only came from Name
                try:
                    if c.IsOffscreen and not from_pattern:
                        text = ""
                except Exception:
                    pass
        except Exception:
            text = (getattr(c, "Name", "") or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        collected.append((_rect(c), text))

    collected.sort(key=lambda item: (item[0][1], item[0][0]))
    chars = 0
    pieces = []
    truncated = False
    for rect, text in collected:
        if chars + len(text) + 1 > cfg.perception.max_chars:
            truncated = True
            break
        pieces.append(text)
        chars += len(text) + 1
    return "\n".join(pieces), truncated


def get_text(window: str | None, cfg: Config) -> dict:
    with auto.UIAutomationInitializerInThread():
        ctrl, info = _find_window(window, cfg)
        if ctrl is None:
            return {"ok": False, "error": "Finestra non trovata."}
        title = info.get("title") or (ctrl.Name or "")
        process = info.get("process") or _process_name(ctrl)
        if is_blocked(process, title, cfg):
            return {"ok": False, "error": "blocked by privacy policy"}
        state = WalkState(max_nodes=cfg.perception.max_nodes, max_depth=cfg.perception.max_depth,
                          deadline=time.time() + cfg.perception.uia_timeout)
        nodes: list = []
        _walk(ctrl, state, 0, nodes)

        focused_text = None
        try:
            fc = auto.GetFocusedControl()
            if fc is not None and getattr(fc, "ProcessId", None) == getattr(ctrl, "ProcessId", None):
                if not getattr(fc, "IsPassword", False):
                    t = (fc.Name or "").strip()
                    try:
                        vp = fc.GetValuePattern()
                        if vp is not None:
                            v = (vp.Value or "").strip()
                            if v and v != t:
                                t = (t + " " + v).strip() if t else v
                    except Exception:
                        pass
                    if t:
                        focused_text = t
        except Exception:
            focused_text = None

        text_out, truncated_flag = _collect_text(nodes, cfg, focused_text)
        if truncated_flag:
            state.truncated = True
        r = _rect(ctrl)
        result = {
            "ok": True,
            "process": process,
            "title": title,
            "source": "uia",
            "text": text_out,
            "truncated": bool(state.truncated or len(text_out) >= cfg.perception.max_chars),
            "node_count": len(nodes),
            "rect": {"left": r[0], "top": r[1], "right": r[2], "bottom": r[3]},
            "minimized": bool(info.get("minimized", False)),
        }
        if info.get("minimized"):
            result["note"] = "Finestra minimizzata: lettura best-effort."
        return result


def get_tree(window: str | None, max_depth: int | None, cfg: Config) -> dict:
    depth_limit = max_depth if max_depth is not None else cfg.perception.max_depth
    with auto.UIAutomationInitializerInThread():
        ctrl, info = _find_window(window, cfg)
        if ctrl is None:
            return {"ok": False, "error": "Finestra non trovata."}
        title = info.get("title") or (ctrl.Name or "")
        process = info.get("process") or _process_name(ctrl)
        if is_blocked(process, title, cfg):
            return {"ok": False, "error": "blocked by privacy policy"}
        state = WalkState(max_nodes=cfg.perception.max_nodes, max_depth=min(depth_limit, cfg.perception.max_depth),
                          deadline=time.time() + cfg.perception.uia_timeout)
        nodes: list = []
        _walk(ctrl, state, 0, nodes)

        lines = []
        for depth, c in nodes:
            try:
                ctype = (c.ControlTypeName or "").replace("Control", "")
            except Exception:
                ctype = ""
            name = (c.Name or "").strip().replace("\n", " ")[:60]
            aid = ""
            try:
                aid = (c.AutomationId or "").strip()
            except Exception:
                aid = ""
            if not name and not aid and ctype in DECORATIVE:
                continue
            r = _rect(c)
            parts = [f"{'  ' * depth}{ctype or '?'}"]
            if name:
                parts.append(f'"{name}"')
            if aid:
                parts.append(f"[{aid}]")
            if r[0] <= -30000 or r[1] <= -30000:
                parts.append("(offscreen)")
            else:
                parts.append(f"({r[0]},{r[1]} {r[2]-r[0]}x{r[3]-r[1]})")
            lines.append(" ".join(parts))

        text_out = "\n".join(lines)
        if len(text_out) > cfg.perception.max_chars:
            text_out = text_out[: cfg.perception.max_chars]
            state.truncated = True
        return {
            "ok": True,
            "process": process,
            "title": title,
            "tree": text_out,
            "truncated": bool(state.truncated),
            "node_count": len(nodes),
        }
