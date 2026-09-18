# Python Plugin Worker Runtime Design

**Date:** 2026-08-02
**Iteration:** 141
**Stage:** E1 - Plugin/Skill safe runtime
**Status:** Approved for implementation planning

## 1. Goal

Move Python Plugin import and lifecycle execution out of the J.A.R.V.I.S.
Core process. Each loaded Plugin runs in its own long-lived subprocess, uses a
strict versioned IPC protocol, and reaches Core-owned capabilities only through
a default-deny parent-side Broker.

Iteration 141 must prove that a Plugin import failure, exception, timeout,
protocol violation, or process crash cannot terminate or mutate the Core
process. Existing Plugin HTTP response shapes remain compatible.

## 2. Current Problem

`PluginLoader` currently inserts a Plugin directory into the Core process
`sys.path` and calls `importlib.import_module()`. The `sandbox` Manifest field
only checks that three strings appear in `denied_apis`; it does not create an
execution boundary. `XiaoYiPluginAPI` also performs file access directly and
contains placeholder model and system implementations.

Consequences:

- Plugin import side effects run inside Core.
- A Plugin can mutate shared modules and process globals.
- A crash or unbounded lifecycle call can block or damage the service.
- Declared permissions are not an authoritative runtime boundary.
- Service shutdown does not own a set of persistent Plugin processes.

Stage D already provides bounded local discovery and verified disabled package
storage. This design consumes only repository-local Plugin directories selected
by trusted service configuration; it adds no HTTP archive, URL, path, install,
upgrade, rollback, or enablement authority.

## 3. Scope

Iteration 141 includes:

- A strict Plugin Worker protocol, version 1.
- One persistent Python subprocess per loaded Plugin.
- Child-only entrypoint import and lifecycle calls.
- Parent-owned timeout, termination, output, and process-state enforcement.
- A parent-side Broker requiring declaration, grant, and handler registration.
- One bounded `event.emit` handler backed by the service EventBus.
- Explicit denial of file, configuration, model, network, terminal, and process
  capabilities.
- Per-service PluginManager ownership and deterministic shutdown.
- Migration of the two repository Plugins from `native` to `python_worker`.
- Regression coverage for the existing Python, FastAPI, and Express HTTP
  response contracts.

Iteration 141 does not include:

- OS user, container, AppContainer, seccomp, namespace, or filesystem ACL
  isolation.
- Dependency installation or per-Plugin virtual environments.
- Native, Node, `python_uv`, or `python_venv` execution.
- File, configuration, model, network, terminal, or process Broker handlers.
- Automatic Plugin loading or enabling at startup.
- Remote Plugin acquisition or HTTP lifecycle expansion.
- Stage E completion. A same-user Python process can still access operating
  system resources directly until later platform sandbox work is delivered.

## 4. Considered Approaches

### 4.1 One persistent subprocess per Plugin - selected

The parent starts a sanitized `subprocess.Popen` host for each loaded Plugin.
The process remains alive through activate and deactivate calls, preserving
module state while isolating imports and failures from Core. JSON Lines over
stdin/stdout provides a versioned, inspectable protocol; the parent owns all
deadlines and termination.

This requires a reader loop and explicit lifecycle cleanup, but it is the only
option that preserves Plugin lifecycle semantics and isolates Plugins from one
another.

### 4.2 One short-lived process per lifecycle action - rejected

This simplifies timeout cleanup but re-imports the Plugin on every action and
loses module state between activate and deactivate. It cannot faithfully
support the existing lifecycle contract.

### 4.3 One shared Plugin host process - rejected

This reduces process count, but one Plugin can corrupt or terminate every other
Plugin in the host. It fails the Stage E per-Plugin fault-containment goal.

## 5. Component Boundaries

### `src/core/contracts/plugin_worker_protocol.py`

Owns immutable protocol values, exact message schemas, canonical JSON encoding,
identifier validation, byte budgets, and decode errors. It imports no runtime,
Plugin, HTTP, or EventBus implementation.

### `src/core/kernel/plugin_broker.py`

Owns the parent-side authorization decision and handler registry. A call is
authorized only when all of these are true:

1. The Plugin Manifest declares the mapped permission.
2. The service composition root grants the capability to that Plugin.
3. A handler for the exact capability is registered.

The Broker records a bounded, redacted audit entry for allowed and denied
calls. Missing policy, malformed arguments, missing handlers, handler errors,
and output-limit failures all fail closed.

### `src/runtime/plugin_worker.py`

Is the child-process entrypoint. It performs the protocol handshake, validates
requests, imports one entrypoint under a unique module name, invokes lifecycle
functions, and exposes a protocol-backed `XiaoYiPluginAPI`. It never constructs
Core services or executes a Broker handler.

### `src/adapters/subprocess_plugin_runtime.py`

Owns `Popen`, the sanitized environment, stdin/stdout transport, stderr capture,
deadlines, process generation, termination confirmation, and late-message
rejection. It exposes a synchronous runtime interface to `PluginLoader` so the
existing service handlers do not need a response-shape change.

### `src/core/kernel/plugin_sdk.py`

Retains the public Manifest, status, instance, loader, manager, and
`XiaoYiPluginAPI` import surface. `PluginLoader` becomes a coordinator and never
imports Plugin content. `XiaoYiPluginAPI` delegates external operations to the
child transport; it no longer reads files or returns placeholder model/system
data directly.

### Service composition roots

`src/main.py` and `src/main_fastapi.py` each own an injected `EventBus` and
`PluginManager`. Plugin routes use the AppState-owned manager instead of the
module singleton. Shutdown closes the manager and confirms every Worker exit.
The legacy `global_plugin_manager` remains available to direct imports during
the compatibility period but is not used by production HTTP handlers.

## 6. Process Model

The parent launches the current interpreter with isolated mode and unbuffered
I/O:

```text
python -I -u <trusted-plugin-worker-entrypoint>
```

The command contains no caller-controlled executable or flags. The parent
resolves the Plugin root as one direct, non-symlink child of the configured
`plugins/` root. The entrypoint must be a regular file contained by that root.
HTTP callers provide only `plugin_id`; they cannot provide a root, path,
entrypoint, interpreter, environment, timeout, or command.

The Worker environment contains only the values needed to start Python on the
current platform:

- `PATH`
- `PATHEXT`, `SystemRoot`, `WINDIR`, and `ComSpec` on Windows when present
- `PYTHONIOENCODING=utf-8`
- `PYTHONUNBUFFERED=1`
- `PYTHONNOUSERSITE=1`
- a Worker-owned temporary directory through `TEMP`/`TMP` or `HOME`/`TMPDIR`

Service tokens, Ollama configuration, proxy variables, credentials, arbitrary
`PYTHONPATH`, and caller environment overrides are not inherited. The trusted
Worker bootstrap adds only the repository `src/` root and the selected Plugin
root inside the child process.

Only `runtime: "python_worker"` is executable. Legacy `native`, `python_uv`,
`python_venv`, and `node_worker` Manifests remain discoverable but loading them
returns a bounded unsupported-runtime error without importing content.

## 7. Protocol

`PLUGIN_WORKER_PROTOCOL_VERSION` is `1`. Every message is one compact UTF-8 JSON
object followed by `\n`. Unknown, missing, duplicate-semantic, or incorrectly
typed fields are rejected. Booleans do not satisfy integer fields.

The maximum encoded line is 65,536 bytes. Identifiers are 1 to 128 ASCII
characters matching `[A-Za-z0-9][A-Za-z0-9._:-]*`. Error text is redacted and
truncated to 1,024 characters. Captured stderr is retained only up to 8 KiB.

### 7.1 Handshake

The child must emit a `hello` message within 5 seconds:

```json
{
  "protocol_version": 1,
  "kind": "hello",
  "worker_id": "worker-...",
  "pid": 1234
}
```

An invalid, oversized, missing, or duplicate handshake terminates the process.

### 7.2 Lifecycle request

The parent sends one lifecycle action at a time:

```json
{
  "protocol_version": 1,
  "kind": "lifecycle_request",
  "request_id": "request-...",
  "plugin_id": "event-logger",
  "action": "load",
  "payload": {}
}
```

Supported actions are `load`, `activate`, `deactivate`, `cleanup`, and
`shutdown`. The initial `load` payload carries the already validated canonical
Plugin specification: entrypoint, declared permissions, API version, and a
process generation. Later actions carry no path or permission changes.

### 7.3 Broker call

During an action, the child may issue a Broker request tied to the active
lifecycle request:

```json
{
  "protocol_version": 1,
  "kind": "broker_request",
  "request_id": "request-...",
  "call_id": "call-...",
  "plugin_id": "event-logger",
  "capability": "event.emit",
  "arguments": {
    "event_type": "plugin.activated",
    "payload": {"plugin_id": "event-logger"}
  }
}
```

The parent replies with exactly one `broker_result` containing `allowed`, a
bounded result, and a stable error code when denied. A lifecycle action may
issue at most 32 calls and may exchange at most 64 KiB of cumulative Broker
arguments and results.

### 7.4 Lifecycle result

The child completes an action with exactly one result:

```json
{
  "protocol_version": 1,
  "kind": "lifecycle_result",
  "request_id": "request-...",
  "plugin_id": "event-logger",
  "success": true,
  "status": "enabled",
  "error": "",
  "audit": []
}
```

Audit output is limited to 100 entries and the line-size budget. A result with
the wrong request, Plugin, protocol version, process generation, or state
transition is a protocol violation.

## 8. Lifecycle and State

Public statuses remain `loaded`, `enabled`, `disabled`, `error`, and `unloaded`.
Synchronous routes do not expose transient states.

### Load

1. Validate the Manifest, runtime, unique Plugin ID, root, and entrypoint.
2. Start one Worker and complete the handshake.
3. Send `load`; only the child imports the entrypoint.
4. Require a valid success result before publishing `loaded`.

An exact second load returns the existing instance. A different root,
entrypoint, or generation for the same ID is rejected.

### Activate

`activate(api)` runs inside the Worker. Broker calls are handled synchronously
by the parent while it waits for the final result. Success publishes `enabled`
and increments activation count. There is no hidden retry.

### Deactivate

If the module has `deactivate`, it runs inside the same Worker. Missing
`deactivate` is a successful no-op. Success publishes `disabled`.

### Unload

If available, `cleanup` runs first. The parent then requests `shutdown`, closes
the transport, and confirms process exit before removing the instance. Repeated
unload of a missing Plugin retains the existing `False` compatibility result.

### Service shutdown

The AppState closes every Plugin in deterministic Plugin-ID order. Cleanup is
best effort across Plugins, but each Worker is still terminated and reaped.
The first cleanup error may be reported after all Workers have been processed.

## 9. Timeouts and Termination

Budgets are parent-owned constants and cannot be changed through HTTP or a
Manifest:

| Operation | Deadline |
|---|---:|
| Handshake | 5 seconds |
| Load | 10 seconds |
| Activate/deactivate/cleanup | 30 seconds |
| Graceful shutdown | 5 seconds |
| Terminate/kill grace | 1 second each |

On deadline, EOF, process exit, malformed protocol, or output overflow, the
parent:

1. Records a bounded stable error.
2. Closes stdin to prevent new work.
3. Waits for the process until the applicable grace expires.
4. Calls terminate, then kill when supported, with a one-second wait after
   each action.
5. Marks termination confirmed only after the process is not alive and has
   been reaped.

If exit cannot be confirmed, the instance remains `error`, retains its process
handle, and blocks replacement or reactivation. Late messages are discarded by
request ID and process generation and cannot change a published terminal state.

## 10. Broker Policy

Capability names are independent of Manifest permission strings. Iteration 141
defines one mapping:

| Manifest permission | Broker capability | Iteration 141 handler |
|---|---|---|
| `event_bus` | `event.emit` | Bounded EventBus publish |

`event.emit` requires an event type matching
`plugin.[A-Za-z0-9][A-Za-z0-9._:-]{0,95}` and a JSON-compatible payload of at
most 16 KiB. The parent supplies the authoritative source as
`plugin:<plugin_id>`; the child cannot override it.

Production grants `event.emit` only to the two repository-owned first-party
Plugin IDs. Tests may inject other explicit grants. A Manifest declaration by
itself never grants the call.

The following existing API methods return a structured permission denial in
Iteration 141 because no handler is registered:

- `get_config`
- `read_file`
- `call_llm`
- `get_system_stats`

No generic method accepts a URL, command, filesystem path, environment value,
model identifier, or arbitrary Core method name.

## 11. First-Party Plugin Migration

Both `plugins/event-logger/manifest.json` and
`plugins/plugin-template/manifest.json` change to
`runtime: "python_worker"`.

`event-logger` keeps only `event_bus` and continues to emit
`plugin.activated`.

`plugin-template` is reduced to the capability that is real in this iteration:
it keeps `event_bus`, removes `system_config` and `file_read`, and no longer
calls placeholder configuration or direct file APIs. This prevents the sample
from advertising capabilities that the production runtime intentionally
denies.

Plugin API version remains `1.0.0`; Worker protocol versioning is separate.

## 12. HTTP Compatibility

The following response shapes do not change:

- `GET /api/plugins`
- `POST /api/plugins/load`
- `POST /api/plugins/enable`
- `POST /api/plugins/disable`

Python HTTPServer and FastAPI use their AppState-owned manager. Express remains
a Core API proxy. Request bodies still accept only `plugin_id` and retain the
current size, missing-ID, not-found, and proxy error envelopes.

OpenAPI is updated to describe Worker-isolated execution and unsupported
legacy runtimes. A contract version bump is allowed, but no new lifecycle path
or caller-controlled Worker field is introduced.

## 13. Error Semantics

Internal failures use stable codes while public response shapes remain
compatible:

- `PLUGIN_RUNTIME_UNSUPPORTED`
- `PLUGIN_ROOT_INVALID`
- `PLUGIN_ENTRYPOINT_INVALID`
- `PLUGIN_WORKER_START_FAILED`
- `PLUGIN_WORKER_HANDSHAKE_FAILED`
- `PLUGIN_WORKER_PROTOCOL_ERROR`
- `PLUGIN_WORKER_OUTPUT_LIMIT`
- `PLUGIN_WORKER_TIMEOUT`
- `PLUGIN_WORKER_CRASHED`
- `PLUGIN_WORKER_TERMINATION_UNCONFIRMED`
- `PLUGIN_BROKER_DENIED`
- `PLUGIN_BROKER_HANDLER_FAILED`
- `PLUGIN_LIFECYCLE_FAILED`

Errors exposed through `PluginInstance.error_message` are redacted, bounded,
and contain no absolute Plugin path, environment value, traceback, request
payload, or service secret. Full tracebacks remain parent-side logs after
redaction.

## 14. Testing Strategy

Implementation follows test-first RED-GREEN-REFACTOR cycles.

### Protocol tests

- Exact round trips for every message kind.
- Missing, unknown, incorrectly typed, oversized, and invalid Unicode fields.
- Strict integer, identifier, request correlation, and protocol version rules.
- Broker call-count and cumulative-byte budgets.

### Broker tests

- Declaration, grant, and handler are all required.
- Undeclared, ungranted, unregistered, malformed, and oversized calls never
  reach the handler.
- Allowed event calls preserve the parent-owned Plugin source.
- Audit history is bounded, copied, and redacted.

### Runtime tests

Use generated local fixtures for:

- Successful load, activate, deactivate, cleanup, and shutdown.
- Import exception.
- Activation exception.
- Infinite wait and deadline termination.
- Explicit child-process exit.
- Invalid or oversized protocol output.
- Excessive Broker calls.
- Unconfirmed termination using an injected process double.
- Late response from an old request or generation.
- Minimal environment without a sentinel service secret.
- Parent `sys.path` and `sys.modules` remaining unchanged.

The parent test process must remain alive in every crash case and all real
fixture processes must be reaped before test cleanup.

### SDK and service tests

- Legacy runtimes are discoverable but cannot load.
- Both first-party Plugins execute in a different PID.
- The first-party event reaches the injected EventBus only when explicitly
  granted.
- Existing load/enable/disable success shapes remain valid in Python
  HTTPServer, FastAPI, and Express contract fixtures.
- AppState shutdown processes every Worker even when one cleanup fails.

### Final gates

- Canonical aggregate Python suite.
- Full Python unittest discovery.
- Python compileall.
- Frontend Vitest, typecheck, build, and Playwright.
- Deterministic three-service integration profile.
- `git diff --check`.

## 15. Rollout and Recovery

The new runtime is the only executable Python Plugin path; there is no
environment switch that silently restores in-process native imports. Plugins
remain unloaded until an existing lifecycle request explicitly loads them.

Rollback is a normal Git revert of the Iteration 141 implementation and
first-party Manifest migration. No persistent Plugin state or data migration
is introduced. Worker temporary directories are disposable and excluded from
Git.

Stage E remains in progress after this iteration. The next design must address
OS-level filesystem/network isolation and additional Brokers before verified
third-party Plugin content may be enabled.

## 16. Acceptance Criteria

Iteration 141 is complete only when all of the following are evidenced:

1. No production Plugin entrypoint is imported in the Core process.
2. Each loaded Plugin has a distinct, owned subprocess and process generation.
3. Import failure, exception, timeout, protocol corruption, and process exit do
   not terminate or mutate Core.
4. A Worker is not replaced or reused until its previous exit is confirmed.
5. Broker execution requires declaration, grant, and registered handler.
6. File, configuration, model, network, terminal, and process calls remain
   denied.
7. Both first-party Plugins use `python_worker` and the documented event path.
8. Existing Plugin HTTP request and response shapes remain contract-valid.
9. Service shutdown reaps every Plugin Worker.
10. The full repository verification gates pass with current, recorded counts.

