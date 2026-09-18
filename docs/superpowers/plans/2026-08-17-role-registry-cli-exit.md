# Role Registry CLI Exit Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Restore the documented `get` and `register` role-registry CLI
success paths without changing registry semantics.

### Task 1: TDD CLI regressions and minimal control-flow fix

- [x] Add real-subprocess regressions for successful `get engineer` and
  `register <json_file>` commands.
- [x] Register the new CLI regression class in `tests/run_all.py`.
- [x] Run both regressions and observe the current unconditional exit code 1
  (RED).
- [x] Restrict `sys.exit(1)` to missing-argument branches only.
- [x] Re-run the focused regressions and role-registry suites (GREEN).

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review CLI exit codes, output shapes, missing-argument behavior,
  registry semantics, and diff scope.
- [x] Update Iteration 176 ledgers and roll the report window to 167-176.
