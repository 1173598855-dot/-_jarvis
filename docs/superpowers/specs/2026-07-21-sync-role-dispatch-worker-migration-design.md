# Synchronous Role Dispatch Worker Migration Design

**Date:** 2026-07-21
**Iteration:** 132
**Status:** Approved for planning

## Context

The role-task lifecycle added in Iterations 130 and 131 can confirm process
termination for timeout and cancellation. The older synchronous role routes
still call `AgentFactory` in the service process, where `Orchestrator` enforces
timeouts with a daemon thread that cannot be safely terminated. This design
migrates those compatibility routes to the process Worker boundary without
changing their request or top-level response shapes.

The migration covers both Python service implementations. Express remains a
transparent Core API proxy and does not gain a second execution path.

## Goals

- Route `/api/roles/dispatch`, `/api/roles/dispatch_by_cap`, and
  `/api/roles/batch_dispatch` through `RoleWorkerSupervisor` in Python
  HTTPServer and FastAPI.
- Preserve the existing synchronous `DispatchResult` and batch response
  shapes.
- Preserve the synchronous routes' one-active-request-per-role `busy`
  behavior while leaving the asynchronous task API's concurrency contract
  unchanged.
- Return a timeout result only after the Worker process has exited.
- Keep FastAPI's event loop responsive while a compatibility request waits.
- Keep role selection, fixed production runner construction, token telemetry,
  output bounds, redaction, and shutdown cleanup in their existing ownership
  layers.
- Remove the child-local daemon-thread timeout from fixed Worker execution so
  the parent Supervisor is the only deadline authority.

## Non-Goals

- Migrating `/api/orchestrator/dispatch` or other generic orchestrator routes.
- Persisting task records or reconciling orphan processes after service
  restart.
- Adding model-driven tool calls or exposing runner configuration through
  HTTP input.
- Cancelling work solely because an HTTP client disconnects. A cancelled
  FastAPI coroutine does not stop its underlying `to_thread` call.
- Changing asynchronous `/api/roles/tasks` request or concurrency semantics.

## Considered Approaches

### Shared synchronous compatibility service (selected)

Add one brain-layer service that selects roles, owns synchronous role leases,
submits fixed Worker requests, waits for terminal records, and maps them back
to `DispatchResult`. Both Python adapters consume the same service. This keeps
policy and terminal mapping out of HTTP code and prevents adapter drift.

### Remove the synchronous routes

Require callers to use `202 Accepted` plus task polling. This is simpler but
breaks the documented API and existing callers, so it is not suitable for a
compatibility migration.

### Implement a bridge independently in each adapter

This minimizes new abstraction but duplicates role selection, terminal
mapping, timeout handling, and error policy. It would recreate the behavior
drift that the shared contract work is intended to remove.

## Architecture

Create `RoleDispatchService` in `src/core/brain/role_dispatch_service.py`.
It consumes a `RoleRegistry` and a `RoleWorkerSupervisor`; it does not create
processes, Ollama clients, or HTTP responses itself.

`AgentFactory` gains a child-only `execute_role_once` primitive that reuses the
existing profile, prompt, tool-authorization metadata, Ollama normalization,
and `DispatchResult` rules but invokes the resolved handler directly in the
Worker process main thread. The fixed production runner uses this primitive
instead of `dispatch_by_role`, so it does not create a nested Orchestrator
daemon thread or a second deadline. Its child-local `OllamaManager` also uses
no HTTP transport deadline; the disposable Worker process is the timeout
boundary. If the parent cannot confirm termination, the existing fail-closed
503 and role lease apply instead of allowing a transport timeout to publish a
competing result. Other OllamaManager instances retain their existing finite
timeouts. The generic and legacy Orchestrator remains unchanged for routes
outside this migration.

`RoleWorkerSupervisor` gains a condition-based `wait(task_id, timeout)` method.
Every record mutation that can unblock a waiter notifies the condition. Waiting
does not create a second deadline or terminate a process; the monitor remains
the sole owner of request deadlines and termination. A bounded caller wait
budget covers the request timeout plus monitor and termination grace. If the
budget expires while the record is still nonterminal, the service reports
termination as unconfirmed and keeps the role lease.

The Supervisor also supports multiple terminal observers. Finalization stores
the terminal record and notifies waiters under the Supervisor lock, then calls
a copied observer list only after every recursive acquisition of that lock has
been released. Existing finalize call sites are refactored to compute their
decision under the lock and publish after leaving it; invoking observers merely
outside `_finalize`'s innermost `with` block is insufficient with an `RLock`.
Observer failures are isolated. The existing token telemetry callback becomes
one observer, and the compatibility service registers another to release
matching role leases only after confirmed termination. The service never holds
its lease lock while submitting or waiting, so the lock order cannot invert.

The compatibility service maintains a lock-protected `role_name -> task_id`
lease map. A second synchronous request for that role receives the existing
`busy` `DispatchResult`, including its own generated request task ID. A lease
is released only after its Worker record is terminal with
`termination_confirmed=true`. If a previous request returned
an infrastructure error while termination remained uncertain, later calls
recheck the record and keep the role blocked until confirmation arrives. A
submit failure that did not establish a Supervisor record/runtime atomically
rolls back its reservation. A missing leased record may release the lease only
because the Supervisor invariant permits pruning after confirmed terminal
publication, observer notification, and runtime cleanup; this invariant is
covered directly by a race regression. These leases apply only to the three
synchronous compatibility methods; the async task API remains unchanged.

## Data Flow

1. The HTTP adapter performs its existing body, string, timeout, role, and
   capability validation.
2. `RoleDispatchService` resolves the requested role. Capability dispatch uses
   the first registry candidate, preserving current priority ordering.
3. The service creates a `WorkerTaskRequest`, then acquires the synchronous
   role lease. HTTP data cannot supply task IDs, runner names,
   commands, environment variables, working directories, or capabilities.
4. The shared `RoleWorkerSupervisor` starts the fixed production runner and
   returns the running record.
5. The service waits for the parent-authoritative terminal record. The child
   executes the resolved role handler directly without an independent timeout;
   only the parent monitor may publish `timeout`.
6. Every terminal record must have `termination_confirmed=true`; otherwise it
   is treated as an unconfirmed infrastructure failure. A successful record is
   then strictly decoded from `record.result["dispatch"]`: it must contain
   exactly the four string fields of `DispatchResult`, and its `role_name` must
   equal the selected role. The outer Worker `task_id` is the public task ID
   returned by the compatibility route. In FastAPI deployments this provides
   one correlation ID across synchronous and task-lifecycle views; the
   standard-library HTTPServer still exposes only the synchronous view. The
   inner orchestrator task ID is not exposed.
7. Token usage remains applied once by the Supervisor terminal callback. The
   compatibility mapping never records usage again.

FastAPI calls the complete submit-and-wait operation with `asyncio.to_thread`.
The standard-library HTTPServer calls it directly. Batch dispatch invokes the
same role/capability methods sequentially, preserving input order and result
count.

Batch compatibility is defined per item because the current public item schema
is intentionally open:

- A mapping with a truthy `role` value uses role dispatch when that value is a
  string and becomes a per-item error otherwise. Only when `role` is absent or
  false does a truthy `capability` select capability dispatch, again requiring
  a string value.
- When both routing fields are absent or empty, the existing behavior is
  preserved by selecting the registry's first, highest-priority role.
- Unknown roles and nonempty capabilities remain `no_role` and
  `no_capability` results at their original positions.
- `prompt` defaults to the current empty string and `timeout` defaults to 300.
  Because `WorkerTaskRequest` intentionally rejects blank prompts and invalid
  timeout values outside the strict integer `1..300` range, these invalid
  items now become stable per-item `error` results rather than raising or
  entering a Worker.
- Non-mapping items and non-string routing or prompt values likewise become
  per-item `error` results. Unknown extra fields remain ignored.

These rules keep the documented valid-input behavior and the top-level
`200 {results, count}` contract while replacing previously accidental 500s
with deterministic positions. They do not tighten the OpenAPI request schema
in this iteration.

## Result And Error Mapping

- `succeeded`: return the decoded inner role result's `role_name`, `status`,
  and `message`, with the outer Worker task ID.
- `timeout`: return a `DispatchResult` with the outer Worker task ID, status
  `timeout`, and stable timeout text only when termination is confirmed.
- `failed`, `crashed`, or `cancelled`: return a `DispatchResult` with the outer
  Worker task ID, status `error`, and a stable redacted message.
- synchronous role lease conflict: return the legacy-compatible `busy` result
  with the newly generated request task ID and stable busy message. The
  rejected request is not added to Worker task history.
- unknown role or capability on either single-dispatch route: retain the
  adapters' existing `404` error codes. Batch items keep positional `no_role`
  or `no_capability` results instead of becoming request-level errors.
- spawn failure: return `503 ROLE_WORKER_UNAVAILABLE` for a single dispatch.
- nonterminal record after the bounded wait: return
  `503 ROLE_TASK_TERMINATION_UNCONFIRMED` and retain the role lease.
- malformed Worker success payload: return
  `503 ROLE_WORKER_INVALID_RESULT`; do not trust or partially expose it.

Batch dispatch remains a `200` response with one result per input item. A
per-item validation, spawn, malformed-result, or unconfirmed-termination
failure becomes a stable `error` `DispatchResult` with a generated request task
ID so an infrastructure failure cannot silently drop earlier or later result
positions. Request-level validation failures remain HTTP errors.

## Lifecycle And Ownership

`AppState` in each Python service composes one shared Supervisor and one
`RoleDispatchService`. Existing asynchronous FastAPI routes use the Supervisor
directly; synchronous routes use the compatibility service. Shutdown first
stops the Supervisor, then closes existing orchestrator, factory, terminal,
and Ollama-owned resources according to the adapter's current lifecycle.
Shutdown remains idempotent, and tests must prove no test-owned Worker remains
alive.

The standard-library service must expose an injectable state factory or
equivalent narrow seam so spawn-safe tests do not mutate unrelated module
globals. No new general command, plugin, environment, or working-directory
input is introduced.

## Contract Changes

The OpenAPI version advances from `1.12.0` to `1.13.0`. The three synchronous
role routes retain their current request and success schemas. Their descriptions
state that execution uses a terminable Worker, while `503` responses explicitly
cover unavailable, invalid-result, and unconfirmed-termination failures in
addition to the existing Express/Core configuration and proxy meanings.

The contract does not claim that generic orchestrator dispatch is terminable,
and documentation continues to list persistent task recovery and model tool
execution as later Phase 11 work.

## Test Strategy

- Unit-test Supervisor waiting for success, timeout, late terminal updates,
  unknown task IDs, and a bounded unconfirmed result.
- Exercise the exact deadline boundary and prove the fixed runner has no child
  Orchestrator or HTTP transport timeout race: a confirmed parent deadline
  always maps to `timeout`, while a completed direct execution maps once to its
  actual result.
- Unit-test compatibility role selection, public task-ID mapping, strict
  success decoding, stable terminal errors, busy leases, lease retention after
  unconfirmed termination, spawn reservation rollback, terminal-observer
  release before pruning, and sequential batch ordering.
- Unit-test every batch compatibility branch: role, capability, missing route,
  unknown route, blank prompt, invalid timeout, non-mapping item, extra fields,
  and a per-item Worker infrastructure failure.
- Hold the compatibility service lease lock from another thread while a Worker
  finalizes and prove Supervisor `get`, `list`, waiter notification, and runtime
  cleanup continue without a lock-order deadlock.
- Verify FastAPI performs compatibility calls outside the event loop and maps
  service failures to stable envelopes.
- Verify Python HTTPServer uses the same service and closes all Workers during
  shutdown.
- Extend the real three-adapter contract harness to prove the same synchronous
  request reaches the fixed Worker runner and returns the existing response
  shape.
- Keep focused Worker/service/API tests, aggregate tests, full discovery,
  compileall, Vitest, Playwright, typecheck, production build, and required
  local integration as the delivery gates.

## Acceptance Criteria

1. Production synchronous role routes in both Python adapters no longer call
   `AgentFactory.dispatch_by_role`, `dispatch_by_capability`, or
   `batch_dispatch` directly.
2. A compatibility request cannot return `status=timeout` until its child
   process is confirmed dead. It may instead return
   `ROLE_TASK_TERMINATION_UNCONFIRMED` as `503`, in which case the synchronous
   role remains blocked.
3. Existing request bodies and success response shapes remain compatible,
   capability selection and batch ordering remain deterministic, invalid batch
   items have stable positional results, and token usage is counted once.
4. FastAPI remains responsive during submit and wait, and both service
   lifecycles clean up all Worker processes.
5. Tests and documentation explicitly retain generic dispatch, persistent
   recovery, and model tools as out-of-scope work.
