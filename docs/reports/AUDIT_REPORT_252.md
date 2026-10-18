# AUDIT_REPORT_252.md

**Iteration**: #252
**Date**: 2026-09-30
**Status**: Complete

## Scope

This iteration delivers the next Phase F work package: trigram full-text
retrieval over the migratable SQLite memory metadata index. The Markdown
memory store stays the single source of truth; the FTS5 table is derived
metadata inside the same index database, synced in the same bounded reconcile
transaction. No execution authority is added: the retrieval path remains a
read-only adapter surface, and the fixed role-tool catalog keeps its exact
lexical contract.

## Changes

- Bumped the index schema to version 2 with an FTS5 `memory_fts` virtual
  table (`tokenize='trigram'`, `entry_id UNINDEXED`). Availability of FTS5
  trigram is probed at open time; a build without it fails closed with a
  clear error instead of silently degrading the index.
- Reconcile now rebuilds the FTS table in the same transaction as the
  metadata rows, so the fingerprint skip continues to guarantee that both
  tables match the authoritative snapshot exactly.
- Version 1 databases are transparently reset to version 2 (drop and
  recreate) because the index is derived data the Markdown store can always
  rebuild; unknown newer versions still fail closed, as does read-only access
  to an old-version database.
- Added `SqliteMemoryIndex.search_fulltext`: bounded, quote-safe, OR-combined
  trigram MATCH joined back to the metadata rows, ordered by FTS5 BM25
  `rank`, returning each hit with its positive relevance.
- Added the shared `memory_fulltext_terms` contract rule: casefolded
  alphanumeric or CJK runs of at least 3 characters (the trigram minimum);
  shorter queries are directed to the lexical path instead of silently
  degrading.
- Extended `GET /api/memory/search` with a bounded `mode` parameter
  (`lexical` default, `fulltext`) on the stdlib HTTPServer, FastAPI and the
  Express bridge (query passthrough, unchanged). Responses now declare the
  `mode`, and the `score` field is the lexical 5x/3x/1x integer or the BM25
  relevance float depending on mode; ranking stays deterministic with
  title/id tie-breaks.
- Documented the parameter and updated the `MemorySearchResponse` schema in
  `contracts/core-api.openapi.json`.
- Added 10 focused tests (CJK and ASCII trigram matching, OR semantics and
  BM25 ordering, short/unsafe term rejection, FTS drift, v1-to-v2 reset,
  mode validation) and extended the cross-implementation contract test to
  exercise live `mode=fulltext` search through all three service surfaces.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_sqlite_memory_index -v` | 31 passed |
| `python tests/run_all.py` | Total: 1211; passed: 1200; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed |
| `git diff --check` | Passed |

## Residual Risk

- Trigram matching requires at least 3 characters, so single CJK characters
  and very short ASCII words are rejected in `fulltext` mode with a clear
  error; the lexical default mode remains the exact-contract path for them.
- FTS5 BM25 relevance and the lexical score are different measures; the
  response declares the mode so consumers cannot confuse them.
- The index database stores raw entry content in FTS form inside the memory
  directory, sharing the store's trust domain; it is not secret-scanned.
- Local embeddings and `MemoryRepository` contract convergence remain Phase F
  follow-up work packages.
