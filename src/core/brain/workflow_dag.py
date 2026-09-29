"""
Workflow DAG Engine - J.A.R.V.I.S. 任务依赖编排引擎

在既有 Orchestrator（单任务派发）之上增加一层有向无环图（DAG）编排能力，
用于把多个角色任务按依赖关系组织、拓扑分层并并行执行。

核心能力：
1. DAG 定义与校验：拒绝环、自依赖、悬空依赖、重复节点
2. 拓扑分层（Kahn）：把一个图切成可并行执行的层
3. 分层并行执行：同层节点并发，跨层串行，尊重 max_parallelism
4. 失败策略：fail-fast（默认）与 continue-on-error 两种模式
5. 结果聚合：每个节点的状态、输出、耗时、错误统一收集
6. 纯 stdlib 实现，线程安全，与 Orchestrator 的 dispatch 契约兼容

设计原则：
- 零外部依赖（stdlib only）
- 不引入新的执行权限：所有实际执行仍委托给传入的 dispatch 回调
- 确定性：同一 DAG + 同一结果集合产生相同的执行层级

运行：python workflow_dag.py [validate <json_file> | layers <json_file>]
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

WORKFLOW_MAX_NODES = 512
WORKFLOW_MAX_EDGES = 4096
WORKFLOW_MAX_PARALLELISM = 16
WORKFLOW_DEFAULT_TIMEOUT_SECONDS = 300.0


class WorkflowValidationError(ValueError):
    """Raised when a workflow graph violates the DAG contract."""


class WorkflowExecutionError(RuntimeError):
    """Raised when a workflow fails under the fail-fast policy."""


class WorkflowNodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailurePolicy(str, Enum):
    """How the engine reacts to a failed node."""

    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"


@dataclass(frozen=True)
class WorkflowNode:
    """A single unit of work inside a workflow graph."""

    node_id: str
    agent_name: str
    prompt: str
    depends_on: tuple[str, ...] = ()
    timeout: int = int(WORKFLOW_DEFAULT_TIMEOUT_SECONDS)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "agent_name": self.agent_name,
            "prompt": self.prompt,
            "depends_on": list(self.depends_on),
            "timeout": self.timeout,
            "metadata": dict(self.metadata),
        }


@dataclass
class WorkflowNodeResult:
    """Outcome of executing one workflow node."""

    node_id: str
    status: WorkflowNodeStatus
    output: Any = None
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        return round(self.finished_at - self.started_at, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "duration": self.duration,
        }


@dataclass
class WorkflowRunResult:
    """Aggregated outcome of a full workflow run."""

    workflow_id: str
    success: bool
    layers: List[List[str]]
    results: Dict[str, WorkflowNodeResult]
    started_at: float
    finished_at: float

    @property
    def duration(self) -> float:
        return round(self.finished_at - self.started_at, 4)

    def failed_nodes(self) -> List[str]:
        return [
            node_id
            for node_id, result in self.results.items()
            if result.status is WorkflowNodeStatus.FAILED
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "success": self.success,
            "layers": [list(layer) for layer in self.layers],
            "duration": self.duration,
            "failed_nodes": self.failed_nodes(),
            "results": {
                node_id: result.to_dict()
                for node_id, result in self.results.items()
            },
        }


def _validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowValidationError(f"{field_name} must be a non-empty string")
    if len(value) > 128:
        raise WorkflowValidationError(f"{field_name} exceeds 128 characters")
    return value


class Workflow:
    """
    A validated directed acyclic graph of workflow nodes.

    Construction validates the graph eagerly so execution never has to
    re-derive structural invariants.
    """

    def __init__(self, workflow_id: str, nodes: Sequence[WorkflowNode]) -> None:
        self.workflow_id = _validate_identifier(workflow_id, "workflow_id")
        if len(nodes) > WORKFLOW_MAX_NODES:
            raise WorkflowValidationError(
                f"workflow exceeds {WORKFLOW_MAX_NODES} nodes"
            )
        self._nodes: Dict[str, WorkflowNode] = {}
        for node in nodes:
            if node.node_id in self._nodes:
                raise WorkflowValidationError(
                    f"duplicate node_id: {node.node_id}"
                )
            self._nodes[node.node_id] = node
        self._validate_edges()
        self._layers = self._compute_layers()

    @property
    def nodes(self) -> Dict[str, WorkflowNode]:
        return dict(self._nodes)

    @property
    def layers(self) -> List[List[str]]:
        return [list(layer) for layer in self._layers]

    def _validate_edges(self) -> None:
        edge_count = 0
        for node in self._nodes.values():
            for dependency in node.depends_on:
                edge_count += 1
                if dependency == node.node_id:
                    raise WorkflowValidationError(
                        f"node '{node.node_id}' depends on itself"
                    )
                if dependency not in self._nodes:
                    raise WorkflowValidationError(
                        f"node '{node.node_id}' depends on unknown node "
                        f"'{dependency}'"
                    )
        if edge_count > WORKFLOW_MAX_EDGES:
            raise WorkflowValidationError(
                f"workflow exceeds {WORKFLOW_MAX_EDGES} edges"
            )

    def _compute_layers(self) -> List[List[str]]:
        """Kahn topological layering; raises on a cycle."""
        indegree: Dict[str, int] = {
            node_id: len(node.depends_on)
            for node_id, node in self._nodes.items()
        }
        dependents: Dict[str, List[str]] = {node_id: [] for node_id in self._nodes}
        for node in self._nodes.values():
            for dependency in node.depends_on:
                dependents[dependency].append(node.node_id)

        remaining = dict(indegree)
        current_layer = sorted(
            node_id for node_id, degree in remaining.items() if degree == 0
        )
        layers: List[List[str]] = []
        visited = 0
        while current_layer:
            layers.append(current_layer)
            visited += len(current_layer)
            next_layer: List[str] = []
            for node_id in current_layer:
                for dependent in dependents[node_id]:
                    remaining[dependent] -= 1
                    if remaining[dependent] == 0:
                        next_layer.append(dependent)
            current_layer = sorted(next_layer)

        if visited != len(self._nodes):
            cyclic = sorted(
                node_id for node_id, degree in remaining.items() if degree > 0
            )
            raise WorkflowValidationError(
                "workflow contains a cycle among: " + ", ".join(cyclic)
            )
        return layers


class WorkflowEngine:
    """
    Executes a validated Workflow by mapping nodes onto a dispatch callback.

    The engine owns only scheduling: no command, environment, or capability
    selection is performed here. The injected ``dispatch`` callback receives a
    :class:`WorkflowNode` and returns any JSON-serializable output.
    """

    def __init__(
        self,
        dispatch: Callable[[WorkflowNode], Any],
        *,
        max_parallelism: int = 4,
        failure_policy: FailurePolicy = FailurePolicy.FAIL_FAST,
    ) -> None:
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        if (
            isinstance(max_parallelism, bool)
            or not isinstance(max_parallelism, int)
            or not 1 <= max_parallelism <= WORKFLOW_MAX_PARALLELISM
        ):
            raise ValueError(
                f"max_parallelism must be between 1 and "
                f"{WORKFLOW_MAX_PARALLELISM}"
            )
        self._dispatch = dispatch
        self._max_parallelism = max_parallelism
        self._failure_policy = failure_policy
        self._lock = threading.Lock()

    @property
    def max_parallelism(self) -> int:
        return self._max_parallelism

    def run(self, workflow: Workflow) -> WorkflowRunResult:
        started_at = time.time()
        results: Dict[str, WorkflowNodeResult] = {
            node_id: WorkflowNodeResult(
                node_id=node_id,
                status=WorkflowNodeStatus.PENDING,
            )
            for node_id in workflow.nodes
        }

        for layer in workflow.layers:
            runnable = [
                node_id
                for node_id in layer
                if self._dependencies_satisfied(
                    workflow, node_id, results
                )
            ]
            skipped = [
                node_id for node_id in layer if node_id not in runnable
            ]
            for node_id in skipped:
                results[node_id] = WorkflowNodeResult(
                    node_id=node_id,
                    status=WorkflowNodeStatus.SKIPPED,
                    error="dependency did not succeed",
                )

            if runnable:
                self._run_layer(workflow, runnable, results)

            if (
                self._failure_policy is FailurePolicy.FAIL_FAST
                and any(
                    result.status is WorkflowNodeStatus.FAILED
                    for result in results.values()
                )
            ):
                for node_id in workflow.nodes:
                    if results[node_id].status is WorkflowNodeStatus.PENDING:
                        results[node_id] = WorkflowNodeResult(
                            node_id=node_id,
                            status=WorkflowNodeStatus.SKIPPED,
                            error="aborted by fail-fast policy",
                        )
                break

        finished_at = time.time()
        success = all(
            result.status is WorkflowNodeStatus.SUCCEEDED
            for result in results.values()
        )
        run_result = WorkflowRunResult(
            workflow_id=workflow.workflow_id,
            success=success,
            layers=workflow.layers,
            results=results,
            started_at=started_at,
            finished_at=finished_at,
        )
        if not success and self._failure_policy is FailurePolicy.FAIL_FAST:
            raise WorkflowExecutionError(
                "workflow failed at nodes: "
                + ", ".join(run_result.failed_nodes() or ["<none>"]),
            )
        return run_result

    def _dependencies_satisfied(
        self,
        workflow: Workflow,
        node_id: str,
        results: Dict[str, WorkflowNodeResult],
    ) -> bool:
        node = workflow.nodes[node_id]
        return all(
            results[dependency].status is WorkflowNodeStatus.SUCCEEDED
            for dependency in node.depends_on
        )

    def _run_layer(
        self,
        workflow: Workflow,
        layer: List[str],
        results: Dict[str, WorkflowNodeResult],
    ) -> None:
        worker_count = min(self._max_parallelism, len(layer))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._execute_node, workflow, node_id): node_id
                for node_id in layer
            }
            for future in as_completed(futures):
                node_id = futures[future]
                try:
                    result = future.result()
                except Exception as error:  # pragma: no cover - defensive
                    logger.exception("workflow node %s raised", node_id)
                    result = WorkflowNodeResult(
                        node_id=node_id,
                        status=WorkflowNodeStatus.FAILED,
                        error=f"{type(error).__name__}: {error}",
                    )
                with self._lock:
                    results[node_id] = result

    def _execute_node(
        self,
        workflow: Workflow,
        node_id: str,
    ) -> WorkflowNodeResult:
        node = workflow.nodes[node_id]
        started_at = time.time()
        try:
            output = self._dispatch(node)
        except Exception as error:
            logger.warning("workflow node %s failed: %s", node_id, error)
            return WorkflowNodeResult(
                node_id=node_id,
                status=WorkflowNodeStatus.FAILED,
                error=f"{type(error).__name__}: {error}",
                started_at=started_at,
                finished_at=time.time(),
            )
        return WorkflowNodeResult(
            node_id=node_id,
            status=WorkflowNodeStatus.SUCCEEDED,
            output=output,
            started_at=started_at,
            finished_at=time.time(),
        )


def workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    """Build a validated Workflow from a plain JSON-compatible dict."""
    if not isinstance(data, dict):
        raise WorkflowValidationError("workflow definition must be an object")
    workflow_id = data.get("workflow_id")
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise WorkflowValidationError("workflow must declare a non-empty nodes list")

    nodes: List[WorkflowNode] = []
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise WorkflowValidationError(f"node #{index} must be an object")
        depends = raw.get("depends_on", [])
        if not isinstance(depends, list) or not all(
            isinstance(item, str) for item in depends
        ):
            raise WorkflowValidationError(
                f"node #{index} depends_on must be a list of strings"
            )
        timeout = raw.get("timeout", int(WORKFLOW_DEFAULT_TIMEOUT_SECONDS))
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            raise WorkflowValidationError(
                f"node #{index} timeout must be an integer"
            )
        nodes.append(
            WorkflowNode(
                node_id=_validate_identifier(
                    raw.get("node_id"), f"node #{index} node_id"
                ),
                agent_name=_validate_identifier(
                    raw.get("agent_name"), f"node #{index} agent_name"
                ),
                prompt=str(raw.get("prompt", "")),
                depends_on=tuple(depends),
                timeout=timeout,
                metadata=dict(raw.get("metadata", {})),
            )
        )
    return Workflow(_validate_identifier(workflow_id, "workflow_id"), nodes)


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python workflow_dag.py <validate|layers> <json_file>")
        sys.exit(0)
    command, json_path = sys.argv[1], sys.argv[2]
    with open(json_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    workflow = workflow_from_dict(data)
    if command == "validate":
        print(f"valid DAG: {workflow.workflow_id} ({len(workflow.nodes)} nodes)")
        print(json.dumps(workflow.layers, ensure_ascii=False, indent=2))
    elif command == "layers":
        for index, layer in enumerate(workflow.layers):
            print(f"layer {index}: {', '.join(layer)}")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
