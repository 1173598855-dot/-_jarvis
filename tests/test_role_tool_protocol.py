"""Tests for immutable, versioned role-tool protocol values."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import core.contracts.role_tool_protocol as role_tool_protocol
from core.contracts.role_tool_protocol import (
    RoleToolBudget,
    RoleToolCall,
    RoleToolDefinition,
    RoleToolProtocolError,
    RoleToolResult,
    stable_json_bytes,
)


class TestRoleToolProtocol(unittest.TestCase):
    def setUp(self):
        self.definition = RoleToolDefinition(
            name="repository_metadata",
            description="Read repository state",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 24},
                    "depth": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["brief", "full"],
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    def test_definition_exports_ollama_function_contract(self):
        exported = self.definition.to_ollama()

        self.assertEqual(exported["type"], "function")
        self.assertEqual(
            exported["function"]["name"],
            "repository_metadata",
        )
        self.assertEqual(
            exported["function"]["parameters"]["additionalProperties"],
            False,
        )

    def test_definition_rejects_non_strict_object_schemas(self):
        with self.assertRaises(RoleToolProtocolError):
            RoleToolDefinition(
                name="unsafe",
                description="unsafe",
                parameters={"type": "object", "properties": {}},
            )
        with self.assertRaises(RoleToolProtocolError):
            RoleToolDefinition(
                name="invalid",
                description="invalid",
                parameters={
                    "type": "object",
                    "properties": {"flag": {"type": "boolean", "minimum": 0}},
                    "additionalProperties": False,
                },
            )

    def test_definition_validates_required_properties_and_value_bounds(self):
        self.definition.validate_arguments(
            {"path": "src", "depth": 2, "mode": "brief"}
        )

        for arguments in (
            {},
            {"path": "a" * 25},
            {"path": "src", "depth": True},
            {"path": "src", "depth": 4},
            {"path": "src", "mode": "other"},
            {"path": "src", "extra": "no"},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(RoleToolProtocolError):
                    self.definition.validate_arguments(arguments)

    def test_call_parses_object_arguments_and_rejects_malformed_values(self):
        call = RoleToolCall.from_ollama(
            {
                "id": "call-7",
                "function": {
                    "name": "repository_metadata",
                    "arguments": '{"path":"src"}',
                },
            },
            1,
            1,
        )

        self.assertEqual(call.name, "repository_metadata")
        self.assertEqual(call.arguments, {"path": "src"})
        self.assertEqual(call.call_id, "call-7")
        with self.assertRaises(RoleToolProtocolError):
            RoleToolCall.from_ollama(
                {"function": {"name": "", "arguments": {}}}, 1, 1
            )
        with self.assertRaises(RoleToolProtocolError):
            RoleToolCall.from_ollama(
                {"function": {"name": "repository_metadata", "arguments": "[]"}},
                1,
                1,
            )

    def test_result_and_budget_enforce_stable_json_byte_limits(self):
        result = RoleToolResult.from_value({"label": "中文"})
        self.assertEqual(result.content, '{"label":"中文"}')
        self.assertEqual(result.byte_size, len(result.content.encode("utf-8")))
        with self.assertRaises(RoleToolProtocolError):
            RoleToolResult.from_value(float("nan"))
        with self.assertRaises(RoleToolProtocolError):
            RoleToolBudget(max_argument_bytes=0)
        with self.assertRaises(RoleToolProtocolError):
            RoleToolBudget(max_elapsed_seconds=0)

    def test_stable_json_bytes_canonicalizes_object_key_order(self):
        self.assertEqual(
            stable_json_bytes({"second": 2, "first": 1}),
            b'{"first":1,"second":2}',
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
                    role_tool_protocol.bounded_stable_json_size(
                        value, expected
                    ),
                    expected,
                )
                with self.assertRaises(OverflowError):
                    role_tool_protocol.bounded_stable_json_size(
                        value, expected - 1
                    )

    def test_bounded_stable_json_size_validates_limits_and_values(self):
        for limit in (True, -1, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    role_tool_protocol.bounded_stable_json_size(None, limit)

        with self.assertRaises(RoleToolProtocolError):
            role_tool_protocol.bounded_stable_json_size(object(), 64)


if __name__ == "__main__":
    unittest.main()
