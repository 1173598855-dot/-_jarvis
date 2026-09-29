"""Tests for the workflow DAG engine."""

import unittest

from core.brain.workflow_dag import (
    FailurePolicy,
    Workflow,
    WorkflowEngine,
    WorkflowExecutionError,
    WorkflowNode,
    WorkflowNodeStatus,
    WorkflowValidationError,
    workflow_from_dict,
)


def _node(node_id, depends_on=(), agent="engineer", prompt="p"):
    return WorkflowNode(
        node_id=node_id,
        agent_name=agent,
        prompt=prompt,
        depends_on=tuple(depends_on),
    )


class TestWorkflowValidation(unittest.TestCase):
    def test_valid_graph_layers(self):
        workflow = Workflow(
            "wf",
            [
                _node("a"),
                _node("b", ["a"]),
                _node("c", ["a"]),
                _node("d", ["b", "c"]),
            ],
        )
        self.assertEqual(workflow.layers, [["a"], ["b", "c"], ["d"]])

    def test_duplicate_node_rejected(self):
        with self.assertRaises(WorkflowValidationError):
            Workflow("wf", [_node("a"), _node("a")])

    def test_self_dependency_rejected(self):
        with self.assertRaises(WorkflowValidationError):
            Workflow("wf", [_node("a", ["a"])])

    def test_unknown_dependency_rejected(self):
        with self.assertRaises(WorkflowValidationError):
            Workflow("wf", [_node("a", ["missing"])])

    def test_cycle_rejected(self):
        with self.assertRaises(WorkflowValidationError) as ctx:
            Workflow(
                "wf",
                [_node("a", ["b"]), _node("b", ["a"])],
            )
        self.assertIn("cycle", str(ctx.exception))

    def test_empty_workflow_id_rejected(self):
        with self.assertRaises(WorkflowValidationError):
            Workflow("", [_node("a")])

    def test_node_cap_enforced(self):
        nodes = [_node(f"n{i}") for i in range(513)]
        with self.assertRaises(WorkflowValidationError):
            Workflow("wf", nodes)

    def test_layers_are_deterministic(self):
        nodes = [_node("b"), _node("a")]
        first = Workflow("wf", nodes).layers
        second = Workflow("wf", nodes).layers
        self.assertEqual(first, second)
        self.assertEqual(first, [["a", "b"]])


class TestWorkflowEngine(unittest.TestCase):
    def test_successful_run_records_output(self):
        seen = []

        def dispatch(node):
            seen.append(node.node_id)
            return {"node": node.node_id}

        workflow = Workflow("wf", [_node("a"), _node("b", ["a"])])
        engine = WorkflowEngine(dispatch)
        result = engine.run(workflow)
        self.assertTrue(result.success)
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(result.results["b"].output, {"node": "b"})
        self.assertGreaterEqual(result.duration, 0.0)

    def test_parallel_layer_executes_concurrently(self):
        import threading

        barrier = threading.Barrier(3, timeout=5)

        def dispatch(node):
            barrier.wait()
            return node.node_id

        workflow = Workflow("wf", [_node("a"), _node("b"), _node("c")])
        engine = WorkflowEngine(dispatch, max_parallelism=3)
        result = engine.run(workflow)
        self.assertTrue(result.success)

    def test_fail_fast_skips_remaining(self):
        def dispatch(node):
            if node.node_id == "a":
                raise RuntimeError("boom")
            return node.node_id

        workflow = Workflow("wf", [_node("a"), _node("b", ["a"])])
        engine = WorkflowEngine(dispatch, failure_policy=FailurePolicy.FAIL_FAST)
        with self.assertRaises(WorkflowExecutionError):
            engine.run(workflow)

    def test_continue_policy_reports_failure_without_raising(self):
        def dispatch(node):
            if node.node_id == "a":
                raise RuntimeError("boom")
            return node.node_id

        workflow = Workflow("wf", [_node("a"), _node("b")])
        engine = WorkflowEngine(dispatch, failure_policy=FailurePolicy.CONTINUE)
        result = engine.run(workflow)
        self.assertFalse(result.success)
        self.assertEqual(result.failed_nodes(), ["a"])
        self.assertEqual(
            result.results["a"].status, WorkflowNodeStatus.FAILED
        )
        self.assertEqual(
            result.results["b"].status, WorkflowNodeStatus.SUCCEEDED
        )

    def test_dependent_of_failed_node_is_skipped(self):
        def dispatch(node):
            raise RuntimeError("boom")

        workflow = Workflow("wf", [_node("a"), _node("b", ["a"])])
        engine = WorkflowEngine(dispatch, failure_policy=FailurePolicy.CONTINUE)
        result = engine.run(workflow)
        self.assertEqual(
            result.results["b"].status, WorkflowNodeStatus.SKIPPED
        )

    def test_invalid_parallelism_rejected(self):
        with self.assertRaises(ValueError):
            WorkflowEngine(lambda node: None, max_parallelism=0)
        with self.assertRaises(ValueError):
            WorkflowEngine(lambda node: None, max_parallelism=17)
        with self.assertRaises(ValueError):
            WorkflowEngine(lambda node: None, max_parallelism=True)

    def test_non_callable_dispatch_rejected(self):
        with self.assertRaises(TypeError):
            WorkflowEngine("not-callable")


class TestWorkflowFromDict(unittest.TestCase):
    def test_round_trip(self):
        data = {
            "workflow_id": "wf",
            "nodes": [
                {"node_id": "a", "agent_name": "engineer", "prompt": "x"},
                {
                    "node_id": "b",
                    "agent_name": "reviewer",
                    "prompt": "y",
                    "depends_on": ["a"],
                },
            ],
        }
        workflow = workflow_from_dict(data)
        self.assertEqual(workflow.layers, [["a"], ["b"]])

    def test_missing_nodes_rejected(self):
        with self.assertRaises(WorkflowValidationError):
            workflow_from_dict({"workflow_id": "wf", "nodes": []})

    def test_bad_depends_on_rejected(self):
        with self.assertRaises(WorkflowValidationError):
            workflow_from_dict(
                {
                    "workflow_id": "wf",
                    "nodes": [
                        {
                            "node_id": "a",
                            "agent_name": "e",
                            "prompt": "x",
                            "depends_on": "b",
                        }
                    ],
                }
            )

    def test_bad_timeout_rejected(self):
        with self.assertRaises(WorkflowValidationError):
            workflow_from_dict(
                {
                    "workflow_id": "wf",
                    "nodes": [
                        {
                            "node_id": "a",
                            "agent_name": "e",
                            "prompt": "x",
                            "timeout": "fast",
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
