# Role Worker Lifecycle Design

**Date:** 2026-07-19
**Stage:** Phase B, first executable slice
**Status:** Approved by the repository Phase B direction and the existing OpenAPI 1.12 contract tests

## Problem

The synchronous role routes still execute registered handlers through daemon threads. A timed-out thread cannot be safely cancelled, so the orchestrator correctly leaves that role nonrecoverable. Exposing cancellation on top of that path would be dishonest: a response could say `cancelled` while work continued in the service process.

Phase B therefore starts with a separate asynchronous role-task path whose work is owned by a child process. The parent service remains the sole authority for task state and reports `timeout` or `cancelled` only after the child is confirmed dead.

## Goals

- Define a versioned worker request, event, task record, cancellation, and terminal outcome protocol.
- Distinguish `succeeded`, `failed`, `timeout`, `cancelled`, and `crashed` terminal outcomes.
- Execute new asynchronous role tasks in a spawned process with a fixed production runner.
- Bound timeout, output size, heartbeat interval, termination grace, and retained task history.
- Prevent late child messages from changing an already terminal task or a newer attempt.
- Add create/list/get/cancel FastAPI endpoints and OpenAPI 1.12 declarations.
- Preserve the existing synchronous role routes and their response shapes during this slice.

## Non-Goals

- Migrating the existing synchronous `dispatch`, `dispatch_by_cap`, or batch routes to the process worker.
- Persistent task recovery across a whole service restart.
- Arbitrary runner modules, shell commands, plugin execution, or model tool calls from HTTP input.
- Multi-host queues, distributed leases, or unbounded task history.

## Contracts

`src/core/contracts/worker_protocol.py` owns immutable protocol values:

- `WORKER_PROTOCOL_VERSION = 1`
- `WorkerTaskStatus`: `queued`, `running`, `succeeded`, `failed`, `timeout`, `cancelled`, `crashed`
- `WorkerTaskRequest`: task ID, role name, prompt, timeout, created timestamp, and attempt ID
- `WorkerEvent`: protocol version, task ID, attempt ID, sequence, kind, timestamp, and redacted payload
- `WorkerTaskRecord`: public state, timestamps, optional result/error, worker PID, last heartbeat, and termination confirmation

All identifiers and text are nonblank. Timeout is an integer from 1 through 300 seconds. Event sequence is positive and monotonic per attempt. Public serialization uses explicit dictionaries rather than raw `asdict` so enums and future private fields cannot leak.

## Process Boundary

`RoleWorkerSupervisor` uses the `spawn` multiprocessing context and one process per accepted task. The process target is a top-level project function, never a callable supplied by an HTTP request. The child sends `started`, periodic `heartbeat`, and exactly one `result` or `failure` event over a one-way pipe.

The parent monitor owns all state transitions. Every message must match both `task_id` and `attempt_id`, and its sequence must exceed the last accepted sequence. Once a record is terminal, all later messages are ignored.

Cancellation and timeout use this order:

1. Mark cancellation/timeout intent under the task lock.
2. Call `terminate()` if the process is alive.
3. Join for the bounded termination grace.
4. Call `kill()` when available if it is still alive, then join again.
5. Publish `cancelled` or `timeout` only after `is_alive()` is false.
6. If death cannot be confirmed, retain `running` with a stable internal error and reject role reuse.

An unexpected process exit without a valid terminal message becomes `crashed`. A caught runner exception becomes `failed`. Serialized result and error output is capped at 1 MiB before it crosses into the retained record.

## Production Runner

The fixed child runner constructs its own `OllamaManager` and `AgentFactory` from trusted parent configuration, then dispatches the requested built-in role. HTTP input can select only the role name, prompt, and bounded timeout. It cannot select a module, executable, environment, working directory, or capability token.

The child returns the role result plus token counts. The parent records returned counts in the service's existing `OllamaManager`, preserving aggregate telemetry without sharing a non-picklable manager across processes.

## API

- `POST /api/roles/tasks` validates `role_name`, `prompt`, and `timeout`, starts a process task, and returns `202` with `WorkerTaskRecord`.
- `GET /api/roles/tasks` returns a bounded newest-first list and count.
- `GET /api/roles/tasks/{task_id}` returns the record or `404 ROLE_TASK_NOT_FOUND`.
- `POST /api/roles/tasks/{task_id}/cancel` returns the confirmed terminal record, `404` for an unknown ID, or `409 ROLE_TASK_TERMINAL` when the task already ended.

The Express catch-all Core API bridge continues to proxy these paths. The standard-library service is unchanged in this slice; it remains behind the same Express fallback boundary and does not claim native asynchronous task ownership.

## Shutdown

FastAPI lifespan shuts down the role-task supervisor before shutting down `AgentFactory` and `Orchestrator`. Shutdown cancels and confirms every live child, closes pipe endpoints, and leaves no process owned by the service.

## Acceptance

- A cancelled or timed-out task is terminal only after its process is confirmed stopped.
- A crash and a caught runner failure are distinguishable.
- A forged, duplicate, stale, or late event cannot change terminal state.
- Task retention stays within the configured bound.
- New endpoints match OpenAPI 1.12 and use stable error envelopes.
- Existing role, orchestrator, API contract, aggregate, discovery, frontend, and local-integration gates remain green.
