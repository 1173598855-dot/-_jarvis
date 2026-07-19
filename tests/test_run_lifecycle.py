import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.file_run_state_repository import FileRunStateRepository
from adapters.git_workspace import GitWorkspaceInspector, WorkspaceSnapshot
from app.run_lifecycle import RunLifecycleCoordinator
from core.brain.resume_document import ResumeSections, render_resume_document
from core.contracts.context_budget import ContextBudgetSnapshot, ContextWatermarkChanged
from core.contracts.run_state import ContextLevel, RunState, RunStatus, WorkPackageState


class FakeGit:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class TestRunLifecycleCoordinator(unittest.TestCase):
    def make_state(
        self,
        *,
        status=RunStatus.PLANNING,
        context_level=ContextLevel.GREEN,
        base_commit="a" * 40,
        branch="codex/iteration-101-core-contracts",
        work_packages=(),
        next_action="Finish atomic replacement test",
    ):
        return RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit=base_commit,
            active_branch=branch,
            next_action=next_action,
            status=status,
            context_level=context_level,
            work_packages=work_packages,
        )

    def make_package(self, status=RunStatus.RUNNING, *, handoff_path=None):
        return WorkPackageState(
            work_package_id="A2" if status is RunStatus.RUNNING else "A4",
            objective="Persist recovery state",
            status=status,
            handoff_path=handoff_path,
            next_action="Finish atomic replacement test",
        )

    def coordinator(self, root, state, *, dirty_paths=(), head=None, branch=None):
        repository = FileRunStateRepository(Path(root), lambda: b"k" * 32)
        repository.save(
            state,
            render_resume_document(
                state,
                ResumeSections(confirmed_decisions=("Keep local-first behavior",)),
            ),
        )
        snapshot = WorkspaceSnapshot(
            head=head or state.base_commit,
            branch=branch or state.active_branch,
            dirty_paths=dirty_paths,
        )
        return RunLifecycleCoordinator(repository, FakeGit(snapshot)), repository

    def test_running_state_becomes_unknown_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self.make_state(status=RunStatus.RUNNING)
            coordinator, _ = self.coordinator(tmp, state)

            outcome = coordinator.recover_active()

            self.assertEqual(outcome.state.status, RunStatus.UNKNOWN)
            self.assertIn("Confirm terminated workers", outcome.state.next_action)

    def test_dirty_workspace_has_one_preservation_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = self.make_package()
            state = self.make_state(work_packages=(package,))
            coordinator, _ = self.coordinator(
                tmp,
                state,
                dirty_paths=("src/main_fastapi.py",),
            )

            outcome = coordinator.recover_active()

            self.assertEqual(
                outcome.state.next_action,
                "Preserve and review 1 uncommitted path before resuming A2",
            )

    def test_partial_package_resumes_exact_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = self.make_package(
                RunStatus.PARTIAL,
                handoff_path=".auto-memory/runs/run-20260716-043000/agents/a4.md",
            )
            state = self.make_state(work_packages=(package,))
            coordinator, _ = self.coordinator(tmp, state)

            outcome = coordinator.recover_active()

            self.assertIn("A4", outcome.state.next_action)
            self.assertIn("agents/a4.md", outcome.state.next_action)

    def test_drift_precedes_partial_and_dirty_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = self.make_package(
                RunStatus.PARTIAL,
                handoff_path="agents/a4.md",
            )
            state = self.make_state(work_packages=(package,))
            coordinator, _ = self.coordinator(
                tmp,
                state,
                dirty_paths=("src/main.py",),
                head="b" * 40,
            )

            outcome = coordinator.recover_active()

            self.assertEqual(outcome.reason, "workspace_drift")
            self.assertIn("a" * 40, outcome.state.next_action)
            self.assertIn("b" * 40, outcome.state.next_action)

    def test_red_watermark_has_highest_priority_and_persists_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = self.make_package(
                RunStatus.PARTIAL,
                handoff_path="agents/a4.md",
            )
            state = self.make_state(
                status=RunStatus.RUNNING,
                context_level=ContextLevel.RED,
                work_packages=(package,),
            )
            coordinator, repository = self.coordinator(
                tmp,
                state,
                dirty_paths=("src/main.py",),
                head="b" * 40,
            )

            outcome = coordinator.recover_active()
            reloaded = repository.load_active().state

            self.assertEqual(outcome.reason, "red_context")
            self.assertEqual(outcome.state.status, RunStatus.UNKNOWN)
            self.assertEqual(
                outcome.state.next_action,
                "Persist recovery checkpoint and stop dispatch before compression",
            )
            self.assertEqual(reloaded, outcome.state)

    def test_context_escalation_checkpoints_and_non_escalation_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self.make_state()
            coordinator, repository = self.coordinator(tmp, state)
            red = ContextWatermarkChanged(
                ContextLevel.ORANGE,
                ContextLevel.RED,
                ContextBudgetSnapshot(95, 100, "runtime"),
            )

            outcome = coordinator.handle_context_event(red)
            ignored = coordinator.handle_context_event(
                ContextWatermarkChanged(
                    ContextLevel.RED,
                    ContextLevel.ORANGE,
                    ContextBudgetSnapshot(85, 100, "runtime"),
                )
            )

            self.assertEqual(outcome.state.context_level, ContextLevel.RED)
            self.assertEqual(
                outcome.state.next_action,
                "Persist recovery checkpoint and stop dispatch before compression",
            )
            self.assertIsNone(ignored)
            self.assertEqual(repository.load_active().state.revision, state.revision + 1)


class TestGitWorkspaceInspector(unittest.TestCase):
    def test_snapshot_reads_real_temporary_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(("git", "init", "-q"), cwd=root, check=True)
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(("git", "add", "tracked.txt"), cwd=root, check=True)
            subprocess.run(
                (
                    "git",
                    "-c",
                    "user.name=JARVIS Test",
                    "-c",
                    "user.email=jarvis@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "initial",
                ),
                cwd=root,
                check=True,
            )
            (root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            (root / "untracked.txt").write_text("new\n", encoding="utf-8")

            snapshot = GitWorkspaceInspector(root).snapshot()

            self.assertRegex(snapshot.head, r"^[0-9a-f]{40}$")
            self.assertTrue(snapshot.branch)
            self.assertEqual(snapshot.dirty_paths, ("tracked.txt", "untracked.txt"))

    def test_snapshot_uses_only_fixed_commands_and_sanitized_environment(self):
        outputs = (
            subprocess.CompletedProcess((), 0, stdout=b"a" * 40 + b"\n", stderr=b""),
            subprocess.CompletedProcess((), 0, stdout=b"codex/test\n", stderr=b""),
            subprocess.CompletedProcess((), 0, stdout=b" M src/main.py\0", stderr=b""),
        )
        with patch("adapters.git_workspace.subprocess.run", side_effect=outputs) as run:
            snapshot = GitWorkspaceInspector(Path.cwd()).snapshot()

        self.assertEqual(snapshot.dirty_paths, ("src/main.py",))
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ("git", "rev-parse", "HEAD"),
                ("git", "branch", "--show-current"),
                ("git", "status", "--porcelain=v1", "-z"),
            ],
        )
        for call in run.call_args_list:
            kwargs = call.kwargs
            self.assertFalse(kwargs["shell"])
            self.assertTrue(kwargs["check"])
            self.assertTrue(kwargs["capture_output"])
            self.assertEqual(kwargs["timeout"], 10)
            self.assertEqual(kwargs["env"]["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertLessEqual(
                set(kwargs["env"]),
                {
                    "PATH",
                    "SYSTEMROOT",
                    "WINDIR",
                    "TEMP",
                    "TMP",
                    "HOME",
                    "USERPROFILE",
                    "GIT_CONFIG_NOSYSTEM",
                },
            )


if __name__ == "__main__":
    unittest.main()
