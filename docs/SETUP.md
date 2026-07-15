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

Ollama is expected on `http://127.0.0.1:11434` unless `OLLAMA_HOST` or `OLLAMA_PORT` overrides it. Role dispatch uses the same in-process `OllamaManager` and token telemetry as chat. Set `JARVIS_ROLE_MODEL` to an installed Ollama model when the default `llama3.2` is not available:

```powershell
$env:JARVIS_ROLE_MODEL = "llama3.2"
```

Role profile `tools` are declarations, not authority. The default
`RoleToolBroker` has no grants or handlers. A tool is exposed to a role only
when its declaration, explicit role grant, and registered handler all match.
Automatic model-driven tool invocation remains disabled, and this policy does
not reuse the HTTP terminal token as a role grant.

## Optional Local Integration Profile

After FastAPI, Express, and Ollama are running, execute the real local SSE,
memory, and plugin flow from the repository root:

```powershell
.\venv\Scripts\python.exe scripts/local_integration_profile.py
```

The default mode prints `SKIPPED` and exits successfully when a required local
service is unavailable. CI or a prepared workstation can require the full flow:

```powershell
.\venv\Scripts\python.exe scripts/local_integration_profile.py --require-services
```

Use `--express-url` or `JARVIS_EXPRESS_URL` for a non-default Express address,
and `--model` or `JARVIS_OLLAMA_MODEL` to select an installed Ollama model.
The profile validates an assistant content frame, Ollama's native `done: true`
frame, and the final `[DONE]` marker. Its temporary memory probe is removed with
an exact memory type and one-time cleanup token, including when a later SSE or
schema check fails. A malformed Ollama response remains a contract failure;
only the stable `OLLAMA_UNAVAILABLE` code is treated as an optional skip.

CI uses a deterministic repository-owned stack with a local Ollama fixture, so the required-services gate does
not depend on a downloaded model or an external Ollama daemon:

```powershell
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services
```

The runner starts FastAPI, Express, and `scripts/local_ollama_fixture.py` on
ephemeral loopback ports, runs the same profile, and always terminates the
child services afterward.

## CORS Configuration

`JARVIS_ALLOWED_ORIGINS` controls CORS for the Python HTTPServer, FastAPI server, and Express backend.

Development default:

- When unset, local servers allow only `http://localhost:5173` and `http://127.0.0.1:5173`.
- `JARVIS_HOST` defaults to `127.0.0.1`; Docker publishes its development ports only on the host loopback interface.
- `JARVIS_GIT_COMMAND` optionally overrides the trusted process-level Git executable for controlled deployments and tests. It is never read from an HTTP request.

Restricted mode:

```powershell
$env:JARVIS_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

When set, only matching request origins receive `Access-Control-Allow-Origin`; wildcard origins are ignored.

## Terminal Capability

`/api/terminal/execute` is disabled unless both variables below are set. It is intended for a trusted local client and only accepts `echo`, `pwd`, `whoami`, `hostname`, and `date`; arbitrary interpreters, package managers, downloaders, environment readers, and user-defined executables are rejected before process creation.

```powershell
$tokenBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
$env:JARVIS_TERMINAL_TOKEN = [Convert]::ToHexString($tokenBytes)
$env:JARVIS_TERMINAL_ENABLED = "true"
```

Send the token as `X-Jarvis-Terminal-Token`. Missing runtime configuration returns `403 TERMINAL_DISABLED`; an invalid token returns `401 TERMINAL_UNAUTHORIZED`. Do not put this token in a browser bundle or source file.

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
