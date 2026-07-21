/**
 * J.A.R.V.I.S. Backend — Node.js + Express (ESM)
 * 解决 Windows Python 中文路径问题
 * 生产模式：同时提供 API 和前端静态文件
 */

import express from 'express';
import cors from 'cors';
import { spawn } from 'child_process';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { createCoreApiClient } from './server/core-api.js';
import { readSystemStats } from './server/system-metrics.js';
import { createTokenUsageStore } from './server/token-usage.js';
import { createRuntimeSecurity } from './server/runtime-security.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = Number(process.env.PORT || 9999);
const runtimeSecurity = createRuntimeSecurity(process.env);
const HOST = runtimeSecurity.host;
const OLLAMA_HOST = process.env.OLLAMA_HOST || 'localhost';
const OLLAMA_PORT = Number(process.env.OLLAMA_PORT || 11434);
const GIT_COMMAND = process.env.JARVIS_GIT_COMMAND || 'git';
const { allowedOrigins } = runtimeSecurity;
const coreApi = createCoreApiClient({
  baseUrl: process.env.JARVIS_CORE_API_URL || '',
});
const tokenUsage = createTokenUsageStore();

// ============================================================
// 中间件
// ============================================================

app.disable('x-powered-by');
app.use(cors({
  origin(origin, callback) {
    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, origin || false);
      return;
    }

    callback(null, false);
  },
  credentials: false,
  methods: ['GET', 'POST', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'X-Jarvis-Terminal-Token'],
}));
const strictJsonParser = express.json({ limit: '32kb' });
const orchestratorJsonParser = express.json({ limit: '32kb', strict: false });
app.use((req, res, next) => {
  if (req.path === '/api/orchestrator/dispatch') {
    return orchestratorJsonParser(req, res, next);
  }
  return strictJsonParser(req, res, next);
});

// 托管前端构建产物
const distPath = path.join(__dirname, '..', 'frontend', 'dist');
app.use(express.static(distPath));

// ============================================================
// 工具函数
// ============================================================

function proxyToOllama(reqPath, res, method = 'GET', body = null) {
  const options = {
    hostname: OLLAMA_HOST,
    port: OLLAMA_PORT,
    path: reqPath,
    method: method,
    headers: { 'Content-Type': 'application/json' },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    let responseBody = '';
    proxyRes.on('data', (chunk) => { responseBody += chunk.toString(); });
    proxyRes.on('end', () => {
      if (!proxyRes.statusCode || proxyRes.statusCode < 200 || proxyRes.statusCode >= 300) {
        return sendApiError(res, 502, 'OLLAMA_UPSTREAM_ERROR', 'Ollama models request failed');
      }
      try {
        const result = JSON.parse(responseBody || '{}');
        if (!result || typeof result !== 'object' || Array.isArray(result) || !Array.isArray(result.models)) {
          throw new Error('Invalid models response');
        }
        return res.status(200).json(result);
      } catch {
        return sendApiError(res, 502, 'OLLAMA_INVALID_RESPONSE', 'Ollama models response is invalid');
      }
    });
  });

  proxyReq.on('error', (err) => {
    console.error(`[Proxy] ${reqPath}: ${err.message}`);
    if (!res.headersSent) {
      sendApiError(
        res,
        503,
        'OLLAMA_UNAVAILABLE',
        'Ollama service is unavailable',
      );
    }
  });

  if (body) {
    proxyReq.write(JSON.stringify(body));
  }
  proxyReq.end();
}

function proxyOllamaChat(res, body) {
  const serializedPayload = JSON.stringify({ ...body, stream: false });
  const options = {
    hostname: OLLAMA_HOST,
    port: OLLAMA_PORT,
    path: '/api/chat',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(serializedPayload),
    },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    let responseBody = '';
    proxyRes.on('data', (chunk) => { responseBody += chunk.toString(); });
    proxyRes.on('end', () => {
      if (!proxyRes.statusCode || proxyRes.statusCode < 200 || proxyRes.statusCode >= 300) {
        return sendApiError(
          res,
          502,
          'OLLAMA_UPSTREAM_ERROR',
          'Ollama chat request failed',
        );
      }

      try {
        const result = JSON.parse(responseBody);
        if (!isValidOllamaChatResponse(result)) {
          throw new Error('Ollama chat response is invalid');
        }
        tokenUsage.recordFrame(result);
        return res.status(200).json(result);
      } catch {
        return sendApiError(
          res,
          502,
          'OLLAMA_UPSTREAM_ERROR',
          'Ollama chat request failed',
        );
      }
    });
  });

  proxyReq.on('error', () => {
    if (!res.headersSent) {
      sendApiError(
        res,
        502,
        'OLLAMA_UPSTREAM_ERROR',
        'Ollama chat request failed',
      );
    }
  });

  proxyReq.write(serializedPayload);
  proxyReq.end();
}

function isValidOllamaChatResponse(result) {
  if (!result || typeof result !== 'object' || Array.isArray(result) || 'error' in result) {
    return false;
  }
  if (typeof result.model !== 'string' || !result.model) return false;
  if (!result.message || typeof result.message !== 'object' || Array.isArray(result.message)) {
    return false;
  }
  if (typeof result.message.role !== 'string' || !result.message.role) return false;
  if (typeof result.message.content !== 'string' || typeof result.done !== 'boolean') {
    return false;
  }
  return ['prompt_eval_count', 'eval_count'].every((field) => (
    result[field] === undefined || (Number.isInteger(result[field]) && result[field] >= 0)
  ));
}

function writeSseHeaders(res) {
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
}

function streamOllamaChat(res, payload) {
  writeSseHeaders(res);
  let completed = false;
  let failed = false;

  const emitStreamError = (message) => {
    if (failed || res.writableEnded) return;
    failed = true;
    res.write(`data: ${JSON.stringify({
      error: {
        code: 'OLLAMA_STREAM_ERROR',
        message,
      },
    })}\n\n`);
  };

  const emitFrame = (frame) => {
    if (failed || completed) return;
    tokenUsage.recordFrame(frame);
    const normalized = {
      model: frame.model || payload.model,
      content: frame.message?.content ?? frame.content ?? '',
      done: frame.done === true,
    };
    if (Number.isFinite(frame.prompt_eval_count)) {
      normalized.prompt_eval_count = frame.prompt_eval_count;
    }
    if (Number.isFinite(frame.eval_count)) {
      normalized.eval_count = frame.eval_count;
    }
    res.write(`data: ${JSON.stringify(normalized)}\n\n`);
    if (normalized.done) completed = true;
  };

  const emitLine = (line) => {
    if (failed || completed) return;
    const data = line.trim().replace(/^data:\s?/, '');
    if (!data || data === '[DONE]') return;

    try {
      const frame = JSON.parse(data);
      if (!frame || typeof frame !== 'object' || Array.isArray(frame)) {
        throw new Error('Ollama stream frame must be a JSON object');
      }
      emitFrame(frame);
    } catch {
      emitStreamError('Ollama stream contained invalid JSON');
    }
  };

  const options = {
    hostname: OLLAMA_HOST,
    port: OLLAMA_PORT,
    path: '/api/chat',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    if (proxyRes.statusCode && proxyRes.statusCode >= 400) {
      let errorBody = '';
      proxyRes.on('data', (chunk) => { errorBody += chunk.toString(); });
      proxyRes.on('end', () => {
        let message = errorBody || `Ollama HTTP ${proxyRes.statusCode}`;
        try {
          const parsed = JSON.parse(errorBody);
          message = typeof parsed.error === 'string'
            ? parsed.error
            : parsed.error?.message || message;
        } catch {
          // The raw upstream text is the most specific available message.
        }
        emitStreamError(message);
        res.end();
      });
      return;
    }

    let buffer = '';

    proxyRes.on('data', (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        emitLine(line);
      }
    });

    proxyRes.on('end', () => {
      emitLine(buffer);
      if (!failed && completed) {
        res.write('data: [DONE]\n\n');
      } else if (!failed) {
        emitStreamError('Ollama stream ended before completion');
      }
      res.end();
    });
  });

  proxyReq.on('error', (err) => {
    emitStreamError(err.message);
    res.end();
  });

  proxyReq.write(JSON.stringify({ ...payload, stream: true }));
  proxyReq.end();
}

function sendCoreError(res, error, capability) {
  const code = error.code || 'CORE_API_UNAVAILABLE';
  const messages = {
    CORE_API_NOT_CONFIGURED: 'Core API is not configured',
    CORE_API_UNAVAILABLE: 'Core API is unavailable',
    CORE_API_INVALID_RESPONSE: 'Core API returned invalid JSON',
  };
  return sendApiError(
    res,
    code === 'CORE_API_NOT_CONFIGURED' ? 503 : 502,
    code,
    messages[code] || 'Core API request failed',
  );
}

function sendApiError(res, status, code, message) {
  return res.status(status).json({
    error: { code, message },
  });
}

function hasUnpairedSurrogate(value) {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xD800 && codeUnit <= 0xDBFF) {
      const nextCodeUnit = value.charCodeAt(index + 1);
      if (nextCodeUnit < 0xDC00 || nextCodeUnit > 0xDFFF) {
        return true;
      }
      index += 1;
    } else if (codeUnit >= 0xDC00 && codeUnit <= 0xDFFF) {
      return true;
    }
  }
  return false;
}

async function proxyCoreRequest(req, res, capability) {
  try {
    const hasBody = req.method !== 'GET' && req.method !== 'HEAD';
    const headers = hasBody ? { 'Content-Type': 'application/json' } : {};
    const terminalToken = req.get('X-Jarvis-Terminal-Token');
    if (terminalToken) {
      headers['X-Jarvis-Terminal-Token'] = terminalToken;
    }
    const result = await coreApi.request(req.originalUrl, {
      method: req.method,
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      body: hasBody ? JSON.stringify(req.body || {}) : undefined,
    });
    res.status(result.status).json(result.body);
  } catch (error) {
    sendCoreError(res, error, capability);
  }
}

// ============================================================
// API 端点
// ============================================================

app.get('/api/health', (req, res) => {
  res.json({
    status: 'healthy',
    uptime: process.uptime(),
    timestamp: Date.now(),
    version: '1.1.0',
  });
});

app.get('/api/ollama/status', async (req, res) => {
  const options = {
    hostname: OLLAMA_HOST,
    port: OLLAMA_PORT,
    path: '/api/tags',
    method: 'GET',
  };

  const ollamaReq = http.request(options, (ollamaRes) => {
    let body = '';
    ollamaRes.on('data', (chunk) => { body += chunk.toString(); });
    ollamaRes.on('end', () => {
      if (ollamaRes.statusCode && ollamaRes.statusCode >= 400) {
        return sendApiError(res, 502, 'OLLAMA_UPSTREAM_ERROR', 'Ollama status request failed');
      }

      try {
        const parsed = JSON.parse(body || '{}');
        res.json({
          running: true,
          version: parsed.version,
          models: parsed.models || [],
          gpu_available: false,
          gpu_name: '',
        });
      } catch (err) {
        return sendApiError(res, 502, 'OLLAMA_INVALID_RESPONSE', 'Ollama status response is invalid');
      }
    });
  });

  ollamaReq.on('error', (err) => {
    return sendApiError(res, 503, 'OLLAMA_UNAVAILABLE', 'Ollama service is unavailable');
  });

  ollamaReq.end();
});

app.get('/api/ollama/models', (req, res) => {
  proxyToOllama('/api/tags', res);
});

app.post('/api/ollama/chat', (req, res) => {
  if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'Request body must be a JSON object',
    );
  }
  if (req.body.stream !== undefined && req.body.stream !== false) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'Use /api/ollama/chat/stream for streaming requests',
    );
  }
  return proxyOllamaChat(res, req.body);
});

app.get('/api/ollama/chat/stream', (req, res) => {
  const model = req.query.model || 'default';
  let messages;

  try {
    messages = JSON.parse(req.query.messages || '[]');
  } catch {
    messages = [{ role: 'user', content: String(req.query.messages || '') }];
  }

  streamOllamaChat(res, { model, messages });
});

app.post('/api/ollama/chat/stream', (req, res) => {
  if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'Request body must be a JSON object',
    );
  }
  const { model = 'default', messages = [] } = req.body || {};
  streamOllamaChat(res, { model, messages });
});

app.get('/api/system/stats', async (req, res) => {
  try {
    res.json(await readSystemStats());
  } catch (err) {
    return sendApiError(res, 500, 'SYSTEM_STATS_FAILED', 'System statistics are unavailable');
  }
});

app.get('/api/capabilities', async (req, res) => {
  res.json({ core_api: await coreApi.status() });
});

app.post('/api/terminal/execute', async (req, res) => {
  if (!req.body || Array.isArray(req.body) || typeof req.body !== 'object') {
    return sendApiError(res, 400, 'INVALID_REQUEST', 'Request body must be a JSON object');
  }
  const { command } = req.body;
  if (!command) {
    return sendApiError(res, 400, 'MISSING_COMMAND', '缺少 command 参数');
  }
  if (!runtimeSecurity.terminalEnabled) {
    return sendApiError(res, 403, 'TERMINAL_DISABLED', 'Terminal execution is disabled');
  }
  if (!runtimeSecurity.isAuthorized(req.get('X-Jarvis-Terminal-Token'))) {
    return sendApiError(res, 401, 'TERMINAL_UNAUTHORIZED', 'Terminal capability token is invalid');
  }
  await proxyCoreRequest(req, res, 'terminal');
});

app.get('/api/plugins', async (req, res) => {
  await proxyCoreRequest(req, res, 'plugins');
});

app.get('/api/memory/entries', async (req, res) => {
  await proxyCoreRequest(req, res, 'memory');
});

app.post('/api/memory/store', async (req, res) => {
  await proxyCoreRequest(req, res, 'memory');
});

app.delete('/api/memory/probes/:memoryType/:entryId', async (req, res) => {
  await proxyCoreRequest(req, res, 'memory');
});

app.get('/api/events', async (req, res) => {
  await proxyCoreRequest(req, res, 'events');
});

app.get('/api/orchestrator/agents', async (req, res) => {
  await proxyCoreRequest(req, res, 'orchestrator');
});

app.get('/api/orchestrator/history', async (req, res) => {
  const rawLimit = req.query.limit;
  if (rawLimit !== undefined) {
    const normalizedLimit = Array.isArray(rawLimit)
      ? ''
      : String(rawLimit).trim();
    const parsedLimit = Number(normalizedLimit);
    if (
      !/^[+-]?\d+$/.test(normalizedLimit)
      || !Number.isSafeInteger(parsedLimit)
    ) {
      return sendApiError(
        res,
        400,
        'INVALID_REQUEST',
        'limit must be an integer',
      );
    }
  }
  await proxyCoreRequest(req, res, 'orchestrator');
});

app.post('/api/orchestrator/dispatch', async (req, res) => {
  if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'Request body must be a JSON object',
    );
  }

  const {
    agent_name: agentName,
    prompt,
    timeout = 300,
    priority = 1,
  } = req.body;
  if (
    typeof agentName !== 'string'
    || !agentName.trim()
    || hasUnpairedSurrogate(agentName)
  ) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'agent_name must be a non-empty string',
    );
  }
  if (
    typeof prompt !== 'string'
    || !prompt.trim()
    || hasUnpairedSurrogate(prompt)
  ) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'prompt must be a non-empty string',
    );
  }
  if (
    typeof timeout !== 'number'
    || !Number.isSafeInteger(timeout)
    || timeout < 1
    || timeout > 300
  ) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'timeout must be an integer between 1 and 300',
    );
  }
  if (
    typeof priority !== 'number'
    || !Number.isInteger(priority)
    || priority < 0
    || priority > 3
  ) {
    return sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'priority must be an integer between 0 and 3',
    );
  }
  req.body = {
    ...req.body,
    agent_name: agentName,
    prompt,
    timeout,
    priority,
  };
  await proxyCoreRequest(req, res, 'orchestrator');
});

app.get('/api/roles', async (req, res) => {
  await proxyCoreRequest(req, res, 'roles');
});

app.get('/api/roles/tasks', async (req, res) => {
  await proxyCoreRequest(req, res, 'role_tasks');
});

app.post('/api/roles/tasks', async (req, res) => {
  await proxyCoreRequest(req, res, 'role_tasks');
});

app.get('/api/roles/tasks/:taskId', async (req, res) => {
  await proxyCoreRequest(req, res, 'role_tasks');
});

app.post('/api/roles/tasks/:taskId/cancel', async (req, res) => {
  await proxyCoreRequest(req, res, 'role_tasks');
});

app.get('/api/roles/:roleName', async (req, res) => {
  await proxyCoreRequest(req, res, 'roles');
});

function validateRolePrompt(req, res) {
  const { prompt } = req.body;
  const timeout = req.body.timeout === undefined ? 300 : req.body.timeout;
  if (
    typeof prompt !== 'string'
    || !prompt.trim()
    || hasUnpairedSurrogate(prompt)
  ) {
    sendApiError(res, 400, 'INVALID_REQUEST', 'prompt must be a non-empty string');
    return false;
  }
  if (
    typeof timeout !== 'number'
    || !Number.isSafeInteger(timeout)
    || timeout < 1
    || timeout > 300
  ) {
    sendApiError(
      res,
      400,
      'INVALID_REQUEST',
      'timeout must be an integer between 1 and 300',
    );
    return false;
  }
  req.body = { ...req.body, prompt, timeout };
  return true;
}

app.post('/api/roles/dispatch', async (req, res) => {
  if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    return sendApiError(res, 400, 'INVALID_REQUEST', 'Request body must be a JSON object');
  }
  const { role_name: roleName } = req.body;
  if (
    typeof roleName !== 'string'
    || !roleName.trim()
    || hasUnpairedSurrogate(roleName)
  ) {
    return sendApiError(res, 400, 'INVALID_REQUEST', 'role_name must be a non-empty string');
  }
  if (!validateRolePrompt(req, res)) {
    return;
  }
  await proxyCoreRequest(req, res, 'roles');
});

app.post('/api/roles/dispatch_by_cap', async (req, res) => {
  if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    return sendApiError(res, 400, 'INVALID_REQUEST', 'Request body must be a JSON object');
  }
  const { capability } = req.body;
  if (
    typeof capability !== 'string'
    || !capability.trim()
    || hasUnpairedSurrogate(capability)
  ) {
    return sendApiError(res, 400, 'INVALID_REQUEST', 'capability must be a non-empty string');
  }
  if (!validateRolePrompt(req, res)) {
    return;
  }
  await proxyCoreRequest(req, res, 'roles');
});

app.post('/api/roles/batch_dispatch', async (req, res) => {
  if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    return sendApiError(res, 400, 'INVALID_REQUEST', 'Request body must be a JSON object');
  }
  if (req.body.tasks !== undefined && !Array.isArray(req.body.tasks)) {
    return sendApiError(res, 400, 'INVALID_REQUEST', 'tasks must be an array');
  }
  await proxyCoreRequest(req, res, 'roles');
});

for (const action of ['load', 'enable', 'disable']) {
  app.post(`/api/plugins/${action}`, async (req, res) => {
    await proxyCoreRequest(req, res, 'plugins');
  });
}

// ============================================================
// Git 仓库状态
// ============================================================

app.get('/api/git/status', async (req, res) => {
  try {
    const result = await runGitCommand(['status', '--porcelain', '--branch']);
    const branchMatch = result.stdout.match(/^## (.+?)(?:\.\.\.)?/);
    const branch = branchMatch ? branchMatch[1] : 'unknown';
    const changedFiles = result.stdout
      .split('\n')
      .filter((line) => line.trim().length > 0 && !line.startsWith('##'))
      .map((line) => {
        const status = line.slice(0, 2);
        const file = line.slice(3);
        return { status, file, staged: status[0] !== ' ' && status[0] !== '?' };
      });
    res.json({
      branch,
      clean: changedFiles.length === 0,
      changedFiles,
      count: changedFiles.length,
    });
  } catch {
    return sendApiError(
      res,
      500,
      'GIT_COMMAND_FAILED',
      'Git repository metadata is unavailable',
    );
  }
});

app.get('/api/git/log', async (req, res) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || '10') || 10, 100);
    const result = await runGitCommand([
      'log',
      `--max-count=${limit}`,
      '--format=%H|%an|%ae|%ai|%s',
    ]);
    const commits = result.stdout
      .split('\n')
      .filter((l) => l.trim())
      .map((line) => {
        const [hash, author, email, date, ...subjectParts] = line.split('|');
        return {
          hash: hash.slice(0, 8),
          author,
          email,
          date,
          subject: subjectParts.join('|'),
        };
      });
    res.json({ commits });
  } catch {
    return sendApiError(
      res,
      500,
      'GIT_COMMAND_FAILED',
      'Git repository metadata is unavailable',
    );
  }
});

app.get('/api/git/branches', async (req, res) => {
  try {
    const result = await runGitCommand(['branch', '--list', '-a']);
    const branches = result.stdout
      .split('\n')
      .map((b) => b.replace(/^\s*[\* ]\s*/, ''))
      .filter((b) => b.trim().length > 0);
    res.json({ branches });
  } catch {
    return sendApiError(
      res,
      500,
      'GIT_COMMAND_FAILED',
      'Git repository metadata is unavailable',
    );
  }
});

function runGitCommand(args) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (callback, value) => {
      if (settled) return;
      settled = true;
      callback(value);
    };
    const git = spawn(GIT_COMMAND, args, { cwd: path.join(__dirname, '..') });
    let stdout = '';
    let stderr = '';
    git.stdout?.on('data', (d) => { stdout += d.toString(); });
    git.stderr?.on('data', (d) => { stderr += d.toString(); });
    git.once('close', (code) => {
      if (code === 0) settle(resolve, { stdout, stderr });
      else settle(reject, new Error(stderr || `git exit ${code}`));
    });
    git.once('error', (error) => settle(reject, error));
  });
}

// ============================================================
app.get('/api/ollama/token-usage', (req, res) => {
  res.json(tokenUsage.snapshot());
});

app.use((error, _req, res, next) => {
  if (error?.type === 'entity.too.large' || error?.status === 413) {
    return sendApiError(
      res,
      413,
      'REQUEST_BODY_TOO_LARGE',
      'Request body exceeds the 32 KiB limit',
    );
  }
  if (error instanceof SyntaxError && error.status === 400 && 'body' in error) {
    return sendApiError(res, 400, 'INVALID_JSON', 'Request body must be valid JSON');
  }
  return next(error);
});

app.all('/api/*path', (_req, res) => {
  sendApiError(res, 404, 'API_NOT_FOUND', 'API endpoint not found');
});

// ============================================================
// 前端路由 fallback（SPA）— Express v5 修复：sendFile 不再接受回调
// ============================================================
app.get('*path', (req, res) => {
  const indexPath = path.join(distPath, 'index.html');
  if (!fs.existsSync(indexPath)) {
    return sendApiError(res, 404, 'FRONTEND_NOT_BUILT', 'Frontend assets are not built');
  }
  res.sendFile(indexPath);
});

// ============================================================
// 启动
// ============================================================

const server = app.listen(PORT, HOST, () => {
  const address = server.address();
  const boundHost = typeof address === 'object' && address ? address.address : HOST;
  const boundPort = typeof address === 'object' && address ? address.port : PORT;
  console.log(`🤖 J.A.R.V.I.S. Backend 启动: http://${boundHost}:${boundPort}`);
  console.log('可用端点:');
  console.log('  GET  /api/health');
  console.log('  GET  /api/system/stats');
  console.log('  GET  /api/ollama/status');
  console.log('  GET  /api/ollama/models');
  console.log('  POST /api/ollama/chat');
  console.log('  GET  /api/ollama/chat/stream (SSE)');
  console.log('  POST /api/terminal/execute');
  console.log('  GET  /api/plugins');
  console.log('  GET  /api/memory/entries');
  console.log('  POST /api/memory/store');
  console.log('  GET  /api/events');
});

server.on('error', (err) => {
  console.error(`[Server] 启动失败: ${err.message}`);
  process.exit(1);
});

process.on('uncaughtException', (err) => {
  console.error(`[Uncaught] ${err.message}`);
  console.error(err.stack);
});
