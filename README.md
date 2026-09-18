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
| Core kernel | Ollama manager, terminal executor, Worker-isolated plugin SDK, broker, and event bus |
| Brain layer | Context compressor, orchestrator, role registry, agent factory |
| Tests | Python unittest suites, Vitest component tests, and Playwright browser QA |
| Plugins | `python_worker` Plugin runtime with parent-owned lifecycle and event delivery |

## Repository Map

```text
.
+-- CHANGELOG.md
+-- contracts/
|   +-- core-api.openapi.json
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
- Plugin lifecycle controls plus a read-only Skill, Plugin, and UI capability inventory with provenance, compatibility, health, risk, and permissions.

The desktop shell uses stable `216px / minmax(0, 1fr) / 320px` tracks. At `1279px` the status rail becomes a drawer; at `767px` the sidebar becomes bottom navigation.

## Developer Setup

Use the full setup guide in [docs/SETUP.md](docs/SETUP.md).

Quick Python setup:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

Quick frontend setup:

```powershell
cd frontend
npm ci
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

`JARVIS_ALLOWED_ORIGINS` controls CORS for the Python HTTPServer, FastAPI server, and Express backend. When unset, only the local Vite origins are allowed; `*` is ignored rather than used as a fallback.

```powershell
$env:JARVIS_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

When set, only exact matching request origins receive `Access-Control-Allow-Origin`. `JARVIS_HOST` defaults to `127.0.0.1`; use an explicit value only when a deployment boundary has been reviewed.

Role dispatch uses the same `OLLAMA_BASE_URL` and model setting as chat, but each role Worker owns its model client and returns bounded token usage to the parent. The synchronous role routes (`/api/roles/dispatch`, capability dispatch, and batch dispatch) now execute through a terminable Worker while preserving their compatibility response shapes. `JARVIS_ROLE_MODEL` selects the installed model they use; it defaults to `llama3.2`. Generic orchestration has three explicit registration paths: deprecated `register(callable)` remains a source-compatible in-process wrapper that emits a `DeprecationWarning`; use `register_in_process(name, handler)` for intentional process-local execution, where a timed-out daemon handler cannot be dispatched, unregistered, or replaced until it exits; internal-only `register_declared(name, runner_id)` resolves a static trusted runner in a terminable child process; and internal-only `register_worker(name, handler)` resolves a stable top-level function in a terminable child process. The first declared runner is `echo`; its task data is strict, byte-bounded JSON and invalid input is rejected before process creation without leaving the Agent unavailable. No HTTP adapter accepts runner selection, module paths, commands, environments, working directories, or capability tokens. Shipped services do not bootstrap a declared generic Agent, so this does not add external execution authority or generic task cancellation/persistence.

Internal callers may use `Orchestrator.register_in_process(name, handler, capabilities=None)` when a closure, bound method, or callable instance must intentionally remain local; this path emits no deprecation warning. They may use `register_worker(name, handler, capabilities=None)` for a stable top-level function whose module already binds the exact function. The Worker derives the locator from the callable object, so lambdas, closures, bound methods, callable instances, and `__main__` functions fail before Worker registration; those remain supported only through `register_in_process()`. `Orchestrator.cancel(agent_name, task_id)` is an internal synchronous cancellation hook for Worker-backed Agents and returns true only after the child process reports confirmed termination. Neither registration nor cancellation is exposed through HTTP.

```powershell
$env:JARVIS_ROLE_MODEL = "llama3.2"
```

Role profile `tools` are declarations, not authority. `AgentFactory` still uses
an empty `RoleToolBroker` by default. Model-driven tools are enabled only inside
the production `RoleWorker`, where every request must be declared by the role,
explicitly granted, validated against a strict schema and executed through the
broker within call, byte and elapsed-time budgets. The fixed catalog contains
only `system_status`, `model_list`, `orchestrator_status`, `memory_search` and
`repository_metadata`; it does not expose terminal execution, plugin lifecycle,
HTTP capability tokens or generic orchestrator dispatch. The catalog is also
published as five read-only `role_tool` capability records, but those records
grant no execution authority. Each default service-owned Worker receives only
the registry-validated schema version, exact sorted capability IDs, and catalog
SHA-256; the child validates that evidence against its local static catalog
before binding any fixed handler.

Stage D capability discovery is local and read-only. `CapabilityRegistry`
scans fixed repository roots for Skills, Plugins, the five built-in role tools,
and directly exported UI components without importing extension code. Its versioned records preserve unknown
source, license, and version fields explicitly, expose only relative paths, and
include bounded content digests plus health and risk reasons. The local resolver
supports a strict numeric compatibility subset, bounded kind/risk/compatibility
filters, and deterministic scoring; unsupported runtimes remain explicitly
unknown. The local `FileCapabilityStore` accepts already-provided ZIP bytes only
after bounded archive, manifest, source, license, and entrypoint validation; it
never imports or executes package content, stores revisions by SHA-256, and
publishes them as disabled. Its bounded lifecycle supports atomic upgrade,
content-revalidated rollback, canonical removal, and restart-safe rebuild with
fail-closed drift detection. `GET /api/capabilities/registry` now exposes only
bounded public metadata through Python HTTPServer, FastAPI, and the Express Core
bridge; the Plugins view polls that read-only inventory and keeps lifecycle
controls confined to the existing Plugin API. No network archive, URL input, or
HTTP lifecycle mutation is accepted.

MemoryStore writes use a strictly validated v2 Markdown envelope whose fields
and UTF-8 content round-trip without loss in normal operation. Existing v1
Markdown records are loaded read-only for compatibility; the original tag
delimiter and marker-like body text can be ambiguous. The Python memory-list
endpoints read through a bounded read-only snapshot (8,192 directory entries,
256 candidate files, 1 MiB per file and 32 MiB total) and clip public fields to
their response budgets. Entry and index publication is crash-consistent: a
bounded intent journal records the filename a mutation is about to publish, and
every writable open or mutation rolls that intent forward so the index holds a
row for the journalled entry exactly when that entry file exists and parses.
Recovery is idempotent, atomic replaces flush the containing directory through
one shared durability contract, and temporaries left by a crashed write are
cleaned up within a bounded scan. `consolidate()` applies the pruning and
merging it reports: records outside the compressed target set are deleted through
the same journalled delete path and counted in a `removed` stat. Merging is
lossless within a bound: the surviving duplicate absorbs the other record's
distinct body, tags and access counts and records the absorbed ids, and a merge
whose combined body would exceed 8,192 characters is refused so both records are
kept rather than one body lost. Survivors are stored before non-survivors are
deleted, so an interrupted consolidation leaves a consistent superset that the
next run converges. Truncation keeps the largest head/tail pair that fits the
requested token budget, compression markers never stack on a title, and duplicate
detection matches on the marker-free base title, so repeated consolidation reaches
a fixed point instead of growing each record. All-or-nothing batch semantics, summarizing an over-budget
absorbed body and non-cooperating same-user filesystem races remain documented
follow-up work.

FastAPI and the Express Core API bridge also expose `/api/roles/tasks` for
process-owned asynchronous execution. Clients create a task, poll its task ID,
and may request cancellation; `timeout` and `cancelled` are terminal only after
the child process is confirmed stopped. Request bodies cannot select a runner,
command, environment, working directory, or capability token. Task records are
persisted during shutdown and reconciled on FastAPI startup; orphaned active
records become explicit terminal failures instead of being silently resumed.

Terminal execution is disabled by default. To expose the five read-only diagnostic operations (`echo`, `pwd`, `whoami`, `hostname`, and `date`) to a local trusted client, explicitly configure both a high-entropy capability token and the enable flag:

```powershell
$tokenBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
$env:JARVIS_TERMINAL_TOKEN = [Convert]::ToHexString($tokenBytes)
$env:JARVIS_TERMINAL_ENABLED = "true"
```

Callers must send the token in `X-Jarvis-Terminal-Token`. The Express service forwards this header to the configured Core API; it never launches the Python terminal executor itself.

`JARVIS_CORE_API_URL` enables the Express bridge for memory, plugin, event, and capability endpoints. Start FastAPI first, then launch Express with:

```powershell
$env:JARVIS_CORE_API_URL = "http://127.0.0.1:8080"
cd frontend
node server.js
```

## Plugin Setup

Plugins live under `plugins/`. Only a manifest with `runtime: "python_worker"`
is executable; legacy `native`, virtual-environment, and Node runtime values may
be discovered but fail closed without importing Plugin code. Each plugin needs a
`manifest.json` and an `activate(api)` entry point. The project ships
`plugin-template` as a starting point.

Each Python service owns its own `PluginManager` and `EventBus`. Loading and
lifecycle calls run in a persistent child process, while the parent validates
the protocol, enforces timeouts, owns shutdown, and reaps the Worker. The V1
Broker is default-deny: a capability must be declared in the manifest,
explicitly configured by the service, and registered by the parent before
any handler runs. First-party Plugins are only granted `event.emit`;
read-only `system.stats`, `file.read`, `file.list` and `config.get` are
registered but never granted by default. `file.list` reuses `file_read` and
returns a name-sorted snapshot of direct children inside the plugin's bound
root, with an 8,192-entry scan budget and the existing Broker exchange budget.
POSIX scans bind the validated directory identity to the opened descriptor and
fail closed when the target changes; platforms without descriptor-relative
directory scanning retain the existing before/after identity checks.
`file.read` opens rooted POSIX paths descriptor-relatively without following
links and rejects target identity changes while preserving its 1 MiB UTF-8
budget; other platforms retain open-before/after identity checks.
`llm.call` is only registered once a service
configures a parent provider, while `network.get` requires a registered host
allowlist; neither is granted by default. Model uses outside that explicit
provider, network egress outside the registered allowlist, terminal,
file-write and process operations remain denied.

On Linux, the Worker also enters a private network namespace and applies a
Landlock filesystem ruleset before serving. The ruleset keeps the plugin root
read-only, gives only the Worker-owned temporary directory bounded write
access, and denies execution and access outside the verified runtime paths.
Unavailable or invalid Landlock ABI and setup failures stop the Worker before
its hello handshake; newer ABIs use only the rights this code understands.
The fixed Terminal Worker uses the same Linux network and filesystem boundary
before reading a terminal request; its parent-owned temporary root is the only
explicitly writable root. On Windows, production Plugin Workers now start
through a parent-owned capability-free AppContainer with staged read-only code
and one writable Worker root; setup failures fail closed. On macOS, production
Plugin Workers now use a parent-owned `sandbox-exec`/Seatbelt `(deny default)`
profile with bounded staged code and one writable Worker root; setup failures
fail closed without direct-spawn fallback. This Windows host verifies the macOS
policy and failure contract only, not macOS kernel enforcement. Iteration 243
adds a dedicated `macos-sandbox` CI job and a real probe that uses a live
loopback listener, an ungranted file, and the Worker-owned writable root; the
probe is explicitly skipped on non-macOS hosts. All platforms keep the same-user process model and default-deny
Broker.

## Current Evidence

Iteration 249 is the current audit entry. It covers bounded lexical memory
search with deterministic ranking and provenance; semantic embeddings remain a
separate Phase F work package. The platform enforcement evidence for the Linux
Plugin and Terminal Workers is recorded in Iterations 245, 246 and 248, while
Windows and macOS boundaries retain their platform-specific evidence limits.
Use [the report index](docs/reports/README.md) for the current ten-report window
and [CHANGELOG.md](CHANGELOG.md) for the complete iteration ledger.

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

# 冒烟子集、超时与 JSON 报告（CI 使用 --timeout 1800）
.\venv\Scripts\python.exe tests/run_all.py --smoke
.\venv\Scripts\python.exe tests/run_all.py --timeout 1800 --json-report run-all-report.json
```

Complete Python discovery and syntax checks:

```powershell
.\venv\Scripts\python.exe scripts/discover_tests.py --timeout 1800
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

Configuration and documentation guards:

```powershell
python tests/test_project_config.py
python tests/test_docs_setup.py
python tests/test_readme.py
python -m unittest tests.test_api_contract
```

Frontend unit, browser, type, and production checks:

```powershell
cd frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
```

Optional local integration profile (requires running Express + Ollama):

```powershell
.\venv\Scripts\python.exe scripts/local_integration_profile.py
```

Use `--require-services` in CI or prepared environments to enforce service availability.

The CI-equivalent deterministic check starts FastAPI, Express, and a local Ollama fixture on ephemeral loopback ports:

```powershell
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services
```

## Key API Surfaces

The stable cross-implementation response contract is maintained in
[`contracts/core-api.openapi.json`](contracts/core-api.openapi.json).

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
| `/api/git/branches` | Express | Read-only branch list |
| `/api/capabilities` | Express | Core API bridge availability |
| `/api/capabilities/registry` | Python / FastAPI / Express | Read-only local Skill, Plugin, and UI capability metadata |
| `/api/terminal/execute` | Python / FastAPI / Express | Opt-in token-gated fixed diagnostic operations |
| `/api/plugins` | Python / FastAPI / Express | Worker-isolated Plugin inventory |
| `/api/plugins/load` | Python / FastAPI / Express | Load a Worker-isolated Plugin by `plugin_id` |
| `/api/plugins/enable` | Python / FastAPI / Express | Enable a loaded Worker-isolated Plugin by `plugin_id` |
| `/api/plugins/disable` | Python / FastAPI / Express | Disable a loaded Worker-isolated Plugin by `plugin_id` |
| `/api/memory/entries` | Python / FastAPI / Express | Memory entries |
| `/api/memory/store` | Python / FastAPI / Express | Store memory |
| `DELETE /api/memory/probes/{type}/{id}` | Python / FastAPI / Express | Token-verified local integration probe cleanup |
| `/api/events` | Python / FastAPI / Express | Event history |
| `/api/orchestrator/agents` | Python / FastAPI / Express | Registered agent list |
| `/api/orchestrator/history` | Python / FastAPI / Express | Task history |
| `/api/orchestrator/dispatch` | Python / FastAPI / Express | Dispatch task |
| `/api/roles` | Python / FastAPI / Express | Registered role list and capability filter |
| `/api/roles/{role_name}` | Python / FastAPI / Express | Role profile |
| `GET /api/roles/tasks` | FastAPI / Express | List asynchronous role tasks |
| `POST /api/roles/tasks` | FastAPI / Express | Create an asynchronous role task |
| `GET /api/roles/tasks/{task_id}` | FastAPI / Express | Read an asynchronous role task |
| `POST /api/roles/tasks/{task_id}/cancel` | FastAPI / Express | Request confirmed task cancellation |
| `/api/roles/dispatch` | Python / FastAPI / Express | Synchronous role dispatch through a terminable Worker |
| `/api/roles/dispatch_by_cap` | Python / FastAPI / Express | Capability-selected synchronous dispatch through a terminable Worker |
| `/api/roles/batch_dispatch` | Python / FastAPI / Express | Ordered batch dispatch through terminable Workers |

Git endpoints are Express-only and are declared in `contracts/core-api.openapi.json`
with `x-jarvis-implementations: ["frontend/server.js"]`; Python services do not
implement or proxy them.

## Notes

- Audit reports are rolling iteration evidence, not a substitute for tests.
- Prefer `rg` for repository search and the documented verification commands before claiming an iteration is complete.
- Iteration 249 is the current evidence: the aggregate suite reports 1161 total (1150 passed, 11 skipped), and bounded discovery reports 2135 total (2123 passed, 12 skipped). Frontend verification reports Vitest 151 passed, Playwright 7 passed and 1 desktop-conditional skip; typecheck, build, Ruff lint and compileall passed.
- Worker filesystem and network unit tests verify decision logic and fail-closed behavior with injected platform doubles on this Windows host. Linux additionally has real Ubuntu 24.04 WSL2 evidence for the isolation primitives and the complete production Plugin Runtime and fixed Terminal Worker paths with a non-overflow UID/GID; Ubuntu 22.04 CI is the independent hosted-runner path. The Windows AppContainer boundary has a Windows real-enforcement test; the macOS Seatbelt boundary has a dedicated `macos-sandbox` CI job, but only a non-skipped macOS run can provide macOS kernel-enforcement evidence.
