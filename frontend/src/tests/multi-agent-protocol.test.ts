import { describe, it, expect } from 'vitest';
import {
  IAgentTask,
  IAgentResult,
  IAgentInfo,
  IAgentProfile,
  IMultiAgentOrchestrator,
  TaskOutcome,
  TaskPriority,
} from '../core/brain/multi-agent-protocol';

describe('Multi-agent protocol contracts', () => {
  it('defines a valid agent task with defaults', () => {
    const task: IAgentTask = {
      taskId: 'task-1',
      agentName: 'engineer',
      prompt: 'Implement feature X',
    };

    expect(task.taskId).toBe('task-1');
    expect(timeoutOr(task)).toBe(undefined);
    expect(priorityOf(task)).toBe(undefined);
  });

  it('defines a valid agent result shape', () => {
    const result: IAgentResult = {
      taskId: 'task-1',
      agentName: 'engineer',
      status: 'success',
      result: { ok: true },
    };
    const outcome: TaskOutcome = result.status;

    expect(outcome).toBe('success');
    expect(result.error).toBe(undefined);
    expect(result.durationMs).toBe(undefined);
  });

  it('defines agent info shape', () => {
    const info: IAgentInfo = {
      name: 'engineer',
      capabilities: ['coding', 'testing'],
      tasksCompleted: 1,
      errorsCount: 0,
      status: 'idle',
    };

    expect(info.status).toBe('idle');
  });

  it('defines agent profile shape with defaults', () => {
    const profile: IAgentProfile = {
      name: 'engineer',
      displayName: '工程师',
      description: 'Builds features.',
      capabilities: ['coding'],
      constraints: [],
      promptTemplate: 'You are {name}.',
      tools: ['terminal_executor'],
      priority: 7,
    };

    expect(profile.parentRole).toBe(undefined);
    expect(profile.metadata).toBe(undefined);
  });

  it('accepts orchestrator interface shape', () => {
    const orchestrator: IMultiAgentOrchestrator = {
      async dispatch() {
        return {
          taskId: 'task-1',
          agentName: 'engineer',
          status: 'success',
        };
      },
      async dispatchConcurrent() {
        return [];
      },
      register() {
        return orchestrator;
      },
      unregister() {
        return true;
      },
      listAgents() {
        return [];
      },
      collect() {
        return [];
      },
      getStats() {
        return {};
      },
      shutdown() {},
    };

    expect(orchestrator).toBeDefined();
  });

  it('allows numeric priority alias', () => {
    const numericPriority: IAgentTask['priority'] = 1;
    expect(numericPriority).toBe(1);
  });
});

function timeoutOr(task: IAgentTask): number | undefined {
  return task.timeout;
}

function priorityOf(task: IAgentTask): TaskPriority | number | undefined {
  return task.priority;
}
