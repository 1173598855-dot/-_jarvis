// @vitest-environment node

import { describe, expect, test, vi } from 'vitest';
import { createCoreApiClient } from './core-api.js';

describe('createCoreApiClient', () => {
  test('distinguishes unconfigured and unavailable core APIs', async () => {
    await expect(createCoreApiClient({ baseUrl: '' }).status()).resolves.toEqual({
      configured: false,
      available: false,
      base_url: null,
    });

    const client = createCoreApiClient({
      baseUrl: 'http://127.0.0.1:8080',
      fetchImpl: vi.fn().mockRejectedValue(new Error('offline')),
    });

    await expect(client.status()).resolves.toEqual({
      configured: true,
      available: false,
      base_url: 'http://127.0.0.1:8080',
    });
  });

  test('forwards JSON requests and preserves query strings', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(
      '{"events":[]}',
      {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      },
    ));
    const client = createCoreApiClient({
      baseUrl: 'http://core.local/',
      fetchImpl,
    });

    await expect(client.request('/api/events?limit=20')).resolves.toEqual({
      status: 200,
      body: { events: [] },
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      'http://core.local/api/events?limit=20',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  test('labels non-JSON responses separately from network failures', async () => {
    const client = createCoreApiClient({
      baseUrl: 'http://core.local',
      fetchImpl: vi.fn().mockResolvedValue(new Response('not-json')),
    });

    await expect(client.request('/api/health')).rejects.toMatchObject({
      code: 'CORE_API_INVALID_RESPONSE',
    });
  });

  test('cancels a chunked response at the first byte beyond 8 MiB', async () => {
    const limit = 8 * 1024 * 1024;
    const chunk = new Uint8Array(64 * 1024).fill(0x78);
    let emittedBytes = 0;
    const cancelSpy = vi.spyOn(ReadableStreamDefaultReader.prototype, 'cancel');
    const body = new ReadableStream({
      pull(controller) {
        if (emittedBytes < limit) {
          controller.enqueue(chunk);
          emittedBytes += chunk.byteLength;
        } else if (emittedBytes === limit) {
          controller.enqueue(Uint8Array.of(0x78));
          emittedBytes += 1;
        } else {
          controller.close();
        }
      },
    });
    const client = createCoreApiClient({
      baseUrl: 'http://core.local',
      fetchImpl: vi.fn().mockResolvedValue(new Response(body, {
        headers: { 'Content-Type': 'application/json' },
      })),
    });

    try {
      await expect(client.request('/api/events')).rejects.toMatchObject({
        code: 'CORE_API_INVALID_RESPONSE',
      });
      expect(emittedBytes).toBe(limit + 1);
      expect(cancelSpy).toHaveBeenCalledOnce();
    } finally {
      cancelSpy.mockRestore();
    }
  });

  test('cancels a response whose declared length exceeds 8 MiB', async () => {
    let cancelled = false;
    const body = new ReadableStream({
      pull(controller) {
        controller.enqueue(new TextEncoder().encode('{}'));
        controller.close();
      },
      cancel() {
        cancelled = true;
      },
    });
    const client = createCoreApiClient({
      baseUrl: 'http://core.local',
      fetchImpl: vi.fn().mockResolvedValue(new Response(body, {
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': String((8 * 1024 * 1024) + 1),
        },
      })),
    });

    await expect(client.request('/api/events')).rejects.toMatchObject({
      code: 'CORE_API_INVALID_RESPONSE',
    });
    expect(cancelled).toBe(true);
  });

  test('does not wait for an oversized response cancellation to settle', async () => {
    vi.useFakeTimers();
    try {
      let cancelCalled = false;
      const body = new ReadableStream({
        cancel() {
          cancelCalled = true;
          return new Promise(() => {});
        },
      });
      const client = createCoreApiClient({
        baseUrl: 'http://core.local',
        fetchImpl: vi.fn().mockResolvedValue(new Response(body, {
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': String((8 * 1024 * 1024) + 1),
          },
        })),
        timeoutMs: 1000,
      });
      const outcome = client.request('/api/events').then(
        (value) => ({ value }),
        (error) => ({ error }),
      );

      const pending = Symbol('pending');
      const deadline = new Promise((resolve) => {
        setTimeout(() => resolve(pending), 1);
      });
      const observedPromise = Promise.race([outcome, deadline]);
      await vi.advanceTimersByTimeAsync(1);
      const observed = await observedPromise;

      expect(observed).not.toBe(pending);
      expect(observed.error).toMatchObject({
        code: 'CORE_API_INVALID_RESPONSE',
      });
      expect(cancelCalled).toBe(true);
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  test('keeps the timeout active while the response body is pending', async () => {
    vi.useFakeTimers();
    try {
      let cancelled = false;
      const client = createCoreApiClient({
        baseUrl: 'http://core.local',
        fetchImpl: vi.fn().mockResolvedValue(new Response(new ReadableStream({
          cancel() {
            cancelled = true;
          },
        }), {
          headers: { 'Content-Type': 'application/json' },
        })),
        timeoutMs: 1000,
      });
      const outcome = client.request('/api/events').then(
        (value) => ({ value }),
        (error) => ({ error }),
      );

      await vi.advanceTimersByTimeAsync(1000);
      await Promise.resolve();
      const pending = Symbol('pending');
      const observed = await Promise.race([outcome, Promise.resolve(pending)]);

      expect(observed).not.toBe(pending);
      expect(observed.error).toMatchObject({ code: 'CORE_API_UNAVAILABLE' });
      expect(cancelled).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  test('uses a per-request timeout without forwarding it to fetch', async () => {
    vi.useFakeTimers();
    try {
      const fetchImpl = vi.fn((_url, init) => new Promise((resolve, reject) => {
        init.signal.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        });
        setTimeout(() => {
          resolve(new Response('{"status":"ok"}', {
            headers: { 'Content-Type': 'application/json' },
          }));
        }, 4000);
      }));
      const client = createCoreApiClient({
        baseUrl: 'http://core.local',
        fetchImpl,
        timeoutMs: 3000,
      });

      const request = client.request(
        '/api/roles/dispatch',
        { method: 'POST' },
        { timeoutMs: 5000 },
      );
      await vi.advanceTimersByTimeAsync(4000);

      await expect(request).resolves.toEqual({
        status: 200,
        body: { status: 'ok' },
      });
      expect(fetchImpl).toHaveBeenCalledWith(
        'http://core.local/api/roles/dispatch',
        expect.not.objectContaining({ timeoutMs: expect.anything() }),
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
