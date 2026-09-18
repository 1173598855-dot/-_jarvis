# TerminalExecutor Shell Parse Failure Design

**Date:** 2026-08-17
**Iteration:** 175

## Problem

`TerminalExecutor.execute_shell()` calls `shlex.split()` directly. An
unmatched quote or non-string input raises `ValueError`/`TypeError` through the
direct executor API, while the fixed `TerminalWorker` path already turns shell
parse failures into a bounded failed result.

## Required Behavior

- Malformed or non-string shell input returns a failed `TerminalResult`.
- No child process starts and no successful execution/audit record is created.
- The stable command ID, dangerous risk classification, and parser error text
  remain available to callers.
- Empty shell input, valid shell input, policy checks, timeout behavior, and
  public HTTP contracts remain unchanged.

## Design

Wrap only `shlex.split()` in a `TypeError`/`ValueError` boundary and return the
same zero-duration failure shape used for an empty command, with the exception
text as `stderr`. Leave process launch and `execute()` behavior untouched.

## Verification

- Add a registered unmatched-quote regression.
- Confirm the old implementation raises `ValueError` (RED), then require the
  bounded failed result (GREEN).
- Re-run terminal, aggregate, discovery, warning, frontend, integration,
  compile, lint, and repository consistency gates.

## Scope Boundary

This does not expand shell command allowlists, rewrite shell parsing, or change
the process-isolated TerminalWorker protocol.
