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
});
