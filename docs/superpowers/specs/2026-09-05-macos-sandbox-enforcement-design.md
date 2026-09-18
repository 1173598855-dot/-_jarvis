# macOS Seatbelt Enforcement Evidence Design

**Date:** 2026-09-05

**Iteration:** 243

## Goal

Turn the existing macOS Seatbelt contract coverage into an executable,
platform-gated enforcement probe that proves a real `MacOSSandbox` child can
read its staged/runtime inputs, write only to the Worker-owned root, and
cannot read an ungranted path or open a network connection.

## Current boundary

`MacOSSandbox` already owns a private `code/` and `tmp/` tree, builds a
`(deny default)` profile, grants runtime and staged-code reads, grants writes
only below `tmp/`, and launches through `sandbox-exec`. The Windows host can
verify profile construction and fail-closed selection, but cannot prove
macOS kernel enforcement. The existing behavior and public Python interfaces
remain unchanged.

## Design

Add one independent unittest module with a class skipped unless the current
host is macOS and `sandbox-exec` is discoverable. The test creates a small
probe source tree, stages it through `MacOSSandbox.stage()`, and launches the
probe through `MacOSSandbox.spawn()`. The probe reports three fixed outcomes:

1. reading a temporary file outside the sandbox's granted code/runtime/write
   roots is denied;
2. connecting to loopback is denied;
3. creating a file below the supplied `TMPDIR` writable root succeeds.

The probe uses the current interpreter with `-S -u`, a bounded subprocess
timeout, and a minimal environment. It does not modify the repository or use
caller-controlled shell text. On non-macOS hosts the test is an explicit
skip, never a pass, preserving the evidence distinction recorded in the
project reports.

Add a dedicated `macos-sandbox` GitHub Actions job. It checks out the
repository, installs the existing hash-locked Python dependencies, installs
the local project without dependency resolution, and runs the new probe plus
the existing macOS sandbox contract/runtime tests. The job is independent of
Ollama and frontend services so sandbox evidence is deterministic and bounded.

## Failure and evidence rules

- Missing `sandbox-exec`, non-macOS hosts, or unavailable runtime paths produce
  an explicit skip only for the real-enforcement probe; contract tests remain
  available everywhere.
- A macOS host that has `sandbox-exec` but cannot enforce one of the three
  expected outcomes fails the test and the CI job.
- The probe never treats an exception or a non-zero child exit as evidence of
  success.
- No production fallback, permission broadening, or new dependency is added.

## Verification

Windows verification must show the new module is collected and skipped,
while the existing aggregate, full discovery, Ruff, compileall and frontend
gates remain green. A macOS runner must execute the probe with zero skips for
the enforcement test and report all three expected outcomes.
