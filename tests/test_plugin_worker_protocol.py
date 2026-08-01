"""Tests for the strict JSON-lines plugin worker protocol boundary."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts.plugin_worker_protocol import (
    MAX_PLUGIN_WORKER_LINE_BYTES,
    PLUGIN_WORKER_PROTOCOL_VERSION,
    LifecycleAction,
    PluginBrokerRequest,
    PluginBrokerResult,
    PluginLifecycleRequest,
    PluginLifecycleResult,
    PluginLoadSpec,
    PluginWorkerHello,
    PluginWorkerProtocolError,
    decode_message,
    encode_message,
    redact_protocol_error,
    stable_json_bytes,
)


class TestPluginWorkerProtocol(unittest.TestCase):
    def setUp(self):
        self.load_spec = PluginLoadSpec(
            entry_point="plugin.py",
            permissions=("event_bus",),
            api_version="1.0.0",
            generation=1,
        )
        self.messages = (
            PluginWorkerHello(worker_id="worker-1", pid=1234),
            PluginLifecycleRequest(
                request_id="request-1",
                plugin_id="event-logger",
                action=LifecycleAction.LOAD,
                payload=self.load_spec.to_dict(),
            ),
            PluginBrokerRequest(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                capability="event_bus.publish",
                arguments={"topic": "events"},
            ),
            PluginBrokerResult(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                allowed=True,
                result={"published": True},
                error="",
            ),
            PluginLifecycleResult(
                request_id="request-1",
                plugin_id="event-logger",
                success=True,
                status="loaded",
                error="",
                audit=[{"action": "load"}],
            ),
        )

    def test_lifecycle_request_round_trip_is_canonical(self):
        request = self.messages[1]

        self.assertEqual(decode_message(encode_message(request)), request)

    def test_every_message_kind_round_trips_through_the_json_line_codec(self):
        for message in self.messages:
            with self.subTest(kind=message.to_dict()["kind"]):
                self.assertEqual(decode_message(encode_message(message)), message)

    def test_encoding_is_compact_canonical_utf8_json_line(self):
        encoded = encode_message(self.messages[0])

        self.assertEqual(
            encoded,
            b'{"kind":"hello","pid":1234,"protocol_version":1,"worker_id":"worker-1"}\n',
        )
        self.assertEqual(stable_json_bytes({"z": "\u4e2d", "a": 1}), '{"a":1,"z":"\u4e2d"}'.encode("utf-8"))

    def test_records_reject_wrong_protocol_version_and_noncanonical_identifiers(self):
        with self.assertRaises(PluginWorkerProtocolError):
            PluginWorkerHello(protocol_version=2, worker_id="worker-1", pid=1)
        for value in ("", "worker name", "\u5de5\u4f5c\u8005"):
            with self.subTest(value=value):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginWorkerHello(worker_id=value, pid=1)

    def test_decoder_rejects_missing_unknown_and_wrong_version_fields(self):
        valid = self.messages[0].to_dict()
        for payload in (
            {key: value for key, value in valid.items() if key != "pid"},
            {**valid, "extra": True},
            {**valid, "protocol_version": 2},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(PluginWorkerProtocolError):
                    decode_message(stable_json_bytes(payload) + b"\n")

    def test_decoder_rejects_invalid_utf8_empty_and_oversized_lines(self):
        for line in (b"\xff\n", b"\n", b"x" * (MAX_PLUGIN_WORKER_LINE_BYTES + 1)):
            with self.subTest(line=line[:10]):
                with self.assertRaises(PluginWorkerProtocolError):
                    decode_message(line)

    def test_integer_fields_reject_booleans_and_invalid_worker_pid(self):
        for pid in (True, 0, -1):
            with self.subTest(pid=pid):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginWorkerHello(worker_id="worker-1", pid=pid)
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLoadSpec("plugin.py", (), "1.0.0", True)

    def test_lifecycle_actions_and_payloads_are_exact(self):
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleRequest("request-1", "event-logger", "restart", {})
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleRequest("request-1", "event-logger", LifecycleAction.LOAD, {})
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleRequest(
                "request-1", "event-logger", LifecycleAction.ACTIVATE, {"generation": 1}
            )

    def test_broker_result_correlation_and_denial_contract_are_strict(self):
        with self.assertRaises(PluginWorkerProtocolError):
            PluginBrokerResult(
                request_id="request-1",
                call_id="wrong call",
                plugin_id="event-logger",
                allowed=True,
                result=None,
                error="",
            )
        with self.assertRaises(PluginWorkerProtocolError):
            PluginBrokerResult(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                allowed=True,
                result=None,
                error="denied",
            )
        with self.assertRaises(PluginWorkerProtocolError):
            PluginBrokerResult(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                allowed=False,
                result=None,
                error="",
            )

    def test_records_reject_non_json_values_and_invalid_lifecycle_results(self):
        with self.assertRaises(PluginWorkerProtocolError):
            PluginBrokerRequest("request-1", "call-1", "event-logger", "capability", {"bad": object()})
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleResult("request-1", "event-logger", True, "starting", "", [])
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleResult("request-1", "event-logger", True, "loaded", "", [{}] * 101)

    def test_lifecycle_result_validates_declared_fields_without_inventing_status_correlation(self):
        result = PluginLifecycleResult(
            "request-1", "event-logger", False, "loaded", "load_failed", []
        )

        self.assertEqual(result.status, "loaded")
        self.assertEqual(result.error, "load_failed")

    def test_redaction_removes_secrets_newlines_and_truncates_unicode_characters(self):
        redacted = redact_protocol_error({"token": "secret-value", "message": "line one\nline two"})

        self.assertIn("<redacted>", redacted)
        self.assertNotIn("secret-value", redacted)
        self.assertNotIn("\n", redacted)
        self.assertNotIn("secret-value", redact_protocol_error("token=secret-value"))
        self.assertLessEqual(len(redact_protocol_error("\u4e2d" * 2000)), 1024)


if __name__ == "__main__":
    unittest.main()
