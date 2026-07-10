# J.A.R.V.I.S. Setup

## Python Environment

Install runtime and development dependencies from the project root:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -e ".[dev]"
```

FastAPI tests use Starlette's TestClient, which requires the `httpx2` dev dependency declared in `pyproject.toml`.

## Frontend Environment

Install and verify the Solid/Vite frontend from `frontend/`:

```powershell
cd frontend
npm install
npx playwright install chromium
npm test -- server.test.js
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
```

The Playwright install is a one-time browser-runtime setup. Browser tests start an isolated Vite server, intercept `/api/**` with deterministic fixtures, and verify desktop (`1440x900`) and mobile (`390x844`) layouts.

## Local Service Topology

Run the services in separate PowerShell sessions:

```powershell
# Core API, choose FastAPI or src/main.py on port 8080
.\venv\Scripts\python.exe -m uvicorn src.main_fastapi:app --host 127.0.0.1 --port 8080

# Express API on port 9999 with optional Core API capabilities
cd frontend
$env:JARVIS_CORE_API_URL = "http://127.0.0.1:8080"
node server.js

# Vite UI on port 5173
cd frontend
npm run dev
```

Ollama is expected on `http://127.0.0.1:11434` unless `OLLAMA_HOST` or `OLLAMA_PORT` overrides it.

## CORS Configuration

`JARVIS_ALLOWED_ORIGINS` controls CORS for the Python HTTPServer, FastAPI server, and Express backend.

Development default:

- When unset, local servers keep wildcard CORS compatibility.

Restricted mode:

```powershell
$env:JARVIS_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

When set, only matching request origins receive `Access-Control-Allow-Origin`.

## Verification Commands

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests
.\venv\Scripts\python.exe tests/test_project_config.py
.\venv\Scripts\python.exe tests/test_main_fastapi_extended.py
cd frontend
npm test -- server.test.js
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
```
