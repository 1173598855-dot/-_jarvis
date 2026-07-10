import { afterEach, describe, expect, it, vi } from 'vitest';
import { JarvisApiError, requestJson } from '../services/jarvis-api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('requestJson', () => {
  it('returns typed JSON and forwards AbortSignal', async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      '{"status":"healthy"}',
      {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      },
    ));
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestJson<{ status: string }>('/api/health', { signal }))
      .resolves.toEqual({ status: 'healthy' });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ signal }),
    );
  });

  it('turns structured failures into JarvisApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        error: {
          code: 'CORE_API_UNAVAILABLE',
          message: 'Core API 未连接',
        },
      }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      },
    )));

    await expect(requestJson('/api/plugins')).rejects.toMatchObject({
      name: 'JarvisApiError',
      code: 'CORE_API_UNAVAILABLE',
      status: 503,
    } satisfies Partial<JarvisApiError>);
  });
});
