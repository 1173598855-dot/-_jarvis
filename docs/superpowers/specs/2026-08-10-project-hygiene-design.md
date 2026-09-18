# Project Hygiene and Report Canonicalization Design

**Date:** 2026-08-10  
**Status:** Approved for planning

## Goal

Reduce repository clutter without changing runtime behavior. Remove reproducible local artifacts and retire stale duplicate reports so that `docs/reports/` remains the only authoritative report location.

## Scope

The cleanup removes only reproducible, ignored artifacts that currently exist:

- `.test-perf/`
- `.test-pip-download/`
- `.test-runtime/`
- `.test-python-discovery.txt`
- `frontend/debug.log`
- `frontend/dist/`
- Python `__pycache__/` directories under project source, tests, scripts, and first-party plugins

The documentation cleanup removes these tracked, stale root-level snapshots:

- `PROJECT_ANALYSIS.md`
- `GITHUB_LEARNING_REPORT.md`

Their maintained counterparts remain:

- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/README.md`

## Explicit Exclusions

The cleanup must preserve local dependencies, user state, and tool configuration:

- `venv/` and `frontend/node_modules/`
- `.auto-memory/`
- `.agents/`, `.compound-engineering/`, and machine-local configuration
- `.superpowers/` and `.worktrees/`
- capability stores, runtime state, or any untracked path not explicitly listed in scope

No application code, API contract, dependency, architecture, or runtime behavior changes are included.

## Documentation Rules

`docs/reports/README.md` remains the report navigation entry. `AGENTS.md`, `README.md`, the development guide, protocol, tests, and iteration ledger already reference the canonical `docs/reports/` paths. Before removing the root snapshots, the implementation must re-run a repository-wide reference scan and stop if an active reference depends on either root path.

Git history provides recovery for the removed tracked snapshots, so no archive directory or duplicate copy will be created.

## Safe Deletion Procedure

1. Reconfirm a clean tracked worktree and resolve every cleanup target to the repository root.
2. Verify that each ignored target matches an existing `.gitignore` rule.
3. Delete only the explicit ignored targets listed in this design.
4. Remove the two tracked root-level report snapshots.
5. Confirm that preserved local-state and dependency paths still exist when they existed before cleanup.

## Validation

Validation is documentation- and repository-focused because runtime code is unchanged:

- repository-wide scan finds no active references to the removed root reports;
- `tests/test_readme.py`, `tests/test_docs_setup.py`, and `tests/test_iteration_ledger.py` pass;
- Markdown navigation targets referenced by the report index exist;
- `git diff --check` passes;
- `git status --short --branch` shows only the intended tracked report deletions;
- explicit ignored cleanup targets no longer exist;
- preserved local dependency, memory, and tool-state paths are untouched.

## Rollback

The two tracked reports can be restored from the cleanup commit's parent. Ignored artifacts are intentionally reproducible through tests, builds, or runtime execution and are not backed up.
