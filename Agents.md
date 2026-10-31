# AGENTS.md — Ayra

Ayra is a local AI desktop agent for Windows ("second brain", de-powered Jarvis).
Long-term goals: control the PC, see the screen to advise in real time, own chat app,
Opera sidebar, companion mode that follows the user in another program.

## Hard rules
- ZERO COST: only free/open-source libs, LLM must be configurable (Ollama or free-tier API).
- Windows 10/11, Python 3.11+. UI = vanilla HTML/CSS/JS, no npm, no build step.
- Small files (<~200 lines), no over-engineering, minimal dependencies.
- Don't rewrite working files; don't re-read the whole repo each time.
- Work in phases; only implement what the current phase asks.

## Security (non-negotiable)
- Server binds only to 127.0.0.1, random token at every startup, Origin check on WebSocket.
- Never use shell=True with raw user text.
- Risky tools need user confirmation (permission levels: read / confirm / auto).

## Structure
- ayra/ core: config.py, llm.py (OpenAI-compatible), agent.py, permissions.py, server.py
- ayra/tools/: one file per tool group, registered in tools/__init__.py
- ui/: index.html, app.js, style.css (must work at ~350px width for a future browser sidebar)
- Planned: perception/ (UIA, screenshot, OCR, watcher), extension/ (Opera), profiles/ (per-app prompts)

## Phases
0 foundation (done) | 1 perception (current) | 2 actions | 3 Opera sidebar | 4 companion mode

## Structure (phase 1)
ayra/perception/: guard.py, target.py, uia.py, screen.py, ocr.py, vision.py
Probe: python scripts/probe.py ...

## Come eseguire
- `python run.py` (crea config.yaml se manca, apre il browser con il token).
- Test: `.\.venv\Scripts\python.exe tests/smoke.py`.
- Venv: `.\.venv\Scripts\python.exe`.

## Convenzioni
- File < ~200 righe; un gruppo di tool per file in `ayra/tools/`.
- Sicurezza: bind solo 127.0.0.1; mai `shell=True` con testo utente; tool `confirm` chiedono approvazione.
- UI: vanilla HTML/CSS/JS, nessun build step; colori come variabili CSS in `ui/style.css`.