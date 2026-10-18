# AUDIT_REPORT_257.md

**Iteration**: #257
**Date**: 2026-09-30
**Status**: Complete

## Scope

This iteration delivers the last open Phase F work package: entry-level
retention policies. With it, the Phase F exit gate — memory is explainable,
deletable and migratable — is met by delivered, verified capability: provenance
since Iterations 249/251, migration since 254/255, and now explicit,
bounded, opt-in deletion through `POST /api/memory/prune`. Retention is
default-off: every request must state at least one criterion, probe entries
are always excluded, and deletion goes through the journalled store path.

## Changes

- Added `MemoryStore.delete(memory_type, entry_id)`: a general journalled
  deletion path reusing the probe deletion machinery (frontmatter identity,
  reparse-point checks, two-stage stat snapshot comparison, index-aware
  publish). It refuses integration probe entries on purpose — they leave
  only through `delete_probe` and its token check — and returns `False`
  for unknown ids, type mismatches and unparsable files.
- Bumped the `MemoryRepository` port to version 2 with `delete` in the
  protocol; the conformance checker now verifies that writable repositories
  delete a stored entry by type and id and that read-only repositories
  refuse deletion.
- Added `prune_memory_entries_for_api`: an explicit, bounded policy engine
  — `max_entries` keeps the most valuable entries (importance, then
  last_accessed, then id), `max_age_days` marks stale entries by parsed
  `last_accessed`/`created_at` (unparseable timestamps are kept), and
  `min_importance` marks lightweight entries. Probe entries are always
  excluded, `dry_run` reports candidates without deleting, deletions are
  capped at 64 per request, and the response accounts for evaluated,
  matched, pruned and failed ids.
- Exposed `POST /api/memory/prune` on the stdlib HTTPServer, FastAPI and
  the Express bridge with stable `INVALID_REQUEST` (400) and
  `MEMORY_PRUNE_FAILED` (500) envelopes plus standard proxy `502/503`.
- Documented the route and the `MemoryPruneRequest`/`MemoryPruneResponse`
  schemas in `contracts/core-api.openapi.json`.
- Added 11 focused tests (journalled delete, probe refusal, unknown/type
  mismatch, read-only refusal, dry runs, each criterion, timestamp
  fail-safety, policy validation, per-request cap) and extended the
  cross-implementation contract test: dry run through the stdlib server,
  invalid-policy rejection through the Express bridge, and an executed
  prune through FastAPI that reduces the authoritative store to the
  expected export count.
- Archived `AUDIT_REPORT_247.md` per the ten-report window rule, registered
  in `manifest.json` with SHA-256 and size.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_memory_retention tests.test_memory_repository` | 17 passed |
| `python tests/run_all.py` | Total: 1258; passed: 1247; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed |
| `git diff --check` | Passed |
| Frontend Vitest `npm test -- --run` | 159 passed |

## Residual Risk

- Retention pruning operates on the bounded export snapshot (256 files), so
  stores beyond that budget are pruned oldest-first per request until the
  cap is met across repeated calls.
- The prune policy is request-scoped: no schedule or background job enforces
  retention automatically; callers decide when to prune.
- Delete keeps the probe lifecycle untouched by design; probe entries still
  require their per-entry cleanup tokens.
