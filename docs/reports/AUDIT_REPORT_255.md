# AUDIT_REPORT_255.md

**Iteration**: #255
**Date**: 2026-09-30
**Status**: Complete

## Scope

This iteration delivers the next Phase F work package: verified memory
backup, inventory and non-destructive restore, plus the first retention
slice (backup retention pruning). Backups are self-describing single files
under `.auto-memory/backups/` whose envelopes embed the SHA-256 of the
canonically serialized export snapshot, so restore verifies integrity
without external metadata. Restore merges through Iteration 254's idempotent
id-level import and never deletes existing entries. No execution authority
is added: all operations stay inside the memory directory's trust domain
using stdlib only.

## Changes

- Added `create_memory_backup_for_api`: writes the bounded export snapshot
  into `backups/backup-<21-char microsecond stamp>-<8 hex>.json` via a
  temporary file and atomic replace, verifies the written file by read-back
  (guide §11.5 pattern), and prunes backups beyond the retention cap
  (default 8, bounded 1-64) oldest-first. The microsecond stamp makes name
  order equal creation order — filesystem mtime proved too coarse for
  back-to-back writes on Windows, which surfaced as a flaky prune during
  verification and was fixed before delivery.
- Added `list_memory_backups_for_api`: newest-first inventory where each
  entry reports its recorded SHA-256, size, entry count and an `intact`
  flag recomputed from the file at read time.
- Added `restore_memory_backup_for_api`: strict backup-name pattern
  (fail-closed against path traversal), resolved-path containment check,
  bounded read (33 MiB), canonical SHA-256 verification, then merge through
  idempotent import returning the standard accounting.
- Exposed `POST /api/memory/backup`, `GET /api/memory/backups` and
  `POST /api/memory/restore` on the stdlib HTTPServer, FastAPI and the
  Express bridge (proxy passthrough) with stable envelopes:
  `INVALID_REQUEST` (400), `MEMORY_BACKUP_NOT_FOUND` (404),
  `MEMORY_BACKUP_FAILED` (500) and standard proxy `502/503`.
- Documented the three routes and the `MemoryBackupCreateResponse`,
  `MemoryBackupSummary` and `MemoryBackupListResponse` schemas in
  `contracts/core-api.openapi.json`.
- Added 6 focused unit tests (round trip across stores, tamper detection on
  restore and inventory, name validation, retention pruning, retention
  bounds, empty-store backup) and extended the cross-implementation contract
  test: live backup through the stdlib server, inventory through the Express
  bridge, and restore through FastAPI deduplicating against the shared
  authoritative store.
- Archived `AUDIT_REPORT_245.md` per the ten-report window rule, registered
  in `manifest.json` with SHA-256 and size.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_memory_transfer -v` | 13 passed |
| `python tests/run_all.py` | Total: 1241; passed: 1230; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed |
| `git diff --check` | Passed |
| Frontend Vitest `npm test -- --run` | 158 passed |

## Residual Risk

- Backups cover at most the bounded export snapshot (256 files, 1 MiB per
  file); stores beyond that budget produce partial backups, consistent with
  the listing and export endpoints.
- Restore is merge-only: entries deleted after the backup was taken are
  re-imported, and entries created after it are kept. A destructive
  point-in-time rollback would need explicit approval and is not provided.
- Backup pruning is best-effort; a locked file survives one cycle and is
  retried by the next backup.
- Retention policies for the entries themselves and `MemoryRepository`
  contract convergence remain Phase F follow-up work packages.
