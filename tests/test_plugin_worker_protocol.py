"""Tests for the strict, newline-delimited plugin worker protocol."""

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import core.contracts.plugin_worker_protocol as plugin_worker_protocol
from core.contracts.plugin_worker_protocol import (
    MAX_PLUGIN_WORKER_INTEGER_DIGITS,
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

    def test_constants_and_records_are_immutable(self):
        hello = PluginWorkerHello(worker_id="worker-1", pid=123)

        self.assertEqual(PLUGIN_WORKER_PROTOCOL_VERSION, 1)
        self.assertEqual(MAX_PLUGIN_WORKER_LINE_BYTES, 65_536)
        with self.assertRaises(FrozenInstanceError):
            hello.pid = 456

    def test_lifecycle_request_round_trip_is_canonical(self):
        request = PluginLifecycleRequest(
            request_id="request-1",
            plugin_id="event-logger",
            action=LifecycleAction.LOAD,
            payload=self.load_spec.to_dict(),
        )

        self.assertEqual(decode_message(encode_message(request)), request)
        self.assertEqual(
            encode_message(request),
            b'{"action":"load","kind":"lifecycle_request","payload":'
            b'{"api_version":"1.0.0","entry_point":"plugin.py",'
            b'"generation":1,"permissions":["event_bus"]},'
            b'"plugin_id":"event-logger","protocol_version":1,'
            b'"request_id":"request-1"}\n',
        )

    def test_all_message_kinds_round_trip_with_exact_schemas(self):
        messages = (
            PluginWorkerHello(worker_id="worker-1", pid=123),
            PluginLifecycleRequest(
                request_id="request-1",
                plugin_id="event-logger",
                action=LifecycleAction.ACTIVATE,
                payload={},
            ),
            PluginBrokerRequest(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                capability="event_bus.publish",
                arguments={"topic": "plugin.loaded"},
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
                status="enabled",
                error="",
                audit=({"event": "activated"},),
            ),
        )

        for message in messages:
            with self.subTest(kind=message.to_dict()["kind"]):
                serialized = message.to_dict()
                self.assertEqual(decode_message(encode_message(message)), message)
                self.assertEqual(type(message).from_dict(serialized), message)
                self.assertNotIn("generation", serialized)

    def test_decode_rejects_wrong_version_missing_or_unknown_fields(self):
        valid = PluginWorkerHello(worker_id="worker-1", pid=123).to_dict()
        invalid_values = []
        wrong_version = dict(valid)
        wrong_version["protocol_version"] = 2
        invalid_values.append(wrong_version)
        missing = dict(valid)
        del missing["pid"]
        invalid_values.append(missing)
        unknown = dict(valid)
        unknown["generation"] = 1
        invalid_values.append(unknown)

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(PluginWorkerProtocolError):
                    decode_message(stable_json_bytes(value) + b"\n")

        with self.assertRaises(PluginWorkerProtocolError):
            PluginWorkerHello.from_dict({
                **valid,
                1: "not-json",
                "extra": "not-json",
            })

    def test_decode_rejects_invalid_utf8_and_oversized_lines_before_json(self):
        with self.assertRaises(PluginWorkerProtocolError):
            decode_message(b"\xff\n")
        with self.assertRaises(PluginWorkerProtocolError):
            decode_message(b"{" + b" " * MAX_PLUGIN_WORKER_LINE_BYTES + b"}\n")
        with self.assertRaises(PluginWorkerProtocolError):
            decode_message(b'{"kind":"hello"}')

    def test_decode_normalizes_resource_limited_json_numbers(self):
        line = b'{"value":' + b"9" * 5_000 + b"}\n"

        with self.assertRaises(PluginWorkerProtocolError):
            decode_message(line)

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

    def test_decode_normalizes_deeply_nested_broker_arguments(self):
        depth = 900
        arguments = b"[" * depth + b"0" + b"]" * depth
        line = (
            b'{"arguments":'
            + arguments
            + b',"call_id":"call-1","capability":"event.emit",'
            b'"kind":"broker_request","plugin_id":"event-logger",'
            b'"protocol_version":1,"request_id":"request-1"}\n'
        )

        with self.assertRaises(PluginWorkerProtocolError) as raised:
            decode_message(line)
        self.assertNotIn("RecursionError", str(raised.exception))
        self.assertLessEqual(len(str(raised.exception)), 1024)

    def test_record_construction_rejects_deeply_nested_json(self):
        depth = 900
        arguments = 0
        for _ in range(depth):
            arguments = [arguments]

        with self.assertRaises(PluginWorkerProtocolError) as raised:
            PluginBrokerRequest(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                capability="event.emit",
                arguments=arguments,
            )
        self.assertNotIn("RecursionError", str(raised.exception))
        self.assertLessEqual(len(str(raised.exception)), 1024)

    def test_decode_rejects_duplicate_or_noncanonical_json_lines(self):
        invalid_lines = (
            b'{"kind":"hello","kind":"hello","pid":123,'
            b'"protocol_version":1,"worker_id":"worker-1"}\n',
            b'{"kind":"hello", "pid":123,"protocol_version":1,'
            b'"worker_id":"worker-1"}\n',
            b'{"worker_id":"worker-1","pid":123,"protocol_version":1,'
            b'"kind":"hello"}\n',
        )

        for line in invalid_lines:
            with self.subTest(line=line):
                with self.assertRaises(PluginWorkerProtocolError):
                    decode_message(line)

    def test_identifiers_are_canonical_nonempty_and_cannot_contain_unicode(self):
        for identifier in ("", "worker id", "worker-\u4e2d\u6587", "worker\n1"):
            with self.subTest(identifier=identifier):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginWorkerHello(worker_id=identifier, pid=1)

    def test_positive_integer_fields_reject_booleans_and_invalid_pid(self):
        for pid in (True, False, 0, -1, 1.5):
            with self.subTest(pid=pid):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginWorkerHello(worker_id="worker-1", pid=pid)
        for generation in (True, 0, -1, 1.5):
            with self.subTest(generation=generation):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginLoadSpec(
                        entry_point="plugin.py",
                        permissions=("event_bus",),
                        api_version="1.0.0",
                        generation=generation,
                    )

    def test_lifecycle_actions_and_payloads_are_strict(self):
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleRequest(
                request_id="request-1",
                plugin_id="event-logger",
                action="restart",
                payload={},
            )
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleRequest(
                request_id="request-1",
                plugin_id="event-logger",
                action=LifecycleAction.ACTIVATE,
                payload={"generation": 1},
            )
        malformed_load = self.load_spec.to_dict()
        malformed_load["extra"] = "no"
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleRequest(
                request_id="request-1",
                plugin_id="event-logger",
                action=LifecycleAction.LOAD,
                payload=malformed_load,
            )

    def test_broker_messages_require_nonempty_correlation_identifiers(self):
        for request_id, call_id in (("", "call-1"), ("request-1", "")):
            with self.subTest(request_id=request_id, call_id=call_id):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginBrokerRequest(
                        request_id=request_id,
                        call_id=call_id,
                        plugin_id="event-logger",
                        capability="event_bus.publish",
                        arguments={},
                    )
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginBrokerResult(
                        request_id=request_id,
                        call_id=call_id,
                        plugin_id="event-logger",
                        allowed=False,
                        result=None,
                        error="capability_denied",
                    )

    def test_broker_result_and_lifecycle_result_validate_semantics(self):
        with self.assertRaises(PluginWorkerProtocolError):
            PluginBrokerResult(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                allowed=True,
                result=None,
                error="capability_denied",
            )
        for error in ("", "contains newline\n"):
            with self.subTest(error=error):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginBrokerResult(
                        request_id="request-1",
                        call_id="call-1",
                        plugin_id="event-logger",
                        allowed=False,
                        result=None,
                        error=error,
                    )
        for status, audit in (("missing", ()), ([], ()), ("enabled", tuple(range(101)))):
            with self.subTest(status=status):
                with self.assertRaises(PluginWorkerProtocolError):
                    PluginLifecycleResult(
                        request_id="request-1",
                        plugin_id="event-logger",
                        success=False,
                        status=status,
                        error="failed",
                        audit=audit,
                    )

    def test_json_values_and_error_redaction_are_bounded(self):
        for value in ({"callback": object()}, float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(PluginWorkerProtocolError):
                    stable_json_bytes(value)
        with self.assertRaises(PluginWorkerProtocolError):
            PluginBrokerRequest(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                capability="event_bus.publish",
                arguments={"callback": object()},
            )

        redacted = redact_protocol_error("token=secret-value\n" + "x" * 2_000)
        self.assertNotIn("secret-value", redacted)
        self.assertNotIn("\n", redacted)
        self.assertLessEqual(len(redacted), 1_024)

    def test_surrogate_strings_raise_protocol_errors_at_every_boundary(self):
        surrogate = chr(0xD800)
        with self.assertRaises(PluginWorkerProtocolError):
            stable_json_bytes({"value": surrogate})
        with self.assertRaises(PluginWorkerProtocolError):
            PluginBrokerRequest(
                request_id="request-1",
                call_id="call-1",
                plugin_id="event-logger",
                capability="event_bus.publish",
                arguments={"value": surrogate},
            )
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleResult(
                request_id="request-1",
                plugin_id="event-logger",
                success=False,
                status="error",
                error="failure",
                audit=({"value": surrogate},),
            )
        with self.assertRaises(PluginWorkerProtocolError):
            PluginLifecycleResult(
                request_id="request-1",
                plugin_id="event-logger",
                success=False,
                status="error",
                error=surrogate,
                audit=(),
            )
        with self.assertRaises(PluginWorkerProtocolError):
            decode_message(
                b'{"allowed":true,"call_id":"call-1","error":"",'
                b'"kind":"broker_result","plugin_id":"event-logger",'
                b'"protocol_version":1,"request_id":"request-1",'
                b'"result":"\\ud800"}\n'
            )

    def test_bounded_stable_json_size_matches_canonical_encoding(self):
        values = (
            None,
            True,
            -17,
            1.25,
            "quote\" slash\\ controls\n\x00",
            "中文🙂",
            {"z": [1, False, None], "a": {"nested": "value"}},
        )

        for value in values:
            with self.subTest(value=value):
                expected = len(stable_json_bytes(value))
                self.assertEqual(
                    plugin_worker_protocol.bounded_stable_json_size(
                        value, expected
                    ),
                    expected,
                )
                with self.assertRaises(OverflowError):
                    plugin_worker_protocol.bounded_stable_json_size(
                        value, expected - 1
                    )

    def test_bounded_stable_json_size_validates_limits_and_values(self):
        for limit in (True, -1, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    plugin_worker_protocol.bounded_stable_json_size(None, limit)

        with self.assertRaises(PluginWorkerProtocolError):
            plugin_worker_protocol.bounded_stable_json_size(object(), 64)

    def test_encode_enforces_the_exact_line_byte_boundary(self):
        base = PluginLifecycleResult(
            request_id="request-1",
            plugin_id="event-logger",
            success=True,
            status="enabled",
            error="",
            audit=("",),
        )
        padding_size = MAX_PLUGIN_WORKER_LINE_BYTES - len(encode_message(base))
        at_limit = PluginLifecycleResult(
            request_id="request-1",
            plugin_id="event-logger",
            success=True,
            status="enabled",
            error="",
            audit=("x" * padding_size,),
        )
        over_limit = PluginLifecycleResult(
            request_id="request-1",
            plugin_id="event-logger",
            success=True,
            status="enabled",
            error="",
            audit=("x" * (padding_size + 1),),
        )

        self.assertEqual(len(encode_message(at_limit)), MAX_PLUGIN_WORKER_LINE_BYTES)
        with self.assertRaises(PluginWorkerProtocolError):
            encode_message(over_limit)


if __name__ == "__main__":
    unittest.main()
