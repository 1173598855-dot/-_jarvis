"""Tests for the bounded model-to-tool-to-model role loop."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.agent_factory import AgentFactory
from core.brain.role_tool_loop import RoleToolLoop, RoleToolLoopError
from core.brain.role_tools import RoleToolBroker, RoleToolPolicy
from core.contracts.role_tool_protocol import RoleToolBudget, RoleToolDefinition


def _definition(name="orchestrator"):
    return RoleToolDefinition(
        name=name,
        description=f"Read {name} state",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 64},
            },
            "additionalProperties": False,
        },
    )


def _tool_response(name="orchestrator", arguments=None, call_id="call-1"):
    payload = {
        "function": {
            "name": name,
            "arguments": {} if arguments is None else arguments,
        }
    }
    if call_id is not None:
        payload["id"] = call_id
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [payload],
        },
        "done": True,
    }


def _final_response(content="Final output"):
    return {
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


class TestRoleToolLoop(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.definition = _definition()
        self.handler = Mock(return_value={"status": "ready"})
        self.broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": [self.definition.name]}),
            handlers={self.definition.name: self.handler},
            definitions={self.definition.name: self.definition},
        )

    def _factory(self, broker=None):
        return AgentFactory(
            ollama_manager=self.manager,
            role_model="fixture-role",
            role_tool_broker=broker if broker is not None else self.broker,
        )

    def test_executes_schema_authorized_tool_and_uses_message_snapshots(self):
        self.manager.chat.side_effect = [
            _tool_response(arguments={"query": "health"}),
            _final_response(),
        ]
        factory = self._factory()

        result = factory.execute_role_once(
            "engineer",
            "inspect state",
            task_id="task-1",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "Final output")
        self.handler.assert_called_once_with({"query": "health"})
        self.assertEqual(self.manager.chat.call_count, 2)
        first = self.manager.chat.call_args_list[0]
        second = self.manager.chat.call_args_list[1]
        self.assertEqual(len(first.args[1]), 2)
        self.assertEqual(first.kwargs["tools"], [self.definition.to_ollama()])
        self.assertEqual(len(second.args[1]), 4)
        self.assertEqual(second.args[1][-1]["role"], "tool")
        self.assertEqual(second.args[1][-1]["tool_name"], "orchestrator")
        self.assertEqual(second.args[1][-1]["tool_call_id"], "call-1")
        self.assertEqual(
            json.loads(second.args[1][-1]["content"]),
            {"status": "ready"},
        )

    def test_empty_broker_does_not_advertise_tools(self):
        self.manager.chat.return_value = _final_response("Plain")
        factory = self._factory(RoleToolBroker())

        result = factory.execute_role_once("engineer", "hello", task_id="task-2")

        self.assertEqual(result.status, "success")
        self.assertEqual(self.manager.chat.call_args.kwargs, {"stream": False})

    def test_unadvertised_tool_request_still_passes_through_empty_broker(self):
        broker = RoleToolBroker()
        self.manager.chat.side_effect = [
            _tool_response(name="orchestrator"),
            _final_response("Recovered without advertised tools"),
        ]

        result = self._factory(broker).execute_role_once(
            "engineer",
            "inspect",
            task_id="task-2b",
        )

        self.assertEqual(result.status, "success")
        invocation = broker.invocation_log()[-1]
        self.assertFalse(invocation.allowed)
        self.assertEqual(invocation.reason, "tool_not_granted")
        tool_message = self.manager.chat.call_args_list[1].args[1][-1]
        self.assertEqual(
            json.loads(tool_message["content"]),
            {"error": "tool_not_granted"},
        )

    def test_unadvertised_tool_is_denied_and_model_can_finish(self):
        self.manager.chat.side_effect = [
            _tool_response(name="terminal_executor"),
            _final_response("Recovered without tool"),
        ]
        factory = self._factory()

        result = factory.execute_role_once("engineer", "inspect", task_id="task-3")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "Recovered without tool")
        self.handler.assert_not_called()
        invocation = self.broker.invocation_log()[-1]
        self.assertFalse(invocation.allowed)
        self.assertEqual(invocation.reason, "tool_not_granted")
        tool_message = self.manager.chat.call_args_list[1].args[1][-1]
        self.assertEqual(
            json.loads(tool_message["content"]),
            {"error": "tool_not_granted"},
        )

    def test_handler_error_is_stable_and_model_can_finish(self):
        handler = Mock(side_effect=RuntimeError("secret socket path"))
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": [self.definition.name]}),
            handlers={self.definition.name: handler},
            definitions={self.definition.name: self.definition},
        )
        self.manager.chat.side_effect = [
            _tool_response(),
            _final_response("Handled failure"),
        ]
        factory = self._factory(broker)

        result = factory.execute_role_once("engineer", "inspect", task_id="task-4")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "Handled failure")
        tool_message = self.manager.chat.call_args_list[1].args[1][-1]
        self.assertEqual(
            json.loads(tool_message["content"]),
            {"error": "handler_error"},
        )
        self.assertNotIn("secret socket path", tool_message["content"])

    def test_argument_and_result_limits_return_bounded_denials(self):
        cases = (
            (
                RoleToolBudget(max_argument_bytes=8),
                Mock(return_value={"ok": True}),
                {"query": "too long"},
                "argument_too_large",
            ),
            (
                RoleToolBudget(max_result_bytes=8),
                Mock(return_value={"value": "too long"}),
                {},
                "result_too_large",
            ),
        )
        for budget, handler, arguments, reason in cases:
            with self.subTest(reason=reason):
                broker = RoleToolBroker(
                    policy=RoleToolPolicy({"engineer": [self.definition.name]}),
                    handlers={self.definition.name: handler},
                    definitions={self.definition.name: self.definition},
                    budget=budget,
                )
                self.manager.reset_mock()
                self.manager.chat.side_effect = [
                    _tool_response(arguments=arguments),
                    _final_response("Recovered"),
                ]
                result = self._factory(broker).execute_role_once(
                    "engineer",
                    "inspect",
                    task_id=f"task-{reason}",
                )

                self.assertEqual(result.status, "success")
                invocation = broker.invocation_log()[-1]
                self.assertEqual(invocation.reason, reason)
                message = self.manager.chat.call_args_list[1].args[1][-1]
                self.assertLessEqual(
                    len(message["content"].encode("utf-8")),
                    64,
                )

    def test_rejects_tool_batch_before_partial_execution_when_call_budget_exceeded(self):
        budget = RoleToolBudget(max_calls=1)
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": [self.definition.name]}),
            handlers={self.definition.name: self.handler},
            definitions={self.definition.name: self.definition},
            budget=budget,
        )
        first = _tool_response()["message"]["tool_calls"][0]
        second = _tool_response(call_id="call-2")["message"]["tool_calls"][0]
        self.manager.chat.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [first, second],
            },
            "done": True,
        }

        result = self._factory(broker).execute_role_once(
            "engineer",
            "inspect",
            task_id="task-5",
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "Ollama role execution failed")
        self.handler.assert_not_called()

    def test_call_budget_is_total_across_model_rounds(self):
        budget = RoleToolBudget(max_calls=2)
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": [self.definition.name]}),
            handlers={self.definition.name: self.handler},
            definitions={self.definition.name: self.definition},
            budget=budget,
        )
        self.manager.chat.side_effect = [
            _tool_response(call_id="call-1"),
            _tool_response(call_id="call-2"),
            _tool_response(call_id="call-3"),
        ]

        result = self._factory(broker).execute_role_once(
            "engineer",
            "loop",
            task_id="task-6",
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(self.handler.call_count, 2)
        self.assertEqual(self.manager.chat.call_count, 3)

    def test_cumulative_result_budget_fails_closed(self):
        budget = RoleToolBudget(
            max_calls=2,
            max_result_bytes=64,
            max_total_result_bytes=20,
        )
        handler = Mock(return_value={"value": "1234"})
        broker = RoleToolBroker(
            policy=RoleToolPolicy({"engineer": [self.definition.name]}),
            handlers={self.definition.name: handler},
            definitions={self.definition.name: self.definition},
            budget=budget,
        )
        first = _tool_response(call_id="call-1")["message"]["tool_calls"][0]
        second = _tool_response(call_id="call-2")["message"]["tool_calls"][0]
        self.manager.chat.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [first, second],
            },
            "done": True,
        }

        result = self._factory(broker).execute_role_once(
            "engineer",
            "inspect",
            task_id="task-7",
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(handler.call_count, 2)
        self.assertEqual(len(broker.invocation_log()), 2)

    def test_malformed_tool_call_fails_without_reaching_broker(self):
        self.manager.chat.return_value = _tool_response(name="")

        result = self._factory().execute_role_once(
            "engineer",
            "inspect",
            task_id="task-8",
        )

        self.assertEqual(result.status, "error")
        self.handler.assert_not_called()
        self.assertEqual(self.broker.invocation_log(), [])

    def test_elapsed_budget_is_checked_after_model_response(self):
        ticks = iter((0.0, 0.0, 2.0))
        clock = lambda: next(ticks)
        self.manager.chat.return_value = _tool_response()
        loop = RoleToolLoop(
            self.manager,
            self.broker,
            budget=RoleToolBudget(max_elapsed_seconds=1.0),
            clock=clock,
        )
        profile = AgentFactory().registry.get("engineer")

        with self.assertRaises(RoleToolLoopError):
            loop.run(
                model="fixture-role",
                messages=[{"role": "user", "content": "inspect"}],
                profile=profile,
                timeout_seconds=10,
            )

        self.handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
