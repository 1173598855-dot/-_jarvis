import { createRoot } from 'solid-js';
import { describe, expect, it, vi } from 'vitest';
import { createPollingResource } from '../primitives/create-polling-resource';

function withRoot<T>(factory: () => T) {
  let dispose: () => void = () => undefined;
  const value = createRoot((rootDispose) => {
    dispose = rootDispose;
    return factory();
  });
  return { value, dispose };
}

describe('createPollingResource', () => {
  it('retains the last value and becomes stale after refresh failure', async () => {
    const load = vi.fn()
      .mockResolvedValueOnce({ value: 1 })
      .mockRejectedValueOnce(new Error('offline'));
    const { value: resource, dispose } = withRoot(() =>
      createPollingResource<{ value: number }>({
        load,
        intervalMs: 1000,
        autoStart: false,
      }));

    await resource.refresh();
    expect(resource.phase()).toBe('ready');
    await resource.refresh();
    expect(resource.phase()).toBe('stale');
    expect(resource.data()).toEqual({ value: 1 });
    expect(resource.error()?.message).toBe('offline');
    dispose();
  });

  it('classifies empty and degraded successful values', async () => {
    const load = vi.fn()
      .mockResolvedValueOnce({ items: [] as string[], degraded: false })
      .mockResolvedValueOnce({ items: ['one'], degraded: true });
    const { value: resource, dispose } = withRoot(() =>
      createPollingResource<{ items: string[]; degraded: boolean }>({
        load,
        intervalMs: 1000,
        autoStart: false,
        classify: (value) => {
          if (value.items.length === 0) return 'empty';
          return value.degraded ? 'degraded' : 'ready';
        },
      }));

    await resource.refresh();
    expect(resource.phase()).toBe('empty');
    await resource.refresh();
    expect(resource.phase()).toBe('degraded');
    dispose();
  });

  it('aborts an overlapping request and ignores its late result', async () => {
    const requests: Array<{
      signal: AbortSignal;
      resolve(value: number): void;
    }> = [];
    const load = vi.fn((signal: AbortSignal) => new Promise<number>((resolve) => {
      requests.push({ signal, resolve });
    }));
    const { value: resource, dispose } = withRoot(() =>
      createPollingResource<number>({
        load,
        intervalMs: 1000,
        autoStart: false,
      }));

    const first = resource.refresh();
    const second = resource.refresh();
    expect(requests[0].signal.aborted).toBe(true);

    requests[1].resolve(2);
    await second;
    requests[0].resolve(1);
    await first;

    expect(resource.data()).toBe(2);
    expect(resource.phase()).toBe('ready');
    dispose();
  });
});
