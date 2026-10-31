# Ayra — agente desktop locale per Windows (Fase 0: foundation)

Ayra è un assistente locale ("secondo cervello") che gira su Windows, controllabile da una chat web.
Questa è la **Fase 0**: server locale + chat UI + loop agente + client LLM + permessi + 3 tool.

## Requisiti
- Windows 10/11
- Python 3.11+ (testato su 3.12)
- Un backend LLM OpenAI-compatible (es. Ollama) — vedi sotto.

## Installazione
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
```

## Configurazione
Modifica `config.yaml` (git-ignored). Campi principali:
- `llm.base_url`, `llm.model`, `llm.api_key`, `llm.supports_tools`
- `server.port` (default 8765)
- `agent.max_steps`, `agent.system_prompt`
- `launch.allowlist`

Override da variabili d'ambiente: `AYRA_LLM_BASE_URL`, `AYRA_LLM_MODEL`, `AYRA_LLM_API_KEY`, `AYRA_LLM_SUPPORTS_TOOLS`, `AYRA_PORT`, `AYRA_MAX_STEPS`, `AYRA_CONFIG`.

Blocchi pronti (commentati) in `config.example.yaml` per Ollama, Gemini, OpenRouter.

### Ollama (consigliato, gratis, locale)
```powershell
ollama pull qwen2.5:3b
```
`config.yaml`:
```yaml
llm:
  base_url: "http://localhost:11434/v1"
  model: "qwen2.5:3b"
  api_key: "ollama"
  supports_tools: true
```

Se il modello è piccolo e non supporta tool calling, imposta `supports_tools: false`: Ayra usa il fallback JSON nel system prompt.

## Avvio
```powershell
python run.py
```
Il browser si apre con un URL contenente il token di sessione. Il server ascolta solo su `127.0.0.1`.

## Sicurezza
- Binding solo `127.0.0.1`, token casuale ad ogni avvio.
- Controllo dell'header `Origin` sul WebSocket.
- Nessun `shell=True` con testo utente.
- Tool `launch_app` richiede conferma (Allow/Deny, timeout 60s = deny).

## Tool disponibili
- `get_active_window` (read)
- `list_windows` (read)
- `launch_app` (confirm)

## Tool di percezione (Fase 1)
- `read_window_text` (read): legge il testo visibile (UIA, con fallback OCR se il testo è scarso).
- `get_ui_tree` (read): elenca la struttura dei controlli (pulsanti, campi) con posizione.
- `describe_screen` (confirm, auto se vision locale): descrive lo schermo con un modello di visione.

### Privacy guard
- Blocklist di processi/titoli in `config.yaml` (`perception.blocklist_processes/titles`). Ogni tool verifica la finestra prima di leggere; se bloccata ritorna `blocked by privacy policy` senza contenuto.
- I campi password (UIA `IsPassword`) vengono sostituiti con `[hidden]`.
- Limite: una pagina bancaria dentro il browser non è riconoscibile per nome di processo; evita di leggere finestre del browser su siti sensibili o aggiungi il titolo alla blocklist.

### OCR
Richiede un pacchetto lingua Windows con OCR (Impostazioni > Ora e lingua > Lingua). Se manca, il tool restituisce un errore chiaro. Fallback opzionale: `rapidocr-onnxruntime`.

### Vision
Disabilitata di default. Per abilitarla con un modello locale:
```yaml
vision:
  enabled: true
  base_url: "http://localhost:11434/v1"
  model: "llava"   # o minicpm-v
```
Se l'endpoint è remoto, `describe_screen` richiede conferma e avvisa che l'immagine verrà inviata fuori.

### Limiti noti
- UIA su app Chromium/Electron può essere quasi vuoto: in quel caso scatta l'OCR automatico.
- Nessun controllo mouse/tastiera, nessun watcher/companion, nessuna memoria persistente.

## Test
```powershell
.\.venv\Scripts\python.exe tests/smoke.py
```
Avvia un LLM finto locale e verifica la pipeline end-to-end (tool nativi, fallback JSON, 429, token/Origin).

## Probe percezione (senza LLM)
```powershell
.\.venv\Scripts\python.exe scripts/probe.py --delay 3 read "Blocco note"
.\.venv\Scripts\python.exe scripts/probe.py active
```
Comandi: `active`, `windows`, `read "<titolo>"`, `tree "<titolo>"`, `screen`. `--delay N` attende N secondi per cambiare finestra.
