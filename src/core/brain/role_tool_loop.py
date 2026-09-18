"""Bounded Ollama model-to-tool-to-model execution for role agents."""

from __future__ import annotations

import copy
import math
import time
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from core.contracts.role_tool_protocol import (
    RoleToolBudget,
    RoleToolCall,
    RoleToolProtocolError,
    RoleToolResult,
)

from .role_registry import AgentProfile
from .role_tools import RoleToolBroker, RoleToolDeniedError


class RoleToolLoopError(RuntimeError):
    """Raised when a role tool loop cannot complete within its contract."""


class RoleToolLoop:
    """Run one bounded role conversation through schema-authorized tools."""

    def __init__(
        self,
        manager: object,
        broker: RoleToolBroker,
        *,
        budget: RoleToolBudget | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if manager is None:
            raise ValueError("Role tool loop requires an Ollama manager")
        if not isinstance(broker, RoleToolBroker):
            raise ValueError("Role tool loop requires a RoleToolBroker")
        if budget is not None and not isinstance(budget, RoleToolBudget):
            raise ValueError("Role tool loop budget must be a RoleToolBudget")
        self._manager = manager
        self._broker = broker
        self._budget = budget or broker.budget
        self._clock = clock or time.monotonic

    def run(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        profile: AgentProfile,
        timeout_seconds: float,
    ) -> str:
        if not isinstance(model, str) or not model.strip():
            raise RoleToolLoopError("role model is invalid")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise RoleToolLoopError("role tool timeout is invalid")
        if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
            raise RoleToolLoopError("role messages are invalid")
        history = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise RoleToolLoopError("role message is invalid")
            history.append(copy.deepcopy(dict(message)))

        definitions = self._broker.authorized_definitions(profile)
        tools = [definition.to_ollama() for definition in definitions]
        started_at = self._clock()
        elapsed_limit = min(
            float(timeout_seconds),
            float(self._budget.max_elapsed_seconds),
        )
        calls_used = 0
        result_bytes_used = 0
        round_index = 0

        while True:
            self._check_deadline(started_at, elapsed_limit)
            kwargs: dict[str, Any] = {"stream": False}
            if tools:
                kwargs["tools"] = copy.deepcopy(tools)
            response = self._manager.chat(
                model,
                copy.deepcopy(history),
                **kwargs,
            )
            self._check_deadline(started_at, elapsed_limit)
            assistant, raw_calls = self._parse_assistant(response)
            history.append(assistant)

            if not raw_calls:
                content = assistant["content"]
                if isinstance(content, str) and content.strip():
                    return content.strip()
                raise RoleToolLoopError("role response content is empty")
            if calls_used + len(raw_calls) > self._budget.max_calls:
                raise RoleToolLoopError("role tool call budget exceeded")

            calls = []
            for call_index, raw_call in enumerate(raw_calls):
                try:
                    calls.append(
                        RoleToolCall.from_ollama(
                            raw_call,
                            round_index,
                            call_index,
                        )
                    )
                except RoleToolProtocolError as error:
                    raise RoleToolLoopError("role tool call is invalid") from error

            for call in calls:
                calls_used += 1
                self._check_deadline(started_at, elapsed_limit)
                result = self._invoke(profile, call)
                if result.byte_size > self._budget.max_result_bytes:
                    raise RoleToolLoopError("role tool result budget exceeded")
                result_bytes_used += result.byte_size
                if result_bytes_used > self._budget.max_total_result_bytes:
                    raise RoleToolLoopError("role tool output budget exceeded")
                self._check_deadline(started_at, elapsed_limit)
                history.append(self._tool_message(call, result))
            round_index += 1

    def _invoke(
        self,
        profile: AgentProfile,
        call: RoleToolCall,
    ) -> RoleToolResult:
        try:
            fallback = self._broker.invoke(profile, call)
        except (RoleToolDeniedError, Exception):
            fallback = None
        invocation = self._find_invocation(profile, call)
        if invocation is not None:
            return invocation.result
        try:
            return RoleToolResult.from_value(fallback)
        except RoleToolProtocolError:
            return RoleToolResult.failure("tool_error")

    def _find_invocation(
        self,
        profile: AgentProfile,
        call: RoleToolCall,
    ):
        expected = call.to_dict()
        for invocation in reversed(self._broker.invocation_log()):
            if (
                invocation.role_name == profile.name
                and invocation.call.to_dict() == expected
            ):
                return invocation
        return None

    @staticmethod
    def _parse_assistant(
        response: object,
    ) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
        if not isinstance(response, Mapping) or response.get("error"):
            raise RoleToolLoopError("role model response is invalid")
        message = response.get("message")
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            raise RoleToolLoopError("role assistant message is invalid")
        content = message.get("content")
        raw_calls = message.get("tool_calls")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise RoleToolLoopError("role assistant content is invalid")
        if raw_calls is None:
            calls: list[Mapping[str, Any]] = []
        elif not isinstance(raw_calls, list) or any(
            not isinstance(item, Mapping) for item in raw_calls
        ):
            raise RoleToolLoopError("role assistant tool calls are invalid")
        else:
            calls = list(raw_calls)
        assistant: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if calls:
            assistant["tool_calls"] = copy.deepcopy(calls)
        return assistant, calls

    @staticmethod
    def _tool_message(
        call: RoleToolCall,
        result: RoleToolResult,
    ) -> dict[str, Any]:
        message = {
            "role": "tool",
            "content": result.content,
            "tool_name": call.name,
        }
        if call.call_id is not None:
            message["tool_call_id"] = call.call_id
        return message

    def _check_deadline(self, started_at: float, elapsed_limit: float) -> None:
        if self._clock() - started_at >= elapsed_limit:
            raise RoleToolLoopError("role tool elapsed budget exceeded")
