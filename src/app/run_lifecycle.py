from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from adapters.file_run_state_repository import FileRunStateRepository
from adapters.git_workspace import GitWorkspaceInspector, WorkspaceSnapshot
from core.brain.resume_document import ResumeSections, render_resume_document
from core.contracts.context_budget import ContextWatermarkChanged
from core.contracts.run_state import ContextLevel, RunState, RunStatus, WorkPackageState

_LEVEL_ORDER = {
    ContextLevel.GREEN: 0,
    ContextLevel.AMBER: 1,
    ContextLevel.ORANGE: 2,
    ContextLevel.RED: 3,
}
_CONTEXT_ACTIONS = {
    ContextLevel.AMBER: "Deduplicate context and reference large outputs by file",
    ContextLevel.ORANGE: "Update recovery document and complete active work-package handoff",
    ContextLevel.RED: "Persist recovery checkpoint and stop dispatch before compression",
}
_SECTION_FIELDS = {
    "Confirmed Decisions": "confirmed_decisions",
    "Completed Work": "completed_work",
    "Files and Git State": "files_and_git_state",
    "Verification": "verification",
    "Agent State": "agent_state",
    "Downloaded Resources": "downloaded_resources",
    "Risks and Approvals": "risks",
    "Do Not Repeat": "do_not_repeat",
}


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    state: RunState
    reason: str
    workspace: WorkspaceSnapshot


class RunLifecycleCoordinator:
    def __init__(
        self,
        repository: FileRunStateRepository,
        git_workspace: GitWorkspaceInspector,
    ) -> None:
        self._repository = repository
        self._git_workspace = git_workspace

    def start_run(
        self,
        state: RunState,
        sections: ResumeSections | None = None,
    ) -> RecoveryOutcome:
        workspace = self._git_workspace.snapshot()
        active_sections = sections or ResumeSections()
        self._repository.save(
            state,
            render_resume_document(state, active_sections),
            events=(self._event("run.started", state, "started"),),
        )
        return RecoveryOutcome(state, "started", workspace)

    def checkpoint(
        self,
        state: RunState | None = None,
        sections: ResumeSections | None = None,
        *,
        reason: str = "manual_checkpoint",
    ) -> RecoveryOutcome | None:
        stored = self._repository.load_active()
        if stored is None and state is None:
            return None
        if stored is not None:
            if state is None:
                state = stored.state.evolve()
            elif state.revision <= stored.state.revision:
                state = state.evolve()
            active_sections = sections or self._sections_from_document(
                stored.resume_markdown
            )
        else:
            active_sections = sections or ResumeSections()
        if state is None:
            return None
        workspace = self._git_workspace.snapshot()
        self._repository.save(
            state,
            render_resume_document(state, active_sections),
            events=(self._event("run.checkpointed", state, reason),),
        )
        return RecoveryOutcome(state, reason, workspace)

    def recover_active(self) -> RecoveryOutcome | None:
        stored = self._repository.load_active()
        if stored is None:
            return None
        workspace = self._git_workspace.snapshot()
        saved = stored.state
        status = RunStatus.UNKNOWN if saved.status is RunStatus.RUNNING else saved.status
        reason, next_action = self._recovery_action(saved, workspace)
        recovered = saved.evolve(status=status, next_action=next_action)
        sections = self._sections_from_document(stored.resume_markdown)
        sections = replace(
            sections,
            files_and_git_state=sections.files_and_git_state
            + (self._workspace_summary(workspace),),
            agent_state=sections.agent_state + (f"Recovery reason: {reason}",),
        )
        self._repository.save(
            recovered,
            render_resume_document(recovered, sections),
            events=(self._event("run.recovered", recovered, reason),),
        )
        return RecoveryOutcome(recovered, reason, workspace)

    def handle_context_event(
        self,
        event: ContextWatermarkChanged,
    ) -> RecoveryOutcome | None:
        if not isinstance(event, ContextWatermarkChanged):
            raise TypeError("event must be a ContextWatermarkChanged")
        if _LEVEL_ORDER[event.current] <= _LEVEL_ORDER[event.previous]:
            return None
        stored = self._repository.load_active()
        if stored is None:
            return None
        if _LEVEL_ORDER[event.current] <= _LEVEL_ORDER[stored.state.context_level]:
            return None
        action = _CONTEXT_ACTIONS[event.current]
        state = stored.state.evolve(
            context_level=event.current,
            next_action=action,
        )
        sections = self._sections_from_document(stored.resume_markdown)
        sections = replace(
            sections,
            agent_state=sections.agent_state
            + (
                f"Context usage {event.snapshot.used_tokens}/"
                f"{event.snapshot.total_tokens} from {event.snapshot.source}",
            ),
        )
        return self.checkpoint(
            state,
            sections,
            reason=f"context_{event.current.value}",
        )

    def _recovery_action(
        self,
        state: RunState,
        workspace: WorkspaceSnapshot,
    ) -> tuple[str, str]:
        target = self._resume_target(state)
        if state.context_level is ContextLevel.RED:
            return "red_context", _CONTEXT_ACTIONS[ContextLevel.RED]
        if state.status is RunStatus.RUNNING:
            return (
                "interrupted_running",
                f"Confirm terminated workers and resource leases before resuming {target}",
            )
        if workspace.head != state.base_commit or workspace.branch != state.active_branch:
            return (
                "workspace_drift",
                "Reconcile saved "
                f"{state.base_commit}@{state.active_branch} with current "
                f"{workspace.head}@{workspace.branch} before resuming {target}",
            )
        partial = next(
            (
                package
                for package in state.work_packages
                if package.status is RunStatus.PARTIAL
            ),
            None,
        )
        if partial is not None:
            return "partial_work_package", self._partial_action(partial)
        if workspace.dirty_paths:
            count = len(workspace.dirty_paths)
            noun = "path" if count == 1 else "paths"
            return (
                "dirty_workspace",
                f"Preserve and review {count} uncommitted {noun} before resuming {target}",
            )
        return "saved_next_action", state.next_action

    @staticmethod
    def _resume_target(state: RunState) -> str:
        active = next(
            (
                package
                for package in state.work_packages
                if package.status in {RunStatus.RUNNING, RunStatus.PARTIAL}
            ),
            None,
        )
        return active.work_package_id if active is not None else state.current_stage

    @staticmethod
    def _partial_action(package: WorkPackageState) -> str:
        if package.handoff_path:
            action = f"Resume {package.work_package_id} from {package.handoff_path}"
        else:
            action = f"Review partial state for {package.work_package_id}"
        if package.next_action:
            action += f" and execute: {package.next_action}"
        return action

    @staticmethod
    def _event(event_type: str, state: RunState, reason: str) -> dict[str, Any]:
        return {
            "type": event_type,
            "run_id": state.run_id,
            "revision": state.revision,
            "reason": reason,
        }

    @staticmethod
    def _workspace_summary(workspace: WorkspaceSnapshot) -> str:
        dirty = ", ".join(workspace.dirty_paths) if workspace.dirty_paths else "clean"
        return (
            f"HEAD {workspace.head}; branch {workspace.branch}; "
            f"uncommitted paths: {dirty}"
        )

    @staticmethod
    def _sections_from_document(document: str) -> ResumeSections:
        collected: dict[str, list[str]] = {field: [] for field in _SECTION_FIELDS.values()}
        current_field: str | None = None
        for line in document.splitlines():
            if line.startswith("## "):
                current_field = _SECTION_FIELDS.get(line[3:])
                continue
            if current_field is None or not line.startswith("- "):
                continue
            value = line[2:]
            if value != "None recorded.":
                collected[current_field].append(value)
        return ResumeSections(
            **{field: tuple(values) for field, values in collected.items()}
        )
