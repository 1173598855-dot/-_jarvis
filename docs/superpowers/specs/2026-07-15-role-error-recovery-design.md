# Role Error Recovery Design

**Iteration:** 127
**Date:** 2026-07-15
**Status:** Approved by autonomous continuation directive

## Goal

Allow a role to accept a later request after a completed handler error without
changing the failed request's result, history, counters, or timeout safety.

## Root Cause

`Orchestrator.dispatch()` calls `_RegisteredAgent.fail()` when a handler raises.
That method increments `errors_count`, clears `current_task`, and leaves the
agent in `AgentStatus.ERROR`. `is_available()` accepts only `IDLE`, so every
later request returns `busy` even though the handler thread has ended. The
existing `reset()` transition is used only inside `dispatch_with_retry()`.

A deterministic reproduction produced `error` followed by `busy` with only one
Ollama call. Resetting the same registered agent between requests produced
`error` followed by `success`, confirming the persistent state as the cause.

## Chosen Approach

Add an explicit recovery boundary to the orchestrator:

1. `_RegisteredAgent.fail(recoverable=...)` records whether an `ERROR` came from
   a completed handler or a timeout whose daemon thread may still be running.
2. `_RegisteredAgent.recover_from_error()` atomically changes only a recoverable
   `ERROR -> IDLE` and returns whether it performed the transition.
3. `Orchestrator.recover_agent(name)` delegates to that transition and returns
   `False` for unknown agents or any non-error state.
4. `AgentFactory.dispatch_by_role()` calls `recover_agent()` only after receiving
   an `AgentResult` whose status is `error`.
5. The original `DispatchResult` remains an error. Recovery only prepares the
   role for a separate future request; it is not a hidden retry.

This keeps state ownership in `Orchestrator` and avoids further access to its
private `_agents` map from `AgentFactory`.

## Alternatives Rejected

- Change `_RegisteredAgent.fail()` to return directly to `IDLE`: this removes
  the observable error state for all orchestrator consumers and changes existing
  semantics globally.
- Reset from `AgentFactory` through `orchestrator._agents`: this fixes the symptom
  but extends private coupling and cannot make the state check atomic.
- Use `dispatch_with_retry()`: it adds retry/backoff behavior that the public role
  API did not request and still treats ordinary handler errors as non-retriable.

## State Semantics

| Current state | `recover_agent()` | Resulting state |
|---|---|---|
| Recoverable `ERROR` | `True` | `IDLE` |
| Nonrecoverable `ERROR` | `False` | `ERROR` |
| `IDLE` | `False` | `IDLE` |
| `BUSY` | `False` | `BUSY` |
| `SHUTDOWN` | `False` | `SHUTDOWN` |
| Missing agent | `False` | Missing |

The transition does not modify `tasks_completed`, `errors_count`, dispatch
statistics, or history. The recoverable marker is internal and does not change
the public `AgentInfo.status` values or OpenAPI schema.

Timeouts call `fail(recoverable=False)` and remain intentionally unrecovered.
`_run_with_timeout()` uses a daemon thread that may still be executing after the
timeout result; returning that agent to `IDLE` could allow overlapping work.
Timeout cancellation or process isolation requires a separate design.

## Data Flow

1. A role handler raises after its worker thread has ended.
2. `Orchestrator.dispatch()` records the error result and sets the agent to
   `ERROR` as today.
3. `AgentFactory` maps the result, then requests `recover_agent(role_name)`.
4. The caller receives the original `error` result.
5. A later request finds the role `IDLE`, executes the handler, and records its
   own result normally.

## Testing

- Agent factory regression: manager responses `[error, success]` yield role
  statuses `[error, success]`, two manager calls, one retained error count, and
  an idle final agent.
- Orchestrator unit tests: recovery succeeds only from `ERROR`, preserves counts,
  and refuses missing, idle, busy, and shutdown agents.
- Existing timeout tests prove no automatic timeout recovery is introduced.
- Focused orchestrator/factory suites, aggregate Python tests, complete discovery,
  syntax checks, frontend gates, and diff checks remain required.

## Delivery

- Record the Phase 3 search and no-dependency decision.
- Add Iteration 127 to the changelog, project analysis, report index, and audit
  report; retain audit reports 118-127.
- Update the next Phase 11 risk to timeout cancellation/process isolation and
  controlled role tool policy.
