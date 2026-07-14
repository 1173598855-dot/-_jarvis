"""Default-deny authorization and invocation boundary for role tools."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from .role_registry import AgentProfile

ToolHandler = Callable[[dict[str, Any]], Any]


class RoleToolDeniedError(PermissionError):
    """Raised when a role tool call cannot pass the broker policy."""


@dataclass(frozen=True)
class RoleToolDecision:
    """Immutable authorization evidence for one role-tool check."""

    role_name: str
    tool_name: str
    allowed: bool
    reason: str


class RoleToolPolicy:
    """Immutable explicit grants keyed by resolved role name."""

    def __init__(
        self,
        grants: Optional[Mapping[str, Iterable[str]]] = None,
    ) -> None:
        normalized: dict[str, frozenset[str]] = {}
        for role_name, tools in (grants or {}).items():
            if not isinstance(role_name, str) or not role_name:
                raise ValueError(
                    "Role tool policy names must be non-empty strings"
                )
            try:
                tool_set = frozenset(tools)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Role tool grants must be an iterable of strings"
                ) from error
            if any(
                not isinstance(tool, str) or not tool
                for tool in tool_set
            ):
                raise ValueError("Role tool grants must be non-empty strings")
            normalized[role_name] = tool_set
        self._grants = normalized

    def is_granted(self, role_name: str, tool_name: str) -> bool:
        """Return whether a role has an exact explicit grant for a tool."""
        return tool_name in self._grants.get(role_name, frozenset())


class RoleToolBroker:
    """Authorize every role tool call before invoking a registered handler."""

    def __init__(
        self,
        policy: Optional[RoleToolPolicy] = None,
        handlers: Optional[Mapping[str, ToolHandler]] = None,
        audit_limit: int = 256,
    ) -> None:
        if type(audit_limit) is not int or audit_limit < 1:
            raise ValueError(
                "Role tool audit limit must be a positive integer"
            )
        registered = dict(handlers or {})
        if any(
            not isinstance(name, str)
            or not name
            or not callable(handler)
            for name, handler in registered.items()
        ):
            raise ValueError(
                "Role tool handlers require non-empty names and callables"
            )
        self._policy = policy or RoleToolPolicy()
        self._handlers = registered
        self._audit: deque[RoleToolDecision] = deque(maxlen=audit_limit)
        self._lock = threading.Lock()

    def authorized_tools(self, profile: AgentProfile) -> list[str]:
        """Return declared tools that also have a grant and handler."""
        authorized = []
        for tool_name in dict.fromkeys(profile.tools):
            decision = self._decide(profile, tool_name)
            if decision.allowed:
                authorized.append(tool_name)
        return authorized

    def invoke(
        self,
        profile: AgentProfile,
        tool_name: str,
        arguments: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Invoke one handler only after an allow decision."""
        if not isinstance(tool_name, str) or not tool_name:
            raise RoleToolDeniedError(
                "Role tool call denied: invalid tool name"
            )
        if arguments is not None and not isinstance(arguments, Mapping):
            raise RoleToolDeniedError(
                "Role tool call denied: invalid arguments"
            )
        decision = self._decide(profile, tool_name)
        if not decision.allowed:
            raise RoleToolDeniedError(
                f"Role tool call denied: {decision.reason}"
            )
        return self._handlers[tool_name](dict(arguments or {}))

    def audit_log(self) -> list[RoleToolDecision]:
        """Return a copy of the bounded authorization history."""
        with self._lock:
            return list(self._audit)

    def _decide(
        self,
        profile: AgentProfile,
        tool_name: str,
    ) -> RoleToolDecision:
        if tool_name not in profile.tools:
            reason = "tool_not_declared"
        elif not self._policy.is_granted(profile.name, tool_name):
            reason = "tool_not_granted"
        elif tool_name not in self._handlers:
            reason = "tool_not_registered"
        else:
            reason = "allowed"
        decision = RoleToolDecision(
            role_name=profile.name,
            tool_name=tool_name,
            allowed=reason == "allowed",
            reason=reason,
        )
        with self._lock:
            self._audit.append(decision)
        return decision
