# Generic Orchestrator Timeout Quarantine Design

**Date:** 2026-08-11

## Context

`Orchestrator._run_with_timeout()` executes arbitrary registered handlers in a
daemon thread. When `thread.join(timeout)` expires, the caller receives an
`AgentResult(status="timeout")`, but Python cannot terminate that handler
thread. The pre-change state machine immediately moved the agent to ordinary
`ERROR`: `unregister()` accepted that state, and `dispatch_with_retry()` reset
it before retrying. A timed-out handler could therefore continue to run while
the same logical agent was removed or invoked again.

The failure is observable without an HTTP adapter: a handler blocked on an
event times out, and `unregister()` returns `True` before that event is
released. The shared HTTP request/response contract is already aligned across
the Python HTTPServer, FastAPI, and Express bridge, so this increment must not
change endpoint shapes, request validation, or result schemas.

## Options Considered

1. Migrate generic dispatch directly to the existing process Worker runtime.
   This would provide hard termination, but arbitrary registered Python
   handlers and their in-memory dependencies have no serializable execution
   contract. Defining parent-side registration, result/history ownership,
   cancellation, and compatibility is a separate P1 work package.
2. Remove or reject the generic dispatch route. This prevents concurrent late
   execution but breaks the documented compatibility API without providing a
   replacement.
3. Add an in-process timeout quarantine around the existing runtime. Preserve
   the route and result contract, retain the daemon-thread limitation, and
   prevent reuse or removal until the background handler has actually exited.

Option 3 is selected. It is the smallest independently testable safety
improvement and establishes a lifecycle boundary that the later Worker
migration can replace without changing the public dispatch shape.

## Design

### Internal Lifecycle

`_run_with_timeout()` will raise a private `_AgentExecutionTimeout` only when
its own join deadline expires. That exception carries the still-live thread.
A handler that itself raises `TimeoutError` remains distinguishable: it is a
completed timeout failure, remains non-recoverable through `recover_agent()`,
and still uses the existing `dispatch_with_retry()` reset behavior.

`_RegisteredAgent` will track at most one pending timed-out thread. While that
thread is alive, the agent remains internally quarantined:

- `dispatch()` returns the existing `busy` result and does not invoke the
  handler again;
- `unregister()` returns `False`;
- `register()` leaves the existing registration in place instead of replacing
  the active logical agent;
- `recover_agent()` and `dispatch_with_retry()` cannot reset the state;
- the timeout result is recorded once, and a late handler result is not added
  to history or allowed to overwrite it.

The registry reservation begins when an Agent becomes `BUSY`, not only after a
join deadline is observed. This prevents a same-name replacement from detaching
the wrapper during the transition from an active handler to timeout quarantine.

Every state observation that needs availability (`is_available`,
`can_unregister`, and `info`) reaps a pending thread only after
`thread.is_alive()` is false. Reaping clears the task reference and returns the
agent to `IDLE`; it does not manufacture a success result. This is natural
completion confirmation, not forced cancellation.

Assignment becomes an atomic `try_assign(task)` operation under the existing
agent lock. A separate registry lock keeps lookup plus assignment, registration,
unregistration, retry lookup, and shutdown membership decisions in one
consistent order, so an otherwise-idle agent cannot be deleted or replaced
between validation and assignment. Normal completion and completed handler
exceptions retain their prior states and counters; shutdown remains terminal
when a late handler exits.

### Retry Behavior

`dispatch_with_retry()` continues to retry completed handler-raised timeout
failures through its existing reset path, without changing the public
`recover_agent()` contract. For `_AgentExecutionTimeout`, it detects the
pending execution and returns the original `timeout` result without resetting
or starting a parallel retry. Once the original thread exits, a subsequent new
dispatch is allowed.

### Scope and Non-Goals

- No public API, OpenAPI schema, adapter route, request body, timeout range, or
  response field changes.
- No attempt is made to kill Python threads, serialize arbitrary handlers, or
  claim OS/process isolation.
- This does not replace the planned generic Worker compatibility and lifecycle
  contract; it constrains the legacy in-process path until that work exists.

## Test Strategy

Add deterministic `threading.Event` tests to the orchestrator lifecycle suite:

1. A blocked handler times out, cannot be unregistered, re-registered, or
   re-dispatched while the event is withheld, and becomes dispatchable only
   after it exits.
2. A controlled concurrent unregister/dispatch interleaving cannot start a
   handler after unregister has entered its protected decision.
3. `dispatch_with_retry()` does not start another handler while a prior
   execution is still unconfirmed, and late exit cannot reopen shutdown.
4. A handler-raised `TimeoutError` remains non-recoverable through
   `recover_agent()` while `dispatch_with_retry()` still retries it, proving the
   private join-timeout distinction without changing the public recovery
   contract.

Run the focused orchestrator tests during red/green, then the aggregate and
complete discovery suites plus the repository's syntax, frontend, integration,
and diff checks before recording Iteration 144 evidence.
