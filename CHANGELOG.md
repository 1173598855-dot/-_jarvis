## Iteration #130 - 2026-07-19

**Protocol**: Terminable asynchronous role-task lifecycle
**Status**: Complete

### Achievements

- Added protocol-version-1 Worker requests, events, terminal states, strict serialization, and confirmed-termination invariants.
- Added a parent-authoritative, Windows-spawn-compatible role Worker supervisor with timeout, cancellation, crash, late-event, bounded-output, bounded-history, and shutdown cleanup behavior.
- Added a fixed production runner that builds child-local Ollama and AgentFactory dependencies and writes returned Token usage into the parent service telemetry.
- Added FastAPI create/list/get/cancel lifecycle endpoints without allowing HTTP callers to choose execution controls.
- Upgraded OpenAPI to `1.12.0` with Worker schemas, stable success/error responses, and conditional confirmation for timeout/cancelled records.
- Registered Worker protocol, supervisor, and API lifecycle coverage in the canonical aggregate suite.
- Kept legacy synchronous role dispatch unchanged and explicitly outside the new cancellation guarantee.

### Verification

- `python -m unittest tests.test_worker_protocol tests.test_role_worker tests.test_main_fastapi.TestRoleTaskLifecycleEndpoints tests.test_api_contract.TestSharedApiContract -v`: 40/40 passed
- `python -m unittest tests.test_role_worker tests.test_agent_factory tests.test_agent_factory_extended tests.test_ollama_manager tests.test_ollama_manager_extended`: 140/140 passed
- `python tests/run_all.py`: 262/262 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1136/1136 passed
- `python -m compileall -q src tests`: passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed

### Files Changed

- `src/core/contracts/worker_protocol.py`
- `src/core/contracts/__init__.py`
- `src/core/brain/role_worker.py`
- `src/main_fastapi.py`
- `contracts/core-api.openapi.json`
- `tests/worker_fixtures.py`
- `tests/test_worker_protocol.py`
- `tests/test_role_worker.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_130.md`
- `docs/superpowers/specs/2026-07-19-role-worker-lifecycle-design.md`
- `docs/superpowers/plans/2026-07-19-role-worker-lifecycle.md`
- `CHANGELOG.md`

---

## Iteration #129 - 2026-07-16

**Protocol**: Authenticated context continuity and startup recovery
**Status**: Complete

### Achievements

- Added versioned immutable run state and concrete next-action contracts with monotonic revisions.
- Added context budget watermarks and deterministic Red-level checkpoint behavior.
- Added shared secret redaction, fixed-section resume documents, and an HMAC-authenticated atomic recovery repository.
- Added Git drift inspection and recovery coordination for Red context, changed HEAD/branch, partial work, and dirty paths.
- Integrated fail-closed one-time active-run recovery into FastAPI startup.
- Added a combined recovery gate covering Red context, dirty work, and a partial agent handoff.

### Verification

- `python -m unittest tests.test_run_state tests.test_context_budget tests.test_resume_document tests.test_file_run_state_repository tests.test_run_lifecycle tests.test_main_fastapi.TestRunRecoveryLifespan tests.test_phase_a_recovery ... -v`: 35/35 passed
- `python tests/run_all.py`: 262/262 passed in the final Iteration 130 branch verification
- `python -m unittest discover -s tests -p "test_*.py"`: 1136/1136 passed in the final Iteration 130 branch verification
- `python -m compileall -q src tests`: passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed

### Files Changed

- `src/core/contracts/run_state.py`
- `src/core/brain/context_budget.py`
- `src/core/brain/resume_document.py`
- `src/core/kernel/secret_redaction.py`
- `src/adapters/file_run_state_repository.py`
- `src/adapters/git_workspace.py`
- `src/app/run_lifecycle.py`
- `src/main_fastapi.py`
- `tests/test_run_state.py`
- `tests/test_context_budget.py`
- `tests/test_resume_document.py`
- `tests/test_file_run_state_repository.py`
- `tests/test_run_lifecycle.py`
- `tests/test_phase_a_recovery.py`
- `tests/test_main_fastapi.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_129.md`
- `docs/superpowers/plans/2026-07-16-phase-a-context-continuity.md`
- `CHANGELOG.md`

---

## Iteration #128 - 2026-07-15

**Protocol**: Default-deny role tool authorization boundary
**Status**: Complete

### Achievements

- Added `RoleToolPolicy` for exact, explicit per-role grants with no wildcard or ambient fallback.
- Added `RoleToolBroker` as the only supported invocation choke point; profile declaration, grant, and registered handler must all match before execution.
- Added immutable decisions and a thread-safe bounded audit history with stable denial reasons.
- Changed `AgentFactory` prompts to expose only authorized tools and to state `[TOOL ACCESS] disabled` by default.
- Separated `declared_tools` from `authorized_tools` in task metadata and kept automatic model-driven tool invocation disabled.
- Evaluated Kontext CLI and Doberman Core, adopting their fail-closed/on-path principles without introducing another runtime or control plane.

### Verification

- `python -m unittest tests.test_role_tools tests.test_agent_factory tests.test_agent_factory_extended -v`: 68/68 passed
- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1080/1080 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/brain/role_tools.py`
- `src/core/brain/agent_factory.py`
- `tests/test_role_tools.py`
- `tests/test_agent_factory.py`
- `docs/superpowers/specs/2026-07-15-role-tool-authorization-design.md`
- `docs/superpowers/plans/2026-07-15-role-tool-authorization.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_128.md`
- `README.md`
- `docs/SETUP.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #127 - 2026-07-15

**Protocol**: Recoverable role errors with timeout-safe state semantics
**Status**: Complete

### Achievements

- Distinguished completed handler errors from timeouts with an internal recoverable marker while preserving the public agent status contract.
- Added atomic orchestrator recovery that retains the failed result, history, counters, and statistics.
- Recovered role agents only for later independent requests; no hidden retry occurs.
- Kept timeout states nonrecoverable because their daemon handler thread may still be running.
- Verified an Ollama error followed by a successful request invokes the manager twice and leaves the role idle.

### Verification

- `python -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v`: 93/93 passed
- `python -m unittest tests.test_agent_factory tests.test_agent_factory_extended tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v`: 154/154 passed
- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1073/1073 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/brain/orchestrator.py`
- `src/core/brain/agent_factory.py`
- `tests/test_orchestrator_extended.py`
- `tests/test_agent_factory.py`
- `docs/superpowers/specs/2026-07-15-role-error-recovery-design.md`
- `docs/superpowers/plans/2026-07-15-role-error-recovery.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_127.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #126 - 2026-07-15

**Protocol**: Production Ollama role execution
**Status**: Complete

### Achievements

- Replaced production role placeholder responses with real Ollama-backed execution through the existing `AgentFactory` injection point.
- Added trusted `JARVIS_ROLE_MODEL` selection, stable upstream failure handling, and a corrected semantic role-selection call.
- Reused each service's single `OllamaManager`, so role calls contribute to the existing Token telemetry instead of creating a parallel client.
- Proved Python HTTPServer, FastAPI, and Express role dispatch return deterministic fixture content while preserving public request and response shapes.
- Kept role tools as prompt metadata only; terminal and plugin capability boundaries remain unchanged.

### Verification

- `python -m unittest tests.test_agent_factory tests.test_agent_factory_extended -v`: 60/60 passed
- `python -m unittest tests.test_main_extended.TestAppStateExtended tests.test_main_fastapi_extended.TestAppState tests.test_api_contract -v`: 30/30 passed
- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1066/1066 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/brain/agent_factory.py`
- `src/main.py`
- `src/main_fastapi.py`
- `tests/test_agent_factory.py`
- `tests/test_main_extended.py`
- `tests/test_main_fastapi_extended.py`
- `tests/test_api_contract.py`
- `README.md`
- `docs/SETUP.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_126.md`
- `docs/superpowers/specs/2026-07-15-production-role-execution-design.md`
- `docs/superpowers/plans/2026-07-15-production-role-execution.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #125 - 2026-07-14

**Protocol**: Role routing parity across three service adapters
**Status**: Complete

### Achievements

- Implemented `GET /api/roles`, `GET /api/roles/{role_name}`, and all role dispatch routes in the Python HTTPServer.
- Unified FastAPI role validation and error envelopes with the shared adapter contract.
- Added Express Core API proxy coverage for role listing, role details, capability dispatch, and batch dispatch.
- Added shared OpenAPI `1.11.0` schemas for role profiles, dispatch results, and role request/response shapes.
- Standardized role errors as `ROLE_NOT_FOUND`, `CAPABILITY_NOT_FOUND`, and `INVALID_REQUEST`, including timeout defaults and bounds.
- Added handler, proxy, and live three-adapter contract regression coverage.

### Verification

- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1058/1058 passed
- `python -m unittest tests.test_api_contract tests.test_main tests.test_main_fastapi`: 302/302 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; node --check server.js`: passed
- `git diff --check`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server.test.js`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `contracts/core-api.openapi.json`
- `README.md`
- `AGENTS.md`
- `docs/reports/README.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/AUDIT_REPORT_125.md`

---

## Iteration #124 - 2026-07-13

**Protocol**: Orchestrator contract integrity and three-adapter dispatch evidence
**Status**: Complete

### Achievements

- Enforced the shared orchestrator history bound of `1..100` in FastAPI and documented `maximum: 100` in OpenAPI.
- Unified Python HTTPServer dispatch defaults and validation with FastAPI: `timeout=300`, `priority=1`, priority `0..3`.
- Added `maximum` support to the local contract shape validator.
- Extended the real loopback harness to dispatch through Python HTTPServer, FastAPI, and Express, validating complete `AgentResult` payloads and invalid-request envelopes.
- Completed the Express Core fixture with the required `error` and `duration_ms` fields.
- Upgraded the shared contract to OpenAPI `1.10.0`, declaring history/dispatch defaults, `timeout` range `1..300`, non-blank text fields, and dispatch `413` responses.
- Rejected malformed JSON extremes and unpaired Unicode surrogates without disconnecting; valid surrogate pairs are normalized to Unicode scalar values.
- Stabilized Python HTTPServer oversized-body responses on Windows with bounded chunked request draining before the `413` envelope.
- Added a two-second total deadline for in-limit HTTPServer request bodies so partial uploads cannot monopolize the single-threaded service.
- Kept role-specific routes explicitly outside the shared contract until their semantics are aligned across all adapters.

### Verification

- `python tests/run_all.py`: 189/189 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1020/1020 passed
- `python -m unittest tests.test_api_contract`: 18/18 passed
- `python -m unittest tests.test_main tests.test_main_fastapi`: 246/246 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 103/103 passed
- `git diff --check`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `contracts/core-api.openapi.json`
- `frontend/server.js`
- `frontend/server.test.js`
- `docs/superpowers/specs/2026-07-13-orchestrator-contract-integrity-design.md`
- `docs/superpowers/plans/2026-07-13-orchestrator-contract-integrity.md`
- `docs/reports/AUDIT_REPORT_124.md`

---

## Iteration #123 - 2026-07-13

**Protocol**: Shared orchestrator route contract across three service adapters
**Status**: Complete

### Achievements

- Added the shared `GET /api/orchestrator/agents`, `GET /api/orchestrator/history`, and `POST /api/orchestrator/dispatch` contract to OpenAPI `1.9.0` with agent, history, dispatch, and proxy error schemas.
- Added Express Core API proxy coverage and aligned Python HTTPServer/FastAPI history limits with the shared `1..100` query range.
- Extended the live three-service contract harness to validate orchestrator response schemas and proxy failure envelopes.

### Verification

- `python tests/run_all.py`: 166/166 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 966/966 passed
- `python -m unittest tests.test_api_contract`: 16/16 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 80/80 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `git diff --check`: passed

### Files Changed

- `contracts/core-api.openapi.json`
- `frontend/server.js`
- `frontend/server.test.js`
- `src/main.py`
- `tests/test_api_contract.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_123.md`

---

## Iteration #122 - 2026-07-13

**Protocol**: Deterministic required-services integration gate
**Status**: Complete

### Achievements

- Added `scripts/local_ollama_fixture.py`, a repository-owned minimal Ollama HTTP fixture covering version, model inventory, process inventory, and streaming chat token frames.
- Added `scripts/ci_local_integration.py`, which allocates ephemeral loopback ports, starts FastAPI/Core, Express, and the fixture, runs `local_integration_profile.py --require-services`, and cleans up child processes and logs on Windows and POSIX hosts.
- Promoted the real-service profile into the GitHub Actions Python contract job without downloading models or depending on an external Ollama daemon.
- Added runner/fixture guard tests and documented the deterministic CI-equivalent command.

### Verification

- `python tests/run_all.py`: 165/165 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 965/965 passed
- `python -m compileall -q src tests scripts`: passed
- `python scripts/ci_local_integration.py --require-services --timeout 15`: passed
- `cd frontend; npm test -- --run`: 79/79 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `git diff --check`: passed

### Files Changed

- `.github/workflows/ci.yml`
- `README.md`
- `docs/SETUP.md`
- `scripts/ci_local_integration.py`
- `scripts/local_ollama_fixture.py`
- `tests/run_all.py`
- `tests/test_ci_workflow.py`
- `tests/test_docs_setup.py`
- `tests/test_local_integration_runner.py`
- `docs/reports/AUDIT_REPORT_122.md`

---

## Iteration #121 - 2026-07-13

**Protocol**: Process-isolated terminal worker and shared proxy error contracts
**Status**: Complete

### Achievements

- Added `TerminalWorker`, a JSONL child-process boundary with a minimal environment, an owned temporary directory, fixed read-only operations, bounded responses, and optional POSIX UID/GID lowering.
- Switched Python HTTPServer and FastAPI default terminal state to `TerminalWorker` while preserving explicit executor injection and lifecycle cleanup.
- Normalized Express Ollama models/status, system telemetry, Core bridge, and frontend-not-built failures to stable nested `ErrorResponse` envelopes.
- Upgraded `contracts/core-api.openapi.json` to 1.8.0 with an Express-only `x-jarvis-api-fallback` description and declared shared proxy error responses.
- Added worker, live Express, and static contract regressions, and registered the new Python contract/profile suites in the aggregate runner.

### Verification

- `python tests/run_all.py`: 161/161 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 960/960 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 79/79 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/terminal_worker.py`
- `tests/test_terminal_worker.py`
- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server.test.js`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `tests/test_local_integration_profile.py`
- `tests/run_all.py`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_121.md`
- `AGENTS.md`
- `CHANGELOG.md`

---
## Iteration #120 - 2026-07-13

**Protocol**: Express API fallback contract and verification-budget hardening
**Status**: Complete

### Achievements

- Unknown Express `/api/*` routes now return `404 API_NOT_FOUND` with the nested `ErrorResponse` shape instead of SPA HTML or the default Express HTML error page.
- Added live GET/POST integration coverage for the API fallback and retained the existing SPA fallback for non-API browser routes.
- Aligned the real system telemetry integration test's timeout with the existing 3-second provider probe budget, removing full-suite scheduling false positives without changing production behavior.
- Added `.test-*.txt` to the ignored verification-artifact patterns.

### Verification

- `python tests/run_all.py`: 158/158 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 949/949 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 77/77 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `git diff --check`: passed

### Files Changed

- `.gitignore`
- `AGENTS.md`
- `frontend/server.js`
- `frontend/server.test.js`
- `docs/reports/AUDIT_REPORT_120.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `CHANGELOG.md`

---
## Iteration #119 - 2026-07-13

**Protocol**: Non-streaming contract validation, telemetry bounds, and internal executor containment
**Status**: Complete

### Achievements

- Validated the non-streaming Ollama success shape before returning data from Python HTTPServer, FastAPI, or Express; malformed or incomplete upstream `200` responses now normalize to `502 OLLAMA_UPSTREAM_ERROR`.
- Added a live three-service regression for that invalid-success response path and aligned stale test fixtures with the declared response schema.
- Added bounded telemetry provider probes so a slow `systeminformation` call degrades the relevant metric instead of exhausting the API test budget.
- Gave the default internal terminal executor an owned temporary working directory, a minimal environment, override rejection, explicit cleanup, and FastAPI/Python HTTP service lifecycle cleanup.

### Verification

- `python tests/run_all.py`: 158/158 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 949/949 passed
- `python -m compileall -q src tests`: passed
- `cd frontend; npm test -- --run`: 75/75 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/kernel/ollama_manager.py`
- `src/core/kernel/terminal_executor.py`
- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server/system-metrics.js`
- `frontend/server/system-metrics.test.js`
- `tests/test_api_contract.py`
- `tests/test_main_fastapi.py`
- `tests/test_main_fastapi_extended.py`
- `tests/test_ollama_manager_extended.py`
- `tests/test_terminal_executor_extended.py`
- `RISK_COMPONENTS.log`
- `docs/reports/AUDIT_REPORT_119.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `CHANGELOG.md`

---
## Iteration #118 - 2026-07-13

**Protocol**: Local integration profile documentation
**Status**: Complete

### Achievements

- Added local integration profile documentation to README.md test section
- Clarified that `local_integration_profile.py` is an opt-in check requiring running Express + Ollama services
- Documented `--require-services` flag for enforcing service availability in CI environments
- Made existing real-service validation capabilities more discoverable without code changes

### Verification

- `python tests/run_all.py`: 155/155 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 940/940 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 74/74 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `README.md`
- `docs/reports/AUDIT_REPORT_118.md`
- `docs/reports/README.md`
- `CHANGELOG.md`

---
## Iteration #117 - 2026-07-13

**Protocol**: Test suite alignment + Ollama error contract verification
**Status**: Complete

### Achievements

- Fixed test count documentation mismatch: updated from 154 to actual 155 tests in CHANGELOG and AUDIT_REPORT_116.
- Updated Ollama chat test to accept 502 status when service is unavailable, aligning with current implementation.
- Verified cross-service Ollama error contract compliance: all three services (Python HTTPServer, FastAPI, Express) correctly return 502 with OLLAMA_UPSTREAM_ERROR code.
- Confirmed shared OpenAPI contract version 1.6.0 properly documents 502 ErrorResponse for non-streaming chat failures.

### Verification

- `python tests/run_all.py`: 155/155 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 940/940 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 74/74 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `CHANGELOG.md`
- `docs/reports/AUDIT_REPORT_116.md`
- `docs/reports/AUDIT_REPORT_117.md`
- `docs/reports/README.md`
- `tests/test_main_fastapi.py`

---
## Iteration #116 - 2026-07-12

**Protocol**: Phase 3 research + chunked ASGI request-body boundary
**Status**: Complete

### Achievements

- Extended FastAPI's 32 KiB limit from declared-length requests to headerless/chunked ASGI body streams.
- Rejected an over-limit sequence at the receive boundary with the existing `413 REQUEST_BODY_TOO_LARGE` envelope, before forwarding any body data to downstream parsing.
- Preserved valid exact-limit semantics and guarded against downstream duplicate responses after middleware rejection.
- Added a deterministic ASGI regression for a 32 KiB chunk followed by one extra byte.

### Verification

- `python tests/run_all.py`: 155/155 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 940/940 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 74/74 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/main_fastapi.py`
- `tests/test_main_fastapi.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/AUDIT_REPORT_116.md`
- `docs/reports/README.md`
- `docs/superpowers/specs/2026-07-12-chunked-body-limit-design.md`
- `docs/superpowers/plans/2026-07-12-chunked-body-limit.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #115 - 2026-07-12

**Protocol**: Phase 3 research + shared request-body boundary
**Status**: Complete

### Achievements

- Advanced the shared API contract to `1.6.0` and declared `413 REQUEST_BODY_TOO_LARGE` for POST SSE requests.
- Applied a byte-based 32 KiB declared-body limit before JSON parsing in Python HTTPServer, FastAPI, and Express.
- Standardized oversized JSON as a nested, non-sensitive `413` envelope and verified it does not reach the Ollama stream path.
- Added real three-service regression coverage for the same 32 KiB-plus JSON payload.

### Verification

- `python tests/run_all.py`: 153/153 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 939/939 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 74/74 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/AUDIT_REPORT_115.md`
- `docs/reports/README.md`
- `docs/superpowers/specs/2026-07-12-request-body-limit-design.md`
- `docs/superpowers/plans/2026-07-12-request-body-limit.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #114 - 2026-07-12

**Protocol**: Phase 3 research + cross-service POST SSE contract
**Status**: Complete

### Achievements

- Advanced the shared OpenAPI contract to `1.5.0` and declared `POST /api/ollama/chat/stream` with JSON input, canonical SSE output, and 400 ErrorResponse semantics.
- Added the same JSON-body stream route to Python HTTPServer and FastAPI while retaining GET compatibility for EventSource clients.
- Reused one canonical SSE writer per Python service and rejected non-object POST bodies across Express, Python HTTPServer, and FastAPI as `400 INVALID_REQUEST`.
- Added real loopback tests that send the same POST stream request to all three implementations and validate canonical frames, one terminal marker, and invalid-body error envelopes.

### Verification

- `python tests/run_all.py`: 152/152 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 938/938 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 74/74 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/AUDIT_REPORT_114.md`
- `docs/reports/README.md`
- `docs/superpowers/specs/2026-07-12-post-sse-contract-design.md`
- `docs/superpowers/plans/2026-07-12-post-sse-contract.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #113 - 2026-07-12

**Protocol**: Phase 3 research + Express Git error envelope
**Status**: Complete

### Achievements

- Normalized Express Git process failures as `GIT_COMMAND_FAILED` ErrorResponse objects and removed raw system error exposure.
- Added trusted process-level `JARVIS_GIT_COMMAND` configuration, defaulting to `git`, plus child-process error handling that keeps the server alive.
- Added a real Express subprocess regression for an unavailable Git executable and documented the server-only override.

### Verification

- `python tests/run_all.py`: 151/151 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 937/937 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 74/74 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `frontend/server.js`
- `frontend/server.test.js`
- `docs/SETUP.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/AUDIT_REPORT_113.md`
- `docs/reports/README.md`
- `docs/superpowers/specs/2026-07-12-express-git-error-envelope-design.md`
- `docs/superpowers/plans/2026-07-12-express-git-error-envelope.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #112 - 2026-07-12

**Protocol**: Phase 3 research + canonical SSE contract
**Status**: Complete

### Achievements

- Advanced OpenAPI to 1.4.0 and declared GET /api/ollama/chat/stream plus canonical content/error event schemas.
- Standardized Python HTTPServer, FastAPI, and Express stream frames as { model, content, done }, preserving native token counters.
- Normalized failures as OLLAMA_STREAM_ERROR and prevented error streams from sending the successful [DONE] marker.
- Added cross-service loopback stream tests, canonical browser-parser tests, and query-path routing coverage.

### Verification

- `python tests/run_all.py`: 151/151 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 937/937 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 73/73 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server.test.js`
- `frontend/e2e/command-center.spec.ts`
- `frontend/src/services/chat-stream.ts`
- `frontend/src/tests/chat-stream.test.ts`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/AUDIT_REPORT_112.md`
- `docs/reports/README.md`
- `docs/superpowers/plans/2026-07-12-canonical-sse-contract.md`
- `AGENTS.md`
- `CHANGELOG.md`

---


## Iteration #111 - 2026-07-12

**Protocol**: Phase 3 research + P0 terminal capability contract and verification
**Status**: Complete

### Achievements

- Advanced OpenAPI to `1.3.0` with terminal capability-header, 401, and 403 contracts.
- Declared the fixed-operation `200` terminal result schema and added a live Python HTTPServer, FastAPI, and Express-to-Core capability-token success-path regression.
- Completed the five-round P0 mitigation: loopback defaults, default-deny CORS, token-gated terminal access, fixed read-only operations, and Express Core-only execution.
- Updated Docker, startup documentation, GitHub intelligence, risk archive, and project analysis.

### Verification

- `python tests/run_all.py`: 147/147 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 931/931 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 71/71 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/kernel/runtime_security.py`
- `src/core/kernel/terminal_policy.py`
- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server/runtime-security.js`
- `frontend/server.js`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `docker-compose.yml`
- `README.md`
- `docs/SETUP.md`
- `docs/reports/AUDIT_REPORT_111.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `RISK_COMPONENTS.log`
- `CHANGELOG.md`

---

## Iteration #110 - 2026-07-12

**Protocol**: Express terminal execution consolidation
**Status**: Complete

### Achievements

- Removed Express direct Python terminal launching and delegated the operation to Core API policy.
- Added a JSON request-size limit and removed Express technology header exposure.

### Verification

- `cd frontend; npm test -- --run`: passed

### Files Changed

- `frontend/server.js`
- `frontend/server.test.js`
- `docs/reports/AUDIT_REPORT_110.md`
- `CHANGELOG.md`

---

## Iteration #109 - 2026-07-12

**Protocol**: Fixed terminal operation policy
**Status**: Complete

### Achievements

- Replaced general HTTP command input with bounded, fixed read-only diagnostic operations.
- Blocked interpreters, package managers, downloaders, environment readers, unknown commands, and unsupported arguments before process creation.

### Verification

- `python -m unittest tests.test_runtime_security -v`: passed

### Files Changed

- `src/core/kernel/terminal_policy.py`
- `tests/test_runtime_security.py`
- `docs/reports/AUDIT_REPORT_109.md`
- `CHANGELOG.md`

---

## Iteration #108 - 2026-07-12

**Protocol**: Terminal capability gate
**Status**: Complete

### Achievements

- Disabled terminal HTTP access unless explicitly enabled with a nonempty capability token.
- Added constant-time token comparison and standard 401/403 responses across all services.

### Verification

- Focused terminal policy regressions: passed

### Files Changed

- `src/core/kernel/runtime_security.py`
- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server/runtime-security.js`
- `frontend/server.js`
- `docs/reports/AUDIT_REPORT_108.md`
- `CHANGELOG.md`

---

## Iteration #107 - 2026-07-12

**Protocol**: Local-first listener and CORS defaults
**Status**: Complete

### Achievements

- Changed the Express default listener to loopback and constrained CORS to explicit local Vite origins.
- Bound Docker development ports to the host loopback interface.

### Verification

- Focused CORS regressions: passed

### Files Changed

- `frontend/server.js`
- `src/main.py`
- `src/main_fastapi.py`
- `docker-compose.yml`
- `docs/reports/AUDIT_REPORT_107.md`
- `CHANGELOG.md`

---

## Iteration #106 - 2026-07-12

**Protocol**: Phase 3 research + FastAPI request-validation contract
**Status**: Complete

### Achievements

- Mapped a missing terminal `command` field to the shared `400 MISSING_COMMAND` envelope across all three services.
- Replaced the FastAPI-only 422 assertion with a real cross-implementation contract regression.
- Finished the five-round error-contract pass: malformed body, invalid shape, missing plugin ID, unknown plugin, and missing command.
- Archived the discovered pre-existing public terminal-execution exposure in `RISK_COMPONENTS.log` without changing deployment defaults.

### Verification

- `python tests/run_all.py`: 135/135 passed
- `python -m unittest discover -s tests -p "test_*.py"`: passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/main_fastapi.py`
- `tests/test_api_contract.py`
- `tests/test_main_fastapi.py`
- `RISK_COMPONENTS.log`
- `docs/reports/AUDIT_REPORT_106.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/README.md`
- `CHANGELOG.md`

---

## Iteration #105 - 2026-07-12

**Protocol**: Shared plugin-not-found contract
**Status**: Complete

### Achievements

- Standardized unknown plugin loads as `404 PLUGIN_NOT_FOUND` in both Python implementations and the Express proxy.
- Added the shared OpenAPI 404 response and a live three-service regression.

### Verification

- `python -m unittest tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas -v`: passed after expected red failure

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `docs/reports/AUDIT_REPORT_105.md`
- `CHANGELOG.md`

---

## Iteration #104 - 2026-07-12

**Protocol**: Shared plugin request-validation contract
**Status**: Complete

### Achievements

- Standardized missing plugin identifiers as `400 MISSING_PLUGIN_ID`.
- Declared `POST /api/plugins/load` request and error response in OpenAPI and verified all three services.

### Verification

- `python -m unittest tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas -v`: passed after expected red failure

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `docs/reports/AUDIT_REPORT_104.md`
- `CHANGELOG.md`
## Iteration #121 - 2026-07-13

**Protocol**: Process-isolated terminal worker and shared proxy error contracts
**Status**: Complete

### Achievements

- Added `TerminalWorker`, a JSONL child-process boundary with a minimal environment, an owned temporary directory, fixed read-only operations, bounded responses, and optional POSIX UID/GID lowering.
- Switched Python HTTPServer and FastAPI default terminal state to `TerminalWorker` while preserving explicit executor injection and lifecycle cleanup.
- Normalized Express Ollama models/status, system telemetry, Core bridge, and frontend-not-built failures to stable nested `ErrorResponse` envelopes without exposing upstream or process-specific messages.
- Upgraded `contracts/core-api.openapi.json` to 1.8.0 with an Express-only `x-jarvis-api-fallback` description and declared shared error responses for the covered proxy paths.
- Added worker, live Express, and static contract regressions covering process isolation and stable error shapes.

### Verification

- `python tests/run_all.py`: 161/161 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 960/960 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 79/79 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/terminal_worker.py`
- `tests/test_terminal_worker.py`
- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server.test.js`
- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/README.md`
- `CHANGELOG.md`

---
