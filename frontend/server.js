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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = Number(process.env.PORT || 9999);
const OLLAMA_HOST = process.env.OLLAMA_HOST || 'localhost';
const OLLAMA_PORT = Number(process.env.OLLAMA_PORT || 11434);
const allowedOrigins = (process.env.JARVIS_ALLOWED_ORIGINS || '*')
  .split(',')
  .map((origin) => origin.trim())
  .filter(Boolean);
const coreApi = createCoreApiClient({
  baseUrl: process.env.JARVIS_CORE_API_URL || '',
});
const tokenUsage = createTokenUsageStore();

// ============================================================
// 中间件
// ============================================================

app.use(cors({
  origin(origin, callback) {
    if (allowedOrigins.includes('*')) {
      callback(null, '*');
      return;
    }

    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, origin || false);
      return;
    }

    callback(null, false);
  },
}));
app.use(express.json());

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
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    console.error(`[Proxy] ${reqPath}: ${err.message}`);
    if (!res.headersSent) {
      res.status(500).json({ error: `Ollama 服务未启动: ${err.message}` });
    }
  });

  if (body) {
    proxyReq.write(JSON.stringify(body));
  }
  proxyReq.end();
}

function writeSseHeaders(res) {
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
}

function streamOllamaChat(res, payload) {
  writeSseHeaders(res);

  const emitLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;

    if (trimmed.startsWith('data:')) {
      const data = trimmed.replace(/^data:\s?/, '');
      if (data !== '[DONE]') {
        try {
          tokenUsage.recordFrame(JSON.parse(data));
        } catch {
          // Preserve malformed upstream frames for the client to report.
        }
      }
      res.write(`${trimmed}\n\n`);
      return;
    }

    try {
      const frame = JSON.parse(trimmed);
      tokenUsage.recordFrame(frame);
      res.write(`data: ${JSON.stringify(frame)}\n\n`);
    } catch {
      res.write(`data: ${JSON.stringify({ raw: trimmed })}\n\n`);
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
      res.write('data: [DONE]\n\n');
      res.end();
    });
  });

  proxyReq.on('error', (err) => {
    res.write(`data: ${JSON.stringify({ error: err.message })}\n\n`);
    res.end();
  });

  proxyReq.write(JSON.stringify({ ...payload, stream: true }));
  proxyReq.end();
}

function runPythonScript(scriptName, args = []) {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(__dirname, '..', 'src', 'core', scriptName);
    const python = spawn('python', [scriptPath, ...args]);

    let stdout = '';
    let stderr = '';

    python.stdout.on('data', (data) => { stdout += data.toString(); });
    python.stderr.on('data', (data) => { stderr += data.toString(); });

    python.on('close', (code) => {
      if (code === 0) {
        try { resolve(JSON.parse(stdout)); }
        catch { resolve({ stdout, stderr }); }
      } else {
        reject(new Error(stderr || `Exit code: ${code}`));
      }
    });

    python.on('error', reject);
  });
}

function sendCoreError(res, error, capability) {
  const code = error.code || 'CORE_API_UNAVAILABLE';
  res.status(code === 'CORE_API_NOT_CONFIGURED' ? 503 : 502).json({
    error: {
      code,
      message: error.message || 'Core API 未连接',
    },
    capability,
  });
}

async function proxyCoreRequest(req, res, capability) {
  try {
    const hasBody = req.method !== 'GET' && req.method !== 'HEAD';
    const result = await coreApi.request(req.originalUrl, {
      method: req.method,
      headers: hasBody ? { 'Content-Type': 'application/json' } : undefined,
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
        res.status(ollamaRes.statusCode).json({
          running: false,
          models: [],
          error: body || `Ollama HTTP ${ollamaRes.statusCode}`,
        });
        return;
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
        res.status(502).json({
          running: false,
          models: [],
          error: `Invalid Ollama response: ${err.message}`,
        });
      }
    });
  });

  ollamaReq.on('error', (err) => {
    res.status(503).json({
      running: false,
      models: [],
      error: err.message,
    });
  });

  ollamaReq.end();
});

app.get('/api/ollama/models', (req, res) => {
  proxyToOllama('/api/tags', res);
});

app.post('/api/ollama/chat', (req, res) => {
  proxyToOllama('/api/chat', res, 'POST', req.body);
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
  const { model = 'default', messages = [] } = req.body || {};
  streamOllamaChat(res, { model, messages });
});

app.get('/api/system/stats', async (req, res) => {
  try {
    res.json(await readSystemStats());
  } catch (err) {
    res.status(500).json({
      error: {
        code: 'SYSTEM_STATS_FAILED',
        message: err.message,
      },
    });
  }
});

app.get('/api/capabilities', async (req, res) => {
  res.json({ core_api: await coreApi.status() });
});

app.post('/api/terminal/execute', async (req, res) => {
  const { command, args = [], timeout = 30 } = req.body;
  if (!command) return res.status(400).json({ error: '缺少 command 参数' });

  try {
    const result = await runPythonScript('kernel/terminal_executor.py', [command, ...args]);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
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

app.get('/api/events', async (req, res) => {
  await proxyCoreRequest(req, res, 'events');
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
  } catch (err) {
    res.status(500).json({ error: err.message });
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
  } catch (err) {
    res.status(500).json({ error: err.message });
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
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

function runGitCommand(args) {
  return new Promise((resolve, reject) => {
    const git = spawn('git', args, { cwd: path.join(__dirname, '..') });
    let stdout = '';
    let stderr = '';
    git.stdout.on('data', (d) => { stdout += d.toString(); });
    git.stderr.on('data', (d) => { stderr += d.toString(); });
    git.on('close', (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(stderr || `git exit ${code}`));
    });
    git.on('error', reject);
  });
}

// ============================================================
app.get('/api/ollama/token-usage', (req, res) => {
  res.json(tokenUsage.snapshot());
});

// ============================================================
// 前端路由 fallback（SPA）— Express v5 修复：sendFile 不再接受回调
// ============================================================
app.get('*path', (req, res) => {
  const indexPath = path.join(distPath, 'index.html');
  if (!fs.existsSync(indexPath)) {
    return res.status(404).json({ error: '前端未构建，请先运行 npm run build' });
  }
  res.sendFile(indexPath);
});

// ============================================================
// 启动
// ============================================================

const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`🤖 J.A.R.V.I.S. Backend 启动: http://0.0.0.0:${PORT}`);
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
