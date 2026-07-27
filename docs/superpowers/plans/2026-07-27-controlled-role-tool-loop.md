# Controlled Role Tool Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bounded, replayable Ollama role tool loop that exposes only fixed read-only tools inside the existing terminable RoleWorker process.

**Architecture:** Versioned protocol dataclasses and a dedicated loop engine separate parsing and budgets from `AgentFactory`. A production read-only catalog creates a schema-aware `RoleToolBroker` inside `execute_role_task()`, and the Worker result carries bounded invocation audit records.

**Tech Stack:** Python 3 stdlib dataclasses/JSON/time/platform/shutil, existing requests-based OllamaManager, unittest, existing multiprocessing RoleWorker.

## Global Constraints

- Every model tool request passes through `RoleToolBroker`.
- Production tool execution occurs only inside the existing `RoleWorker` child process.
- Maximum calls, total time, argument bytes, per-result bytes, and cumulative result bytes are all bounded.
- First-party tools are read-only and use trusted paths/base URLs only.
- No command, plugin lifecycle operation, HTTP capability token, or general orchestrator migration.
- Success and denial records are JSON serializable and replayable from the Worker result.

---

### Task 1: Versioned Tool Protocol And Broker Enforcement

**Files:**
- Create: `src/core/contracts/role_tool_protocol.py`
- Modify: `src/core/brain/role_tools.py`
- Modify: `tests/test_role_tools.py`
- Create: `tests/test_role_tool_protocol.py`

**Interfaces:**
- Produces: `RoleToolDefinition`, `RoleToolCall`, `RoleToolResult`, `RoleToolBudget`, `RoleToolInvocation`.
- Produces: `RoleToolBroker.authorized_definitions(profile)`, `RoleToolBroker.invocation_log()`.

- [ ] **Step 1: Write failing protocol tests**

```python
definition = RoleToolDefinition(
    name="repository_metadata",
    description="Read repository state",
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
)
self.assertEqual(definition.to_ollama()["function"]["name"], "repository_metadata")
with self.assertRaises(RoleToolProtocolError):
    RoleToolCall.from_ollama({"function": {"name": "", "arguments": {}}}, 1, 1)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_role_tool_protocol tests.test_role_tools -v`

Expected: import/API failures because the protocol types and Broker methods do not exist.

- [ ] **Step 3: Implement immutable protocol values and strict object-schema validation**

```python
@dataclass(frozen=True, slots=True)
class RoleToolBudget:
    max_calls: int = 5
    max_argument_bytes: int = 8192
    max_result_bytes: int = 16384
    max_total_result_bytes: int = 65536
    max_elapsed_seconds: float = 300.0
```

Implement stable UTF-8 JSON sizing, exact supported JSON types, `required`, `enum`, numeric bounds, string `maxLength`, and `additionalProperties=False`.

- [ ] **Step 4: Extend Broker with definitions, validation, normalized results and bounded invocation audit**

```python
broker = RoleToolBroker(
    policy=policy,
    handlers={definition.name: handler},
    definitions={definition.name: definition},
    budget=budget,
)
```

Preserve the existing authorization decision API and programmatic handler invocation compatibility.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_role_tool_protocol tests.test_role_tools -v`

Expected: all pass.

### Task 2: Dedicated Bounded Loop And AgentFactory Integration

**Files:**
- Create: `src/core/brain/role_tool_loop.py`
- Modify: `src/core/brain/agent_factory.py`
- Replace: `tests/test_role_tool_loop.py`
- Modify: `tests/test_agent_factory.py`

**Interfaces:**
- Consumes: protocol values and Broker definitions/invocation API from Task 1.
- Produces: `RoleToolLoop.run(model, messages, profile, timeout_seconds) -> str`.

- [ ] **Step 1: Replace exploratory tests with failing behavior tests**

```python
first_messages = manager.chat.call_args_list[0].args[1]
self.assertEqual(first_messages, initial_messages)
self.assertEqual(second_messages[-1]["tool_name"], "repository_metadata")
self.assertEqual(manager.chat.call_count, 2)
```

Cover call-count exhaustion as an error, multiple calls counting individually, malformed calls, denial recovery, elapsed time, argument, single output and cumulative output budgets.

- [ ] **Step 2: Run loop and AgentFactory tests and confirm RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_role_tool_loop tests.test_agent_factory.TestOllamaRoleExecution -v`

Expected: failures for mutation, budget handling and Ollama `tool_name` messages.

- [ ] **Step 3: Implement RoleToolLoop**

```python
while True:
    self._check_deadline(started_at)
    response = manager.chat(model, [copy.deepcopy(item) for item in messages], stream=False, tools=tools)
    assistant = self._parse_assistant(response)
    if not assistant.tool_calls:
        return self._require_content(assistant)
    for raw_call in assistant.tool_calls:
        self._consume_call_budget()
        result = self._invoke(profile, raw_call)
        self._consume_output_budget(result)
        messages.append(result.to_ollama_message())
```

- [ ] **Step 4: Delegate AgentFactory role execution to the loop**

Keep prompt construction, error sanitization, role recovery and general dispatch unchanged. Pass the task timeout into direct execution and derive the loop deadline from it.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_role_tool_loop tests.test_agent_factory tests.test_agent_factory_extended -v`

Expected: all pass.

### Task 3: Fixed Read-Only Catalog Inside RoleWorker

**Files:**
- Create: `src/core/brain/read_only_role_tools.py`
- Modify: `src/core/brain/role_registry.py`
- Modify: `src/core/brain/role_worker.py`
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Create: `tests/test_read_only_role_tools.py`
- Modify: `tests/test_role_worker.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi.py`

**Interfaces:**
- Produces: `create_read_only_role_tool_broker(manager, memory_dir, repository_root, role_names, budget)`.
- Worker result adds `tool_audit: list[dict[str, object]]` without changing public dispatch decoding.

- [ ] **Step 1: Write failing catalog and Worker tests**

```python
broker = create_read_only_role_tool_broker(
    manager,
    memory_dir=temp_memory,
    repository_root=repo,
    role_names=["engineer"],
)
self.assertIn("repository_metadata", broker.authorized_tools(engineer))
self.assertNotIn("terminal_executor", broker.authorized_tools(engineer))
```

The real Worker fixture must request one exposed tool, receive its tool result, return final `OK`, and expose one successful `tool_audit` item.

- [ ] **Step 2: Run catalog and Worker tests and confirm RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_read_only_role_tools tests.test_role_worker.TestRoleWorkerSupervisor.test_fixed_role_runner_returns_content_and_parent_token_usage tests.test_role_worker.TestRoleWorkerSupervisor.test_fixed_role_runner_uses_direct_execution_without_transport_timeout -v`

Expected: missing factory/catalog and absent Worker audit.

- [ ] **Step 3: Implement five read-only handlers with strict schemas**

Use `platform`, `os.cpu_count`, `shutil.disk_usage`, `OllamaManager.list_models`, `MemoryStore.load`, and `GitWorkspaceInspector.snapshot`. Redact all returned values and bound lists before returning.

- [ ] **Step 4: Wire trusted roots and Broker in execute_role_task**

```python
broker = create_read_only_role_tool_broker(
    manager,
    memory_dir=trusted_memory_dir,
    repository_root=trusted_repository_root,
    role_names=[profile.name for profile in registry.list_roles()],
)
factory = AgentFactory(registry=registry, ollama_manager=manager, role_model=role_model, role_tool_broker=broker)
```

Return `broker.invocation_log()` next to `dispatch` and `usage`. Main adapters pass resolved trusted roots in `runner_config`; request data cannot override them.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_read_only_role_tools tests.test_role_worker tests.test_main tests.test_main_fastapi -v`

Expected: all pass.

### Task 4: Ollama Contract And Deterministic Fixture

**Files:**
- Modify: `src/core/kernel/ollama_manager.py`
- Modify: `scripts/local_ollama_fixture.py`
- Modify: `tests/test_ollama_manager.py`
- Modify: `tests/test_ollama_manager_extended.py`
- Modify: `tests/test_local_integration_runner.py`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- `OllamaManager.chat(model, messages, stream=False, tools=None)` serializes tools only when supplied.
- Non-stream responses accept valid assistant tool calls without content and reject malformed tool-call shapes.

- [ ] **Step 1: Write failing request and response-contract tests**

```python
manager.chat("fixture", messages, tools=[definition.to_ollama()])
self.assertEqual(manager._post.call_args.args[1]["tools"][0]["type"], "function")
self.assertTrue(manager._is_valid_chat_response(tool_only_response))
self.assertFalse(manager._is_valid_chat_response(malformed_tool_response))
```

- [ ] **Step 2: Run Ollama tests and confirm RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_ollama_manager tests.test_ollama_manager_extended tests.test_local_integration_runner -v`

Expected: malformed tool calls are currently accepted and fixture tool mode is missing.

- [ ] **Step 3: Complete strict serialization/validation and fixture mode**

When non-stream requests contain `tools`, the fixture returns a deterministic call until a `role=tool` message is present, then returns `OK`. Requests without tools retain existing behavior.

- [ ] **Step 4: Run focused and live contract tests and confirm GREEN**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_ollama_manager tests.test_ollama_manager_extended tests.test_local_integration_runner tests.test_api_contract -v`

Expected: all pass.

### Task 5: Suite Registration, Documentation And Verification

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Create: `docs/reports/AUDIT_REPORT_134.md`
- Delete: `docs/reports/AUDIT_REPORT_124.md`
- Modify: `docs/reports/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Aggregate suite discovers every new test case exactly once.
- Documentation records measured current counts rather than copying historical baselines.

- [ ] **Step 1: Add failing aggregate coverage assertions for new modules**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage -v`

Expected: failure until the new suites are imported and registered.

- [ ] **Step 2: Register suites and run Python verification**

Run:

```powershell
.\venv\Scripts\python.exe tests\run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

- [ ] **Step 3: Run frontend and integration verification**

Run:

```powershell
Set-Location frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
git diff --check
```

- [ ] **Step 4: Update Iteration 134 ledgers with measured results**

Mark Stage C delivered only if all exit gates are evidenced. Roll the audit window to 125-134 and remove stale claims that task persistence remains unfinished.

- [ ] **Step 5: Review the complete diff and create scoped commits**

Commit protocol/loop, Worker catalog, fixture/tests, and documentation as reviewable units without staging unrelated user changes.
