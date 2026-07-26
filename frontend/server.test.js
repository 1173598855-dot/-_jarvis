// @vitest-environment node

import { afterAll, beforeAll, describe, expect, test, vi } from 'vitest';
import { spawn } from 'child_process';
import { readFileSync } from 'fs';
import http from 'http';

let apiPort;
let ollamaPort;
let corePort;
let apiProcess;
let apiOutput = '';
let ollamaServer;
let coreServer;
let ollamaStatusMode = 'healthy';
let coreMode = 'healthy';
let coreHistoryUrl;
let coreDispatchBody;
let coreRoleUrl;
let coreRoleBody;
let coreRoleTaskUrl;
let coreRoleTaskBody;
let coreRoleFixture;

function getServerPort(server) {
  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('test server did not expose a TCP port');
  }
  return address.port;
}

function waitForExpressPort() {
  const deadline = Date.now() + 8000;

  return new Promise((resolve, reject) => {
    const attempt = () => {
      const match = apiOutput.match(/http:\/\/127\.0\.0\.1:(\d+)/);
      const port = match ? Number(match[1]) : 0;
      if (port > 0) {
        resolve(port);
        return;
      }

      if (apiProcess && apiProcess.exitCode !== null) {
        reject(new Error(`server exited before listening: ${apiProcess.exitCode}`));
        return;
      }
      if (Date.now() > deadline) {
        reject(new Error('server did not report a dynamic port'));
        return;
      }

      setTimeout(attempt, 50);
    };

    attempt();
  });
}

function waitForHealth() {
  const deadline = Date.now() + 8000;

  return new Promise((resolve, reject) => {
    const attempt = async () => {
      try {
        const response = await fetch(`http://127.0.0.1:${apiPort}/api/health`);
        if (response.ok) {
          resolve();
          return;
        }
      } catch {
        // Server is still starting.
      }

      if (Date.now() > deadline) {
        reject(new Error('server did not become healthy'));
        return;
      }

      setTimeout(attempt, 100);
    };

    attempt();
  });
}

beforeAll(async () => {
  ollamaServer = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/api/tags') {
      if (ollamaStatusMode === 'upstream-error') {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'fixture unavailable' }));
        return;
      }
      if (ollamaStatusMode === 'malformed') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('{invalid json');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ models: [] }));
      return;
    }
    if (req.method === 'POST' && req.url === '/api/chat') {
      let body = '';
      req.on('data', (chunk) => { body += chunk.toString(); });
      req.on('end', () => {
        const payload = JSON.parse(body || '{}');
        if (payload.model === 'missing-model') {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'model not found' }));
          return;
        }
      res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
      res.write(JSON.stringify({ message: { content: 'hello' }, done: false }) + '\n');
      res.write(JSON.stringify({
        done: true,
        prompt_eval_count: 7,
        eval_count: 5,
      }) + '\n');
      res.end();
      });
      return;
    }

    res.writeHead(404);
    res.end();
  });

  await new Promise((resolve) => ollamaServer.listen(0, '127.0.0.1', resolve));
  ollamaPort = getServerPort(ollamaServer);

  coreServer = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');

    if (req.url === '/api/health') {
      res.end(JSON.stringify({ status: 'healthy' }));
      return;
    }
    if (req.url === '/api/plugins') {
      if (coreMode === 'invalid') {
        res.writeHead(200, { 'Content-Type': 'text/plain' });
        res.end('not-json');
        return;
      }
      res.end(JSON.stringify({
        plugins: [{
          id: 'event-logger',
          name: 'Event Logger',
          version: '1.0.0',
          status: 'enabled',
          permissions: ['events'],
        }],
      }));
      return;
    }
    if (req.url === '/api/memory/entries') {
      res.end(JSON.stringify({ entries: [] }));
      return;
    }
    if (req.method === 'DELETE' && req.url === '/api/memory/probes/project/probe123') {
      res.end(JSON.stringify({ success: true, id: 'probe123' }));
      return;
    }
    if (req.url?.startsWith('/api/events')) {
      res.end(JSON.stringify({ events: [] }));
      return;
    }
    if (req.url === '/api/orchestrator/agents') {
      res.end(JSON.stringify({ agents: [], count: 0 }));
      return;
    }
    if (req.url?.startsWith('/api/orchestrator/history')) {
      coreHistoryUrl = req.url;
      res.end(JSON.stringify({ results: [], count: 0 }));
      return;
    }
    if (req.method === 'POST' && req.url === '/api/orchestrator/dispatch') {
      let body = '';
      req.on('data', (chunk) => { body += chunk.toString(); });
      req.on('end', () => {
        const payload = JSON.parse(body || '{}');
        coreDispatchBody = payload;
        res.end(JSON.stringify({
          task_id: 'fixture-task',
          agent_name: payload.agent_name || 'fixture-agent',
          result: 'ok',
          error: '',
          duration_ms: 0,
          status: 'success',
        }));
      });
      return;
    }

    if (req.method === 'GET' && req.url === '/api/roles') {
      res.end(JSON.stringify({
        roles: [{
          name: 'engineer',
          display_name: 'Engineer',
          capabilities: ['coding'],
          priority: 7,
        }],
        count: 1,
      }));
      return;
    }
    if (req.method === 'GET' && req.url === '/api/roles/engineer') {
      res.end(JSON.stringify({
        role: {
          name: 'engineer',
          display_name: 'Engineer',
          capabilities: ['coding'],
          priority: 7,
        },
      }));
      return;
    }
    if (req.method === 'GET' && req.url?.startsWith('/api/roles/tasks?')) {
      coreRoleTaskUrl = req.url;
      res.end(JSON.stringify({ tasks: [], count: 0 }));
      return;
    }
    if (req.method === 'GET' && req.url === '/api/roles/tasks/task-fixture') {
      coreRoleTaskUrl = req.url;
      res.end(JSON.stringify({
        protocol_version: 1,
        task_id: 'task-fixture',
        attempt_id: 'attempt-fixture',
        role_name: 'engineer',
        status: 'running',
      }));
      return;
    }
    if (
      req.method === 'POST'
      && (
        req.url === '/api/roles/tasks'
        || req.url === '/api/roles/tasks/task-fixture/cancel'
      )
    ) {
      let body = '';
      req.on('data', (chunk) => { body += chunk.toString(); });
      req.on('end', () => {
        coreRoleTaskUrl = req.url;
        coreRoleTaskBody = JSON.parse(body || '{}');
        const cancelled = req.url.endsWith('/cancel');
        res.writeHead(cancelled ? 200 : 202);
        res.end(JSON.stringify({
          protocol_version: 1,
          task_id: 'task-fixture',
          attempt_id: 'attempt-fixture',
          role_name: 'engineer',
          status: cancelled ? 'cancelled' : 'running',
          termination_confirmed: cancelled,
        }));
      });
      return;
    }
    if (
      req.method === 'POST'
      && (
        req.url === '/api/roles/dispatch'
        || req.url === '/api/roles/dispatch_by_cap'
        || req.url === '/api/roles/batch_dispatch'
      )
    ) {
      let body = '';
      req.on('data', (chunk) => { body += chunk.toString(); });
      req.on('end', () => {
        coreRoleUrl = req.url;
        coreRoleBody = JSON.parse(body || '{}');
        if (coreRoleFixture) {
          const { body: fixtureBody, delayMs = 0, status = 200 } = coreRoleFixture;
          setTimeout(() => {
            res.writeHead(status);
            res.end(JSON.stringify(fixtureBody));
          }, delayMs);
          return;
        }
        if (req.url === '/api/roles/batch_dispatch') {
          res.end(JSON.stringify({ results: [], count: 0 }));
          return;
        }
        res.end(JSON.stringify({
          role_name: coreRoleBody.role_name || 'engineer',
          task_id: 'fixture-role-task',
          status: 'dispatched',
          message: 'ok',
        }));
      });
      return;
    }

    res.writeHead(404);
    res.end(JSON.stringify({ detail: 'not found' }));
  });

  await new Promise((resolve) => coreServer.listen(0, '127.0.0.1', resolve));
  corePort = getServerPort(coreServer);

  apiProcess = spawn('node', ['server.js'], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      PORT: '0',
      JARVIS_HOST: '127.0.0.1',
      OLLAMA_HOST: '127.0.0.1',
      OLLAMA_PORT: String(ollamaPort),
      JARVIS_CORE_API_URL: `http://127.0.0.1:${corePort}`,
      JARVIS_ALLOWED_ORIGINS: 'https://jarvis.local',
      JARVIS_GIT_COMMAND: 'jarvis-git-command-does-not-exist',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  apiProcess.stdout.on('data', (chunk) => {
    apiOutput += chunk.toString();
  });

  apiPort = await waitForExpressPort();
  await waitForHealth();
}, 10000);

afterAll(async () => {
  if (apiProcess) {
    apiProcess.kill();
  }
  if (ollamaServer) {
    await new Promise((resolve) => ollamaServer.close(resolve));
  }
  if (coreServer) {
    await new Promise((resolve) => coreServer.close(resolve));
  }
});

describe('Server binding', () => {
  test('allocates every harness port dynamically', () => {
    const harnessSource = readFileSync(new URL('./server.test.js', import.meta.url), 'utf8');

    expect(harnessSource).not.toMatch(
      /\b(?:const|let)\s+(?:API|OLLAMA|CORE)_PORT\s*=\s*\d+\s*;/,
    );
    expect(harnessSource.match(/\.listen\(0, '127\.0\.0\.1'/g)).toHaveLength(3);
    expect(harnessSource).toMatch(/^\s+PORT: '0',\s*$/m);
  });

  test('uses the configured loopback host', () => {
    expect(apiOutput).toContain(`http://127.0.0.1:${apiPort}`);
  });
});

describe('API fallback contract', () => {
  test.each(['GET', 'POST'])('returns ErrorResponse for an unknown %s API route', async (method) => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/not-a-real-route`, {
      method,
      headers: method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
      body: method === 'POST' ? JSON.stringify({}) : undefined,
    });

    expect(response.status).toBe(404);
    expect(response.headers.get('content-type')).toContain('application/json');
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'API_NOT_FOUND',
        message: 'API endpoint not found',
      },
    });
  });
});

describe('Ollama streaming chat proxy', () => {
  test('allows configured origins without exposing wildcard CORS', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/health`, {
      headers: { Origin: 'https://jarvis.local' },
    });

    expect(response.headers.get('access-control-allow-origin')).toBe('https://jarvis.local');
  });

  test('rejects unconfigured origins from CORS response headers', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/health`, {
      headers: { Origin: 'https://evil.example' },
    });

    expect(response.headers.get('access-control-allow-origin')).toBeNull();
  });

  test('accepts POST requests and emits SSE data frames', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/ollama/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'test-model',
        messages: [{ role: 'user', content: 'ping' }],
      }),
    });

    const body = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('text/event-stream');
    expect(body).toContain('data: {"model":"test-model","content":"hello","done":false}');
    expect(body).toContain('data: [DONE]');

    const usageResponse = await fetch(
      `http://127.0.0.1:${apiPort}/api/ollama/token-usage`,
    );
    const usage = await usageResponse.json();

    expect(usage.latest).toMatchObject({
      prompt_tokens: 7,
      completion_tokens: 5,
      total_tokens: 12,
    });
    expect(usage.totals.total_tokens).toBe(12);
    expect(usage.samples).toHaveLength(1);
  });

  test('turns an upstream Ollama HTTP failure into an explicit SSE error', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/ollama/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'missing-model', messages: [] }),
    });
    const body = await response.text();

    expect(body).toContain('"error":{"code":"OLLAMA_STREAM_ERROR","message":"model not found"}');
    expect(body).not.toContain('data: [DONE]');
  });

  test('labels malformed Ollama status JSON as a contract failure', async () => {
    ollamaStatusMode = 'malformed';
    try {
      const response = await fetch(`http://127.0.0.1:${apiPort}/api/ollama/status`);
      const body = await response.json();

      expect(response.status).toBe(502);
      expect(body.error.code).toBe('OLLAMA_INVALID_RESPONSE');
    } finally {
      ollamaStatusMode = 'healthy';
    }
  });

  test('returns a stable envelope for an Ollama models upstream failure', async () => {
    ollamaStatusMode = 'upstream-error';
    try {
      const response = await fetch(`http://127.0.0.1:${apiPort}/api/ollama/models`);
      expect(response.status).toBe(502);
      await expect(response.json()).resolves.toEqual({
        error: {
          code: 'OLLAMA_UPSTREAM_ERROR',
          message: 'Ollama models request failed',
        },
      });
    } finally {
      ollamaStatusMode = 'healthy';
    }
  });
});

describe('System telemetry', () => {
  test('reports truthful cross-platform metrics with source metadata', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/system/stats`);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.meta).toMatchObject({
      source: 'systeminformation',
    });
    expect(['ready', 'degraded']).toContain(body.meta.status);
    expect(body.meta.unavailable_fields).toBeInstanceOf(Array);
    expect(body.cpu.usage === null || typeof body.cpu.usage === 'number').toBe(true);
    expect(body.memory.usage === null || typeof body.memory.usage === 'number').toBe(true);
    expect(body.disk.usage === null || typeof body.disk.usage === 'number').toBe(true);
  }, 10_000);
});

describe('Shared API errors', () => {
  test('returns a stable envelope when Git cannot start', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/git/status`);
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({
      error: {
        code: 'GIT_COMMAND_FAILED',
        message: 'Git repository metadata is unavailable',
      },
    });
  });

  test('does not proxy terminal execution without an explicit capability', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/terminal/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'echo', args: ['blocked'] }),
    });
    const body = await response.json();

    expect(response.status).toBe(403);
    expect(body.error.code).toBe('TERMINAL_DISABLED');
  });

  test('returns the standard missing-command envelope', async () => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/terminal/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: '' }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({
      error: {
        code: 'MISSING_COMMAND',
        message: expect.any(String),
      },
    });
  });
});

describe('Core API bridge', () => {
  test('reports capability availability and proxies plugins', async () => {
    const capabilitiesResponse = await fetch(
      `http://127.0.0.1:${apiPort}/api/capabilities`,
    );
    const capabilities = await capabilitiesResponse.json();
    expect(capabilitiesResponse.status).toBe(200);
    expect(capabilities.core_api).toEqual({
      configured: true,
      available: true,
      base_url: `http://127.0.0.1:${corePort}`,
    });

    const pluginsResponse = await fetch(
      `http://127.0.0.1:${apiPort}/api/plugins`,
    );
    const plugins = await pluginsResponse.json();
    expect(pluginsResponse.status).toBe(200);
    expect(plugins.plugins).toEqual([
      expect.objectContaining({ id: 'event-logger', status: 'enabled' }),
    ]);
  });

  test('proxies scoped memory probe deletion', async () => {
    const response = await fetch(
      `http://127.0.0.1:${apiPort}/api/memory/probes/project/probe123`,
      { method: 'DELETE' },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ success: true, id: 'probe123' });
  });

  test('proxies the shared orchestrator agent, history, and dispatch routes', async () => {
    coreHistoryUrl = undefined;
    coreDispatchBody = undefined;

    const agents = await fetch(`http://127.0.0.1:${apiPort}/api/orchestrator/agents`);
    expect(agents.status).toBe(200);
    await expect(agents.json()).resolves.toEqual({ agents: [], count: 0 });

    const history = await fetch(`http://127.0.0.1:${apiPort}/api/orchestrator/history?limit=5`);
    expect(history.status).toBe(200);
    await expect(history.json()).resolves.toEqual({ results: [], count: 0 });
    expect(coreHistoryUrl).toBe('/api/orchestrator/history?limit=5');

    const dispatch = await fetch(`http://127.0.0.1:${apiPort}/api/orchestrator/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_name: 'fixture-agent',
        prompt: 'ping',
        timeout: 45,
        priority: 3,
      }),
    });
    expect(dispatch.status).toBe(200);
    expect(coreDispatchBody).toEqual({
      agent_name: 'fixture-agent',
      prompt: 'ping',
      timeout: 45,
      priority: 3,
    });
    await expect(dispatch.json()).resolves.toMatchObject({
      task_id: 'fixture-task',
      agent_name: 'fixture-agent',
      result: 'ok',
      error: '',
      duration_ms: expect.any(Number),
      status: 'success',
    });
  });

  test('proxies the shared role list, detail, and dispatch routes', async () => {
    coreRoleUrl = undefined;
    coreRoleBody = undefined;

    const roles = await fetch(`http://127.0.0.1:${apiPort}/api/roles`);
    expect(roles.status).toBe(200);
    await expect(roles.json()).resolves.toMatchObject({
      count: 1,
      roles: [expect.objectContaining({ name: 'engineer' })],
    });

    const role = await fetch(`http://127.0.0.1:${apiPort}/api/roles/engineer`);
    expect(role.status).toBe(200);
    await expect(role.json()).resolves.toMatchObject({
      role: expect.objectContaining({ name: 'engineer' }),
    });

    const dispatch = await fetch(`http://127.0.0.1:${apiPort}/api/roles/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        role_name: 'engineer',
        prompt: 'write a test',
        timeout: 30,
      }),
    });
    expect(dispatch.status).toBe(200);
    expect(coreRoleUrl).toBe('/api/roles/dispatch');
    expect(coreRoleBody).toEqual({
      role_name: 'engineer',
      prompt: 'write a test',
      timeout: 30,
    });
    await expect(dispatch.json()).resolves.toMatchObject({
      role_name: 'engineer',
      task_id: 'fixture-role-task',
      status: 'dispatched',
    });

    const capability = await fetch(
      `http://127.0.0.1:${apiPort}/api/roles/dispatch_by_cap`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capability: 'coding', prompt: 'fix bug' }),
      },
    );
    expect(capability.status).toBe(200);
    expect(coreRoleUrl).toBe('/api/roles/dispatch_by_cap');
    expect(coreRoleBody).toEqual({
      capability: 'coding',
      prompt: 'fix bug',
      timeout: 300,
    });

    const batch = await fetch(
      `http://127.0.0.1:${apiPort}/api/roles/batch_dispatch`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tasks: [{ role: 'engineer', prompt: 'task' }] }),
      },
    );
    expect(batch.status).toBe(200);
    expect(coreRoleUrl).toBe('/api/roles/batch_dispatch');
    expect(coreRoleBody).toEqual({
      tasks: [{ role: 'engineer', prompt: 'task' }],
    });
    await expect(batch.json()).resolves.toEqual({ results: [], count: 0 });
  });

  test('keeps synchronous role requests alive beyond the default Core timeout with fake timers', async () => {
    let resolveCoreCall;
    let resolveCoreResponse;
    const coreRequest = vi.fn((_path, _init, options) => {
      resolveCoreCall(options);
      return new Promise((resolve) => {
        resolveCoreResponse = resolve;
      });
    });
    const coreCall = new Promise((resolve) => {
      resolveCoreCall = resolve;
    });
    const previousNoListen = process.env.JARVIS_TEST_NO_LISTEN;
    let proxyServer;
    try {
      process.env.JARVIS_TEST_NO_LISTEN = '1';
      vi.doMock('./server/core-api.js', () => ({
        createCoreApiClient: () => ({
          request: coreRequest,
          status: async () => ({
            configured: true,
            available: true,
            base_url: 'http://core.test',
          }),
        }),
      }));
      const { app: proxyApp } = await import('./server.js');
      proxyServer = http.createServer(proxyApp);
      await new Promise((resolve) => proxyServer.listen(0, '127.0.0.1', resolve));
      const proxyPort = getServerPort(proxyServer);
      const responsePromise = fetch(
        `http://127.0.0.1:${proxyPort}/api/roles/dispatch`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            role_name: 'engineer',
            prompt: 'wait for worker',
            timeout: 1,
          }),
        },
      );
      await coreCall;
      expect(coreRequest).toHaveBeenCalledWith(
        '/api/roles/dispatch',
        expect.any(Object),
        { timeoutMs: 6000 },
      );

      vi.useFakeTimers();
      setTimeout(() => resolveCoreResponse({
        status: 200,
        body: {
          role_name: 'engineer',
          task_id: 'fixture-delayed-role-task',
          status: 'success',
          message: 'delayed ok',
        },
      }), 3100);
      await vi.advanceTimersByTimeAsync(3100);
      const response = await responsePromise;

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toEqual({
        role_name: 'engineer',
        task_id: 'fixture-delayed-role-task',
        status: 'success',
        message: 'delayed ok',
      });
    } finally {
      vi.useRealTimers();
      vi.doUnmock('./server/core-api.js');
      vi.resetModules();
      if (previousNoListen === undefined) {
        delete process.env.JARVIS_TEST_NO_LISTEN;
      } else {
        process.env.JARVIS_TEST_NO_LISTEN = previousNoListen;
      }
      if (proxyServer) {
        await new Promise((resolve) => proxyServer.close(resolve));
      }
    }
  });

  test.each([
    ['ROLE_WORKER_UNAVAILABLE', 'Role worker is unavailable'],
    [
      'ROLE_WORKER_INVALID_RESULT',
      'Role worker returned an invalid result',
    ],
    [
      'ROLE_TASK_TERMINATION_UNCONFIRMED',
      'Worker process termination is not confirmed',
    ],
  ])('forwards the Core %s response unchanged', async (code, message) => {
    const body = { error: { code, message } };
    coreRoleFixture = { status: 503, body };
    try {
      const response = await fetch(
        `http://127.0.0.1:${apiPort}/api/roles/dispatch`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            role_name: 'engineer',
            prompt: 'exercise worker error',
            timeout: 1,
          }),
        },
      );

      expect(response.status).toBe(503);
      expect(await response.text()).toBe(JSON.stringify(body));
    } finally {
      coreRoleFixture = undefined;
    }
  });

  test('keeps batch Worker failures as positional 200 results', async () => {
    const body = {
      results: [{
        role_name: 'engineer',
        task_id: 'fixture-batch-task',
        status: 'error',
        message: 'Role worker is unavailable',
      }],
      count: 1,
    };
    coreRoleFixture = { status: 200, body };
    try {
      const response = await fetch(
        `http://127.0.0.1:${apiPort}/api/roles/batch_dispatch`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tasks: [{ role: 'engineer', prompt: 'batch worker error' }],
          }),
        },
      );

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toEqual(body);
    } finally {
      coreRoleFixture = undefined;
    }
  });

  test('proxies every asynchronous role task lifecycle route', async () => {
    coreRoleTaskUrl = undefined;
    coreRoleTaskBody = undefined;

    const created = await fetch(`http://127.0.0.1:${apiPort}/api/roles/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        role_name: 'engineer',
        prompt: 'review state',
        timeout: 30,
      }),
    });
    expect(created.status).toBe(202);
    expect(coreRoleTaskUrl).toBe('/api/roles/tasks');
    expect(coreRoleTaskBody).toEqual({
      role_name: 'engineer',
      prompt: 'review state',
      timeout: 30,
    });

    const listed = await fetch(
      `http://127.0.0.1:${apiPort}/api/roles/tasks?limit=5`,
    );
    expect(listed.status).toBe(200);
    expect(coreRoleTaskUrl).toBe('/api/roles/tasks?limit=5');

    const fetched = await fetch(
      `http://127.0.0.1:${apiPort}/api/roles/tasks/task-fixture`,
    );
    expect(fetched.status).toBe(200);
    await expect(fetched.json()).resolves.toMatchObject({
      task_id: 'task-fixture',
      status: 'running',
    });

    const cancelled = await fetch(
      `http://127.0.0.1:${apiPort}/api/roles/tasks/task-fixture/cancel`,
      { method: 'POST' },
    );
    expect(cancelled.status).toBe(200);
    expect(coreRoleTaskUrl).toBe('/api/roles/tasks/task-fixture/cancel');
    await expect(cancelled.json()).resolves.toMatchObject({
      task_id: 'task-fixture',
      status: 'cancelled',
      termination_confirmed: true,
    });
  });

  test.each([
    ['/api/roles/dispatch', { prompt: 'missing role' }],
    ['/api/roles/dispatch', { role_name: ' ', prompt: 'blank role' }],
    ['/api/roles/dispatch', { role_name: 'engineer', prompt: ' ' }],
    ['/api/roles/dispatch', { role_name: 'engineer', prompt: 'task', timeout: 301 }],
    ['/api/roles/dispatch_by_cap', { prompt: 'missing capability' }],
    ['/api/roles/dispatch_by_cap', { capability: ' ', prompt: 'blank capability' }],
    ['/api/roles/dispatch_by_cap', { capability: 'coding', prompt: ' ' }],
    ['/api/roles/batch_dispatch', { tasks: {} }],
  ])('rejects invalid role request %s locally', async (path, payload) => {
    const response = await fetch(`http://127.0.0.1:${apiPort}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'INVALID_REQUEST',
        message: expect.any(String),
      },
    });
  });

  test('applies and forwards the default orchestrator timeout', async () => {
    coreDispatchBody = undefined;

    const response = await fetch(`http://127.0.0.1:${apiPort}/api/orchestrator/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_name: 'fixture-agent',
        prompt: 'ping',
      }),
    });

    expect(response.status).toBe(200);
    expect(coreDispatchBody).toEqual({
      agent_name: 'fixture-agent',
      prompt: 'ping',
      timeout: 300,
      priority: 1,
    });
  });

  test.each([
    ['an array body', []],
    ['a scalar body', 'not-an-object'],
    ['a null body', null],
  ])('rejects %s for orchestrator dispatch', async (_label, payload) => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/orchestrator/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'INVALID_REQUEST',
        message: expect.any(String),
      },
    });
  });

  test.each([
    ['missing agent_name', { prompt: 'ping' }],
    ['empty agent_name', { agent_name: '   ', prompt: 'ping' }],
    ['non-string agent_name', { agent_name: 1, prompt: 'ping' }],
    ['unpaired surrogate in agent_name', { agent_name: 'fixture\uD800agent', prompt: 'ping' }],
    ['missing prompt', { agent_name: 'fixture-agent' }],
    ['empty prompt', { agent_name: 'fixture-agent', prompt: '\t' }],
    ['non-string prompt', { agent_name: 'fixture-agent', prompt: [] }],
    ['unpaired surrogate in prompt', { agent_name: 'fixture-agent', prompt: 'ping\uDC00' }],
    ['timeout below minimum', { agent_name: 'fixture-agent', prompt: 'ping', timeout: 0 }],
    ['timeout above maximum', { agent_name: 'fixture-agent', prompt: 'ping', timeout: 301 }],
    ['non-integer timeout', { agent_name: 'fixture-agent', prompt: 'ping', timeout: 1.5 }],
    ['boolean timeout', { agent_name: 'fixture-agent', prompt: 'ping', timeout: true }],
    ['priority below minimum', { agent_name: 'fixture-agent', prompt: 'ping', priority: -1 }],
    ['priority above maximum', { agent_name: 'fixture-agent', prompt: 'ping', priority: 4 }],
    ['non-integer priority', { agent_name: 'fixture-agent', prompt: 'ping', priority: 1.5 }],
    ['boolean priority', { agent_name: 'fixture-agent', prompt: 'ping', priority: false }],
  ])('rejects %s for orchestrator dispatch', async (_label, payload) => {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/orchestrator/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'INVALID_REQUEST',
        message: expect.any(String),
      },
    });
  });

  test.each(['abc', '1.5', ''])('rejects non-integer history limit %j', async (limit) => {
    const response = await fetch(
      `http://127.0.0.1:${apiPort}/api/orchestrator/history?limit=${encodeURIComponent(limit)}`,
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'INVALID_REQUEST',
        message: expect.any(String),
      },
    });
  });

  test('returns a stable envelope when Core API returns non-JSON', async () => {
    coreMode = 'invalid';
    try {
      const response = await fetch(`http://127.0.0.1:${apiPort}/api/plugins`);
      expect(response.status).toBe(502);
      await expect(response.json()).resolves.toEqual({
        error: {
          code: 'CORE_API_INVALID_RESPONSE',
          message: 'Core API returned invalid JSON',
        },
      });
    } finally {
      coreMode = 'healthy';
    }
  });
});
