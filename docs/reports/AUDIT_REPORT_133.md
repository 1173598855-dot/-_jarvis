# AUDIT_REPORT_133.md

**Iteration**: #133
**Date**: 2026-07-27
**Status**: Complete

## Goal

Persist role task records so they survive process restarts, and reconcile orphan
Worker records on FastAPI startup.

## Delivered Behavior

- **RoleTaskRecordRepository** (src/adapters/role_task_record_repository.py):
  Thread-safe, atomic JSON-file persistence of WorkerTaskRecord snapshots
  inside the auto-memory directory, using the same atomic-write convention as
  FileRunStateRepository.

- **Orphan reconciliation** (RoleWorkerSupervisor.recover_orphans()):
  - Non-terminal persisted records are marked as CRASHED with a clear
    \"terminated by restart\" error message — worker processes no longer exist.
  - Terminal-unconfirmed records are promoted to FAILED with confirmation,
    since the worker process died before the confirmation handoff.
  - Confirmed terminal records are preserved as-is.
  - Duplicate 	ask_id values are silently skipped.
  - The bounded record cap is enforced; excess records are pruned.

- **Startup wiring** (AppState in src/main_fastapi.py):
  - _persist_role_tasks() saves active records before supervisor shutdown.
  - The FastAPI lifespan loads persisted records after un_lifecycle.recover_active(),
    reconciles orphans via ecover_orphans(), then clears the persisted file.
  - Orphan recovery is logged at INFO level with a record count.

- **Shutdown wiring**: _persist_role_tasks runs as the first cleanup step in
  AppState.shutdown(), before the supervisor is shut down, ensuring the
  last-available state is captured even on abnormal exits.

## Files Changed

- src/adapters/role_task_record_repository.py (new)
- src/core/brain/role_worker.py — added ecover_orphans()
- src/main_fastapi.py — wired persistence and recovery into AppState/lifespan
- 	ests/test_role_task_persistence.py (new, 13 tests)

## Verification

| Command | Result |
|---|---|
| python tests/run_all.py | 352 total; 350 passed; 2 skipped; 0 errors |
| python -m unittest tests.test_role_task_persistence tests.test_role_worker tests.test_role_dispatch_service -v | 58 passed |
| python -m unittest tests.test_role_task_persistence -v | 13 passed |
| python -m compileall -q src tests scripts | Passed |
| python -m compileall -q src/main_fastapi.py src/core/brain/role_worker.py src/adapters/role_task_record_repository.py | Passed |
