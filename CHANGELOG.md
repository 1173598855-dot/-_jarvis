## Iteration #140 - 2026-07-31

**Protocol**: Express-only Git API contract and OpenAPI boundary
**Status**: Complete

### Achievements

- Upgraded the shared OpenAPI contract to `1.15.0` and declared
  `/api/git/status`, `/api/git/log`, and `/api/git/branches` as Express-only
  through path-level `x-jarvis-implementations`.
- Added Git status, changed-file, commit, log, and branches response schemas
  plus the shared `500` ErrorResponse contract without changing Express Git
  behavior.
- Added a typed `gitBranches` client method and Vitest coverage for all three
  Git read-only endpoints; Express server tests now cover all Git error paths.
- Updated README, development guide, project analysis, report index, AGENTS,
  and iteration-ledger counts so the machine-readable boundary and current
  evidence stay aligned.

### Verification

- `python -m unittest tests.test_api_contract.TestSharedApiContract -v`: 27/27 passed
- `python tests/run_all.py`: 513 total (511 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1384 total (1382 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 136/136 passed
- `cd frontend; JARVIS_E2E_PORT=5189; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `frontend/server.test.js`
- `frontend/src/services/jarvis-api.ts`
- `frontend/src/types/api.ts`
- `frontend/src/tests/jarvis-api.test.ts`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_140.md`
- `docs/reports/AUDIT_REPORT_130.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #139 - 2026-07-31

**Protocol**: Read-only capability registry contract and operational Plugins view
**Status**: Complete

### Achievements

- Added shared OpenAPI `1.14.0` coverage for `GET /api/capabilities/registry`, including bounded scalar query parameters, explicit public capability schemas, repository-relative path constraints, and stable invalid/unavailable errors.
- Added one shared capability query parser and response shaper, then wired repository-root-only discovery and deterministic resolution into Python HTTPServer and FastAPI without accepting caller-controlled roots or lifecycle mutations.
- Hardened the registry after independent review with a shared Plugin API version, real first-party compatibility coverage, a two-second single-flight snapshot cache, per-kind child bounds, bounded discovery issues, and a record-only public wire shape without resolver scores.
- Added an Express Core API proxy that preserves the original registry query and Core status/error envelope; no archive upload, URL fetch, install, enable, rollback, or removal endpoint was introduced.
- Added strict TypeScript capability records, a Core-gated polling client, and a read-only Plugins view inventory for kind counts, lifecycle, provenance, compatibility, health, risk, permissions, and relative origin metadata while preserving existing Plugin lifecycle actions.
- Covered loading, degraded, issue-only, empty, unavailable, and lifecycle states in Vitest, and added Playwright desktop/mobile evidence that capability metadata remains visible without overlap or horizontal overflow at 1440px and 390px.
- Completed Stage D while keeping package content local, disabled, unimported, unexecuted, and unavailable to HTTP mutation callers.

### Verification

- `python -m unittest tests.test_api_contract tests.test_capability_registry tests.test_capability_resolver tests.test_main tests.test_main_fastapi`: 394/394 passed
- `python tests/run_all.py`: 511 total (509 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1382 total (1380 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 135/135 passed
- `cd frontend; JARVIS_E2E_PORT=5189; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `contracts/core-api.openapi.json`
- `src/core/kernel/capability_api.py`
- `src/core/kernel/capability_registry.py`
- `src/core/kernel/capability_resolver.py`
- `src/core/kernel/plugin_sdk.py`
- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server.test.js`
- `frontend/src/types/api.ts`
- `frontend/src/services/jarvis-api.ts`
- `frontend/src/views/PluginsView.tsx`
- `frontend/src/styles/components.css`
- `frontend/src/tests/domain-views.test.tsx`
- `frontend/src/tests/jarvis-api.test.ts`
- `frontend/src/tests/polling-resource.test.ts`
- `frontend/e2e/command-center.spec.ts`
- `tests/test_api_contract.py`
- `tests/test_capability_registry.py`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_139.md`
- `docs/reports/AUDIT_REPORT_129.md`

---

## Iteration #138 - 2026-07-29

**Protocol**: Reversible disabled capability lifecycle with fail-closed drift detection
**Status**: Complete

### Achievements

- Added bounded immutable upgrades that publish content before atomically switching the selected revision; exact retries remain idempotent and a failed index replacement preserves the previous pointer.
- Added explicit and previous-revision rollback with full bundle, manifest, and payload revalidation before any state switch.
- Added canonical revision removal with tombstone restoration on index failure, deterministic fallback selection, last-revision uninstall, and preservation of unknown sibling content.
- Added restart-safe rebuild from the stored bundle and extracted payload, atomic `revision.json` repair, preservation of root-level operator files, and fail-closed rejection of changed or injected payload content.
- Serialized same-root writers with the existing shared `RLock`, bounded each capability to 64 revisions, and kept every installed or restored revision disabled.

### Verification

- `python -m unittest tests.test_file_capability_store -v`: 47/47 passed
- `python tests/run_all.py`: 500 total (498 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1357 total (1355 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/adapters/file_capability_store.py`
- `tests/test_file_capability_store.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_138.md`
- `docs/reports/AUDIT_REPORT_128.md`

---

## Iteration #137 - 2026-07-29

**Protocol**: Verified local package staging with disabled-only publication
**Status**: Complete

### Achievements

- Added a standard-library `FileCapabilityStore` for content-addressed local ZIP bundles without network access, imports, process creation, or automatic enablement.
- Enforced archive byte, entry-count, expanded-byte, and per-file limits before publication; rejected traversal, absolute/drive/backslash paths, symlinks, encrypted members, duplicate/conflicting entries, invalid encodings, unsupported compression, and malformed layouts.
- Required a strict manifest with HTTPS source, one of four allowlisted licenses, a valid payload entrypoint, and verified immutable public metadata that retains repository-relative POSIX paths only.
- Published verified revisions through temporary siblings and `os.replace`, retained disabled lifecycle state, failed closed on damaged state or reparse traversal, and made exact retries idempotent and failed publications retryable.
- Added regression coverage for malformed archives, manifest and license validation, Win32 aliases, state reload, atomic failure cleanup, storage identity aliasing, and all allowlisted licenses.

### Verification

- `python -m unittest tests.test_file_capability_store tests.test_capability_registry -v`: 48/48 passed
- `python tests/run_all.py`: 486 total (484 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1343 total (1341 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `.gitignore`
- `src/adapters/file_capability_store.py`
- `src/core/kernel/capability_manifest.py`
- `tests/test_file_capability_store.py`
- `tests/test_capability_registry.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_137.md`
- `docs/reports/AUDIT_REPORT_127.md`

---

## Iteration #136 - 2026-07-28

**Protocol**: Bounded compatibility evaluation and deterministic local resolution
**Status**: Complete

### Achievements

- Added a strict numeric compatibility grammar with exact and ordered comparators, at most eight clauses, bounded components, and explicit rejection of wildcards, caret ranges, prereleases, and malformed expressions.
- Added immutable runtime targets and capability queries with strict kind, risk, boolean, query-character, length, and `1..100` limit validation.
- Added deterministic local resolution with exact ID/name, token, and description scoring, health/compatibility/provenance/risk quality signals, and capability-ID tie breaking.
- Evaluated unsupported or unavailable runtimes as `unknown`, constraint mismatches as `incompatible`, and allowed callers to filter to proven-compatible results without mutating the registry snapshot.
- Verified the live repository query `memory` resolves only `skill:memory-keeper` with an explicit compatible status; no dependency or external service was introduced.

### Verification

- `python -m unittest tests.test_capability_registry tests.test_capability_resolver tests.test_run_all_coverage -v`: 38/38 passed
- `python tests/run_all.py`: 452 total (450 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1308 total (1306 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/capability_resolver.py`
- `tests/test_capability_resolver.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_136.md`
- `docs/reports/AUDIT_REPORT_126.md`

---

## Iteration #135 - 2026-07-28

**Protocol**: Versioned local capability records and read-only discovery
**Status**: Complete

### Achievements

- Started Stage D with immutable schema-version-1 records for Skill, Plugin, and UI component capabilities, including lifecycle, permissions, compatibility, provenance, health, risk, and public relative paths.
- Added deterministic repository-local discovery that scans only trusted direct roots, never imports plugin code, rejects symlinked capabilities, ignores generated artifacts, and computes bounded content digests.
- Preserved unknown version, source, and license metadata as explicit null/incomplete values instead of inventing provenance; malformed plugin manifests remain visible as invalid high-risk records.
- Discovered the current repository as 22 capability records: 19 Skills, 2 Plugins, and 1 directly exported UI component, with no snapshot-level scan errors.
- Registered the new 14-test suite exactly once in the canonical aggregate runner and recorded the Stage D design and five-iteration implementation plan.

### Verification

- `python -m unittest tests.test_capability_registry tests.test_run_all_coverage -v`: 27/27 passed
- `python tests/run_all.py`: 442 total (440 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1297 total (1295 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/capability_manifest.py`
- `src/core/kernel/capability_registry.py`
- `tests/test_capability_registry.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/superpowers/specs/2026-07-28-capability-registry-safe-deployment-design.md`
- `docs/superpowers/plans/2026-07-28-capability-registry-safe-deployment.md`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_135.md`
- `docs/reports/AUDIT_REPORT_125.md`

---

## Iteration #134 - 2026-07-28

**Protocol**: Bounded read-only model tools inside role Workers
**Status**: Complete

### Achievements

- Added strict role-tool protocol values, schema validation and explicit call, argument, result, total-output and elapsed-time budgets.
- Enabled model-driven tool calls only inside the production `RoleWorker`, with every invocation forced through the default-deny `RoleToolBroker` and recorded in a bounded redacted audit.
- Registered the fixed five-tool read-only catalog for system status, model inventory, orchestrator status, Memory search and repository metadata.
- Extended Ollama request/response and local fixture coverage for deterministic tool calls, while keeping terminal execution, Plugin lifecycle, HTTP capability tokens and generic `/api/orchestrator/dispatch` outside the capability.
- Registered the new suites exactly once, synchronized current project documentation, repaired the encoding of the Iteration 133 report and rolled the audit window to Iteration 125-134.

### Verification

- `python tests/run_all.py`: 428 total (426 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1282 total (1280 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 129/129 passed
- `cd frontend; JARVIS_E2E_PORT=5174; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `tests/test_agent_factory.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_134.md`
- `docs/reports/AUDIT_REPORT_133.md`
- `docs/reports/AUDIT_REPORT_124.md`
- `docs/reports/AUDIT_REPORT_123.md`

---

## Iteration #133 - 2026-07-27

**Protocol**: Role task record persistence and orphan Worker reconciliation
**Status**: Complete

### Achievements

- Created `RoleTaskRecordRepository` for atomic JSON-file persistence of `WorkerTaskRecord` snapshots inside the auto-memory directory.
- Added `RoleWorkerSupervisor.recover_orphans()` that marks non-terminal persisted records as `CRASHED`, terminal-unconfirmed as `FAILED`, and preserves confirmed terminal records.
- Wired `_persist_role_tasks()` into `AppState.shutdown()` to capture active records before supervisor shutdown.
- Added orphan recovery to the FastAPI lifespan: loads persisted records after run-state recovery, reconciles orphans, logs count, and clears the file.

### Verification

- `python tests/run_all.py`: 352/352 (350 passed, 2 skipped)
- `python -m unittest tests.test_role_task_persistence -v`: 13/13 passed
- `python -m unittest tests.test_role_worker tests.test_role_dispatch_service -v`: 45/45 passed
- `python -m compileall -q src tests scripts`: passed

### Files Changed

- `src/adapters/role_task_record_repository.py` (new)
- `src/core/brain/role_worker.py`
- `src/main_fastapi.py`
- `tests/test_role_task_persistence.py` (new, 13 tests)
- `docs/reports/AUDIT_REPORT_133.md`
---
## Iteration #132 - 2026-07-26

**Protocol**: Terminable synchronous role dispatch migration
**Status**: Complete

### Achievements

- Migrated synchronous role, capability, and ordered batch dispatch through `RoleDispatchService` and the terminable `RoleWorkerSupervisor`, while preserving their compatibility response shapes and batch positions.
- Aligned Python HTTPServer, FastAPI, Express proxy budgets, OpenAPI descriptions, and stable Worker failure mappings for the three role routes.
- Kept `/api/orchestrator/dispatch` unchanged; role-task persistence/recovery and bounded model tool loops remain the next Phase 11 work.
- Added canonical aggregate coverage for the service and Python/FastAPI adapters, and made the browser E2E port isolatable with `JARVIS_E2E_PORT`.
- Closed final lifecycle review gaps for terminal observer delivery, nonterminal waiter notifications, HTTP bind-failure cleanup, and the environment-independent aggregate runner guard.

### Verification

- `python tests/run_all.py`: 352 total (350 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1225 total (1223 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `python scripts/ci_local_integration.py --require-services --timeout 15`: passed
- `cd frontend; npm test -- --run`: 129/129 passed
- `cd frontend; JARVIS_E2E_PORT=5174; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python -m ruff check src tests scripts`: not run because Ruff is not installed in the project environment

### Files Changed

- `src/core/brain/role_worker.py`
- `src/main.py`
- `tests/test_main.py`
- `tests/test_role_worker.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_132.md`
- `docs/reports/AUDIT_REPORT_122.md`

---

## Iteration #131 - 2026-07-21

**Protocol**: Atomic recovery publication and role-task lifecycle hardening
**Status**: Complete

### Achievements

- Changed `FileRunStateRepository` to publish immutable revision snapshots before atomically switching the authenticated active manifest.
- Serialized same-root readers and writers with a shared thread lock plus a Windows machine-wide named mutex or POSIX no-follow `flock`, then revalidated the active revision at publication time.
- Added an authenticated save-request fingerprint for exact committed-readback retries, recognized only canonical same-revision staging remnants for initial retry, and made authenticated archive publication idempotently retryable so an archived `run_id` cannot be reactivated as an interrupted save.
- Limited automatic snapshot cleanup to positive canonical revisions on POSIX descriptor-relative paths; Windows and platforms without the required primitives conservatively retain old revision and staging data, while unknown content is always preserved for inspection.
- Kept unconfirmed or record-less Worker runtimes resident and blocked only reuse of their role, preserved the first timeout/cancel intent, serialized process-handle termination and cleanup, and bounded public terminal history before cleanup completes.
- Moved blocking Worker submission and cancellation off the FastAPI event loop, rejected unsupported task fields, and stabilized spawn and terminal-race HTTP errors.
- Added the missing Express create/list/get/cancel proxies for `/api/roles/tasks` and regression coverage for their exact Core API forwarding behavior.
- Reported skipped Python tests separately from passed tests in console and JSON aggregate results, with ledger guards for total accounting.
- Kept legacy synchronous role dispatch, persistent task recovery, and model tool execution explicitly outside this iteration's guarantees.

### Verification

- `python -m unittest tests.test_file_run_state_repository tests.test_role_worker tests.test_main_fastapi.TestRoleTaskLifecycleEndpoints`: 52 total (50 passed, 2 skipped)
- `cd frontend; .\\node_modules\\.bin\\vitest.cmd run server.test.js`: 51/51 passed
- `python tests/run_all.py`: 295 total (293 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1170 total (1168 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `ruff check src tests scripts`: not run because Ruff is not installed in the project environment or `PATH`
- `cd frontend; npm test -- --run`: 113/113 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services --timeout 15`: passed

### Files Changed

- `.gitignore`
- `README.md`
- `frontend/server.js`
- `frontend/server.test.js`
- `src/adapters/file_run_state_repository.py`
- `src/core/brain/role_worker.py`
- `src/main_fastapi.py`
- `tests/test_file_run_state_repository.py`
- `tests/test_main_fastapi.py`
- `tests/test_role_worker.py`
- `tests/test_iteration_ledger.py`
- `tests/test_run_all_coverage.py`
- `tests/worker_fixtures.py`
- `tests/run_all.py`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_131.md`
- `docs/reports/AUDIT_REPORT_121.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

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
