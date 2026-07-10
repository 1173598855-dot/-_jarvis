# XiaoYi J.A.R.V.I.S.

XiaoYi J.A.R.V.I.S. is a local autonomous-evolution engine for multi-agent orchestration, local model access, plugin/runtime isolation, memory compression, and a Solid.js monitoring dashboard.

The project is evolving through the protocol in [docs/protocols](docs/protocols). Iteration history is tracked in [CHANGELOG.md](CHANGELOG.md), with detailed reports organized in the [report index](docs/reports/README.md).

## Current Stack

| Layer | Implementation |
|------|----------------|
| Frontend | Solid.js + Vite dashboard |
| Node backend | Express API and Ollama SSE adapter |
| Python backend | Python HTTPServer in `src/main.py` |
| FastAPI backend | Alternative API surface in `src/main_fastapi.py` |
| Core kernel | Ollama manager, terminal executor, plugin SDK, event bus |
| Brain layer | Context compressor, orchestrator, role registry, agent factory |
| Tests | Python unittest/pytest-compatible files, Vitest frontend tests |
| Plugins | Plugin SDK with `plugins/` directory for installable components |

## Repository Map

```text
.
+-- CHANGELOG.md
+-- docs/
|   +-- protocols/
|   +-- reports/
+-- frontend/
|   +-- server.js
|   +-- src/
+-- plugins/
|   +-- plugin-template/
+-- skills/
+-- src/
|   +-- main.py
|   +-- main_fastapi.py
|   +-- core/
+-- tests/
```

## Developer Setup

Use the full setup guide in [docs/SETUP.md](docs/SETUP.md).

Quick Python setup:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Quick frontend setup:

```powershell
cd frontend
npm install
```

## Run Services

Python HTTPServer:

```powershell
python src/main.py
```

FastAPI:

```powershell
.\venv\Scripts\python.exe -m uvicorn src.main_fastapi:app --host 127.0.0.1 --port 8080
```

Express backend:

```powershell
cd frontend
node server.js
```

Vite frontend:

```powershell
cd frontend
npm run dev
```

## Runtime Configuration

`JARVIS_ALLOWED_ORIGINS` controls CORS for the Python HTTPServer, FastAPI server, and Express backend.

```powershell
$env:JARVIS_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

When unset, development servers keep wildcard CORS compatibility. When set, only matching request origins receive `Access-Control-Allow-Origin`.

## Plugin Setup

Plugins live under `plugins/`. Each plugin needs a `manifest.json` and an `activate(api)` entry point. The project ships `plugin-template` as a starting point.

```powershell
# discover plugins from plugins/
python -c "from core.kernel.plugin_sdk import PluginLoader; print(PluginLoader().discover())"

# load and enable via FastAPI
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/plugins/load -Method Post -Body ('{"plugin_id":"' + (Get-Content plugins\plugin-template\manifest.json | ConvertFrom-Json).plugin_id + '"}' | ConvertTo-Json) -ContentType 'application/json'
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/plugins/enable -Method Post -Body ('{"plugin_id":"' + (Get-Content plugins\plugin-template\manifest.json | ConvertFrom-Json).plugin_id + '"}' | ConvertTo-Json) -ContentType 'application/json'
```

## Verification

Core Python smoke suite:

```powershell
python tests/run_all.py
```

FastAPI endpoint suite:

```powershell
.\venv\Scripts\python.exe tests/test_main_fastapi_extended.py
```

Configuration and documentation guards:

```powershell
python tests/test_project_config.py
python tests/test_docs_setup.py
python tests/test_readme.py
```

Frontend server and build:

```powershell
cd frontend
npm test -- server.test.js
npm run typecheck
npm run build
```

## Key API Surfaces

| Endpoint | Service | Purpose |
|----------|---------|---------|
| `/api/health` | Python / FastAPI / Express | Health check |
| `/api/system/stats` | Python / FastAPI / Express | Local system statistics |
| `/api/ollama/status` | Python / FastAPI / Express | Ollama availability |
| `/api/ollama/chat` | Python / FastAPI / Express | Non-streaming chat |
| `/api/ollama/chat/stream` | Python / FastAPI / Express | SSE chat stream |
| `/api/terminal/execute` | Python / FastAPI / Express | Guarded terminal execution |
| `/api/plugins` | Python / FastAPI / Express | Plugin inventory |
| `/api/plugins/load` | Python / FastAPI / Express | Load plugin |
| `/api/plugins/enable` | Python / FastAPI / Express | Enable plugin |
| `/api/plugins/disable` | Python / FastAPI / Express | Disable plugin |
| `/api/memory/entries` | Python / FastAPI / Express | Memory entries |
| `/api/memory/store` | Python / FastAPI / Express | Store memory |
| `/api/events` | Python / FastAPI / Express | Event history |
| `/api/orchestrator/agents` | Python / FastAPI / Express | Registered agent list |
| `/api/orchestrator/history` | Python / FastAPI / Express | Task history |
| `/api/orchestrator/dispatch` | Python / FastAPI / Express | Dispatch task |
| `/api/roles/*` | FastAPI | Role-driven dispatch |

## Notes

- The working tree currently contains many historical generated files and uncommitted iteration artifacts.
- Audit reports are append-only iteration evidence, not a substitute for tests.
- Prefer `rg` for repository search and the documented verification commands before claiming an iteration is complete.
