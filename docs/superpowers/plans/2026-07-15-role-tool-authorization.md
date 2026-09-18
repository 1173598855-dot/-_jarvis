# Role Tool Authorization Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-deny, auditable role-tool broker and ensure role prompts expose only explicitly granted, declared, and registered tools.

**Architecture:** A new standard-library `role_tools.py` module owns policy evaluation, registered handlers, the invocation choke point, and bounded audit history. `AgentFactory` injects an empty broker by default, resolves authorized tools once per dispatch, and keeps declared and authorized tool metadata separate.

**Tech Stack:** Python 3.11+, dataclasses, threading, collections.deque, unittest

---

### Task 1: Default-Deny Role Tool Broker

**Files:**
- Create: `src/core/brain/role_tools.py`
- Create: `tests/test_role_tools.py`

- [ ] **Step 1: Write failing broker tests**

Create `tests/test_role_tools.py` with tests that exercise real policy and broker
objects rather than mocks:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.role_registry import AgentProfile
from core.brain.role_tools import (
    RoleToolBroker,
    RoleToolDeniedError,
    RoleToolPolicy,
)


class TestRoleToolBroker(unittest.TestCase):
    def setUp(self):
        self.profile = AgentProfile(
            name="engineer",
            display_name="Engineer",
            description="Implements tested changes.",
            tools=["terminal_executor", "plugin_sdk", "terminal_executor"],
        )

    def test_default_policy_denies_before_handler_execution(self):
        calls = []
        broker = RoleToolBroker(
            handlers={"terminal_executor": lambda arguments: calls.append(arguments)}
        )

        self.assertEqual(broker.authorized_tools(self.profile), [])
        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(self.profile, "terminal_executor", {"command": "pwd"})

        self.assertEqual(calls, [])
        self.assertEqual(broker.audit_log()[-1].reason, "tool_not_granted")

    def test_authorization_requires_declaration_grant_and_registration(self):
        broker = RoleToolBroker(
            policy=RoleToolPolicy(
                {"engineer": ["terminal_executor", "missing_tool"]}
            ),
            handlers={"terminal_executor": lambda arguments: arguments["command"]},
        )

        self.assertEqual(broker.authorized_tools(self.profile), ["terminal_executor"])
        self.assertEqual(
            broker.invoke(self.profile, "terminal_executor", {"command": "pwd"}),
            "pwd",
        )
        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(self.profile, "missing_tool")
        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(self.profile, "plugin_sdk")

        reasons = [decision.reason for decision in broker.audit_log()]
        self.assertIn("allowed", reasons)
        self.assertIn("tool_not_declared", reasons)
        self.assertIn("tool_not_granted", reasons)

    def test_registered_handler_is_still_denied_when_not_declared(self):
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": ["security_auditor"]}),
            handlers={"security_auditor": lambda arguments: "ran"},
        )

        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(self.profile, "security_auditor")

        self.assertEqual(broker.audit_log()[-1].reason, "tool_not_declared")

    def test_granted_but_unregistered_tool_is_denied(self):
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": ["plugin_sdk"]})
        )

        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(self.profile, "plugin_sdk")

        self.assertEqual(broker.audit_log()[-1].reason, "tool_not_registered")

    def test_audit_history_is_bounded_and_returned_as_a_copy(self):
        broker = RoleToolBroker(audit_limit=2)

        for tool_name in ("one", "two", "three"):
            with self.assertRaises(RoleToolDeniedError):
                broker.invoke(self.profile, tool_name)

        first_snapshot = broker.audit_log()
        self.assertEqual([item.tool_name for item in first_snapshot], ["two", "three"])
        first_snapshot.clear()
        self.assertEqual(len(broker.audit_log()), 2)

    def test_invalid_policy_and_broker_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            RoleToolPolicy({"engineer": [""]})
        with self.assertRaises(ValueError):
            RoleToolBroker(audit_limit=0)
        with self.assertRaises(ValueError):
            RoleToolBroker(handlers={"terminal_executor": "not callable"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm red**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_tools -v
```

Expected: import fails because `core.brain.role_tools` does not exist.

- [ ] **Step 3: Implement the minimal policy and broker**

Create `src/core/brain/role_tools.py`:

```python
"""Default-deny authorization and invocation boundary for role tools."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from .role_registry import AgentProfile

ToolHandler = Callable[[dict[str, Any]], Any]


class RoleToolDeniedError(PermissionError):
    """Raised when a role tool call cannot pass the broker policy."""


@dataclass(frozen=True)
class RoleToolDecision:
    role_name: str
    tool_name: str
    allowed: bool
    reason: str


class RoleToolPolicy:
    """Immutable explicit grants keyed by resolved role name."""

    def __init__(
        self,
        grants: Optional[Mapping[str, Iterable[str]]] = None,
    ) -> None:
        normalized: dict[str, frozenset[str]] = {}
        for role_name, tools in (grants or {}).items():
            if not isinstance(role_name, str) or not role_name:
                raise ValueError("Role tool policy names must be non-empty strings")
            tool_set = frozenset(tools)
            if any(not isinstance(tool, str) or not tool for tool in tool_set):
                raise ValueError("Role tool grants must be non-empty strings")
            normalized[role_name] = tool_set
        self._grants = normalized

    def is_granted(self, role_name: str, tool_name: str) -> bool:
        return tool_name in self._grants.get(role_name, frozenset())


class RoleToolBroker:
    """Authorize every role tool call before invoking a registered handler."""

    def __init__(
        self,
        policy: Optional[RoleToolPolicy] = None,
        handlers: Optional[Mapping[str, ToolHandler]] = None,
        audit_limit: int = 256,
    ) -> None:
        if type(audit_limit) is not int or audit_limit < 1:
            raise ValueError("Role tool audit limit must be a positive integer")
        registered = dict(handlers or {})
        if any(
            not isinstance(name, str) or not name or not callable(handler)
            for name, handler in registered.items()
        ):
            raise ValueError("Role tool handlers require non-empty names and callables")
        self._policy = policy or RoleToolPolicy()
        self._handlers = registered
        self._audit = deque(maxlen=audit_limit)
        self._lock = threading.Lock()

    def authorized_tools(self, profile: AgentProfile) -> list[str]:
        authorized = []
        for tool_name in dict.fromkeys(profile.tools):
            decision = self._decide(profile, tool_name)
            if decision.allowed:
                authorized.append(tool_name)
        return authorized

    def invoke(
        self,
        profile: AgentProfile,
        tool_name: str,
        arguments: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        if not isinstance(tool_name, str) or not tool_name:
            raise RoleToolDeniedError("Role tool call denied: invalid tool name")
        if arguments is not None and not isinstance(arguments, Mapping):
            raise RoleToolDeniedError("Role tool call denied: invalid arguments")
        decision = self._decide(profile, tool_name)
        if not decision.allowed:
            raise RoleToolDeniedError(
                f"Role tool call denied: {decision.reason}"
            )
        return self._handlers[tool_name](dict(arguments or {}))

    def audit_log(self) -> list[RoleToolDecision]:
        with self._lock:
            return list(self._audit)

    def _decide(
        self,
        profile: AgentProfile,
        tool_name: str,
    ) -> RoleToolDecision:
        if tool_name not in profile.tools:
            reason = "tool_not_declared"
        elif not self._policy.is_granted(profile.name, tool_name):
            reason = "tool_not_granted"
        elif tool_name not in self._handlers:
            reason = "tool_not_registered"
        else:
            reason = "allowed"
        decision = RoleToolDecision(
            role_name=profile.name,
            tool_name=tool_name,
            allowed=reason == "allowed",
            reason=reason,
        )
        with self._lock:
            self._audit.append(decision)
        return decision
```

- [ ] **Step 4: Run broker tests and confirm green**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_tools -v
```

Expected: all broker tests pass with no handler call on denied paths.

- [ ] **Step 5: Commit the broker**

Stage only the new broker and its tests, run `git diff --cached --check`, then
commit:

```powershell
git commit -m "feat: add default-deny role tool broker"
```

### Task 2: AgentFactory Authorization Integration

**Files:**
- Modify: `src/core/brain/agent_factory.py`
- Modify: `tests/test_agent_factory.py`

- [ ] **Step 1: Write failing factory authorization tests**

Update the existing Ollama prompt assertion to require `[TOOL ACCESS] disabled`
and reject `[AVAILABLE TOOLS]`. Add a test with an explicitly configured broker:

```python
from core.brain.role_tools import RoleToolBroker, RoleToolPolicy


def test_injected_broker_exposes_only_authorized_registered_tools(self):
    manager = Mock()
    manager.chat.return_value = self._response()
    broker = RoleToolBroker(
        policy=RoleToolPolicy({"engineer": ["terminal_executor", "plugin_sdk"]}),
        handlers={"terminal_executor": lambda arguments: arguments},
    )
    factory = AgentFactory(ollama_manager=manager, role_tool_broker=broker)
    captured_tasks = []
    original_dispatch = factory.orchestrator.dispatch

    def capture(task):
        captured_tasks.append(task)
        return original_dispatch(task)

    with patch.object(factory.orchestrator, "dispatch", side_effect=capture):
        result = factory.dispatch_by_role("engineer", "inspect the workspace")

    self.assertEqual(result.status, "success")
    system_prompt = manager.chat.call_args.args[1][0]["content"]
    self.assertIn("[AUTHORIZED TOOLS] terminal_executor", system_prompt)
    self.assertNotIn("plugin_sdk", system_prompt)
    self.assertEqual(
        captured_tasks[0].metadata["declared_tools"],
        ["orchestrator", "terminal_executor", "plugin_sdk"],
    )
    self.assertEqual(
        captured_tasks[0].metadata["authorized_tools"],
        ["terminal_executor"],
    )
    self.assertNotIn("tools", captured_tasks[0].metadata)
```

Change `test_build_prompt_with_tools` so a profile declaration alone produces
`[TOOL ACCESS] disabled` and never produces `[AVAILABLE TOOLS]`.

- [ ] **Step 2: Run focused factory tests and confirm red**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory -v
```

Expected: `AgentFactory` rejects `role_tool_broker`, and old prompts still claim
all declared tools are available.

- [ ] **Step 3: Inject the broker and separate metadata**

In `src/core/brain/agent_factory.py`, import `RoleToolBroker`, accept
`role_tool_broker=None` in `__init__`, and set:

```python
self._role_tool_broker = role_tool_broker or RoleToolBroker()
```

In `dispatch_by_role`, resolve authorization before building prompts:

```python
authorized_tools = self._role_tool_broker.authorized_tools(profile)
system_prompt = profile.resolve_prompt(task_prompt)
full_prompt = self._build_full_prompt(
    profile,
    task_prompt,
    system_prompt,
    authorized_tools=authorized_tools,
)
```

Replace task metadata key `tools` with:

```python
"declared_tools": list(profile.tools),
"authorized_tools": authorized_tools,
```

Change the Ollama handler to pass the already-resolved metadata list:

```python
"content": self._build_system_prompt(
    profile,
    authorized_tools=list(task.metadata.get("authorized_tools", [])),
),
```

- [ ] **Step 4: Make prompt construction fail closed**

Add optional `authorized_tools` parameters to `_build_full_prompt` and
`_build_system_prompt`. When the argument is `None`, resolve through the broker;
when it is empty, emit the disabled marker:

```python
def _append_tool_access(
    self,
    parts: List[str],
    profile: AgentProfile,
    authorized_tools: Optional[List[str]],
) -> None:
    resolved = (
        self._role_tool_broker.authorized_tools(profile)
        if authorized_tools is None
        else authorized_tools
    )
    if resolved:
        parts.append(f"[AUTHORIZED TOOLS] {chr(44).join(resolved)}")
    else:
        parts.append("[TOOL ACCESS] disabled")
```

Use this helper from both prompt builders and remove both `[AVAILABLE TOOLS]`
branches.

- [ ] **Step 5: Run factory and broker regressions**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_tools tests.test_agent_factory tests.test_agent_factory_extended -v
```

Expected: all tests pass; default prompts expose no role tools, and an injected
broker exposes only the authorized subset.

- [ ] **Step 6: Commit the factory integration**

Stage `agent_factory.py` and `test_agent_factory.py`, run
`git diff --cached --check`, then commit:

```powershell
git commit -m "feat: enforce role tool authorization in prompts"
```

### Task 3: Iteration 128 Evidence And Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/SETUP.md`
- Modify: `docs/reports/GITHUB_LEARNING_REPORT.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_128.md`
- Delete: `docs/reports/AUDIT_REPORT_118.md`

- [ ] **Step 1: Record Phase 3 and the bridge decision**

Record the three searches, exact candidate metadata, the no-dependency decision,
and this bridge analysis:

| Priority | Requirement | Skill / evidence | Decision |
|---|---|---|---|
| P0 | Prevent profile declarations from becoming ambient authority | TDD + secure-by-default Python review | Add a fail-closed broker and prompt filtering |
| P1 | Execute approved read-only role tools | Existing TerminalWorker capability | Defer automatic model tool calls until broker enforcement exists |
| P1 | Terminate timed-out role work | Existing worker-process pattern | Keep timeout isolation as later Phase 11 work |

- [ ] **Step 2: Advance the project ledger**

Add Iteration 128 to `CHANGELOG.md` and `PROJECT_ANALYSIS.md`; update `AGENTS.md`
and the report index; add `AUDIT_REPORT_128.md`; remove `AUDIT_REPORT_118.md` so
exactly reports 119-128 remain. Update user documentation to state that role
tools are default-deny and no automatic model-driven invocation exists yet.

- [ ] **Step 3: Run focused security and documentation checks**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_tools tests.test_agent_factory tests.test_agent_factory_extended -v
.\venv\Scripts\python.exe -m unittest tests.test_readme tests.test_docs_setup tests.test_iteration_ledger -v
```

Expected: both commands exit 0.

- [ ] **Step 4: Run complete Python gates**

Run:

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

Record the measured totals rather than copying Iteration 127 counts.

- [ ] **Step 5: Run frontend gates**

From `frontend/`, run:

```powershell
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
```

Expected: all commands exit 0; the desktop-only mobile-navigation test may remain
skipped by its project condition.

- [ ] **Step 6: Run final integrity checks**

Run `git diff --check`, confirm exactly ten audit reports 119-128, inspect
`git status --short`, and verify that unrelated pre-existing worktree changes
remain intact.
