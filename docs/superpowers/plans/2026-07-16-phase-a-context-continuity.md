# Phase A Context Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase A2–A6 so an interrupted J.A.R.V.I.S. run can persist authenticated state, detect context watermarks and workspace drift, and restart with one concrete next action.

**Architecture:** Stable state and budget data structures live in `core/contracts`; policy lives in `core/brain`; redaction lives in `core/kernel`; filesystem and Git access live in `adapters`; startup coordination lives in `app`. FastAPI only composes and invokes the lifecycle coordinator, while the standard-library service remains unchanged until a separate compatibility adapter is justified.

**Tech Stack:** Python 3.10+ standard library (`dataclasses`, `enum`, `hashlib`, `hmac`, `json`, `os`, `pathlib`, `subprocess`), FastAPI lifespan, `unittest`, existing repository test runner.

## Global Constraints

- `.auto-memory/` stores only unfinished runtime state and remains Git-ignored.
- Schema version is exactly `1`; every persisted state uses a monotonically increasing positive `revision`.
- Watermarks are Green `< 0.65`, Amber `0.65–<0.80`, Orange `0.80–<0.90`, and Red `>= 0.90`.
- A `next_action` is mandatory and cannot be a generic phrase such as `continue`, `继续`, or `继续开发`.
- Integrity uses HMAC-SHA256 with key material supplied from outside `.auto-memory/`; an active state without a usable key fails closed.
- All writes use a same-directory temporary file, flush, `fsync`, `os.replace`, and read-back verification.
- Secret-bearing keys and bearer/token/password patterns are redacted before any recovery, event, decision, or verification record is written.
- Git inspection uses fixed argument arrays with `shell=False`; recovery text is never executed as a command.
- Unknown or dirty user work is preserved. Recovery may inspect it, but must not reset, clean, overwrite, or stage it implicitly.
- New behavior follows red-green-refactor and receives focused tests before implementation.
- Stage commits use exact pathspecs; push, merge, release, deployment, new L3 permissions, and irreversible migration remain outside this plan.

---

### Task 1: A2 Versioned Run-State Contracts

**Files:**
- Create: `src/core/contracts/__init__.py`
- Create: `src/core/contracts/run_state.py`
- Create: `tests/test_run_state.py`

**Interfaces:**
- Produces: `RunStatus`, `ContextLevel`, `StageState`, `WorkPackageState`, and `RunState`.
- Produces: `RunState.new`, `RunState.evolve`, `RunState.to_dict`, and `RunState.from_dict`.
- Consumes: only Python standard-library types.

- [ ] **Step 1: Write failing schema tests**

```python
from dataclasses import replace
import unittest

from core.contracts.run_state import (
    ContextLevel,
    RunState,
    RunStatus,
    StageState,
    WorkPackageState,
)


class TestRunState(unittest.TestCase):
    def test_round_trip_preserves_nested_state(self):
        stage = StageState(
            stage_id="A",
            objective="Context continuity",
            status=RunStatus.RUNNING,
            acceptance_criteria=("restart has one next action",),
        )
        package = WorkPackageState(
            work_package_id="A2",
            objective="Define state contracts",
            status=RunStatus.RUNNING,
            allowed_paths=("src/core/contracts/",),
            acceptance_commands=(
                r".\venv\Scripts\python.exe -m unittest tests.test_run_state",
            ),
            next_action="Implement RunState serialization",
        )
        state = RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Implement RunState serialization",
            stages=(stage,),
            work_packages=(package,),
        )

        restored = RunState.from_dict(state.to_dict())

        self.assertEqual(restored, state)
        self.assertEqual(restored.schema_version, 1)

    def test_generic_next_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "next_action"):
            RunState.new(
                run_id="run-20260716-043000",
                goal="Complete Phase A",
                current_stage="A",
                base_commit="a" * 40,
                active_branch="codex/iteration-101-core-contracts",
                next_action="继续开发",
            )

    def test_evolve_increments_revision_and_rejects_revision_regression(self):
        state = RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Write state contract tests",
        )

        evolved = state.evolve(
            status=RunStatus.VERIFYING,
            context_level=ContextLevel.AMBER,
            next_action="Run focused state contract tests",
        )

        self.assertEqual(evolved.revision, state.revision + 1)
        with self.assertRaisesRegex(ValueError, "revision"):
            replace(evolved, revision=state.revision)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_run_state -v`

Expected: import failure for `core.contracts.run_state`.

- [ ] **Step 3: Implement immutable, strict contracts**

`src/core/contracts/run_state.py` must define the following public shape and validate all non-empty identifiers, the 40-hex `base_commit`, timezone-aware ISO `updated_at`, unique stage/work-package IDs, supported enum values, and exact schema version:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1
_GENERIC_ACTIONS = {"continue", "continue development", "继续", "继续开发"}
_RUN_ID = re.compile(r"^run-[0-9]{8}-[0-9]{6}(?:-[a-z0-9]{4,12})?$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class RunStatus(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    VERIFYING = "verifying"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    UNKNOWN = "unknown"
    PARTIAL = "partial"


class ContextLevel(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    ORANGE = "orange"
    RED = "red"


@dataclass(frozen=True, slots=True)
class StageState:
    stage_id: str
    objective: str
    status: RunStatus
    acceptance_criteria: tuple[str, ...] = ()
    completed_work_packages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkPackageState:
    work_package_id: str
    objective: str
    status: RunStatus
    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    acceptance_commands: tuple[str, ...] = ()
    handoff_path: str | None = None
    next_action: str | None = None


@dataclass(frozen=True, slots=True)
class RunState:
    schema_version: int
    run_id: str
    revision: int
    updated_at: str
    goal: str
    current_stage: str
    status: RunStatus
    base_commit: str
    active_branch: str
    context_level: ContextLevel
    next_action: str
    next_command: str | None = None
    stages: tuple[StageState, ...] = ()
    work_packages: tuple[WorkPackageState, ...] = ()

```

Add a `new` classmethod with keyword-only arguments shown by the test and defaults of revision `1`, UTC `updated_at`, `RunStatus.PLANNING`, and `ContextLevel.GREEN`. Add `evolve(**changes)` using `dataclasses.replace` while forcing `revision + 1` and a fresh UTC timestamp. Add `to_dict()` with enum values and nested tuples serialized as JSON arrays. Add `from_dict(value)` that reconstructs nested dataclasses and rejects missing or unknown top-level fields instead of silently accepting a damaged/newer schema. `src/core/contracts/__init__.py` re-exports these five types.

- [ ] **Step 4: Verify GREEN and regression scope**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_run_state -v`

Expected: all `TestRunState` tests pass.

Run: `\.\venv\Scripts\python.exe -m compileall -q src/core/contracts tests/test_run_state.py`

Expected: exit code `0`.

- [ ] **Step 5: Commit the stable A2 contract**

```powershell
git add -- src/core/contracts/__init__.py src/core/contracts/run_state.py tests/test_run_state.py
git diff --cached --check
git commit -m "feat: define recoverable run state contracts"
```

---

### Task 2: A3 Context Budget Provider and Watermark Events

**Files:**
- Create: `src/core/contracts/context_budget.py`
- Modify: `src/core/contracts/__init__.py`
- Create: `src/core/brain/context_budget.py`
- Create: `tests/test_context_budget.py`

**Interfaces:**
- Produces: `ContextBudgetSnapshot`, `ContextBudgetProvider`, and `ContextWatermarkChanged` contracts.
- Produces: `FallbackContextBudgetProvider.snapshot()` and `ContextBudgetMonitor.observe()`.
- Consumes: `ContextLevel` from Task 1.

- [ ] **Step 1: Write failing boundary and event tests**

```python
import unittest

from core.brain.context_budget import ContextBudgetMonitor, FallbackContextBudgetProvider
from core.contracts.run_state import ContextLevel


class TestContextBudgetMonitor(unittest.TestCase):
    def test_exact_boundaries_map_to_expected_levels(self):
        monitor = ContextBudgetMonitor()
        cases = ((64, ContextLevel.GREEN), (65, ContextLevel.AMBER),
                 (80, ContextLevel.ORANGE), (90, ContextLevel.RED))
        for used, expected in cases:
            snapshot = FallbackContextBudgetProvider(
                total_tokens=100,
                estimate=lambda: used,
            ).snapshot()
            self.assertEqual(monitor.level_for(snapshot), expected)

    def test_observe_emits_only_when_level_changes(self):
        monitor = ContextBudgetMonitor()
        green = FallbackContextBudgetProvider(100, lambda: 10).snapshot()
        red = FallbackContextBudgetProvider(100, lambda: 95).snapshot()

        self.assertIsNone(monitor.observe(green))
        event = monitor.observe(red)
        self.assertEqual(event.previous, ContextLevel.GREEN)
        self.assertEqual(event.current, ContextLevel.RED)
        self.assertIsNone(monitor.observe(red))

    def test_invalid_usage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "total_tokens"):
            FallbackContextBudgetProvider(0, lambda: 1).snapshot()
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_context_budget -v`

Expected: import failure for `core.brain.context_budget`.

- [ ] **Step 3: Implement provider and monitor**

`src/core/contracts/context_budget.py`:

```python
from dataclasses import dataclass
from typing import Protocol

from core.contracts.run_state import ContextLevel


@dataclass(frozen=True, slots=True)
class ContextBudgetSnapshot:
    used_tokens: int
    total_tokens: int
    source: str

    @property
    def usage_ratio(self) -> float:
        return self.used_tokens / self.total_tokens


class ContextBudgetProvider(Protocol):
    def snapshot(self) -> ContextBudgetSnapshot: ...


@dataclass(frozen=True, slots=True)
class ContextWatermarkChanged:
    previous: ContextLevel
    current: ContextLevel
    snapshot: ContextBudgetSnapshot
```

`src/core/brain/context_budget.py` must validate thresholds and token counts, clamp a fallback estimate above the configured total to the total, prefer an injected runtime reader when it returns a valid `(used, total)` pair, and emit an event only when the level changes. The initial Green observation establishes state without emitting an event; an initial Amber/Orange/Red observation emits from Green.

- [ ] **Step 4: Verify GREEN**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_context_budget -v`

Expected: boundary, event, runtime-reader, fallback, and validation tests pass.

- [ ] **Step 5: Commit the stable A3 unit**

```powershell
git add -- src/core/contracts/context_budget.py src/core/contracts/__init__.py src/core/brain/context_budget.py tests/test_context_budget.py
git diff --cached --check
git commit -m "feat: monitor context budget watermarks"
```

---

### Task 3: A4 Secret Redaction and Deterministic Resume Documents

**Files:**
- Create: `src/core/kernel/secret_redaction.py`
- Create: `src/core/brain/resume_document.py`
- Create: `tests/test_resume_document.py`

**Interfaces:**
- Produces: `redact_text(text: str) -> str` and `redact_value(value: object, key: str | None = None) -> object`.
- Produces: `ResumeSections` and `render_resume_document(state, sections) -> str`.
- Consumes: `RunState` from Task 1.

- [ ] **Step 1: Write failing privacy and layout tests**

```python
import unittest

from core.brain.resume_document import ResumeSections, render_resume_document
from core.contracts.run_state import RunState
from core.kernel.secret_redaction import redact_text, redact_value


class TestResumeDocument(unittest.TestCase):
    def test_redaction_masks_structured_and_free_text_secrets(self):
        self.assertEqual(redact_value("abc", key="api_token"), "[REDACTED]")
        text = redact_text("Authorization: Bearer secret-value password=hunter2")
        self.assertNotIn("secret-value", text)
        self.assertNotIn("hunter2", text)

    def test_resume_has_machine_header_and_all_fixed_sections(self):
        state = RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Run focused recovery tests",
        )
        document = render_resume_document(
            state,
            ResumeSections(
                confirmed_decisions=("Keep local-first behavior",),
                risks=("token=must-not-leak",),
            ),
        )

        for heading in (
            "## Current Goal", "## Confirmed Decisions", "## Completed Work",
            "## Files and Git State", "## Verification", "## Agent State",
            "## Downloaded Resources", "## Risks and Approvals",
            "## Next Step", "## Do Not Repeat",
        ):
            self.assertIn(heading, document)
        self.assertIn("schema_version: 1", document)
        self.assertNotIn("must-not-leak", document)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_resume_document -v`

Expected: import failure for `core.brain.resume_document`.

- [ ] **Step 3: Implement redaction and rendering**

`secret_redaction.py` must recursively redact mapping values whose normalized key contains `authorization`, `api_key`, `apikey`, `password`, `passwd`, `secret`, `token`, `private_key`, or `cookie`. `redact_text` must mask bearer credentials and `key=value`/`key: value` secret patterns without changing ordinary `run_id`, `trace_id`, or `work_package_id` text.

`resume_document.py` must define:

```python
@dataclass(frozen=True, slots=True)
class ResumeSections:
    confirmed_decisions: tuple[str, ...] = ()
    completed_work: tuple[str, ...] = ()
    files_and_git_state: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    agent_state: tuple[str, ...] = ()
    downloaded_resources: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    do_not_repeat: tuple[str, ...] = ()


```

Implement `render_resume_document(state: RunState, sections: ResumeSections) -> str`. The renderer emits the exact machine-readable fields from Appendix A first, then the ten fixed headings in the tested order. Empty sections contain `- None recorded.`. All interpolated content passes through `redact_text`.

- [ ] **Step 4: Verify GREEN and deterministic output**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_resume_document -v`

Expected: all privacy and document-layout tests pass and two renders of identical input are byte-identical.

- [ ] **Step 5: Commit the stable A4 document unit**

```powershell
git add -- src/core/kernel/secret_redaction.py src/core/brain/resume_document.py tests/test_resume_document.py
git diff --cached --check
git commit -m "feat: render redacted recovery documents"
```

---

### Task 4: A4 Atomic Authenticated Run-State Repository

**Files:**
- Create: `src/adapters/__init__.py`
- Create: `src/adapters/file_run_state_repository.py`
- Create: `tests/test_file_run_state_repository.py`

**Interfaces:**
- Produces: `RunStateIntegrityError`, `StoredRunState`, and `FileRunStateRepository`.
- Produces: `save`, `load_active`, and `archive_active`.
- Consumes: Task 1 contracts, Task 3 redaction and resume rendering.

- [ ] **Step 1: Write failing atomicity, integrity, and path tests**

```python
import tempfile
import unittest
from pathlib import Path

from adapters.file_run_state_repository import (
    FileRunStateRepository,
    RunStateIntegrityError,
)
from core.contracts.run_state import RunState


class TestFileRunStateRepository(unittest.TestCase):
    def make_state(self):
        return RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Verify atomic state persistence",
        )

    def test_save_and_load_verify_authenticated_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = FileRunStateRepository(Path(tmp), key_provider=lambda: b"k" * 32)
            state = self.make_state()
            repo.save(state, "schema_version: 1\n", events=({"type": "started"},))

            stored = repo.load_active()

            self.assertEqual(stored.state, state)
            self.assertIn("schema_version: 1", stored.resume_markdown)
            self.assertFalse(list(Path(tmp).rglob("*.tmp")))

    def test_tampered_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = FileRunStateRepository(root, key_provider=lambda: b"k" * 32)
            repo.save(self.make_state(), "schema_version: 1\n")
            state_path = root / "runs" / "run-20260716-043000" / "state.json"
            state_path.write_text("{}", encoding="utf-8")

            with self.assertRaises(RunStateIntegrityError):
                repo.load_active()

    def test_missing_key_for_active_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            FileRunStateRepository(root, lambda: b"k" * 32).save(
                self.make_state(), "schema_version: 1\n"
            )
            with self.assertRaisesRegex(RunStateIntegrityError, "key"):
                FileRunStateRepository(root, lambda: None).load_active()
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_file_run_state_repository -v`

Expected: import failure for `adapters.file_run_state_repository`.

- [ ] **Step 3: Implement the file repository**

`FileRunStateRepository` accepts `root: Path` and `key_provider: Callable[[], bytes | None]`. Its `save` method accepts `state: RunState`, `resume_markdown: str`, keyword-only iterables `events` and `decisions`, plus optional `artifacts` and `verification` mappings. `load_active() -> StoredRunState | None` returns `None` only when `active-run.json` does not exist. `archive_active(expected_run_id: str) -> None` removes only the matching active pointer after integrity verification and leaves the run directory as historical recovery evidence.

The repository resolves every target below `root`, rejects symlink/reparse escape candidates, writes `state.json`, `resume.md`, `decisions.jsonl`, `events.jsonl`, `artifacts.json`, and `verification.json`, then writes `active-run.json` last. The manifest records relative paths, SHA-256 digests, schema version, run ID, revision, and HMAC-SHA256 over canonical compact JSON. `load_active` checks schema, canonical containment, all digests, HMAC with `hmac.compare_digest`, matching run IDs, and matching revisions before parsing `RunState`. JSONL appends are rewritten atomically so a crash cannot leave a partial final line. The key is never serialized.

- [ ] **Step 4: Verify GREEN, corruption cases, and cleanup**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_file_run_state_repository -v`

Expected: round-trip, tampering, missing key, revision mismatch, path escape, redaction, append, and simulated replace-failure tests pass; no `.tmp` files remain after successful writes.

- [ ] **Step 5: Commit the stable A4 repository unit**

```powershell
git add -- src/adapters/__init__.py src/adapters/file_run_state_repository.py tests/test_file_run_state_repository.py
git diff --cached --check
git commit -m "feat: persist authenticated run recovery state"
```

---

### Task 5: A5 Git Drift and Crash Recovery Coordinator

**Files:**
- Create: `src/adapters/git_workspace.py`
- Create: `src/app/__init__.py`
- Create: `src/app/run_lifecycle.py`
- Create: `tests/test_run_lifecycle.py`

**Interfaces:**
- Produces: `WorkspaceSnapshot`, `GitWorkspaceInspector.snapshot()`.
- Produces: `RecoveryOutcome`, `RunLifecycleCoordinator.start_run()`, `checkpoint()`, `recover_active()`, and `handle_context_event()`.
- Consumes: Tasks 1–4.

- [ ] **Step 1: Write failing recovery-priority tests**

```python
import tempfile
import unittest
from pathlib import Path

from adapters.file_run_state_repository import FileRunStateRepository
from adapters.git_workspace import WorkspaceSnapshot
from app.run_lifecycle import RunLifecycleCoordinator
from core.brain.resume_document import ResumeSections
from core.contracts.context_budget import ContextBudgetSnapshot, ContextWatermarkChanged
from core.contracts.run_state import ContextLevel, RunState, RunStatus, WorkPackageState


class FakeGit:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class TestRunLifecycleCoordinator(unittest.TestCase):
    def test_running_state_becomes_unknown_after_restart(self):
        outcome = self._recover(status=RunStatus.RUNNING)
        self.assertEqual(outcome.state.status, RunStatus.UNKNOWN)
        self.assertIn("Confirm terminated workers", outcome.state.next_action)

    def test_dirty_workspace_has_one_preservation_action(self):
        outcome = self._recover(dirty_paths=("src/main_fastapi.py",))
        self.assertEqual(
            outcome.state.next_action,
            "Preserve and review 1 uncommitted path before resuming A2",
        )

    def test_partial_package_resumes_exact_handoff(self):
        package = WorkPackageState(
            work_package_id="A4",
            objective="Persist recovery state",
            status=RunStatus.PARTIAL,
            handoff_path=".auto-memory/runs/run-20260716-043000/agents/a4.md",
            next_action="Finish atomic replacement test",
        )
        outcome = self._recover(work_packages=(package,))
        self.assertIn("A4", outcome.state.next_action)
        self.assertIn("agents/a4.md", outcome.state.next_action)

    def test_red_watermark_overrides_dispatch_and_persists_checkpoint(self):
        coordinator, _ = self._coordinator()
        event = ContextWatermarkChanged(
            ContextLevel.ORANGE,
            ContextLevel.RED,
            ContextBudgetSnapshot(95, 100, "runtime"),
        )
        outcome = coordinator.handle_context_event(event)
        self.assertEqual(outcome.state.context_level, ContextLevel.RED)
        self.assertEqual(
            outcome.state.next_action,
            "Persist recovery checkpoint and stop dispatch before compression",
        )
```

The test helper creates a temporary repository, saves a state with a deterministic key, and injects a `WorkspaceSnapshot(head="a" * 40, branch="codex/iteration-101-core-contracts", dirty_paths=dirty_paths)` without running real Git.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_run_lifecycle -v`

Expected: import failure for `app.run_lifecycle`.

- [ ] **Step 3: Implement fixed-command Git inspection and recovery policy**

`WorkspaceSnapshot` is a frozen dataclass with `head`, `branch`, and sorted `dirty_paths`. `GitWorkspaceInspector` executes exactly:

```python
("git", "rev-parse", "HEAD")
("git", "branch", "--show-current")
("git", "status", "--porcelain=v1", "-z")
```

with `cwd=repository_root`, `shell=False`, `check=True`, `capture_output=True`, `timeout=10`, and a sanitized environment containing only `PATH`, `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, `HOME`, `USERPROFILE`, and `GIT_CONFIG_NOSYSTEM=1`.

`RunLifecycleCoordinator.recover_active()` chooses exactly one action in this order:

1. Red context: persist checkpoint and stop dispatch.
2. Previously `running`: mark `unknown` and confirm terminated Worker/resource leases.
3. Base commit or branch drift: reconcile the exact saved/current refs before resuming.
4. Partial work package: resume its exact handoff path.
5. Dirty workspace: preserve and review the counted paths before the current package.
6. Otherwise retain the saved concrete `next_action`.

Each recovery increments revision, renders a redacted resume document, and appends one `run.recovered` event containing the reason but no secret or command execution. `handle_context_event` ignores unchanged/non-escalating events and checkpoints on Amber, Orange, and Red using the guide’s prescribed actions.

- [ ] **Step 4: Verify GREEN and a real temporary Git repository**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_run_lifecycle -v`

Expected: crash, drift, dirty work, partial handoff, Red priority, revision, and fixed-command tests pass.

- [ ] **Step 5: Commit the stable A5 coordinator**

```powershell
git add -- src/adapters/git_workspace.py src/app/__init__.py src/app/run_lifecycle.py tests/test_run_lifecycle.py
git diff --cached --check
git commit -m "feat: coordinate safe run recovery"
```

---

### Task 6: FastAPI Startup Recovery Integration

**Files:**
- Modify: `src/main_fastapi.py`
- Modify: `tests/test_main_fastapi.py`

**Interfaces:**
- Consumes: `RunLifecycleCoordinator` from Task 5.
- Produces: an injectable `AppState` lifecycle dependency, `recovery_outcome`, and startup invocation.
- Keeps: all existing routes and response contracts unchanged.

- [ ] **Step 1: Write failing lifespan integration tests**

```python
class FakeRunLifecycle:
    def __init__(self, outcome=None, error=None):
        self.outcome = outcome
        self.error = error
        self.calls = 0

    def recover_active(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.outcome


def test_lifespan_recovers_once_before_serving_requests(self):
    lifecycle = FakeRunLifecycle(outcome=None)
    app_state = AppState(memory_dir=tempfile.mkdtemp(), run_lifecycle=lifecycle)
    application = create_app(app_state)

    with TestClient(application) as client:
        assert client.get("/api/health").status_code == 200

    assert lifecycle.calls == 1


def test_integrity_failure_aborts_startup(self):
    lifecycle = FakeRunLifecycle(error=RunStateIntegrityError("tampered"))
    application = create_app(
        AppState(memory_dir=tempfile.mkdtemp(), run_lifecycle=lifecycle)
    )

    with pytest.raises(RunStateIntegrityError, match="tampered"):
        with TestClient(application):
            pass
```

Adapt the assertions to this repository’s `unittest` style while preserving the behavior.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_main_fastapi.TestRunRecoveryLifespan -v`

Expected: `AppState` rejects `run_lifecycle` or the lifecycle is not called.

- [ ] **Step 3: Add dependency injection and default composition**

Modify the signature to:

```python
def __init__(
    self,
    memory_dir: str = ".auto-memory",
    terminal=None,
    run_lifecycle: RunLifecycleCoordinator | None = None,
):
```

When no coordinator is injected, compose `FileRunStateRepository(Path(memory_dir), key_provider)` and `GitWorkspaceInspector(Path.cwd())`. The key provider reads `JARVIS_RUN_STATE_KEY` at call time and returns UTF-8 bytes or `None`; it never logs the value. At the beginning of lifespan, call `app_state.run_lifecycle.recover_active()` exactly once and store the result in `app_state.recovery_outcome`. If active-state validation raises `RunStateIntegrityError`, log only the error category and re-raise before `yield`. An absent active manifest returns `None` and does not require a key.

- [ ] **Step 4: Verify GREEN and API regressions**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_main_fastapi.TestRunRecoveryLifespan -v`

Expected: recovery invocation, no-active-state, and integrity failure tests pass.

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_main_fastapi -v`

Expected: all existing FastAPI tests remain green.

- [ ] **Step 5: Commit the startup integration**

```powershell
git add -- src/main_fastapi.py tests/test_main_fastapi.py
git diff --cached --check
git commit -m "feat: recover active runs during FastAPI startup"
```

---

### Task 7: A6 Combined Recovery Gate, Documentation, and Aggregate Coverage

**Files:**
- Create: `tests/test_phase_a_recovery.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Modify: `CHANGELOG.md`
- Create: `docs/reports/AUDIT_REPORT_129.md`

**Interfaces:**
- Consumes: all Phase A units.
- Produces: one black-box exit-gate test and current-state delivery evidence.

- [ ] **Step 1: Write the failing combined restart test**

```python
class TestPhaseARecoveryGate(unittest.TestCase):
    def test_red_restart_with_dirty_work_and_partial_agent_has_one_safe_action(self):
        state = self.make_state(
            status=RunStatus.RUNNING,
            context_level=ContextLevel.RED,
            work_packages=(self.partial_package("A4", "agents/a4.md"),),
            next_action="Finish atomic replacement test",
        )
        self.repository.save(
            state,
            render_resume_document(
                state,
                ResumeSections(agent_state=("A4 partial at agents/a4.md",)),
            ),
        )
        coordinator = RunLifecycleCoordinator(
            self.repository,
            FakeGit(WorkspaceSnapshot(
                head=state.base_commit,
                branch=state.active_branch,
                dirty_paths=("src/main_fastapi.py",),
            )),
        )

        outcome = coordinator.recover_active()
        reloaded = self.repository.load_active().state

        self.assertEqual(outcome.state.next_action, reloaded.next_action)
        self.assertEqual(
            reloaded.next_action,
            "Persist recovery checkpoint and stop dispatch before compression",
        )
        self.assertEqual(reloaded.status, RunStatus.UNKNOWN)
        self.assertEqual(reloaded.revision, state.revision + 1)
```

- [ ] **Step 2: Run the combined test and confirm RED if any integration behavior is absent**

Run: `\.\venv\Scripts\python.exe -m unittest tests.test_phase_a_recovery -v`

Expected before final integration: fail on the first missing combined invariant; after Tasks 1–6 are present, the test may pass immediately as a characterization of their composition. If it passes immediately, temporarily replace the expected Red action with the saved package action, observe the assertion fail, then restore the correct assertion before continuing.

- [ ] **Step 3: Register tests and update current-state documents**

Add the Phase A test classes to `tests/run_all.py` imports and suite construction. Update `tests/test_run_all_coverage.py` so every new `test_*.py` module is represented by the aggregate suite. Update the guide’s Phase A status only after all commands below pass. `PROJECT_ANALYSIS.md`, `CHANGELOG.md`, report index, and `AUDIT_REPORT_129.md` must record commands actually run and their fresh counts; they must not copy Iteration 128 counts in advance.

The audit report uses title `AUDIT_REPORT_129.md`, Iteration `#129`, date `2026-07-16`, status `Complete`, and goal `Complete Phase A context continuity and governance.` Under `## Evidence`, copy the literal focused-test, aggregate, full-discovery, compile, frontend, Playwright, and local-integration results from Step 4. If a command is not run, record `Not run` plus the concrete reason and keep the phase status incomplete; do not infer or pre-fill counts.

- [ ] **Step 4: Run the full Phase A verification contract**

Run in order:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_state tests.test_context_budget tests.test_resume_document tests.test_file_run_state_repository tests.test_run_lifecycle tests.test_phase_a_recovery -v
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
Set-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Set-Location ..
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services --timeout 15
git diff --check
```

Expected: every command exits `0`; Playwright may report the existing desktop-conditional skip but no failure. Run Ruff only if the already-approved exact tool is available from the locked environment; do not download it while Python locking remains incomplete.

- [ ] **Step 5: Self-review requirements and create the Phase A checkpoint**

Re-read guide sections 11 and 15/A, then confirm evidence for A2–A6, the Red/dirty/partial exit gate, secret redaction, authenticated integrity, startup recovery, and one concrete next action. Search changed files for `TBD`, `TODO`, unredacted test secrets, generic next actions, and absolute machine paths. Review `git diff` and `git diff --cached` so unrelated user changes are not staged.

```powershell
git add -- src/core/contracts src/core/brain/context_budget.py src/core/brain/resume_document.py src/core/kernel/secret_redaction.py src/adapters src/app src/main_fastapi.py tests/test_run_state.py tests/test_context_budget.py tests/test_resume_document.py tests/test_file_run_state_repository.py tests/test_run_lifecycle.py tests/test_phase_a_recovery.py tests/test_main_fastapi.py tests/run_all.py tests/test_run_all_coverage.py docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_129.md CHANGELOG.md docs/superpowers/plans/2026-07-16-phase-a-context-continuity.md
git diff --cached --check
git commit -m "feat: complete phase A context continuity"
```

After the commit, verify `git status --short` contains only preserved unrelated files, and set the next action to Phase B’s Worker request/cancel/terminal protocol design.
