# Role Registry Snapshot Ownership Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Prevent callers from mutating RoleRegistry state through mutable
profile inputs and snapshots.

### Task 1: TDD ownership regression and minimal copy boundary

- [x] Add a registered regression that mutates the original profile, a `get()`
  result, nested metadata, and a `list_roles()` result, then asserts registry
  state is unchanged.
- [x] Run the regression and observe caller mutations leak into registry state
  (RED).
- [x] Deep-copy accepted profiles in `register()` and parentless profiles at
  the resolution boundary.
- [x] Re-run the regression and all role registry suites (GREEN).

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review copy scope, inheritance merge behavior, nested metadata,
  thread ownership, and diff scope.
- [x] Update Iteration 177 ledgers and roll the report window to 168-177.
