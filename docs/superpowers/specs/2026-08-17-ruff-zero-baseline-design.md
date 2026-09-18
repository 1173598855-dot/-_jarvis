# Ruff Zero-Baseline Design

**Date:** 2026-08-17
**Iteration:** 149
**Status:** Approved for autonomous implementation

## Context

The repository declares Ruff 0.16.2 and runs `ruff check src/ tests/ scripts/`
as the first CI job, but the current worktree reports 153 E/F/I/W findings:
79 import-order findings, 48 post-bootstrap import findings, 11 unused imports,
7 placeholder-free f-strings, 5 unused locals, and one finding each for lambda
assignment, a repeated dictionary key, and an unused redefinition. This makes
CI fail before the otherwise green Python, frontend, browser, and integration
gates run.

The development guide already classifies full lint cleanup as separately scoped
technical debt. Iteration 149 owns only that cleanup and must preserve all
Iteration 145-148 behavior and the mixed worktree.

## Options Considered

1. **Clear every finding and restore a zero baseline.** Apply Ruff's safe fixes,
   inspect their exact diff, resolve the seven judgment-requiring findings by
   hand, and document only structurally unavoidable E402 cases. This is the
   selected option because it makes the existing CI gate truthful.
2. **Add broad per-file or project ignores.** This is smaller but would hide
   future defects and leave the source unchanged. It is rejected except for
   four explicit bootstrap modules whose imports must follow a trusted path
   setup.
3. **Fix only F-class findings.** This removes potential correctness smells but
   leaves CI red on import ordering and is therefore incomplete.

## Decision

Run `python -m ruff check src tests scripts --fix` without unsafe fixes. Ruff may
only reorder imports, remove provably unused imports or redefinitions, and
remove redundant `f` prefixes. Inspect all resulting files and retain every
existing behavior, test fixture, public symbol, and user change.

Resolve the seven unsafe-fix candidates explicitly:

- remove the unused temporary-directory target/path assignment and three
  unused process return targets while preserving process registration and
  cleanup in `ci_local_integration.py`;
- remove the unused timing assignment in `terminal_executor.py`;
- replace the assigned test clock lambda in `test_role_tool_loop.py` with a
  local function;
- remove the earlier repeated `UP` key in `ruff_check.py` after confirming the
  later mapping is the intended value.

## E402 Boundary

Four modules intentionally execute path bootstrap code before project imports:

- `src/runtime/plugin_worker.py` must make the repository `src/` root
  importable when launched as a standalone Worker entrypoint;
- `tests/run_all.py` imports the canonical aggregate suite only after adding
  both repository and test roots;
- `tests/test_plugin_installation.py` and `tests/test_run_all_coverage.py`
  bootstrap direct-script and aggregate-runner imports.

Add a file-level `# ruff: noqa: E402` to these files with a short adjacent
reason. Do not add a global E402 ignore or suppress any other file.

## Compatibility And Scope

- No API, schema, dependency, runtime policy, tool grant, Worker protocol,
  persistence format, frontend behavior, or test count changes.
- Do not run unsafe automatic fixes.
- Do not format unrelated code beyond Ruff's safe import changes.
- Do not stage, commit, reset, clean, or revert the mixed worktree.
- Keep CI's existing Ruff command unchanged so future findings fail the gate.

## Verification

1. Capture the 153-finding RED baseline and exact rule/file distribution.
2. Run safe fixes, inspect every changed file, and run Ruff again.
3. Apply the explicit seven fixes and four bootstrap suppressions.
4. Require `python -m ruff check src tests scripts` to exit zero.
5. Run aggregate and discovery suites, compileall, frontend Vitest, Playwright,
   typecheck, build, deterministic local integration, and `git diff --check`.
6. Update Iteration 149 evidence and the rolling report window from fresh
   results.

## Exit Criteria

- The exact CI Ruff command reports `All checks passed!` with no broad ignore.
- The four E402 suppressions are individually justified bootstrap boundaries.
- All behavior and integration gates remain green.
- The final diff contains only mechanical lint cleanup, explicit local fixes,
  and Iteration 149 evidence.
