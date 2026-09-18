# Aggregate Performance Temporary Ownership Design

**Date:** 2026-08-17
**Iteration:** 151
**Status:** Approved for autonomous implementation

## Context

`TestPerformance.test_store_speed` in `tests/run_all.py` uses the fixed
repository-relative directory `.test-perf`. It deletes old contents before
the benchmark but never removes new contents afterward, so every aggregate
run leaves eleven ignored MemoryStore files in the worktree. This contradicts
the development guide's completion rule that temporary directories and side
effects are cleaned.

## Options Considered

1. **Own a `TemporaryDirectory` inside the benchmark.** Keep the real
   MemoryStore writes and timing assertion, but give every invocation a unique
   `.test-perf-` OS temporary directory that is removed on normal return or an
   assertion/exception. This is selected.
2. **Add `tearDown` for the fixed `.test-perf` path.** This would clean ordinary
   unittest execution but retains cross-session collisions and broad recursive
   deletion of a shared relative path.
3. **Mock MemoryStore writes.** This avoids files but stops measuring the real
   store path, defeating the performance test.

## Decision

Import `tempfile` in the aggregate runner and wrap the complete store benchmark
in `tempfile.TemporaryDirectory(prefix=".test-perf-")`. Pass that absolute
owned directory to `MemoryStore`; remove the inline `shutil.rmtree`, manual
mkdir, and fixed repository-relative target. The context must include the
timing assertion so cleanup also occurs if the assertion fails.

Add a regression test that runs the real `TestPerformance.test_store_speed`
from an isolated working directory, verifies the unittest result succeeds,
and asserts that the old `.test-perf` path was not created. The outer test
owns and restores the process working directory in `finally`.

## Scope Boundary

- Do not change MemoryStore, runtime code, benchmark workload, or the 500 ms
  threshold.
- Do not delete unknown repository paths or add another cleanup utility.
- Do not stage, commit, reset, clean, or revert the mixed worktree.
- Keep the temporary prefix `.test-perf-` for diagnostic ownership.

## Verification

1. Run the new regression against the current fixed-path benchmark and observe
   failure because `.test-perf` remains.
2. Implement the owned temporary directory and require the regression plus
   `TestPerformance` to pass.
3. Run aggregate and discovery suites, compileall, Ruff, frontend gates, local
   integration, and `git diff --check`.
4. Confirm no `.test-perf` or `.test-perf-*` remains under the repository root.

## Exit Criteria

- Repeated aggregate performance runs leave no repository `.test-perf` path.
- Real MemoryStore writes and the existing performance threshold remain under
  test.
- Cleanup occurs through context ownership on success and exceptions.
- All project gates pass and Iteration 151 evidence is current.
