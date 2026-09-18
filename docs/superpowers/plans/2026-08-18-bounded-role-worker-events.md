# Bounded Role Worker Events Plan

**Goal:** Bound parent-side Worker event transport before JSON decoding while
preserving valid custom output budgets and lifecycle behavior.

1. Add RED tests for the exact `recv_bytes` limit and sentinel overflow.
2. Add the bounded event overhead constant and dynamic `limit + 1` receive
   path in `RoleWorkerSupervisor._receive_event()`.
3. Run RoleWorker, aggregate, and full discovery suites plus Ruff, compileall,
   integration, and diff checks.
4. Record the self-review and evidence in Iteration 198 documentation.
