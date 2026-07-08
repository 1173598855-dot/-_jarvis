/**
 * MultiAgentProtocol — 小奕 J.A.R.V.I.S. 多 Agent 对话协议
 * @core/brain
 *
 * 萃取自 AutoGen 的多 Agent 对话架构，重写为小奕原生实现
 *
 * 功能：
 * 1. Agent 注册与发现
 * 2. 对话式任务协作
 * 3. 消息路由与转发
 * 4. 任务分解与委派
 * 5. 冲突协商机制
 * 6. 人类介入（Human-in-the-Loop）
 */

import { globalEventBus } from '../kernel/event-bus';
import type { AgentMessage, AgentTask } from '../../types';

// ============================================================
// 类型定义
// ============================================================

export type AgentStatus = 'idle' | 'thinking' | 'acting' | 'waiting' | 'error';

export interface Agent {
  id: string;
  name: string;
  role: string;
  capabilities: string[];
  status: AgentStatus;
  systemPrompt: string;
  tools: string[];
}

export interface AgentCapability {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface ConversationTurn {
  id: string;
  agentId: string;
  message: AgentMessage;
  timestamp: number;
  metadata?: Record<string, unknown>;
}

export interface MultiAgentConfig {
  maxRounds: number;
  enableHumanInLoop: boolean;
  conflictResolution: 'vote' | 'arbitrate' | 'sequential';
  timeout: number;
}

// ============================================================
// MultiAgentOrchestrator 实现
// ============================================================

export class MultiAgentOrchestrator {
  private agents: Map<string, Agent> = new Map();
  private conversations: Map<string, ConversationTurn[]> = new Map();
  private config: MultiAgentConfig;
  private roundCounter = 0;

  constructor(config: Partial<MultiAgentConfig> = {}) {
    this.config = {
      maxRounds: config.maxRounds ?? 10,
      enableHumanInLoop: config.enableHumanInLoop ?? true,
      conflictResolution: config.conflictResolution ?? 'arbitrate',
      timeout: config.timeout ?? 30000,
    };
  }

  // ============================================================
  // Agent 注册与管理
  // ============================================================

  /**
   * 注册 Agent
   */
  registerAgent(agent: Agent): void {
    this.agents.set(agent.id, {
      ...agent,
      status: 'idle',
    });

    // 发布事件
    globalEventBus.emit('agent.registered', {
      agentId: agent.id,
      agentName: agent.name,
      capabilities: agent.capabilities,
    });

    console.log(`[MultiAgent] Agent 注册: ${agent.name} (${agent.id})`);
  }

  /**
   * 注销 Agent
   */
  unregisterAgent(agentId: string): boolean {
    const deleted = this.agents.delete(agentId);
    if (deleted) {
      globalEventBus.emit('agent.unregistered', { agentId });
    }
    return deleted;
  }

  /**
   * 获取所有 Agent
   */
  getAgents(): Agent[] {
    return Array.from(this.agents.values());
  }

  /**
   * 根据能力查找 Agent
   */
  findAgentByCapability(capability: string): Agent | undefined {
    return Array.from(this.agents.values()).find(
      agent => agent.capabilities.includes(capability)
    );
  }

  // ============================================================
  // 对话协作
  // ============================================================

  /**
   * 启动多 Agent 对话
   *
   * 流程：
   * 1. 选择适合的 Agent
   * 2. 分发任务给 Agent
   * 3. Agent 之间对话协作
   * 4. 冲突协商
   * 5. 汇总结果
   */
  async startConversation(
    taskId: string,
    initialMessage: string,
    participatingAgentIds: string[],
  ): Promise<AgentTask> {
    const task: AgentTask = {
      id: taskId,
      description: initialMessage,
      status: 'running',
      createdAt: Date.now(),
    };

    const participants = participatingAgentIds
      .map(id => this.agents.get(id))
      .filter((a): a is Agent => a !== undefined);

    if (participants.length === 0) {
      task.status = 'failed';
      task.error = '无可用 Agent';
      return task;
    }

    // 初始化对话
    this.conversations.set(taskId, []);

    // 发布任务开始事件
    globalEventBus.emit('task.started', { taskId, participants: participants.map(a => a.id) });

    // 多轮对话
    let currentMessage = initialMessage;
    let currentAgentIndex = 0;

    for (let round = 0; round < this.config.maxRounds; round++) {
      this.roundCounter++;

      const currentAgent = participants[currentAgentIndex % participants.length];
      currentAgent.status = 'thinking';

      // 模拟 Agent 处理（实际中这里会调用 LLM）
      const response = await this.simulateAgentResponse(
        currentAgent,
        currentMessage,
        taskId,
      );

      // 记录对话
      const turn: ConversationTurn = {
        id: `turn_${this.roundCounter}`,
        agentId: currentAgent.id,
        message: {
          role: 'assistant',
          content: response,
          timestamp: Date.now(),
        },
        timestamp: Date.now(),
        metadata: { round, taskId },
      };

      const conversation = this.conversations.get(taskId) || [];
      conversation.push(turn);
      this.conversations.set(taskId, conversation);

      // 发布对话事件
      globalEventBus.emit('conversation.turn', {
        taskId,
        turn,
      });

      // 检查是否完成
      if (this.isTaskComplete(response, round)) {
        task.status = 'completed';
        task.result = response;
        task.completedAt = Date.now();
        break;
      }

      // 下一轮
      currentMessage = response;
      currentAgent.status = 'idle';
      currentAgentIndex++;
    }

    if (task.status === 'running') {
      task.status = 'completed';
      task.result = `任务完成（${this.config.maxRounds} 轮对话）`;
      task.completedAt = Date.now();
    }

    // 发布任务完成事件
    globalEventBus.emit('task.completed', { taskId, result: task.result });

    return task;
  }

  // ============================================================
  // 任务分解
  // ============================================================

  /**
   * 将复杂任务分解为子任务
   *
   * 萃取自 AutoGen 的任务分解逻辑
   */
  async decomposeTask(taskDescription: string): Promise<AgentTask[]> {
    const subTasks: AgentTask[] = [];

    // 简单分解策略：按能力匹配
    const capabilities = this.analyzeCapabilities(taskDescription);

    for (let i = 0; i < capabilities.length; i++) {
      const capability = capabilities[i];
      const agent = this.findAgentByCapability(capability);

      if (agent) {
        subTasks.push({
          id: `subtask_${Date.now()}_${i}`,
          description: `[子任务 ${i + 1}] 处理能力: ${capability}`,
          status: 'pending',
          createdAt: Date.now(),
        });
      }
    }

    // 如果没有找到匹配的 Agent，创建一个通用任务
    if (subTasks.length === 0) {
      subTasks.push({
        id: `subtask_${Date.now()}_0`,
        description: taskDescription,
        status: 'pending',
        createdAt: Date.now(),
      });
    }

    return subTasks;
  }

  /**
   * 分析任务所需能力（简化版）
   */
  private analyzeCapabilities(task: string): string[] {
    const capabilities: string[] = [];

    if (/代码|编程|code|program/.test(task)) {
      capabilities.push("coding");
    }
    if (/搜索|查询|search|query/.test(task)) {
      capabilities.push("search");
    }
    if (/分析|analyze/.test(task)) {
      capabilities.push("analysis");
    }
    if (/写作|文档|write|document/.test(task)) {
      capabilities.push("writing");
    }

    return capabilities.length > 0 ? capabilities : ["general"];
  }

  // ============================================================
  // 冲突协商
  // ============================================================

  /**
   * 多 Agent 冲突协商
   */
  async resolveConflict(
    conflictingResponses: Array<{ agentId: string; response: string }>,
  ): Promise<string> {
    switch (this.config.conflictResolution) {
      case 'vote':
        return this.voteResolution(conflictingResponses);
      case 'arbitrate':
        return this.arbitrateResolution(conflictingResponses);
      case 'sequential':
        return this.sequentialResolution(conflictingResponses);
      default:
        return conflictingResponses[0]?.response || '';
    }
  }

  private voteResolution(responses: Array<{ agentId: string; response: string }>): string {
    // 简化：返回第一个
    return responses[0]?.response || '';
  }

  private async arbitrateResolution(responses: Array<{ agentId: string; response: string }>): Promise<string> {
    // 委托给 arbitrator Agent
    const arbitrator = this.findAgentByCapability('arbitration');
    if (arbitrator) {
      // 实际中调用 arbitrator 的 LLM
      return responses[0]?.response || '';
    }
    return responses[0]?.response || '';
  }

  private sequentialResolution(responses: Array<{ agentId: string; response: string }>): string {
    // 按顺序执行，最后一个结果为准
    return responses[responses.length - 1]?.response || '';
  }

  // ============================================================
  // 人类介入
  // ============================================================

  /**
   * 请求人类介入
   */
  async requestHumanIntervention(
    taskId: string,
    reason: string,
  ): Promise<string | null> {
    if (!this.config.enableHumanInLoop) {
      return null;
    }

    // 发布事件，等待外部响应
    return new Promise((resolve) => {
      const handler = (event: EventBusEvent) => {
        if (event.type === 'human.response' && event.payload.taskId === taskId) {
          globalEventBus.unsubscribe(handlerId);
          resolve(event.payload.response as string);
        }
      };

      const handlerId = globalEventBus.subscribe('human.response', handler);

      globalEventBus.emit('human.intervention', {
        taskId,
        reason,
        timestamp: Date.now(),
      });
    });
  }

  // ============================================================
  // 工具方法
  // ============================================================

  /**
   * 模拟 Agent 响应（实际中会调用 LLM）
   */
  private async simulateAgentResponse(
    agent: Agent,
    message: string,
    taskId: string,
  ): Promise<string> {
    // 实际实现会调用 LLM
    // 这里返回模拟响应
    return `[${agent.name}] 处理完成: ${message[:100]}`;
  }

  /**
   * 检查任务是否完成
   */
  private isTaskComplete(response: string, round: number): boolean {
    // 简化：到达最大轮次或包含完成标记
    return round >= this.config.maxRounds - 1 ||
           response.includes('[完成]') ||
           response.includes('[DONE]');
  }

  /**
   * 获取对话历史
   */
  getConversation(taskId: string): ConversationTurn[] {
    return this.conversations.get(taskId) || [];
  }

  /**
   * 清除对话
   */
  clearConversation(taskId: string): void {
    this.conversations.delete(taskId);
  }
}

// ============================================================
// 单例导出
// ============================================================

export const globalMultiAgent = new MultiAgentOrchestrator();
