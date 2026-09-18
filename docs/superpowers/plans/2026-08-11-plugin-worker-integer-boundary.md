# Plugin Worker Integer Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every direct or wire-derived Plugin Worker V1 JSON integer fails through the stable protocol boundary before Python serialization can raise an environment-dependent exception.

**Architecture:** Keep the resource check in `plugin_worker_protocol.py`, the common validation authority for all V1 records and canonical serialization. A shared 512-decimal-digit limit will cover arbitrary JSON fields and positive numeric protocol fields without modifying Worker, Broker, service, or HTTP code.

**Tech Stack:** Python 3.10+ standard library and `unittest`.

## Global Constraints

- Do not add dependencies or broaden Plugin, file, network, process, or HTTP authority.
- Preserve V1 message shapes, canonical encoding, line limits, and existing error redaction.
- Follow RED -> GREEN: observe the new regression fail before editing production code.
- Treat Python interpreter integer-conversion limits as an untrusted environmental detail, not as a protocol validation mechanism.

---

### Task 1: Specify the direct-integer failure boundary

**Files:**

- Modify: `tests/test_plugin_worker_protocol.py`
- Inspect: `src/core/contracts/plugin_worker_protocol.py`

**Interfaces:**

- Consumes: `PluginBrokerRequest`, `stable_json_bytes`, `encode_message`, and `decode_message`.
- Produces: a regression proving that `10 ** MAX_PLUGIN_WORKER_INTEGER_DIGITS` is rejected as `PluginWorkerProtocolError`, while `10 ** (MAX_PLUGIN_WORKER_INTEGER_DIGITS - 1)` remains wire-round-trippable.

- [x] **Step 1: Write the failing test**

```python
def test_integer_digit_boundary_is_stable_for_direct_protocol_values(self):
    integer_digits = MAX_PLUGIN_WORKER_INTEGER_DIGITS
    in_limit = 10 ** (integer_digits - 1)
    request = PluginBrokerRequest(
        request_id="request-1",
        call_id="call-1",
        plugin_id="event-logger",
        capability="event.emit",
        arguments={"value": in_limit},
    )
    self.assertEqual(decode_message(encode_message(request)), request)

    overflow = 10 ** integer_digits
    for value in (overflow, -overflow):
        with self.subTest(value_sign="positive" if value > 0 else "negative"):
            with self.assertRaises(PluginWorkerProtocolError):
                stable_json_bytes({"value": value})
            with self.assertRaises(PluginWorkerProtocolError):
                PluginBrokerRequest(
                    request_id="request-1",
                    call_id="call-1",
                    plugin_id="event-logger",
                    capability="event.emit",
                    arguments={"value": value},
                )

    with self.assertRaises(PluginWorkerProtocolError):
        PluginWorkerHello(worker_id="worker-1", pid=overflow)
    with self.assertRaises(PluginWorkerProtocolError):
        PluginLoadSpec(
            entry_point="plugin.py",
            permissions=("event_bus",),
            api_version="1.0.0",
            generation=overflow,
        )
```

- [x] **Step 2: Run the test to verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_protocol.TestPluginWorkerProtocol.test_integer_digit_boundary_is_stable_for_direct_protocol_values -v
```

Observed: FAIL because direct construction and serialization accept the
513-digit value; the independently reproduced 5,001-digit value then reaches
Python's raw `ValueError` during serialization.

### Task 2: Enforce the common protocol integer limit

**Files:**

- Modify: `src/core/contracts/plugin_worker_protocol.py`
- Test: `tests/test_plugin_worker_protocol.py`

**Interfaces:**

- Consumes: all V1 protocol record constructors and `stable_json_bytes()`.
- Produces: `MAX_PLUGIN_WORKER_INTEGER_DIGITS`, plus stable `PluginWorkerProtocolError` rejection before serialization for oversized integers.

- [x] **Step 1: Add the protocol constant and magnitude rule**

```python
MAX_PLUGIN_WORKER_INTEGER_DIGITS = 512
_MAX_PLUGIN_WORKER_INTEGER_MAGNITUDE = 10 ** MAX_PLUGIN_WORKER_INTEGER_DIGITS

def _require_bounded_integer(value: int, path: str) -> None:
    if (
        value >= _MAX_PLUGIN_WORKER_INTEGER_MAGNITUDE
        or value <= -_MAX_PLUGIN_WORKER_INTEGER_MAGNITUDE
    ):
        raise PluginWorkerProtocolError(f"{path} exceeds integer digit limit")
```

- [x] **Step 2: Apply the rule at both validation entry points**

```python
if type(value) is int:
    _require_bounded_integer(value, path)
    return

if type(value) is not int or value < 1:
    raise PluginWorkerProtocolError(f"{field_name} must be a positive integer")
_require_bounded_integer(value, field_name)
```

- [x] **Step 3: Run the focused test to verify GREEN**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_protocol.TestPluginWorkerProtocol.test_integer_digit_boundary_is_stable_for_direct_protocol_values -v
```

Expected: PASS; no raw `ValueError` is observable.

### Task 3: Verify adjacent protocol and Worker behavior

**Files:**

- Inspect: `src/core/contracts/plugin_worker_protocol.py`
- Inspect: `src/adapters/subprocess_plugin_runtime.py`
- Inspect: `src/runtime/plugin_worker.py`

**Interfaces:**

- Consumes: the existing canonical protocol, Worker transport, and broker lifecycle suites.
- Produces: verification evidence that no protocol shape or Worker ownership behavior changed.

- [x] **Step 1: Run focused protocol and Worker suites**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_protocol tests.test_plugin_worker_entrypoint tests.test_subprocess_plugin_runtime -v
```

Observed: 77 tests passed.

- [x] **Step 2: Run repository gates and inspect the final scope**

```powershell
.\venv\Scripts\python.exe tests\run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
cd frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
cd ..
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
git diff --check
```

Observed: aggregate 575 total (573 passed, 2 skipped); full discovery 1514
total (1512 passed, 2 skipped); compileall, Vitest 137, TypeScript, build,
and local integration passed; Playwright passed 7 and skipped 1 by project
condition.
