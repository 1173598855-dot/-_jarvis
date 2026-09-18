# Python Plugin Worker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move executable Python Plugins into one owned, persistent subprocess per
Plugin, with a strict V1 JSON Lines protocol and a parent-owned default-deny
Broker, while preserving the existing Plugin HTTP response shapes.

**Architecture:** Immutable protocol values live in `src/core/contracts`; the
parent-side authorization boundary lives in `src/core/kernel`; the child
entrypoint and `Popen` transport are isolated in `src/runtime` and
`src/adapters`. `PluginLoader` remains the public lifecycle coordinator but
never imports Plugin content. Each Python service owns an `EventBus` and a
`PluginManager`; Express remains a Core API proxy.

**Tech Stack:** Python 3.10+ standard library, `unittest`, FastAPI, Express 5,
OpenAPI 3.1, existing Solid.js frontend tests.

## Global Constraints

- Add no runtime dependency, package installer, remote acquisition path, or HTTP
  lifecycle authority beyond existing `load`, `enable`, and `disable` routes.
- Only `runtime: "python_worker"` is executable. `native`, `python_uv`,
  `python_venv`, and `node_worker` remain discoverable but fail closed with
  `PLUGIN_RUNTIME_UNSUPPORTED` before any Plugin import.
- The parent launches only the current interpreter as
  `python -I -u <trusted-worker-entrypoint>`, with a direct non-symlink Plugin
  child as `cwd`, no shell, no caller-provided executable, flags, environment,
  root, entrypoint, or timeout.
- Worker protocol V1 uses compact UTF-8 JSON Lines, 65,536 bytes maximum per
  line, canonical ASCII identifiers of 1..128 characters, strict field sets,
  and error text redacted/truncated to 1,024 bytes.
- Parent-owned limits are: 5 seconds handshake, 10 seconds load, 30 seconds
  activate/deactivate/cleanup, 5 seconds graceful shutdown, 1 second each for
  terminate and kill, 32 Broker calls, 64 KiB cumulative Broker exchange, 16
  KiB event payload, 100 audit entries, and 8 KiB captured stderr.
- A Broker call is allowed only when the Manifest declares its mapped
  permission, the service composition root grants it to that Plugin, and an
  exact handler is registered. V1 provides only `event_bus -> event.emit`.
- File, configuration, model, network, terminal, and process APIs have no V1
  handler and return structured `PLUGIN_BROKER_DENIED` results.
- Tests are written and observed failing before production changes. All real
  child processes must be reaped by test cleanup.
- Update the iteration ledger and preserve exactly the newest ten audit reports
  on completion; record actual verification counts rather than copied baselines.

---

### Task 1: Define The Strict Plugin Worker Protocol

**Files:**
- Create: `src/core/contracts/plugin_worker_protocol.py`
- Create: `tests/test_plugin_worker_protocol.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Produces `PLUGIN_WORKER_PROTOCOL_VERSION = 1`,
  `MAX_PLUGIN_WORKER_LINE_BYTES = 65_536`, `PluginWorkerProtocolError`, and
  `LifecycleAction` (`load`, `activate`, `deactivate`, `cleanup`, `shutdown`).
- Produces frozen `PluginLoadSpec`, `PluginWorkerHello`,
  `PluginLifecycleRequest`, `PluginBrokerRequest`, `PluginBrokerResult`, and
  `PluginLifecycleResult` records, each with `to_dict()` and `from_dict()`.
- Produces `encode_message(message) -> bytes`,
  `decode_message(line: bytes) -> ProtocolMessage`, `stable_json_bytes(value)`,
  and `redact_protocol_error(value) -> str`.
- This module imports no Plugin SDK, EventBus, HTTP, subprocess, or service code.

**V1 field decision:** Every message has exactly the required fields below and
no others. `generation` lives only in the initial `load` payload; the parent
correlates later messages with the owning runtime/reader generation, so do not
add a top-level generation field to the documented message examples.

```python
HELLO_FIELDS = {
    "protocol_version", "kind", "worker_id", "pid",
}
LIFECYCLE_REQUEST_FIELDS = {
    "protocol_version", "kind", "request_id", "plugin_id", "action", "payload",
}
BROKER_REQUEST_FIELDS = {
    "protocol_version", "kind", "request_id", "call_id", "plugin_id",
    "capability", "arguments",
}
BROKER_RESULT_FIELDS = {
    "protocol_version", "kind", "request_id", "call_id", "plugin_id",
    "allowed", "result", "error",
}
LIFECYCLE_RESULT_FIELDS = {
    "protocol_version", "kind", "request_id", "plugin_id", "success",
    "status", "error", "audit",
}
```

`hello` has `kind="hello"`, a canonical `worker_id`, and a positive integer
`pid`. A `lifecycle_request` carries one supported action. Its `load` payload
is exactly `{"entry_point": str, "permissions": list[str],
"api_version": str, "generation": positive-int}`; every other action uses
`{}`. A `broker_result` with `allowed=True` has `error=""`; one with
`allowed=False` has a stable non-empty error code and a JSON-compatible
`result` (normally `None`). `lifecycle_result.status` is one of `loaded`,
`enabled`, `disabled`, `error`, or `unloaded`; `audit` is a JSON-compatible
array of at most 100 entries. `error` carries no newline and is capped to
1,024 Unicode characters after redaction.

- [ ] **Step 1: Write failing exact-schema and round-trip tests**

```python
def test_lifecycle_request_round_trip_is_canonical(self):
    request = PluginLifecycleRequest(
        request_id="request-1",
        plugin_id="event-logger",
        action=LifecycleAction.LOAD,
        payload=PluginLoadSpec(
            entry_point="plugin.py",
            permissions=("event_bus",),
            api_version="1.0.0",
            generation=1,
        ).to_dict(),
    )
    self.assertEqual(decode_message(encode_message(request)), request)
```

Cover all message kinds, compact canonical encoding, wrong protocol version,
missing and unknown fields, invalid UTF-8, oversized lines, empty or Unicode
identifiers, bool-for-int rejection, invalid actions, invalid PID, wrong
request correlation, non-JSON values, and redaction/byte truncation.

- [ ] **Step 2: Run the protocol suite and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_protocol -v
```

Expected: import failure because `plugin_worker_protocol` does not exist.

- [ ] **Step 3: Implement immutable messages and bounded codec**

Use explicit required field sets per `kind`, `type(value) is int` for integer
fields, `json.dumps(..., ensure_ascii=False, sort_keys=True,
separators=(",", ":"), allow_nan=False)`, and byte limits before JSON decoding.
Do not accept generic mappings as a substitute for validated protocol records.
The `load` payload is exactly a validated `PluginLoadSpec`; later lifecycle
payloads are `{}`.

- [ ] **Step 4: Register the aggregate guard once and verify GREEN**

Add `TestPluginWorkerProtocol` to `tests/run_all.py`, then add a
`test_aggregate_runner_includes_plugin_worker_guards_once` assertion in
`tests/test_run_all_coverage.py`.

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_protocol tests.test_run_all_coverage -v
```

Expected: all protocol validation and aggregate-registration tests pass.

- [ ] **Step 5: Commit the protocol boundary**

```powershell
git add src/core/contracts/plugin_worker_protocol.py tests/test_plugin_worker_protocol.py tests/run_all.py tests/test_run_all_coverage.py
git commit -m "feat(plugins): add worker protocol contract"
```

### Task 2: Add The Parent-Owned Capability Broker

**Files:**
- Create: `src/core/kernel/plugin_broker.py`
- Create: `tests/test_plugin_broker.py`
- Modify: `src/core/kernel/event_bus.py`
- Modify: `tests/test_event_bus_extended.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Produces `PluginBroker(event_bus, grants)` where `grants` maps Plugin IDs to
  explicitly granted capability names.
- Produces `PluginBrokerSession`, returned by
  `PluginBroker.begin_lifecycle(plugin_id, request_id, declared_permissions,
  generation)`, with `handle(request: PluginBrokerRequest) ->
  PluginBrokerResult`.
- Produces `PluginBroker.register_handler(capability, handler)`,
  `PluginBroker.register_event_emit_handler()`, and `PluginBroker.audit_log()`.
- `PluginBrokerSession` enforces request/plugin/generation correlation,
  `MAX_BROKER_CALLS = 32`, and `MAX_BROKER_EXCHANGE_BYTES = 65_536` across one
  lifecycle request before a handler is reached.
- `EventBus.publish(event)` preserves supplied `Event.source`, so the V1 handler
  can publish `Event(event_type, source="plugin:<plugin_id>", data=payload)`.

- [ ] **Step 1: Write failing deny-by-default and event tests**

```python
def test_event_emit_requires_declaration_grant_and_registered_handler(self):
    broker = PluginBroker(EventBus(), grants={"event-logger": {"event.emit"}})
    session = broker.begin_lifecycle(
        "event-logger", "request-1", ("event_bus",), generation=1
    )
    denied = session.handle(event_request("request-1"))
    self.assertFalse(denied.allowed)
    broker.register_event_emit_handler()
    allowed = session.handle(event_request("request-1", call_id="call-2"))
    self.assertTrue(allowed.allowed)
```

Cover undeclared, ungranted, unregistered, malformed, over-budget,
wrong-request, wrong-generation, duplicate call ID, handler exception, and
oversized-result cases. Assert denied requests do not invoke the handler,
audit entries are copied/redacted/bounded, event type matches
`plugin.[A-Za-z0-9][A-Za-z0-9._:-]{0,95}`, payload stays JSON-compatible and
within 16 KiB, and the child cannot control the event source.

- [ ] **Step 2: Run the Broker tests and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_broker tests.test_event_bus_extended -v
```

Expected: import failure because `plugin_broker` does not exist.

- [ ] **Step 3: Implement the mapped, bounded handler registry**

Keep the only V1 permission map local and immutable:

```python
MANIFEST_PERMISSION_BY_CAPABILITY = {"event.emit": "event_bus"}
FIRST_PARTY_EVENT_GRANTS = {
    "event-logger": frozenset({"event.emit"}),
    "plugin-template": frozenset({"event.emit"}),
}
```

Validate all arguments before calling the handler. Return only protocol-safe,
redacted values and stable error codes. Do not add generic dispatch, a path,
URL, command, environment, model, or Core-object lookup API.

- [ ] **Step 4: Preserve EventBus source and verify GREEN**

Refactor `EventBus.publish` to append and dispatch the provided `Event` rather
than recreating it through `emit`; retain existing `emit` behavior for its
callers. Add a regression test that a published event retains
`source="plugin:event-logger"`.

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_broker tests.test_event_bus_extended -v
```

Expected: every allowed `event.emit` is parent-authored and all denial paths
remain side-effect free.

- [ ] **Step 5: Register the suite and commit**

```powershell
git add src/core/kernel/plugin_broker.py src/core/kernel/event_bus.py tests/test_plugin_broker.py tests/test_event_bus_extended.py tests/run_all.py tests/test_run_all_coverage.py
git commit -m "feat(plugins): add default-deny broker"
```

### Task 3: Implement The Child-Only Worker Entrypoint

**Files:**
- Create: `src/runtime/__init__.py`
- Create: `src/runtime/plugin_worker.py`
- Create: `tests/test_plugin_worker_entrypoint.py`
- Modify: `src/core/kernel/plugin_sdk.py`

**Interfaces:**
- Produces `runtime.plugin_worker.main() -> int` and
  `PluginWorkerServer(stdin, stdout, stderr, plugin_root)` for direct unit
  tests.
- The server sends one `PluginWorkerHello`, consumes one lifecycle request at a
  time, and returns exactly one `PluginLifecycleResult` for every accepted
  action.
- `XiaoYiPluginAPI(plugin_id, permissions, broker_call, audit_sink)` remains
  importable from `core.kernel.plugin_sdk`; external methods route through the
  active lifecycle Broker callback rather than reading files or returning
  placeholder configuration/model/system data.

- [ ] **Step 1: Write failing child lifecycle tests**

```python
def test_worker_imports_only_after_valid_load_and_keeps_module_state(self):
    worker = self._worker_for("COUNTER = 0\ndef activate(api):\n global COUNTER\n COUNTER += 1")
    self.assertEqual(worker.hello().kind, "hello")
    self.assertTrue(worker.request(load_request()).success)
    self.assertTrue(worker.request(activate_request("request-2")).success)
    self.assertTrue(worker.request(deactivate_request("request-3")).success)
```

Use temporary fixture Plugin roots for successful lifecycle calls, missing
`deactivate`, import error, lifecycle exception, explicit `SystemExit`, invalid
request, invalid Broker result, and a child API call that waits for exactly one
matching `broker_result`. Assert module names are unique per generation and no
Core service is constructed in the child.

- [ ] **Step 2: Run the entrypoint suite and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_entrypoint -v
```

Expected: import failure because `runtime.plugin_worker` does not exist.

- [ ] **Step 3: Implement isolated import and protocol-driven API**

At startup, resolve the trusted repository `src/` from this entrypoint and use
`Path.cwd()` as the selected Plugin root; add only those locations inside the
child. On `load`, validate the relative regular-file entrypoint, use
`importlib.util.spec_from_file_location` with a module name containing Plugin
ID and generation, then execute it in the child. Cache that module only in the
child process. Lifecycle actions map only to `activate(api)`, optional
`deactivate()`, optional `cleanup()`, and shutdown.

`emit_event` serializes a `PluginBrokerRequest` and blocks until the matching
parent result arrives. `get_config`, `read_file`, `call_llm`, and
`get_system_stats` return structured V1 denials through the same transport;
they must never use `open`, `os.environ`, an Ollama manager, or a system probe.

- [ ] **Step 4: Verify child protocol behavior stays bounded**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_protocol tests.test_plugin_worker_entrypoint -v
```

Expected: success responses retain state in one child process; malformed
protocol and lifecycle failures are converted to bounded results or exit
without changing the parent test process.

- [ ] **Step 5: Commit the child runtime**

```powershell
git add src/runtime/__init__.py src/runtime/plugin_worker.py src/core/kernel/plugin_sdk.py tests/test_plugin_worker_entrypoint.py
git commit -m "feat(plugins): add isolated worker entrypoint"
```

### Task 4: Add The Parent `Popen` Runtime And Fault Containment

**Files:**
- Create: `src/adapters/subprocess_plugin_runtime.py`
- Create: `tests/test_subprocess_plugin_runtime.py`
- Modify: `src/adapters/__init__.py`

**Interfaces:**
- Produces `PluginWorkerTimeouts`, `PluginRuntimeError(code, message)`,
  `PluginRuntimeSnapshot(plugin_id, pid, generation, termination_confirmed)`,
  and `SubprocessPluginRuntime(plugin_root, load_spec, broker, timeouts=...)`.
- `start() -> PluginRuntimeSnapshot` starts one child and validates its
  handshake; `invoke(action) -> PluginLifecycleResult` handles Broker messages
  synchronously while waiting for a final result; `close() -> None` cleans up
  and reaps the child.
- `is_usable` is false after timeout, protocol corruption, EOF, crash, output
  overflow, or unconfirmed termination. A failed runtime cannot be reused or
  silently replaced.

- [ ] **Step 1: Write failing real-subprocess and process-double tests**

```python
def test_timeout_terminates_and_reaps_child_without_killing_parent(self):
    runtime = self._runtime_for("def activate(api):\n    while True: pass", activate_timeout=0.2)
    runtime.start()
    with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_TIMEOUT"):
        runtime.invoke(LifecycleAction.ACTIVATE)
    self.assertTrue(runtime.snapshot.termination_confirmed)
    self.assertFalse(runtime.process_is_alive())
```

Cover successful load/activate/deactivate/cleanup/shutdown, handshake timeout,
import error, activation exception, child exit, malformed/oversized stdout,
Broker call exchange, cumulative-call cap, late old-request/generation
messages, stderr truncation, minimal sanitized environment, unchanged parent
`sys.path`/`sys.modules`, and injected unconfirmed termination. Each fixture
uses `TemporaryDirectory`; each test closes the runtime in `addCleanup`.

- [ ] **Step 2: Run the runtime suite and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_subprocess_plugin_runtime -v
```

Expected: import failure because `subprocess_plugin_runtime` does not exist.

- [ ] **Step 3: Implement deterministic launch, transport, and termination**

Construct `Popen` with an argument list only, `shell=False`, binary streams,
the current `sys.executable`, `-I`, `-u`, a trusted absolute worker entrypoint,
a validated direct-child Plugin `cwd`, and a sanitized environment. Preserve
only `PATH`, `PATHEXT`, `SystemRoot`, `WINDIR`, and `ComSpec` when present, plus
`PYTHONIOENCODING=utf-8`, `PYTHONUNBUFFERED=1`, `PYTHONNOUSERSITE=1`, and a
fresh Worker temporary directory. Omit every `JARVIS_*`, `OLLAMA_*`, proxy,
credential, and arbitrary `PYTHON*` value.

Use one stdout reader thread and a bounded queue, reject messages not matching
the active request and generation, route Broker calls through a newly opened
Broker session, and cap stderr without exposing it in public errors. On every
fatal transport condition, close stdin, wait, terminate, then kill when
available, and mark confirmation only after `poll()`/`wait()` proves exit.

- [ ] **Step 4: Verify fault containment and process cleanup**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_subprocess_plugin_runtime tests.test_plugin_broker -v
```

Expected: all failure fixtures leave the parent alive, all successful fixture
processes are reaped, and no late message changes a published terminal result.

- [ ] **Step 5: Commit the transport adapter**

```powershell
git add src/adapters/subprocess_plugin_runtime.py src/adapters/__init__.py tests/test_subprocess_plugin_runtime.py
git commit -m "feat(plugins): isolate workers in subprocesses"
```

### Task 5: Refactor The SDK Coordinator And Migrate First-Party Plugins

**Files:**
- Modify: `src/core/kernel/plugin_sdk.py`
- Modify: `plugins/event-logger/manifest.json`
- Modify: `plugins/event-logger/plugin.py`
- Modify: `plugins/plugin-template/manifest.json`
- Modify: `plugins/plugin-template/plugin.py`
- Modify: `tests/test_plugin_sdk.py`
- Modify: `tests/test_plugin_sdk_extended.py`
- Modify: `tests/test_plugin_sdk_extended_v2.py`
- Modify: `tests/test_plugin_installation.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- `RuntimeType` adds `PYTHON_WORKER = "python_worker"`; the existing legacy
  values remain enumerable and non-executable.
- `PluginLoader(plugins_dir, broker, runtime_factory=SubprocessPluginRuntime)`
  owns discovered Manifests and runtime handles, but never imports Plugin code.
- `PluginManager(plugins_dir, event_bus, grants, runtime_factory=...)` is a
  normal per-service owner with `close() -> None`; `global_plugin_manager`
  remains a compatibility object only for direct imports.
- `PluginInstance` retains public manifest/status/timestamp/count/error fields
  and gains private runtime ownership plus safe `worker_pid` and generation
  metadata; its `module` is never a Plugin module in the Core process.

- [ ] **Step 1: Write failing SDK and first-party lifecycle tests**

```python
def test_first_party_plugin_runs_in_distinct_pid_and_emits_parent_owned_event(self):
    bus = EventBus()
    manager = PluginManager(ROOT / "plugins", event_bus=bus)
    instance = manager.load(self._manifest(manager, "event-logger"))
    self.assertNotEqual(instance.worker_pid, os.getpid())
    self.assertTrue(manager.enable("event-logger"))
    event = bus.get_history()[-1]
    self.assertEqual(event.event_type, "plugin.activated")
    self.assertEqual(event.source, "plugin:event-logger")
```

Also assert one exact second load returns its existing instance, a changed
root/entrypoint/generation for that ID is rejected, an invalid root or
entrypoint stays under the configured direct child, legacy runtime discovery
does not import content and returns `PLUGIN_RUNTIME_UNSUPPORTED`, an import
failure becomes a bounded error instance, disable is a no-op when the Plugin
has no hook, unload returns `False` when missing, and manager shutdown attempts
every worker even if one cleanup fails.

- [ ] **Step 2: Run SDK and installation tests and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_sdk tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation -v
```

Expected: assertions fail because `native` remains executable and the old API
still accesses files/configuration in the Core process.

- [ ] **Step 3: Replace in-process import with runtime coordination**

Remove `sys.path.insert`, `importlib.import_module`, direct `open()` from
`XiaoYiPluginAPI.read_file`, and placeholder model/system/configuration
responses. Validate the Manifest before starting a runtime, resolve only a
direct non-symlink root below the configured Plugin directory, start a
generation-specific runtime, and publish `loaded` only after a valid `load`
result. Map runtime failure codes to redacted `PluginInstance.error_message`.

Make `enable`, `disable`, and `unload` call lifecycle actions; increment
activation count only after success. `unload` runs best-effort cleanup, always
requests shutdown, reaps before removing an instance, and leaves an unconfirmed
handle in `error` rather than replacing it.

- [ ] **Step 4: Migrate the repository Plugins**

Set both Manifests to `"runtime": "python_worker"`. Keep only `event_bus`
for `plugin-template`; remove its placeholder configuration/file calls. Keep
`event-logger` emitting `plugin.activated`. Both Plugins use only
`api.emit_event("plugin.activated", {"plugin_id": api.plugin_id})`.

- [ ] **Step 5: Verify SDK compatibility and register final guards**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_sdk tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation tests.test_plugin_broker -v
```

Expected: public lifecycle statuses remain `loaded`, `enabled`, `disabled`,
`error`, and `unloaded`; neither first-party Plugin is present in the parent
module cache; all test workers exit during cleanup.

- [ ] **Step 6: Commit the SDK migration**

```powershell
git add src/core/kernel/plugin_sdk.py plugins/event-logger/manifest.json plugins/event-logger/plugin.py plugins/plugin-template/manifest.json plugins/plugin-template/plugin.py tests/test_plugin_sdk.py tests/test_plugin_sdk_extended.py tests/test_plugin_sdk_extended_v2.py tests/test_plugin_installation.py tests/run_all.py tests/test_run_all_coverage.py
git commit -m "feat(plugins): run first-party plugins in workers"
```

### Task 6: Inject Per-Service Plugin Ownership And Preserve HTTP Contracts

**Files:**
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `frontend/server.js`
- Modify: `frontend/server.test.js`
- Modify: `contracts/core-api.openapi.json`
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi.py`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Both `AppState` constructors accept optional `event_bus` and `plugin_manager`;
  otherwise they construct an injected `EventBus` and service-local
  `PluginManager` with only `FIRST_PARTY_EVENT_GRANTS`.
- Python HTTPServer handlers use `self.app_state.plugin_manager`; FastAPI
  endpoints use the active `state.plugin_manager`. Production routes no longer
  reference `global_plugin_manager`.
- `AppState.shutdown()` calls `plugin_manager.close()` in deterministic order,
  continues cleanup after one failure, then destroys its EventBus.
- Existing response bodies stay exactly
  `{plugins: [...]}`, `{plugin_id, name, status}`, and `{success, plugin_id}`.

- [ ] **Step 1: Write failing injected-state and service contract tests**

```python
def test_httpserver_plugin_handler_uses_its_app_state_manager(self):
    manager = MagicMock()
    handler = _make_handler(app_state=AppState(plugin_manager=manager))
    handler.handle_plugins_list()
    manager.get_all_plugins.assert_called_once_with()

def test_fastapi_shutdown_reaps_all_plugin_workers_after_cleanup_error(self):
    first, second = _manager_that_raises_once(), _manager_that_confirms_close()
    state = AppState(plugin_manager=CompositePluginManager(first, second))
    with self.assertRaises(RuntimeError):
        state.shutdown()
    self.assertTrue(second.closed)
```

Cover injected EventBus event visibility, first-party explicit grants, missing
ID and not-found envelopes, `python_worker` successful load/enable/disable,
legacy-runtime load failure with unchanged response shape, Express forwarding
of all three paths, and no caller-controlled Worker fields.

- [ ] **Step 2: Run focused service tests and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main tests.test_main_fastapi tests.test_api_contract -v
Set-Location frontend
npm test -- --run server.test.js
Set-Location ..
```

Expected: existing services still reference the global manager and tests expose
the missing owned shutdown behavior.

- [ ] **Step 3: Implement injected ownership and deterministic teardown**

Import `EventBus`, `PluginManager`, and `FIRST_PARTY_EVENT_GRANTS` only at
service composition roots. Replace all production route references to the
global compatibility manager. Have `/api/events` serialize the service's
EventBus history without expanding its public response fields. Add Plugin
manager cleanup after task/orchestrator cleanup and before `EventBus.destroy`,
capturing the first error only after all cleanup attempts complete.

- [ ] **Step 4: Update the shared API contract without expanding authority**

Bump `info.version` from `1.15.0` to `1.16.0`. Document the existing Plugin
paths as Worker-isolated, state that only `plugin_id` is accepted, and declare
the existing stable runtime errors where they fit existing error envelopes. Add
the existing `enable` and `disable` paths only if their current shape is
represented exactly; do not introduce an unload, install, archive, URL, or
Worker-control endpoint. Keep Express's `proxyCoreRequest` implementation and
proxy error envelopes unchanged.

- [ ] **Step 5: Verify all three services match**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_api_contract tests.test_main tests.test_main_fastapi -v
Set-Location frontend
npm test -- --run
Set-Location ..
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services
```

Expected: Python HTTPServer, FastAPI, and Express preserve existing Plugin
success/error shapes while all Plugin execution remains in owned workers.

- [ ] **Step 6: Commit the service boundary**

```powershell
git add src/main.py src/main_fastapi.py frontend/server.js frontend/server.test.js contracts/core-api.openapi.json tests/test_main.py tests/test_main_fastapi.py tests/test_api_contract.py
git commit -m "feat(plugins): own worker lifecycles per service"
```

### Task 7: Record Iteration 141 Evidence And Run Final Gates

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_141.md`
- Delete: `docs/reports/AUDIT_REPORT_131.md`
- Modify: any test ledger/count guard affected by actual final counts

**Interfaces:**
- Documentation calls the execution model `python_worker`, makes the
  same-user/OS-isolation limitation explicit, and documents the default-deny
  Broker as the only V1 authority.
- The reports index retains only `AUDIT_REPORT_132.md` through
  `AUDIT_REPORT_141.md` after the final audit is created.

- [ ] **Step 1: Write documentation guard expectations before editing prose**

```python
def test_readme_documents_worker_isolated_plugin_runtime(self):
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    self.assertIn("python_worker", text)
    self.assertIn("event.emit", text)
    self.assertNotIn("native plugin import", text.lower())
```

Update the relevant documentation/iteration tests so the reported Iteration and
audit window are checked mechanically.

- [ ] **Step 2: Run the documentation guards and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_readme tests.test_docs_setup tests.test_iteration_ledger -v
```

Expected: old Iteration 140 references and Plugin setup wording fail the new
assertions.

- [ ] **Step 3: Update current-state documentation and audit evidence**

Record the actual architecture, added modules, no-new-authority scope,
first-party migration, response compatibility, exact verification output, and
remaining Stage E OS-level isolation work. Do not state a test count until the
final commands have completed. Delete only the named oldest audit report after
confirming the report index has eleven entries including 141.

- [ ] **Step 4: Run the complete final verification gate**

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
Set-Location frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services
git diff --check
```

Expected: every gate passes; audit/report counts contain observed results; no
test fixture or Worker temporary file remains outside ignored `.test-*` or
temporary directories.

- [ ] **Step 5: Review the final diff and commit Iteration 141**

```powershell
git status --short
git diff --check
git diff -- src/core/contracts/plugin_worker_protocol.py src/core/kernel/plugin_broker.py src/core/kernel/plugin_sdk.py src/runtime/plugin_worker.py src/adapters/subprocess_plugin_runtime.py src/main.py src/main_fastapi.py
```

Then stage only Iteration 141 files plus the already-approved design and this
plan after confirming there are no unrelated user edits:

```powershell
git add src/core/contracts/plugin_worker_protocol.py src/core/kernel/plugin_broker.py src/core/kernel/plugin_sdk.py src/core/kernel/event_bus.py src/runtime src/adapters/subprocess_plugin_runtime.py src/main.py src/main_fastapi.py plugins tests contracts frontend README.md AGENTS.md CHANGELOG.md docs/DEVELOPMENT_GUIDE.md docs/reports docs/superpowers/specs/2026-08-02-plugin-worker-runtime-design.md docs/superpowers/plans/2026-08-02-plugin-worker-runtime.md
git commit -m "feat(plugins): isolate Python plugin runtime"
```

## Plan Self-Review

- Every acceptance criterion from `2026-08-02-plugin-worker-runtime-design.md`
  maps to Tasks 1-7: strict protocol, process isolation, timeout/reap behavior,
  Broker declaration/grant/handler checks, first-party migration, owned service
  shutdown, response compatibility, and final evidence.
- The interfaces are directional: protocol feeds Broker and runtime; runtime
  feeds SDK; SDK feeds service composition. No later task requires a name not
  introduced in an earlier task.
- The plan leaves OS-level filesystem/network sandboxing, remote acquisition,
  runtime selection by HTTP, and non-Python runtimes outside scope.
- Each production task starts with a concrete failing unittest and ends with an
  exact focused command before a bounded commit.
