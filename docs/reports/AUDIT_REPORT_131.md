# AUDIT_REPORT_131.md

**Iteration**: #131
**Date**: 2026-07-21
**Status**: Complete

## Goal

Close the lifecycle gaps found after the first asynchronous role-task delivery:
make recovery publication monotonic under concurrent writers, and keep role
termination fail-closed until the child process is confirmed stopped.

## RunState Changes

- Recovery documents are written to an immutable per-revision directory before
  the authenticated active manifest is atomically replaced.
- Repositories that share a root serialize readers and writers with a thread
  lock plus a Windows machine-wide named mutex or POSIX no-follow `flock`, then
  recheck the active revision immediately before publication.
- An authenticated save-request fingerprint permits exact retry after a
  committed manifest cannot be read back. Initial retry recognizes only
  canonical same-revision staging remnants.
- Archive writes the authenticated manifest to `archived-run.json` before
  removing the active pointer. A retry verifies that marker byte-for-byte,
  while ordinary saves reject the pending-archive state.
- POSIX cleanup removes only identity-matched positive canonical revisions with
  the expected flat file set. Windows and capability-limited platforms retain
  old revision/staging data; unknown names and content are always preserved.

## Worker And API Changes

- A Worker that cannot be terminated remains supervised and prevents reuse of
  only its own role until process exit is confirmed.
- A runtime whose authoritative record is missing also remains resident and
  blocks same-role reuse; shutdown can still terminate and close it.
- Timeout and cancellation preserve the first termination intent through exit
  finalization, keep draining the pipe, and cannot overwrite one another during
  deadline races or shutdown.
- Terminal publication prunes eligible history while holding the supervisor
  lock, before cleanup callbacks can expose a transient `max_records` overflow.
- Per-runtime process locks serialize terminate/join/is-alive/close operations,
  preventing monitor cleanup from invalidating a Windows handle in active use.
- FastAPI rejects unsupported task fields, maps process-spawn failures to a
  stable 503 response, and runs blocking submit/cancel operations via
  `asyncio.to_thread`.
- FastAPI maps cancellation races to the actual terminal record instead of
  claiming cancellation succeeded.
- Express now proxies asynchronous role-task create, list, get, and cancel
  requests to the configured Core API.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_file_run_state_repository tests.test_role_worker tests.test_main_fastapi.TestRoleTaskLifecycleEndpoints` | Total: 52; passed: 50; skipped: 2 |
| `cd frontend; .\node_modules\.bin\vitest.cmd run server.test.js` | Passed: 51 tests |
| `python tests/run_all.py` | Total: 295; passed: 293; skipped: 2 |
| `python -m unittest discover -s tests -p "test_*.py"` | Total: 1170; passed: 1168; skipped: 2 |
| `python -m compileall -q src tests scripts` | Passed |
| `ruff check src tests scripts` | Not run: Ruff is not installed |
| `cd frontend; npm test -- --run` | Passed: 113 tests |
| `cd frontend; npm run test:e2e` | Passed: 5; skipped by project condition: 1 |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `python scripts/ci_local_integration.py --require-services --timeout 15` | Passed |

## Independent Review

Successive read-only reviews found and drove fixes for a reader/pruning race,
termination-intent races, transient history overflow, missing-record runtime
loss, archive/reactivation ambiguity, and concurrent Windows process-handle
closure. Deterministic regressions now hold each critical window open and verify
serialized snapshots, monotonic publication, fail-closed role reuse, bounded
public history, exact retry, durable archive evidence, and stable HTTP mapping.

## Residual Risks

- `asyncio.to_thread` work may finish after its HTTP coroutine is cancelled.
- A process that cannot be terminated remains resident and blocks same-role
  reuse; this is intentional fail-closed behavior.
- File contents are flushed, but parent-directory metadata is not explicitly
  synchronized with a directory `fsync`.
- Windows and capability-limited platforms intentionally retain superseded
  revision/staging data; unknown or persistently undeletable content may
  accumulate until inspected.
- POSIX cleanup rechecks directory identity before every deletion, but the
  cooperative repository lock cannot exclude a hostile same-user rename in the
  narrow interval between identity check and unlink.

## Remaining Work

- Migrate legacy synchronous role dispatch to the terminable Worker semantics.
- Persist role-task records in RunState and reconcile orphan Workers at startup.
- Add a bounded model tool loop only through the default-deny `RoleToolBroker`.
