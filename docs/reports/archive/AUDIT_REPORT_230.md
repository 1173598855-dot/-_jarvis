# AUDIT_REPORT_230.md

**Iteration**: #230
**Date**: 2026-08-29
**Status**: Complete

## Scope

This audit closes the two-file crash-consistency gap that AUDIT_REPORT_229
recorded as its primary residual risk. A writable `MemoryStore` mutation touches
two files: the entry payload and the derived `MEMORY.md` index. Both writes were
already atomic and parent-directory durable on their own, but a crash between
them could leave one side new and the other old. This iteration adds a durable
intent journal with roll-forward reconciliation so the pair converges on the
next writable open or mutation.

The same iteration consolidates the duplicated directory-fsync primitive onto
the shared `durable_directory` contract and registers the previously unregistered
`test_durable_directory` suite in the canonical aggregate gate.

## Changes

- Added a bounded intent journal at `.auto-memory/.memory-journal`. Each record
  is one 4 KiB-bounded JSON object carrying `schema_version`, `operation`
  (`store` or `delete`) and the exact `<type>_<id>.md` filename the mutation is
  about to publish. It is written, fsynced and parent-flushed through the
  existing `_atomic_write_regular_target()` before the entry file changes, and
  removed only after the index write lands.
- Added `_recover_journal_unlocked()` to `_mutation_transaction()`, so every
  writable construction and every mutation reconciles first. Reconciliation
  restores one invariant: the index holds a row for the journalled filename
  exactly when that entry file exists and parses. The entry file is
  authoritative and the index is derived, so applying the same journal any
  number of times is a no-op.
- Made reconciliation skip the index write when the derived payload already
  matches the current bytes, so a consistent store never rewrites `MEMORY.md`.
- Extracted `_render_index_removal()` so probe deletion and reconciliation share
  one exact link-destination filter instead of duplicating the row scan.
- Added bounded best-effort cleanup of temporaries a crashed atomic write left
  behind. Only names `_atomic_write_regular_target()` can produce are matched: a
  leading dot, a known base (`MEMORY.md`, `.memory-journal` or a valid entry
  filename), a 32-character lowercase hex token and the `.tmp` suffix. The scan
  reuses the existing 8,192-entry budget and runs under the store's process
  lock, so no cooperating instance can own a live temporary while it runs.
- Consolidated `FileRunStateRepository._fsync_directory()` onto
  `core.contracts.durable_directory.fsync_directory`. The repository now only
  translates `OSError` into `RunStateIntegrityError`; platform detection,
  no-follow opening and the unsupported-filesystem errno set live in one place.
- Registered `TestSupportsDirectoryFsync`, `TestFsyncDirectory` and the new
  `TestMemoryStoreJournal` in `tests/run_all.py`, raising the canonical aggregate
  gate from 967 to 998 cases.
- Ignored `.test-*.patch` and `.test-*.py` so scratch artifacts follow the
  documented `.test-*` convention.

## Self-Review

- Recovery cannot recurse: it runs inside `_mutation_transaction()` behind a
  re-entrancy flag and calls `_atomic_write_regular_target()` directly rather than
  the locked `store()` or `_update_index()` helpers. POSIX `flock` is not
  re-entrant across descriptors, so no nested transaction is taken.
- Read-only stores never reconcile and never write. `_mutation_transaction()`
  calls `_require_writable()` first, so the stdlib and FastAPI listing endpoints
  keep their existing bounded read-only snapshot behavior even when a journal
  or a corrupt journal is present.
- Malformed, oversized, non-regular, unknown-schema, unknown-operation,
  duplicate-key and unsafe-filename journals fail closed with `OSError` rather
  than being silently discarded. A journal is only ever produced by an fsynced
  atomic write, so an invalid one indicates tampering or hardware failure.
- A surviving but unparseable journalled entry leaves the index exactly as it
  is. This store only publishes round-tripped v2 payloads, so such a file came
  from legacy content or an external writer and no row can be derived from it.
- The journal filename has no `.md` suffix, so neither `_load_legacy()` nor
  `_load_read_only()` can mistake it for an entry.
- Rollback paths deliberately leave the journal in place when they re-raise, so
  an interrupted mutation is still reconciled later. Success paths clear it.
- Temporary cleanup is best effort by design: a stray temporary never breaks
  the entry/index invariant, and failing the mutation for it would be worse.
- The run-state consolidation preserves the `RunStateIntegrityError` type,
  message text and every existing flush call site; only the duplicated
  primitive was removed.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_context_compressor tests.test_context_compressor_llm` | 141 passed |
| `python -m unittest tests.test_context_compressor.TestMemoryStoreJournal` | 19 passed |
| `python -m unittest tests.test_durable_directory` | 12 total; 10 passed; 2 skipped |
| `python -m unittest tests.test_file_run_state_repository` | 38 total; 35 passed; 3 skipped |
| `python -m unittest tests.test_main` | 263 passed |
| `python -m unittest tests.test_main_fastapi` | 109 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python tests/run_all.py` | Total: 998; passed: 992; skipped: 6 |
| `python -m unittest discover -s tests -p "test_*.py"` | 1952 total; 1946 passed; 6 skipped |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed; only existing LF/CRLF conversion notices |

## Residual Risk and Follow-Up

- Reconciliation converges the entry/index pair, but it is not a general
  multi-record transaction. Exactly one filename is journalled per mutation,
  which is sufficient because `store()` and `delete_probe()` each touch one entry.
  A future batch mutation would need a multi-record journal.
- `consolidate()` still republishes entries one at a time inside a single
  transaction. Each individual publication is now crash-consistent, but an
  interrupted consolidation can still leave the set partially compressed.
- The final `lstat`/`unlink` window, post-construction root replacement and
  temporary-inode hardlinking remain non-atomic against a non-cooperating
  same-user process. The mutation lock and the journal protect cooperating
  instances only.
- v1 Markdown compatibility remains best effort for inherently ambiguous
  legacy records, unchanged from Iteration 229.
- Windows and macOS still have no parent-owned OS filesystem or network
  sandbox equivalent to the Linux Landlock and namespace boundaries.
