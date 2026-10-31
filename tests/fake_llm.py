"""LLM finto OpenAI-compatible per test locali. Avvio: python tests/fake_llm.py [port]."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def _last_user_text(body: dict) -> str:
    messages = body.get("messages") or []
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _has_tool_result(body: dict) -> bool:
    messages = body.get("messages") or []
    if any(m.get("role") == "tool" for m in messages):
        return True
    return any(m.get("role") == "user" and "RISULTATO TOOL" in str(m.get("content") or "") for m in messages)


def _sse(handler: BaseHTTPRequestHandler, chunks: list[str]) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    for chunk in chunks:
        handler.wfile.write((chunk + "\n\n").encode("utf-8"))
        handler.wfile.flush()
        time.sleep(0.01)
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            body = {}
        native = "tools" in body
        text = _last_user_text(body)

        if "429" in text.lower():
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "rate limited"}}).encode())
            return

        if _has_tool_result(body):
            final = "Ho usato lo strumento e questo è il risultato riassunto."
            _sse(self, [f'data: {json.dumps({"choices": [{"delta": {"content": final}}]})}'])
            return

        lowered = text.lower()
        if "finestra" in lowered:
            if native:
                call = {"index": 0, "id": "call_finestra", "function": {"name": "get_active_window", "arguments": "{}"}}
                _sse(self, [f'data: {json.dumps({"choices": [{"delta": {"tool_calls": [call]}}]})}'])
            else:
                inner = '{"tool": "get_active_window", "args": {}}'
                _sse(self, [f"data: {json.dumps({'choices': [{'delta': {'content': inner}}]})}"])
            return
        if "programmi" in lowered:
            if native:
                call = {"index": 0, "id": "call_programmi", "function": {"name": "list_windows", "arguments": "{}"}}
                _sse(self, [f'data: {json.dumps({"choices": [{"delta": {"tool_calls": [call]}}]})}'])
            else:
                inner = '{"tool": "list_windows", "args": {}}'
                _sse(self, [f"data: {json.dumps({'choices': [{'delta': {'content': inner}}]})}"])
            return
        if "apri" in lowered:
            if native:
                call = {"index": 0, "id": "call_apri", "function": {"name": "launch_app", "arguments": json.dumps({"name": "notepad"})}}
                _sse(self, [f'data: {json.dumps({"choices": [{"delta": {"tool_calls": [call]}}]})}'])
            else:
                inner = '{"tool": "launch_app", "args": {"name": "notepad"}}'
                _sse(self, [f"data: {json.dumps({'choices': [{'delta': {'content': inner}}]})}"])
            return

        _sse(self, [f'data: {json.dumps({"choices": [{"delta": {"content": "Ciao, sono un modello finto."}}]})}'])


def run(port: int = 8899) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    srv = run(port)
    print(f"fake llm on http://127.0.0.1:{port}/v1", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
