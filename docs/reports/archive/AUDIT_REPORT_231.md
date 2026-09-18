# AUDIT_REPORT_231.md

**Iteration**: #231
**Date**: 2026-08-29
**Status**: Complete

## Scope

This audit fixes a correctness defect in `MemoryStore.consolidate()` and closes the
batch follow-up that AUDIT_REPORT_230 recorded. Consolidation reported `pruned` and
`merged` counts but only ever rewrote the surviving entries. The dropped records kept
their files and their index rows, so the next `load()` returned them again and the
documented cleanup was a no-op.

## Defect Evidence

A direct probe against the pre-fix worktree stored four entries (one expired and
low-importance, two same-title duplicates, one plain survivor), then consolidated:

```
stats: {'merged': 1, 'pruned': 1, 'remaining': 2, 'total': 4}
files before: 4    files after: 4    actually deleted: 0
titles after reload: ['dup', 'dup', 'keeper', 'stale']
```

Two records were reported dropped, zero were removed, and both duplicates plus the
expired entry survived the reload.

## Changes

- Extracted the journalled delete sequence from `_delete_probe_unlocked()` into
  `_publish_entry_deletion_unlocked()`, so probe deletion and consolidation share one
  journal/unlink/index-removal/rollback path instead of duplicating it.
- Added `_delete_entry_unlocked()`: a reusable, in-transaction entry deletion that
  validates the filename against the publishable `<type>_<id>.md` form, rejects
  non-regular targets and reparse points, and re-checks file identity before
  publishing. It returns `False` for unreadable or vanished records so a single bad
  file never aborts a batch, while index faults still propagate.
- Added `_bounded_legacy_records()`, which pairs each parsed entry with the file it
  was actually read from, and made `_load_legacy()` a thin projection of it. A record
  whose frontmatter type disagrees with its filename prefix does not round-trip to
  the same name, so reconstructing the name from the entry alone would target the
  wrong file.
- Made `_consolidate_unlocked()` delete every record whose filename is not in the
  compressed target set, and report the real on-disk count as a new `removed` stat.
  `_truncate()` and `_summarize()` preserve `id`, so filenames are stable and the
  target set is always a subset of the loaded set.
- Registered `TestMemoryStoreConsolidateRemoval` in `tests/run_all.py`, raising the
  canonical aggregate gate from 998 to 1006 cases.

## Crash Consistency

Every deletion and every store inside consolidation is individually journalled by
the Iteration 230 mechanism. A crash mid-batch therefore leaves an applied prefix
whose entry/index pairs are all consistent, and re-running consolidation converges.
A probe that hard-killed the child (`os._exit(9)`) after the second deletion's
journal and unlink but before its index rewrite confirms this:

```
child exit code: 9
journal present after crash: True
index targets after recovery == files after recovery  (orphan index rows: [])
re-consolidate -> files final: 1, titles final: ['keeper']
BATCH CRASH-CONSISTENT AND CONVERGENT: True
```

## Self-Review

- Consolidation deletes before it stores. A merge that drops one duplicate and
  rewrites the survivor therefore cannot leave the dropped file behind.
- `removed` is deliberately not asserted to equal `pruned + merged`. Unreadable
  siblings are skipped, and a record whose declared type disagrees with its filename
  is removed under its old name and republished under the canonical one, so the
  on-disk count is its own fact.
- The new `removed` key is additive. The four existing consolidate tests assert key
  presence, `total` and `remaining` only, so no established contract changed.
- `_delete_entry_unlocked()` reuses the existing validation helpers rather than
  re-implementing them, and refuses anything that is not a publishable entry file,
  including `MEMORY.md` and the journal.
- Deletion runs inside the caller's existing mutation transaction, so the process
  lock is held once and POSIX `flock` is never re-entered.
- A control run that reverted only the removal loop, with the new tests left in
  place, fails 5 of 8 cases and then restores the file byte-identically. The tests
  therefore fail without the fix.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_context_compressor.TestMemoryStoreConsolidateRemoval` | 8 passed |
| control run with the removal loop reverted | 5 of 8 failed; file restored byte-identical |
| `python -m unittest tests.test_context_compressor tests.test_context_compressor_llm tests.test_context_compressor_extended tests.test_context_compressor_extended_v2` | 218 passed |
| `python -m unittest tests.test_main tests.test_main_fastapi tests.test_read_only_role_tools` | 381 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python tests/run_all.py` | Total: 1006; passed: 1000; skipped: 6 |
| `python -m unittest discover -s tests -p "test_*.py"` | 1960 total; 1954 passed; 6 skipped |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed; only existing LF/CRLF conversion notices |

## Residual Risk and Follow-Up

- Consolidation is now convergent but still not atomic as a batch. An interrupted
  run leaves a consistent, partially compressed set that the next run finishes; it
  does not roll the whole batch back. A multi-record journal would be needed for
  all-or-nothing batch semantics.
- `_merge_duplicates()` still selects by `access_count` alone and matches on the
  post-transformation title. Summarization appends a suffix to the title, so a
  summarized record no longer collides with its unsummarized twin. This is
  pre-existing compressor behavior and was deliberately left unchanged.
- Two source files whose entries reconstruct to the same canonical filename still
  collapse to one record, which is the pre-existing id-collision behavior of the
  store rather than something consolidation introduces.
- The final `lstat`/`unlink` window and post-construction root replacement remain
  non-atomic against a non-cooperating same-user process, unchanged from
  Iteration 230.
- Windows and macOS still have no parent-owned OS filesystem or network sandbox
  equivalent to the Linux Landlock and namespace boundaries.
