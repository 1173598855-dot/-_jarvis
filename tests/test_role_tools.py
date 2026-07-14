"""Tests for the default-deny role tool authorization boundary."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.role_registry import AgentProfile
from core.brain.role_tools import (
    RoleToolBroker,
    RoleToolDeniedError,
    RoleToolPolicy,
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


if __name__ == "__main__":
    unittest.main()
