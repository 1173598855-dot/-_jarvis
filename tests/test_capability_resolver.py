"""Compatibility evaluation and deterministic capability resolution tests."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from core.kernel.capability_manifest import (  # noqa: E402
    CapabilityHealth,
    CapabilityKind,
    CapabilityRecord,
    CapabilityRisk,
    CapabilitySnapshot,
    CapabilityValidationError,
)
from core.kernel.capability_resolver import (  # noqa: E402
    CapabilityQuery,
    CapabilityResolver,
    CompatibilityTarget,
    evaluate_constraint,
)


def make_record(
    capability_id: str,
    *,
    name: str,
    kind: CapabilityKind = CapabilityKind.SKILL,
    description: str = "",
    compatibility=None,
    health: CapabilityHealth = CapabilityHealth.HEALTHY,
    risk: CapabilityRisk = CapabilityRisk.LOW,
    provenance_status: str = "complete",
):
    return CapabilityRecord.create(
        capability_id=capability_id,
        kind=kind,
        name=name,
        version="1.0.0",
        description=description,
        relative_path=f"capabilities/{capability_id.replace(':', '/')}",
        entrypoint=None,
        compatibility=compatibility or {},
        source_url="https://github.com/example/project",
        license_name="MIT",
        sha256="a" * 64,
        provenance_status=provenance_status,
        health=health,
        risk=risk,
    )


class TestCompatibilityEvaluation(unittest.TestCase):
    def test_numeric_constraints_support_exact_and_ordered_comparators(self):
        self.assertTrue(evaluate_constraint("3.13.5", ">=3.10,<4"))
        self.assertTrue(evaluate_constraint("1.0.0", "==1.0"))
        self.assertFalse(evaluate_constraint("22.0.0", ">22"))
        self.assertFalse(evaluate_constraint("0.9", ">=1.0"))

    def test_constraint_rejects_wildcards_prereleases_and_excessive_clauses(self):
        invalid = (
            "",
            "^1.0",
            "1.*",
            ">=1.0-beta",
            ">=1.0," * 8 + ">=1.0",
            ">=1000000.0",
        )
        for constraint in invalid:
            with self.subTest(constraint=constraint):
                with self.assertRaises(CapabilityValidationError):
                    evaluate_constraint("1.0.0", constraint)

    def test_target_rejects_invalid_runtime_versions(self):
        with self.assertRaises(CapabilityValidationError):
            CompatibilityTarget(python="3.13-rc1", node="22.0.0", jarvis_api="1.0.0")


class TestCapabilityQuery(unittest.TestCase):
    def test_query_rejects_invalid_shapes_and_bounds(self):
        invalid_arguments = (
            {"query": "x" * 257},
            {"query": "x", "limit": 0},
            {"query": "x", "limit": 101},
            {"query": "x", "limit": True},
            {"query": "x", "compatible_only": "true"},
            {"query": "x", "kind": "skill"},
            {"query": "x", "max_risk": "low"},
            {"query": "line\nbreak"},
            {"query": chr(0xD800)},
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(CapabilityValidationError):
                    CapabilityQuery(**arguments)


class TestCapabilityResolver(unittest.TestCase):
    def setUp(self):
        self.target = CompatibilityTarget(
            python="3.13.5",
            node="22.0.0",
            jarvis_api="1.0.0",
        )
        self.resolver = CapabilityResolver()
        self.snapshot = CapabilitySnapshot.create((
            make_record(
                "plugin:logger",
                name="Logger",
                kind=CapabilityKind.PLUGIN,
                description="Records lifecycle events",
                compatibility={"jarvis_api": ">=1.0,<2"},
            ),
            make_record(
                "role_tool:repository_metadata",
                name="Repository Metadata",
                kind=CapabilityKind.ROLE_TOOL,
                description="Reads repository metadata",
            ),
            make_record(
                "skill:audit-helper",
                name="Audit Helper",
                description="Searches logger output",
                compatibility={"python": ">=3.10,<4"},
                risk=CapabilityRisk.MEDIUM,
            ),
            make_record(
                "skill:future-memory",
                name="Future Memory",
                description="Memory for future Python",
                compatibility={"python": ">=99"},
            ),
            make_record(
                "ui_component:memory-panel",
                name="Memory Panel",
                kind=CapabilityKind.UI_COMPONENT,
                description="Displays memory status",
                compatibility={"browser": ">=1"},
                health=CapabilityHealth.DEGRADED,
                risk=CapabilityRisk.HIGH,
                provenance_status="incomplete",
            ),
        ))

    def test_exact_name_beats_description_match(self):
        matches = self.resolver.resolve(
            self.snapshot,
            CapabilityQuery(query="logger"),
            self.target,
        )

        self.assertEqual(matches[0].record.capability_id, "plugin:logger")
        self.assertGreater(matches[0].score, matches[1].score)
        self.assertIn("name_exact", matches[0].reasons)
        self.assertIn("description_match", matches[1].reasons)

    def test_incompatible_runtime_is_explicit_and_filterable(self):
        all_matches = self.resolver.resolve(
            self.snapshot,
            CapabilityQuery(query="memory"),
            self.target,
        )
        statuses = {
            match.record.capability_id: match.compatibility_status
            for match in all_matches
        }
        self.assertEqual(statuses["skill:future-memory"], "incompatible")
        self.assertEqual(statuses["ui_component:memory-panel"], "unknown")

        compatible = self.resolver.resolve(
            self.snapshot,
            CapabilityQuery(query="memory", compatible_only=True),
            self.target,
        )
        self.assertNotIn(
            "skill:future-memory",
            [match.record.capability_id for match in compatible],
        )
        self.assertNotIn(
            "ui_component:memory-panel",
            [match.record.capability_id for match in compatible],
        )

    def test_kind_risk_and_limit_filters_apply_before_ranking(self):
        matches = self.resolver.resolve(
            self.snapshot,
            CapabilityQuery(
                query="",
                kind=CapabilityKind.SKILL,
                max_risk=CapabilityRisk.MEDIUM,
                limit=1,
            ),
            self.target,
        )
        self.assertEqual(len(matches), 1)
        self.assertIs(matches[0].record.kind, CapabilityKind.SKILL)
        self.assertNotEqual(matches[0].record.risk, CapabilityRisk.HIGH)

    def test_role_tool_kind_is_independently_filterable(self):
        matches = self.resolver.resolve(
            self.snapshot,
            CapabilityQuery(kind=CapabilityKind.ROLE_TOOL),
            self.target,
        )

        self.assertEqual(
            [match.record.capability_id for match in matches],
            ["role_tool:repository_metadata"],
        )

    def test_ties_are_sorted_by_capability_id(self):
        snapshot = CapabilitySnapshot.create((
            make_record("skill:zeta", name="Shared"),
            make_record("skill:alpha", name="Shared"),
        ))
        matches = self.resolver.resolve(snapshot, CapabilityQuery(query="shared"), self.target)
        self.assertEqual(
            [match.record.capability_id for match in matches],
            ["skill:alpha", "skill:zeta"],
        )

    def test_unicode_query_is_casefolded_and_tokenized(self):
        snapshot = CapabilitySnapshot.create((
            make_record("skill:memory", name="记忆管理", description="本地长期记忆"),
        ))
        matches = self.resolver.resolve(snapshot, CapabilityQuery(query="长期记忆"), self.target)
        self.assertEqual(matches[0].record.capability_id, "skill:memory")
        self.assertIn("description_match", matches[0].reasons)

    def test_public_match_overlays_evaluated_status_without_mutating_record(self):
        match = self.resolver.resolve(
            self.snapshot,
            CapabilityQuery(query="logger"),
            self.target,
        )[0]
        body = match.to_public_dict()
        self.assertEqual(body["compatibility"]["status"], "compatible")
        self.assertEqual(match.record.compatibility_status, "unknown")
        self.assertEqual(body["match"]["score"], match.score)
        self.assertEqual(body["match"]["reasons"], list(match.reasons))


if __name__ == "__main__":
    unittest.main()
