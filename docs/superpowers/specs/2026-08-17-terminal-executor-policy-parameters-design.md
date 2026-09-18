# Terminal Executor Policy Parameters Design

**Date:** 2026-08-17
**Status:** Approved for implementation

## Context

`TerminalExecutor` exposes `denied_commands` and `default_timeout`, but the
execution path did not enforce either option. A caller could configure a
command in both allow and deny lists and still execute it, while
`execute_shell()` silently used a hard-coded 30-second timeout.

## Decision

- Resolve the command's base executable before the allowlist check.
- Reject an explicitly denied base executable before spawning a process, with
  the same fail-closed dangerous risk classification used for unknown commands.
- Make an omitted `execute_shell()` timeout inherit `self.default_timeout`;
  preserve explicit per-call timeout values.
- Keep the fixed `TerminalWorker` protocol and service defaults unchanged.

## Invariants

- Deny entries always override allow entries.
- A denied command must not spawn a child process or write an execution audit
  entry.
- Explicit `execute_shell(..., timeout=n)` remains unchanged.
- No HTTP, Plugin, or OS sandbox behavior changes in this iteration.

## Verification

Regression tests cover deny-over-allow precedence and propagation of the
executor default timeout to `Popen.communicate()`.
