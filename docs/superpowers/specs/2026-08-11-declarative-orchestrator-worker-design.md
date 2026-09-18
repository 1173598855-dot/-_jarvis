# Declarative Orchestrator Worker Design

**Date:** 2026-08-11

## Context

`Orchestrator.register()` accepts an arbitrary in-memory Python callable. The
Iteration 144 timeout quarantine prevents a timed-out callable from being
reused while its daemon thread is still alive, but Python cannot terminate that
thread. The three HTTP adapters retain the generic dispatch route for
compatibility; no service currently bootstraps a generic Agent by default.

The existing `RoleWorkerSupervisor` already owns a `spawn` child process,
bounded output, timeout termination, confirmation, and reaping. It cannot
directly execute every registered generic callable: closures, bound instances,
and parent-only dependencies do not have a stable cross-process contract.

## Options Considered

1. Pass the existing callable through `multiprocessing`.
   This fails on the Windows `spawn` context for common closures and makes an
   arbitrary import/execution contract implicit.
2. Refactor the entire role Worker protocol into a new generic protocol.
   This would eventually cover every lifecycle feature, but expands a focused
   reliability increment into a protocol and API migration.
3. Add an opt-in declarative registration path backed by the existing
   supervisor. The child resolves a fixed runner identifier from a static,
   trusted registry; the legacy callable path remains explicitly in-process.

Option 3 is selected. It creates a real terminable Worker path now without
pretending that arbitrary Python callables are serializable or isolated.

## Design

### Registration Boundary

`Orchestrator.register_declared(name, runner_id, capabilities=None)` will add a
new Agent only when `name` is a canonical worker identifier and `runner_id` is
present in a module-local static runner registry. The first registry entry is
the deterministic `echo` runner. It receives a JSON representation of the
full `AgentTask`, optionally waits for bounded `metadata.delay_ms`, and returns
the prompt, priority, metadata, and child PID. It is an explicit bootstrap
building block, not an HTTP registration API.

`Orchestrator.register(name, callable, capabilities=None)` is unchanged. It
continues to use the legacy daemon-thread compatibility path and therefore
continues to be covered by Iteration 144 quarantine behavior. Neither path
accepts a caller-supplied module path, command, environment, working directory,
or capability token.

### Worker Data Flow

Each declared Agent owns one `RoleWorkerSupervisor`. On dispatch, a private
adapter validates the original task ID, agent name, prompt, timeout, priority,
and metadata as strict JSON with exact built-in text, scalar, and container
types (UTF-8 text, string keys, finite numbers, bounded integer magnitude,
non-recursive nesting), then serializes it into a bounded JSON string. This
rejects hostile Python subclasses before their hooks can run. It creates an internal
`WorkerTaskRequest` with a generated canonical worker task ID and the declared
Agent name in `role_name`; this lets the existing Worker protocol retain its
strict identifiers, process ownership, heartbeat, output cap, and confirmed
termination semantics.

The module-level child entry point decodes the task payload, verifies it agrees
with the trusted request, resolves `runner_id` only from the static registry,
and invokes the selected runner. Pre-execution JSON rejection fails before
process creation and returns the Agent to `IDLE` without changing its lifecycle
counters; malformed child payloads (including duplicate keys or non-finite
constants), unknown runner IDs, and runner exceptions become normal Worker
failures. Worker results are converted back to the existing `AgentResult` shape
in the parent, preserving the original caller task ID and history ownership.

### Lifecycle Mapping

- Confirmed `SUCCEEDED`: complete the Agent and return `success`.
- Confirmed `TIMEOUT`: increment errors, preserve the existing non-recoverable
  timeout state, and return `timeout`; `dispatch_with_retry()` retains its
  existing reset-and-retry behavior.
- Confirmed `FAILED`, `CRASHED`, or `CANCELLED`: record a normal recoverable
  `error` state with the bounded Worker failure message.
- Missing, nonterminal, or unconfirmed records: preserve a pending Worker
  reference and quarantine the Agent. `dispatch`, `unregister`, re-registration,
  and retry cannot reuse it until the supervisor reports confirmed termination.
- A transport or Supervisor error after a task has become active: probe the
  Worker state and preserve the same quarantine whenever termination cannot be
  confirmed; a failed probe is treated as pending.
- `shutdown()` asks every declared Agent's supervisor to stop and reaps only
  after the existing confirmation policy has completed.

This establishes hard child-process termination for declared Agents only.
Generic dispatch remains synchronous and has no public cancellation or task
persistence endpoint in this increment.

### Scope and Non-Goals

- Preserve all HTTP request/response schemas and Express bridge behavior.
- Reuse the existing role Worker process protocol instead of adding a second
  process monitor or external dependency.
- Do not dynamically import runner identifiers, serialize arbitrary callables,
  expose a registration endpoint, add a user-configurable command runner, or
  claim OS-level filesystem/network sandboxing.
- A later increment can add additional audited static runners or a broader
  declarative package contract; it must not weaken the static registry boundary.

## Test Strategy

Use `unittest` with the real Windows-safe `spawn` process context:

1. A declared `echo` Agent returns the complete task projection from a child
   PID, while a legacy callable still executes in the parent process.
2. Unknown or non-plain runner IDs are rejected before registration and leave
   the registry unchanged.
3. Recursive, non-string-keyed, invalid-Unicode, oversized, oversized-
   integer, and hostile-subclass metadata returns a bounded error without
   starting a child process, corrupting later dispatches, or incrementing Agent
   execution counters.
4. A delayed declared echo task reaches the existing Worker timeout path,
   confirms child termination, remains non-recoverable through `recover_agent`,
   and becomes retryable through the existing retry API. A post-submit transport
   failure with an active Worker also blocks recovery, removal, and replacement
   until the Worker reports release.
5. Direct child decoding rejects duplicate keys and non-finite JSON constants.
6. Existing generic timeout-quarantine and shared API contract suites remain
   green, proving the compatibility path and adapter shape are unchanged.
