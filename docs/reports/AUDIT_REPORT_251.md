# AUDIT_REPORT_251.md

**Iteration**: #251
**Date**: 2026-09-29
**Status**: Complete

## Scope

This iteration delivers the next Phase F work package: a migratable SQLite
metadata index over the file-authoritative memory store. The Markdown entries
under `.auto-memory` remain the single source of truth; the new index is a
derived, rebuildable, single-file metadata layer that can be reconciled on any
machine, so memory metadata becomes migratable without copying entry files. It
does not add any execution authority: the index is a read-path adapter with no
tool, terminal, plugin or network capability, and every stored row cites the
authoritative `entry_id` plus a SHA-256 `content_hash`.

## Changes

- Extracted the deterministic lexical search contract from the fixed role tool
  into `src/core/contracts/memory_search.py` (term extraction, matching,
  5x/3x/1x title/tag/body scoring, snippet alignment, bounded source ids) so
  the role tool and the HTTP surface rank identically for the same entries.
  Role-tool behavior is unchanged; query validation still surfaces as
  `RoleToolProtocolError` inside Workers.
- Added `src/adapters/sqlite_memory_index.py`: stdlib `sqlite3`, versioned
  schema (`index_meta` + `memory_entries`), fingerprint-skip reconcile that
  rewrites rows in one transaction only when entries changed, bounded
  fail-closed writes (entry count, id, title, content, tags, metadata budgets),
  read-only URI mode that never creates or rewrites the database, reentrant
  locking, and fail-closed handling of schema mismatches and malformed rows.
- Added the shared `GET /api/memory/search` surface to the stdlib HTTPServer,
  FastAPI and the Express bridge (proxy passthrough with the query string),
  with a bounded `limit` (default 10, max 50) and stable error envelopes for
  invalid requests and an unavailable index.
- The reconcile input is the same bounded read-only snapshot the listing API
  uses; unchanged stores skip the rewrite entirely via the entry fingerprint.
- Documented the route and a `MemorySearchResponse` schema in
  `contracts/core-api.openapi.json`.
- Archived `AUDIT_REPORT_240.md` and `AUDIT_REPORT_241.md` into
  `docs/reports/archive/` per the ten-report window rule, registered in
  `manifest.json` with SHA-256 and sizes.
- Added 21 focused tests (adapter fail-closed behavior, contract parity, and
  end-to-end store-to-index search) and extended the cross-implementation
  contract test to exercise live memory search through all three service
  surfaces against an isolated memory directory.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_sqlite_memory_index -v` | 21 passed |
| `python -m unittest tests.test_read_only_role_tools` | 12 passed |
| `python tests/run_all.py` | Total: 1201; passed: 1190; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed |
| `git diff --check` | Passed |
| Frontend Vitest `npm test -- --run` | 156 passed |

## Residual Risk

- The index stores raw entry content in the database file inside the memory
  directory; it shares the store's trust domain but is not secret-scanned the
  way redacted API responses are.
- Reconcile is request-scoped and full-replace: a store larger than the 8,192
  row budget fails closed rather than indexing partially.
- Full-text (FTS) retrieval, local embeddings and cross-file citation search
  remain Phase F follow-up work packages; the current query path is still
  lexical.
