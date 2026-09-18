# Terminal Executor Policy Parameters Plan

**Date:** 2026-08-17
**Design:** `docs/superpowers/specs/2026-08-17-terminal-executor-policy-parameters-design.md`

## Task 1: Reproduce the policy gaps

- [x] Add a regression proving a denied command overrides an allowed command.
- [x] Add a regression proving an omitted shell timeout uses the executor
  default.
- [x] Run both tests and record the expected RED failures.

## Task 2: Implement the minimal enforcement

- [x] Reject denied commands before allowlist execution.
- [x] Resolve omitted shell timeout from `default_timeout` while preserving
  explicit timeout values.
- [x] Include the new regression classes in the aggregate test runner.

## Task 3: Review and verify

- [x] Run focused terminal tests and the aggregate Python suite.
- [x] Run full discovery, compileall, Ruff, frontend tests/build, Playwright,
  required-services integration, and diff checks.
- [x] Update Iteration 154 evidence and the rolling audit window.
- [x] Run final guards for plan completion, report count, temporary paths, and
  listeners.
