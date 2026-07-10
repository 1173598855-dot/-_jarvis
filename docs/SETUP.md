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
npm test -- server.test.js
npm run typecheck
npm run build
```

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
python tests/run_all.py
python tests/test_project_config.py
.\venv\Scripts\python.exe tests/test_main_fastapi_extended.py
cd frontend
npm test -- server.test.js
npm run typecheck
npm run build
```
