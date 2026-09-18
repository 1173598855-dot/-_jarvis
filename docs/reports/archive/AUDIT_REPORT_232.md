# AUDIT_REPORT_232.md

**Iteration**: #232
**Date**: 2026-08-29
**Status**: Complete

## Scope

This audit closes the data-loss defect that AUDIT_REPORT_231 recorded as a residual
risk. `SemanticCompressor._merge_duplicates()` is documented as merging duplicate
memories, but it only ever selected the record with the higher `access_count` and
discarded the other one whole. That drop was invisible while consolidation left
non-surviving files on disk. Iteration 231 made consolidation delete them, so the
same in-memory selection became permanent loss of the duplicate's body.

## Defect Evidence

A probe stored two same-title records with distinct bodies, consolidated, and
reloaded from disk:

```
stats {'total': 2, 'merged': 1, 'pruned': 0, 'compressed': 0, 'remaining': 1, 'removed': 1}
loaded_after [('355ccb03d36e', 'same-title', 'AAA unique content of A')]
CONTENT LOST: ['BBB unique content of B']
```

The merge was reported, the file was deleted, and the second body existed nowhere
afterwards.

## Changes

- Rewrote `SemanticCompressor._merge_duplicates()` as a survivor-absorbs-duplicate
  fold. The higher-`access_count` record keeps its identity, so the surviving
  filename and the previous selection rule are unchanged, but it now carries the
  other record's body.
- Added `_absorb_duplicate()`, which appends only content the survivor does not
  already contain, unions tags in first-seen order, lifts `access_count`,
  `importance` and `last_accessed` to the maximum, lowers `created_at` to the
  minimum, recomputes `token_count`, and records absorbed ids in
  `metadata["merged_from"]`.
- Bounded the merge: absorbing is refused when the combined body would exceed
  `_MEMORY_MERGE_CONTENT_MAX_CHARS` (8,192). A refused merge keeps both records, so
  the bound never degrades into silent loss. Recorded ids are capped at
  `_MEMORY_MERGE_SOURCE_IDS_MAX` (64).
- Added `_merged_source_ids()`, which tolerates an externally written
  `merged_from` of the wrong type or with non-string members instead of raising.
- Reordered `_consolidate_unlocked()` to store survivors before deleting
  non-survivors. This is required, not cosmetic: a merged survivor now carries the
  absorbed body, so publishing the deletion first would open a window where the only
  copy of that body is gone and its replacement is not yet durable.
- Registered `TestMemoryStoreLosslessMerge` in `tests/run_all.py`, raising the
  canonical aggregate gate from 1006 to 1018 cases.

## Durability and Convergence

Stores and deletions remain individually journalled by the Iteration 230 mechanism,
so each step is still crash-consistent on its own. Storing first makes any applied
prefix a superset of the final state rather than a subset, which is what makes the
absorbed body safe:

- Crash during the store phase: every non-survivor file is still present and some
  survivors are already merged. The next `load()` returns a superset, and because
  absorption skips content the survivor already contains, re-running consolidation is
  idempotent rather than accumulative.
- Crash during the delete phase: every survivor is durable, so the absorbed body is
  already safe. The next run removes the remaining non-survivors.

A probe that hard-killed the child (`os._exit(9)`) at the start of the delete phase
confirms both bodies survive and the re-run converges:

```
child exit: 9
files after crash: ['MEMORY.md', 'project_dbe4bfb17edb.md', 'project_e8cd04a2fcb8.md']
A SURVIVED: True    B SURVIVED: True
re-consolidate merged/removed: 1 1
final count: 1      FINAL LOSSLESS: True
```

Idempotence and the bounded refusal were probed separately:

```
stats1 merged/removed 1 1      stats2 merged/removed 0 0
BOTH BODIES PRESENT: True      IDEMPOTENT: True      separator count: 1

over-budget: {'total': 2, 'merged': 0, 'removed': 0, 'remaining': 2}
titles: ['big', 'big']   lengths: [6000, 6000]   REFUSED AND BOTH KEPT: True
```

## Self-Review

- The absorbed body is appended with a single fixed `_MEMORY_MERGE_SEPARATOR`
  marker, so a merged record stays a plain readable entry and round-trips through the
  existing v2 serializer without a schema change.
- Absorption is a substring check, not a hash, so a survivor re-merged against a
  record whose body it already contains adds nothing. This is what keeps repeated
  consolidation stable; the test asserts a separator count of exactly one.
- The 8,192-character bound is far below the existing 8 MiB entry budget, so a merged
  payload can never be the reason a store fails. Refusing the merge is the
  conservative branch: it keeps two records rather than losing one body.
- `metadata["merged_from"]` is a list of strings, which the existing
  `_validate_json_value()` contract already accepts. `probe_cleanup_token` and any
  other survivor metadata is copied unchanged.
- `access_count` is lifted with `max`, not summed. Summing would cross the
  `_is_expired()` threshold of 5 and silently change pruning behavior, which is
  outside this defect.
- Ties keep the first-seen record, matching the previous strict `>` comparison.
- `LLMCompressor._merge_duplicates()` has the same selection shape but is
  deliberately unchanged: nothing routes its result into a disk deletion.
  `AdaptiveContextCompressor._semantic_compress()` builds throwaway in-memory
  entries and returns a string, so no stored file depends on it.
- The two existing merge tests assert only that duplicates collapse to one title, and
  the Iteration 231 removal test asserts file and index cleanup. Both still hold.
- Control runs prove the tests fail without each half of the fix: reverting only the
  lossless merge fails 10 of 12 cases, reverting only the store-before-delete
  ordering fails 2 of 12, and each revert restores the file byte-identically
  (sha256 prefix `89cb1f19d1e1a763`).

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_context_compressor.TestMemoryStoreLosslessMerge` | 12 passed |
| control run with the lossless merge reverted | 10 of 12 failed; file restored byte-identical |
| control run with the store-before-delete ordering reverted | 2 of 12 failed; file restored byte-identical |
| `python -m unittest tests.test_context_compressor tests.test_context_compressor_llm tests.test_context_compressor_extended tests.test_context_compressor_extended_v2` | 238 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python tests/run_all.py` | Total: 1018; passed: 1012; skipped: 6 |
| `python -m unittest discover -s tests -p "test_*.py"` | 1972 total; 1966 passed; 6 skipped |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed; only existing LF/CRLF conversion notices |

## Residual Risk and Follow-Up

- Merging is lossless within the 8,192-character bound. Beyond it both records are
  kept, so a store can accumulate same-title duplicates that consolidation will never
  fold. Bounded summarization of the absorbed body, rather than refusal, is the
  natural follow-up.
- Refused duplicates are compared only against the first record holding that title,
  never against each other. Three same-title records where the first is already near
  the bound therefore keep the second and third separate even if those two would fit
  together. This leaves a possible merge unrealized; it never loses a body.
- `_merge_duplicates()` still matches on the post-transformation title, so a
  summarized or truncated record no longer collides with its untransformed twin.
  Unchanged pre-existing compressor behavior.
- Consolidation remains convergent rather than atomic as a batch. An interrupted run
  now leaves a superset instead of a subset, which is strictly safer, but there is
  still no rollback. All-or-nothing batch semantics would need a multi-record journal.
- `LLMCompressor._merge_duplicates()` keeps the lossy selection. It is safe today
  only because its output never drives a deletion; routing it into `MemoryStore`
  would require the same fix.
- The final `lstat`/`unlink` window and post-construction root replacement remain
  non-atomic against a non-cooperating same-user process, unchanged from
  Iteration 230.
- Windows and macOS still have no parent-owned OS filesystem or network sandbox
  equivalent to the Linux Landlock and namespace boundaries.
