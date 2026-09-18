from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = 1
_GENERIC_ACTIONS = {"continue", "continue development", "继续", "继续开发"}
_RUN_ID = re.compile(r"^run-[0-9]{8}-[0-9]{6}(?:-[a-z0-9]{4,12})?$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class RunStatus(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    VERIFYING = "verifying"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    UNKNOWN = "unknown"
    PARTIAL = "partial"


class ContextLevel(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    ORANGE = "orange"
    RED = "red"


def _non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a tuple")
    for item in value:
        _non_empty(item, field_name)
    return value


def _validate_next_action(value: object, field_name: str = "next_action") -> str:
    action = _non_empty(value, field_name)
    if " ".join(action.split()).casefold() in _GENERIC_ACTIONS:
        raise ValueError(f"{field_name} must describe one concrete action")
    return action


def _expect_exact_fields(
    value: object,
    expected: set[str],
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unknown:
            details.append(f"unknown {sorted(unknown)}")
        raise ValueError(f"{field_name} has {'; '.join(details)}")
    return value


def _json_array(value: object, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a JSON array")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class StageState:
    stage_id: str
    objective: str
    status: RunStatus
    acceptance_criteria: tuple[str, ...] = ()
    completed_work_packages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.stage_id, "stage_id")
        _non_empty(self.objective, "objective")
        if not isinstance(self.status, RunStatus):
            raise ValueError("status must be a supported RunStatus")
        _string_tuple(self.acceptance_criteria, "acceptance_criteria")
        _string_tuple(self.completed_work_packages, "completed_work_packages")


@dataclass(frozen=True, slots=True)
class WorkPackageState:
    work_package_id: str
    objective: str
    status: RunStatus
    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    acceptance_commands: tuple[str, ...] = ()
    handoff_path: str | None = None
    next_action: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.work_package_id, "work_package_id")
        _non_empty(self.objective, "objective")
        if not isinstance(self.status, RunStatus):
            raise ValueError("status must be a supported RunStatus")
        _string_tuple(self.allowed_paths, "allowed_paths")
        _string_tuple(self.forbidden_paths, "forbidden_paths")
        _string_tuple(self.dependencies, "dependencies")
        _string_tuple(self.acceptance_commands, "acceptance_commands")
        if self.handoff_path is not None:
            _non_empty(self.handoff_path, "handoff_path")
        if self.next_action is not None:
            _validate_next_action(self.next_action)


@dataclass(frozen=True, slots=True)
class RunState:
    schema_version: int
    run_id: str
    revision: int
    updated_at: str
    goal: str
    current_stage: str
    status: RunStatus
    base_commit: str
    active_branch: str
    context_level: ContextLevel
    next_action: str
    next_command: str | None = None
    stages: tuple[StageState, ...] = ()
    work_packages: tuple[WorkPackageState, ...] = ()
    _revision_floor: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool):
            raise ValueError("revision must be a positive integer")
        if self.revision < 1 or self.revision < self._revision_floor:
            raise ValueError("revision must not regress")
        if not isinstance(self._revision_floor, int) or self._revision_floor < 1:
            raise ValueError("revision floor must be a positive integer")
        if not isinstance(self.run_id, str) or not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id must use the canonical run timestamp format")
        _non_empty(self.goal, "goal")
        _non_empty(self.current_stage, "current_stage")
        if not isinstance(self.base_commit, str) or not _COMMIT.fullmatch(self.base_commit):
            raise ValueError("base_commit must be a 40-character lowercase hex commit")
        _non_empty(self.active_branch, "active_branch")
        if not isinstance(self.status, RunStatus):
            raise ValueError("status must be a supported RunStatus")
        if not isinstance(self.context_level, ContextLevel):
            raise ValueError("context_level must be a supported ContextLevel")
        _validate_next_action(self.next_action)
        if self.next_command is not None:
            _non_empty(self.next_command, "next_command")
        if not isinstance(self.stages, tuple) or not all(
            isinstance(stage, StageState) for stage in self.stages
        ):
            raise ValueError("stages must be a tuple of StageState values")
        if not isinstance(self.work_packages, tuple) or not all(
            isinstance(package, WorkPackageState) for package in self.work_packages
        ):
            raise ValueError("work_packages must be a tuple of WorkPackageState values")
        stage_ids = [stage.stage_id for stage in self.stages]
        package_ids = [package.work_package_id for package in self.work_packages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("stage_id values must be unique")
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("work_package_id values must be unique")
        try:
            parsed_time = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("updated_at must be an ISO timestamp") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ValueError("updated_at must include a timezone")

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        goal: str,
        current_stage: str,
        base_commit: str,
        active_branch: str,
        next_action: str,
        status: RunStatus = RunStatus.PLANNING,
        context_level: ContextLevel = ContextLevel.GREEN,
        next_command: str | None = None,
        stages: tuple[StageState, ...] = (),
        work_packages: tuple[WorkPackageState, ...] = (),
    ) -> RunState:
        return cls(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            revision=1,
            updated_at=datetime.now(timezone.utc).isoformat(),
            goal=goal,
            current_stage=current_stage,
            status=status,
            base_commit=base_commit,
            active_branch=active_branch,
            context_level=context_level,
            next_action=next_action,
            next_command=next_command,
            stages=stages,
            work_packages=work_packages,
            _revision_floor=1,
        )

    def evolve(self, **changes: object) -> RunState:
        protected = {"schema_version", "revision", "updated_at", "_revision_floor"}
        attempted = protected.intersection(changes)
        if attempted:
            raise ValueError(f"cannot override managed fields: {sorted(attempted)}")
        next_revision = self.revision + 1
        return replace(
            self,
            **changes,
            revision=next_revision,
            updated_at=datetime.now(timezone.utc).isoformat(),
            _revision_floor=next_revision,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "goal": self.goal,
            "current_stage": self.current_stage,
            "status": self.status.value,
            "base_commit": self.base_commit,
            "active_branch": self.active_branch,
            "context_level": self.context_level.value,
            "next_action": self.next_action,
            "next_command": self.next_command,
            "stages": [
                {
                    "stage_id": stage.stage_id,
                    "objective": stage.objective,
                    "status": stage.status.value,
                    "acceptance_criteria": list(stage.acceptance_criteria),
                    "completed_work_packages": list(stage.completed_work_packages),
                }
                for stage in self.stages
            ],
            "work_packages": [
                {
                    "work_package_id": package.work_package_id,
                    "objective": package.objective,
                    "status": package.status.value,
                    "allowed_paths": list(package.allowed_paths),
                    "forbidden_paths": list(package.forbidden_paths),
                    "dependencies": list(package.dependencies),
                    "acceptance_commands": list(package.acceptance_commands),
                    "handoff_path": package.handoff_path,
                    "next_action": package.next_action,
                }
                for package in self.work_packages
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> RunState:
        top_fields = {
            "schema_version",
            "run_id",
            "revision",
            "updated_at",
            "goal",
            "current_stage",
            "status",
            "base_commit",
            "active_branch",
            "context_level",
            "next_action",
            "next_command",
            "stages",
            "work_packages",
        }
        raw = _expect_exact_fields(value, top_fields, "run state")
        stage_fields = {
            "stage_id",
            "objective",
            "status",
            "acceptance_criteria",
            "completed_work_packages",
        }
        package_fields = {
            "work_package_id",
            "objective",
            "status",
            "allowed_paths",
            "forbidden_paths",
            "dependencies",
            "acceptance_commands",
            "handoff_path",
            "next_action",
        }

        stages = []
        for index, item in enumerate(_json_array(raw["stages"], "stages")):
            stage = _expect_exact_fields(item, stage_fields, f"stages[{index}]")
            try:
                status = RunStatus(stage["status"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"stages[{index}].status is unsupported") from exc
            stages.append(
                StageState(
                    stage_id=stage["stage_id"],
                    objective=stage["objective"],
                    status=status,
                    acceptance_criteria=_json_array(
                        stage["acceptance_criteria"],
                        f"stages[{index}].acceptance_criteria",
                    ),
                    completed_work_packages=_json_array(
                        stage["completed_work_packages"],
                        f"stages[{index}].completed_work_packages",
                    ),
                )
            )

        packages = []
        for index, item in enumerate(_json_array(raw["work_packages"], "work_packages")):
            package = _expect_exact_fields(item, package_fields, f"work_packages[{index}]")
            try:
                status = RunStatus(package["status"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"work_packages[{index}].status is unsupported") from exc
            packages.append(
                WorkPackageState(
                    work_package_id=package["work_package_id"],
                    objective=package["objective"],
                    status=status,
                    allowed_paths=_json_array(
                        package["allowed_paths"], f"work_packages[{index}].allowed_paths"
                    ),
                    forbidden_paths=_json_array(
                        package["forbidden_paths"],
                        f"work_packages[{index}].forbidden_paths",
                    ),
                    dependencies=_json_array(
                        package["dependencies"], f"work_packages[{index}].dependencies"
                    ),
                    acceptance_commands=_json_array(
                        package["acceptance_commands"],
                        f"work_packages[{index}].acceptance_commands",
                    ),
                    handoff_path=package["handoff_path"],
                    next_action=package["next_action"],
                )
            )

        try:
            status = RunStatus(raw["status"])
            context_level = ContextLevel(raw["context_level"])
        except (TypeError, ValueError) as exc:
            raise ValueError("run state contains an unsupported enum value") from exc
        return cls(
            schema_version=raw["schema_version"],
            run_id=raw["run_id"],
            revision=raw["revision"],
            updated_at=raw["updated_at"],
            goal=raw["goal"],
            current_stage=raw["current_stage"],
            status=status,
            base_commit=raw["base_commit"],
            active_branch=raw["active_branch"],
            context_level=context_level,
            next_action=raw["next_action"],
            next_command=raw["next_command"],
            stages=tuple(stages),
            work_packages=tuple(packages),
            _revision_floor=raw["revision"],
        )
