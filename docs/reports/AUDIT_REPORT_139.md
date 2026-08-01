# AUDIT_REPORT_139.md

**Iteration**: #139
**Date**: 2026-07-31
**Status**: Complete

## Goal

Expose bounded repository-local capability metadata through the existing three
service boundary and make it operationally visible without adding an HTTP
installation or lifecycle mutation surface.

## Delivered Behavior

- Added OpenAPI `1.14.0` schemas and `GET /api/capabilities/registry` with
  strict scalar query bounds, repository-relative public paths, and stable
  invalid or unavailable error envelopes.
- Reused one query parser and response shaper across Python HTTPServer and
  FastAPI, always scanning the fixed repository root and resolving against
  trusted runtime versions.
- Unified the runtime compatibility target with the Plugin SDK, bounded direct
  children and public discovery issues, removed internal match scores from the
  wire shape, and coalesced concurrent scans behind a short snapshot cache.
- Added an Express Core proxy that forwards the original read-only query and
  preserves Core status and error bodies.
- Added strict TypeScript records and a Core-gated polling inventory in the
  Plugins view for kind, lifecycle, provenance, compatibility, health, risk,
  permissions, and relative origin metadata.
- Preserved existing Plugin lifecycle controls while keeping Skill, UI, and
  registry rows read-only; verified desktop and 390px mobile layout through
  Playwright geometry assertions and screenshots.
- Classified issue-only snapshots as degraded even when no capability record
  survives discovery, so a partial or complete scan failure cannot look empty.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_api_contract tests.test_capability_registry tests.test_capability_resolver tests.test_main tests.test_main_fastapi` | Passed: 394 tests |
| `python tests/run_all.py` | Total: 511; passed: 509; skipped: 2 |
| `python -m unittest discover -s tests -p "test_*.py"` | Total: 1382; passed: 1380; skipped: 2 |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | Passed: 135 tests |
| `cd frontend; JARVIS_E2E_PORT=5189; npm run test:e2e` | Passed: 7; skipped: 1 conditional desktop case |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `python scripts/ci_local_integration.py --require-services` | Passed |
| `git diff --check` | Passed |

## Scope Boundary

The endpoint accepts no archive, URL, filesystem root, entrypoint, or lifecycle
mutation. Discovery and rendering do not import or execute capability content,
and installed packages remain disabled until a future isolated runtime grants
explicit authority.
