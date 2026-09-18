# Plugin Worker Process-Tree Containment Implementation Plan

**Goal:** Make Plugin Worker generation cleanup own the complete process tree
instead of only the direct child process.

## Task 1: RED Regressions

- Add platform-neutral containment tests for launch flags, POSIX group
  termination, Windows Job lifecycle calls, and failure propagation.
- Add Plugin runtime coverage proving real launches request containment and
  startup attachment failure reaps the direct process.
- Run the new tests and confirm failures arise because containment does not yet
  exist.

## Task 2: Containment Adapter

- Add `src/core/kernel/process_containment.py` using only the standard library.
- Implement POSIX new-session/process-group ownership.
- Implement Windows kill-on-close Job Object setup, assignment, termination,
  and handle release with bounded stable errors.
- Run focused adapter tests to GREEN and targeted Ruff.

## Task 3: Plugin Runtime Integration

- Launch real Plugin Workers with platform containment flags.
- Attach before reader startup and handshake acceptance.
- Route graceful/forced termination through the tree boundary.
- Retain containment ownership until process and readers are confirmed stopped.
- Run all Plugin runtime, Broker, SDK, installation, entrypoint, and protocol
  tests.

## Task 4: Delivery Evidence

- Perform an independent diff and lifecycle self-review.
- Run aggregate/discovery, compileall, Ruff, frontend, integration, ledger, and
  whitespace checks.
- Update Iteration 180 records and roll the audit window from 170-179 to
  171-180 without altering unrelated worktree changes.
