"""Tests for the immutable built-in role-tool catalog and assembly evidence."""

import json
import re
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts.role_tool_catalog import (  # noqa: E402
    ROLE_TOOL_CAPABILITY_IDS,
    ROLE_TOOL_CATALOG,
    RoleToolAssembly,
    role_tool_catalog_digest,
    role_tool_definitions,
)
from core.contracts.role_tool_protocol import (  # noqa: E402
    RoleToolProtocolError,
)

EXPECTED_TOOLS = {
    "memory_search": "role_tool:memory_search",
    "model_list": "role_tool:model_list",
    "orchestrator_status": "role_tool:orchestrator_status",
    "repository_metadata": "role_tool:repository_metadata",
    "system_status": "role_tool:system_status",
}


class TestRoleToolCatalog(unittest.TestCase):
    def test_catalog_is_exact_immutable_and_deterministic(self):
        by_name = {
            entry.definition.name: entry.capability_id
            for entry in ROLE_TOOL_CATALOG
        }

        self.assertEqual(by_name, EXPECTED_TOOLS)
        self.assertEqual(
            ROLE_TOOL_CAPABILITY_IDS,
            tuple(sorted(EXPECTED_TOOLS.values())),
        )
        self.assertEqual(
            list(role_tool_definitions()),
            [entry.definition.name for entry in ROLE_TOOL_CATALOG],
        )
        self.assertRegex(role_tool_catalog_digest(), r"^[0-9a-f]{64}$")
        self.assertEqual(
            role_tool_catalog_digest(),
            role_tool_catalog_digest(),
        )
        for entry in ROLE_TOOL_CATALOG:
            self.assertRegex(entry.descriptor_sha256, r"^[0-9a-f]{64}$")
            self.assertEqual(entry.permissions, tuple(sorted(set(entry.permissions))))
            with self.assertRaises(FrozenInstanceError):
                entry.capability_id = "role_tool:changed"
            with self.assertRaises(TypeError):
                entry.definition.parameters["type"] = "string"

    def test_assembly_round_trips_as_bounded_json(self):
        assembly = RoleToolAssembly.for_catalog()
        payload = assembly.to_dict()

        self.assertEqual(payload, {
            "schema_version": 1,
            "capability_ids": list(ROLE_TOOL_CAPABILITY_IDS),
            "catalog_sha256": role_tool_catalog_digest(),
        })
        self.assertEqual(
            RoleToolAssembly.from_value(
                json.loads(json.dumps(payload))
            ),
            assembly,
        )
        self.assertLess(len(json.dumps(payload).encode("utf-8")), 1024)

    def test_assembly_rejects_noncanonical_or_mismatched_evidence(self):
        class DictSubclass(dict):
            pass

        class StringSubclass(str):
            pass

        valid = RoleToolAssembly.for_catalog().to_dict()
        invalid_values = (
            None,
            [],
            DictSubclass(valid),
            {**valid, "extra": True},
            {key: value for key, value in valid.items() if key != "catalog_sha256"},
            {**valid, "schema_version": True},
            {**valid, "schema_version": 2},
            {**valid, "capability_ids": "role_tool:system_status"},
            {**valid, "capability_ids": tuple(valid["capability_ids"])},
            {
                **valid,
                "capability_ids": [
                    StringSubclass(capability_id)
                    for capability_id in valid["capability_ids"]
                ],
            },
            {**valid, "capability_ids": [*valid["capability_ids"], valid["capability_ids"][0]]},
            {**valid, "capability_ids": list(reversed(valid["capability_ids"]))},
            {**valid, "capability_ids": valid["capability_ids"][:-1]},
            {**valid, "capability_ids": [*valid["capability_ids"][:-1], "role_tool:unknown"]},
            {**valid, "catalog_sha256": StringSubclass(valid["catalog_sha256"])},
            {**valid, "catalog_sha256": "A" * 64},
            {**valid, "catalog_sha256": "0" * 64},
        )

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(RoleToolProtocolError):
                    RoleToolAssembly.from_value(value)

    def test_catalog_ids_and_hashes_are_public_identifier_safe(self):
        identifier = re.compile(r"^role_tool:[a-z0-9][a-z0-9._-]{0,127}$")

        self.assertTrue(ROLE_TOOL_CATALOG)
        for entry in ROLE_TOOL_CATALOG:
            self.assertRegex(entry.capability_id, identifier)
            self.assertNotIn("\\", entry.capability_id)


if __name__ == "__main__":
    unittest.main()
