import tempfile
import unittest
from pathlib import Path

from adapters.file_run_state_repository import FileRunStateRepository
from adapters.git_workspace import WorkspaceSnapshot
from app.run_lifecycle import RunLifecycleCoordinator
from core.brain.resume_document import ResumeSections, render_resume_document
from core.contracts.run_state import ContextLevel, RunState, RunStatus, WorkPackageState


class FakeGit:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class TestPhaseARecoveryGate(unittest.TestCase):
    def test_red_restart_with_dirty_work_and_partial_agent_has_one_safe_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = FileRunStateRepository(Path(tmp), lambda: b"k" * 32)
            package = WorkPackageState(
                work_package_id="A4",
                objective="Persist recovery state",
                status=RunStatus.PARTIAL,
                handoff_path="agents/a4.md",
                next_action="Finish atomic replacement test",
            )
            state = RunState.new(
                run_id="run-20260716-043000",
                goal="Complete Phase A",
                current_stage="A",
                base_commit="a" * 40,
                active_branch="codex/iteration-101-core-contracts",
                status=RunStatus.RUNNING,
                context_level=ContextLevel.RED,
                work_packages=(package,),
                next_action="Finish atomic replacement test",
            )
            repository.save(
                state,
                render_resume_document(
                    state,
                    ResumeSections(agent_state=("A4 partial at agents/a4.md",)),
                ),
            )
            coordinator = RunLifecycleCoordinator(
                repository,
                FakeGit(
                    WorkspaceSnapshot(
                        head=state.base_commit,
                        branch=state.active_branch,
                        dirty_paths=("src/main_fastapi.py",),
                    )
                ),
            )

            outcome = coordinator.recover_active()
            reloaded = repository.load_active().state

            self.assertEqual(outcome.state.next_action, reloaded.next_action)
            self.assertEqual(
                reloaded.next_action,
                "Persist recovery checkpoint and stop dispatch before compression",
            )
            self.assertEqual(reloaded.status, RunStatus.UNKNOWN)
            self.assertEqual(reloaded.revision, state.revision + 1)
            self.assertEqual(outcome.reason, "red_context")


if __name__ == "__main__":
    unittest.main()
