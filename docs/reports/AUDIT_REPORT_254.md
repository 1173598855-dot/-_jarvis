# AUDIT_REPORT_254.md

**Iteration**: #254
**Date**: 2026-09-30
**Status**: Complete

## Scope

This iteration delivers the next Phase F work package: bounded memory export
and import with id-level deduplication. Together with the migratable SQLite
index (Iteration 251) this completes the migration story — the authoritative
Markdown entries can now be moved or merged between stores through a
structured, validated API instead of raw directory copies. No execution
authority is added: export reads through the existing bounded read-only
snapshot, and import writes through the existing journalled
`MemoryStore.store()` with its lossless round-trip check.

## Changes

- Added `export_memory_entries_for_api`: a bounded, lossless snapshot in the
  same record shape the store parses, including id, metadata, tags,
  timestamps, access statistics, importance, token count, compression flag
  and parent linkage. Bounds come from the shared read-only snapshot budgets
  (256 files, 1 MiB per file, 32 MiB total).
- Added `import_memory_entries_for_api`: per-record validation (type, title,
  content, tags, metadata, timestamps, statistics), id-level deduplication
  against the current store and inside the batch, and deterministic id
  recomputation via `MemoryEntry.create` when a record omits its id, so the
  same record imports to the same id on every machine. Repeated imports are
  idempotent; per-record failures are rejected without aborting the batch and
  reported as bounded, content-free notes (max 32).
- Added `GET /api/memory/export` and `POST /api/memory/import` to the stdlib
  HTTPServer, FastAPI and the Express bridge (proxy passthrough), with the
  shared 32 KiB body limit and a 256-entry batch cap governing request size.
  Stable error envelopes: `INVALID_REQUEST` (400), `MEMORY_IMPORT_FAILED`
  (500), plus the standard proxy `502/503`.
- Documented both routes, `MemoryExportEntry/Response` and
  `MemoryImportResponse` schemas in `contracts/core-api.openapi.json`.
- Added 7 focused unit tests (lossless round trip including custom ids and
  parent linkage, idempotency, in-batch dedup, deterministic id computation,
  per-record rejection isolation, batch/payload bounds, skip-on-existing) and
  extended the cross-implementation contract test: live export through all
  three service surfaces and live import where only the first surface lands
  and the others dedupe to skipped against the same authoritative store.
- Archived `AUDIT_REPORT_244.md` per the ten-report window rule, registered
  in `manifest.json` with SHA-256 and size.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_memory_transfer -v` | 7 passed |
| `python tests/run_all.py` | Total: 1235; passed: 1224; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed |
| `git diff --check` | Passed |
| Frontend Vitest `npm test -- --run` | 157 passed |

## Residual Risk

- The frontend Vitest suite showed intermittent failures in pre-existing
  view tests under heavy machine load during early verification runs; the
  failures were never attributed to the changed files and seven consecutive
  full runs (157 tests) passed afterwards, but the flakiness itself remains
  pre-existing risk.
- Import trusts record-level validation but not cross-record consistency: an
  imported parent_id may reference an id that never arrives, exactly like a
  raw directory copy.
- Export is a point-in-time snapshot over the bounded read; concurrent
  writes during export are reflected or not depending on scan order, the
  same as the existing listing endpoint.
- Backup/restore archives and retention policies remain Phase F follow-up
  work packages alongside `MemoryRepository` contract convergence.
