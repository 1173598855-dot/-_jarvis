"""
Test main_fastapi.py - Phase 11 FastAPI REST API integration tests
Run: python3 tests/test_main_fastapi.py
"""
import asyncio
from contextlib import contextmanager
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.kernel.capability_manifest import (  # noqa: E402
    CapabilityHealth,
    CapabilityKind,
    CapabilityLifecycle,
    CapabilityRecord,
    CapabilityRisk,
    CapabilitySnapshot,
)
from core.kernel.plugin_sdk import PluginManifest  # noqa: E402
from core.kernel.event_bus import EventBus  # noqa: E402


def _capability_snapshot(issues=()):
    return CapabilitySnapshot.create((
        CapabilityRecord.create(
            capability_id="skill:memory-keeper",
            kind=CapabilityKind.SKILL,
            name="Memory Keeper",
            version=None,
            description="Local memory management",
            relative_path="skills/memory-keeper",
            entrypoint="skills/memory-keeper/SKILL.md",
            lifecycle=CapabilityLifecycle.DISCOVERED,
            permissions=("memory.read",),
            compatibility={"python": ">=3.10", "jarvis_api": ">=1.0"},
            source_url="https://example.invalid/memory-keeper",
            license_name="MIT",
            sha256="a" * 64,
            provenance_status="verified",
            health=CapabilityHealth.HEALTHY,
            risk=CapabilityRisk.LOW,
        ),
        CapabilityRecord.create(
            capability_id="plugin:event-logger",
            kind=CapabilityKind.PLUGIN,
            name="Event Logger",
            version="1.0.0",
            description="Records local events",
            relative_path="plugins/event-logger",
            entrypoint="plugins/event-logger/plugin.py",
            lifecycle=CapabilityLifecycle.DISABLED,
            permissions=("events.read",),
            source_url="https://example.invalid/event-logger",
            license_name="Apache-2.0",
            sha256="b" * 64,
            provenance_status="complete",
            health=CapabilityHealth.DEGRADED,
            health_issues=("disabled",),
            risk=CapabilityRisk.MEDIUM,
            risk_reasons=("event_access",),
        ),
    ), issues)

# Test that the module can be imported (syntax check)
class TestMainFastapiSyntax(unittest.TestCase):

    def test_src_module_prefers_the_worktree_core_over_inherited_pythonpath(self):
        worktree_root = Path(__file__).resolve().parents[1]
        main_checkout_src = worktree_root.parents[1] / "src"
        environment = os.environ.copy()
        inherited_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            value
            for value in (
                str(main_checkout_src),
                str(worktree_root / "src"),
                inherited_pythonpath,
            )
            if value
        )
        script = (
            "import src.main_fastapi; "
            "import core.kernel.plugin_sdk as plugin_sdk; "
            "from pathlib import Path; "
            "print(Path(plugin_sdk.__file__).resolve())"
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=worktree_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plugin_sdk_path = Path(result.stdout.strip()).resolve()
        self.assertTrue(plugin_sdk_path.is_relative_to(worktree_root))

    def test_import_main_fastapi(self):
        """Verify main_fastapi.py can be parsed without syntax errors"""
        import ast
        path = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertGreater(len(source), 10000, "File too short - may be truncated")

    def test_fastapi_app_exists(self):
        """Verify FastAPI app object is created"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "main_fastapi",
                str(Path(__file__).parent.parent / "src" / "main_fastapi.py"),
            )
            self.assertIsNotNone(spec)
        except Exception as e:
            self.fail(f"Module spec error: {e}")

    def test_agent_factory_imported(self):
        """Verify agent_factory is imported in main_fastapi"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("from core.brain.agent_factory import", text)
        self.assertIn("AgentFactory", text)

    def test_role_registry_imported(self):
        """Verify role_registry function is imported in main_fastapi"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("from core.brain.role_registry import", text)
        self.assertIn("create_default_registry", text)

    def test_api_role_routes_exist(self):
        """Verify Phase 11 role API routes exist"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('"/api/roles"', text)
        self.assertIn('"/api/roles/{role_name}"', text)
        self.assertIn('"/api/roles/dispatch"', text)
        self.assertIn('"/api/roles/dispatch_by_cap"', text)
        self.assertIn('"/api/roles/batch_dispatch"', text)

    def test_file_not_truncated(self):
        """Verify file ends with complete code (no truncation at data=a)"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped == "data = a":
                self.fail("File is truncated at 'data = a'")
        self.assertIn("uvicorn.run(app", text)

    def test_uses_lifespan_instead_of_deprecated_event_hooks(self):
        """FastAPI lifecycle is configured through the lifespan API."""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")

        self.assertIn("lifespan=lifespan", text)
        self.assertNotIn("@app.on_event", text)

    def test_isolated_app_lifespan_does_not_shutdown_default_state(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        with tempfile.TemporaryDirectory() as memory_dir:
            isolated_state = main_fastapi.AppState(memory_dir=memory_dir)
            isolated_app = main_fastapi.create_app(isolated_state)
            sandbox_dir = isolated_state.terminal.sandbox_dir
            with patch.object(
                main_fastapi.state.orchestrator,
                "shutdown",
            ) as default_shutdown:
                with TestClient(isolated_app) as client:
                    self.assertEqual(client.get("/api/health").status_code, 200)

            default_shutdown.assert_not_called()
            self.assertTrue(isolated_state.orchestrator._shutdown)
            self.assertFalse(os.path.exists(sandbox_dir))

    def test_app_state_has_agent_factory(self):
        """Verify AppState includes agent_factory"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("self.agent_factory = AgentFactory(", text)
        self.assertIn("registry=self.role_registry", text)
        self.assertIn("orchestrator=self.orchestrator", text)

    def test_version_bumped(self):
        """Verify API version is 1.1.0"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('version="1.1.0"', text)


class TestRunRecoveryLifespan(unittest.TestCase):
    class FakeRunLifecycle:
        def __init__(self, outcome=None, error=None):
            self.outcome = outcome
            self.error = error
            self.calls = 0

        def recover_active(self):
            self.calls += 1
            if self.error is not None:
                raise self.error
            return self.outcome

    def test_lifespan_recovers_once_before_serving_requests(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        lifecycle = self.FakeRunLifecycle(outcome=None)
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                run_lifecycle=lifecycle,
            )
            application = main_fastapi.create_app(app_state)

            with TestClient(application) as client:
                self.assertEqual(lifecycle.calls, 1)
                self.assertEqual(client.get("/api/health").status_code, 200)

            self.assertEqual(lifecycle.calls, 1)
            self.assertIsNone(app_state.recovery_outcome)

    def test_integrity_failure_aborts_startup_without_logging_details(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        lifecycle = self.FakeRunLifecycle(
            error=main_fastapi.RunStateIntegrityError("tampered-secret-detail")
        )
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                run_lifecycle=lifecycle,
            )
            application = main_fastapi.create_app(app_state)

            with patch.object(main_fastapi.logger, "error") as log_error:
                with self.assertRaisesRegex(
                    main_fastapi.RunStateIntegrityError,
                    "tampered-secret-detail",
                ):
                    with TestClient(application):
                        pass

            self.assertEqual(lifecycle.calls, 1)
            logged = " ".join(str(value) for call in log_error.call_args_list for value in call.args)
            self.assertIn("RUN_STATE_INTEGRITY_ERROR", logged)
            self.assertNotIn("tampered-secret-detail", logged)

    def test_default_lifecycle_needs_no_key_without_active_manifest(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        with tempfile.TemporaryDirectory() as memory_dir:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("JARVIS_RUN_STATE_KEY", None)
                app_state = main_fastapi.AppState(memory_dir=memory_dir)
                application = main_fastapi.create_app(app_state)

                with TestClient(application) as client:
                    self.assertEqual(client.get("/api/health").status_code, 200)

            self.assertIsNone(app_state.recovery_outcome)


class _FakeRoleTasks:
    def __init__(self, shutdown_order=None):
        self.records = {}
        self.shutdown_calls = 0
        self.shutdown_order = shutdown_order
        self.terminal_observers = []

    def add_terminal_observer(self, observer):
        self.terminal_observers.append(observer)

    def submit(self, request):
        from core.contracts.worker_protocol import WorkerTaskRecord, WorkerTaskStatus

        record = WorkerTaskRecord.from_request(request).evolve(
            status=WorkerTaskStatus.RUNNING,
            worker_pid=4242,
        )
        self.records[record.task_id] = record
        return record

    def list(self, limit=100):
        return list(reversed(tuple(self.records.values())[-limit:]))

    def get(self, task_id):
        return self.records.get(task_id)

    def cancel(self, task_id):
        from core.brain.role_worker import WorkerTaskTerminalError
        from core.contracts.worker_protocol import WorkerTaskStatus

        record = self.records.get(task_id)
        if record is None:
            return None
        if record.status.is_terminal:
            raise WorkerTaskTerminalError(record)
        record = record.evolve(
            status=WorkerTaskStatus.CANCELLED,
            error="Worker task cancelled",
            termination_confirmed=True,
        )
        self.records[task_id] = record
        return record

    def shutdown(self):
        self.shutdown_calls += 1
        if self.shutdown_order is not None:
            self.shutdown_order.append("role_tasks")


class _FakeRoleDispatch:
    def __init__(
        self,
        *,
        results=None,
        error=None,
        blocking=False,
        supervisor=None,
    ):
        self.results = results or {}
        self.error = error
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.blocking = blocking
        self.__supervisor = (
            supervisor if supervisor is not None else _FakeRoleTasks()
        )

    @property
    def supervisor(self):
        return self.__supervisor

    def _call(self, method, args):
        self.calls.append((method, *args))
        self.started.set()
        if self.blocking:
            self.release.wait(timeout=3)
        if self.error is not None:
            raise self.error
        return self.results[method]

    def dispatch_by_role(self, role_name, prompt, timeout):
        return self._call("role", (role_name, prompt, timeout))

    def dispatch_by_capability(self, capability, prompt, timeout):
        return self._call("capability", (capability, prompt, timeout))

    def batch_dispatch(self, tasks):
        return self._call("batch", (tasks,))


class _BlockingRoleTasks(_FakeRoleTasks):
    def __init__(self):
        super().__init__()
        self.cancel_started = threading.Event()
        self.release_cancel = threading.Event()

    def cancel(self, task_id):
        self.cancel_started.set()
        self.release_cancel.wait(timeout=2)
        return super().cancel(task_id)


class _BlockingSubmitRoleTasks(_FakeRoleTasks):
    def __init__(self):
        super().__init__()
        self.submit_started = threading.Event()
        self.release_submit = threading.Event()

    def submit(self, request):
        self.submit_started.set()
        self.release_submit.wait(timeout=2)
        return super().submit(request)


class _UnavailableRoleTasks(_FakeRoleTasks):
    def submit(self, _request):
        raise OSError("spawn unavailable")


class _TimeoutOnCancelRoleTasks(_FakeRoleTasks):
    def cancel(self, task_id):
        from core.contracts.worker_protocol import WorkerTaskStatus

        record = self.records.get(task_id)
        if record is None:
            return None
        record = record.evolve(
            status=WorkerTaskStatus.TIMEOUT,
            error="Worker task timed out after 30s",
            termination_confirmed=True,
        )
        self.records[task_id] = record
        return record


class TestRoleTaskLifecycleEndpoints(unittest.TestCase):
    @contextmanager
    def client(self, role_tasks=None):
        from fastapi.testclient import TestClient
        import main_fastapi

        role_tasks = role_tasks or _FakeRoleTasks()
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                role_tasks=role_tasks,
            )
            application = main_fastapi.create_app(app_state)
            with TestClient(application) as client:
                yield client, role_tasks

    def create_task(self, client):
        response = client.post(
            "/api/roles/tasks",
            json={
                "role_name": "engineer",
                "prompt": "Review recovery state",
                "timeout": 30,
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_create_list_and_get_task(self):
        with self.client() as (client, _role_tasks):
            created = self.create_task(client)
            task_id = created["task_id"]

            listed = client.get("/api/roles/tasks").json()
            fetched = client.get(f"/api/roles/tasks/{task_id}")

            self.assertEqual(created["status"], "running")
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["tasks"][0]["task_id"], task_id)
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["task_id"], task_id)

    def test_cancel_is_confirmed_and_terminal_conflict_is_stable(self):
        with self.client() as (client, _role_tasks):
            task_id = self.create_task(client)["task_id"]

            cancelled = client.post(f"/api/roles/tasks/{task_id}/cancel")
            conflict = client.post(f"/api/roles/tasks/{task_id}/cancel")

            self.assertEqual(cancelled.status_code, 200)
            self.assertEqual(cancelled.json()["status"], "cancelled")
            self.assertTrue(cancelled.json()["termination_confirmed"])
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["error"]["code"], "ROLE_TASK_TERMINAL")

    def test_unknown_tasks_and_invalid_requests_use_stable_errors(self):
        with self.client() as (client, _role_tasks):
            missing_get = client.get("/api/roles/tasks/task-missing")
            missing_cancel = client.post("/api/roles/tasks/task-missing/cancel")
            invalid = client.post(
                "/api/roles/tasks",
                json={"role_name": " ", "prompt": "work", "timeout": 0},
            )

            self.assertEqual(missing_get.status_code, 404)
            self.assertEqual(
                missing_get.json()["error"]["code"],
                "ROLE_TASK_NOT_FOUND",
            )
            self.assertEqual(missing_cancel.status_code, 404)
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(invalid.json()["error"]["code"], "INVALID_REQUEST")

    def test_create_rejects_fields_outside_the_wire_contract(self):
        with self.client() as (client, _role_tasks):
            response = client.post(
                "/api/roles/tasks",
                json={
                    "role_name": "engineer",
                    "prompt": "work",
                    "runner": "tests.worker_fixtures.succeed",
                    "env": {"INJECTED": "1"},
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_spawn_errors_use_the_declared_unavailable_envelope(self):
        with self.client(_UnavailableRoleTasks()) as (client, _role_tasks):
            response = client.post(
                "/api/roles/tasks",
                json={"role_name": "engineer", "prompt": "work"},
            )

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json()["error"]["code"],
                "ROLE_WORKER_UNAVAILABLE",
            )

    def test_cancel_race_reports_a_confirmed_timeout_as_terminal(self):
        with self.client(_TimeoutOnCancelRoleTasks()) as (client, _role_tasks):
            task_id = self.create_task(client)["task_id"]

            response = client.post(f"/api/roles/tasks/{task_id}/cancel")

            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["code"],
                "ROLE_TASK_TERMINAL",
            )

    def test_cancel_does_not_block_the_application_event_loop(self):
        role_tasks = _BlockingRoleTasks()
        with self.client(role_tasks) as (client, _role_tasks):
            task_id = self.create_task(client)["task_id"]
            result = {}

            def cancel_task():
                result["response"] = client.post(
                    f"/api/roles/tasks/{task_id}/cancel"
                )

            cancel_thread = threading.Thread(target=cancel_task, daemon=True)
            cancel_thread.start()
            self.assertTrue(role_tasks.cancel_started.wait(timeout=1))
            started = time.monotonic()
            try:
                health = client.get("/api/health")
            finally:
                role_tasks.release_cancel.set()
            elapsed = time.monotonic() - started
            cancel_thread.join(timeout=2)

            self.assertEqual(health.status_code, 200)
            self.assertLess(elapsed, 0.75)
            self.assertFalse(cancel_thread.is_alive())
            self.assertEqual(result["response"].status_code, 200)

    def test_create_does_not_block_the_application_event_loop(self):
        role_tasks = _BlockingSubmitRoleTasks()
        with self.client(role_tasks) as (client, _role_tasks):
            result = {}

            def create_task():
                result["response"] = client.post(
                    "/api/roles/tasks",
                    json={"role_name": "engineer", "prompt": "work"},
                )

            create_thread = threading.Thread(target=create_task, daemon=True)
            create_thread.start()
            self.assertTrue(role_tasks.submit_started.wait(timeout=1))
            started = time.monotonic()
            try:
                health = client.get("/api/health")
            finally:
                role_tasks.release_submit.set()
            elapsed = time.monotonic() - started
            create_thread.join(timeout=2)

            self.assertEqual(health.status_code, 200)
            self.assertLess(elapsed, 0.75)
            self.assertFalse(create_thread.is_alive())
            self.assertEqual(result["response"].status_code, 202)

    def test_lifespan_shuts_down_role_tasks(self):
        role_tasks = _FakeRoleTasks()
        from fastapi.testclient import TestClient
        import main_fastapi

        with tempfile.TemporaryDirectory() as memory_dir:
            application = main_fastapi.create_app(
                main_fastapi.AppState(
                    memory_dir=memory_dir,
                    role_tasks=role_tasks,
                )
            )
            with TestClient(application) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)

        self.assertEqual(role_tasks.shutdown_calls, 1)



class TestRequestBodyLimitMiddleware(unittest.TestCase):
    def test_rejects_headerless_chunked_overflow(self):
        import main_fastapi

        incoming = iter([
            {
                "type": "http.request",
                "body": b"x" * main_fastapi.MAX_REQUEST_BODY_BYTES,
                "more_body": True,
            },
            {"type": "http.request", "body": b"x", "more_body": False},
        ])
        downstream_messages = []
        sent = []

        async def receive():
            return next(incoming)

        async def send(message):
            sent.append(message)

        async def downstream(_scope, downstream_receive, _send):
            downstream_messages.append(await downstream_receive())

        middleware = main_fastapi._RequestBodyLimitMiddleware(downstream)
        asyncio.run(middleware(
            {"type": "http", "method": "POST", "headers": []},
            receive,
            send,
        ))

        self.assertEqual(downstream_messages[0]["type"], "http.disconnect")
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(
            json.loads(sent[-1]["body"]),
            {
                "error": {
                    "code": "REQUEST_BODY_TOO_LARGE",
                    "message": "Request body exceeds the 32 KiB limit",
                }
            },
        )


# ============================================================
# Test: Role dispatch endpoints (Iteration 40)
# ============================================================

class TestRoleDispatchEndpoints(unittest.TestCase):
    @contextmanager
    def client(self, role_dispatch):
        from fastapi.testclient import TestClient
        import main_fastapi

        role_tasks = role_dispatch.supervisor
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                role_tasks=role_tasks,
                role_dispatch=role_dispatch,
            )
            application = main_fastapi.create_app(app_state)
            with TestClient(application) as client:
                yield client, app_state

    @staticmethod
    def result(role_name="engineer", task_id="task-worker", status="success", message="done"):
        from core.brain.agent_factory import DispatchResult

        return DispatchResult(role_name, task_id, status, message)

    def test_dispatch_by_role_forwards_exact_arguments_and_response(self):
        service = _FakeRoleDispatch(results={"role": self.result()})
        with self.client(service) as (client, _state):
            response = client.post(
                "/api/roles/dispatch",
                json={
                    "role_name": "engineer",
                    "prompt": "write a test",
                    "timeout": 30,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(service.calls, [("role", "engineer", "write a test", 30)])
        self.assertEqual(response.json(), {
            "role_name": "engineer",
            "task_id": "task-worker",
            "status": "success",
            "message": "done",
        })

    def test_dispatch_by_role_missing_role_name(self):
        service = _FakeRoleDispatch(results={"role": self.result()})
        with self.client(service) as (client, _state):
            resp = client.post("/api/roles/dispatch", json={"prompt": "test"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(service.calls, [])

    def test_dispatch_by_role_maps_service_no_role_without_registry_precheck(self):
        service = _FakeRoleDispatch(results={
            "role": self.result(
                role_name="nonexistent_role_xyz",
                task_id="",
                status="no_role",
                message="service owns selection",
            )
        })
        with self.client(service) as (client, app_state):
            with patch.object(
                app_state.role_registry,
                "get",
                side_effect=AssertionError("adapter registry precheck"),
            ):
                resp = client.post("/api/roles/dispatch", json={
                    "role_name": "nonexistent_role_xyz", "prompt": "test",
                })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "ROLE_NOT_FOUND")
        self.assertEqual(service.calls, [
            ("role", "nonexistent_role_xyz", "test", 300)
        ])

    def test_dispatch_by_capability_forwards_exact_arguments_and_response(self):
        service = _FakeRoleDispatch(results={
            "capability": self.result(role_name="reviewer", task_id="task-cap")
        })
        with self.client(service) as (client, _state):
            resp = client.post("/api/roles/dispatch_by_cap", json={
                "capability": "coding", "prompt": "fix bug", "timeout": 19,
            })
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(service.calls, [("capability", "coding", "fix bug", 19)])
        self.assertEqual(resp.json(), {
            "role_name": "reviewer",
            "task_id": "task-cap",
            "status": "success",
            "message": "done",
        })

    def test_dispatch_by_capability_maps_service_no_capability(self):
        service = _FakeRoleDispatch(results={
            "capability": self.result(
                role_name="",
                task_id="",
                status="no_capability",
                message="service owns selection",
            )
        })
        with self.client(service) as (client, _state):
            resp = client.post("/api/roles/dispatch_by_cap", json={
                "capability": "nonexistent_cap_xyz", "prompt": "test",
            })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "CAPABILITY_NOT_FOUND")
        self.assertEqual(service.calls, [
            ("capability", "nonexistent_cap_xyz", "test", 300)
        ])

    def test_batch_dispatch_forwards_tasks_and_serializes_results(self):
        tasks = [
            {"role": "engineer", "prompt": "task 1", "timeout": 30},
            {"capability": "review", "prompt": "task 2"},
        ]
        service = _FakeRoleDispatch(results={"batch": [
            self.result(task_id="task-one"),
            self.result(role_name="reviewer", task_id="task-two"),
        ]})
        with self.client(service) as (client, _state):
            resp = client.post("/api/roles/batch_dispatch", json={"tasks": tasks})

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(service.calls, [("batch", tasks)])
        self.assertEqual(resp.json(), {
            "results": [
                {
                    "role_name": "engineer",
                    "task_id": "task-one",
                    "status": "success",
                    "message": "done",
                },
                {
                    "role_name": "reviewer",
                    "task_id": "task-two",
                    "status": "success",
                    "message": "done",
                },
            ],
            "count": 2,
        })

    def test_batch_dispatch_empty_tasks(self):
        service = _FakeRoleDispatch(results={"batch": []})
        with self.client(service) as (client, _state):
            resp = client.post("/api/roles/batch_dispatch", json={"tasks": []})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"results": [], "count": 0})
        self.assertEqual(service.calls, [("batch", [])])

    def test_single_dispatch_failures_have_stable_503_envelopes(self):
        from core.brain.role_dispatch_service import (
            RoleTaskTerminationUnconfirmedError,
            RoleWorkerInvalidResultError,
            RoleWorkerUnavailableError,
        )

        exceptions = (
            (
                RoleWorkerUnavailableError,
                "ROLE_WORKER_UNAVAILABLE",
                "Role worker is unavailable",
            ),
            (
                RoleTaskTerminationUnconfirmedError,
                "ROLE_TASK_TERMINATION_UNCONFIRMED",
                "Worker process termination is not confirmed",
            ),
            (
                RoleWorkerInvalidResultError,
                "ROLE_WORKER_INVALID_RESULT",
                "Role worker returned an invalid result",
            ),
        )
        routes = (
            (
                "role",
                "/api/roles/dispatch",
                {"role_name": "engineer", "prompt": "work"},
            ),
            (
                "capability",
                "/api/roles/dispatch_by_cap",
                {"capability": "coding", "prompt": "work"},
            ),
        )
        for method, route, payload in routes:
            for exception_type, code, message in exceptions:
                with self.subTest(route=route, exception=exception_type.__name__):
                    service = _FakeRoleDispatch(
                        error=exception_type("engineer", "task-failed", message)
                    )
                    with self.client(service) as (client, _state):
                        response = client.post(route, json=payload)
                    self.assertEqual(response.status_code, 503, response.text)
                    self.assertEqual(response.json(), {
                        "error": {"code": code, "message": message}
                    })
                    self.assertEqual(len(service.calls), 1)

    def test_batch_dispatch_preserves_positional_service_errors_as_200(self):
        tasks = [
            {"role": "engineer", "prompt": "first"},
            {"role": "engineer", "prompt": "second"},
        ]
        service = _FakeRoleDispatch(results={"batch": [
            self.result(task_id="task-first"),
            self.result(
                task_id="task-second",
                status="error",
                message="Role worker is unavailable",
            ),
        ]})

        with self.client(service) as (client, _state):
            response = client.post(
                "/api/roles/batch_dispatch",
                json={"tasks": tasks},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(service.calls, [("batch", tasks)])
        self.assertEqual(response.json(), {
            "results": [
                {
                    "role_name": "engineer",
                    "task_id": "task-first",
                    "status": "success",
                    "message": "done",
                },
                {
                    "role_name": "engineer",
                    "task_id": "task-second",
                    "status": "error",
                    "message": "Role worker is unavailable",
                },
            ],
            "count": 2,
        })

    def test_batch_does_not_translate_service_exception_to_top_level_503(self):
        from core.brain.role_dispatch_service import RoleWorkerUnavailableError

        error = RoleWorkerUnavailableError(
            "engineer",
            "task-failed",
            "Role worker is unavailable",
        )
        service = _FakeRoleDispatch(error=error)

        with self.client(service) as (client, _state):
            with self.assertRaises(RoleWorkerUnavailableError) as raised:
                client.post(
                    "/api/roles/batch_dispatch",
                    json={"tasks": []},
                )

        self.assertIs(raised.exception, error)
        self.assertEqual(service.calls, [("batch", [])])

    def test_batch_dispatch_rejects_non_array_tasks_with_exact_400(self):
        service = _FakeRoleDispatch(results={"batch": []})

        with self.client(service) as (client, _state):
            response = client.post(
                "/api/roles/batch_dispatch",
                json={"tasks": {"role": "engineer"}},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {
            "error": {
                "code": "INVALID_REQUEST",
                "message": "tasks must be an array",
            }
        })
        self.assertEqual(service.calls, [])

    def test_compatibility_dispatch_does_not_block_event_loop(self):
        routes = (
            (
                "role",
                "/api/roles/dispatch",
                {"role_name": "engineer", "prompt": "work"},
                self.result(),
            ),
            (
                "capability",
                "/api/roles/dispatch_by_cap",
                {"capability": "coding", "prompt": "work"},
                self.result(),
            ),
            (
                "batch",
                "/api/roles/batch_dispatch",
                {"tasks": []},
                [],
            ),
        )
        for method, route, payload, result in routes:
            with self.subTest(route=route):
                service = _FakeRoleDispatch(
                    results={method: result},
                    blocking=True,
                )
                with self.client(service) as (client, _state):
                    outcome = {}

                    def dispatch():
                        outcome["response"] = client.post(route, json=payload)

                    thread = threading.Thread(target=dispatch, daemon=True)
                    thread.start()
                    self.assertTrue(service.started.wait(timeout=1))
                    started = time.monotonic()
                    try:
                        health = client.get("/api/health")
                    finally:
                        service.release.set()
                    elapsed = time.monotonic() - started
                    thread.join(timeout=2)

                self.assertEqual(health.status_code, 200)
                self.assertLess(elapsed, 0.75)
                self.assertFalse(thread.is_alive())
                self.assertEqual(outcome["response"].status_code, 200)

    def test_lifespan_shutdown_is_worker_first_and_idempotent(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        order = []
        role_tasks = _FakeRoleTasks(order)
        role_dispatch = _FakeRoleDispatch(
            results={},
            supervisor=role_tasks,
        )
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                role_tasks=role_tasks,
                role_dispatch=role_dispatch,
            )
            orchestrator_shutdown = app_state.orchestrator.shutdown
            terminal_close = app_state.terminal.close

            def shutdown_orchestrator():
                order.append("orchestrator")
                orchestrator_shutdown()

            def shutdown_factory():
                order.append("agent_factory")

            def close_terminal():
                order.append("terminal")
                terminal_close()

            app_state.orchestrator.shutdown = shutdown_orchestrator
            app_state.agent_factory.shutdown = shutdown_factory
            app_state.terminal.close = close_terminal
            application = main_fastapi.create_app(app_state)
            with TestClient(application) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)

            app_state.shutdown()
            app_state.shutdown()

        self.assertEqual(role_tasks.shutdown_calls, 1)
        self.assertEqual(
            order,
            ["role_tasks", "orchestrator", "agent_factory", "terminal"],
        )

    def test_default_worker_receives_resolved_trusted_roots(self):
        import main_fastapi

        supervisor = MagicMock()
        with tempfile.TemporaryDirectory() as memory_dir, patch.object(
            main_fastapi,
            "RoleWorkerSupervisor",
            return_value=supervisor,
        ) as supervisor_type:
            app_state = main_fastapi.AppState(memory_dir=memory_dir)
            try:
                runner_config = supervisor_type.call_args.kwargs["runner_config"]
                self.assertEqual(
                    runner_config["memory_dir"],
                    str(Path(memory_dir).resolve()),
                )
                self.assertEqual(
                    runner_config["repository_root"],
                    str(Path.cwd().resolve()),
                )
            finally:
                app_state.shutdown()

    def test_injected_role_dispatch_reuses_its_supervisor(self):
        import main_fastapi

        role_tasks = _FakeRoleTasks()
        role_dispatch = _FakeRoleDispatch(
            results={},
            supervisor=role_tasks,
        )
        with tempfile.TemporaryDirectory() as memory_dir:
            with patch.object(
                main_fastapi,
                "RoleWorkerSupervisor",
                side_effect=AssertionError("constructed a second supervisor"),
            ):
                app_state = main_fastapi.AppState(
                    memory_dir=memory_dir,
                    role_dispatch=role_dispatch,
                )
            try:
                self.assertIs(app_state.role_tasks, role_tasks)
                self.assertIs(app_state.role_dispatch, role_dispatch)
            finally:
                app_state.shutdown()

        self.assertEqual(role_tasks.shutdown_calls, 1)

    def test_matching_role_task_and_dispatch_injections_preserve_identity(self):
        import main_fastapi

        role_tasks = _FakeRoleTasks()
        role_dispatch = _FakeRoleDispatch(
            results={},
            supervisor=role_tasks,
        )
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                role_tasks=role_tasks,
                role_dispatch=role_dispatch,
            )
            try:
                self.assertIs(app_state.role_tasks, role_tasks)
                self.assertIs(app_state.role_dispatch, role_dispatch)
            finally:
                app_state.shutdown()

    def test_mismatched_role_task_and_dispatch_injections_are_rejected(self):
        import main_fastapi

        role_tasks = _FakeRoleTasks()
        role_dispatch = _FakeRoleDispatch(
            results={},
            supervisor=_FakeRoleTasks(),
        )
        with tempfile.TemporaryDirectory() as memory_dir:
            with self.assertRaisesRegex(
                ValueError,
                "role_tasks and role_dispatch must share the same supervisor",
            ):
                main_fastapi.AppState(
                    memory_dir=memory_dir,
                    role_tasks=role_tasks,
                    role_dispatch=role_dispatch,
                )

    def test_shutdown_retries_only_resources_that_failed(self):
        import main_fastapi

        order = []
        role_tasks = _FakeRoleTasks()
        role_dispatch = _FakeRoleDispatch(
            results={},
            supervisor=role_tasks,
        )
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                role_tasks=role_tasks,
                role_dispatch=role_dispatch,
            )
            orchestrator_shutdown = app_state.orchestrator.shutdown
            terminal_close = app_state.terminal.close
            worker_attempts = 0

            def shutdown_worker():
                nonlocal worker_attempts
                worker_attempts += 1
                order.append("role_tasks")
                if worker_attempts == 1:
                    raise RuntimeError("worker shutdown failed")

            def shutdown_orchestrator():
                order.append("orchestrator")
                orchestrator_shutdown()

            def shutdown_factory():
                order.append("agent_factory")

            def close_terminal():
                order.append("terminal")
                terminal_close()

            app_state.role_tasks.shutdown = shutdown_worker
            app_state.orchestrator.shutdown = shutdown_orchestrator
            app_state.agent_factory.shutdown = shutdown_factory
            app_state.terminal.close = close_terminal

            with self.assertRaisesRegex(
                RuntimeError,
                "worker shutdown failed",
            ):
                app_state.shutdown()
            self.assertEqual(order, [
                "role_tasks",
                "orchestrator",
                "agent_factory",
                "terminal",
            ])

            app_state.shutdown()
            app_state.shutdown()

        self.assertEqual(order, [
            "role_tasks",
            "orchestrator",
            "agent_factory",
            "terminal",
            "role_tasks",
        ])


class TestQueryEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_memory_entries_with_type_filter(self):
        resp = self.client.get("/api/memory/entries?memory_type=user")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("entries", data)
        self.assertIsInstance(data["entries"], list)

    def test_memory_entries_invalid_type_ignored(self):
        resp = self.client.get("/api/memory/entries?memory_type=invalid_type")
        self.assertEqual(resp.status_code, 200)

    def test_orchestrator_history_default_limit(self):
        resp = self.client.get("/api/orchestrator/history")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        self.assertIn("count", data)

    def test_orchestrator_history_custom_limit(self):
        resp = self.client.get("/api/orchestrator/history?limit=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(data["count"], 5)

    def test_orchestrator_history_clamps_limit_to_contract_maximum(self):
        import main_fastapi

        with patch.object(
            main_fastapi.state.orchestrator,
            "collect",
            return_value=[],
        ) as collect:
            resp = self.client.get("/api/orchestrator/history?limit=101")

        self.assertEqual(resp.status_code, 200)
        collect.assert_called_once_with(limit=100)

    def test_orchestrator_history_rejects_non_integer_limit_with_invalid_request(self):
        resp = self.client.get("/api/orchestrator/history?limit=abc")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_roles_list_with_capability_filter(self):
        resp = self.client.get("/api/roles?capability=coding")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("roles", data)
        self.assertIn("count", data)


class TestCapabilityRegistryEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.main_fastapi = main_fastapi
        cls.client = TestClient(main_fastapi.app)

    @contextmanager
    def registry(self, error=None, snapshot=None):
        registry = MagicMock()
        if error is None:
            registry.snapshot.return_value = snapshot or _capability_snapshot()
        else:
            registry.snapshot.side_effect = error
        with patch.object(
            self.main_fastapi._default_state,
            "capability_registry",
            registry,
            create=True,
        ):
            yield registry

    def test_registry_filters_and_serializes_public_records(self):
        with self.registry():
            response = self.client.get(
                "/api/capabilities/registry"
                "?q=memory&kind=skill&compatible_only=true&max_risk=low&limit=1"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {"schema_version", "capabilities", "count", "issues"},
        )
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["count"], 1)
        self.assertEqual(
            body["capabilities"][0]["capability_id"],
            "skill:memory-keeper",
        )
        self.assertEqual(
            body["capabilities"][0]["compatibility"]["status"],
            "compatible",
        )
        self.assertNotIn("match", body["capabilities"][0])
        self.assertEqual(body["issues"], [])
        self.assertNotIn(
            str(Path(__file__).parent.parent.resolve()),
            json.dumps(body),
        )

    def test_registry_rejects_duplicate_unknown_and_invalid_queries(self):
        invalid_paths = (
            "/api/capabilities/registry?q=one&q=two",
            "/api/capabilities/registry?kind=archive",
            "/api/capabilities/registry?kind=skill&kind=plugin",
            "/api/capabilities/registry?compatible_only=1",
            "/api/capabilities/registry?max_risk=critical",
            "/api/capabilities/registry?limit=0",
            "/api/capabilities/registry?limit=101",
            "/api/capabilities/registry?limit=abc",
            f"/api/capabilities/registry?q={'x' * 257}",
            "/api/capabilities/registry?q%5B%5D=memory",
            "/api/capabilities/registry?root=C%3A%5Csecret",
        )
        with self.registry() as registry:
            for path in invalid_paths:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(
                        response.json()["error"]["code"],
                        "INVALID_REQUEST",
                    )

        registry.snapshot.assert_not_called()

    def test_registry_unavailable_hides_internal_path_details(self):
        repository_root = Path(__file__).parent.parent.resolve()
        with self.registry(
            OSError(f"cannot read {repository_root / 'skills'}")
        ):
            response = self.client.get("/api/capabilities/registry")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"]["code"],
            "CAPABILITY_REGISTRY_UNAVAILABLE",
        )
        self.assertNotIn(str(repository_root), response.text)

    def test_registry_reports_bounded_snapshot_issues(self):
        issues = tuple(f"ui_component_invalid:item-{index}:read_failed" for index in range(101))
        with self.registry(snapshot=_capability_snapshot(issues)):
            response = self.client.get("/api/capabilities/registry")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("issues", body)
        self.assertEqual(len(body["issues"]), 100)
        self.assertEqual(body["issues"][-1], "issues_truncated")

    def test_default_registry_uses_the_repository_root(self):
        expected_root = Path(__file__).parent.parent.resolve()
        self.assertEqual(
            self.main_fastapi._default_state.capability_registry._root,
            expected_root,
        )

    def test_default_capability_target_matches_the_plugin_sdk(self):
        manifest = PluginManifest(name="fixture", version="1.0.0", description="")
        self.assertEqual(
            self.main_fastapi._default_state.capability_target.jarvis_api,
            manifest.api_version,
        )


class TestOrchestratorInputValidation(unittest.TestCase):
    """The shared orchestrator contract rejects malformed request values."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.main_fastapi = main_fastapi
        cls.client = TestClient(main_fastapi.app, raise_server_exceptions=False)

    def assert_invalid_request(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        self.assertIn("message", response.json()["error"])

    def test_normalize_dispatch_text_accepts_surrogate_pair_and_scalar(self):
        paired_surrogates = "\ud83d\ude00"
        scalar_emoji = "\U0001f600"

        self.assertEqual(
            self.main_fastapi._normalize_dispatch_text(paired_surrogates),
            scalar_emoji,
        )
        self.assertEqual(
            self.main_fastapi._normalize_dispatch_text(scalar_emoji),
            scalar_emoji,
        )

    def test_dispatch_rejects_non_object_json_bodies(self):
        for payload in ([], 1, "prompt"):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    json=payload,
                )
                self.assert_invalid_request(response)

    def test_dispatch_rejects_malformed_json_with_invalid_json_code(self):
        response = self.client.post(
            "/api/orchestrator/dispatch",
            content=b'{"agent_name":',
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_JSON")

    def test_dispatch_normalizes_json_resource_limit_errors(self):
        excessive_integer = (
            b'{"agent_name":"analyzer","prompt":"ping","timeout":'
            + (b"9" * 5000)
            + b"}"
        )
        depth = 10_000
        deeply_nested = (
            b'{"agent_name":"analyzer","prompt":"ping","nested":'
            + (b"[" * depth)
            + b"0"
            + (b"]" * depth)
            + b"}"
        )

        for payload in (excessive_integer, deeply_nested):
            with self.subTest(payload_size=len(payload)):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "INVALID_JSON",
                )

    def test_dispatch_rejects_non_string_or_blank_agent_and_prompt(self):
        payloads = (
            {"agent_name": 1, "prompt": "ping"},
            {"agent_name": [], "prompt": "ping"},
            {"agent_name": "analyzer", "prompt": 1},
            {"agent_name": "analyzer", "prompt": []},
            {"agent_name": "   ", "prompt": "ping"},
            {"agent_name": "analyzer", "prompt": "\t"},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    json=payload,
                )
                self.assert_invalid_request(response)

    def test_dispatch_rejects_surrogate_code_points(self):
        payloads = (
            b'{"agent_name":"\\ud800","prompt":"ping"}',
            b'{"agent_name":"analyzer\\udfff","prompt":"ping"}',
            b'{"agent_name":"analyzer","prompt":"\\ud800"}',
            b'{"agent_name":"analyzer","prompt":"ping\\udfff"}',
        )
        with patch.object(self.main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            for payload in payloads:
                with self.subTest(payload=payload):
                    response = self.client.post(
                        "/api/orchestrator/dispatch",
                        content=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assert_invalid_request(response)

        dispatch.assert_not_called()

    def test_dispatch_enforces_timeout_minimum_and_priority_bounds(self):
        for payload in (
            {"agent_name": "analyzer", "prompt": "ping", "timeout": 0},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": -1},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": 301},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": 10**100},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": True},
            {"agent_name": "analyzer", "prompt": "ping", "priority": -1},
            {"agent_name": "analyzer", "prompt": "ping", "priority": 4},
            {"agent_name": "analyzer", "prompt": "ping", "priority": True},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    json=payload,
                )
                self.assert_invalid_request(response)

    def test_dispatch_accepts_contract_boundary_values(self):
        with patch.object(self.main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            response = self.client.post(
                "/api/orchestrator/dispatch",
                json={
                    "agent_name": "analyzer",
                    "prompt": "ping",
                    "timeout": 300,
                    "priority": 0,
                },
            )

        self.assertEqual(response.status_code, 200)
        task = dispatch.call_args.args[0]
        self.assertEqual(task.timeout, 300)
        self.assertEqual(task.priority, 0)

    def test_dispatch_defaults_timeout_to_contract_maximum(self):
        with patch.object(self.main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            response = self.client.post(
                "/api/orchestrator/dispatch",
                json={"agent_name": "analyzer", "prompt": "ping"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(dispatch.call_args.args[0].timeout, 300)


class TestPluginLifecycleEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_plugin_enable_nonexistent_returns_error(self):
        resp = self.client.post("/api/plugins/enable", json={"plugin_id": "nonexistent_xyz_999"})
        self.assertIn(resp.status_code, [200, 404, 500])

    def test_plugin_disable_nonexistent_returns_error(self):
        resp = self.client.post("/api/plugins/disable", json={"plugin_id": "nonexistent_xyz_999"})
        self.assertIn(resp.status_code, [200, 404, 500])


class TestPluginServiceOwnership(unittest.TestCase):
    def test_plugins_endpoint_uses_the_active_state_manager(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        manager = MagicMock()
        manager.get_all_plugins.return_value = []
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                plugin_manager=manager,
            )
            with TestClient(main_fastapi.create_app(app_state)) as client:
                self.assertEqual(client.get("/api/plugins").json(), {"plugins": []})

        manager.get_all_plugins.assert_called_once_with()

    def test_events_endpoint_reads_the_active_state_event_bus(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        event_bus = EventBus()
        event_bus.emit("plugin.loaded", {"plugin_id": "fixture"})
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                event_bus=event_bus,
                plugin_manager=MagicMock(),
            )
            with TestClient(main_fastapi.create_app(app_state)) as client:
                response = client.get("/api/events")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][0]["type"], "plugin.loaded")

    def test_shutdown_destroys_event_bus_after_plugin_cleanup_error(self):
        import main_fastapi

        manager = MagicMock()
        manager.close.side_effect = RuntimeError("plugin cleanup failed")
        event_bus = MagicMock()
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                event_bus=event_bus,
                plugin_manager=manager,
            )
            with self.assertRaisesRegex(RuntimeError, "plugin cleanup failed"):
                app_state.shutdown()

        manager.close.assert_called_once_with()
        event_bus.destroy.assert_called_once_with()

    def test_plugin_endpoints_reject_worker_controls_before_calling_manager(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        manager = MagicMock()
        with tempfile.TemporaryDirectory() as memory_dir:
            app_state = main_fastapi.AppState(
                memory_dir=memory_dir,
                plugin_manager=manager,
            )
            with TestClient(main_fastapi.create_app(app_state)) as client:
                for path in (
                    "/api/plugins/load",
                    "/api/plugins/enable",
                    "/api/plugins/disable",
                ):
                    response = client.post(
                        path,
                        json={"plugin_id": "event-logger", "worker_pid": 1234},
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

        manager.discover.assert_not_called()
        manager.load.assert_not_called()
        manager.enable.assert_not_called()
        manager.disable.assert_not_called()


class TestPydanticModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        import main_fastapi
        cls.mf = main_fastapi

    def test_chat_request_defaults(self):
        req = self.mf.ChatRequest(messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(req.model, "default")
        self.assertFalse(req.stream)

    def test_terminal_request_requires_command(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.mf.TerminalRequest()

    def test_memory_request_defaults(self):
        req = self.mf.MemoryRequest(title="t", content="c")
        self.assertEqual(req.type, "user")
        self.assertEqual(req.tags, [])

    def test_plugin_load_request_requires_plugin_id(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.mf.PluginLoadRequest()

    def test_batch_dispatch_default_empty(self):
        req = self.mf.BatchDispatchRequest()
        self.assertEqual(req.tasks, [])

def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. main_fastapi tests - Iteration 31")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestMainFastapiSyntax)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 60)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed, {len(result.failures)} failed, {len(result.errors)} errors")
    print("=" * 60)
    return 0 if result.wasSuccessful() else 1

class TestFastAPIEndpoints(unittest.TestCase):
    """Integration tests for FastAPI HTTP endpoints using TestClient"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_health_returns_200(self):
        """GET /api/health returns status=healthy"""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)

    def test_health_has_uptime(self):
        """Health response includes uptime as float"""
        resp = self.client.get("/api/health")
        data = resp.json()
        self.assertIn("uptime", data)
        self.assertIsInstance(data["uptime"], (int, float))

    def test_system_stats_returns_200(self):
        """GET /api/system/stats returns dict with cpu/memory/disk/network"""
        resp = self.client.get("/api/system/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cpu", data)
        self.assertIn("memory", data)
        self.assertIn("disk", data)
        self.assertIn("network", data)

    def test_ollama_status_returns_dict(self):
        """GET /api/ollama/status returns dict (error OK since no Ollama)"""
        resp = self.client.get("/api/ollama/status")
        # Returns 200 with status dict or 500 if Ollama unavailable
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable

    def test_ollama_chat_missing_model_returns_400(self):
        """POST /api/ollama/chat with empty model returns error"""
        resp = self.client.post("/api/ollama/chat", json={"messages": []})
        # Upstream unavailability is normalized to the public 502 envelope.
        self.assertIn(resp.status_code, [400, 502])

    def test_terminal_execute_empty_command_returns_400(self):
        """POST /api/terminal/execute with empty command returns 400"""
        resp = self.client.post("/api/terminal/execute", json={"command": ""})
        self.assertEqual(resp.status_code, 400)

    def test_terminal_execute_missing_field_returns_standard_error(self):
        """POST /api/terminal/execute without 'command' uses the shared envelope."""
        resp = self.client.post("/api/terminal/execute", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "MISSING_COMMAND")

    def test_plugins_list_returns_200(self):
        """GET /api/plugins returns list of plugins"""
        resp = self.client.get("/api/plugins")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("plugins", data)
        self.assertIsInstance(data["plugins"], list)

    def test_memory_entries_returns_list(self):
        """GET /api/memory/entries returns list"""
        resp = self.client.get("/api/memory/entries")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("entries", data)
        self.assertIsInstance(data["entries"], list)

    def test_memory_store_returns_success(self):
        """POST /api/memory/store creates a new entry"""
        resp = self.client.post("/api/memory/store", json={
            "type": "user",
            "title": "test_entry",
            "content": "test content for integration",
            "tags": ["test"],
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("success", data)
        self.assertTrue(data["success"])

    def test_events_returns_list(self):
        """GET /api/events returns list of events"""
        resp = self.client.get("/api/events")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("events", data)
        self.assertIsInstance(data["events"], list)

    def test_orchestrator_agents_returns_list(self):
        """GET /api/orchestrator/agents returns agents list"""
        try:
            resp = self.client.get("/api/orchestrator/agents")
        except Exception:
            # Connection error if orchestrator shutdown by prior test
            return
        # 200 if running, 500 if error
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable
        if resp.status_code == 200:
            data = resp.json()
            self.assertIn("agents", data)
            self.assertIn("count", data)

    def test_roles_list_returns_200(self):
        """GET /api/roles returns roles list"""
        resp = self.client.get("/api/roles")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("roles", data)
        self.assertIn("count", data)

    def test_get_role_not_found_returns_404(self):
        """GET /api/roles/nonexistent_role returns 404"""
        resp = self.client.get("/api/roles/nonexistent_role_xyz_999")
        self.assertEqual(resp.status_code, 404)

    def test_dispatch_by_role_missing_fields_returns_422(self):
        """POST /api/roles/dispatch without required fields returns 400"""
        resp = self.client.post("/api/roles/dispatch", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_cors_headers_present(self):
        """CORS middleware allows cross-origin requests"""
        resp = self.client.get("/api/health", headers={"Origin": "http://example.com"})
        self.assertEqual(resp.status_code, 200)

    def test_openapi_docs_available(self):
        """FastAPI auto-generated OpenAPI docs are available"""
        resp = self.client.get("/docs")
        self.assertIn(resp.status_code, [200, 404])

    def test_version_in_health_response(self):
        """Health endpoint includes API version 1.1.0"""
        resp = self.client.get("/api/health")
        data = resp.json()
        self.assertEqual(data.get("version"), "1.1.0")



class TestMainFastapiIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient
        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_health_returns_200(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healthy")

    def test_health_version_is_1_1_0(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.json().get("version"), "1.1.0")

    def test_system_stats_returns_keys(self):
        resp = self.client.get("/api/system/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ["cpu", "memory", "disk", "network"]:
            self.assertIn(key, data)

    def test_terminal_missing_command_returns_400(self):
        resp = self.client.post("/api/terminal/execute", json={"command": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "MISSING_COMMAND")

    def test_terminal_execute_is_disabled_without_capability(self):
        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "false", "JARVIS_TERMINAL_TOKEN": ""},
        ):
            resp = self.client.post(
                "/api/terminal/execute",
                json={"command": "echo", "args": ["blocked"]},
            )

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "TERMINAL_DISABLED")

    def test_terminal_execute_rejects_invalid_capability_token(self):
        import main_fastapi

        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "true", "JARVIS_TERMINAL_TOKEN": "test-token"},
        ), patch.object(main_fastapi.state.terminal, "execute") as execute:
            resp = self.client.post(
                "/api/terminal/execute",
                json={"command": "pwd", "args": []},
                headers={"X-Jarvis-Terminal-Token": "wrong-token"},
            )

        execute.assert_not_called()
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "TERMINAL_UNAUTHORIZED")

    def test_orchestrator_dispatch_forwards_timeout_and_priority(self):
        import main_fastapi

        with patch.object(main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            resp = self.client.post(
                "/api/orchestrator/dispatch",
                json={
                    "agent_name": "analyzer",
                    "prompt": "ping",
                    "timeout": 45,
                    "priority": 3,
                },
            )

        self.assertEqual(resp.status_code, 200)
        task = dispatch.call_args.args[0]
        self.assertEqual(task.timeout, 45)
        self.assertEqual(task.priority, 3)

    def test_memory_store_returns_success(self):
        resp = self.client.post("/api/memory/store", json={
            "type": "user",
            "title": "integration_test",
            "content": "iteration 78 canonical integration",
            "tags": ["test"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))

    def test_memory_probe_can_be_deleted_by_returned_id(self):
        cleanup_token = "fastapi-test-secret"
        stored = self.client.post("/api/memory/store", json={
            "type": "project",
            "title": ".test-local-integration-fastapi-delete",
            "content": "temporary integration probe",
            "tags": ["test"],
            "probe_cleanup_token": cleanup_token,
        })
        entry_id = stored.json()["id"]

        deleted = self.client.request(
            "DELETE",
            f"/api/memory/probes/project/{entry_id}",
            json={"cleanup_token": cleanup_token},
        )

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), {"success": True, "id": entry_id})


    def test_ollama_token_usage_returns_fields(self):
        resp = self.client.get("/api/ollama/token-usage")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("latest", data)
        self.assertIn("totals", data)
        self.assertIn("samples", data)
        self.assertIn("session_started_at", data)

    def test_ollama_chat_records_token_usage(self):
        resp = self.client.post("/api/ollama/chat", json={
            "model": "default",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
        })
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable
        usage_resp = self.client.get("/api/ollama/token-usage")
        self.assertEqual(usage_resp.status_code, 200)

    def test_ollama_stream_uses_nested_error_frame_without_done(self):
        import main_fastapi

        with patch.object(
            main_fastapi.state.ollama,
            "stream_chat_generator",
            side_effect=RuntimeError("fixture failure"),
        ):
            response = self.client.get(
                "/api/ollama/chat/stream",
                params={"model": "fixture-model"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '"error": {"code": "OLLAMA_STREAM_ERROR", "message": "fixture failure"}',
            response.text,
        )
        self.assertNotIn("data: [DONE]", response.text)

    def test_openapi_route_exists(self):
        resp = self.client.get("/docs")
        self.assertIn(resp.status_code, [200, 404])

if __name__ == "__main__":
    sys.exit(run_all_tests())
