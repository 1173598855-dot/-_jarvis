# AUDIT_REPORT_135.md

**Iteration**: #135
**Date**: 2026-07-28
**Status**: Complete

## Goal

Start Stage D with a versioned public capability record and deterministic,
read-only discovery of repository-local Skills, Plugins, and UI components.

## Delivered Behavior

- Added immutable schema-version-1 capability and snapshot records with strict
  identifiers, repository-relative POSIX paths, explicit unknown metadata, and
  bounded public serialization.
- Added fixed-root discovery for direct Skill, Plugin, and UI component entries.
  Discovery never imports Plugin code and rejects symlinked capability roots.
- Added bounded deterministic tree hashing that ignores generated caches and
  build output while limiting files, individual bytes, and total bytes.
- Kept trusted subroots closed against symlink substitution, isolated direct UI
  file digests from sibling changes, and bounded normalized-ID collisions to a
  stable record plus a snapshot issue.
- Preserved malformed Plugin manifests as explicit invalid, high-risk records;
  a bad entry does not hide healthy siblings or fail the full snapshot.
- Scanned the repository into 22 records: 19 Skills, 2 Plugins, and 1 directly
  exported UI component, with no snapshot-level issues.
- Phase 3 stopped at the local-capability condition: the repository and current
  skills cover D1, so no dependency, download, or external deployment was added.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_capability_registry tests.test_run_all_coverage -v` | Passed: 27 tests |
| `python tests/run_all.py` | Total: 442; passed: 440; skipped: 2 |
| `python -m unittest discover -s tests -p "test_*.py"` | Total: 1297; passed: 1295; skipped: 2 |
| `python -m compileall -q src tests scripts` | Passed |
| `git diff --check` | Passed |

## Scope Boundary

This iteration does not resolve compatibility constraints, accept package
archives, mutate installed capability state, import discovered code, or expose
the registry over HTTP. Those boundaries remain explicit work for Iterations
136-139.
