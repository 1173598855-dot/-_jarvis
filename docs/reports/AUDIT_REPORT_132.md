# AUDIT_REPORT_132.md

**Iteration**: #132
**Date**: 2026-07-26
**Status**: Complete

## Goal

Migrate the three compatibility synchronous role-dispatch routes to the
terminable Worker path without changing generic orchestrator dispatch, then
record the final delivery evidence.

## Delivered Behavior

- `POST /api/roles/dispatch`, `POST /api/roles/dispatch_by_cap`, and
  `POST /api/roles/batch_dispatch` select a role through `RoleDispatchService`
  and execute via `RoleWorkerSupervisor`.
- The service preserves role/capability selection, response mapping, batch
  ordering, and the established terminal-state error contract while avoiding
  supervisor/lease lock inversion.
- Terminal records remain protected from pruning through observer delivery,
  accepted nonterminal Worker events do not wake terminal waiters, and HTTP
  bind failures still shut down the owned application state.
- Python HTTPServer and FastAPI use the shared Worker service; Express proxies
  the routes with a transport budget that covers Worker timeout and termination
  grace. `JARVIS_E2E_PORT` permits isolated browser verification.
- `POST /api/orchestrator/dispatch` is unchanged. Role-task persistence and
  startup recovery, plus bounded model tool loops through `RoleToolBroker`,
  remain pending Phase 11 work.

## Delivery Commits

- `028515a` `feat: make role worker completion waitable`
- `d35c59e` `fix: make role worker the sole dispatch deadline`
- `908a7cd` `feat: bridge synchronous role dispatch to workers`
- `5fb8759` `feat: migrate fastapi role dispatch to workers`
- `ad00d03` `fix: align fastapi role dispatch lifecycle`
- `0448e0e` `feat: migrate http role dispatch to workers`
- `533d4e7` `feat: declare terminable synchronous role dispatch`
- `a286285` `test: make role dispatch proxy timeout deterministic`
- `3be3727` `fix: allow isolated e2e server ports`
- `8d10fb3` `fix: close role dispatch lifecycle review gaps`

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_run_all_coverage -v` | Passed after registration; 11 tests |
| `python tests/run_all.py` | Total: 352; passed: 350; skipped: 2 |
| `python -m unittest tests.test_agent_factory tests.test_role_worker tests.test_role_dispatch_service tests.test_main tests.test_main_fastapi tests.test_api_contract -v` | 426 passed |
| `python -m unittest discover -s tests -p "test_*.py"` | Total: 1225; passed: 1223; skipped: 2 |
| `python -m compileall -q src tests scripts` | Passed |
| `python scripts/ci_local_integration.py --require-services --timeout 15` | Passed; FastAPI, Express, and Ollama fixture started on ephemeral loopback ports |
| `cd frontend; npm test -- --run` | 129 passed |
| `cd frontend; JARVIS_E2E_PORT=5174; npm run test:e2e` | 5 passed; 1 desktop-only conditional skip |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `python -m ruff check src tests scripts` | Not run; Ruff is not installed in the project environment |

## TDD Evidence

- RED: the aggregate coverage guard failed before registration because the new
  service and adapter classes were absent from `AGGREGATE_TEST_CASES`.
- GREEN: after importing and registering the exact service, HTTP, and FastAPI
  test classes, the coverage guard passed and the canonical aggregate contained
  352 tests.
- The enlarged aggregate made the coverage test's previous 60-second success
  budget expire under full discovery (60.984 seconds). The successful-path
  guard now injects a two-test passing/skipped suite while preserving timeout,
  JSON report, count, and title assertions; its independent one-second timeout
  failure assertion and the standalone canonical delivery gate are unchanged.
- Final review RED tests reproduced observer-time pruning, nonterminal
  `notify_all()` amplification, and skipped state shutdown on bind failure.
  Each passed after the focused lifecycle fixes in `8d10fb3`.

## Residual Work

- Persist role-task records in RunState and reconcile orphan Workers on startup.
- Add a bounded model tool loop only through the default-deny `RoleToolBroker`.
- Keep generic orchestrator dispatch outside the synchronous role-route Worker
  migration until it has its own compatibility and lifecycle design.
