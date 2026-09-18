from __future__ import annotations

from dataclasses import dataclass

from core.contracts.run_state import RunState
from core.kernel.secret_redaction import redact_text


@dataclass(frozen=True, slots=True)
class ResumeSections:
    confirmed_decisions: tuple[str, ...] = ()
    completed_work: tuple[str, ...] = ()
    files_and_git_state: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    agent_state: tuple[str, ...] = ()
    downloaded_resources: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    do_not_repeat: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")


def _header_value(value: object) -> str:
    if value is None:
        return ""
    return " ".join(redact_text(str(value)).splitlines())


def _render_items(items: tuple[str, ...]) -> list[str]:
    if not items:
        return ["- None recorded."]
    rendered = []
    for item in items:
        safe_lines = redact_text(item).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        rendered.append(f"- {safe_lines[0]}")
        rendered.extend(f"  {line}" for line in safe_lines[1:])
    return rendered


def render_resume_document(state: RunState, sections: ResumeSections) -> str:
    if not isinstance(state, RunState):
        raise TypeError("state must be a RunState")
    if not isinstance(sections, ResumeSections):
        raise TypeError("sections must be ResumeSections")

    lines = [
        f"schema_version: {state.schema_version}",
        f"run_id: {_header_value(state.run_id)}",
        f"revision: {state.revision}",
        f"updated_at: {_header_value(state.updated_at)}",
        f"goal: {_header_value(state.goal)}",
        f"current_stage: {_header_value(state.current_stage)}",
        f"status: {state.status.value}",
        f"base_commit: {_header_value(state.base_commit)}",
        f"active_branch: {_header_value(state.active_branch)}",
        f"context_level: {state.context_level.value}",
        f"next_action: {_header_value(state.next_action)}",
        f"next_command: {_header_value(state.next_command)}",
    ]

    section_content = (
        ("Current Goal", (state.goal,)),
        ("Confirmed Decisions", sections.confirmed_decisions),
        ("Completed Work", sections.completed_work),
        ("Files and Git State", sections.files_and_git_state),
        ("Verification", sections.verification),
        ("Agent State", sections.agent_state),
        ("Downloaded Resources", sections.downloaded_resources),
        ("Risks and Approvals", sections.risks),
        (
            "Next Step",
            (state.next_action,)
            + ((f"Suggested command: {state.next_command}",) if state.next_command else ()),
        ),
        ("Do Not Repeat", sections.do_not_repeat),
    )
    for heading, items in section_content:
        lines.extend(("", f"## {heading}"))
        lines.extend(_render_items(items))
    return "\n".join(lines) + "\n"
