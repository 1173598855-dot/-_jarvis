"""Tests for the default-deny role tool authorization boundary."""

import sys
import tracemalloc
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.role_registry import AgentProfile
from core.brain.role_tools import (
    RoleToolBroker,
    RoleToolDeniedError,
    RoleToolPolicy,
)
from core.contracts.role_tool_protocol import (
    RoleToolBudget,
    RoleToolCall,
    RoleToolDefinition,
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
            handlers={
                "terminal_executor": lambda arguments: calls.append(arguments)
            }
        )

        self.assertEqual(broker.authorized_tools(self.profile), [])
        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(
                self.profile,
                "terminal_executor",
                {"command": "pwd"},
            )

        self.assertEqual(calls, [])
        self.assertEqual(broker.audit_log()[-1].reason, "tool_not_granted")

    def test_authorization_requires_declaration_grant_and_registration(self):
        broker = RoleToolBroker(
            policy=RoleToolPolicy(
                {"engineer": ["terminal_executor", "missing_tool"]}
            ),
            handlers={
                "terminal_executor": lambda arguments: arguments["command"]
            },
        )

        self.assertEqual(
            broker.authorized_tools(self.profile),
            ["terminal_executor"],
        )
        self.assertEqual(
            broker.invoke(
                self.profile,
                "terminal_executor",
                {"command": "pwd"},
            ),
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

        self.assertEqual(
            broker.audit_log()[-1].reason,
            "tool_not_declared",
        )

    def test_granted_but_unregistered_tool_is_denied(self):
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": ["plugin_sdk"]})
        )

        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(self.profile, "plugin_sdk")

        self.assertEqual(
            broker.audit_log()[-1].reason,
            "tool_not_registered",
        )

    def test_audit_history_is_bounded_and_returned_as_a_copy(self):
        broker = RoleToolBroker(audit_limit=2)

        for tool_name in ("one", "two", "three"):
            with self.assertRaises(RoleToolDeniedError):
                broker.invoke(self.profile, tool_name)

        first_snapshot = broker.audit_log()
        self.assertEqual(
            [item.tool_name for item in first_snapshot],
            ["two", "three"],
        )
        first_snapshot.clear()
        self.assertEqual(len(broker.audit_log()), 2)

    def test_invalid_policy_and_broker_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            RoleToolPolicy({"engineer": [""]})
        with self.assertRaises(ValueError):
            RoleToolBroker(audit_limit=0)
        with self.assertRaises(ValueError):
            RoleToolBroker(handlers={"terminal_executor": "not callable"})

    def test_broker_exposes_only_authorized_definitions(self):
        definition = RoleToolDefinition(
            name="repository_metadata",
            description="Read repository state",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
        profile = AgentProfile(
            name="engineer",
            display_name="Engineer",
            description="Implements tested changes.",
            tools=["repository_metadata", "missing_definition"],
        )
        broker = RoleToolBroker(
            policy=RoleToolPolicy(
                {"engineer": ["repository_metadata", "missing_definition"]}
            ),
            handlers={"repository_metadata": lambda arguments: arguments},
            definitions={"repository_metadata": definition},
        )

        self.assertEqual(broker.authorized_definitions(profile), [definition])

    def test_broker_validates_protocol_call_and_records_replayable_result(self):
        definition = RoleToolDefinition(
            name="repository_metadata",
            description="Read repository state",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "maxLength": 4}},
                "required": ["path"],
                "additionalProperties": False,
            },
        )
        calls = []
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": [definition.name]}),
            handlers={definition.name: lambda arguments: calls.append(arguments) or {"ok": True}},
            definitions={definition.name: definition},
            budget=RoleToolBudget(max_argument_bytes=16, max_result_bytes=16),
        )
        call = RoleToolCall.from_ollama(
            {"id": "call-1", "function": {"name": definition.name, "arguments": {"path": "src"}}},
            1,
            1,
        )

        profile = AgentProfile(
            name="engineer",
            display_name="Engineer",
            description="Implements tested changes.",
            tools=[definition.name],
        )
        self.assertEqual(broker.invoke(profile, call), {"ok": True})
        invocation = broker.invocation_log()[-1]
        self.assertTrue(invocation.allowed)
        self.assertTrue(invocation.result.success)
        self.assertEqual(invocation.call.to_dict(), call.to_dict())
        self.assertEqual(invocation.to_dict()["result"]["content"], '{"ok":true}')
        self.assertEqual(calls, [{"path": "src"}])

    def test_broker_rejects_oversized_or_schema_invalid_arguments_before_handler(self):
        definition = RoleToolDefinition(
            name="repository_metadata",
            description="Read repository state",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        )
        calls = []
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": [definition.name]}),
            handlers={definition.name: lambda arguments: calls.append(arguments)},
            definitions={definition.name: definition},
            budget=RoleToolBudget(max_argument_bytes=12),
        )

        with self.assertRaises(RoleToolDeniedError):
            broker.invoke(
                AgentProfile(
                    name="engineer",
                    display_name="Engineer",
                    description="Implements tested changes.",
                    tools=[definition.name],
                ),
                RoleToolCall.from_ollama(
                    {"function": {"name": definition.name, "arguments": {"path": "too-long"}}},
                    1,
                    1,
                ),
            )
        self.assertEqual(calls, [])
        self.assertFalse(broker.invocation_log()[-1].allowed)
        self.assertEqual(broker.invocation_log()[-1].reason, "argument_too_large")

    def test_oversized_handler_result_is_denied_before_full_serialization(self):
        definition = RoleToolDefinition(
            name="repository_metadata",
            description="Read repository state",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
        profile = AgentProfile(
            name="engineer",
            display_name="Engineer",
            description="Implements tested changes.",
            tools=[definition.name],
        )
        oversized_result = {"value": "x" * (2 * 1024 * 1024)}
        broker = RoleToolBroker(
            policy=RoleToolPolicy({profile.name: [definition.name]}),
            handlers={definition.name: lambda _arguments: oversized_result},
            definitions={definition.name: definition},
        )
        call = RoleToolCall(
            name=definition.name,
            arguments={},
            round_index=1,
            call_index=1,
        )

        tracemalloc.start()
        try:
            with self.assertRaises(RoleToolDeniedError):
                broker.invoke(profile, call)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertLess(peak_bytes, 512 * 1024)
        self.assertFalse(broker.invocation_log()[-1].allowed)
        self.assertEqual(broker.invocation_log()[-1].reason, "result_too_large")

    def test_handler_overflow_error_remains_a_handler_error(self):
        definition = RoleToolDefinition(
            name="repository_metadata",
            description="Read repository state",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
        profile = AgentProfile(
            name="engineer",
            display_name="Engineer",
            description="Implements tested changes.",
            tools=[definition.name],
        )

        def fail_handler(_arguments):
            raise OverflowError("handler fixture failed")

        broker = RoleToolBroker(
            policy=RoleToolPolicy({profile.name: [definition.name]}),
            handlers={definition.name: fail_handler},
            definitions={definition.name: definition},
        )
        call = RoleToolCall(
            name=definition.name,
            arguments={},
            round_index=1,
            call_index=1,
        )

        with self.assertRaises(OverflowError):
            broker.invoke(profile, call)
        self.assertEqual(broker.invocation_log()[-1].reason, "handler_error")


if __name__ == "__main__":
    unittest.main()
