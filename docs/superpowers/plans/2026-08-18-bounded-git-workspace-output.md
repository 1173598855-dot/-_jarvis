# Bounded GitWorkspace Child-Process Output

**Goal:** Prevent unbounded Git child-process output from entering workspace
snapshot parsing while preserving existing Git contracts.

## Task 1: Add RED regression

- Patch a bounded fake `Popen` process whose stdout crosses a small configured
  budget and assert `GitWorkspaceInspector.snapshot()` rejects it before parsing.

## Task 2: Implement bounded readers

- Add an 8 MiB per-stream budget and concurrent stdout/stderr reader threads.
- Kill once on overflow or timeout, join readers, close pipes, and preserve
  bounded output in non-zero `CalledProcessError` values.
- Keep command order, sanitized environment and successful parsing unchanged.

## Task 3: Verify and document

- Run GitWorkspace-focused tests, aggregate/discovery suites, compileall, Ruff,
  frontend checks, required-services integration, ledger and diff checks.
- Synchronize current-state docs and the rolling Iteration 210 audit report.
