"""Tests for the opt-in local integration profile."""

import importlib.util
import io
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "local_integration_profile.py"


def _load_profile():
    spec = importlib.util.spec_from_file_location("jarvis_local_integration", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLocalIntegrationProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = _load_profile()

    def test_parse_sse_collects_json_frames_and_done_marker(self):
        payload = (
            'data: {"message":{"content":"OK"},"done":false}\n\n'
            'data: {"done":true}\n\n'
            'data: [DONE]\n\n'
        )

        frames = self.profile.parse_sse_payload(payload)

        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]["message"]["content"], "OK")

    def test_parse_sse_rejects_stream_without_done_marker(self):
        with self.assertRaises(self.profile.ProfileFailure):
            self.profile.parse_sse_payload('data: {"done":false}\n\n')

    def test_parse_sse_rejects_error_frame_even_with_done_marker(self):
        payload = 'data: {"error":"Ollama unavailable"}\n\ndata: [DONE]\n\n'
        with self.assertRaises(self.profile.ProfileFailure):
            self.profile.parse_sse_payload(payload)

    def test_parse_sse_requires_assistant_content_frame(self):
        payload = 'data: {"done":true}\n\ndata: [DONE]\n\n'
        with self.assertRaises(self.profile.ProfileFailure):
            self.profile.parse_sse_payload(payload)

    def test_parse_sse_requires_native_done_frame(self):
        payload = (
            'data: {"message":{"content":"OK"},"done":false}\n\n'
            'data: [DONE]\n\n'
        )
        with self.assertRaises(self.profile.ProfileFailure):
            self.profile.parse_sse_payload(payload)

    def test_optional_mode_skips_unavailable_services(self):
        with patch.object(
            self.profile,
            "run_profile",
            side_effect=self.profile.ProfileUnavailable("Express unavailable"),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = self.profile.main([])

        self.assertEqual(code, 0)
        self.assertIn("SKIPPED", output.getvalue())

    def test_required_mode_fails_unavailable_services(self):
        with patch.object(
            self.profile,
            "run_profile",
            side_effect=self.profile.ProfileUnavailable("Ollama unavailable"),
        ):
            with redirect_stdout(io.StringIO()):
                code = self.profile.main(["--require-services"])

        self.assertEqual(code, 1)

    def test_http_error_is_profile_failure_not_unavailable(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1/api/health",
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b'{"error":"broken"}'),
        )
        with patch.object(
            self.profile.urllib.request,
            "urlopen",
            side_effect=error,
        ):
            with self.assertRaises(self.profile.ProfileFailure):
                self.profile._request_json("http://127.0.0.1/api/health")

    def test_ollama_503_is_treated_as_unavailable(self):
        http_error = self.profile.ProfileHttpError(
            "http://127.0.0.1:9999/api/ollama/status",
            503,
            '{"error":{"code":"OLLAMA_UNAVAILABLE","message":"offline"}}',
        )
        with patch.object(
            self.profile,
            "_request_json",
            side_effect=[
                {"status": "healthy"},
                {"core_api": {"configured": True, "available": True}},
                http_error,
            ],
        ):
            with self.assertRaises(self.profile.ProfileUnavailable):
                self.profile.run_profile("http://127.0.0.1:9999")

    def test_ollama_malformed_502_is_contract_failure(self):
        http_error = self.profile.ProfileHttpError(
            "http://127.0.0.1:9999/api/ollama/status",
            502,
            '{"error":{"code":"OLLAMA_INVALID_RESPONSE","message":"bad json"}}',
        )
        with patch.object(
            self.profile,
            "_request_json",
            side_effect=[
                {"status": "healthy"},
                {"core_api": {"configured": True, "available": True}},
                http_error,
            ],
        ):
            with self.assertRaises(self.profile.ProfileHttpError):
                self.profile.run_profile("http://127.0.0.1:9999")

    def test_memory_probe_is_deleted_when_later_check_fails(self):
        responses = [
            {"status": "healthy"},
            {"core_api": {"configured": True, "available": True}},
            {"running": True, "models": [{"name": "fixture"}]},
            {"plugins": []},
            {"success": True, "id": "probe123"},
            {"entries": []},
            {"success": True, "id": "probe123"},
        ]

        with patch.object(
            self.profile,
            "_request_json",
            side_effect=responses,
        ) as request_json:
            with self.assertRaises(self.profile.ProfileFailure):
                self.profile.run_profile("http://127.0.0.1:9999")

        cleanup = request_json.call_args_list[-1]
        self.assertEqual(
            cleanup.args[0],
            "http://127.0.0.1:9999/api/memory/probes/project/probe123",
        )
        self.assertEqual(cleanup.kwargs["method"], "DELETE")
        self.assertTrue(cleanup.kwargs["payload"]["cleanup_token"])

    def test_cleanup_failure_does_not_replace_primary_failure(self):
        cleanup_error = self.profile.ProfileFailure("cleanup unavailable")
        responses = [
            {"status": "healthy"},
            {"core_api": {"configured": True, "available": True}},
            {"running": True, "models": [{"name": "fixture"}]},
            {"plugins": []},
            {"success": True, "id": "probe123", "type": "project"},
            {"entries": []},
            cleanup_error,
        ]
        with patch.object(self.profile, "_request_json", side_effect=responses):
            with self.assertRaises(self.profile.ProfileFailure) as raised:
                self.profile.run_profile("http://127.0.0.1:9999")

        self.assertIn("Stored memory entry was not returned", str(raised.exception))
        self.assertIn("cleanup unavailable", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
