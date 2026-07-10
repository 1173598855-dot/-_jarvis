/**
 * Multi-Agent Protocol - Phase 11
 *
 * TypeScript contracts for frontend integration with the Python orchestrator.
 * These interfaces mirror `core.brain.orchestrator` and `core.brain.role_registry`.
 */

// ============================================================
// Task / Result contracts
// ============================================================

export type AgentStatus = 'idle' | 'busy' | 'error' | 'shutdown';
export type TaskPriority = 'low' | 'medium' | 'high' | 'critical';
export type TaskOutcome = 'success' | 'error' | 'timeout' | 'busy' | 'unknown';

export interface IAgentTask {
  taskId: string;
  agentName: string;
  prompt: string;
  timeout?: number;
  priority?: TaskPriority | number;
  metadata?: Record<string, unknown>;
}

export interface IAgentResult {
  taskId: string;
  agentName: string;
  result?: unknown;
  error?: string;
  durationMs?: number;
  status: TaskOutcome;
}

// ============================================================
// Registry / role contracts
// ============================================================

export interface IAgentInfo {
  name: string;
  capabilities: string[];
  tasksCompleted: number;
  errorsCount: number;
  status: AgentStatus;
}

export interface IAgentProfile {
  name: string;
  displayName: string;
  description: string;
  parentRole?: string;
  capabilities: string[];
  constraints: string[];
  promptTemplate: string;
  tools: string[];
  priority: number;
  metadata?: Record<string, unknown>;
}

// ============================================================
// Orchestrator contracts
// ============================================================

export type AgentHandler = (task: IAgentTask) => Promise<unknown>;

export interface IMultiAgentOrchestrator {
  register(name: string, handler: AgentHandler, capabilities?: string[]): IMultiAgentOrchestrator;
  unregister(name: string): boolean;
  listAgents(): IAgentInfo[];
  dispatch(task: IAgentTask): Promise<IAgentResult>;
  dispatchConcurrent(tasks: IAgentTask[]): Promise<IAgentResult[]>;
  collect(agentName?: string, status?: TaskOutcome, limit?: number): IAgentResult[];
  getStats(): Record<string, number>;
  shutdown(): void;
}
