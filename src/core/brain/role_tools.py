"""Default-deny authorization and invocation boundary for role tools."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from core.contracts.role_tool_protocol import (
    RoleToolBudget,
    RoleToolCall,
    RoleToolDefinition,
    RoleToolInvocation,
    RoleToolProtocolError,
    RoleToolResult,
    stable_json_bytes,
)

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
        definitions: Optional[Mapping[str, RoleToolDefinition]] = None,
        budget: Optional[RoleToolBudget] = None,
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
        declared = dict(definitions or {})
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(definition, RoleToolDefinition)
            or definition.name != name
            for name, definition in declared.items()
        ):
            raise ValueError(
                "Role tool definitions require matching names and definitions"
            )
        if budget is not None and not isinstance(budget, RoleToolBudget):
            raise ValueError("Role tool budget must be a RoleToolBudget")
        self._policy = policy or RoleToolPolicy()
        self._handlers = registered
        self._definitions = declared
        self._budget = budget or RoleToolBudget()
        self._audit: deque[RoleToolDecision] = deque(maxlen=audit_limit)
        self._invocations: deque[RoleToolInvocation] = deque(maxlen=audit_limit)
        self._lock = threading.Lock()

    @property
    def budget(self) -> RoleToolBudget:
        """Return the immutable budget shared with the model tool loop."""
        return self._budget

    def authorized_tools(self, profile: AgentProfile) -> list[str]:
        """Return declared tools that also have a grant and handler."""
        authorized = []
        for tool_name in dict.fromkeys(profile.tools):
            decision = self._decide(profile, tool_name)
            if decision.allowed:
                authorized.append(tool_name)
        return authorized

    def authorized_definitions(
        self,
        profile: AgentProfile,
    ) -> list[RoleToolDefinition]:
        """Return definitions available for safe model invocation."""
        definitions = []
        for tool_name in self.authorized_tools(profile):
            definition = self._definitions.get(tool_name)
            if definition is not None:
                definitions.append(definition)
        return definitions

    def invoke(
        self,
        profile: AgentProfile,
        tool_name: str | RoleToolCall,
        arguments: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Invoke one handler only after an allow decision."""
        call = tool_name if isinstance(tool_name, RoleToolCall) else None
        resolved_name = call.name if call is not None else tool_name
        if not isinstance(resolved_name, str) or not resolved_name:
            raise RoleToolDeniedError(
                "Role tool call denied: invalid tool name"
            )
        if arguments is not None and not isinstance(arguments, Mapping):
            raise RoleToolDeniedError(
                "Role tool call denied: invalid arguments"
            )
        if call is not None and arguments is not None:
            raise RoleToolDeniedError(
                "Role tool call denied: arguments must be part of the protocol call"
            )
        decision = self._decide(profile, resolved_name)
        if not decision.allowed:
            if call is not None:
                self._record_invocation(
                    profile,
                    call,
                    RoleToolResult.failure(decision.reason),
                    False,
                    decision.reason,
                )
            raise RoleToolDeniedError(
                f"Role tool call denied: {decision.reason}"
            )
        if call is None:
            return self._handlers[resolved_name](dict(arguments or {}))

        definition = self._definitions.get(resolved_name)
        if definition is None:
            return self._deny_call(profile, call, "tool_definition_not_registered")
        try:
            argument_size = len(stable_json_bytes(call.arguments))
            if argument_size > self._budget.max_argument_bytes:
                return self._deny_call(profile, call, "argument_too_large")
            definition.validate_arguments(call.arguments)
        except RoleToolProtocolError:
            return self._deny_call(profile, call, "invalid_arguments")

        started = time.monotonic()
        try:
            result = self._handlers[resolved_name](dict(call.arguments))
            normalized = RoleToolResult.from_value(result)
            if normalized.byte_size > self._budget.max_result_bytes:
                return self._deny_call(profile, call, "result_too_large")
        except RoleToolDeniedError:
            raise
        except RoleToolProtocolError:
            return self._deny_call(profile, call, "invalid_result")
        except Exception:
            self._record_invocation(
                profile,
                call,
                RoleToolResult.failure("handler_error"),
                False,
                "handler_error",
                time.monotonic() - started,
            )
            raise
        self._record_invocation(
            profile,
            call,
            normalized,
            True,
            "allowed",
            time.monotonic() - started,
        )
        return result

    def audit_log(self) -> list[RoleToolDecision]:
        """Return a copy of the bounded authorization history."""
        with self._lock:
            return list(self._audit)

    def invocation_log(self) -> list[RoleToolInvocation]:
        """Return bounded, JSON-replayable protocol invocation evidence."""
        with self._lock:
            return list(self._invocations)

    def _deny_call(
        self,
        profile: AgentProfile,
        call: RoleToolCall,
        reason: str,
    ) -> Any:
        self._record_invocation(
            profile,
            call,
            RoleToolResult.failure(reason),
            False,
            reason,
        )
        raise RoleToolDeniedError(f"Role tool call denied: {reason}")

    def _record_invocation(
        self,
        profile: AgentProfile,
        call: RoleToolCall,
        result: RoleToolResult,
        allowed: bool,
        reason: str,
        elapsed_seconds: float = 0.0,
    ) -> None:
        invocation = RoleToolInvocation(
            role_name=profile.name,
            call=call,
            result=result,
            allowed=allowed,
            reason=reason,
            elapsed_seconds=elapsed_seconds,
        )
        with self._lock:
            self._invocations.append(invocation)

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
