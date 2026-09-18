import unittest
from dataclasses import replace

from core.contracts.run_state import (
    ContextLevel,
    RunState,
    RunStatus,
    StageState,
    WorkPackageState,
)


class TestRunState(unittest.TestCase):
    def test_round_trip_preserves_nested_state(self):
        stage = StageState(
            stage_id="A",
            objective="Context continuity",
            status=RunStatus.RUNNING,
            acceptance_criteria=("restart has one next action",),
        )
        package = WorkPackageState(
            work_package_id="A2",
            objective="Define state contracts",
            status=RunStatus.RUNNING,
            allowed_paths=("src/core/contracts/",),
            acceptance_commands=(
                r".\venv\Scripts\python.exe -m unittest tests.test_run_state",
            ),
            next_action="Implement RunState serialization",
        )
        state = RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Implement RunState serialization",
            stages=(stage,),
            work_packages=(package,),
        )

        restored = RunState.from_dict(state.to_dict())

        self.assertEqual(restored, state)
        self.assertEqual(restored.schema_version, 1)

    def test_generic_next_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "next_action"):
            RunState.new(
                run_id="run-20260716-043000",
                goal="Complete Phase A",
                current_stage="A",
                base_commit="a" * 40,
                active_branch="codex/iteration-101-core-contracts",
                next_action="继续开发",
            )

    def test_evolve_increments_revision_and_rejects_revision_regression(self):
        state = RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Write state contract tests",
        )

        evolved = state.evolve(
            status=RunStatus.VERIFYING,
            context_level=ContextLevel.AMBER,
            next_action="Run focused state contract tests",
        )

        self.assertEqual(evolved.revision, state.revision + 1)
        with self.assertRaisesRegex(ValueError, "revision"):
            replace(evolved, revision=state.revision)


if __name__ == "__main__":
    unittest.main()
