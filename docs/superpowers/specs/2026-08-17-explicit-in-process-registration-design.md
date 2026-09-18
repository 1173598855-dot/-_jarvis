# Explicit In-Process Orchestrator Registration Design

**Date:** 2026-08-17
**Iteration:** 147
**Status:** Approved for autonomous implementation

## Context

Iteration 145 added the static `register_declared()` Worker path. Iteration
146 added `register_worker()` for stable module-level functions and confirmed
internal cancellation. The original `register(callable)` API still accepts
closures, bound methods, callable instances, and other process-local objects.
That compatibility is intentional, but its name does not make the weaker
thread execution and non-terminable timeout behavior explicit.

The next P1 requirement is to define a migration or deprecation contract for
callables that cannot be replayed across the Windows `spawn` boundary. The
contract must not silently promote or demote execution modes.

## Decision

Add `Orchestrator.register_in_process(name, handler, capabilities=None)` as the
explicit API for process-local handlers. It owns the existing thread-backed
registration behavior without changing dispatch, timeout quarantine,
replacement, recovery, statistics, or history semantics.

Keep `Orchestrator.register()` as a compatibility wrapper with the same
signature and return value. Every call emits a `DeprecationWarning` whose
message identifies both migration choices:

- use `register_worker()` for a stable importable top-level function;
- use `register_in_process()` when process-local execution is intentional.

The wrapper always delegates to `register_in_process()`. It never inspects the
handler to choose a Worker and never falls back from a failed Worker
registration to a thread.

## Production Migration

`AgentFactory.dispatch_by_role()` creates a profile-bound closure and therefore
cannot use `register_worker()`. Change that call site to
`register_in_process()` so production code declares the weaker execution mode
without generating a deprecation warning.

Repository tests and internal fixtures that intentionally exercise thread
behavior should also use `register_in_process()`. Keep one focused compatibility
test on `register()` to prove the warning and unchanged parent-process
execution.

## Compatibility And Scope

- Preserve the `register()` positional and keyword signature and chaining.
- Preserve support for closures, lambdas, bound methods, and callable objects
  through the explicit in-process API.
- Preserve `register_declared()`, `register_worker()`, `cancel()`, public
  `AgentInfo`/`AgentResult`, HTTP routes, and OpenAPI schemas.
- Do not add a global strict flag, automatic callable serialization, cloud
  execution, generic task persistence, or a new HTTP registration surface.
- Do not remove `register()` in this iteration.

## Error And Warning Semantics

The compatibility wrapper emits one standard `DeprecationWarning` per normal
Python warning-filter behavior and then performs the same registration work as
before. Validation, active-agent replacement refusal, and shutdown behavior
remain owned by the explicit implementation. A warning must never cause an
automatic execution-mode change.

## Test Strategy

1. Prove `register_in_process()` accepts a closure, returns the Orchestrator,
   executes in the parent process, and emits no deprecation warning.
2. Prove `register()` emits the documented warning and still executes an
   importable top-level function in the parent process.
3. Migrate existing thread-path tests and the `AgentFactory` production call
   to the explicit API, leaving only the compatibility regression on
   `register()`.
4. Run the four orchestrator suites, AgentFactory suites, aggregate suite,
   full discovery, static checks, frontend gates, and local integration.

## Exit Criteria

- All production Orchestrator handler registrations name their execution mode.
- `register()` remains source-compatible but has an executable deprecation
  contract.
- No callable is implicitly moved between process and thread execution.
- Existing timeout quarantine and Worker termination guarantees remain green.
