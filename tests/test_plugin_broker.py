"""Tests for the parent-owned Plugin Broker boundary."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts.plugin_worker_protocol import PluginBrokerRequest
from core.kernel.event_bus import EventBus
from core.kernel.plugin_broker import (
    MAX_BROKER_EXCHANGE_BYTES,
    MANIFEST_PERMISSION_BY_CAPABILITY,
    PLUGIN_BROKER_DENIED,
    PLUGIN_BROKER_HANDLER_FAILED,
    PluginBroker,
)


def event_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    event_type="plugin.activated",
    payload=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability="event.emit",
        arguments={
            "event_type": event_type,
            "payload": {} if payload is None else payload,
        },
    )


class TestPluginBroker(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def _session(self, broker, permissions=("event_bus",)):
        return broker.begin_lifecycle(
            "event-logger",
            "request-1",
            permissions,
            generation=1,
        )

    def _session_for(self, broker, plugin_id, request_id, generation):
        return broker.begin_lifecycle(
            plugin_id,
            request_id,
            ("event_bus",),
            generation=generation,
        )

    def test_capability_permission_map_is_immutable(self):
        with self.assertRaises(TypeError):
            MANIFEST_PERMISSION_BY_CAPABILITY["test.capability"] = "test_permission"

    def test_event_emit_requires_declaration_grant_and_registered_handler(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )

        self.assertFalse(self._session(broker).handle(event_request()).allowed)
        self.assertFalse(
            self._session(broker, permissions=()).handle(event_request()).allowed
        )

        ungranted = PluginBroker(self.bus, grants={})
        ungranted.register_event_emit_handler()
        self.assertFalse(self._session(ungranted).handle(event_request()).allowed)

        broker.register_event_emit_handler()
        allowed = self._session(broker).handle(event_request(call_id="call-2"))

        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")

    def test_allowed_event_uses_parent_owned_source(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()

        result = self._session(broker).handle(
            event_request(payload={"plugin_id": "forged"})
        )

        self.assertTrue(result.allowed)
        event = self.bus.get_history()[-1]
        self.assertEqual(event.event_type, "plugin.activated")
        self.assertEqual(event.source, "plugin:event-logger")
        self.assertEqual(event.data, {"plugin_id": "forged"})

    def test_malformed_event_arguments_are_denied_without_side_effect(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()

        result = self._session(broker).handle(
            event_request(event_type="system.shutdown")
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, PLUGIN_BROKER_DENIED)
        self.assertEqual(self.bus.get_history(), [])

    def test_oversized_event_payload_is_denied_without_side_effect(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()

        result = self._session(broker).handle(
            event_request(payload={"value": "x" * 16_385})
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, PLUGIN_BROKER_DENIED)
        self.assertEqual(self.bus.get_history(), [])

    def test_oversized_request_is_denied_before_handler_is_reached(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        calls = []
        broker.register_handler(
            "event.emit",
            lambda request: calls.append(request) or {"emitted": True},
            validator=lambda _arguments: True,
        )
        request = PluginBrokerRequest(
            request_id="request-1",
            call_id="call-1",
            plugin_id="event-logger",
            capability="event.emit",
            arguments={"value": "x" * MAX_BROKER_EXCHANGE_BYTES},
        )

        result = self._session(broker).handle(request)

        self.assertFalse(result.allowed)
        self.assertEqual(calls, [])

    def test_oversized_handler_result_is_denied(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_handler(
            "event.emit",
            lambda _request: {"value": "x" * MAX_BROKER_EXCHANGE_BYTES},
            validator=lambda _arguments: True,
        )

        result = self._session(broker).handle(event_request())

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, PLUGIN_BROKER_DENIED)

    def test_unknown_capability_is_denied_even_when_granted(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event_bus.publish"}},
        )
        request = PluginBrokerRequest(
            request_id="request-1",
            call_id="call-1",
            plugin_id="event-logger",
            capability="event_bus.publish",
            arguments={},
        )

        result = self._session(broker).handle(request)

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, PLUGIN_BROKER_DENIED)

    def test_handler_exception_returns_stable_redacted_failure(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )

        def explode(_request):
            raise RuntimeError("token=secret-value")

        broker.register_handler("event.emit", explode, validator=lambda _args: True)
        result = self._session(broker).handle(event_request())

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, PLUGIN_BROKER_HANDLER_FAILED)
        self.assertNotIn("secret-value", str(broker.audit_log()))

    def test_validator_exception_is_fail_closed_before_handler(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        handler_calls = []

        def exploding_validator(_arguments):
            raise RuntimeError("validator failure")

        broker.register_handler(
            "event.emit",
            lambda request: handler_calls.append(request) or {"emitted": True},
            validator=exploding_validator,
        )

        result = self._session(broker).handle(event_request())

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, PLUGIN_BROKER_HANDLER_FAILED)
        self.assertEqual(handler_calls, [])

    def test_session_rejects_wrong_correlation_and_duplicate_calls(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()
        session = self._session(broker)

        wrong_request = session.handle(event_request(request_id="request-2"))
        wrong_plugin = session.handle(
            event_request(plugin_id="plugin-template", call_id="call-wrong-plugin")
        )
        first = session.handle(event_request())
        duplicate = session.handle(event_request())

        self.assertFalse(wrong_request.allowed)
        self.assertFalse(wrong_plugin.allowed)
        self.assertTrue(first.allowed)
        self.assertFalse(duplicate.allowed)

    def test_stale_generation_session_is_denied_before_event_publish(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()
        stale = self._session_for(broker, "event-logger", "request-1", generation=1)
        current = self._session_for(broker, "event-logger", "request-1", generation=2)

        stale_result = stale.handle(event_request(call_id="call-stale"))
        current_result = current.handle(event_request(call_id="call-current"))

        self.assertFalse(stale_result.allowed)
        self.assertTrue(current_result.allowed)
        self.assertEqual(len(self.bus.get_history()), 1)

    def test_session_limits_calls_and_returns_copied_bounded_audit_history(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()
        session = self._session(broker)

        for index in range(32):
            self.assertTrue(session.handle(event_request(call_id=f"call-{index}")).allowed)
        exhausted = session.handle(event_request(call_id="call-over-limit"))

        self.assertFalse(exhausted.allowed)
        for index in range(105):
            self._session(broker).handle(
                event_request(request_id=f"request-{index + 10}", call_id="call-1")
            )
        audit = broker.audit_log()
        audit[0]["code"] = "mutated"
        self.assertLessEqual(len(audit), 100)
        self.assertNotEqual(broker.audit_log()[0]["code"], "mutated")

    def test_audit_excludes_untrusted_event_payload(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()

        result = self._session(broker).handle(
            event_request(payload={"token": "secret-value"})
        )

        self.assertTrue(result.allowed)
        self.assertNotIn("secret-value", str(broker.audit_log()))

    def test_audit_redacts_sensitive_request_identifiers(self):
        broker = PluginBroker(
            self.bus,
            grants={"event-logger": {"event.emit"}},
        )
        broker.register_event_emit_handler()
        session = self._session_for(
            broker,
            "event-logger",
            "token:secret-value",
            generation=1,
        )

        result = session.handle(
            event_request(
                request_id="token:secret-value",
                call_id="credential:secret-value",
            )
        )

        self.assertTrue(result.allowed)
        self.assertNotIn("secret-value", str(broker.audit_log()))


if __name__ == "__main__":
    unittest.main()
