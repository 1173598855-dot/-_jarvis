# Discovery Fixture Output Decoding Design

## Context

`_DiscoveryFixtureMixin.run_script()` starts the UTF-8-oriented discovery
runner with `subprocess.run(..., text=True)` but leaves the parent-side decoder
implicit. On Windows, `subprocess` therefore selects the process locale (GBK on
the current host) even when the child writes UTF-8. A reader thread can raise
`UnicodeDecodeError`, leave `CompletedProcess.stdout` unset and still allow the
surrounding test to report success when it does not inspect the lost stream.

GitHub research confirms the boundary is not project-specific: CPython issue
`#105312` records the Windows console/locale code-page mismatch, while pytest
issue `#7623` and PR `#14963` cover undecodable captured subprocess output.

## Goal

Make the discovery runner end-to-end fixture decode deterministically on every
host without changing the production discovery runner or the child process
environment.

## Considered Approaches

1. Set `encoding="utf-8"` and `errors="backslashreplace"` on the fixture's
   existing `subprocess.run()` call. This preserves valid UTF-8 exactly and
   keeps arbitrary mirrored bytes diagnosable as `\xNN` escapes.
2. Capture bytes and add a separate decoder helper. This offers more policy
   flexibility but duplicates the standard library's streaming subprocess
   decoding for one test helper.
3. Decode with the host locale. This retains the defect because the discovery
   runner and its Python test child do not share that locale contract.

Approach 1 is selected because it is explicit, dependency-free and limited to
the faulty boundary. `backslashreplace` is preferred to silent replacement so
the original byte value remains visible in assertion failures.

## Design

- Add an end-to-end fixture containing a non-ASCII test docstring.
- Patch the parent process's default subprocess decoder to ASCII and force the
  child's stdio to UTF-8. Before the fix, `run_script()` must fail to return the
  Unicode diagnostic; after the fix, it must return the exact text.
- Add a fixture that writes one invalid UTF-8 byte. The returned output must
  contain the stable `\xff` escape and the discovery result must still succeed.
- Change only `_DiscoveryFixtureMixin.run_script()` by adding
  `encoding="utf-8"` and `errors="backslashreplace"`.

## Acceptance

- The new locale-conflict regression fails before the helper change for the
  decoding defect, not for fixture setup.
- Both new regressions pass after the helper change on Windows and POSIX.
- Existing discovery-runner tests, aggregate wiring, Ruff and compileall pass.
- Current-state documentation records the root cause, GitHub evidence and
  measured verification without claiming a production behavior change.

## Scope Boundaries

- No dependency, production code, environment default or global encoding
  configuration changes.
- No attempt to reinterpret arbitrary bytes in their originating locale.
- No broad cleanup of other test helpers that use implicit text decoding.
