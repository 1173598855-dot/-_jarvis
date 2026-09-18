# AUDIT_REPORT_233.md

**Iteration**: #233
**Date**: 2026-08-29
**Status**: Complete

## Scope

This audit fixes the compression transforms themselves. `SemanticCompressor._truncate()`
never truncated: it kept the leading 60% and the trailing 40% of the body, which is the
whole body plus a marker. Every "truncation" therefore grew the record, raised its token
count, and reported negative savings. Compounding it, both transforms appended a title
marker unconditionally, so markers stacked without bound and a transformed record stopped
colliding with its untransformed twin, silently disabling the documented duplicate
detection across consolidation rounds.

## Defect Evidence

Five consecutive `consolidate()` calls on one over-budget store, before the fix:

```
round 1: titles=['planning [truncated]'] lens=[1466]
round 2: titles=['planning [truncated] [truncated]'] lens=[1524]
round 3: titles=['planning [truncated] [truncated] [truncated]'] lens=[1582]
round 4: titles=['planning [truncated] [truncated] [truncated] [truncated]'] lens=[1640]
round 5: titles=['planning [truncated] [truncated] [truncated] [truncated] [truncated]'] lens=[1699]
```

The body grew by exactly the 58-character marker each round and the title grew without
bound. A separate probe showed a summarized record no longer deduplicating:

```
merged stat: 0   remaining: 2   titles: ['same', 'same [summary]']
```

## Changes

- Added `_truncated_body()`, which keeps the largest head/tail pair whose token estimate
  fits `max_tokens`. The estimate is non-decreasing in kept length for a fixed body, so
  the largest fitting length is found by bisection over kept characters; a defensive
  halving loop after the bisection keeps the budget authoritative if the estimator is ever
  retuned. A budget too small for the marker alone yields the marker.
- `_truncate()` now produces a body that fits the requested budget, so `token_count`
  falls instead of rising and `tokens_saved` is a real saving.
- Added `_base_title()` and `_marked_title()`. Marking a title strips any existing
  compression markers first, so `[truncated]`, `[summary]` and `[llm-summary]` never
  stack and both transforms became idempotent.
- `SemanticCompressor._merge_duplicates()` keys on the base title, so a transformed
  record still collides with its untransformed twin. A survivor that absorbed a
  differently marked twin drops back to the shared base title, because the merged body is
  no longer purely one record's summary or truncation.
- Applied the same marker discipline to `LLMCompressor._llm_summarize()`,
  `_heuristic_summarize()` and `_merge_duplicates()`. That compressor keeps its
  selecting shape, because nothing routes its output into a disk deletion, but it needs
  the same marker-insensitive matching to deduplicate at all.
- Registered `TestSemanticCompressorBoundedTransforms` in `tests/run_all.py`, raising
  the canonical aggregate gate from 1018 to 1034 cases.

## Verified Behavior

Truncation now fits its budget across ASCII, CJK and mixed bodies, and shrinks:

```
orig_tokens=   1750 budget= 500 kept_chars=  1443 tokens= 500 FITS=True SHRANK=True
orig_tokens=   6133 budget= 300 kept_chars=   429 tokens= 300 FITS=True SHRANK=True
orig_tokens=   2340 budget= 120 kept_chars=   344 tokens= 120 FITS=True SHRANK=True
orig_tokens=  35000 budget= 500 kept_chars=  1443 tokens= 500 FITS=True SHRANK=True
```

Repeated consolidation now reaches a fixed point, and duplicate detection survives a
transform:

```
round 1..5: titles=['planning [truncated]'] lens=[780]   (identical every round)
merged stat: 1   remaining: 1   titles: ['same']
stats: {'kept': 3, 'tokens_saved': 2700}   kept token counts: [500, 500, 500]
```

## Self-Review

- Bisection is over kept characters, not over the estimate, so it terminates in
  O(log n) estimator calls even for a 60,000-character body.
- The 60/40 head/tail split is preserved, so a truncated record still shows both ends of
  the original. A regression test asserts the head and tail survive.
- `_base_title()` only strips markers at the end of the title, so a legitimate title
  containing `[summary]` mid-string is untouched. A regression test pins that.
- Marker stripping loops until stable, so titles that already stacked markers before this
  fix collapse to their base on the next pass rather than staying corrupted.
- `_truncate()` still returns the original object unchanged when the entry already fits,
  so the existing identity assertion holds.
- Absorption in the Iteration 232 fold is unchanged; only the key it matches on and the
  survivor's title changed. The 8,192-character content bound and the refusal branch are
  untouched.
- `min`/`max` on ISO timestamps, the `merged_from` list and the store's journalling all
  stay exactly as Iteration 232 left them.
- Control runs prove each half is load-bearing: reverting only the real truncation fails
  10 of 16 cases, reverting only the marker-insensitive matching fails 1 of 16, and each
  revert restores the file byte-identically (sha256 `abdb98138ff3419f...`).

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_context_compressor.TestSemanticCompressorBoundedTransforms` | 16 passed |
| control run with real truncation reverted | 10 of 16 failed; file restored byte-identical |
| control run with base-title matching reverted | 1 of 16 failed; file restored byte-identical |
| `python -m unittest tests.test_context_compressor tests.test_context_compressor_llm tests.test_context_compressor_extended tests.test_context_compressor_extended_v2` | 254 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python tests/run_all.py` | Total: 1034; passed: 1028; skipped: 6 |
| `python -m unittest discover -s tests -p "test_*.py"` | 1988 total; 1982 passed; 6 skipped |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed; only existing LF/CRLF conversion notices |

## Residual Risk and Follow-Up

- The token estimator remains a heuristic, so "fits the budget" means fits the estimate.
  A real tokenizer would change the kept lengths but not the contract.
- `_summarize()` still keeps at most three sentences chosen by a fixed keyword list, so a
  body whose decisions use none of those words is summarized to its first three sentences.
  Semantic summarization is separate work.
- Merging is still lossless only within the 8,192-character bound; beyond it both records
  are kept, so a store can accumulate same-title duplicates. Bounded summarization of the
  absorbed body is the natural follow-up.
- Refused duplicates are compared only against the first record holding that base title,
  never against each other.
- Consolidation remains convergent rather than atomic as a batch.
- Windows and macOS still have no parent-owned OS filesystem or network sandbox
  equivalent to the Linux Landlock and namespace boundaries.
