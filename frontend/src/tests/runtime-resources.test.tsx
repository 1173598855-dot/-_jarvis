import { render, screen } from '@solidjs/testing-library';
import { describe, expect, it } from 'vitest';
import {
  RuntimeResourcesProvider,
  useRuntimeResources,
  type RuntimeResources,
} from '../app/runtime-resources';
import type { PollingResource } from '../primitives/create-polling-resource';

function fixedResource<T>(value: T): PollingResource<T> {
  return {
    data: () => value,
    phase: () => 'ready',
    error: () => undefined,
    updatedAt: () => 1000,
    refresh: async () => undefined,
  };
}

describe('RuntimeResourcesProvider', () => {
  it('shares an injected resource registry with descendants', () => {
    const resources: RuntimeResources = {
      system: fixedResource({
        cpu: { usage: 10, cores: 8, model: 'CPU' },
        memory: { total: 100, used: 50, free: 50, usage: 50 },
        disk: { total: 100, used: 20, free: 80, usage: 20 },
        gpu: [],
        meta: {
          status: 'ready',
          source: 'test',
          unavailable_fields: [],
        },
      }),
      ollama: fixedResource({
        running: true,
        models: [],
        gpu_available: false,
      }),
      git: fixedResource({
        branch: 'test',
        clean: true,
        changedFiles: [],
        count: 0,
      }),
      tokens: fixedResource({
        latest: null,
        totals: {
          prompt_tokens: 0,
          completion_tokens: 0,
          total_tokens: 0,
        },
        samples: [],
        session_started_at: 1000,
      }),
      capabilities: fixedResource({
        core_api: {
          configured: true,
          available: true,
          base_url: 'http://core.local',
        },
      }),
    };

    const Probe = () => {
      const value = useRuntimeResources();
      return <span>{value === resources ? '共享资源' : '重复资源'}</span>;
    };

    render(() => (
      <RuntimeResourcesProvider value={resources}>
        <Probe />
      </RuntimeResourcesProvider>
    ));

    expect(screen.getByText('共享资源')).not.toBeNull();
  });
});
