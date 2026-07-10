// @vitest-environment node

import { afterAll, beforeAll, describe, expect, test } from 'vitest';
import { spawn } from 'child_process';
import http from 'http';

const API_PORT = 19999;
const OLLAMA_PORT = 19998;

let apiProcess;
let ollamaServer;

function waitForHealth() {
  const deadline = Date.now() + 8000;

  return new Promise((resolve, reject) => {
    const attempt = async () => {
      try {
        const response = await fetch(`http://127.0.0.1:${API_PORT}/api/health`);
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
    if (req.method === 'POST' && req.url === '/api/chat') {
      res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
      res.write(JSON.stringify({ message: { content: 'hello' }, done: false }) + '\n');
      res.write(JSON.stringify({ done: true }) + '\n');
      res.end();
      return;
    }

    res.writeHead(404);
    res.end();
  });

  await new Promise((resolve) => ollamaServer.listen(OLLAMA_PORT, '127.0.0.1', resolve));

  apiProcess = spawn('node', ['server.js'], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      PORT: String(API_PORT),
      OLLAMA_HOST: '127.0.0.1',
      OLLAMA_PORT: String(OLLAMA_PORT),
      JARVIS_ALLOWED_ORIGINS: 'https://jarvis.local',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  await waitForHealth();
}, 10000);

afterAll(async () => {
  if (apiProcess) {
    apiProcess.kill();
  }
  if (ollamaServer) {
    await new Promise((resolve) => ollamaServer.close(resolve));
  }
});

describe('Ollama streaming chat proxy', () => {
  test('allows configured origins without exposing wildcard CORS', async () => {
    const response = await fetch(`http://127.0.0.1:${API_PORT}/api/health`, {
      headers: { Origin: 'https://jarvis.local' },
    });

    expect(response.headers.get('access-control-allow-origin')).toBe('https://jarvis.local');
  });

  test('rejects unconfigured origins from CORS response headers', async () => {
    const response = await fetch(`http://127.0.0.1:${API_PORT}/api/health`, {
      headers: { Origin: 'https://evil.example' },
    });

    expect(response.headers.get('access-control-allow-origin')).toBeNull();
  });

  test('accepts POST requests and emits SSE data frames', async () => {
    const response = await fetch(`http://127.0.0.1:${API_PORT}/api/ollama/chat/stream`, {
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
    expect(body).toContain('data: {"message":{"content":"hello"},"done":false}');
    expect(body).toContain('data: [DONE]');
  });
});

describe('System telemetry', () => {
  test('reports truthful cross-platform metrics with source metadata', async () => {
    const response = await fetch(`http://127.0.0.1:${API_PORT}/api/system/stats`);
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
  });
});
