# AUDIT_REPORT_122.md

**Iteration**: #122
**Date**: 2026-07-13
**Status**: Complete

## Goal

Turn the optional local integration profile into a deterministic required-services gate that can run in CI without a downloaded Ollama model or an external daemon.

## Changes

- Added `scripts/local_ollama_fixture.py`, a repository-owned Ollama-compatible fixture for `/api/version`, `/api/tags`, `/api/ps`, and streaming/non-streaming `/api/chat` responses with native token counters.
- Added `scripts/ci_local_integration.py`, which starts FastAPI/Core, Express, and the fixture on ephemeral loopback ports, invokes the existing profile with `--require-services`, and terminates every child process in reverse order.
- Closed the parent log descriptors before child shutdown so temporary log directories are removable on Windows as well as POSIX hosts.
- Added runner/fixture guard tests, wired the runner into the GitHub Actions Python contract job, and documented the deterministic command.

## Verification

| Command | Result |
|---|---|
| `python scripts/ci_local_integration.py --require-services --timeout 15` | Passed: Express/Core/Ollama fixture profile, 2 SSE frames |
| `python -m unittest tests.test_ci_workflow tests.test_docs_setup tests.test_local_integration_runner` | Passed |
| `python tests/run_all.py` | Passed: 165 tests |
| `python -m unittest discover -s tests -p "test_*.py"` | Passed: 965 tests |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | Passed: 79 tests |
| `cd frontend; npm run test:e2e` | 5 passed; 1 skipped by project condition |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `git diff --check` | Passed |

## Remaining Work

- Real Ollama workstation validation remains an optional complement to the deterministic CI fixture.
- Chat and Runtime production chunks still require low-end-device interaction measurements before further splitting.
- Non-shared orchestrator/role routes remain outside the shared OpenAPI contract because the three service implementations do not expose equivalent endpoints.
