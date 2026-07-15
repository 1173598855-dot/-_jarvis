# AUDIT_REPORT_120.md

**Iteration**: #120
**Date**: 2026-07-13
**Status**: Complete

## Goal

Continue the contract hardening pass by making Express API fallbacks machine-readable and keeping the browser verification baseline stable under realistic telemetry latency.

## Changes

- Added a final Express `/api/*` fallback that returns `404 API_NOT_FOUND` as the shared nested `ErrorResponse` shape.
- Added live GET and POST integration coverage proving unknown API requests cannot fall through to the SPA HTML page or Express's default HTML error response.
- Increased only the real system-telemetry integration test budget to 10 seconds. This matches the existing 3-second per-provider probe budget and avoids false failures from full-suite startup contention; production timeout behavior is unchanged.
- Added `.test-*.txt` to the ignored verification-artifact patterns.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Passed: 158 tests |
| `python -m unittest discover -s tests -p "test_*.py"` | Passed: 949 tests |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | Passed: 77 tests |
| `cd frontend; npm run test:e2e` | 5 passed; 1 skipped by project condition |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `git diff --check` | Passed |

## Remaining Work

- The internal executor still requires an OS-level low-privilege worker before any script-capability expansion.
- The optional real-service profile still needs a prepared Ollama/Core API CI environment using `--require-services`.
- The shared OpenAPI document still needs an explicit fallback description for `API_NOT_FOUND` and the remaining proxy error paths.
- Chat and Runtime production chunks still require low-end-device interaction measurements before further splitting.
