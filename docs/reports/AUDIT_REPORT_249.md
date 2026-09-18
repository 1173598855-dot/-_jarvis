# AUDIT_REPORT_249.md

**Iteration**: #249
**Date**: 2026-09-09
**Status**: Complete

## Scope

This iteration advances Phase F by making the fixed read-only `memory_search`
role tool useful for traceable recall. The tool remains local, bounded and
read-only; it does not add embedding dependencies, network retrieval or a new
write path.

## Changes

- Tokenized non-empty bounded queries and ranked title, tag and body matches
  deterministically instead of preserving file order after a raw substring
  scan.
- Returned bounded `score`, `parent_id` and up to eight `source_ids` values
  drawn only from explicit memory provenance metadata; non-string, empty and
  overlong identifiers were skipped from the bounded snapshot.
- Centered the 512-character redacted snippet on the first body match when
  possible, avoiding unrelated prefix flooding in long records.
- Kept the existing store budgets, redaction, symlink rejection, schema and
  default-deny Broker behavior unchanged.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_read_only_role_tools tests.test_role_tool_loop tests.test_role_worker -v` | 56 passed |
| `python tests/run_all.py` | Total: 1161; passed: 1150; skipped: 11 |
| `python scripts/discover_tests.py --timeout 1800` | Total: 2135; passed: 2123; skipped: 12 |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `git diff --check` | Passed |
| Frontend Vitest / Playwright | 151 passed / 7 passed, 1 desktop-conditional skip |
| Frontend typecheck / build | Passed / passed |

## Residual Risk

- This is deterministic lexical recall, not semantic vector retrieval; local
  embeddings remain a separate Phase F work package.
- Memory provenance is only as complete as the source metadata written by the
  producer; absence of `source_ids` is reported honestly rather than inferred.
