import { afterEach, describe, expect, it, vi } from 'vitest';
import { JarvisApiError, jarvisApi, requestJson } from '../services/jarvis-api';

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

  it('requests the complete read-only capability inventory', async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ schema_version: 1, capabilities: [], count: 0, issues: [] }),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      },
    ));
    vi.stubGlobal('fetch', fetchMock);

    await expect(jarvisApi.capabilityRegistry(signal)).resolves.toEqual({
      schema_version: 1,
      capabilities: [],
      count: 0,
      issues: [],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/capabilities/registry?limit=100',
      expect.objectContaining({ signal }),
    );
  });

  it('requests the Express Git read-only endpoints through typed clients', async () => {
    const fetchMock = vi.fn(async (path: string) => {
      const bodies: Record<string, unknown> = {
        '/api/git/status': {
          branch: 'codex/jarvis-command-center',
          clean: false,
          changedFiles: [{
            status: ' M',
            file: 'frontend/src/App.tsx',
            staged: false,
          }],
          count: 1,
        },
        '/api/git/log?limit=5': {
          commits: [{
            hash: 'abc12345',
            author: 'Codex',
            email: 'codex@example.com',
            date: '2026-07-10T10:00:00+08:00',
            subject: 'feat: command center',
          }],
        },
        '/api/git/branches': {
          branches: ['main', 'codex/jarvis-command-center'],
        },
      };
      return new Response(JSON.stringify(bodies[path]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(jarvisApi.gitStatus()).resolves.toMatchObject({
      branch: 'codex/jarvis-command-center',
      count: 1,
    });
    await expect(jarvisApi.gitLog(5)).resolves.toMatchObject({
      commits: [expect.objectContaining({ hash: 'abc12345' })],
    });
    await expect(jarvisApi.gitBranches()).resolves.toEqual({
      branches: ['main', 'codex/jarvis-command-center'],
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/git/status',
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/git/log?limit=5',
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/git/branches',
      expect.any(Object),
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
