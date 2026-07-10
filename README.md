# XiaoYi J.A.R.V.I.S.

XiaoYi J.A.R.V.I.S. is a local-first autonomous-evolution engine for multi-agent orchestration, Ollama access, controlled execution, plugin lifecycle management, memory, and a responsive Solid.js command center.

The project is evolving through the protocol in [docs/protocols](docs/protocols). Iteration history is tracked in [CHANGELOG.md](CHANGELOG.md), with detailed reports organized in the [report index](docs/reports/README.md).

## Current Stack

| Layer | Implementation |
|------|----------------|
| Frontend | Solid.js + Vite command center with Kobalte, Lucide, and Chart.js |
| Node backend | Express API, Ollama SSE adapter, truthful telemetry, and Core API bridge |
| Python backend | Python HTTPServer in `src/main.py` |
| FastAPI backend | Alternative API surface in `src/main_fastapi.py` |
| Core kernel | Ollama manager, terminal executor, plugin SDK, event bus |
| Brain layer | Context compressor, orchestrator, role registry, agent factory |
| Tests | Python unittest suites, Vitest component tests, and Playwright browser QA |
| Plugins | Plugin SDK with `plugins/` directory for installable components |

## Repository Map

```text
.
+-- CHANGELOG.md
+-- docs/
|   +-- protocols/
|   +-- reports/
+-- frontend/
|   +-- e2e/
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

## Command Center

The first screen is the working application, not a landing page. It exposes six Chinese-language views:

- Chat command center with Ollama model selection, SSE streaming, stop, retry, and confirmed clearing.
- Runtime monitoring with system metrics, token accounting, and sampled charts.
- Read-only repository status and commit history.
- Local Ollama runtime and installed-model inventory.
- Searchable memory browsing and controlled writes through the Core API.
- Plugin inventory, permissions, and capability-gated lifecycle controls.

The desktop shell uses stable `216px / minmax(0, 1fr) / 320px` tracks. At `1279px` the status rail becomes a drawer; at `767px` the sidebar becomes bottom navigation.

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
npx playwright install chromium
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

`JARVIS_CORE_API_URL` enables the Express bridge for memory, plugin, event, and capability endpoints. Start FastAPI first, then launch Express with:

```powershell
$env:JARVIS_CORE_API_URL = "http://127.0.0.1:8080"
cd frontend
node server.js
```

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

Canonical Python aggregate suite:

```powershell
.\venv\Scripts\python.exe tests/run_all.py
```

Complete Python discovery and syntax checks:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests
```

Configuration and documentation guards:

```powershell
python tests/test_project_config.py
python tests/test_docs_setup.py
python tests/test_readme.py
```

Frontend unit, browser, type, and production checks:

```powershell
cd frontend
npm test -- --run
npm run test:e2e
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
| `/api/ollama/token-usage` | Python / FastAPI / Express | Session token totals and samples |
| `/api/git/status` | Express | Read-only working-tree status |
| `/api/git/log` | Express | Read-only commit history |
| `/api/capabilities` | Express | Core API bridge availability |
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

- Audit reports are rolling iteration evidence, not a substitute for tests.
- Prefer `rg` for repository search and the documented verification commands before claiming an iteration is complete.
