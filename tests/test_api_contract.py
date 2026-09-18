"""Cross-implementation checks for the shared Core API contract."""

import importlib.util
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
CONTRACT_PATH = ROOT / "contracts" / "core-api.openapi.json"
sys.path.insert(0, str(SRC))
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _free_port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _load_httpserver_module():
    spec = importlib.util.spec_from_file_location(
        "jarvis_contract_httpserver",
        SRC / "main.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_json(url, timeout=5):
    try:
        with _NO_PROXY_OPENER.open(url, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            try:
                body = json.load(error)
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            return error.code, body


def _get_sse_payloads(url, timeout=5):
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/event-stream"},
        method="GET",
    )
    with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
        payloads = []
        while True:
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            payloads.append(payload)
            if payload == "[DONE]":
                break
        return response.status, payloads


def _post_sse_payloads(url, payload, timeout=5):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            payloads = []
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                payloads.append(line.removeprefix("data:").strip())
                if payloads[-1] == "[DONE]":
                    break
            return response.status, payloads
    except urllib.error.HTTPError as error:
        with error:
            return error.code, []


def _post_json(url, payload, timeout=5, headers=None):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


def _post_raw_json(url, payload, timeout=5):
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


def _post_raw_body(url, payload, timeout=5):
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read().decode("utf-8")


def _post_error_body(url, payload, timeout=5):
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            return response.status, ""
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read().decode("utf-8")


def _wait_for_health(base_url, process=None):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError("Express server exited before becoming healthy")
        try:
            status, _ = _get_json(f"{base_url}/api/health", timeout=1)
            if status == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"Server did not become healthy: {base_url}")


def _resolve_schema(document, schema):
    if "$ref" not in schema:
        return schema
    node = document
    for part in schema["$ref"].removeprefix("#/").split("/"):
        node = node[part]
    return node


def _assert_json_shape(test_case, document, schema, value, path="response"):
    schema = _resolve_schema(document, schema)

    for index, child_schema in enumerate(schema.get("allOf", [])):
        _assert_json_shape(
            test_case,
            document,
            child_schema,
            value,
            f"{path}.allOf[{index}]",
        )
    if "anyOf" in schema:
        test_case.assertTrue(
            any(
                _json_shape_matches(document, child_schema, value)
                for child_schema in schema["anyOf"]
            ),
            f"{path}: value does not match anyOf",
        )
    if "if" in schema:
        branch = "then" if _json_shape_matches(document, schema["if"], value) else "else"
        if branch in schema:
            _assert_json_shape(
                test_case,
                document,
                schema[branch],
                value,
                f"{path}.{branch}",
            )

    expected_types = schema.get("type")
    if isinstance(expected_types, str):
        expected_types = [expected_types]

    def matches_type(type_name):
        checks = {
            "null": lambda candidate: candidate is None,
            "object": lambda candidate: isinstance(candidate, dict),
            "array": lambda candidate: isinstance(candidate, list),
            "string": lambda candidate: isinstance(candidate, str),
            "number": lambda candidate: (
                type(candidate) in {int, float}
            ),
            "integer": lambda candidate: type(candidate) is int,
            "boolean": lambda candidate: type(candidate) is bool,
        }
        return type_name in checks and checks[type_name](value)

    expected_type = None
    if expected_types:
        expected_type = next(
            (type_name for type_name in expected_types if matches_type(type_name)),
            None,
        )
        test_case.assertIsNotNone(
            expected_type,
            f"{path}: expected {expected_types}, got {type(value).__name__}",
        )

    if "const" in schema:
        test_case.assertEqual(value, schema["const"], path)
    if "enum" in schema:
        test_case.assertIn(value, schema["enum"], path)
    if "minimum" in schema:
        test_case.assertGreaterEqual(value, schema["minimum"], path)
    if "maximum" in schema:
        test_case.assertLessEqual(value, schema["maximum"], path)
    if "minLength" in schema:
        test_case.assertGreaterEqual(len(value), schema["minLength"], path)
    if "pattern" in schema:
        test_case.assertIsNotNone(re.search(schema["pattern"], value), path)

    if value is None:
        return
    is_object_schema = expected_type == "object" or (
        isinstance(value, dict)
        and ("properties" in schema or "required" in schema)
    )
    if is_object_schema:
        for key in schema.get("required", []):
            test_case.assertIn(key, value, f"{path}.{key}")
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                _assert_json_shape(test_case, document, child_schema, value[key], f"{path}.{key}")
    if expected_type == "array" and "items" in schema:
        for index, item in enumerate(value):
            _assert_json_shape(
                test_case,
                document,
                schema["items"],
                item,
                f"{path}[{index}]",
            )


def _json_shape_matches(document, schema, value):
    try:
        _assert_json_shape(unittest.TestCase(), document, schema, value)
    except AssertionError:
        return False
    return True


def _assert_contract_document(test_case, document):
    test_case.assertRegex(document.get("openapi", ""), r"^3\.1\.")
    test_case.assertIsInstance(document.get("info"), dict)
    test_case.assertIsInstance(document.get("paths"), dict)
    test_case.assertIsInstance(document.get("components", {}).get("schemas"), dict)

    def visit(node):
        if isinstance(node, dict):
            if "$ref" in node:
                resolved = _resolve_schema(document, node)
                test_case.assertIsInstance(resolved, dict)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(document)


class _OllamaFixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def do_GET(self):
        responses = {
            "/api/version": {"version": "0.9.0-test"},
            "/api/tags": {
                "models": [{
                    "name": "fixture-model:latest",
                    "size": 123,
                    "digest": "fixture-digest",
                    "modified_at": "2026-07-12T00:00:00Z",
                    "details": {},
                }],
            },
            "/api/ps": {"models": []},
        }
        payload = responses.get(self.path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return
        content_length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(content_length) or b"{}")
        if request.get("model") == "fixture-error":
            body = json.dumps({"error": "fixture upstream failure"}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if request.get("model") == "fixture-invalid":
            body = json.dumps({
                "message": {"content": "incomplete response"},
                "done": True,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if request.get("stream"):
            frames = [
                {
                    "model": "fixture-model:latest",
                    "message": {"role": "assistant", "content": "OK"},
                    "done": False,
                },
                {
                    "model": "fixture-model:latest",
                    "done": True,
                    "prompt_eval_count": 10,
                    "eval_count": 7,
                },
            ]
            body = "\n".join(json.dumps(frame) for frame in frames).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        payload = {
            "model": "fixture-model:latest",
            "message": {"role": "assistant", "content": "OK"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 7,
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestSharedApiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.spec = cls.contract

    def test_get_json_preserves_non_json_http_error_for_health_retry(self):
        opener = globals().get("_NO_PROXY_OPENER")
        self.assertIsNotNone(opener)
        error = urllib.error.HTTPError(
            "http://127.0.0.1:1/api/health",
            502,
            "Bad Gateway",
            {},
            io.BytesIO(b""),
        )

        with patch.object(opener, "open", side_effect=error):
            status, body = _get_json("http://127.0.0.1:1/api/health")

        self.assertEqual(status, 502)
        self.assertEqual(body, {})

    def test_loopback_http_helpers_do_not_configure_proxy(self):
        opener = globals().get("_NO_PROXY_OPENER")
        self.assertIsNotNone(opener)
        proxy_handlers = [
            handler
            for handler in opener.handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        ]

        self.assertEqual(proxy_handlers, [])

    def test_contract_is_openapi_31_document(self):
        _assert_contract_document(self, self.contract)
        self.assertEqual(self.spec["info"]["version"], "1.17.0")

    def test_plugin_worker_lifecycle_paths_are_bounded_and_schema_bound(self):
        expected = {
            "/api/plugins/load": (
                "PluginLoadResponse",
                {"200", "400", "404", "502", "503"},
            ),
            "/api/plugins/enable": (
                "PluginLifecycleResponse",
                {"200", "400", "502", "503"},
            ),
            "/api/plugins/disable": (
                "PluginLifecycleResponse",
                {"200", "400", "502", "503"},
            ),
        }
        forbidden = {
            "runtime",
            "root",
            "path",
            "entry_point",
            "entrypoint",
            "command",
            "environment",
            "timeout",
            "worker_pid",
            "generation",
        }
        for path, (response_name, response_codes) in expected.items():
            with self.subTest(path=path):
                operation = self.spec["paths"][path]["post"]
                self.assertIn("worker-isolated", operation["description"].lower())
                request_schema = operation["requestBody"]["content"][
                    "application/json"
                ]["schema"]
                self.assertEqual(set(request_schema["properties"]), {"plugin_id"})
                self.assertEqual(request_schema["required"], ["plugin_id"])
                self.assertFalse(request_schema.get("additionalProperties", True))
                self.assertTrue(forbidden.isdisjoint(request_schema["properties"]))
                self.assertEqual(
                    operation["responses"]["200"]["content"][
                        "application/json"
                    ]["schema"],
                    {"$ref": f"#/components/schemas/{response_name}"},
                )
                self.assertEqual(set(operation["responses"]), response_codes)
                self.assertNotIn("PLUGIN_WORKER_EXITED", json.dumps(operation))

        _assert_json_shape(
            self,
            self.spec,
            {"$ref": "#/components/schemas/PluginLoadResponse"},
            {
                "plugin_id": "event-logger",
                "name": "Event Logger",
                "status": "loaded",
            },
            "plugin load response",
        )
        _assert_json_shape(
            self,
            self.spec,
            {"$ref": "#/components/schemas/PluginLifecycleResponse"},
            {"success": True, "plugin_id": "event-logger"},
            "plugin lifecycle response",
        )
        _assert_json_shape(
            self,
            self.spec,
            {"$ref": "#/components/schemas/PluginLoadResponse"},
            {
                "plugin_id": "event-logger",
                "name": "Event Logger",
                "status": "error",
            },
            "plugin load error response",
        )
        _assert_json_shape(
            self,
            self.spec,
            {"$ref": "#/components/schemas/PluginLifecycleResponse"},
            {"success": False, "plugin_id": "event-logger"},
            "plugin lifecycle false response",
        )

    def test_capability_registry_path_is_read_only_and_schema_bound(self):
        path = self.spec["paths"]["/api/capabilities/registry"]
        self.assertEqual(set(path), {"get"})

        operation = path["get"]
        self.assertEqual(operation["operationId"], "listCapabilities")
        parameters = {
            parameter["name"]: parameter
            for parameter in operation["parameters"]
        }
        self.assertEqual(
            set(parameters),
            {"q", "kind", "compatible_only", "max_risk", "limit"},
        )
        for parameter in parameters.values():
            self.assertEqual(parameter["in"], "query")
            self.assertFalse(parameter.get("required", False))

        self.assertEqual(
            parameters["q"]["schema"],
            {"type": "string", "default": "", "maxLength": 256},
        )
        self.assertEqual(
            parameters["kind"]["schema"]["enum"],
            ["skill", "plugin", "role_tool", "ui_component"],
        )
        self.assertEqual(
            parameters["compatible_only"]["schema"],
            {"type": "boolean", "default": False},
        )
        self.assertEqual(
            parameters["max_risk"]["schema"],
            {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "default": "high",
            },
        )
        self.assertEqual(
            parameters["limit"]["schema"],
            {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        )

        responses = operation["responses"]
        self.assertEqual(set(responses), {"200", "400", "413", "502", "503"})
        self.assertIn("INVALID_REQUEST", responses["400"]["description"])
        self.assertIn(
            "CAPABILITY_REGISTRY_UNAVAILABLE",
            responses["503"]["description"],
        )

        schema = responses["200"]["content"]["application/json"]["schema"]
        self.assertEqual(
            schema,
            {"$ref": "#/components/schemas/CapabilityRegistryResponse"},
        )
        capability = {
            "schema_version": 1,
            "capability_id": "skill:memory-keeper",
            "kind": "skill",
            "name": "Memory Keeper",
            "version": None,
            "description": "Local memory management",
            "relative_path": "skills/memory-keeper",
            "entrypoint": "skills/memory-keeper/SKILL.md",
            "lifecycle": "discovered",
            "permissions": ["memory.read"],
            "compatibility": {
                "constraints": {"python": ">=3.10"},
                "status": "compatible",
                "reasons": [],
            },
            "provenance": {
                "source_url": "https://example.invalid/memory-keeper",
                "license": "MIT",
                "sha256": "a" * 64,
                "status": "verified",
            },
            "health": {"status": "healthy", "issues": []},
            "risk": {"level": "low", "reasons": []},
        }
        _assert_json_shape(
            self,
            self.spec,
            schema,
            {
                "schema_version": 1,
                "capabilities": [capability],
                "count": 1,
                "issues": ["skill_invalid:broken:read_failed"],
            },
            "capability registry",
        )

        record_schema = self.spec["components"]["schemas"]["CapabilityRecord"]
        self.assertFalse(record_schema["additionalProperties"])
        self.assertNotIn("match", record_schema["properties"])
        self.assertEqual(
            record_schema["properties"]["kind"]["enum"],
            ["skill", "plugin", "role_tool", "ui_component"],
        )
        self.assertIn(
            "role_tool",
            record_schema["properties"]["capability_id"]["pattern"],
        )
        self.assertEqual(
            set(record_schema["required"]),
            set(capability),
        )
        entrypoint_schema = record_schema["properties"]["entrypoint"]
        self.assertEqual(
            entrypoint_schema.get("pattern"),
            record_schema["properties"]["relative_path"]["pattern"],
        )
        response_schema = self.spec["components"]["schemas"]["CapabilityRegistryResponse"]
        self.assertEqual(
            set(response_schema["required"]),
            {"schema_version", "capabilities", "count", "issues"},
        )
        self.assertEqual(response_schema["properties"]["issues"]["maxItems"], 100)
        for invalid_entrypoint in (
            "C:/outside/plugin.py",
            "/outside/plugin.py",
            "../outside/plugin.py",
            "skills\\outside.py",
        ):
            with self.subTest(entrypoint=invalid_entrypoint):
                invalid_capability = {
                    **capability,
                    "entrypoint": invalid_entrypoint,
                }
                with self.assertRaises(AssertionError):
                    _assert_json_shape(
                        self,
                        self.spec,
                        schema,
                        {
                            "schema_version": 1,
                            "capabilities": [invalid_capability],
                            "count": 1,
                        },
                        "capability registry",
                    )
        self.assertNotIn("root", parameters)
        self.assertNotIn("path", parameters)
        self.assertNotIn("archive", parameters)
        self.assertNotIn("lifecycle", parameters)

    def test_synchronous_role_routes_declare_terminable_worker_contract(self):
        paths = self.spec["paths"]
        single_paths = (
            "/api/roles/dispatch",
            "/api/roles/dispatch_by_cap",
        )
        for path in (*single_paths, "/api/roles/batch_dispatch"):
            description = paths[path]["post"].get("description", "")
            self.assertIn("terminable Worker", description, path)

        expected_worker_failures = (
            "ROLE_WORKER_UNAVAILABLE",
            "ROLE_WORKER_INVALID_RESULT",
            "ROLE_TASK_TERMINATION_UNCONFIRMED",
        )
        for path in single_paths:
            description = paths[path]["post"]["responses"]["503"]["description"]
            for code in expected_worker_failures:
                self.assertIn(code, description, path)

        batch_503 = paths["/api/roles/batch_dispatch"]["post"]["responses"][
            "503"
        ]["description"]
        self.assertIn("Core API", batch_503)
        self.assertIn("proxy", batch_503.lower())
        self.assertIn("positional results", batch_503)
        self.assertIn("200", batch_503)
        for code in expected_worker_failures:
            self.assertNotIn(code, batch_503)

        generic_description = paths["/api/orchestrator/dispatch"]["post"].get(
            "description", ""
        )
        self.assertNotIn("terminable Worker", generic_description)

    def test_agent_worker_outcomes_are_declared(self):
        outcomes = self.spec["components"]["schemas"]["AgentResult"]["properties"]["status"]["enum"]
        for outcome in (
            "completed",
            "error",
            "busy",
            "timeout",
            "cancelled",
            "crashed",
            "failed",
        ):
            self.assertIn(outcome, outcomes)

    def test_role_task_lifecycle_paths_are_declared(self):
        for path in (
            "/api/roles/tasks",
            "/api/roles/tasks/{task_id}",
            "/api/roles/tasks/{task_id}/cancel",
        ):
            self.assertIn(path, self.spec["paths"])

    def test_role_task_lifecycle_schemas_and_errors_are_declared(self):
        schemas = self.spec["components"]["schemas"]
        for schema_name in (
            "WorkerTaskRequest",
            "WorkerTaskRecord",
            "WorkerTaskListResponse",
        ):
            self.assertIn(schema_name, schemas)

        create = self.spec["paths"]["/api/roles/tasks"]["post"]
        request_schema = create["requestBody"]["content"]["application/json"]["schema"]
        _assert_json_shape(
            self,
            self.spec,
            request_schema,
            {"role_name": "engineer", "prompt": "review", "timeout": 30},
            "role task request",
        )
        record = {
            "protocol_version": 1,
            "task_id": "task-abc",
            "attempt_id": "attempt-abc",
            "role_name": "engineer",
            "status": "running",
            "created_at": "2026-07-19T00:00:00+00:00",
            "updated_at": "2026-07-19T00:00:00+00:00",
            "timeout_seconds": 30,
            "result": None,
            "error": "",
            "worker_pid": 42,
            "last_heartbeat": None,
            "last_event_sequence": 0,
            "termination_confirmed": False,
        }
        create_schema = create["responses"]["202"]["content"]["application/json"]["schema"]
        _assert_json_shape(self, self.spec, create_schema, record, "role task create")

        record_fields = set(record)
        record_schema = schemas["WorkerTaskRecord"]
        self.assertEqual(set(record_schema["required"]), record_fields)
        self.assertEqual(set(record_schema["properties"]), record_fields)
        self.assertFalse(record_schema["additionalProperties"])

        for path, method, status in (
            ("/api/roles/tasks/{task_id}", "get", "200"),
            ("/api/roles/tasks/{task_id}/cancel", "post", "200"),
        ):
            success_schema = self.spec["paths"][path][method]["responses"][status][
                "content"
            ]["application/json"]["schema"]
            self.assertEqual(
                success_schema,
                {"$ref": "#/components/schemas/WorkerTaskRecord"},
            )
            _assert_json_shape(
                self,
                self.spec,
                success_schema,
                record,
                f"{method} {path}",
            )

        list_operation = self.spec["paths"]["/api/roles/tasks"]["get"]
        self.assertEqual(list_operation["parameters"][0]["schema"]["maximum"], 100)
        list_schema = list_operation["responses"]["200"]["content"]["application/json"]["schema"]
        _assert_json_shape(
            self,
            self.spec,
            list_schema,
            {"tasks": [record], "count": 1},
            "role task list",
        )

        expected_errors = {
            ("/api/roles/tasks", "post"): {"400", "404", "413", "503"},
            ("/api/roles/tasks", "get"): {"400"},
            ("/api/roles/tasks/{task_id}", "get"): {"404"},
            ("/api/roles/tasks/{task_id}/cancel", "post"): {"404", "409"},
        }
        for (path, method), statuses in expected_errors.items():
            responses = self.spec["paths"][path][method]["responses"]
            self.assertTrue(statuses.issubset(responses), f"{method} {path}")
            for status in statuses:
                self.assertEqual(
                    responses[status]["content"]["application/json"]["schema"],
                    {"$ref": "#/components/schemas/ErrorResponse"},
                )

    def test_role_task_request_does_not_expose_worker_execution_controls(self):
        request_schema = self.spec["components"]["schemas"]["WorkerTaskRequest"]
        self.assertFalse(request_schema["additionalProperties"])
        self.assertEqual(
            set(request_schema["properties"]),
            {"role_name", "prompt", "timeout"},
        )
        forbidden = {
            "runner",
            "command",
            "env",
            "cwd",
            "capability_token",
            "capabilityToken",
        }
        self.assertTrue(forbidden.isdisjoint(request_schema["properties"]))

    def test_role_task_terminal_status_requires_confirmed_termination(self):
        schema = {"$ref": "#/components/schemas/WorkerTaskRecord"}
        record = {
            "protocol_version": 1,
            "task_id": "task-abc",
            "attempt_id": "attempt-abc",
            "role_name": "engineer",
            "status": "running",
            "created_at": "2026-07-19T00:00:00+00:00",
            "updated_at": "2026-07-19T00:00:00+00:00",
            "timeout_seconds": 30,
            "result": None,
            "error": "",
            "worker_pid": 42,
            "last_heartbeat": None,
            "last_event_sequence": 0,
            "termination_confirmed": False,
        }

        for unconfirmed_status in (
            "queued",
            "running",
            "succeeded",
            "failed",
            "crashed",
        ):
            valid = {**record, "status": unconfirmed_status}
            _assert_json_shape(
                self,
                self.spec,
                schema,
                valid,
                f"unconfirmed {unconfirmed_status}",
            )
        for terminal_status in ("timeout", "cancelled"):
            invalid = {**record, "status": terminal_status}
            with self.assertRaises(AssertionError):
                _assert_json_shape(
                    self,
                    self.spec,
                    schema,
                    invalid,
                    terminal_status,
                )
            valid = {**invalid, "termination_confirmed": True}
            _assert_json_shape(
                self,
                self.spec,
                schema,
                valid,
                f"confirmed {terminal_status}",
            )

    def test_express_api_fallback_is_documented(self):
        fallback = self.contract["x-jarvis-api-fallback"]
        self.assertEqual(fallback["status"], 404)
        self.assertEqual(fallback["error_code"], "API_NOT_FOUND")
        self.assertEqual(
            fallback["response_schema"],
            {"$ref": "#/components/schemas/ErrorResponse"},
        )

    def test_express_git_paths_are_declared_as_express_only(self):
        for path in ("/api/git/status", "/api/git/log", "/api/git/branches"):
            with self.subTest(path=path):
                path_item = self.contract["paths"][path]
                self.assertEqual(
                    path_item.get("x-jarvis-implementations"),
                    ["frontend/server.js"],
                )
                self.assertEqual(set(path_item), {"x-jarvis-implementations", "get"})
                self.assertEqual(
                    path_item["get"]["responses"]["500"]["content"][
                        "application/json"
                    ]["schema"],
                    {"$ref": "#/components/schemas/ErrorResponse"},
                )

    def test_express_git_response_schemas_match_runtime_shapes(self):
        status_schema = self.contract["components"]["schemas"]["GitStatus"]
        _assert_json_shape(
            self,
            self.contract,
            status_schema,
            {
                "branch": "codex/jarvis-command-center",
                "clean": False,
                "changedFiles": [
                    {
                        "status": " M",
                        "file": "frontend/src/App.tsx",
                        "staged": False,
                    },
                ],
                "count": 1,
            },
            "git status",
        )

        log_schema = self.contract["components"]["schemas"]["GitLogResponse"]
        _assert_json_shape(
            self,
            self.contract,
            log_schema,
            {
                "commits": [
                    {
                        "hash": "abc12345",
                        "author": "Codex",
                        "email": "codex@example.com",
                        "date": "2026-07-10T10:00:00+08:00",
                        "subject": "feat: command center",
                    },
                ],
            },
            "git log",
        )

        branches_schema = self.contract["components"]["schemas"][
            "GitBranchesResponse"
        ]
        _assert_json_shape(
            self,
            self.contract,
            branches_schema,
            {"branches": ["main", "codex/jarvis-command-center"]},
            "git branches",
        )

    def test_declared_json_error_responses_use_error_response_schema(self):
        for path, operations in self.contract["paths"].items():
            for method, operation in operations.items():
                if method.startswith("x-"):
                    continue
                for status, response in operation.get("responses", {}).items():
                    if status[0] not in "45":
                        continue
                    content = response.get("content", {}).get("application/json")
                    if content is None:
                        continue
                    self.assertEqual(
                        content["schema"],
                        {"$ref": "#/components/schemas/ErrorResponse"},
                        f"{method.upper()} {path} {status}",
                    )

    def test_proxy_error_responses_are_declared(self):
        expected = {
            ("/api/ollama/status", "get"): {"502", "503"},
            ("/api/ollama/models", "get"): {"502", "503"},
            ("/api/system/stats", "get"): {"500"},
            ("/api/plugins", "get"): {"502", "503"},
            ("/api/capabilities/registry", "get"): {"400", "502", "503"},
            ("/api/memory/entries", "get"): {"502", "503"},
            ("/api/events", "get"): {"502", "503"},
            ("/api/orchestrator/agents", "get"): {"502", "503"},
            ("/api/orchestrator/history", "get"): {"400", "502", "503"},
            ("/api/orchestrator/dispatch", "post"): {"413", "502", "503"},
            ("/api/terminal/execute", "post"): {"502", "503"},
        }
        for (path, method), statuses in expected.items():
            responses = self.contract["paths"][path][method]["responses"]
            self.assertTrue(statuses.issubset(responses), f"{method} {path}")

    def test_schema_validation_enforces_const_minimum_and_strict_integer(self):
        schema = {
            "type": "object",
            "required": ["status", "count"],
            "properties": {
                "status": {"type": "string", "const": "healthy"},
                "count": {"type": "integer", "minimum": 0},
            },
        }
        with self.assertRaises(AssertionError):
            _assert_json_shape(self, self.contract, schema, {
                "status": "broken",
                "count": 0,
            })
        with self.assertRaises(AssertionError):
            _assert_json_shape(self, self.contract, schema, {
                "status": "healthy",
                "count": -1,
            })
        with self.assertRaises(AssertionError):
            _assert_json_shape(self, self.contract, schema, {
                "status": "healthy",
                "count": True,
            })

        maximum_schema = {
            "type": "object",
            "required": ["priority"],
            "properties": {
                "priority": {"type": "integer", "minimum": 0, "maximum": 3},
            },
        }
        _assert_json_shape(
            self,
            self.contract,
            maximum_schema,
            {"priority": 3},
        )
        with self.assertRaises(AssertionError):
            _assert_json_shape(
                self,
                self.contract,
                maximum_schema,
                {"priority": 4},
            )

    def test_schema_validation_accepts_any_matching_union_type(self):
        schema = {"type": ["number", "string", "null"]}
        _assert_json_shape(self, self.contract, schema, "123")

    def test_schema_validation_enforces_pattern(self):
        schema = {"type": "string", "pattern": r"\S"}
        _assert_json_shape(self, self.contract, schema, "analyzer")
        with self.assertRaises(AssertionError):
            _assert_json_shape(self, self.contract, schema, " \t")

    def test_stable_shared_paths_are_declared(self):
        self.assertIn("get", self.contract["paths"]["/api/health"])
        self.assertIn("get", self.contract["paths"]["/api/system/stats"])
        self.assertIn("get", self.contract["paths"]["/api/ollama/token-usage"])
        self.assertIn("get", self.contract["paths"]["/api/orchestrator/agents"])
        self.assertIn("get", self.contract["paths"]["/api/orchestrator/history"])
        self.assertIn("get", self.contract["paths"]["/api/capabilities/registry"])
        self.assertIn("post", self.contract["paths"]["/api/orchestrator/dispatch"])

    def test_shared_orchestrator_subset_has_error_contracts(self):
        expected = {
            ("/api/orchestrator/agents", "get"): {"200", "502", "503"},
            ("/api/orchestrator/history", "get"): {"200", "400", "502", "503"},
            ("/api/orchestrator/dispatch", "post"): {
                "200",
                "400",
                "413",
                "502",
                "503",
            },
        }
        for (path, method), statuses in expected.items():
            self.assertTrue(
                statuses.issubset(self.contract["paths"][path][method]["responses"]),
                f"{method} {path}",
            )
        self.assertIn("get", self.contract["paths"]["/api/ollama/status"])
        self.assertIn("get", self.contract["paths"]["/api/ollama/models"])
        self.assertIn("post", self.contract["paths"]["/api/terminal/execute"])

    def test_orchestrator_request_contract_declares_defaults_bounds_and_patterns(self):
        history_parameters = self.contract["paths"][
            "/api/orchestrator/history"
        ]["get"]["parameters"]
        limit_schema = next(
            parameter["schema"]
            for parameter in history_parameters
            if parameter["name"] == "limit" and parameter["in"] == "query"
        )
        self.assertEqual(
            limit_schema,
            {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
        )

        operation = self.contract["paths"]["/api/orchestrator/dispatch"]["post"]
        request_schema = operation["requestBody"]["content"]["application/json"][
            "schema"
        ]
        properties = request_schema["properties"]
        self.assertEqual(
            properties["timeout"],
            {"type": "integer", "default": 300, "minimum": 1, "maximum": 300},
        )
        self.assertEqual(
            properties["priority"],
            {"type": "integer", "default": 1, "minimum": 0, "maximum": 3},
        )
        for field in ("agent_name", "prompt"):
            self.assertIn("pattern", properties[field], field)
            _assert_json_shape(
                self,
                self.contract,
                properties[field],
                "non-blank",
                field,
            )
            with self.assertRaises(AssertionError, msg=field):
                _assert_json_shape(
                    self,
                    self.contract,
                    properties[field],
                    " \t\n",
                    field,
                )

        self.assertEqual(
            operation["responses"]["413"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/ErrorResponse"},
        )

    def test_terminal_access_failures_are_declared(self):
        responses = self.contract["paths"]["/api/terminal/execute"]["post"][
            "responses"
        ]
        for status in ("401", "403"):
            schema = responses[status]["content"]["application/json"]["schema"]
            _assert_json_shape(
                self,
                self.contract,
                schema,
                {"error": {"code": "TERMINAL_DISABLED", "message": "disabled"}},
                status,
            )

    def test_terminal_execution_success_is_declared(self):
        responses = self.contract["paths"]["/api/terminal/execute"]["post"][
            "responses"
        ]
        schema = responses["200"]["content"]["application/json"]["schema"]
        _assert_json_shape(
            self,
            self.contract,
            schema,
            {
                "command_id": "api-contract",
                "exit_code": 0,
                "stdout": "capability-contract\n",
                "stderr": "",
                "duration": 0.01,
                "success": True,
                "risk_level": "safe",
                "timestamp": "2026-07-12T00:00:00",
            },
            "200",
        )

    def test_stream_contract_is_declared(self):
        operation = self.contract["paths"]["/api/ollama/chat/stream"]["get"]
        parameters = {
            parameter["name"]: parameter
            for parameter in operation["parameters"]
        }
        self.assertEqual(parameters["model"]["schema"]["maxLength"], 32768)
        self.assertEqual(parameters["messages"]["schema"]["maxLength"], 32768)
        query_limit_schema = operation["responses"]["413"]["content"][
            "application/json"
        ]["schema"]
        _assert_json_shape(
            self,
            self.contract,
            query_limit_schema,
            {
                "error": {
                    "code": "REQUEST_QUERY_TOO_LARGE",
                    "message": "Request query exceeds the 32 KiB limit",
                }
            },
            "stream query limit",
        )
        stream_schema = operation["responses"]["200"]["content"][
            "text/event-stream"
        ]["schema"]
        self.assertEqual(stream_schema["type"], "string")

        _assert_json_shape(
            self,
            self.contract,
            {"$ref": "#/components/schemas/SseContentFrame"},
            {
                "model": "fixture-model:latest",
                "content": "OK",
                "done": False,
                "prompt_eval_count": 10,
                "eval_count": 7,
            },
            "stream content",
        )
        _assert_json_shape(
            self,
            self.contract,
            {"$ref": "#/components/schemas/SseErrorFrame"},
            {
                "error": {
                    "code": "OLLAMA_STREAM_ERROR",
                    "message": "fixture failure",
                }
            },
            "stream error",
        )

        samples = {
            "/api/plugins": {
                "plugins": [{
                    "id": "event-logger",
                    "name": "Event Logger",
                    "version": "1.0.0",
                    "status": "enabled",
                    "permissions": ["events"],
                }],
            },
            "/api/memory/entries": {
                "entries": [{
                    "id": "memory-1",
                    "type": "project",
                    "title": "Contract fixture",
                    "content": "Stable memory response",
                    "created_at": "2026-07-12T00:00:00",
                    "tags": ["contract"],
                    "access_count": 0,
                }],
            },
            "/api/events": {
                "events": [{
                    "type": "plugin.loaded",
                    "payload": "event-logger",
                    "timestamp": "2026-07-12T00:00:00",
                    "source": "plugin-manager",
                }],
            },
        }
        for path, sample in samples.items():
            self.assertIn(path, self.contract["paths"])
            self.assertIn("get", self.contract["paths"][path])
            schema = self.contract["paths"][path]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            _assert_json_shape(self, self.contract, schema, sample, path)

    def test_every_query_operation_declares_shared_query_limit(self):
        expected_error = {
            "error": {
                "code": "REQUEST_QUERY_TOO_LARGE",
                "message": "Request query exceeds the 32 KiB limit",
            }
        }
        for path, path_item in self.contract["paths"].items():
            for method, operation in path_item.items():
                if method.startswith("x-"):
                    continue
                parameters = operation.get("parameters", [])
                if not any(parameter.get("in") == "query" for parameter in parameters):
                    continue
                with self.subTest(method=method, path=path):
                    schema = operation["responses"]["413"]["content"][
                        "application/json"
                    ]["schema"]
                    _assert_json_shape(
                        self,
                        self.contract,
                        schema,
                        expected_error,
                        f"{method.upper()} {path} query limit",
                    )

    def test_post_stream_contract_is_declared(self):
        operation = self.contract["paths"]["/api/ollama/chat/stream"]["post"]
        request_schema = operation["requestBody"]["content"][
            "application/json"
        ]["schema"]
        _assert_json_shape(
            self,
            self.contract,
            request_schema,
            {
                "model": "fixture-model:latest",
                "messages": [{"role": "user", "content": "ping"}],
            },
            "POST stream request",
        )

        responses = operation["responses"]
        self.assertIn("text/event-stream", responses["200"]["content"])
        error_schema = responses["400"]["content"]["application/json"]["schema"]
        _assert_json_shape(
            self,
            self.contract,
            error_schema,
            {"error": {"code": "INVALID_REQUEST", "message": "invalid"}},
            "POST stream invalid request",
        )

    def test_post_stream_body_limit_is_declared(self):
        responses = self.contract["paths"]["/api/ollama/chat/stream"][
            "post"
        ]["responses"]
        schema = responses["413"]["content"]["application/json"]["schema"]
        _assert_json_shape(
            self,
            self.contract,
            schema,
            {
                "error": {
                    "code": "REQUEST_BODY_TOO_LARGE",
                    "message": "Request body exceeds the 32 KiB limit",
                }
            },
            "POST stream body limit",
        )

    def test_nonstream_chat_contract_is_declared(self):
        operation = self.contract["paths"]["/api/ollama/chat"]["post"]
        request_schema = operation["requestBody"]["content"][
            "application/json"
        ]["schema"]
        _assert_json_shape(
            self,
            self.contract,
            request_schema,
            {
                "model": "fixture-model:latest",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
            },
            "non-stream chat request",
        )

        success_schema = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        _assert_json_shape(
            self,
            self.contract,
            success_schema,
            {
                "model": "fixture-model:latest",
                "message": {"role": "assistant", "content": "OK"},
                "done": True,
                "prompt_eval_count": 10,
                "eval_count": 7,
            },
            "non-stream chat response",
        )

        for status in ("400", "413", "502"):
            schema = operation["responses"][status]["content"][
                "application/json"
            ]["schema"]
            _assert_json_shape(
                self,
                self.contract,
                schema,
                {
                    "error": {
                        "code": "OLLAMA_UPSTREAM_ERROR",
                        "message": "Ollama chat request failed",
                    }
                },
                f"non-stream chat {status}",
            )

    def test_fastapi_routes_cover_contract(self):
        import main_fastapi

        routes = {
            (method.lower(), route.path)
            for route in main_fastapi.app.routes
            for method in getattr(route, "methods", set())
        }
        for path, operations in self.contract["paths"].items():
            for method in operations:
                if method.startswith("x-"):
                    continue
                if path.startswith("/api/git/"):
                    continue
                self.assertIn((method, path), routes)

    def test_all_implementations_match_stable_response_schemas(self):
        from fastapi.testclient import TestClient

        import main_fastapi
        from core.kernel.ollama_manager import OllamaManager

        httpserver_module = _load_httpserver_module()
        ollama_server = HTTPServer(("127.0.0.1", 0), _OllamaFixtureHandler)
        ollama_thread = Thread(target=ollama_server.serve_forever, daemon=True)
        ollama_thread.start()
        ollama_url = f"http://127.0.0.1:{ollama_server.server_port}"

        http_ollama = OllamaManager(base_url=ollama_url)
        with patch.object(
            httpserver_module,
            "OllamaManager",
            return_value=http_ollama,
        ):
            http_state = httpserver_module.AppState()
        http_server = httpserver_module.create_http_server(
            "127.0.0.1",
            0,
            app_state=http_state,
        )
        http_port = http_server.server_address[1]
        http_thread = Thread(target=http_server.serve_forever, daemon=True)
        http_thread.start()

        fastapi_ollama = OllamaManager(base_url=ollama_url)
        with patch.object(
            main_fastapi,
            "OllamaManager",
            return_value=fastapi_ollama,
        ):
            fastapi_state = main_fastapi.AppState()
        fastapi_app = main_fastapi.create_app(fastapi_state)

        observed_dispatch_options = []

        def fixture_handler(_task):
            observed_dispatch_options.append((_task.timeout, _task.priority))
            return "fixture result"

        http_state.orchestrator.register_in_process(
            "analyzer",
            fixture_handler,
            capabilities=["analysis"],
        )
        fastapi_state.orchestrator.register_in_process(
            "analyzer",
            fixture_handler,
            capabilities=["analysis"],
        )

        express_port = _free_port()
        express_env = {
            **os.environ,
            "PORT": str(express_port),
            "JARVIS_HOST": "127.0.0.1",
            "OLLAMA_HOST": "127.0.0.1",
            "OLLAMA_PORT": str(ollama_server.server_port),
        }
        core_url = f"http://127.0.0.1:{http_port}"
        express_env["JARVIS_CORE_API_URL"] = core_url
        express_env["JARVIS_TERMINAL_ENABLED"] = "true"
        express_env["JARVIS_TERMINAL_TOKEN"] = "contract-terminal-token"
        express = subprocess.Popen(
            ["node", "server.js"],
            cwd=ROOT / "frontend",
            env=express_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        try:
            express_url = f"http://127.0.0.1:{express_port}"
            _wait_for_health(express_url, express)
            clients = {
                "python-http": lambda path: _get_json(
                    f"{core_url}{path}"
                ),
                "express": lambda path: _get_json(f"{express_url}{path}"),
            }

            with TestClient(fastapi_app) as fastapi_client:
                for path in (
                    "/api/health",
                    "/api/system/stats",
                    "/api/ollama/status",
                    "/api/ollama/models",
                    "/api/ollama/token-usage",
                    "/api/plugins",
                    "/api/memory/entries",
                    "/api/events",
                    "/api/orchestrator/agents",
                    "/api/orchestrator/history",
                ):
                    self.assertIn(path, self.contract["paths"])
                    operation = self.contract["paths"][path]["get"]
                    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
                    for name, request in clients.items():
                        status, body = request(path)
                        self.assertEqual(status, 200, f"{name} {path}: {body}")
                        _assert_json_shape(self, self.contract, schema, body, f"{name} {path}")

                    response = fastapi_client.get(path)
                    self.assertEqual(response.status_code, 200, "fastapi")
                    _assert_json_shape(
                        self, self.contract, schema, response.json(), "fastapi"
                    )

                roles_list_schema = self.contract["paths"]["/api/roles"][
                    "get"
                ]["responses"]["200"]["content"]["application/json"]["schema"]
                for name, request in clients.items():
                    status, body = request("/api/roles")
                    self.assertEqual(status, 200, f"{name} /api/roles: {body}")
                    _assert_json_shape(
                        self, self.contract, roles_list_schema, body, f"{name} roles"
                    )
                    self.assertGreater(body["count"], 0, name)
                response = fastapi_client.get("/api/roles")
                self.assertEqual(response.status_code, 200, "fastapi roles")
                _assert_json_shape(
                    self, self.contract, roles_list_schema, response.json(), "fastapi"
                )

                role_schema = self.contract["paths"]["/api/roles/{role_name}"][
                    "get"
                ]["responses"]["200"]["content"]["application/json"]["schema"]
                for name, request in clients.items():
                    status, body = request("/api/roles/engineer")
                    self.assertEqual(status, 200, f"{name} role: {body}")
                    _assert_json_shape(
                        self, self.contract, role_schema, body, f"{name} role"
                    )
                    self.assertEqual(body["role"]["name"], "engineer", name)
                response = fastapi_client.get("/api/roles/engineer")
                self.assertEqual(response.status_code, 200, "fastapi role")
                _assert_json_shape(
                    self, self.contract, role_schema, response.json(), "fastapi"
                )

                role_not_found_schema = self.contract["paths"][
                    "/api/roles/{role_name}"
                ]["get"]["responses"]["404"]["content"]["application/json"]["schema"]
                for name, request in clients.items():
                    status, body = request("/api/roles/.test-missing-role")
                    self.assertEqual(status, 404, f"{name} missing role: {body}")
                    _assert_json_shape(
                        self, self.contract, role_not_found_schema, body, f"{name} 404"
                    )
                    self.assertEqual(body["error"]["code"], "ROLE_NOT_FOUND", name)
                response = fastapi_client.get("/api/roles/.test-missing-role")
                self.assertEqual(response.status_code, 404, "fastapi missing role")
                self.assertEqual(
                    response.json()["error"]["code"], "ROLE_NOT_FOUND", "fastapi"
                )

                role_dispatch_schema = self.contract["paths"][
                    "/api/roles/dispatch"
                ]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
                role_dispatch_payload = {
                    "role_name": "engineer",
                    "prompt": "write a unit test",
                    "timeout": 30,
                }

                def assert_exact_role_dispatch_result(name, body):
                    self.assertEqual(
                        set(body),
                        {"role_name", "task_id", "status", "message"},
                        name,
                    )
                    for field in ("role_name", "task_id", "status", "message"):
                        self.assertIsInstance(body[field], str, f"{name} {field}")
                    self.assertEqual(body["role_name"], "engineer", name)
                    self.assertTrue(body["task_id"], f"{name} outer task_id")

                role_dispatch_clients = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/roles/dispatch",
                        role_dispatch_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/roles/dispatch",
                        role_dispatch_payload,
                    ),
                }
                for name, request in role_dispatch_clients.items():
                    status, body = request()
                    self.assertEqual(status, 200, f"{name} role dispatch: {body}")
                    _assert_json_shape(
                        self,
                        self.contract,
                        role_dispatch_schema,
                        body,
                        f"{name} role dispatch",
                    )
                    assert_exact_role_dispatch_result(name, body)
                response = fastapi_client.post(
                    "/api/roles/dispatch",
                    json=role_dispatch_payload,
                )
                self.assertEqual(response.status_code, 200, "fastapi role dispatch")
                _assert_json_shape(
                    self,
                    self.contract,
                    role_dispatch_schema,
                    response.json(),
                    "fastapi role dispatch",
                )
                assert_exact_role_dispatch_result("fastapi", response.json())

                missing_role_dispatch = {"prompt": "no role name"}
                role_dispatch_400_schema = self.contract["paths"][
                    "/api/roles/dispatch"
                ]["post"]["responses"]["400"]["content"]["application/json"]["schema"]
                for name, request in {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/roles/dispatch",
                        missing_role_dispatch,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/roles/dispatch",
                        missing_role_dispatch,
                    ),
                }.items():
                    status, body = request()
                    self.assertEqual(status, 400, f"{name} role dispatch 400: {body}")
                    _assert_json_shape(
                        self, self.contract, role_dispatch_400_schema, body, name
                    )
                    self.assertEqual(body["error"]["code"], "INVALID_REQUEST", name)
                response = fastapi_client.post(
                    "/api/roles/dispatch",
                    json=missing_role_dispatch,
                )
                self.assertEqual(response.status_code, 400, "fastapi role dispatch 400")
                self.assertEqual(
                    response.json()["error"]["code"], "INVALID_REQUEST", "fastapi"
                )

                unknown_role_dispatch = {
                    "role_name": ".test-missing-role",
                    "prompt": "task",
                }
                role_dispatch_404_schema = self.contract["paths"][
                    "/api/roles/dispatch"
                ]["post"]["responses"]["404"]["content"]["application/json"]["schema"]
                for name, request in {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/roles/dispatch",
                        unknown_role_dispatch,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/roles/dispatch",
                        unknown_role_dispatch,
                    ),
                }.items():
                    status, body = request()
                    self.assertEqual(status, 404, f"{name} role dispatch 404: {body}")
                    _assert_json_shape(
                        self, self.contract, role_dispatch_404_schema, body, name
                    )
                    self.assertEqual(body["error"]["code"], "ROLE_NOT_FOUND", name)
                response = fastapi_client.post(
                    "/api/roles/dispatch",
                    json=unknown_role_dispatch,
                )
                self.assertEqual(response.status_code, 404, "fastapi role dispatch 404")
                self.assertEqual(
                    response.json()["error"]["code"], "ROLE_NOT_FOUND", "fastapi"
                )

                cap_dispatch_schema = self.contract["paths"][
                    "/api/roles/dispatch_by_cap"
                ]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
                cap_dispatch_payload = {"capability": "coding", "prompt": "fix bug"}
                for name, request in {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/roles/dispatch_by_cap",
                        cap_dispatch_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/roles/dispatch_by_cap",
                        cap_dispatch_payload,
                    ),
                }.items():
                    status, body = request()
                    self.assertEqual(status, 200, f"{name} cap dispatch: {body}")
                    _assert_json_shape(
                        self, self.contract, cap_dispatch_schema, body, name
                    )
                response = fastapi_client.post(
                    "/api/roles/dispatch_by_cap",
                    json=cap_dispatch_payload,
                )
                self.assertEqual(response.status_code, 200, "fastapi cap dispatch")
                _assert_json_shape(
                    self, self.contract, cap_dispatch_schema, response.json(), "fastapi"
                )

                unknown_cap_payload = {
                    "capability": ".test-missing-cap",
                    "prompt": "task",
                }
                cap_dispatch_404_schema = self.contract["paths"][
                    "/api/roles/dispatch_by_cap"
                ]["post"]["responses"]["404"]["content"]["application/json"]["schema"]
                for name, request in {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/roles/dispatch_by_cap",
                        unknown_cap_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/roles/dispatch_by_cap",
                        unknown_cap_payload,
                    ),
                }.items():
                    status, body = request()
                    self.assertEqual(status, 404, f"{name} cap dispatch 404: {body}")
                    _assert_json_shape(
                        self, self.contract, cap_dispatch_404_schema, body, name
                    )
                    self.assertEqual(
                        body["error"]["code"], "CAPABILITY_NOT_FOUND", name
                    )
                response = fastapi_client.post(
                    "/api/roles/dispatch_by_cap",
                    json=unknown_cap_payload,
                )
                self.assertEqual(response.status_code, 404, "fastapi cap dispatch 404")
                self.assertEqual(
                    response.json()["error"]["code"], "CAPABILITY_NOT_FOUND", "fastapi"
                )

                batch_schema = self.contract["paths"][
                    "/api/roles/batch_dispatch"
                ]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
                batch_payload = {
                    "tasks": [
                        {"role": "engineer", "prompt": "task 1"},
                        {"capability": "code_review", "prompt": "task 2"},
                    ]
                }
                for name, request in {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/roles/batch_dispatch",
                        batch_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/roles/batch_dispatch",
                        batch_payload,
                    ),
                }.items():
                    status, body = request()
                    self.assertEqual(status, 200, f"{name} batch dispatch: {body}")
                    _assert_json_shape(
                        self, self.contract, batch_schema, body, name
                    )
                    self.assertEqual(body["count"], 2, name)
                response = fastapi_client.post(
                    "/api/roles/batch_dispatch",
                    json=batch_payload,
                )
                self.assertEqual(response.status_code, 200, "fastapi batch dispatch")
                _assert_json_shape(
                    self, self.contract, batch_schema, response.json(), "fastapi"
                )

                dispatch_payload = {
                    "agent_name": "analyzer",
                    "prompt": "ping",
                    "timeout": 45,
                    "priority": 3,
                }
                dispatch_schema = self.contract["paths"][
                    "/api/orchestrator/dispatch"
                ]["post"]["responses"]["200"]["content"][
                    "application/json"
                ]["schema"]
                dispatch_clients = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/orchestrator/dispatch",
                        dispatch_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/orchestrator/dispatch",
                        dispatch_payload,
                    ),
                }
                for name, request in dispatch_clients.items():
                    status, body = request()
                    self.assertEqual(status, 200, f"{name} dispatch: {body}")
                    _assert_json_shape(
                        self,
                        self.contract,
                        dispatch_schema,
                        body,
                        f"{name} dispatch",
                    )
                    self.assertEqual(body["agent_name"], "analyzer", name)
                    self.assertEqual(body["result"], "fixture result", name)
                    self.assertEqual(body["status"], "success", name)

                fastapi_dispatch = fastapi_client.post(
                    "/api/orchestrator/dispatch",
                    json=dispatch_payload,
                )
                self.assertEqual(fastapi_dispatch.status_code, 200, "fastapi dispatch")
                _assert_json_shape(
                    self,
                    self.contract,
                    dispatch_schema,
                    fastapi_dispatch.json(),
                    "fastapi dispatch",
                )
                self.assertEqual(fastapi_dispatch.json()["agent_name"], "analyzer")
                self.assertEqual(fastapi_dispatch.json()["result"], "fixture result")
                self.assertEqual(fastapi_dispatch.json()["status"], "success")
                self.assertEqual(
                    observed_dispatch_options,
                    [(45, 3), (45, 3), (45, 3)],
                )

                default_dispatch_payload = {
                    "agent_name": "analyzer",
                    "prompt": "default dispatch options",
                }
                default_dispatch_requests = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/orchestrator/dispatch",
                        default_dispatch_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/orchestrator/dispatch",
                        default_dispatch_payload,
                    ),
                }
                for name, request in default_dispatch_requests.items():
                    status, body = request()
                    self.assertEqual(status, 200, f"{name} default dispatch: {body}")
                fastapi_default_dispatch = fastapi_client.post(
                    "/api/orchestrator/dispatch",
                    json=default_dispatch_payload,
                )
                self.assertEqual(
                    fastapi_default_dispatch.status_code,
                    200,
                    f"fastapi default dispatch: {fastapi_default_dispatch.text}",
                )
                self.assertEqual(
                    observed_dispatch_options[-3:],
                    [(300, 1), (300, 1), (300, 1)],
                )

                dispatch_error_schema = self.contract["paths"][
                    "/api/orchestrator/dispatch"
                ]["post"]["responses"]["400"]["content"][
                    "application/json"
                ]["schema"]
                invalid_dispatch_payload = {"agent_name": "analyzer"}
                invalid_dispatch_clients = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/orchestrator/dispatch",
                        invalid_dispatch_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/orchestrator/dispatch",
                        invalid_dispatch_payload,
                    ),
                }
                for name, request in invalid_dispatch_clients.items():
                    status, body = request()
                    self.assertEqual(status, 400, f"{name} invalid dispatch")
                    _assert_json_shape(
                        self,
                        self.contract,
                        dispatch_error_schema,
                        body,
                        f"{name} invalid dispatch",
                    )

                invalid_shape_payloads = [
                    [],
                    "not-an-object",
                    {"agent_name": 1, "prompt": "ping"},
                    {"agent_name": "analyzer", "prompt": 1},
                    {"agent_name": "   ", "prompt": "ping"},
                    {"agent_name": "analyzer", "prompt": "\t"},
                    {"agent_name": "analyzer", "prompt": "ping", "timeout": 0},
                    {"agent_name": "analyzer", "prompt": "ping", "timeout": 301},
                    {"agent_name": "analyzer", "prompt": "ping", "timeout": True},
                    {"agent_name": "analyzer", "prompt": "ping", "priority": -1},
                    {"agent_name": "analyzer", "prompt": "ping", "priority": 4},
                    {"agent_name": "analyzer", "prompt": "ping", "priority": True},
                ]
                for invalid_payload in invalid_shape_payloads:
                    for name, request in {
                        "python-http": lambda payload=invalid_payload: _post_json(
                            f"{core_url}/api/orchestrator/dispatch",
                            payload,
                        ),
                        "express": lambda payload=invalid_payload: _post_json(
                            f"{express_url}/api/orchestrator/dispatch",
                            payload,
                        ),
                    }.items():
                        status, body = request()
                        self.assertEqual(
                            status,
                            400,
                            f"{name} invalid dispatch shape {invalid_payload!r}",
                        )
                        _assert_json_shape(
                            self,
                            self.contract,
                            dispatch_error_schema,
                            body,
                            f"{name} invalid dispatch shape",
                        )

                    fastapi_invalid_shape = fastapi_client.post(
                        "/api/orchestrator/dispatch",
                        json=invalid_payload,
                    )
                    self.assertEqual(
                        fastapi_invalid_shape.status_code,
                        400,
                        f"fastapi invalid dispatch shape {invalid_payload!r}",
                    )
                    _assert_json_shape(
                        self,
                        self.contract,
                        dispatch_error_schema,
                        fastapi_invalid_shape.json(),
                        "fastapi invalid dispatch shape",
                    )

                unpaired_surrogate_bodies = [
                    b'{"agent_name":"\\ud800","prompt":"ping"}',
                    b'{"agent_name":"analyzer","prompt":"\\udfff"}',
                ]
                for raw_payload in unpaired_surrogate_bodies:
                    for name, request in {
                        "python-http": lambda payload=raw_payload: _post_raw_json(
                            f"{core_url}/api/orchestrator/dispatch",
                            payload,
                        ),
                        "express": lambda payload=raw_payload: _post_raw_json(
                            f"{express_url}/api/orchestrator/dispatch",
                            payload,
                        ),
                    }.items():
                        status, body = request()
                        self.assertEqual(status, 400, f"{name} unpaired surrogate")
                        _assert_json_shape(
                            self,
                            self.contract,
                            dispatch_error_schema,
                            body,
                            f"{name} unpaired surrogate",
                        )

                    fastapi_unpaired_surrogate = fastapi_client.post(
                        "/api/orchestrator/dispatch",
                        content=raw_payload,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(
                        fastapi_unpaired_surrogate.status_code,
                        400,
                        "fastapi unpaired surrogate",
                    )
                    _assert_json_shape(
                        self,
                        self.contract,
                        dispatch_error_schema,
                        fastapi_unpaired_surrogate.json(),
                        "fastapi unpaired surrogate",
                    )

                oversized_dispatch_body = json.dumps({
                    "agent_name": "analyzer",
                    "prompt": "x" * (32 * 1024),
                }).encode("utf-8")
                self.assertGreater(len(oversized_dispatch_body), 32 * 1024)
                dispatch_body_limit_schema = self.contract["paths"][
                    "/api/orchestrator/dispatch"
                ]["post"]["responses"]["413"]["content"]["application/json"][
                    "schema"
                ]
                oversized_dispatch_clients = {
                    "python-http": lambda: _post_raw_json(
                        f"{core_url}/api/orchestrator/dispatch",
                        oversized_dispatch_body,
                    ),
                    "express": lambda: _post_raw_json(
                        f"{express_url}/api/orchestrator/dispatch",
                        oversized_dispatch_body,
                    ),
                }
                for name, request in oversized_dispatch_clients.items():
                    status, body = request()
                    self.assertEqual(status, 413, f"{name} oversized dispatch")
                    _assert_json_shape(
                        self,
                        self.contract,
                        dispatch_body_limit_schema,
                        body,
                        f"{name} oversized dispatch",
                    )
                    self.assertEqual(
                        body["error"]["code"],
                        "REQUEST_BODY_TOO_LARGE",
                        name,
                    )

                fastapi_oversized_dispatch = fastapi_client.post(
                    "/api/orchestrator/dispatch",
                    content=oversized_dispatch_body,
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(
                    fastapi_oversized_dispatch.status_code,
                    413,
                    "fastapi oversized dispatch",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    dispatch_body_limit_schema,
                    fastapi_oversized_dispatch.json(),
                    "fastapi oversized dispatch",
                )
                self.assertEqual(
                    fastapi_oversized_dispatch.json()["error"]["code"],
                    "REQUEST_BODY_TOO_LARGE",
                    "fastapi oversized dispatch",
                )

                for name, request in {
                    "python-http": lambda: _get_json(
                        f"{core_url}/api/orchestrator/history?limit=abc"
                    ),
                    "express": lambda: _get_json(
                        f"{express_url}/api/orchestrator/history?limit=abc"
                    ),
                }.items():
                    status, body = request()
                    self.assertEqual(status, 400, f"{name} invalid history limit")
                    _assert_json_shape(
                        self,
                        self.contract,
                        self.contract["paths"]["/api/orchestrator/history"]["get"][
                            "responses"
                        ]["400"]["content"]["application/json"]["schema"],
                        body,
                        f"{name} invalid history limit",
                    )

                fastapi_invalid_history = fastapi_client.get(
                    "/api/orchestrator/history?limit=abc"
                )
                self.assertEqual(fastapi_invalid_history.status_code, 400)
                _assert_json_shape(
                    self,
                    self.contract,
                    self.contract["paths"]["/api/orchestrator/history"]["get"][
                        "responses"
                    ]["400"]["content"]["application/json"]["schema"],
                    fastapi_invalid_history.json(),
                    "fastapi invalid history limit",
                )

                fastapi_invalid_dispatch = fastapi_client.post(
                    "/api/orchestrator/dispatch",
                    json=invalid_dispatch_payload,
                )
                self.assertEqual(
                    fastapi_invalid_dispatch.status_code,
                    400,
                    "fastapi invalid dispatch",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    dispatch_error_schema,
                    fastapi_invalid_dispatch.json(),
                    "fastapi invalid dispatch",
                )

                chat_payload = {
                    "model": "fixture-model:latest",
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                }
                chat_clients = {
                    "python-http": lambda: _post_json(
                        f"http://127.0.0.1:{http_port}/api/ollama/chat",
                        chat_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/ollama/chat",
                        chat_payload,
                    ),
                }
                chat_success_schema = self.contract["paths"][
                    "/api/ollama/chat"
                ]["post"]["responses"]["200"]["content"][
                    "application/json"
                ]["schema"]
                for name, request in chat_clients.items():
                    status, body = request()
                    self.assertEqual(status, 200, name)
                    _assert_json_shape(
                        self,
                        self.contract,
                        chat_success_schema,
                        body,
                        name,
                    )
                fastapi_response = fastapi_client.post(
                    "/api/ollama/chat",
                    json=chat_payload,
                )
                self.assertEqual(fastapi_response.status_code, 200, "fastapi")
                _assert_json_shape(
                    self,
                    self.contract,
                    chat_success_schema,
                    fastapi_response.json(),
                    "fastapi",
                )

                chat_error_payload = {
                    "model": "fixture-error",
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                }
                chat_error_schema = self.contract["paths"][
                    "/api/ollama/chat"
                ]["post"]["responses"]["502"]["content"][
                    "application/json"
                ]["schema"]
                chat_error_clients = {
                    "python-http": lambda: _post_json(
                        f"http://127.0.0.1:{http_port}/api/ollama/chat",
                        chat_error_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/ollama/chat",
                        chat_error_payload,
                    ),
                }
                for name, request in chat_error_clients.items():
                    status, body = request()
                    self.assertEqual(status, 502, name)
                    _assert_json_shape(
                        self,
                        self.contract,
                        chat_error_schema,
                        body,
                        name,
                    )
                    self.assertEqual(
                        body["error"]["code"],
                        "OLLAMA_UPSTREAM_ERROR",
                        name,
                    )
                    self.assertEqual(
                        body["error"]["message"],
                        "Ollama chat request failed",
                        name,
                    )

                fastapi_chat_error = fastapi_client.post(
                    "/api/ollama/chat",
                    json=chat_error_payload,
                )
                self.assertEqual(fastapi_chat_error.status_code, 502, "fastapi")
                _assert_json_shape(
                    self,
                    self.contract,
                    chat_error_schema,
                    fastapi_chat_error.json(),
                    "fastapi",
                )
                self.assertEqual(
                    fastapi_chat_error.json()["error"]["code"],
                    "OLLAMA_UPSTREAM_ERROR",
                    "fastapi",
                )

                invalid_chat_response_payload = {
                    "model": "fixture-invalid",
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                }
                invalid_chat_response_clients = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/ollama/chat",
                        invalid_chat_response_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/ollama/chat",
                        invalid_chat_response_payload,
                    ),
                }
                for name, request in invalid_chat_response_clients.items():
                    status, body = request()
                    self.assertEqual(status, 502, name)
                    _assert_json_shape(
                        self,
                        self.contract,
                        chat_error_schema,
                        body,
                        name,
                    )
                    self.assertEqual(
                        body,
                        {
                            "error": {
                                "code": "OLLAMA_UPSTREAM_ERROR",
                                "message": "Ollama chat request failed",
                            }
                        },
                        name,
                    )

                fastapi_invalid_chat_response = fastapi_client.post(
                    "/api/ollama/chat",
                    json=invalid_chat_response_payload,
                )
                self.assertEqual(
                    fastapi_invalid_chat_response.status_code,
                    502,
                    "fastapi",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    chat_error_schema,
                    fastapi_invalid_chat_response.json(),
                    "fastapi",
                )
                self.assertEqual(
                    fastapi_invalid_chat_response.json(),
                    {
                        "error": {
                            "code": "OLLAMA_UPSTREAM_ERROR",
                            "message": "Ollama chat request failed",
                        }
                    },
                )

                stream_rejected_payload = {
                    "model": "fixture-model:latest",
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": True,
                }
                chat_invalid_schema = self.contract["paths"][
                    "/api/ollama/chat"
                ]["post"]["responses"]["400"]["content"][
                    "application/json"
                ]["schema"]
                stream_rejected_clients = {
                    "python-http": lambda: _post_error_body(
                        f"http://127.0.0.1:{http_port}/api/ollama/chat",
                        json.dumps(stream_rejected_payload).encode("utf-8"),
                    ),
                    "express": lambda: _post_error_body(
                        f"{express_url}/api/ollama/chat",
                        json.dumps(stream_rejected_payload).encode("utf-8"),
                    ),
                }
                for name, request in stream_rejected_clients.items():
                    status, raw_body = request()
                    self.assertEqual(status, 400, name)
                    body = json.loads(raw_body)
                    _assert_json_shape(
                        self,
                        self.contract,
                        chat_invalid_schema,
                        body,
                        name,
                    )
                    self.assertEqual(body["error"]["code"], "INVALID_REQUEST", name)

                fastapi_stream_rejected = fastapi_client.post(
                    "/api/ollama/chat",
                    json=stream_rejected_payload,
                )
                self.assertEqual(
                    fastapi_stream_rejected.status_code,
                    400,
                    "fastapi",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    chat_invalid_schema,
                    fastapi_stream_rejected.json(),
                    "fastapi",
                )
                self.assertEqual(
                    fastapi_stream_rejected.json()["error"]["code"],
                    "INVALID_REQUEST",
                    "fastapi",
                )

                usage_requests = {
                    **clients,
                    "fastapi": lambda path: (
                        fastapi_client.get(path).status_code,
                        fastapi_client.get(path).json(),
                    ),
                }
                expected_usage = {
                    "python-http": (153, 9),
                    "express": (17, 1),
                    "fastapi": (85, 5),
                }
                for name, request in usage_requests.items():
                    status, body = request("/api/ollama/token-usage")
                    self.assertEqual(status, 200, name)
                    expected_total, expected_samples = expected_usage[name]
                    self.assertEqual(
                        body["totals"]["total_tokens"], expected_total, name
                    )
                    self.assertEqual(len(body["samples"]), expected_samples, name)

                stream_query = urllib.parse.urlencode({
                    "model": "fixture-model:latest",
                    "messages": json.dumps([{"role": "user", "content": "ping"}]),
                })
                stream_path = f"/api/ollama/chat/stream?{stream_query}"
                stream_content_schema = {
                    "$ref": "#/components/schemas/SseContentFrame"
                }
                stream_clients = {
                    "python-http": lambda: _get_sse_payloads(
                        f"{core_url}{stream_path}"
                    ),
                    "express": lambda: _get_sse_payloads(
                        f"{express_url}{stream_path}"
                    ),
                }
                for name, request in stream_clients.items():
                    status, payloads = request()
                    self.assertEqual(status, 200, name)
                    self.assertEqual(payloads.count("[DONE]"), 1, name)
                    frames = [
                        json.loads(payload)
                        for payload in payloads
                        if payload != "[DONE]"
                    ]
                    self.assertEqual(
                        sum(frame.get("done") is True for frame in frames),
                        1,
                        name,
                    )
                    _assert_json_shape(
                        self,
                        self.contract,
                        stream_content_schema,
                        frames[0],
                        name,
                    )

                fastapi_stream = fastapi_client.get(
                    "/api/ollama/chat/stream",
                    params={
                        "model": "fixture-model:latest",
                        "messages": json.dumps([{"role": "user", "content": "ping"}]),
                    },
                )
                self.assertEqual(fastapi_stream.status_code, 200, "fastapi")
                fastapi_payloads = [
                    line.removeprefix("data:").strip()
                    for event in fastapi_stream.text.replace("\r\n", "\n").split("\n\n")
                    for line in event.splitlines()
                    if line.startswith("data:")
                ]
                self.assertEqual(fastapi_payloads.count("[DONE]"), 1, "fastapi")
                fastapi_frames = [
                    json.loads(payload)
                    for payload in fastapi_payloads
                    if payload != "[DONE]"
                ]
                self.assertEqual(
                    sum(frame.get("done") is True for frame in fastapi_frames),
                    1,
                    "fastapi",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    stream_content_schema,
                    fastapi_frames[0],
                    "fastapi",
                )

                stream_post_payload = {
                    "model": "fixture-model:latest",
                    "messages": [{"role": "user", "content": "ping"}],
                }
                post_stream_clients = {
                    "python-http": lambda: _post_sse_payloads(
                        f"{core_url}/api/ollama/chat/stream",
                        stream_post_payload,
                    ),
                    "express": lambda: _post_sse_payloads(
                        f"{express_url}/api/ollama/chat/stream",
                        stream_post_payload,
                    ),
                }
                for name, request in post_stream_clients.items():
                    status, payloads = request()
                    self.assertEqual(status, 200, name)
                    self.assertEqual(payloads.count("[DONE]"), 1, name)
                    frames = [
                        json.loads(payload)
                        for payload in payloads
                        if payload != "[DONE]"
                    ]
                    self.assertEqual(
                        sum(frame.get("done") is True for frame in frames),
                        1,
                        name,
                    )
                    _assert_json_shape(
                        self,
                        self.contract,
                        stream_content_schema,
                        frames[0],
                        name,
                    )

                fastapi_post_stream = fastapi_client.post(
                    "/api/ollama/chat/stream",
                    json=stream_post_payload,
                )
                self.assertEqual(
                    fastapi_post_stream.status_code,
                    200,
                    "fastapi",
                )
                fastapi_post_payloads = [
                    line.removeprefix("data:").strip()
                    for event in fastapi_post_stream.text.replace("\r\n", "\n").split("\n\n")
                    for line in event.splitlines()
                    if line.startswith("data:")
                ]
                self.assertEqual(
                    fastapi_post_payloads.count("[DONE]"),
                    1,
                    "fastapi",
                )
                fastapi_post_frames = [
                    json.loads(payload)
                    for payload in fastapi_post_payloads
                    if payload != "[DONE]"
                ]
                self.assertEqual(
                    sum(frame.get("done") is True for frame in fastapi_post_frames),
                    1,
                    "fastapi",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    stream_content_schema,
                    fastapi_post_frames[0],
                    "fastapi",
                )

                stream_post_error_schema = self.contract["paths"][
                    "/api/ollama/chat/stream"
                ]["post"]["responses"]["400"]["content"][
                    "application/json"
                ]["schema"]
                invalid_post_stream_clients = {
                    "python-http": lambda: _post_raw_body(
                        f"{core_url}/api/ollama/chat/stream",
                        b"[]",
                    ),
                    "express": lambda: _post_raw_body(
                        f"{express_url}/api/ollama/chat/stream",
                        b"[]",
                    ),
                }
                for name, request in invalid_post_stream_clients.items():
                    status, raw_body = request()
                    self.assertEqual(status, 400, name)
                    body = json.loads(raw_body)
                    _assert_json_shape(
                        self,
                        self.contract,
                        stream_post_error_schema,
                        body,
                        name,
                    )
                    self.assertEqual(body["error"]["code"], "INVALID_REQUEST", name)

                fastapi_invalid_post_stream = fastapi_client.post(
                    "/api/ollama/chat/stream",
                    json=[],
                )
                self.assertEqual(
                    fastapi_invalid_post_stream.status_code,
                    400,
                    "fastapi",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    stream_post_error_schema,
                    fastapi_invalid_post_stream.json(),
                    "fastapi",
                )
                self.assertEqual(
                    fastapi_invalid_post_stream.json()["error"]["code"],
                    "INVALID_REQUEST",
                    "fastapi",
                )

                oversized_stream_body = json.dumps({
                    "model": "fixture-model:latest",
                    "messages": [{
                        "role": "user",
                        "content": "x" * (32 * 1024),
                    }],
                }).encode("utf-8")
                self.assertGreater(len(oversized_stream_body), 32 * 1024)
                stream_body_limit_schema = self.contract["paths"][
                    "/api/ollama/chat/stream"
                ]["post"]["responses"]["413"]["content"][
                    "application/json"
                ]["schema"]
                oversized_stream_clients = {
                    "python-http": lambda: _post_error_body(
                        f"{core_url}/api/ollama/chat/stream",
                        oversized_stream_body,
                    ),
                    "express": lambda: _post_error_body(
                        f"{express_url}/api/ollama/chat/stream",
                        oversized_stream_body,
                    ),
                }
                for name, request in oversized_stream_clients.items():
                    status, raw_body = request()
                    self.assertEqual(status, 413, name)
                    body = json.loads(raw_body)
                    _assert_json_shape(
                        self,
                        self.contract,
                        stream_body_limit_schema,
                        body,
                        name,
                    )
                    self.assertEqual(
                        body["error"]["code"],
                        "REQUEST_BODY_TOO_LARGE",
                        name,
                    )

                fastapi_oversized_stream = fastapi_client.post(
                    "/api/ollama/chat/stream",
                    content=oversized_stream_body,
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(
                    fastapi_oversized_stream.status_code,
                    413,
                    "fastapi",
                )
                _assert_json_shape(
                    self,
                    self.contract,
                    stream_body_limit_schema,
                    fastapi_oversized_stream.json(),
                    "fastapi",
                )
                self.assertEqual(
                    fastapi_oversized_stream.json()["error"]["code"],
                    "REQUEST_BODY_TOO_LARGE",
                    "fastapi",
                )

                terminal_headers = {
                    "X-Jarvis-Terminal-Token": "contract-terminal-token"
                }
                terminal_payload = {
                    "command": "echo",
                    "args": ["capability-contract"],
                    "timeout": 5,
                }
                terminal_success_schema = self.contract[
                    "paths"
                ]["/api/terminal/execute"]["post"]["responses"]["200"][
                    "content"
                ]["application/json"]["schema"]
                with patch.dict(
                    os.environ,
                    {
                        "JARVIS_TERMINAL_ENABLED": "true",
                        "JARVIS_TERMINAL_TOKEN": "contract-terminal-token",
                    },
                ):
                    terminal_success_clients = {
                        "python-http": lambda: _post_json(
                            f"{core_url}/api/terminal/execute",
                            terminal_payload,
                            headers=terminal_headers,
                        ),
                        "express": lambda: _post_json(
                            f"{express_url}/api/terminal/execute",
                            terminal_payload,
                            headers=terminal_headers,
                        ),
                    }
                    for name, request in terminal_success_clients.items():
                        status, body = request()
                        self.assertEqual(status, 200, name)
                        _assert_json_shape(
                            self,
                            self.contract,
                            terminal_success_schema,
                            body,
                            name,
                        )
                        self.assertTrue(body["success"], name)
                        self.assertEqual(body["exit_code"], 0, name)
                        self.assertIn("capability-contract", body["stdout"], name)

                    fastapi_response = fastapi_client.post(
                        "/api/terminal/execute",
                        json=terminal_payload,
                        headers=terminal_headers,
                    )
                    self.assertEqual(fastapi_response.status_code, 200, "fastapi")
                    fastapi_body = fastapi_response.json()
                    _assert_json_shape(
                        self,
                        self.contract,
                        terminal_success_schema,
                        fastapi_body,
                        "fastapi",
                    )
                    self.assertTrue(fastapi_body["success"])
                    self.assertEqual(fastapi_body["exit_code"], 0)
                    self.assertIn("capability-contract", fastapi_body["stdout"])

                error_schema = self.contract["paths"]["/api/terminal/execute"][
                    "post"
                ]["responses"]["400"]["content"]["application/json"]["schema"]
                post_clients = {
                    "python-http": lambda: _post_json(
                        f"http://127.0.0.1:{http_port}/api/terminal/execute",
                        {"command": ""},
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/terminal/execute",
                        {"command": ""},
                    ),
                }
                for name, request in post_clients.items():
                    status, body = request()
                    self.assertEqual(status, 400, name)
                    _assert_json_shape(self, self.contract, error_schema, body, name)
                    self.assertEqual(body["error"]["code"], "MISSING_COMMAND", name)

                response = fastapi_client.post(
                    "/api/terminal/execute", json={"command": ""}
                )
                self.assertEqual(response.status_code, 400, "fastapi")
                _assert_json_shape(
                    self, self.contract, error_schema, response.json(), "fastapi"
                )
                self.assertEqual(
                    response.json()["error"]["code"],
                    "MISSING_COMMAND",
                    "fastapi",
                )

                missing_command_clients = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/terminal/execute",
                        {},
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/terminal/execute",
                        {},
                    ),
                }
                for name, request in missing_command_clients.items():
                    status, body = request()
                    self.assertEqual(status, 400, name)
                    _assert_json_shape(self, self.contract, error_schema, body, name)
                    self.assertEqual(body["error"]["code"], "MISSING_COMMAND", name)

                response = fastapi_client.post("/api/terminal/execute", json={})
                self.assertEqual(response.status_code, 400, "fastapi missing command")
                _assert_json_shape(
                    self, self.contract, error_schema, response.json(), "fastapi"
                )
                self.assertEqual(
                    response.json()["error"]["code"],
                    "MISSING_COMMAND",
                    "fastapi",
                )

                invalid_json_clients = {
                    "python-http": lambda: _post_raw_json(
                        f"{core_url}/api/terminal/execute",
                        b'{"command":',
                    ),
                    "express": lambda: _post_raw_json(
                        f"{express_url}/api/terminal/execute",
                        b'{"command":',
                    ),
                }
                for name, request in invalid_json_clients.items():
                    status, body = request()
                    self.assertEqual(status, 400, name)
                    _assert_json_shape(self, self.contract, error_schema, body, name)
                    self.assertEqual(body["error"]["code"], "INVALID_JSON", name)

                response = fastapi_client.post(
                    "/api/terminal/execute",
                    content=b'{"command":',
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 400, "fastapi invalid JSON")
                _assert_json_shape(
                    self, self.contract, error_schema, response.json(), "fastapi"
                )
                self.assertEqual(
                    response.json()["error"]["code"],
                    "INVALID_JSON",
                    "fastapi",
                )

                non_object_json_clients = {
                    "python-http": lambda: _post_raw_json(
                        f"{core_url}/api/terminal/execute",
                        b"[]",
                    ),
                    "express": lambda: _post_raw_json(
                        f"{express_url}/api/terminal/execute",
                        b"[]",
                    ),
                }
                for name, request in non_object_json_clients.items():
                    status, body = request()
                    self.assertEqual(status, 400, name)
                    _assert_json_shape(self, self.contract, error_schema, body, name)
                    self.assertEqual(body["error"]["code"], "INVALID_REQUEST", name)

                response = fastapi_client.post(
                    "/api/terminal/execute",
                    content=b"[]",
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 400, "fastapi non-object JSON")
                _assert_json_shape(
                    self, self.contract, error_schema, response.json(), "fastapi"
                )
                self.assertEqual(
                    response.json()["error"]["code"],
                    "INVALID_REQUEST",
                    "fastapi",
                )

                plugin_error_schema = self.contract["paths"]["/api/plugins/load"][
                    "post"
                ]["responses"]["400"]["content"]["application/json"]["schema"]
                missing_plugin_id_clients = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/plugins/load",
                        {},
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/plugins/load",
                        {},
                    ),
                }
                for name, request in missing_plugin_id_clients.items():
                    status, body = request()
                    self.assertEqual(status, 400, name)
                    _assert_json_shape(
                        self, self.contract, plugin_error_schema, body, name
                    )
                    self.assertEqual(
                        body["error"]["code"], "MISSING_PLUGIN_ID", name
                    )

                response = fastapi_client.post("/api/plugins/load", json={})
                self.assertEqual(response.status_code, 400, "fastapi missing plugin ID")
                _assert_json_shape(
                    self, self.contract, plugin_error_schema, response.json(), "fastapi"
                )
                self.assertEqual(
                    response.json()["error"]["code"],
                    "MISSING_PLUGIN_ID",
                    "fastapi",
                )

                unexpected_plugin_payload = {
                    "plugin_id": ".test-contract-plugin-not-found",
                    "runtime": "python_worker",
                }
                for path in ("load", "enable", "disable"):
                    with self.subTest(plugin_path=path):
                        clients = {
                            "python-http": lambda: _post_json(
                                f"{core_url}/api/plugins/{path}",
                                unexpected_plugin_payload,
                            ),
                            "express": lambda: _post_json(
                                f"{express_url}/api/plugins/{path}",
                                unexpected_plugin_payload,
                            ),
                        }
                        for name, request in clients.items():
                            status, body = request()
                            self.assertEqual(status, 400, name)
                            _assert_json_shape(
                                self, self.contract, plugin_error_schema, body, name
                            )
                            self.assertEqual(
                                body["error"]["code"], "INVALID_REQUEST", name
                            )

                        response = fastapi_client.post(
                            f"/api/plugins/{path}", json=unexpected_plugin_payload
                        )
                        self.assertEqual(response.status_code, 400, "fastapi")
                        _assert_json_shape(
                            self,
                            self.contract,
                            plugin_error_schema,
                            response.json(),
                            "fastapi",
                        )
                        self.assertEqual(
                            response.json()["error"]["code"],
                            "INVALID_REQUEST",
                            "fastapi",
                        )

                missing_plugin_schema = self.contract["paths"]["/api/plugins/load"][
                    "post"
                ]["responses"]["404"]["content"]["application/json"]["schema"]
                missing_plugin_payload = {
                    "plugin_id": ".test-contract-plugin-not-found"
                }
                missing_plugin_clients = {
                    "python-http": lambda: _post_json(
                        f"{core_url}/api/plugins/load",
                        missing_plugin_payload,
                    ),
                    "express": lambda: _post_json(
                        f"{express_url}/api/plugins/load",
                        missing_plugin_payload,
                    ),
                }
                for name, request in missing_plugin_clients.items():
                    status, body = request()
                    self.assertEqual(status, 404, name)
                    _assert_json_shape(
                        self, self.contract, missing_plugin_schema, body, name
                    )
                    self.assertEqual(
                        body["error"]["code"], "PLUGIN_NOT_FOUND", name
                    )

                response = fastapi_client.post(
                    "/api/plugins/load",
                    json=missing_plugin_payload,
                )
                self.assertEqual(response.status_code, 404, "fastapi missing plugin")
                _assert_json_shape(
                    self, self.contract, missing_plugin_schema, response.json(), "fastapi"
                )
                self.assertEqual(
                    response.json()["error"]["code"],
                    "PLUGIN_NOT_FOUND",
                    "fastapi",
                )
        finally:
            express.terminate()
            try:
                express.wait(timeout=5)
            except subprocess.TimeoutExpired:
                express.kill()
                express.wait(timeout=5)
            http_server.shutdown()
            http_server.server_close()
            http_thread.join(timeout=5)
            http_state.shutdown()
            fastapi_state.shutdown()
            ollama_server.shutdown()
            ollama_server.server_close()
            ollama_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
