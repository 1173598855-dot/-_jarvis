# AUDIT_REPORT_121.md

**Iteration**: #121
**Date**: 2026-07-13
**Status**: Complete

## Goal

Continue the contract hardening pass by moving the default Python terminal capability behind a process boundary and documenting the remaining Express proxy error paths.

## Changes

- Added `src/core/kernel/terminal_worker.py`, a JSONL child-process worker with a minimal environment, an owned temporary directory, fixed read-only operations, bounded responses, and optional POSIX UID/GID lowering.
- Switched Python HTTPServer and FastAPI default `AppState` terminal instances to `TerminalWorker`; explicit executor injection and lifecycle cleanup remain supported.
- Normalized Express Ollama models/status, system telemetry, Core bridge, and frontend-not-built failures to stable nested `ErrorResponse` envelopes without exposing raw upstream or process-specific messages.
- Upgraded `contracts/core-api.openapi.json` to 1.8.0 with the Express-only `x-jarvis-api-fallback` metadata and shared error responses for covered proxy paths.
- Added worker, live Express, static contract, and aggregate-runner regressions.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Passed: 161 tests |
| `python -m unittest discover -s tests -p "test_*.py"` | Passed: 960 tests |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | Passed: 79 tests |
| `cd frontend; npm run test:e2e` | 5 passed; 1 skipped by project condition |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `git diff --check` | Passed |

## Remaining Work

- The optional real-service profile still needs a prepared Ollama/Core API CI environment using `--require-services`.
- Chat and Runtime production chunks still require low-end-device interaction measurements before further splitting.
- Non-shared orchestrator/role routes remain outside the shared OpenAPI contract because the three service implementations do not expose equivalent endpoints.
