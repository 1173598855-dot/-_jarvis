"""
MultiAgentProtocol — 小奕 J.A.R.V.I.S. 多 Agent 对话协议 (Python 实现)
萃取自 AutoGen 的多 Agent 对话架构

功能：
1. Agent 注册与发现
2. 对话式任务协作
3. 消息路由与转发
4. 任务分解与委派
5. 冲突协商机制
6. 人类介入 (Human-in-the-Loop)
"""

from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import uuid
import re

from core.kernel.event_bus import global_event_bus, Event


@dataclass
class Agent:
    """Agent 定义"""
    id: str
    name: str
    role: str
    capabilities: List[str]
    system_prompt: str
    tools: List[str] = field(default_factory=list)
    status: str = "idle"


@dataclass
class ConversationTurn:
    """对话轮次"""
    id: str
    agent_id: str
    message: Dict[str, Any]
    timestamp: float
    round: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class MultiAgentOrchestrator:
    """
    多 Agent 编排器 — 对话式任务协作

    萃取自 AutoGen 架构：
    - 多 Agent 通过对话协作
    - 任务分解与委派
    - 冲突协商
    - Human-in-the-Loop
    """

    def __init__(self, max_rounds: int = 10, enable_human_in_loop: bool = True):
        self._agents: Dict[str, Agent] = {}
        self._conversations: Dict[str, List[ConversationTurn]] = {}
        self._max_rounds = max_rounds
        self._enable_human_in_loop = enable_human_in_loop
        self._round_counter = 0

    # ============================================================
    # Agent 注册与管理
    # ============================================================

    def register_agent(self, agent: Agent) -> None:
        """注册 Agent"""
        self._agents[agent.id] = agent

        global_event_bus.emit("agent.registered", {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "capabilities": agent.capabilities,
        })

        print(f"[MultiAgent] Agent 注册: {agent.name} ({agent.id})")

    def unregister_agent(self, agent_id: str) -> bool:
        """注销 Agent"""
        if agent_id in self._agents:
            del self._agents[agent_id]
            global_event_bus.emit("agent.unregistered", {"agent_id": agent_id})
            return True
        return False

    def get_agents(self) -> List[Agent]:
        """获取所有 Agent"""
        return list(self._agents.values())

    def find_agent_by_capability(self, capability: str) -> Optional[Agent]:
        """根据能力查找 Agent"""
        for agent in self._agents.values():
            if capability in agent.capabilities:
                return agent
        return None

    # ============================================================
    # 对话协作
    # ============================================================

    def start_conversation(self, task_id: str, initial_message: str,
                          participating_agent_ids: List[str]) -> Dict[str, Any]:
        """
        启动多 Agent 对话

        Args:
            task_id: 任务 ID
            initial_message: 初始消息
            participating_agent_ids: 参与的 Agent ID 列表

        Returns:
            任务结果
        """
        participants = [self._agents[aid] for aid in participating_agent_ids if aid in self._agents]

        if not participants:
            return {"status": "failed", "error": "无可用 Agent"}

        self._conversations[task_id] = []

        global_event_bus.emit("task.started", {
            "task_id": task_id,
            "participants": [a.id for a in participants],
        })

        current_message = initial_message
        current_agent_idx = 0

        for round_num in range(self._max_rounds):
            self._round_counter += 1
            agent = participants[current_agent_idx % len(participants)]

            # 模拟 Agent 响应
            response = f"[{agent.name}] 处理: {current_message[:50]}"

            turn = ConversationTurn(
                id=f"turn_{self._round_counter}",
                agent_id=agent.id,
                message={"role": "assistant", "content": response},
                timestamp=datetime.now().timestamp(),
                round=round_num,
            )

            self._conversations[task_id].append(turn)

            global_event_bus.emit("conversation.turn", {
                "task_id": task_id,
                "turn": turn,
            })

            if self._is_complete(response, round_num):
                result = {"status": "completed", "result": response, "rounds": round_num + 1}
                global_event_bus.emit("task.completed", {"task_id": task_id, "result": result})
                return result

            current_message = response
            current_agent_idx += 1

        result = {"status": "completed", "result": f"完成 ({self._max_rounds} 轮)", "rounds": self._max_rounds}
        global_event_bus.emit("task.completed", {"task_id": task_id, "result": result})
        return result

    # ============================================================
    # 任务分解
    # ============================================================

    def decompose_task(self, task_description: str) -> List[Dict[str, Any]]:
        """
        将复杂任务分解为子任务

        萃取自 AutoGen 的任务分解逻辑
        """
        sub_tasks = []
        capabilities = self._analyze_capabilities(task_description)

        for i, capability in enumerate(capabilities):
            agent = self.find_agent_by_capability(capability)
            sub_tasks.append({
                "id": f"subtask_{uuid.uuid4().hex[:8]}",
                "description": f"[子任务 {i + 1}] {capability}",
                "capability": capability,
                "assigned_agent": agent.name if agent else None,
                "status": "pending",
            })

        if not sub_tasks:
            sub_tasks.append({
                "id": f"subtask_{uuid.uuid4().hex[:8]}",
                "description": task_description,
                "capability": "general",
                "assigned_agent": None,
                "status": "pending",
            })

        return sub_tasks

    def _analyze_capabilities(self, task: str) -> List[str]:
        """分析任务所需能力"""
        capabilities = []

        if re.search(r"代码|编程|code|program", task):
            capabilities.append("coding")
        if re.search(r"搜索|查询|search|query", task):
            capabilities.append("search")
        if re.search(r"分析|analyze", task):
            capabilities.append("analysis")
        if re.search(r"写作|文档|write|document", task):
            capabilities.append("writing")

        return capabilities if capabilities else ["general"]

    # ============================================================
    # 冲突协商
    # ============================================================

    def resolve_conflict(self, responses: List[Dict[str, str]]) -> str:
        """
        多 Agent 冲突协商

        Args:
            responses: [{agent_id, response}, ...]

        Returns:
            协商后的结果
        """
        if not responses:
            return ""

        # 简化策略：返回第一个响应
        # 实际实现可集成投票、仲裁等策略
        return responses[0].get("response", "")

    # ============================================================
    # 人类介入
    # ============================================================

    def request_human_intervention(self, task_id: str, reason: str) -> Optional[str]:
        """
        请求人类介入

        Returns:
            人类响应，或 None（如果不支持 Human-in-the-Loop）
        """
        if not self._enable_human_in_loop:
            return None

        global_event_bus.emit("human.intervention", {
            "task_id": task_id,
            "reason": reason,
            "timestamp": datetime.now().timestamp(),
        })

        return None  # 实际中会等待外部响应

    # ============================================================
    # 工具方法
    # ============================================================

    def _is_complete(self, response: str, round_num: int) -> bool:
        """检查任务是否完成"""
        return round_num >= self._max_rounds - 1 or "[完成]" in response or "[DONE]" in response

    def get_conversation(self, task_id: str) -> List[ConversationTurn]:
        """获取对话历史"""
        return self._conversations.get(task_id, [])

    def clear_conversation(self, task_id: str) -> None:
        """清除对话"""
        self._conversations.pop(task_id, None)


# 全局单例
global_multi_agent = MultiAgentOrchestrator()
