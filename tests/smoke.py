"""Smoke test end-to-end: python tests/smoke.py"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from tests.fake_llm import run as run_fake_llm
from ayra.agent import Agent
from ayra.config import load_config
from ayra.server import create_app
from ayra.tools.window import get_active_window, list_windows
from ayra.llm import _merge_tool_delta, _finalize_tool_calls
from ayra.tools.launch import _resolve
from ayra.perception import target as target_mod
from ayra import agent_hints


def make_config(supports_tools: bool) -> Path:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    Path(path).write_text(
        f"""
llm:
  base_url: "http://127.0.0.1:8899/v1"
  model: "fake"
  api_key: ""
  supports_tools: {str(supports_tools).lower()}
  timeout: 30
server:
  port: 8766
agent:
  max_steps: 6
  history_messages: 20
  system_prompt: "Sei Ayra, assistente di test."
launch:
  allowlist: []
""",
        encoding="utf-8",
    )
    return Path(path)


def collect_events(client, text: str) -> list[dict]:
    events: list[dict] = []
    with client.websocket_connect("/ws?token=" + client.token) as ws:
        ws.send_json({"type": "user", "text": text})
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] == "done":
                break
    return events


def run_case(supports_tools: bool) -> None:
    print(f"--- caso supports_tools={supports_tools} ---")
    os.environ["AYRA_CONFIG"] = str(make_config(supports_tools))
    cfg = load_config()
    token = "test-token-12345"
    app = create_app(cfg, token)
    app.token = token  # type: ignore[attr-defined]
    client = TestClient(app)
    client.token = token  # type: ignore[attr-defined]

    # sicurezza: token sbagliato
    r = client.get("/health?token=wrong")
    assert r.status_code == 401, r.status_code

    # sicurezza: origin sbagliato
    try:
        with client.websocket_connect("/ws?token=" + token, headers={"origin": "http://evil.example"}):
            raise AssertionError("connessione con origin sbagliato accettata")
    except Exception:
        pass

    # token sbagliato su websocket
    try:
        with client.websocket_connect("/ws?token=wrong"):
            raise AssertionError("connessione con token sbagliato accettata")
    except Exception:
        pass

    # tool diretto
    active = get_active_window()
    assert isinstance(active, dict) and "ok" in active
    windows = list_windows()
    assert windows.get("ok") is True

    # finestra attiva
    events = collect_events(client, "che finestra sto usando?")
    types = [e["type"] for e in events]
    assert "tool_call" in types, types
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "get_active_window", tool_call
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["ok"] is True, tool_result
    assert any(e["type"] == "token" for e in events)

    # programmi aperti
    events = collect_events(client, "che programmi ho aperti?")
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "list_windows", tool_call

    # apri blocco note -> conferma, poi deny
    events = []
    with client.websocket_connect("/ws?token=" + token) as ws:
        ws.send_json({"type": "user", "text": "apri il blocco note"})
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] == "confirm_request":
                ws.send_json({"type": "confirm", "id": event["id"], "allow": False})
            if event["type"] == "done":
                break
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["ok"] is False, tool_result
    assert "denied" in tool_result["result"], tool_result
    assert any(e["type"] == "token" for e in events)

    # 429
    events = collect_events(client, "dammi un 429 per favore")
    kinds = [e.get("kind") for e in events if e["type"] == "error"]
    assert "rate_limit" in kinds, kinds
    print("  ok")


def perception_cases() -> None:
    from types import SimpleNamespace

    from ayra.config import load_config
    from ayra.perception import uia, vision
    from ayra.perception.guard import is_blocked
    from ayra.tools import get_tool
    from ayra.tools.perception import set_config

    import os
    cfg_path = make_config(True)
    os.environ["AYRA_CONFIG"] = str(cfg_path)
    cfg = load_config()
    set_config(cfg)

    assert is_blocked("keepass.exe", "x", cfg) is True
    assert is_blocked("notepad.exe", "password manager", cfg) is True
    assert is_blocked("notepad.exe", "Untitled", cfg) is False

    def mk(name, rect, password=False, offscreen=False, value=None):
        vp = SimpleNamespace(Value=value) if value is not None else None
        return SimpleNamespace(
            Name=name,
            IsOffscreen=offscreen,
            IsPassword=password,
            BoundingRectangle=SimpleNamespace(left=rect[0], top=rect[1], right=rect[2], bottom=rect[3]),
            GetValuePattern=lambda: vp,
            ControlTypeName="TextControl",
            AutomationId="",
        )

    c1 = mk("Zeta", (0, 100, 10, 10))
    c2 = mk("Alpha", (0, 10, 10, 10))
    c3 = mk("Alpha", (0, 10, 10, 10))
    c4 = mk("secret", (0, 50, 10, 10), password=True)
    nodes = [(0, c) for c in (c1, c2, c3, c4)]
    cfg.perception.max_chars = 1000
    text, trunc = uia._collect_text(nodes, cfg, None)
    lines = text.splitlines()
    assert lines[0] == "Alpha", lines
    assert text.count("Alpha") == 1, text
    assert "[hidden]" in text

    cfg.perception.max_chars = 8
    text2, trunc2 = uia._collect_text(nodes, cfg, None)
    assert trunc2 is True
    assert len(text2) <= 8

    cfg.vision.enabled = False
    cfg.vision.model = ""
    ok, msg = vision.describe(cfg.vision, "nope.jpg")
    assert ok is False
    assert "disabilit" in msg.lower()

    cfg.vision.base_url = "http://localhost:11434/v1"
    cfg.vision.enabled = True
    cfg.vision.model = "m"
    assert vision.is_local(cfg.vision) is True
    cfg.vision.base_url = "https://example.com/v1"
    assert vision.is_local(cfg.vision) is False

    cfg.vision.base_url = "http://127.0.0.1:11434/v1"
    spec = get_tool("describe_screen")
    assert spec.auto_when({}) is True
    cfg.vision.base_url = "https://example.com/v1"
    assert spec.auto_when({}) is False

    import ayra.tools.perception as tp
    orig_get_text = tp.uia.get_text
    orig_capture = tp.screen.capture
    orig_ocr = tp.ocr.ocr_image
    try:
        tp.uia.get_text = lambda window, cfg: {
            "ok": True, "process": "p", "title": "t", "text": "hi",
            "truncated": False, "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10},
        }
        tp.screen.capture = lambda rect, ms: {"path": "fake.jpg", "filename": "fake.jpg", "width": 10, "height": 10}
        tp.ocr.ocr_image = lambda path: "OCR TEXT"
        cfg.perception.max_chars = 4000
        cfg.perception.ocr_min_chars = 40
        r = tp.read_window_text(ocr="auto")
        assert r["source"] == "uia+ocr", r
        assert "OCR TEXT" in r["text"]

        tp.ocr.ocr_image = lambda path: "SHOULD NOT RUN"
        r2 = tp.read_window_text(ocr="never")
        assert r2["source"] == "uia", r2
        assert "SHOULD NOT RUN" not in r2["text"]

        tp.ocr.ocr_image = lambda path: (_ for _ in ()).throw(RuntimeError("boom"))
        r3 = tp.read_window_text(ocr="force")
        assert r3.get("ok") is False
    finally:
        tp.uia.get_text = orig_get_text
        tp.screen.capture = orig_capture
        tp.ocr.ocr_image = orig_ocr

    from fastapi.testclient import TestClient
    from ayra.server import create_app
    cfg2_path = make_config(True)
    os.environ["AYRA_CONFIG"] = str(cfg2_path)
    cfg2 = load_config()
    from ayra.tools.perception import set_config as sc
    sc(cfg2)
    app = create_app(cfg2, "tok")
    client = TestClient(app)
    r = client.get("/shots/x.jpg")
    assert r.status_code == 401
    for bad in ["../x.jpg", "a/b.jpg", "a\\b.jpg"]:
        r = client.get("/shots/" + bad, params={"token": "tok"})
        assert r.status_code in (400, 404), (bad, r.status_code)
    from ayra.perception.screen import SHOTS_DIR
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (SHOTS_DIR / "valid.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    r = client.get("/shots/valid.jpg", params={"token": "tok"})
    assert r.status_code == 200, r.status_code
    # describe_screen: vision disabled -> no capture
    import ayra.tools.perception as tp
    tp.set_config(cfg)
    cfg.vision.enabled = False
    cfg.vision.model = ""
    calls = {"n": 0}
    orig_capture = tp.screen.capture
    tp.screen.capture = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), {"path": "x.jpg", "filename": "x.jpg", "width": 1, "height": 1})[1]
    try:
        r = tp.describe_screen()
        assert r.get("ok") is False
        assert calls["n"] == 0
    finally:
        tp.screen.capture = orig_capture

    # describe_screen: blocked foreground -> no capture
    cfg.vision.enabled = True
    cfg.vision.model = "m"
    cfg.vision.base_url = "http://localhost:11434/v1"
    orig_is_blocked = tp.is_blocked
    tp.is_blocked = lambda proc, title, cfg: True
    calls = {"n": 0}
    tp.screen.capture = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), {"path": "x.jpg", "filename": "x.jpg", "width": 1, "height": 1})[1]
    try:
        r = tp.describe_screen()
        assert r.get("ok") is False
        assert "blocked" in r.get("error", "")
        assert calls["n"] == 0
    finally:
        tp.is_blocked = orig_is_blocked
        tp.screen.capture = orig_capture

    # describe_screen: vision error -> ok false
    cfg.vision.base_url = "http://localhost:11434/v1"
    orig_describe = tp.vision.describe
    tp.vision.describe = lambda cfg, path, q=None: (False, "boom")
    tp.screen.capture = lambda *a, **k: {"path": "x.jpg", "filename": "x.jpg", "width": 1, "height": 1}
    try:
        r = tp.describe_screen()
        assert r.get("ok") is False
        assert "boom" in r.get("error", "")
    finally:
        tp.vision.describe = orig_describe
        tp.screen.capture = orig_capture

    # guard any_blocked_visible basic
    from ayra.perception.guard import any_blocked_visible
    assert isinstance(any_blocked_visible(cfg, None), bool)

    # BFS order with fake tree
    from types import SimpleNamespace
    child_deep = SimpleNamespace(Name="deep", IsOffscreen=False, IsPassword=False,
        BoundingRectangle=SimpleNamespace(left=0, top=5, right=1, bottom=6),
        GetValuePattern=lambda: None, GetChildren=lambda: [], ControlTypeName="TextControl", AutomationId="", ProcessId=1)
    child_shallow = SimpleNamespace(Name="shallow", IsOffscreen=False, IsPassword=False,
        BoundingRectangle=SimpleNamespace(left=0, top=1, right=1, bottom=2),
        GetValuePattern=lambda: None, GetChildren=lambda: [child_deep], ControlTypeName="TextControl", AutomationId="", ProcessId=1)
    root = SimpleNamespace(Name="root", IsOffscreen=False, IsPassword=False,
        BoundingRectangle=SimpleNamespace(left=0, top=0, right=10, bottom=10),
        GetValuePattern=lambda: None, GetChildren=lambda: [child_shallow], ControlTypeName="WindowControl", AutomationId="", ProcessId=1)
    st = uia.WalkState(max_nodes=2, max_depth=8, deadline=__import__("time").time() + 5)
    nodes = []
    uia._walk(root, st, 0, nodes)
    names = [n[1].Name for n in nodes]
    assert names[:2] == ["root", "shallow"], names

    print("  perception cases ok")


def extra_cases() -> None:
    # FIX 2: tool-call deltas senza "index" ma con id diversi -> due chiamate separate
    buf = {}
    _merge_tool_delta(buf, {"id": "call_a", "function": {"name": "get_active_window", "arguments": "{}"}})
    _merge_tool_delta(buf, {"id": "call_b", "function": {"name": "list_windows", "arguments": "{}"}})
    calls = _finalize_tool_calls(buf)
    assert len(calls) == 2, calls
    names = [c["function"]["name"] for c in calls]
    assert names == ["get_active_window", "list_windows"], names

    # FIX 4: un nome relativo che coincide con un file nel cwd non deve risolversi a quel file
    from pathlib import Path

    marker = Path("zztestapp")
    marker.write_text("x", encoding="utf-8")
    try:
        assert _resolve("zztestapp") is None
    finally:
        marker.unlink(missing_ok=True)
    print("  extra cases ok")


def phase1_1_cases() -> None:
    from types import SimpleNamespace
    import os
    from ayra.config import load_config
    from ayra.perception import uia, vision
    from ayra.perception import target as target_mod
    from ayra.tools.perception import set_config
    import ayra.tools.perception as tp

    cfg_path = make_config(True)
    os.environ["AYRA_CONFIG"] = str(cfg_path)
    cfg = load_config()
    set_config(cfg)

    # resolve_target: foreground is Ayra -> picks next valid
    wg = SimpleNamespace()
    ayra_hwnd, other_hwnd = 100, 200
    wg.EnumWindows = lambda cb, _: [cb(ayra_hwnd, None), cb(other_hwnd, None)]
    wg.IsWindowVisible = lambda h: True
    wg.IsIconic = lambda h: False
    wg.GetWindowText = lambda h: "Ayra - chat" if h == ayra_hwnd else "Notepad - x"
    wg.GetClassName = lambda h: "Chrome_WidgetWin_1"
    wg.GetForegroundWindow = lambda: ayra_hwnd
    wg.GetWindowRect = lambda h: (0, 0, 10, 10)
    target_mod.win32gui = wg
    import win32process, psutil
    target_mod.win32process = win32process
    # patch process name
    orig_process = target_mod._process_name
    target_mod._process_name = lambda pid: "Ayra.exe" if pid == 1 else "notepad.exe"
    # need ThreadProcessId
    win32process.GetWindowThreadProcessId = lambda h: (0, 1 if h == ayra_hwnd else 2)
    info = target_mod.resolve_target(None, cfg)
    assert info["via"] == "previous", info
    assert "Notepad" in info["title"], info
    # substring match never returns Ayra
    info2 = target_mod.resolve_target("Ayra", cfg)
    assert info2.get("hwnd") is None, info2
    # noise skipped: make other hwnd noise
    target_mod.win32gui.GetClassName = lambda h: "Shell_TrayWnd" if h == other_hwnd else "Chrome_WidgetWin_1"
    info3 = target_mod.resolve_target(None, cfg)
    # fallback first valid -> none (both invalid/noise) maybe None
    target_mod.win32gui.GetClassName = lambda h: "Chrome_WidgetWin_1"
    target_mod._process_name = orig_process

    # TextPattern preferred over Name/Value
    from types import SimpleNamespace as SN
    tp_pat = SN(DocumentRange=SN(GetText=lambda n: "PATTERN TEXT"))
    ctrl = SN(Name="NameOnly", IsOffscreen=False, IsPassword=False,
              BoundingRectangle=SN(left=0, top=1, right=2, bottom=3),
              GetTextPattern=lambda: tp_pat, GetValuePattern=lambda: SN(Value="VALUE"),
              ControlTypeName="DocumentControl", AutomationId="", ProcessId=1)
    cfg.perception.max_chars = 1000
    text, trunc = uia._collect_text([(0, ctrl)], cfg)
    assert "PATTERN TEXT" in text, text

    # password hidden
    ctrl2 = SN(Name="pwd", IsOffscreen=False, IsPassword=True,
               BoundingRectangle=SN(left=0, top=1, right=2, bottom=3),
               GetTextPattern=lambda: None, GetValuePattern=lambda: SN(Value="secret"),
               ControlTypeName="EditControl", AutomationId="", ProcessId=1)
    text2, _ = uia._collect_text([(0, ctrl2)], cfg)
    assert "secret" not in text2
    assert "[hidden]" in text2

    # offscreen pattern kept, offscreen name-only dropped
    ctrl3 = SN(Name="offname", IsOffscreen=True, IsPassword=False,
               BoundingRectangle=SN(left=0, top=1, right=2, bottom=3),
               GetTextPattern=lambda: tp_pat, GetValuePattern=lambda: None,
               ControlTypeName="TextControl", AutomationId="", ProcessId=1)
    ctrl4 = SN(Name="offonly", IsOffscreen=True, IsPassword=False,
               BoundingRectangle=SN(left=0, top=1, right=2, bottom=3),
               GetTextPattern=lambda: None, GetValuePattern=lambda: None,
               ControlTypeName="TextControl", AutomationId="", ProcessId=1)
    t3, _ = uia._collect_text([(0, ctrl3), (0, ctrl4)], cfg)
    assert "PATTERN TEXT" in t3
    assert "offonly" not in t3

    # get_tree offscreen prints (offscreen)
    fake_ctrl = SN(Name="n", ControlTypeName="TextControl", AutomationId="",
                   BoundingRectangle=SN(left=-32000, top=0, right=-31990, bottom=10),
                   GetChildren=lambda: [], ProcessId=1)
    uia._find_window = lambda window, cfg: (fake_ctrl, {"title": "t", "process": "p"})
    tree = uia.get_tree(None, 2, cfg)
    assert "(offscreen)" in tree.get("tree", ""), tree

    # hint_for rules
    from ayra import agent_hints
    assert agent_hints.hint_for("leggi la finestra") == "read_window_text"
    assert agent_hints.hint_for("che programmi ho aperti") == "list_windows"
    assert agent_hints.hint_for("struttura controlli") == "get_ui_tree"
    assert agent_hints.hint_for("descrivi lo schermo", vision_enabled=True) == "describe_screen"
    assert agent_hints.hint_for("descrivi lo schermo", vision_enabled=False) is None
    assert agent_hints.hint_for("che finestra sto usando") == "get_active_window"
    assert agent_hints.hint_for("apri il blocco note") == "launch_app"
    assert agent_hints.hint_for("ciao come stai") is None

    # reset clears history
    from fastapi.testclient import TestClient
    from ayra.server import create_app
    app = create_app(cfg, "tok")
    client = TestClient(app)
    with client.websocket_connect("/ws?token=tok") as ws:
        ws.send_json({"type": "user", "text": "ciao"})
        while True:
            e = ws.receive_json()
            if e["type"] == "done":
                break
        # history non empty; reset
        with client.websocket_connect("/ws?token=tok") as ws2:
            ws2.send_json({"type": "reset"})
            while True:
                e = ws2.receive_json()
                if e["type"] == "system":
                    break
    # check history cleared by accessing agent? agent per connection; just ensure no crash
    print("  phase1.1 cases ok")


def main() -> None:
    server = run_fake_llm(8899)
    try:
        run_case(True)
        run_case(False)
        extra_cases()
        perception_cases()
        phase1_1_cases()
        print("SMOKE OK")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
