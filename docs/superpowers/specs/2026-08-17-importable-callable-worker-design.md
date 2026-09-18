# Importable Callable Worker Design

**Date:** 2026-08-17

## Context

The generic orchestrator currently has two execution paths. The legacy
`register(name, callable)` path runs an arbitrary Python callable in a daemon
thread and can quarantine a timed-out handler, but Python cannot terminate that
thread. Iteration 145 added `register_declared()` for static module-local
runners, yet ordinary top-level callables still have no process-backed option.

The next increment must provide a serializable execution contract without
pretending that closures, lambdas, or bound instances are portable across the
Windows `spawn` boundary.

## Decision

Add an internal `Orchestrator.register_worker(name, handler, capabilities=None)`
path for an importable top-level Python function. Registration derives a
module/function locator from the callable object and verifies that the module
already binds that exact function. The caller never supplies a module path or
string; lambdas, nested functions, bound methods, callable instances, and
`__main__` functions are rejected before the registry changes. The existing
`register()` API remains unchanged for compatibility.

The child process receives only the validated locator and the existing bounded
JSON `AgentTask` projection. It imports the module, resolves the top-level
function, reconstructs an `AgentTask`, and invokes the function. Results are
wrapped in a strict value/`AgentResult` envelope so the parent can preserve the
legacy result shape. The existing `RoleWorkerSupervisor` remains the sole
process lifecycle owner; no HTTP registration or dynamic caller-supplied
execution surface is added.

## Lifecycle Contract

- The parent owns the caller task ID and records the public `AgentResult` once,
  after a confirmed Worker terminal record.
- `SUCCEEDED`, `FAILED`, `CRASHED`, and confirmed `TIMEOUT` map to the existing
  generic result and Agent counters.
- A confirmed `CANCELLED` result releases the Agent to `IDLE`, records one
  `cancelled` result, and does not increment success, error, or timeout counts.
- `Orchestrator.cancel(agent_name, task_id)` is internal and synchronous. It
  returns `True` only when the matching Worker reports confirmed cancellation;
  legacy thread agents return `False`.
- Missing, nonterminal, or unconfirmed records quarantine the Worker and block
  reuse, recovery, removal, and replacement until termination is confirmed.

## Scope and Non-goals

- Preserve all HTTP routes, OpenAPI schemas, Plugin authority, and role Worker
  behavior.
- Do not dynamically import caller-supplied strings, accept commands,
  environments, paths, or capability tokens, or expose registration over HTTP.
- Do not migrate arbitrary closures or bound objects; they remain explicitly
  supported only by the legacy in-process compatibility path.
- Do not add generic task persistence in this increment; the parent retains
  history for the synchronous dispatch call.

## Test Strategy

Use the real Windows-safe `spawn` context with a module-level test fixture:

1. A registered top-level function runs in a child process and returns the
   complete task projection; an `AgentResult` return value preserves its shape.
2. Lambda, nested, bound, `__main__`, and non-function callables are rejected
   before a registry entry or Worker process is created.
3. A delayed function reaches confirmed timeout and remains reusable only after
   the existing confirmation path; an unconfirmed Worker remains quarantined.
4. A background dispatch can be cancelled through `Orchestrator.cancel()`,
   returns `cancelled`, confirms process termination, and creates exactly one
   history record.
5. Existing declared and legacy callable suites remain green.
