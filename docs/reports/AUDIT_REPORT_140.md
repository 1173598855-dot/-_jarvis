# AUDIT_REPORT_140.md

**Iteration**: #140
**Date**: 2026-07-31
**Status**: Complete

## Goal

Close the Express-only Git API contract gap so the shared OpenAPI document
explicitly records which Git endpoints exist, what they return, and which
service implements them.

## Delivered Behavior

- Upgraded the shared OpenAPI contract to `1.15.0`.
- Declared `/api/git/status`, `/api/git/log`, and `/api/git/branches` with
  path-level `x-jarvis-implementations: ["frontend/server.js"]`.
- Added `GitStatus`, `GitChangedFile`, `GitCommit`, `GitLogResponse`, and
  `GitBranchesResponse` schemas plus the shared `500` ErrorResponse contract.
- Added a typed `gitBranches` client method and Vitest coverage for the Git
  read-only endpoints while leaving Express behavior unchanged.
- Updated README, development guide, project analysis, report index, AGENTS,
  and the iteration ledger to reflect the new contract boundary and counts.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_api_contract.TestSharedApiContract -v` | Passed: 27 tests |
| `python tests/run_all.py` | Total: 513; passed: 511; skipped: 2 |
| `python -m unittest discover -s tests -p "test_*.py"` | Total: 1384; passed: 1382; skipped: 2 |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | Passed: 136 tests |
| `cd frontend; JARVIS_E2E_PORT=5189; npm run test:e2e` | Passed: 7; skipped: 1 conditional desktop case |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `python scripts/ci_local_integration.py --require-services` | Passed |
| `git diff --check` | Passed |

## Scope Boundary

The Git endpoints remain Express-only and read-only. Python HTTPServer and
FastAPI do not implement or proxy them; the OpenAPI path-level marker is the
machine-readable boundary.
