"""Guardrails for the deterministic CI local-integration runner."""

import importlib.util
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).parent.parent
RUNNER = ROOT / "scripts" / "ci_local_integration.py"
FIXTURE = ROOT / "scripts" / "local_ollama_fixture.py"


def _load_fixture_module():
    spec = importlib.util.spec_from_file_location("jarvis_ollama_fixture", FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _post_json(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


class TestLocalIntegrationRunner(unittest.TestCase):
    def test_runner_and_fixture_are_repository_owned(self):
        self.assertTrue(RUNNER.is_file())
        self.assertTrue(FIXTURE.is_file())

    def test_runner_exposes_required_services_mode(self):
        spec = importlib.util.spec_from_file_location("jarvis_ci_runner", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertIn("--require-services", module.build_parser().format_help())
        self.assertTrue(callable(module.run_integration))

    def test_fixture_declares_minimal_ollama_contract(self):
        text = FIXTURE.read_text(encoding="utf-8")
        for path in ("/api/version", "/api/tags", "/api/chat"):
            self.assertIn(path, text)
        self.assertIn('"prompt_eval_count"', text)
        self.assertIn('"eval_count"', text)
        self.assertIn('"tool_calls"', text)

    def test_fixture_completes_a_deterministic_tool_round_trip(self):
        module = _load_fixture_module()
        server = ThreadingHTTPServer(("127.0.0.1", 0), module.OllamaFixtureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/chat"
        definition = {
            "type": "function",
            "function": {
                "name": "repository_metadata",
                "description": "Read repository metadata",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
        messages = [{"role": "user", "content": "inspect"}]

        try:
            first = _post_json(
                url,
                {
                    "model": "fixture",
                    "messages": messages,
                    "stream": False,
                    "tools": [definition],
                },
            )
            call = first["message"]["tool_calls"][0]
            self.assertEqual(call["function"]["name"], "repository_metadata")
            self.assertEqual(call["function"]["arguments"], {})

            second = _post_json(
                url,
                {
                    "model": "fixture",
                    "messages": [
                        *messages,
                        first["message"],
                        {
                            "role": "tool",
                            "tool_name": "repository_metadata",
                            "tool_call_id": call["id"],
                            "content": "{}",
                        },
                    ],
                    "stream": False,
                    "tools": [definition],
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(second["message"], {"role": "assistant", "content": "OK"})


if __name__ == "__main__":
    unittest.main()
