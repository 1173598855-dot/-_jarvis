# AUDIT_REPORT_248.md

**Iteration**: #248
**Date**: 2026-09-07
**Status**: Complete

## Scope

This iteration adds real Linux kernel-enforcement evidence for the fixed
`TerminalWorker` production request and cleanup chain. No production protocol,
command, environment, dependency or source file changes.

## Changes

- Staged the trusted source tree with the existing bounded, link-rejecting
  primitive and ran a real outer Terminal driver as UID/GID 12345.
- Preserved production `TerminalWorker.execute()`, request/response handling,
  `_worker_main()`, namespace/Landlock calls, containment and root cleanup.
- Substituted only the opt-in test child's operation body so it can report
  outside/source/loopback/Worker-root access after isolation.
- Added independent filesystem-disabled and network-disabled mutation runs.
- Added the three real modes to the aggregate suite and Ubuntu 22.04 sandbox
  job under `JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT=1`.

## Enforcement Evidence

The full WSL2 run observed baseline access to the outside file, writable staged
source marker and parent listener. Inside the Worker, outside reads and writes,
source-marker writes and loopback access were denied; source reads and the
Worker-root write remained available. The Worker ran in a distinct PID, exited
before `execute()` returned, and its temporary root existed before `close()`
and was reclaimed afterward.

Disabling only the filesystem call made outside and source writes available
while loopback stayed denied. Disabling only the network call made loopback
available while Landlock denials stayed active.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Total: 1158; passed: 1147; skipped: 11 |
| WSL2 opt-in Terminal Worker probe | 3 passed as UID/GID 12345 |
| `python scripts/discover_tests.py --timeout 1800` | Total: 2132; passed: 2120; skipped: 12 |
| Focused Terminal/isolation/aggregate/CI suite | 112 total; 109 passed; 3 skipped |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| Frontend Vitest / Playwright | 151 passed / 7 passed, 1 desktop-conditional skip |
| Frontend typecheck / build | Passed / passed |

## Residual Risk

- The child operation replacement is deliberately test instrumentation. It
  preserves the production isolation and lifecycle path but is not exposed by
  the fixed Terminal protocol.
- Ubuntu 22.04 GitHub Actions remains the independent hosted-runner evidence
  path; this Windows host reports three honest skips.
