# AppState Test Resource Ownership Design

**Date:** 2026-08-17
**Iteration:** 153
**Status:** Approved for autonomous implementation

## Context

The complete Python discovery passes but emits repeated
`ResourceWarning: Implicitly cleaning up <TemporaryDirectory
'...jarvis-terminal-worker-*'>` messages. Isolated warning-enabled runs show
that `tests.test_main_extended` and `tests.test_main_fastapi_extended` reproduce
the warnings, while `tests.test_terminal_worker` does not.

Both legacy `TestAppState` classes construct real default `AppState` instances.
Those states own a `TerminalWorker`, role-task supervisor, orchestrator, agent
factory, Plugin manager, and event bus. Ten of the twelve tests never invoke a
cleanup; the other two close only `state.terminal`. Because AppState resources
form callback cycles, garbage collection can finalize the TemporaryDirectory
before the worker's best-effort destructor, producing nondeterministic warnings.
Current lifecycle tests instead call the idempotent `AppState.shutdown()` in a
`finally` block.

## Options Considered

1. **Register full cleanup in each legacy TestAppState class.** Create one real
   default state per test in `setUp`, register `state.shutdown` with
   `addCleanup`, and reuse it in the assertions. This is selected because it
   makes ownership explicit even when setup or assertions fail.
2. **Inject a mocked terminal into every test.** This would avoid temporary
   directories but stop the classes from testing default state composition and
   leave the other owned resources without explicit cleanup.
3. **Change production finalizers or filter ResourceWarning.** Production
   already exposes and uses deterministic `shutdown()` plus an idempotent
   best-effort destructor. Strengthening finalization or suppressing warnings
   would mask the test's missing owner rather than fix it.

## Decision

In each legacy TestAppState class:

- add `setUp()` that constructs the existing real `AppState`;
- immediately call `self.addCleanup(self.state.shutdown)`;
- replace per-method local construction with `self.state`;
- remove terminal-only cleanup so the complete lifecycle is exercised exactly
  once through the idempotent application shutdown contract.

The FastAPI class gives its state an owned `.test-fastapi-app-state-`
`TemporaryDirectory`. Cleanup registration order is directory first and state
second, so unittest's LIFO cleanup shuts down and persists the isolated state
before removing its directory; shared `.auto-memory` is not touched.

Add a behavioral regression in `tests/test_run_all_coverage.py` that runs each
legacy AppState test class in a fresh Python subprocess with ResourceWarning enabled. The
subprocess must exit successfully and stderr must contain neither
`jarvis-terminal-worker-` nor `Implicitly cleaning up`. A subprocess is used so
the assertion covers GC and atexit ordering rather than only an in-process
warning filter.

## Scope Boundary

- Do not change production AppState, TerminalWorker, TemporaryDirectory, atexit,
  Worker operations, API behavior, or cleanup ordering.
- Do not replace default resources with mocks in the state-composition tests.
- Do not suppress warnings globally or locally.
- Do not stage, commit, reset, clean, or revert the mixed worktree.

## Verification

1. Add the subprocess guard and observe both legacy classes emit the warning.
2. Register full AppState cleanup in both classes and require the guard plus
   both legacy modules to pass without warning text.
3. Run aggregate/discovery, compileall, Ruff, frontend gates, deterministic
   local integration, and final scratch/process checks.

## Exit Criteria

- Both legacy AppState test modules deterministically shut down every local
  application state.
- Warning-enabled class subprocess runs contain no implicit TerminalWorker temporary
  cleanup.
- Full discovery contains no `jarvis-terminal-worker-*` ResourceWarning.
- Production code and lifecycle behavior are unchanged.
- All project gates pass with fresh Iteration 153 evidence.
