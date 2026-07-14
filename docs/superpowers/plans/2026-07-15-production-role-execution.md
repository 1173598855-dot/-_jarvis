# Production Role Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute HTTP role dispatches through the service's real Ollama manager instead of returning the deterministic compatibility response.

**Architecture:** Extend the existing `AgentFactory` Ollama injection point and keep role selection, timeout, and history inside the current registry/orchestrator boundary. Both Python application states inject their single manager instance; Express continues to proxy Core unchanged, while standalone factories without a manager retain the compatibility handler.

**Tech Stack:** Python 3 standard library, `requests`, `unittest`, existing Ollama fixture, Python HTTPServer, FastAPI, Express, OpenAPI 3.1.

## Global Constraints

- Do not add a runtime or development dependency.
- Keep `src/` Python-only and do not change public role route shapes or status codes.
- `JARVIS_ROLE_MODEL` is trusted process configuration; HTTP input cannot override it.
- Role `tools` remain prompt metadata and never authorize command, plugin, or network tools.
- Production service states must never use the deterministic compatibility handler.
- Preserve unrelated worktree changes and stage only files owned by each task.

---

## File Map

- Modify `src/core/brain/agent_factory.py`: model configuration, Ollama-backed role handler, stable response validation, corrected semantic role selection call.
- Modify `tests/test_agent_factory.py`: focused injected-manager and selection regressions.
- Modify `src/main.py`: inject its existing manager into the factory.
- Modify `src/main_fastapi.py`: inject its existing manager into the factory.
- Modify `tests/test_main_extended.py`: verify HTTPServer state shares its manager.
- Modify `tests/test_main_fastapi_extended.py`: verify FastAPI state shares its manager.
- Modify `tests/test_api_contract.py`: require fixture content across all three role adapters.
- Modify `README.md`, `docs/SETUP.md`: document `JARVIS_ROLE_MODEL` and real role execution.
- Modify `docs/reports/GITHUB_LEARNING_REPORT.md`: record Phase 3 evidence and no-dependency decision.
- Modify `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/README.md`, `CHANGELOG.md`, `AGENTS.md`: advance authoritative project state to Iteration 126.
- Create `docs/reports/AUDIT_REPORT_126.md`: current delivery evidence.
- Delete `docs/reports/AUDIT_REPORT_116.md`: retain reports 117-126.
- Modify `docs/superpowers/specs/2026-07-15-production-role-execution-design.md`: remove two trailing Markdown spaces reported during the design commit.

---

### Task 1: Ollama-Backed AgentFactory

**Files:**
- Modify: `tests/test_agent_factory.py`
- Modify: `src/core/brain/agent_factory.py`

**Interfaces:**
- Consumes: `OllamaManager.chat(model: str, messages: List[Dict[str, str]], stream: bool = False) -> Dict[str, Any]`.
- Produces: `AgentFactory(..., ollama_manager=None, role_model: Optional[str] = None)` and stable message `Ollama role execution failed` for upstream failures.

- [ ] **Step 1: Write failing injected-manager tests**

Add `Mock` and `patch` imports and a `TestOllamaRoleExecution` test case to `tests/test_agent_factory.py`:

```python
from unittest.mock import Mock, patch


class TestOllamaRoleExecution(unittest.TestCase):
    @staticmethod
    def _response(content="role output"):
        return {
            "model": "fixture-role",
            "message": {"role": "assistant", "content": content},
            "done": True,
        }

    def test_injected_manager_executes_role_with_system_and_user_messages(self):
        manager = Mock()
        manager.chat.return_value = self._response()
        factory = AgentFactory(
            ollama_manager=manager,
            role_model="fixture-role",
        )

        result = factory.dispatch_by_role("engineer", "write a unit test")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "role output")
        model, messages = manager.chat.call_args.args
        self.assertEqual(model, "fixture-role")
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("工程师", messages[0]["content"])
        self.assertEqual(
            messages[1],
            {"role": "user", "content": "write a unit test"},
        )
        self.assertEqual(manager.chat.call_args.kwargs, {"stream": False})

    def test_injected_manager_error_response_is_sanitized(self):
        manager = Mock()
        manager.chat.return_value = {"error": "connection details"}
        factory = AgentFactory(ollama_manager=manager)

        result = factory.dispatch_by_role("engineer", "task")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "Ollama role execution failed")

    def test_injected_manager_blank_content_is_an_error(self):
        manager = Mock()
        manager.chat.return_value = self._response("   ")
        factory = AgentFactory(ollama_manager=manager)

        result = factory.dispatch_by_role("engineer", "task")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "Ollama role execution failed")

    def test_injected_manager_exception_is_sanitized(self):
        manager = Mock()
        manager.chat.side_effect = RuntimeError("socket path and secret")
        factory = AgentFactory(ollama_manager=manager)

        result = factory.dispatch_by_role("engineer", "task")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "Ollama role execution failed")

    def test_role_model_uses_process_configuration(self):
        with patch.dict("os.environ", {"JARVIS_ROLE_MODEL": "configured-role"}):
            factory = AgentFactory()

        self.assertEqual(factory._role_model, "configured-role")

    def test_dispatch_llm_uses_valid_chat_signature(self):
        manager = Mock()
        manager.chat.side_effect = [
            self._response("engineer"),
            self._response("implemented"),
        ]
        factory = AgentFactory(
            ollama_manager=manager,
            role_model="fixture-role",
        )

        result = factory.dispatch_llm("implement feature")

        self.assertEqual(result.role_name, "engineer")
        self.assertEqual(result.message, "implemented")
        first_call = manager.chat.call_args_list[0]
        self.assertEqual(first_call.args[0], "fixture-role")
        self.assertEqual(first_call.args[1][0]["role"], "user")
        self.assertEqual(first_call.kwargs, {"stream": False})
```

Include `TestOllamaRoleExecution` in the file's explicit `run_all_tests()` list.

- [ ] **Step 2: Run the focused tests and verify the red state**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory.TestOllamaRoleExecution -v
```

Expected: failures for the unsupported `role_model` argument and the invalid current `dispatch_llm()` call shape.

- [ ] **Step 3: Implement model configuration and real execution**

Update `src/core/brain/agent_factory.py` with these exact behaviors:

```python
import os


DEFAULT_ROLE_MODEL = "llama3.2"
ROLE_EXECUTION_ERROR = "Ollama role execution failed"


class AgentFactory:
    def __init__(
        self,
        registry=None,
        orchestrator=None,
        ollama_manager=None,
        role_model: Optional[str] = None,
    ):
        self.registry = registry if registry is not None else create_default_registry()
        self.orchestrator = orchestrator or Orchestrator()
        self._ollama_manager = ollama_manager
        configured_model = role_model or os.environ.get(
            "JARVIS_ROLE_MODEL", DEFAULT_ROLE_MODEL
        )
        self._role_model = configured_model.strip() or DEFAULT_ROLE_MODEL
        self._lock = threading.Lock()
```

Add the original task to `AgentTask.metadata`:

```python
metadata={
    "role_name": role_name,
    "capabilities": profile.capabilities,
    "constraints": profile.constraints,
    "tools": profile.tools,
    "task_prompt": task_prompt,
},
```

Replace the static default handler with an instance method that preserves compatibility only when no manager is injected:

```python
def _default_handler(self, profile: AgentProfile):
    if self._ollama_manager is None:
        def compatibility_handler(task: AgentTask) -> str:
            return f"[{profile.display_name}] Task received: {task.prompt[:100]}"

        return compatibility_handler

    def ollama_handler(task: AgentTask) -> str:
        messages = [
            {"role": "system", "content": task.prompt},
            {
                "role": "user",
                "content": str(task.metadata.get("task_prompt", "")),
            },
        ]
        try:
            response = self._ollama_manager.chat(
                self._role_model,
                messages,
                stream=False,
            )
        except Exception:
            logger.warning("Ollama role execution raised for role %s", profile.name)
            raise RuntimeError(ROLE_EXECUTION_ERROR) from None

        if not isinstance(response, dict) or response.get("error"):
            raise RuntimeError(ROLE_EXECUTION_ERROR)
        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(ROLE_EXECUTION_ERROR)
        return content.strip()

    return ollama_handler
```

Correct `dispatch_llm()` to consume the public manager response:

```python
response = self._ollama_manager.chat(
    self._role_model,
    [{"role": "user", "content": prompt}],
    stream=False,
)
message = response.get("message") if isinstance(response, dict) else None
content = message.get("content") if isinstance(message, dict) else ""
if not isinstance(content, str) or not content.strip():
    return self._fallback_dispatch(task_prompt, timeout)
candidate = content.strip().split()[0].strip("[]").lower()
```

- [ ] **Step 4: Run the focused factory suites and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory tests.test_agent_factory_extended -v
```

Expected: all agent factory tests pass; compatibility tests still see the display name, while injected-manager tests see model output.

- [ ] **Step 5: Commit the factory unit**

```powershell
git add -- src/core/brain/agent_factory.py tests/test_agent_factory.py
git diff --cached --check
git commit -m "feat: execute roles through Ollama"
```

### Task 2: Service Injection And Live Contract Evidence

**Files:**
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `tests/test_main_extended.py`
- Modify: `tests/test_main_fastapi_extended.py`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Consumes: `AgentFactory(..., ollama_manager=self.ollama)` from Task 1.
- Produces: real role content through Python HTTPServer, FastAPI, and Express-to-Core without route changes.

- [ ] **Step 1: Write failing application-state and live-contract assertions**

Add these tests to the existing app-state test cases:

```python
def test_agent_factory_uses_application_ollama_manager(self):
    state = AppState()
    try:
        self.assertIs(state.agent_factory._ollama_manager, state.ollama)
    finally:
        state.terminal.close()
```

In `tests/test_api_contract.py`, extend every successful role dispatch assertion inside the existing live harness:

```python
self.assertEqual(body["status"], "success", name)
self.assertEqual(body["message"], "OK", name)
```

For the direct FastAPI response, add:

```python
self.assertEqual(response.json()["status"], "success")
self.assertEqual(response.json()["message"], "OK")
```

- [ ] **Step 2: Run the focused tests and verify the red state**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main_extended.TestAppStateExtended tests.test_main_fastapi_extended.TestAppState tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas -v
```

Expected: app-state identity assertions fail because `_ollama_manager` is `None`; live role dispatch returns the compatibility text instead of `OK`.

- [ ] **Step 3: Inject the shared manager in both services**

Add the same argument to the existing factory construction in `src/main.py` and `src/main_fastapi.py`:

```python
self.agent_factory = AgentFactory(
    registry=self.role_registry,
    orchestrator=self.orchestrator,
    ollama_manager=self.ollama,
)
```

- [ ] **Step 4: Re-run service and live-contract tests**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main_extended.TestAppStateExtended tests.test_main_fastapi_extended.TestAppState tests.test_api_contract -v
```

Expected: all tests pass; all three public adapters return `message: "OK"` from the local fixture.

- [ ] **Step 5: Commit the service integration**

```powershell
git add -- src/main.py src/main_fastapi.py tests/test_main_extended.py tests/test_main_fastapi_extended.py tests/test_api_contract.py
git diff --cached --check
git commit -m "test: prove live role execution across adapters"
```

### Task 3: Configuration And Iteration 126 Ledger

**Files:**
- Modify: `README.md`
- Modify: `docs/SETUP.md`
- Modify: `docs/reports/GITHUB_LEARNING_REPORT.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Create: `docs/reports/AUDIT_REPORT_126.md`
- Delete: `docs/reports/AUDIT_REPORT_116.md`
- Modify: `docs/superpowers/specs/2026-07-15-production-role-execution-design.md`

**Interfaces:**
- Consumes: `JARVIS_ROLE_MODEL`, the focused/full verification outputs, and Task 2 runtime behavior.
- Produces: current Iteration 126 project state with reports 117-126 and no stale deterministic-role risk.

- [ ] **Step 1: Update user-facing configuration**

Document these exact semantics in both startup references:

```text
JARVIS_ROLE_MODEL selects the Ollama model used by role dispatch and defaults to llama3.2.
Role dispatch uses the same OLLAMA_BASE_URL and in-process OllamaManager as chat and token telemetry.
```

- [ ] **Step 2: Record Phase 3 research**

Append an Iteration 126 section to `GITHUB_LEARNING_REPORT.md` recording:

```markdown
## Production role execution (Iteration 126)

Three focused GitHub searches covered multi-agent role execution, local Ollama
agent frameworks, and agent execution policy. Two queries returned no eligible
candidate. The local Ollama query found `kstevica/captain-claw` (161 Stars, MIT,
active on 2026-07-14) and an AGPL candidate that is incompatible with the
project's deployment rule. No dependency was adopted because the repository
already owns the required Ollama client, role registry, orchestrator, fixture,
and cross-adapter harness; adding a framework would duplicate those boundaries.
```

- [ ] **Step 3: Advance authoritative project state**

Update the analysis and ledgers to state that production HTTP role dispatch now uses Ollama, standalone factory compatibility remains deterministic, role tools are still metadata-only, and the next Phase 11 gap is controlled tool-policy execution rather than model execution. Set the current iteration to 126, retain `AUDIT_REPORT_117.md` through `AUDIT_REPORT_126.md`, and use the actual counts from Task 4 without copying historical numbers.

- [ ] **Step 4: Add the audit report and clean the design whitespace**

Create `AUDIT_REPORT_126.md` with sections `Goal`, `Changes`, `Verification`, and `Remaining Work`. Remove only the two trailing spaces after the design document's Iteration and Date metadata lines. Delete `AUDIT_REPORT_116.md` to preserve the ten-report rule.

- [ ] **Step 5: Run documentation regressions**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_readme tests.test_docs_setup tests.test_iteration_ledger -v
```

Expected: all documentation and report-retention tests pass.

- [ ] **Step 6: Commit documentation and ledger files**

```powershell
git add -- README.md docs/SETUP.md docs/reports/GITHUB_LEARNING_REPORT.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md CHANGELOG.md AGENTS.md docs/reports/AUDIT_REPORT_126.md docs/reports/AUDIT_REPORT_116.md docs/superpowers/specs/2026-07-15-production-role-execution-design.md
git diff --cached --check
git commit -m "docs: record production role execution"
```

### Task 4: Full Verification And Evidence Correction

**Files:**
- Modify only if measured results differ: `AGENTS.md`, `CHANGELOG.md`, `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/AUDIT_REPORT_126.md`

**Interfaces:**
- Consumes: all Iteration 126 implementation and documentation.
- Produces: authoritative current test evidence and a clean scoped diff.

- [ ] **Step 1: Run Python focused, aggregate, discovery, and syntax gates**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory tests.test_main_extended tests.test_main_fastapi_extended tests.test_api_contract -v
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

Expected: every command exits 0. Capture the aggregate and discovery counts from command output.

- [ ] **Step 2: Run frontend and browser gates**

```powershell
Set-Location frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
```

Expected: Vitest, Playwright, TypeScript, and production build all exit 0; the desktop-only Playwright item may remain skipped by its project condition.

- [ ] **Step 3: Correct evidence if measured counts changed**

Replace any provisional counts in the four authoritative files with the captured values. Do not alter behavior or weaken a test to preserve an earlier baseline.

- [ ] **Step 4: Run final integrity checks**

```powershell
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors; only intended Iteration 126 files plus pre-existing user changes are present.

- [ ] **Step 5: Commit evidence-only corrections when needed**

```powershell
git add -- AGENTS.md CHANGELOG.md docs/reports/PROJECT_ANALYSIS.md docs/reports/AUDIT_REPORT_126.md
git diff --cached --check
git commit -m "docs: record iteration 126 verification"
```
