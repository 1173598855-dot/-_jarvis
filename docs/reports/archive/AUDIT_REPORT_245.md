# AUDIT_REPORT_245.md

**Iteration**: #245
**Date**: 2026-09-06
**Status**: Complete

## Scope

This iteration closes two modern Linux compatibility gaps in the existing
child-applied Worker boundary and adds real kernel-enforcement evidence. Linux
Workers must remain usable by an unprivileged service account when direct
network namespace creation returns `EPERM`, and newer Landlock kernels must not
be rejected merely because they expose an ABI newer than this code knows.

## Changes

- Retained the direct `CLONE_NEWNET` path and added an `EPERM`-only fallback
  that enters `CLONE_NEWUSER | CLONE_NEWNET`, maps the identity captured before
  entering the user namespace, and fails closed on namespace, mapping, partial
  write, or descriptor-close errors.
- Made Landlock ABI selection forward-compatible: ABI 3 and newer use the
  latest access mask understood by this implementation while diagnostics still
  report the actual kernel ABI.
- Added an opt-in real Linux probe. The same non-root child first proves that
  an outside file and active loopback listener are reachable, then applies the
  production namespace and Landlock primitives and requires outside reads,
  writes, and loopback access to be denied while the staged plugin remains
  readable and the Worker-owned root remains writable.
- Added a dedicated Ubuntu 22.04 `linux-sandbox` CI job and aggregate/static
  coverage guards. Ordinary non-Linux and non-opt-in runs skip the real probe
  explicitly.

## Self-Review

- The user namespace fallback is attempted only for `EPERM`; every other
  direct namespace error keeps its original stable fail-closed behavior.
- UID/GID are captured before the combined `unshare`. A regression test changes
  the reported identity after namespace entry and proves overflow IDs cannot be
  used accidentally; the real WSL2 probe uses UID/GID 12345 when launched by
  root for the same reason.
- Namespace control files are opened write-only with close-on-exec and
  no-follow flags where available. Exact fixed payloads, short writes, open
  failures, and close failures all stop the Worker.
- Newer Landlock ABI versions enable only the ABI 3 rights known to this code;
  unknown rights are neither requested nor silently treated as allowed.
- Invalid ABI values below 1 are rejected before a ruleset is created.
- The real probe uses the shared bounded, link-free Worker staging primitive
  and a parent-owned live listener, avoiding synthetic network assertions.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Total: 1149; passed: 1142; skipped: 7 |
| `python scripts/discover_tests.py --timeout 1800` | 2121 total; 2113 passed; 8 skipped |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `JARVIS_RUN_LINUX_ISOLATION_ENFORCEMENT=1 python3 -m unittest tests.test_linux_worker_isolation_enforcement -v` (Ubuntu 24.04 WSL2, kernel 6.18, UID/GID 12345) | 1 passed; Landlock ABI 7 and real namespace denial verified |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 desktop-conditional skip |

## Residual Risk

- The local real-enforcement result is from Ubuntu 24.04 on WSL2. The dedicated
  Ubuntu 22.04 CI job is the independent native runner path and must complete in
  hosted CI before that environment has equivalent evidence.
- Linux kernels or service policies that disable unprivileged user namespaces
  still fail closed; there is intentionally no direct-spawn fallback.
- The implementation intentionally handles Landlock rights only through ABI 3.
  Newer rights require an explicit policy review before they are requested.
- macOS Seatbelt kernel enforcement remains represented by its dedicated macOS
  CI job rather than this Windows host.
