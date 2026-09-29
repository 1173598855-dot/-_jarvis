# AUDIT_REPORT_250.md

**Iteration**: #250
**Date**: 2026-09-27
**Status**: Complete

## Scope

This iteration adds a dependency-aware workflow scheduler above the existing
single- and batch-dispatch surfaces. It introduces one new stdlib-only module
(`src/core/brain/workflow_dag.py`), one API route on all three service
surfaces, and the matching read-only contract entry. It does not add any new
execution authority: every node still dispatches through the existing role
dispatch service and its terminable Worker.

## Changes

- Added `Workflow` graph validation: duplicate node ids, self-dependency,
  unknown dependencies, cycles (via Kahn layering) and node/edge caps are all
  rejected before execution.
- Added deterministic topological layering and a `WorkflowEngine` that runs
  one layer concurrently (bounded by `max_parallelism`) and layers in order.
- Added two failure policies: `fail_fast` (raises `WorkflowExecutionError` and
  skips the remainder) and `continue` (returns aggregated status without
  raising). Dependents of a failed node are `skipped`, never silently run.
- Exposed `POST /api/workflows/run` on the stdlib HTTPServer, FastAPI and the
  Express bridge, with a bounded proxy timeout derived from the node budget and
  parallelism.
- Documented the route in `contracts/core-api.openapi.json` with a
  `WorkflowRunResponse` schema.
- Added 19 focused unit tests and 2 Express proxy tests.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_workflow_dag -v` | 19 passed |
| `python tests/run_all.py` | Total: 1180; passed: 1169; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `git diff --check` | Passed |
| Frontend Vitest `server.test.js` | 68 passed |

## Residual Risk

- The engine bounds scheduling, not wall-clock isolation: a node's own Worker
  timeout still governs its execution.
- `max_parallelism` is capped at 16 and does not attempt cross-run fairness.
- No workflow persistence yet; a workflow run is request-scoped.
