"""Tests for the parent-owned default-deny plugin capability broker."""

import contextlib
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts.plugin_worker_protocol import PluginBrokerRequest, PluginBrokerResult
from core.kernel import plugin_broker as plugin_broker_module
from core.kernel.event_bus import EventBus
from core.kernel.plugin_broker import (
    CONFIG_GET_CAPABILITY,
    CONFIG_GET_DENIED_REASON,
    CONFIG_GET_PERMISSION,
    EVENT_EMIT_CAPABILITY,
    FILE_READ_CAPABILITY,
    FILE_READ_PERMISSION,
    LLM_CALL_CAPABILITY,
    LLM_CALL_DENIED_REASON,
    LLM_CALL_PERMISSION,
    MAX_BROKER_CALLS,
    MAX_BROKER_EXCHANGE_BYTES,
    MAX_FILE_READ_BYTES,
    MAX_LLM_PROMPT_BYTES,
    MAX_NETWORK_BODY_BYTES,
    MAX_NETWORK_HEADERS,
    MAX_NETWORK_REDIRECTS,
    MAX_NETWORK_URL_BYTES,
    MAX_PLUGIN_CONFIG_BYTES,
    NETWORK_GET_CAPABILITY,
    NETWORK_GET_DENIED_REASON,
    NETWORK_GET_PERMISSION,
    SYSTEM_MONITOR_PERMISSION,
    SYSTEM_STATS_CAPABILITY,
    PluginBroker,
    PluginCapabilityDenied,
)
from tests.plugin_network_fixture import NetworkFixtureServer


def event_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    arguments=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability="event.emit",
        arguments=arguments
        if arguments is not None
        else {"event_type": "plugin.worker.ready", "payload": {"ok": True}},
    )


def stats_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    capability="system.stats",
    arguments=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability=capability,
        arguments={} if arguments is None else arguments,
    )


def file_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    capability="file.read",
    arguments=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability=capability,
        arguments={"path": "readme.txt"} if arguments is None else arguments,
    )


def config_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    capability="config.get",
    arguments=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability=capability,
        arguments={"key": "theme", "default": "light"}
        if arguments is None
        else arguments,
    )


def llm_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    capability="llm.call",
    arguments=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability=capability,
        arguments={"prompt": "hello", "model": "llama3"}
        if arguments is None
        else arguments,
    )


def network_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    capability="network.get",
    arguments=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability=capability,
        arguments={"url": "http://127.0.0.1/ok"}
        if arguments is None
        else arguments,
    )


def file_list_request(
    request_id="request-1",
    call_id="call-1",
    plugin_id="event-logger",
    capability="file.list",
    arguments=None,
):
    return PluginBrokerRequest(
        request_id=request_id,
        call_id=call_id,
        plugin_id=plugin_id,
        capability=capability,
        arguments={"path": "."} if arguments is None else arguments,
    )


class TestPluginBroker(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.broker = PluginBroker(
            self.bus, grants={"event-logger": {"event.emit"}}
        )
        self.session = self.broker.begin_lifecycle(
            "event-logger", "request-1", ("event_bus",), generation=1
        )

    def test_event_emit_requires_declaration_grant_and_registered_handler(self):
        denied = self.session.handle(event_request())
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_registered")

        self.broker.register_event_emit_handler()
        allowed = self.session.handle(event_request(call_id="call-2"))
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(self.session.commit_events())
        self.assertEqual(len(self.bus.get_history()), 1)

        undeclared = self.broker.begin_lifecycle(
            "event-logger", "request-2", (), generation=1
        ).handle(event_request(request_id="request-2"))
        self.assertEqual(undeclared.error, "capability_not_declared")

        ungranted = PluginBroker(self.bus).begin_lifecycle(
            "event-logger", "request-3", ("event_bus",), generation=1
        ).handle(event_request(request_id="request-3"))
        self.assertEqual(ungranted.error, "capability_not_granted")

    def test_denials_preserve_request_correlation_and_do_not_invoke_handler(self):
        calls = []
        self.broker.register_handler("event.emit", lambda arguments: calls.append(arguments))

        wrong_request = self.session.handle(event_request(request_id="request-other"))
        wrong_plugin = self.session.handle(event_request(plugin_id="other-plugin"))
        self.broker.begin_lifecycle(
            "event-logger", "request-2", ("event_bus",), generation=2
        )
        wrong_generation = self.session.handle(event_request(call_id="call-2"))

        self.assertEqual(wrong_request.error, "request_mismatch")
        self.assertEqual(wrong_plugin.error, "plugin_mismatch")
        self.assertEqual(wrong_generation.error, "generation_mismatch")
        self.assertEqual(calls, [])
        self.assertEqual(wrong_request.request_id, "request-other")
        self.assertEqual(wrong_plugin.plugin_id, "other-plugin")
        self.assertEqual(wrong_generation.request_id, "request-1")

    def test_registered_event_handler_controls_the_allowed_response(self):
        calls = []
        self.broker.register_handler(
            "event.emit", lambda arguments: calls.append(arguments) or {"custom": True}
        )

        result = self.session.handle(event_request())

        self.assertTrue(result.allowed)
        self.assertEqual(result.result, {"custom": True})
        self.assertEqual(calls, [{"event_type": "plugin.worker.ready", "payload": {"ok": True}}])
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(self.session.commit_events())
        self.assertEqual(len(self.bus.get_history()), 1)

    def test_registered_handler_errors_fail_closed_without_staging_an_event(self):
        def fail_handler(_arguments):
            raise RuntimeError("fixture handler failed")

        self.broker.register_handler("event.emit", fail_handler)

        result = self.session.handle(event_request())

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, "handler_failed")
        self.assertEqual(self.bus.get_history(), [])

    def test_oversized_handler_result_is_denied_without_full_serialization(self):
        oversized_result = {"value": "x" * (2 * 1024 * 1024)}
        self.broker.register_handler(
            "event.emit", lambda _arguments: oversized_result
        )

        tracemalloc.start()
        try:
            result = self.session.handle(event_request())
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertFalse(result.allowed)
        self.assertEqual(result.error, "result_too_large")
        self.assertLess(peak_bytes, 512 * 1024)
        self.assertEqual(self.bus.get_history(), [])

    def test_older_lifecycle_cannot_replace_a_newer_active_generation(self):
        self.broker.register_event_emit_handler()
        generation_two = self.broker.begin_lifecycle(
            "event-logger", "request-2", ("event_bus",), generation=2
        )

        with self.assertRaises(ValueError):
            self.broker.begin_lifecycle(
                "event-logger", "request-3", ("event_bus",), generation=1
            )

        stale = self.session.handle(event_request())
        current = generation_two.handle(event_request(request_id="request-2"))
        self.assertEqual(stale.error, "generation_mismatch")
        self.assertTrue(current.allowed)
        self.assertTrue(generation_two.commit_events())

    def test_non_mapping_json_arguments_are_audited_stable_denials(self):
        calls = []
        self.broker.register_handler(
            "event.emit", lambda arguments: calls.append(arguments) or {}
        )
        results = [
            self.session.handle(event_request(call_id=f"call-{index}", arguments=[index]))
            for index in range(1, MAX_BROKER_CALLS + 1)
        ]
        exhausted = self.session.handle(event_request(call_id="call-over", arguments=[]))

        self.assertTrue(all(isinstance(result, PluginBrokerResult) for result in results))
        self.assertEqual([result.error for result in results], ["invalid_arguments"] * MAX_BROKER_CALLS)
        self.assertEqual(exhausted.error, "call_budget_exceeded")
        self.assertEqual(
            [entry.reason for entry in self.broker.audit_log()[-(MAX_BROKER_CALLS + 1):]],
            ["invalid_arguments"] * MAX_BROKER_CALLS + ["call_budget_exceeded"],
        )
        self.assertEqual(calls, [])

    def test_duplicate_call_id_and_call_budget_are_denied_before_handler(self):
        self.broker.register_event_emit_handler()
        first = self.session.handle(event_request())
        duplicate = self.session.handle(event_request())
        self.assertTrue(first.allowed)
        self.assertEqual(duplicate.error, "duplicate_call_id")

        for index in range(2, MAX_BROKER_CALLS + 1):
            result = self.session.handle(event_request(call_id=f"call-{index}"))
            self.assertTrue(result.allowed)
        exhausted = self.session.handle(event_request(call_id="call-over"))
        self.assertEqual(exhausted.error, "call_budget_exceeded")
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(self.session.commit_events())
        self.assertEqual(len(self.bus.get_history()), MAX_BROKER_CALLS)

    def test_exchange_budget_and_malformed_event_are_denied_before_handler(self):
        self.broker.register_event_emit_handler()
        excessive = event_request(arguments={
            "event_type": "plugin.worker.ready",
            "payload": "x" * MAX_BROKER_EXCHANGE_BYTES,
        })
        over_budget = self.session.handle(excessive)
        malformed = self.session.handle(event_request(call_id="call-2", arguments={
            "event_type": "bad event", "payload": {"ok": True}
        }))

        self.assertEqual(over_budget.error, "exchange_budget_exceeded")
        self.assertEqual(malformed.error, "invalid_arguments")

    def test_event_emission_enforces_type_json_payload_limit_and_parent_source(self):
        self.broker.register_event_emit_handler()
        delivered = []
        self.bus.subscribe("plugin.audit.record", delivered.append)
        malicious_source = self.session.handle(event_request(arguments={
            "event_type": "plugin.audit.record",
            "payload": {"value": 1},
            "source": "event_bus",
        }))
        invalid_type = self.session.handle(event_request(call_id="call-2", arguments={
            "event_type": "system.admin", "payload": {}
        }))
        large_payload = self.session.handle(event_request(call_id="call-3", arguments={
            "event_type": "plugin.audit.record", "payload": "x" * 16_385
        }))

        self.assertTrue(malicious_source.allowed)
        self.assertEqual(self.bus.get_history(), [])
        self.assertEqual(invalid_type.error, "invalid_arguments")
        self.assertEqual(large_payload.error, "payload_too_large")
        self.assertTrue(self.session.commit_events())
        event = self.bus.get_history()[-1]
        self.assertEqual(event.source, "plugin:event-logger")
        self.assertEqual(event.event_type, "plugin.audit.record")
        self.assertEqual(delivered, [])
        self.assertFalse(self.session.commit_events())
        self.assertEqual(len(self.bus.get_history()), 1)

    def test_aborted_and_expired_sessions_never_commit_staged_events(self):
        self.broker.register_event_emit_handler()
        self.assertTrue(self.session.handle(event_request()).allowed)
        self.session.abort()
        self.assertFalse(self.session.commit_events())

        expired = self.broker.begin_lifecycle(
            "event-logger",
            "request-2",
            ("event_bus",),
            1,
            deadline=time.monotonic() - 1,
        )
        self.assertTrue(
            expired.handle(event_request(request_id="request-2")).allowed
        )
        self.assertFalse(expired.commit_events())
        self.assertEqual(self.bus.get_history(), [])

    def test_audit_log_is_bounded_redacted_and_returned_as_a_copy(self):
        broker = PluginBroker(self.bus, audit_limit=2)
        session = broker.begin_lifecycle("event-logger", "request-1", (), 1)
        for index in range(3):
            session.handle(event_request(call_id=f"call-{index}", arguments={
                "event_type": "plugin.audit.record",
                "payload": {"token": "secret-value", "index": index},
            }))

        first = broker.audit_log()
        self.assertEqual(len(first), 2)
        self.assertNotIn("secret-value", repr(first))
        first.clear()
        self.assertEqual(len(broker.audit_log()), 2)

    def test_system_stats_requires_declaration_grant_and_registered_handler(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"system.stats"}})
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("system_monitor",), generation=1
        )

        denied = session.handle(stats_request())
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_registered")

        broker.register_event_emit_handler()
        still_denied = session.handle(stats_request(call_id="call-2"))
        self.assertEqual(still_denied.error, "capability_not_registered")
        self.assertEqual(self.bus.get_history(), [])

        broker.register_system_stats_handler()
        allowed = session.handle(stats_request(call_id="call-3"))
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")
        for group in ("cpu", "memory", "disk", "network", "process"):
            self.assertIn(group, allowed.result)
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(session.commit_events())
        self.assertEqual(self.bus.get_history(), [])

        undeclared = broker.begin_lifecycle(
            "event-logger", "request-2", (), generation=1
        ).handle(stats_request(request_id="request-2"))
        self.assertEqual(undeclared.error, "capability_not_declared")

        ungranted = PluginBroker(self.bus).begin_lifecycle(
            "event-logger", "request-3", ("system_monitor",), generation=1
        ).handle(stats_request(request_id="request-3"))
        self.assertEqual(ungranted.error, "capability_not_granted")

    def test_system_stats_rejects_extra_arguments_and_unknown_capabilities(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"system.stats"}})
        broker.register_system_stats_handler()
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("system_monitor",), generation=1
        )

        invalid = session.handle(stats_request(arguments={"select": ["cpu"]}))
        self.assertFalse(invalid.allowed)
        self.assertEqual(invalid.error, "invalid_arguments")

        unsupported = session.handle(
            stats_request(call_id="call-2", capability="fs.write")
        )
        self.assertFalse(unsupported.allowed)
        self.assertEqual(unsupported.error, "capability_not_supported")

    @patch.dict("sys.modules", {"psutil": None})
    def test_system_stats_falls_back_to_empty_snapshot_without_psutil(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"system.stats"}})
        broker.register_system_stats_handler()
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("system_monitor",), generation=1
        )

        allowed = session.handle(stats_request())

        self.assertTrue(allowed.allowed)
        snapshot = allowed.result
        self.assertEqual(snapshot["cpu"], {"usage": 0, "cores": 0, "model": "N/A"})
        self.assertEqual(snapshot["memory"]["total"], 0)
        self.assertEqual(snapshot["disk"]["usage"], 0)
        self.assertEqual(
            list(snapshot["network"]["interfaces"]),
            [],
        )
        self.assertEqual(
            snapshot["process"],
            {
                "pid": 0,
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "memory_info": {"rss": 0, "vms": 0},
            },
        )

    def test_read_only_capability_identifiers_are_stable(self):
        self.assertEqual(EVENT_EMIT_CAPABILITY, "event.emit")
        self.assertEqual(SYSTEM_STATS_CAPABILITY, "system.stats")
        self.assertEqual(SYSTEM_MONITOR_PERMISSION, "system_monitor")
        self.assertEqual(FILE_READ_CAPABILITY, "file.read")
        self.assertEqual(FILE_READ_PERMISSION, "file_read")
        self.assertEqual(CONFIG_GET_CAPABILITY, "config.get")
        self.assertEqual(CONFIG_GET_PERMISSION, "system_config")
        self.assertEqual(CONFIG_GET_DENIED_REASON, "config_get_denied")
        self.assertEqual(MAX_PLUGIN_CONFIG_BYTES, 64 * 1024)
        self.assertEqual(LLM_CALL_CAPABILITY, "llm.call")
        self.assertEqual(LLM_CALL_PERMISSION, "llm_access")
        self.assertEqual(LLM_CALL_DENIED_REASON, "llm_call_denied")
        self.assertEqual(MAX_LLM_PROMPT_BYTES, 32 * 1024)
        self.assertEqual(NETWORK_GET_CAPABILITY, "network.get")
        self.assertEqual(NETWORK_GET_PERMISSION, "network")
        self.assertEqual(NETWORK_GET_DENIED_REASON, "network_get_denied")
        self.assertEqual(MAX_NETWORK_URL_BYTES, 2048)
        self.assertEqual(MAX_NETWORK_BODY_BYTES, 32 * 1024)
        self.assertEqual(MAX_NETWORK_HEADERS, 64)
        self.assertEqual(MAX_NETWORK_REDIRECTS, 3)
        self.assertEqual(
            getattr(plugin_broker_module, "FILE_LIST_CAPABILITY"), "file.list"
        )
        self.assertEqual(
            getattr(plugin_broker_module, "FILE_LIST_PERMISSION"), "file_read"
        )
        self.assertEqual(
            getattr(plugin_broker_module, "FILE_LIST_DENIED_REASON"),
            "file_list_denied",
        )
        self.assertEqual(
            getattr(plugin_broker_module, "MAX_FILE_LIST_ENTRIES"), 8_192
        )

    def test_file_read_requires_declaration_grant_and_registered_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "readme.txt").write_text("hello-broker", encoding="utf-8")
            broker = PluginBroker(self.bus, grants={"event-logger": {"file.read"}})
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("file_read",), generation=1
            )

            denied = session.handle(file_request())
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.error, "capability_not_registered")

            broker.register_event_emit_handler()
            still_denied = session.handle(file_request(call_id="call-2"))
            self.assertEqual(still_denied.error, "capability_not_registered")
            self.assertEqual(self.bus.get_history(), [])

            broker.register_file_read_handler()
            unbound = session.handle(file_request(call_id="call-3"))
            self.assertFalse(unbound.allowed)
            self.assertEqual(unbound.error, "file_read_denied")

            broker.bind_file_read_root("event-logger", root)
            allowed = session.handle(file_request(call_id="call-4"))
            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.error, "")
            self.assertEqual(allowed.result, "hello-broker")
            self.assertEqual(self.bus.get_history(), [])

            undeclared = broker.begin_lifecycle(
                "event-logger", "request-2", (), generation=1
            ).handle(file_request(request_id="request-2"))
            self.assertEqual(undeclared.error, "capability_not_declared")

            ungranted = PluginBroker(self.bus).begin_lifecycle(
                "event-logger", "request-3", ("file_read",), generation=1
            ).handle(file_request(request_id="request-3"))
            self.assertEqual(ungranted.error, "capability_not_granted")

    def test_file_read_rejects_extra_arguments_and_non_string_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broker = PluginBroker(self.bus, grants={"event-logger": {"file.read"}})
            broker.register_file_read_handler()
            broker.bind_file_read_root("event-logger", root)
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("file_read",), generation=1
            )

            extra = session.handle(
                file_request(arguments={"path": "readme.txt", "offset": 0})
            )
            self.assertEqual(extra.error, "invalid_arguments")

            non_string = session.handle(
                file_request(call_id="call-2", arguments={"path": 7})
            )
            self.assertEqual(non_string.error, "invalid_arguments")

            empty = session.handle(
                file_request(call_id="call-3", arguments={"path": ""})
            )
            self.assertEqual(empty.error, "invalid_arguments")

    def test_file_read_denies_out_of_root_traversal_and_links(self):
        with tempfile.TemporaryDirectory() as root_ctx:
            with tempfile.TemporaryDirectory() as outside_ctx:
                root = Path(root_ctx)
                outside = Path(outside_ctx)
                escape = f"../{outside.name}/secret.txt"
                (outside / "secret.txt").write_text("secret", encoding="utf-8")
                broker = PluginBroker(
                    self.bus, grants={"event-logger": {"file.read"}}
                )
                broker.register_file_read_handler()
                broker.bind_file_read_root("event-logger", root)
                session = broker.begin_lifecycle(
                    "event-logger", "request-1", ("file_read",), generation=1
                )

                denied_paths = (
                    escape,
                    str(outside / "secret.txt"),
                    ".",
                    "missing.txt",
                )
                for index, denied_path in enumerate(denied_paths, start=1):
                    with self.subTest(path=denied_path):
                        result = session.handle(
                            file_request(
                                call_id=f"call-{index}",
                                arguments={"path": denied_path},
                            )
                        )
                        self.assertFalse(result.allowed)
                        self.assertEqual(result.error, "file_read_denied")

                linked = root / "linked.txt"
                try:
                    linked.symlink_to(outside / "secret.txt")
                except (OSError, NotImplementedError):
                    pass
                else:
                    result = session.handle(
                        file_request(
                            call_id="call-link",
                            arguments={"path": "linked.txt"},
                        )
                    )
                    self.assertFalse(result.allowed)
                    self.assertEqual(result.error, "file_read_denied")

    def test_file_read_returns_content_within_nested_root_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested" / "deep"
            nested.mkdir(parents=True)
            (nested / "plan.txt").write_text("nested-content", encoding="utf-8")
            broker = PluginBroker(self.bus, grants={"event-logger": {"file.read"}})
            broker.register_file_read_handler()
            broker.bind_file_read_root("event-logger", root)
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("file_read",), generation=1
            )

            allowed = session.handle(
                file_request(arguments={"path": "nested/deep/plan.txt"})
            )

            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.result, "nested-content")

    def test_file_read_rejects_oversized_and_invalid_utf8_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.bin").write_bytes(b"x" * (MAX_FILE_READ_BYTES + 1))
            (root / "bad.txt").write_bytes(b"\xff\xfe\x01")
            broker = PluginBroker(self.bus, grants={"event-logger": {"file.read"}})
            broker.register_file_read_handler()
            broker.bind_file_read_root("event-logger", root)
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("file_read",), generation=1
            )

            oversized = session.handle(
                file_request(arguments={"path": "big.bin"})
            )
            self.assertFalse(oversized.allowed)
            self.assertEqual(oversized.error, "file_read_denied")

            invalid = session.handle(
                file_request(call_id="call-2", arguments={"path": "bad.txt"})
            )
            self.assertFalse(invalid.allowed)
            self.assertEqual(invalid.error, "file_read_denied")

    def test_file_read_denies_target_replacement_after_path_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "readme.txt"
            target.write_text("original", encoding="utf-8")
            broker = PluginBroker(self.bus, grants={"event-logger": {"file.read"}})
            broker.register_file_read_handler()
            broker.bind_file_read_root("event-logger", root)
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("file_read",), generation=1
            )
            real_open = plugin_broker_module.os.open
            replaced = False

            def open_then_replace(path, flags, *args, **kwargs):
                nonlocal replaced
                descriptor = real_open(path, flags, *args, **kwargs)
                if Path(path).name == target.name and not replaced:
                    replaced = True
                    plugin_broker_module.os.close(descriptor)
                    target.unlink()
                    target.write_text("replacement", encoding="utf-8")
                    return real_open(path, flags, *args, **kwargs)
                return descriptor

            with patch.object(
                plugin_broker_module.os, "open", side_effect=open_then_replace
            ):
                result = session.handle(file_request())

            self.assertFalse(result.allowed)
            self.assertEqual(result.error, "file_read_denied")

    def test_config_get_requires_declaration_grant_registered_and_bound_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text(
                '{"theme": "dark"}', encoding="utf-8"
            )
            broker = PluginBroker(self.bus, grants={"event-logger": {"config.get"}})
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("system_config",), generation=1
            )

            denied = session.handle(config_request())
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.error, "capability_not_registered")

            broker.register_event_emit_handler()
            still_denied = session.handle(config_request(call_id="call-2"))
            self.assertEqual(still_denied.error, "capability_not_registered")

            broker.register_config_get_handler()
            unbound = session.handle(config_request(call_id="call-3"))
            self.assertFalse(unbound.allowed)
            self.assertEqual(unbound.error, "config_get_denied")

            broker.bind_file_read_root("event-logger", root)
            allowed = session.handle(config_request(call_id="call-4"))
            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.error, "")
            self.assertEqual(allowed.result, "dark")

            undeclared = broker.begin_lifecycle(
                "event-logger", "request-2", (), generation=1
            ).handle(config_request(request_id="request-2"))
            self.assertEqual(undeclared.error, "capability_not_declared")

            ungranted = PluginBroker(self.bus).begin_lifecycle(
                "event-logger", "request-3", ("system_config",), generation=1
            ).handle(config_request(request_id="request-3"))
            self.assertEqual(ungranted.error, "capability_not_granted")

    def test_config_get_rejects_extra_arguments_and_invalid_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text('{"theme": "dark"}', encoding="utf-8")
            broker = PluginBroker(self.bus, grants={"event-logger": {"config.get"}})
            broker.register_config_get_handler()
            broker.bind_file_read_root("event-logger", root)
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("system_config",), generation=1
            )

            extra = session.handle(
                config_request(arguments={"key": "theme", "default": "x", "offset": 0})
            )
            self.assertFalse(extra.allowed)
            self.assertEqual(extra.error, "invalid_arguments")

            invalid_keys = (7, "", "bad key", "../theme", "a" * 129, "主题")
            for index, invalid_key in enumerate(invalid_keys, start=1):
                with self.subTest(key=invalid_key):
                    result = session.handle(
                        config_request(
                            call_id=f"call-invalid-{index}",
                            arguments={"key": invalid_key, "default": "x"},
                        )
                    )
                    self.assertFalse(result.allowed)
                    self.assertEqual(result.error, "config_get_denied")

    def test_config_get_missing_file_and_missing_key_return_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text('{"other": 1}', encoding="utf-8")
            broker = PluginBroker(self.bus, grants={"event-logger": {"config.get"}})
            broker.register_config_get_handler()
            broker.bind_file_read_root("event-logger", root)
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("system_config",), generation=1
            )

            missing_key = session.handle(
                config_request(arguments={"key": "theme", "default": "light"})
            )
            self.assertTrue(missing_key.allowed)
            self.assertEqual(missing_key.result, "light")

            no_default = session.handle(
                config_request(call_id="call-2", arguments={"key": "theme"})
            )
            self.assertTrue(no_default.allowed)
            self.assertIsNone(no_default.result)

        with tempfile.TemporaryDirectory() as missing_tmp:
            broker = PluginBroker(self.bus, grants={"event-logger": {"config.get"}})
            broker.register_config_get_handler()
            broker.bind_file_read_root("event-logger", Path(missing_tmp))
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("system_config",), generation=1
            )
            missing_file = session.handle(
                config_request(arguments={"key": "theme", "default": "light"})
            )
            self.assertTrue(missing_file.allowed)
            self.assertEqual(missing_file.result, "light")

    def test_config_get_denies_invalid_json_oversized_and_non_object_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broker = PluginBroker(self.bus, grants={"event-logger": {"config.get"}})
            broker.register_config_get_handler()
            broker.bind_file_read_root("event-logger", root)
            session = broker.begin_lifecycle(
                "event-logger", "request-1", ("system_config",), generation=1
            )

            oversized = b'{"k": "' + (b"x" * MAX_PLUGIN_CONFIG_BYTES) + b'"}'
            cases = (
                b"{not-json",
                b"[1, 2, 3]",
                b'"a-string"',
                b"\xff\xfe\x01",
                oversized,
            )
            for index, payload in enumerate(cases, start=1):
                with self.subTest(payload=payload[:12]):
                    (root / "config.json").write_bytes(payload)
                    result = session.handle(config_request(call_id=f"call-case-{index}"))
                    self.assertFalse(result.allowed)
                    self.assertEqual(result.error, "config_get_denied")

    def test_config_get_returns_nested_values_and_denies_reparse_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as outside_ctx:
                root = Path(tmp)
                outside = Path(outside_ctx)
                (outside / "secret.json").write_text(
                    '{"theme": "outside"}', encoding="utf-8"
                )
                (root / "config.json").write_text(
                    '{"nested": {"a": [1, 2]}, "theme": "dark"}', encoding="utf-8"
                )
                broker = PluginBroker(
                    self.bus, grants={"event-logger": {"config.get"}}
                )
                broker.register_config_get_handler()
                broker.bind_file_read_root("event-logger", root)
                session = broker.begin_lifecycle(
                    "event-logger", "request-1", ("system_config",), generation=1
                )

                nested = session.handle(config_request(arguments={"key": "nested"}))
                self.assertTrue(nested.allowed)
                self.assertEqual(nested.result, {"a": (1, 2)})

                linked = root / "config.json"
                linked.unlink()
                try:
                    linked.symlink_to(outside / "secret.json")
                except (OSError, NotImplementedError):
                    pass
                else:
                    denied = session.handle(
                        config_request(
                            call_id="call-link", arguments={"key": "theme"}
                        )
                    )
                    self.assertFalse(denied.allowed)
                    self.assertEqual(denied.error, "config_get_denied")

    def test_llm_call_requires_declaration_grant_and_registered_handler(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"llm.call"}})
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("llm_access",), generation=1
        )

        denied = session.handle(llm_request())
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_registered")

        broker.register_event_emit_handler()
        still_denied = session.handle(llm_request(call_id="call-2"))
        self.assertEqual(still_denied.error, "capability_not_registered")

        broker.register_llm_call_handler(
            lambda prompt, model: {"reply": f"{model}:{prompt}", "count": 1}
        )
        allowed = session.handle(
            llm_request(
                call_id="call-3",
                arguments={"prompt": "hi", "model": "llama3"},
            )
        )
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")
        self.assertEqual(allowed.result, {"reply": "llama3:hi", "count": 1})

        undeclared = broker.begin_lifecycle(
            "event-logger", "request-2", (), generation=1
        ).handle(llm_request(request_id="request-2"))
        self.assertEqual(undeclared.error, "capability_not_declared")

        ungranted = PluginBroker(self.bus).begin_lifecycle(
            "event-logger", "request-3", ("llm_access",), generation=1
        ).handle(llm_request(request_id="request-3"))
        self.assertEqual(ungranted.error, "capability_not_granted")

    def test_llm_call_rejects_extra_arguments_and_invalid_prompts_models(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"llm.call"}})
        broker.register_llm_call_handler(lambda prompt, model: "ok")
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("llm_access",), generation=1
        )

        extra = session.handle(
            llm_request(
                arguments={"prompt": "hi", "model": "m", "stream": True}
            )
        )
        self.assertFalse(extra.allowed)
        self.assertEqual(extra.error, "invalid_arguments")

        invalid_prompts = (7, "", None, "x" * (MAX_LLM_PROMPT_BYTES + 1))
        for index, bad_prompt in enumerate(invalid_prompts, start=1):
            with self.subTest(prompt=type(bad_prompt).__name__):
                result = session.handle(
                    llm_request(
                        call_id=f"call-prompt-{index}",
                        arguments={"prompt": bad_prompt, "model": "m"},
                    )
                )
                self.assertFalse(result.allowed)
                self.assertEqual(result.error, "llm_call_denied")

        invalid_models = (7, "", None, "a" * 129, "bad model", "../llama", "模型")
        for index, bad_model in enumerate(invalid_models, start=1):
            with self.subTest(model=repr(bad_model)):
                result = session.handle(
                    llm_request(
                        call_id=f"call-model-{index}",
                        arguments={"prompt": "hi", "model": bad_model},
                    )
                )
                self.assertFalse(result.allowed)
                self.assertEqual(result.error, "llm_call_denied")

        boundary_session = broker.begin_lifecycle(
            "event-logger", "request-boundary", ("llm_access",), generation=1
        )
        exact_boundary = boundary_session.handle(
            llm_request(
                request_id="request-boundary",
                call_id="call-boundary",
                arguments={
                    "prompt": "x" * MAX_LLM_PROMPT_BYTES,
                    "model": "default",
                },
            )
        )
        self.assertTrue(exact_boundary.allowed)
        self.assertEqual(exact_boundary.result, "ok")

    def test_llm_call_registration_requires_callable_and_failures_are_stable(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"llm.call"}})
        with self.assertRaises(ValueError):
            broker.register_llm_call_handler("not-callable")

        def denied_provider(prompt, model):
            raise PluginCapabilityDenied("llm_call_denied")

        broker.register_llm_call_handler(denied_provider)
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("llm_access",), generation=1
        )
        denied = session.handle(llm_request())
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "llm_call_denied")

        def oserror_provider(prompt, model):
            raise TimeoutError("upstream timed out")

        broker.register_llm_call_handler(oserror_provider)
        timed_out = session.handle(llm_request(call_id="call-2"))
        self.assertEqual(timed_out.error, "llm_call_denied")

        def failing_provider(prompt, model):
            raise RuntimeError("internal provider bug")

        broker.register_llm_call_handler(failing_provider)
        failed = session.handle(llm_request(call_id="call-3"))
        self.assertEqual(failed.error, "handler_failed")

    def test_llm_call_results_are_bounded_and_frozen(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"llm.call"}})
        broker.register_llm_call_handler(
            lambda prompt, model: {
                "reply": prompt,
                "tokens": [1, 2],
                "meta": {"ok": True},
            }
        )
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("llm_access",), generation=1
        )

        allowed = session.handle(
            llm_request(arguments={"prompt": "hello", "model": "m"})
        )
        self.assertTrue(allowed.allowed)
        self.assertEqual(
            allowed.result,
            {"reply": "hello", "tokens": (1, 2), "meta": {"ok": True}},
        )

        def oversized_provider(prompt, model):
            return "x" * (MAX_BROKER_EXCHANGE_BYTES + 1)

        broker.register_llm_call_handler(oversized_provider)
        oversized = session.handle(
            llm_request(
                call_id="call-2", arguments={"prompt": "hello", "model": "m"}
            )
        )
        self.assertFalse(oversized.allowed)
        self.assertEqual(oversized.error, "result_too_large")


class TestPluginBrokerFileList(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def _broker(self, root, grants=("file.list",)):
        broker = PluginBroker(
            self.bus, grants={"event-logger": set(grants)}
        )
        broker.register_file_list_handler()
        broker.bind_file_read_root("event-logger", root)
        return broker

    def _session(self, broker, permissions=("file_read",)):
        return broker.begin_lifecycle(
            "event-logger", "request-1", permissions, generation=1
        )

    def test_file_list_requires_declaration_grant_registration_and_bound_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broker = PluginBroker(
                self.bus, grants={"event-logger": {"file.list"}}
            )
            session = self._session(broker)

            unregistered = session.handle(file_list_request())
            self.assertEqual(unregistered.error, "capability_not_registered")

            broker.register_file_list_handler()
            unbound = session.handle(file_list_request(call_id="call-2"))
            self.assertEqual(unbound.error, "file_list_denied")

            broker.bind_file_read_root("event-logger", root)
            allowed = session.handle(file_list_request(call_id="call-3"))
            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.result, ())

            undeclared = broker.begin_lifecycle(
                "event-logger", "request-2", (), generation=1
            ).handle(file_list_request(request_id="request-2"))
            self.assertEqual(undeclared.error, "capability_not_declared")

            ungranted = PluginBroker(self.bus).begin_lifecycle(
                "event-logger", "request-3", ("file_read",), generation=1
            ).handle(file_list_request(request_id="request-3"))
            self.assertEqual(ungranted.error, "capability_not_granted")

    def test_file_list_returns_sorted_typed_direct_children_and_nested_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "zeta.txt").write_text("z", encoding="utf-8")
            nested = root / "alpha"
            nested.mkdir()
            (nested / "inside.txt").write_text("i", encoding="utf-8")
            session = self._session(self._broker(root))

            root_result = session.handle(file_list_request())
            self.assertTrue(root_result.allowed)
            self.assertEqual(
                root_result.result,
                (
                    {"name": "alpha", "type": "directory"},
                    {"name": "zeta.txt", "type": "file"},
                ),
            )

            nested_result = session.handle(
                file_list_request(
                    call_id="call-2", arguments={"path": "alpha"}
                )
            )
            self.assertTrue(nested_result.allowed)
            self.assertEqual(
                nested_result.result,
                ({"name": "inside.txt", "type": "file"},),
            )

    def test_file_list_rejects_invalid_arguments_and_out_of_root_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("x", encoding="utf-8")
            (root / "nested").mkdir()
            session = self._session(self._broker(root))

            invalid_arguments = (
                {},
                {"path": "", "extra": True},
                {"path": 7},
                {"path": ""},
            )
            for index, arguments in enumerate(invalid_arguments, start=1):
                with self.subTest(arguments=arguments):
                    result = session.handle(
                        file_list_request(
                            call_id=f"call-invalid-{index}", arguments=arguments
                        )
                    )
                    self.assertEqual(result.error, "invalid_arguments")

            denied_paths = (
                "..",
                "../outside",
                "nested/../.",
                "bad\x00name",
                str(root.resolve()),
                "file.txt",
            )
            for index, path in enumerate(denied_paths, start=1):
                with self.subTest(path=path):
                    result = session.handle(
                        file_list_request(
                            call_id=f"call-path-{index}",
                            arguments={"path": path},
                        )
                    )
                    self.assertEqual(result.error, "file_list_denied")

    def test_file_list_rejects_link_components_and_reports_direct_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            link = root / "linked"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            session = self._session(self._broker(root))

            root_result = session.handle(file_list_request())
            self.assertTrue(root_result.allowed)
            self.assertEqual(
                root_result.result,
                (
                    {"name": "linked", "type": "link"},
                    {"name": "target", "type": "directory"},
                ),
            )
            traversed = session.handle(
                file_list_request(
                    call_id="call-2", arguments={"path": "linked"}
                )
            )
            self.assertEqual(traversed.error, "file_list_denied")

    def test_file_list_entry_budget_accepts_boundary_and_rejects_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").touch()
            (root / "b").touch()
            session = self._session(self._broker(root))
            with patch.object(
                plugin_broker_module, "MAX_FILE_LIST_ENTRIES", 2
            ):
                boundary = session.handle(file_list_request())
                self.assertTrue(boundary.allowed)
                (root / "c").touch()
                overflow = session.handle(
                    file_list_request(call_id="call-2")
                )
            self.assertEqual(overflow.error, "file_list_denied")

    def test_file_list_scan_errors_are_stable_denials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self._session(self._broker(root))
            with patch.object(
                plugin_broker_module.os,
                "scandir",
                side_effect=OSError("scan failed"),
            ):
                result = session.handle(file_list_request())
            self.assertEqual(result.error, "file_list_denied")

    def test_file_list_denies_opened_directory_identity_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            expected = nested.stat()
            drifted = SimpleNamespace(
                st_dev=expected.st_dev,
                st_ino=expected.st_ino + 1,
                st_file_attributes=getattr(expected, "st_file_attributes", 0) or 0,
            )
            session = self._session(self._broker(root))
            with (
                patch.object(
                    plugin_broker_module,
                    "_supports_no_follow_directory_scan",
                    return_value=True,
                ),
                patch.object(
                    plugin_broker_module.os, "O_DIRECTORY", 0x10000, create=True
                ),
                patch.object(
                    plugin_broker_module.os, "O_NOFOLLOW", 0x20000, create=True
                ),
                patch.object(
                    plugin_broker_module.os, "open", side_effect=(101, 102)
                ),
                patch.object(
                    plugin_broker_module.os, "fstat", return_value=drifted
                ),
                patch.object(
                    plugin_broker_module.os,
                    "scandir",
                    return_value=contextlib.nullcontext(iter(())),
                ),
                patch.object(plugin_broker_module.os, "close") as close,
            ):
                result = session.handle(
                    file_list_request(arguments={"path": "nested"})
                )

            self.assertEqual(result.error, "file_list_denied")
            self.assertEqual(close.call_count, 2)

    def test_file_list_metadata_errors_are_stable_denials(self):
        class FailingEntry:
            name = "entry"

            def stat(self, *, follow_symlinks):
                raise OSError("metadata failed")

            def is_symlink(self):
                return False

            def is_file(self, *, follow_symlinks):
                return False

            def is_dir(self, *, follow_symlinks):
                return False

        class EntryScan:
            def __enter__(self):
                return iter((FailingEntry(),))

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(self._broker(Path(tmp)))
            with patch.object(
                plugin_broker_module.os,
                "scandir",
                return_value=EntryScan(),
            ):
                result = session.handle(file_list_request())
            self.assertEqual(result.error, "file_list_denied")

    def test_file_list_scan_budget_is_independent_from_result_wire_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = []
            for index in range(900):
                name = f"{'x' * 80}{index:03d}"
                (root / name).touch()
                entries.append(name)
            session = self._session(self._broker(root))
            with patch.object(
                plugin_broker_module, "MAX_FILE_LIST_ENTRIES", len(entries)
            ):
                result = session.handle(file_list_request())
            self.assertEqual(result.error, "result_too_large")


class TestPluginBrokerNetworkGet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = NetworkFixtureServer()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def setUp(self):
        self.bus = EventBus()

    def _allowlisted_broker(self, hosts=("127.0.0.1",)):
        broker = PluginBroker(self.bus, grants={"event-logger": {"network.get"}})
        broker.register_network_get_handler(hosts)
        return broker

    def _session(self, broker, permissions=("network",)):
        return broker.begin_lifecycle(
            "event-logger", "request-1", permissions, generation=1
        )

    def test_network_get_requires_declaration_grant_and_registered_handler(self):
        broker = PluginBroker(self.bus, grants={"event-logger": {"network.get"}})
        session = broker.begin_lifecycle(
            "event-logger", "request-1", ("network",), generation=1
        )

        denied = session.handle(network_request())
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_registered")

        broker.register_event_emit_handler()
        still_denied = session.handle(network_request(call_id="call-2"))
        self.assertEqual(still_denied.error, "capability_not_registered")

        broker.register_network_get_handler(["127.0.0.1"])
        undeclared = broker.begin_lifecycle(
            "event-logger", "request-2", (), generation=1
        ).handle(network_request(request_id="request-2"))
        self.assertEqual(undeclared.error, "capability_not_declared")

        ungranted = PluginBroker(self.bus).begin_lifecycle(
            "event-logger", "request-3", ("network",), generation=1
        ).handle(network_request(request_id="request-3"))
        self.assertEqual(ungranted.error, "capability_not_granted")

    def test_network_get_registration_validates_host_allowlist(self):
        broker = PluginBroker(self.bus)
        with self.assertRaises(ValueError):
            broker.register_network_get_handler("127.0.0.1")
        with self.assertRaises(ValueError):
            broker.register_network_get_handler([""])
        with self.assertRaises(ValueError):
            broker.register_network_get_handler([7])
        with self.assertRaises(ValueError):
            broker.register_network_get_handler(["bad host"])
        with self.assertRaises(ValueError):
            broker.register_network_get_handler(["a" * 254])

    def test_network_get_rejects_invalid_urls(self):
        broker = self._allowlisted_broker()
        session = self._session(broker)
        invalid_urls = (
            "",
            42,
            None,
            "http://",
            "ftp://example.com/file",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "http://user:pass@example.com/path",
            "http://example.com/\x00",
            "http://exa mple.com/",
            "/relative/path",
            "http://" + "a" * 300 + ".invalid/",
            "http://127.0.0.1:99999/x",
        )
        for index, url in enumerate(invalid_urls, start=1):
            with self.subTest(url=repr(url)):
                result = session.handle(
                    network_request(
                        call_id=f"call-url-{index}", arguments={"url": url}
                    )
                )
                self.assertFalse(result.allowed)
                self.assertEqual(result.error, "network_get_denied")

        too_long = "http://127.0.0.1/" + "a" * MAX_NETWORK_URL_BYTES
        oversized = session.handle(
            network_request(
                call_id="call-url-long",
                arguments={"url": too_long},
            )
        )
        self.assertFalse(oversized.allowed)
        self.assertEqual(oversized.error, "network_get_denied")

    def test_network_get_enforces_host_allowlist(self):
        broker = self._allowlisted_broker(["127.0.0.1"])
        session = self._session(broker)
        allowed = session.handle(
            network_request(
                arguments={"url": f"{self.fixture.base_url}/ok"},
            )
        )
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.result["status"], 200)

        blocked = session.handle(
            network_request(
                call_id="call-blocked",
                arguments={"url": "http://localhost:1/ok"},
            )
        )
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.error, "network_get_denied")

    def test_network_get_returns_bounded_response(self):
        broker = self._allowlisted_broker()
        session = self._session(broker)
        allowed = session.handle(
            network_request(arguments={"url": f"{self.fixture.base_url}/ok"})
        )
        self.assertTrue(allowed.allowed)
        result = allowed.result
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["body"], '{"pong": true}')
        self.assertIn("content-type", result["headers"])

        missing = session.handle(
            network_request(
                call_id="call-404",
                arguments={"url": f"{self.fixture.base_url}/missing"},
            )
        )
        self.assertTrue(missing.allowed)
        self.assertEqual(missing.result["status"], 404)

    def test_network_get_url_boundary_is_exact(self):
        broker = self._allowlisted_broker()
        session = self._session(broker)
        base = self.fixture.base_url
        suffix = "x" * (MAX_NETWORK_URL_BYTES - len(base) - 1)
        boundary = session.handle(
            network_request(arguments={"url": f"{base}/{suffix}"})
        )
        self.assertTrue(boundary.allowed)
        self.assertEqual(boundary.result["status"], 404)
        over = session.handle(
            network_request(
                call_id="call-over",
                arguments={"url": f"{base}/{suffix}x"},
            )
        )
        self.assertFalse(over.allowed)
        self.assertEqual(over.error, "network_get_denied")

    def test_network_get_follows_redirects_within_allowlist(self):
        broker = self._allowlisted_broker()
        session = self._session(broker)
        chained = session.handle(
            network_request(
                arguments={"url": f"{self.fixture.base_url}/redirect-chain"}
            )
        )
        self.assertTrue(chained.allowed)
        self.assertEqual(chained.result["status"], 200)
        self.assertEqual(chained.result["body"], '{"pong": true}')

        offsite = session.handle(
            network_request(
                call_id="call-offsite",
                arguments={
                    "url": f"{self.fixture.base_url}/redirect-offsite"
                },
            )
        )
        self.assertFalse(offsite.allowed)
        self.assertEqual(offsite.error, "network_get_denied")

        looped = session.handle(
            network_request(
                call_id="call-loop",
                arguments={"url": f"{self.fixture.base_url}/loop-a"},
            )
        )
        self.assertFalse(looped.allowed)
        self.assertEqual(looped.error, "network_get_denied")

    def test_network_get_bounds_fail_closed(self):
        broker = self._allowlisted_broker()
        session = self._session(broker)
        for path in ("/large", "/stream-large", "/nonutf8"):
            with self.subTest(path=path):
                result = session.handle(
                    network_request(
                        call_id=f"call-{path[1:]}",
                        arguments={"url": f"{self.fixture.base_url}{path}"},
                    )
                )
                self.assertFalse(result.allowed)
                self.assertEqual(result.error, "network_get_denied")

    def test_network_get_connection_failures_are_stable_denials(self):
        broker = self._allowlisted_broker()
        session = self._session(broker)
        result = session.handle(
            network_request(
                arguments={"url": "http://127.0.0.1:1/unreachable"},
            )
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.error, "network_get_denied")


if __name__ == "__main__":
    unittest.main()
