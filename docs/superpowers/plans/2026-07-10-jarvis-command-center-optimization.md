# J.A.R.V.I.S. Command Center Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved Solid.js daily command center with six functional work views, truthful telemetry, recoverable resource states, responsive desktop/mobile layouts, and end-to-end verification.

**Architecture:** Keep Solid.js/Vite as the frontend and Express as the Dashboard BFF. Move response normalization, SSE parsing, polling, and capability handling into focused modules; expose shared runtime resources through a Solid context; render domain views inside one responsive application shell.

**Tech Stack:** Solid.js 1.9, Vite 6, TypeScript 5.6, Express 5, Vitest 3, `@kobalte/core`, `lucide-solid`, `solid-markdown`, `remark-gfm`, Chart.js 4, `systeminformation`, Playwright.

## Global Constraints

- Preserve Solid.js, Vite, Express, Python HTTPServer, and FastAPI; do not migrate frameworks.
- UI copy is Simplified Chinese; model names, Git identifiers, API names, and code remain English.
- Deliver only the approved graphite dark theme with semantic colors: background `#0A0D10`, rail `#0F1419`, surface `#151B21`, border `#2C353D`, text `#EDF2F4`, muted `#8F9BA5`, accent `#42C8BD`, success `#56C984`, warning `#E6AD54`, error `#EB6975`.
- Desktop navigation is `216px`, desktop status rail is approximately `320px`, medium layout starts below `1280px`, and mobile layout starts below `768px`.
- Do not render random, fixed, inferred, or capability-missing values as real telemetry.
- Do not use `innerHTML` for Dashboard UI or enable raw HTML in Markdown.
- Do not add model deletion, Git mutation, or unrestricted terminal controls.
- New runtime dependencies are limited to `@kobalte/core`, `lucide-solid`, `solid-markdown`, `remark-gfm`, and `systeminformation`; the only new test library is `@playwright/test`.
- Every task follows red-green-refactor, runs the listed focused tests, and ends in an independently reviewable commit.

---

## File Structure

### Server modules

- `frontend/server/system-metrics.js`: read and normalize CPU, memory, disk, and graphics data from `systeminformation`.
- `frontend/server/token-usage.js`: record final Ollama usage frames and return deterministic in-process session snapshots.
- `frontend/server/core-api.js`: classify Python/FastAPI availability and proxy supported Dashboard endpoints.
- `frontend/server.js`: compose Express middleware and routes using the focused server modules.
- `frontend/server.test.js`: black-box BFF tests with mock Ollama and mock core API servers.
- `frontend/server/*.test.js`: pure module tests with injected providers.

### Frontend foundation

- `frontend/src/types/api.ts`: canonical frontend API, resource-state, and domain types.
- `frontend/src/services/jarvis-api.ts`: typed JSON client and domain methods.
- `frontend/src/services/chat-stream.ts`: SSE parser and cancellable chat request.
- `frontend/src/primitives/create-polling-resource.ts`: visibility-aware polling with backoff and stale-data retention.
- `frontend/src/app/runtime-resources.tsx`: one shared system/Ollama/Git/Token/capability resource registry.
- `frontend/src/app/navigation.ts`: six view identifiers, Chinese labels, icons, and mobile priority.

### UI and views

- `frontend/src/components/ui/`: project-styled Kobalte wrappers and stable resource-state components.
- `frontend/src/components/layout/`: Sidebar, Topbar, StatusRail, ActivityDock, MobileNav, and AppShell.
- `frontend/src/views/`: Chat, Runtime, Repository, Models, Memory, and Plugins views.
- `frontend/src/styles/tokens.css`: semantic design tokens.
- `frontend/src/styles/global.css`: reset, body, typography, focus, and reduced-motion rules.
- `frontend/src/styles/components.css`: shell, view, control, resource, and responsive component rules.

### Verification and docs

- `frontend/playwright.config.ts`: deterministic Vite-backed browser configuration.
- `frontend/e2e/command-center.spec.ts`: desktop/mobile layout and interaction checks with API interception.
- `README.md`, `docs/SETUP.md`, `AGENTS.md`, `CHANGELOG.md`, `docs/reports/README.md`, `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/AUDIT_REPORT_93.md`: current commands, architecture, counts, and iteration evidence.

---

### Task 1: Canonical API Types and JSON Client

**Files:**
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/services/jarvis-api.ts`
- Create: `frontend/src/tests/jarvis-api.test.ts`
- Modify: `frontend/src/types/index.ts`

**Interfaces:**
- Produces: `ResourcePhase`, `ApiMeta`, `JarvisApiError`, all domain response interfaces, `requestJson<T>()`, and `jarvisApi`.
- Consumes: existing `/api/health`, `/api/ollama/*`, `/api/system/stats`, `/api/git/*`, `/api/memory/*`, `/api/plugins`, and `/api/events` routes.

- [ ] **Step 1: Write failing JSON-client tests**

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { JarvisApiError, requestJson } from '../services/jarvis-api';

afterEach(() => vi.unstubAllGlobals());

describe('requestJson', () => {
  it('returns typed JSON and forwards AbortSignal', async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"status":"healthy"}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestJson<{ status: string }>('/api/health', { signal }))
      .resolves.toEqual({ status: 'healthy' });
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.objectContaining({ signal }));
  });

  it('turns structured failures into JarvisApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'CORE_API_UNAVAILABLE', message: 'Core API 未连接' },
    }), { status: 503, headers: { 'Content-Type': 'application/json' } })));

    await expect(requestJson('/api/plugins')).rejects.toMatchObject({
      name: 'JarvisApiError', code: 'CORE_API_UNAVAILABLE', status: 503,
    });
  });
});
```

- [ ] **Step 2: Run the focused test and verify red**

Run: `npm --prefix frontend test -- src/tests/jarvis-api.test.ts`

Expected: FAIL because `../services/jarvis-api` does not exist.

- [ ] **Step 3: Define canonical types**

```ts
export type ResourcePhase = 'loading' | 'ready' | 'empty' | 'stale' | 'degraded' | 'error';

export interface ApiMeta {
  status: 'ready' | 'degraded';
  source: string;
  unavailable_fields: string[];
}

export interface SystemStats {
  cpu: { usage: number | null; cores: number | null; model: string | null };
  memory: { total: number | null; used: number | null; free: number | null; usage: number | null };
  disk: { total: number | null; used: number | null; free: number | null; usage: number | null };
  gpu: Array<{ model?: string; vendor?: string }>;
  meta: ApiMeta;
}

export interface OllamaModel { name: string; size?: number | string }
export interface OllamaStatus {
  running: boolean;
  version?: string;
  models: OllamaModel[];
  gpu_available: boolean;
  gpu_name?: string;
}

export interface TokenSample {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  timestamp: number;
}

export interface TokenUsageSnapshot {
  latest: TokenSample | null;
  totals: Omit<TokenSample, 'timestamp'>;
  samples: TokenSample[];
  session_started_at: number;
}

export interface GitStatus {
  branch: string;
  clean: boolean;
  changedFiles: Array<{ status: string; file: string; staged: boolean }>;
  count: number;
}

export interface GitCommit { hash: string; author: string; email: string; date: string; subject: string }
export interface MemoryEntry { id: string; type: string; title: string; content: string; tags: string[]; created_at: string }
export interface PluginInfo { id: string; name: string; version: string; status: string; permissions: string[] }
export interface EventInfo { type: string; payload: string; timestamp: string; source: string }
export interface CapabilityState { configured: boolean; available: boolean; base_url: string | null }
```

Replace `frontend/src/types/index.ts` with re-exports from `./api` plus the still-used multi-agent protocol types; remove the inaccurate synchronous `IXiaoYiWidget.render(): string` declaration.

- [ ] **Step 4: Implement the typed client**

```ts
import type {
  CapabilityState, EventInfo, GitCommit, GitStatus, MemoryEntry,
  OllamaStatus, PluginInfo, SystemStats, TokenUsageSnapshot,
} from '../types/api';

export class JarvisApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = 'JarvisApiError';
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload?.error;
    throw new JarvisApiError(
      error?.message || `请求失败（HTTP ${response.status}）`,
      error?.code || 'HTTP_ERROR',
      response.status,
      error?.details,
    );
  }
  return payload as T;
}

export const jarvisApi = {
  health: (signal?: AbortSignal) => requestJson<{ status: string }>('/api/health', { signal }),
  system: (signal?: AbortSignal) => requestJson<SystemStats>('/api/system/stats', { signal }),
  ollamaStatus: (signal?: AbortSignal) => requestJson<OllamaStatus>('/api/ollama/status', { signal }),
  models: (signal?: AbortSignal) => requestJson<{ models: Array<{ name: string; size?: number | string }> }>('/api/ollama/models', { signal }),
  tokenUsage: (signal?: AbortSignal) => requestJson<TokenUsageSnapshot>('/api/ollama/token-usage', { signal }),
  gitStatus: (signal?: AbortSignal) => requestJson<GitStatus>('/api/git/status', { signal }),
  gitLog: (limit = 20, signal?: AbortSignal) => requestJson<{ commits: GitCommit[] }>(`/api/git/log?limit=${limit}`, { signal }),
  capabilities: (signal?: AbortSignal) => requestJson<{ core_api: CapabilityState }>('/api/capabilities', { signal }),
  memories: (signal?: AbortSignal) => requestJson<{ entries: MemoryEntry[] }>('/api/memory/entries', { signal }),
  storeMemory: (body: { type: string; title: string; content: string; tags: string[] }, signal?: AbortSignal) =>
    requestJson<{ success: boolean; path: string }>('/api/memory/store', { method: 'POST', body: JSON.stringify(body), signal }),
  plugins: (signal?: AbortSignal) => requestJson<{ plugins: PluginInfo[] }>('/api/plugins', { signal }),
  pluginAction: (action: 'load' | 'enable' | 'disable', plugin_id: string, signal?: AbortSignal) =>
    requestJson(`/api/plugins/${action}`, { method: 'POST', body: JSON.stringify({ plugin_id }), signal }),
  events: (limit = 100, signal?: AbortSignal) => requestJson<{ events: EventInfo[] }>(`/api/events?limit=${limit}`, { signal }),
};
```

- [ ] **Step 5: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/jarvis-api.test.ts`

Run: `npm --prefix frontend run typecheck`

Expected: both commands pass.

```powershell
git add frontend/src/types frontend/src/services/jarvis-api.ts frontend/src/tests/jarvis-api.test.ts
git commit -m "feat(frontend): add typed JARVIS API client"
```

### Task 2: Truthful Cross-Platform System Metrics

**Files:**
- Create: `frontend/server/system-metrics.js`
- Create: `frontend/server/system-metrics.test.js`
- Modify: `frontend/server.js`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Produces: `readSystemStats(provider): Promise<SystemStats>`.
- Consumes: `systeminformation.currentLoad()`, `systeminformation.mem()`, `systeminformation.fsSize()`, and `systeminformation.graphics()`.

- [ ] **Step 1: Install the approved metrics dependency**

Run: `npm --prefix frontend install systeminformation`

Expected: `systeminformation` appears in dependencies and the lockfile changes.

- [ ] **Step 2: Write failing normalization tests**

```js
import { describe, expect, test } from 'vitest';
import { readSystemStats } from './system-metrics.js';

test('returns real provider values with ready metadata', async () => {
  const stats = await readSystemStats({
    currentLoad: async () => ({ currentLoad: 17.25, cpus: [{ load: 10 }, { load: 20 }] }),
    cpu: async () => ({ cores: 8, brand: 'Test CPU' }),
    mem: async () => ({ total: 1000, active: 600, available: 400 }),
    fsSize: async () => [{ size: 2000, used: 500 }, { size: 1000, used: 250 }],
    graphics: async () => ({ controllers: [] }),
  });

  expect(stats.cpu).toEqual({ usage: 17.3, cores: 8, model: 'Test CPU' });
  expect(stats.memory).toEqual({ total: 1000, used: 600, free: 400, usage: 60 });
  expect(stats.disk).toEqual({ total: 3000, used: 750, free: 2250, usage: 25 });
  expect(stats.meta).toEqual({ status: 'ready', source: 'systeminformation', unavailable_fields: [] });
});

test('preserves available fields and marks provider failures', async () => {
  const stats = await readSystemStats({
    currentLoad: async () => { throw new Error('cpu unavailable'); },
    cpu: async () => ({ cores: 8, brand: 'Test CPU' }),
    mem: async () => ({ total: 1000, active: 500, available: 500 }),
    fsSize: async () => { throw new Error('disk unavailable'); },
    graphics: async () => ({ controllers: [] }),
  });

  expect(stats.cpu.usage).toBeNull();
  expect(stats.memory.usage).toBe(50);
  expect(stats.disk.usage).toBeNull();
  expect(stats.meta.status).toBe('degraded');
  expect(stats.meta.unavailable_fields).toEqual(['cpu.usage', 'disk']);
});
```

- [ ] **Step 3: Run red test**

Run: `npm --prefix frontend test -- server/system-metrics.test.js`

Expected: FAIL because `system-metrics.js` does not exist.

- [ ] **Step 4: Implement `readSystemStats`**

Use `Promise.allSettled` so one failed source does not erase the other metrics. Round percentages to one decimal, aggregate all `fsSize()` entries, and return `null` for unavailable numeric values. Cache `cpu()` and `graphics()` results for 60 seconds inside the module; do not cache current load, memory, or disk usage.

```js
import si from 'systeminformation';

const round = (value) => Math.round(value * 10) / 10;
const missingUsage = { total: null, used: null, free: null, usage: null };
let hardwareCache = null;
let hardwareExpiresAt = 0;

async function readHardware(provider) {
  if (provider !== si) {
    const [cpu, graphics] = await Promise.all([provider.cpu(), provider.graphics()]);
    return { cpu, graphics };
  }
  if (hardwareCache && Date.now() < hardwareExpiresAt) return hardwareCache;
  const [cpu, graphics] = await Promise.all([provider.cpu(), provider.graphics()]);
  hardwareCache = { cpu, graphics };
  hardwareExpiresAt = Date.now() + 60_000;
  return hardwareCache;
}

export async function readSystemStats(provider = si) {
  const [loadResult, memResult, diskResult, hardwareResult] = await Promise.allSettled([
    provider.currentLoad(), provider.mem(), provider.fsSize(), readHardware(provider),
  ]);
  const unavailable = [];
  const hardware = hardwareResult.status === 'fulfilled' ? hardwareResult.value : null;
  const load = loadResult.status === 'fulfilled' ? loadResult.value : null;
  const mem = memResult.status === 'fulfilled' ? memResult.value : null;
  const disks = diskResult.status === 'fulfilled' ? diskResult.value : null;
  if (!load) unavailable.push('cpu.usage');
  if (!mem) unavailable.push('memory');
  if (!disks?.length) unavailable.push('disk');
  if (!hardware) unavailable.push('hardware');

  const disk = disks?.length ? disks.reduce(
    (sum, item) => ({ total: sum.total + item.size, used: sum.used + item.used }),
    { total: 0, used: 0 },
  ) : null;
  return {
    cpu: { usage: load ? round(load.currentLoad) : null, cores: hardware?.cpu?.cores ?? null, model: hardware?.cpu?.brand ?? null },
    memory: mem ? { total: mem.total, used: mem.active, free: mem.available, usage: round((mem.active / mem.total) * 100) } : missingUsage,
    disk: disk ? { total: disk.total, used: disk.used, free: disk.total - disk.used, usage: round((disk.used / disk.total) * 100) } : missingUsage,
    gpu: hardware?.graphics?.controllers?.map((item) => ({ model: item.model, vendor: item.vendor })) ?? [],
    meta: { status: unavailable.length ? 'degraded' : 'ready', source: 'systeminformation', unavailable_fields: unavailable },
  };
}
```

- [ ] **Step 5: Replace the Express system route**

Remove `spawnSync` and `os` imports from `server.js`, import `readSystemStats`, make `/api/system/stats` async, and return a structured `500` only when the module itself throws outside its settled provider calls.

```js
app.get('/api/system/stats', async (req, res) => {
  try {
    res.json(await readSystemStats());
  } catch (error) {
    res.status(500).json({ error: { code: 'SYSTEM_STATS_FAILED', message: error.message } });
  }
});
```

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- server/system-metrics.test.js server.test.js`

Expected: focused server tests pass and `/api/system/stats` remains reachable.

```powershell
git add frontend/package.json frontend/package-lock.json frontend/server.js frontend/server/system-metrics.js frontend/server/system-metrics.test.js
git commit -m "fix(server): serve truthful system metrics"
```

### Task 3: Deterministic Token Usage from Ollama Final Frames

**Files:**
- Create: `frontend/server/token-usage.js`
- Create: `frontend/server/token-usage.test.js`
- Modify: `frontend/server.js`
- Modify: `frontend/server.test.js`

**Interfaces:**
- Produces: `createTokenUsageStore({ maxSamples, now })` with `recordFrame(frame)` and `snapshot()`.
- Consumes: Ollama frames containing `done`, `prompt_eval_count`, and `eval_count`.

- [ ] **Step 1: Write failing token-store tests**

```js
import { describe, expect, test } from 'vitest';
import { createTokenUsageStore } from './token-usage.js';

test('records only final frames and accumulates deterministic totals', () => {
  let timestamp = 1000;
  const store = createTokenUsageStore({ maxSamples: 2, now: () => timestamp++ });
  store.recordFrame({ done: false, prompt_eval_count: 99, eval_count: 99 });
  store.recordFrame({ done: true, prompt_eval_count: 7, eval_count: 5 });
  store.recordFrame({ done: true, prompt_eval_count: 3, eval_count: 2 });

  expect(store.snapshot()).toMatchObject({
    latest: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
    totals: { prompt_tokens: 10, completion_tokens: 7, total_tokens: 17 },
  });
  expect(store.snapshot().samples).toHaveLength(2);
});
```

- [ ] **Step 2: Run red test**

Run: `npm --prefix frontend test -- server/token-usage.test.js`

Expected: FAIL because `token-usage.js` does not exist.

- [ ] **Step 3: Implement the store**

```js
export function createTokenUsageStore({ maxSamples = 60, now = Date.now } = {}) {
  const sessionStartedAt = now();
  let latest = null;
  let totals = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
  let samples = [];

  return {
    recordFrame(frame) {
      if (!frame?.done) return false;
      const prompt = Number(frame.prompt_eval_count);
      const completion = Number(frame.eval_count);
      if (!Number.isFinite(prompt) || !Number.isFinite(completion)) return false;
      latest = { prompt_tokens: prompt, completion_tokens: completion, total_tokens: prompt + completion, timestamp: now() };
      totals = {
        prompt_tokens: totals.prompt_tokens + prompt,
        completion_tokens: totals.completion_tokens + completion,
        total_tokens: totals.total_tokens + prompt + completion,
      };
      samples = [...samples, latest].slice(-maxSamples);
      return true;
    },
    snapshot() {
      return { latest, totals: { ...totals }, samples: [...samples], session_started_at: sessionStartedAt };
    },
  };
}
```

- [ ] **Step 4: Capture final frames in the SSE proxy**

Create one store at module startup. Replace duplicate line parsing in `streamOllamaChat` with an `emitLine` helper that parses JSON, records the parsed frame, then emits the same SSE data. Process the trailing buffer through the same helper.

```js
const tokenUsage = createTokenUsageStore();
const emitLine = (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  if (trimmed.startsWith('data:')) {
    const payload = trimmed.replace(/^data:\s?/, '');
    if (payload !== '[DONE]') {
      try { tokenUsage.recordFrame(JSON.parse(payload)); } catch { /* Forward malformed upstream data unchanged. */ }
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
```

Replace `/api/ollama/token-usage` with `res.json(tokenUsage.snapshot())`; remove model-count multiplication and all `Math.random()` usage.

- [ ] **Step 5: Extend black-box SSE coverage**

Change the mock Ollama final frame in `server.test.js` to:

```js
res.write(JSON.stringify({ done: true, prompt_eval_count: 7, eval_count: 5 }) + '\n');
```

After the stream test, fetch `/api/ollama/token-usage` and assert `latest.total_tokens === 12`, `totals.total_tokens === 12`, and `samples.length === 1`.

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- server/token-usage.test.js server.test.js`

Expected: token unit tests and the real spawned-server test pass.

```powershell
git add frontend/server.js frontend/server.test.js frontend/server/token-usage.js frontend/server/token-usage.test.js
git commit -m "fix(server): derive token usage from Ollama responses"
```

### Task 4: Core API Capability Detection and Proxying

**Files:**
- Create: `frontend/server/core-api.js`
- Create: `frontend/server/core-api.test.js`
- Modify: `frontend/server.js`
- Modify: `frontend/server.test.js`

**Interfaces:**
- Produces: `createCoreApiClient({ baseUrl, fetchImpl, timeoutMs })` with `status()` and `request(path, init)`.
- Consumes: `JARVIS_CORE_API_URL` and Python/FastAPI `/api/health`, plugins, memory, and events routes.

- [ ] **Step 1: Write failing capability tests**

```js
import { describe, expect, test, vi } from 'vitest';
import { createCoreApiClient } from './core-api.js';

test('distinguishes unconfigured and unavailable core APIs', async () => {
  expect(await createCoreApiClient({ baseUrl: '' }).status()).toEqual({
    configured: false, available: false, base_url: null,
  });
  const client = createCoreApiClient({
    baseUrl: 'http://127.0.0.1:8080',
    fetchImpl: vi.fn().mockRejectedValue(new Error('offline')),
  });
  await expect(client.status()).resolves.toMatchObject({ configured: true, available: false });
});

test('forwards JSON and preserves query strings', async () => {
  const fetchImpl = vi.fn().mockResolvedValue(new Response('{"events":[]}', {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }));
  const client = createCoreApiClient({ baseUrl: 'http://core.local', fetchImpl });
  await expect(client.request('/api/events?limit=20')).resolves.toMatchObject({ status: 200 });
  expect(fetchImpl).toHaveBeenCalledWith('http://core.local/api/events?limit=20', expect.any(Object));
});
```

- [ ] **Step 2: Run red test**

Run: `npm --prefix frontend test -- server/core-api.test.js`

Expected: FAIL because `core-api.js` does not exist.

- [ ] **Step 3: Implement the core client**

Normalize the base URL by removing trailing slashes. For every request, create an `AbortController`, abort after `timeoutMs`, forward `method`, `headers`, and `body`, parse JSON once, and return `{ status, body }`. Throw an error with `code: 'CORE_API_UNAVAILABLE'` for network errors and `code: 'CORE_API_INVALID_RESPONSE'` for non-JSON responses.

```js
export function createCoreApiClient({ baseUrl = '', fetchImpl = fetch, timeoutMs = 3000 } = {}) {
  const normalized = baseUrl.trim().replace(/\/$/, '');
  const request = async (path, init = {}) => {
    if (!normalized) throw Object.assign(new Error('Core API 未配置'), { code: 'CORE_API_NOT_CONFIGURED' });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetchImpl(`${normalized}${path}`, { ...init, signal: controller.signal });
    } catch (error) {
      throw Object.assign(new Error('Core API 未连接'), { code: 'CORE_API_UNAVAILABLE', cause: error });
    } finally {
      clearTimeout(timeout);
    }
    try {
      return { status: response.status, body: await response.json() };
    } catch (error) {
      throw Object.assign(new Error('Core API 返回了无效 JSON'), { code: 'CORE_API_INVALID_RESPONSE', cause: error });
    }
  };
  return {
    request,
    async status() {
      if (!normalized) return { configured: false, available: false, base_url: null };
      try {
        const result = await request('/api/health');
        return { configured: true, available: result.status >= 200 && result.status < 300, base_url: normalized };
      } catch {
        return { configured: true, available: false, base_url: normalized };
      }
    },
  };
}
```

- [ ] **Step 4: Wire Express proxy routes**

Instantiate the client from `process.env.JARVIS_CORE_API_URL || ''`. Add `/api/capabilities`. Replace the stub plugins/events routes and the direct memory script calls with a single route helper. Proxy `GET /api/plugins`, `GET /api/memory/entries`, `POST /api/memory/store`, `GET /api/events`, and `POST /api/plugins/{load,enable,disable}`.

```js
function sendCoreError(res, error, capability) {
  const code = error.code || 'CORE_API_UNAVAILABLE';
  const status = code === 'CORE_API_NOT_CONFIGURED' ? 503 : 502;
  res.status(status).json({ error: { code, message: error.message }, capability });
}
```

Forward the incoming query string, JSON body, and core response status. Do not fall back to `[]` when core is absent.

- [ ] **Step 5: Extend black-box server tests**

Start a third HTTP mock on port `19997`, pass `JARVIS_CORE_API_URL=http://127.0.0.1:19997`, and implement `/api/health`, `/api/plugins`, `/api/memory/entries`, and `/api/events`. Assert `/api/capabilities` reports available and `/api/plugins` returns the mock plugin. In `core-api.test.js`, assert an empty base URL rejects with `CORE_API_NOT_CONFIGURED` and a non-JSON response rejects with `CORE_API_INVALID_RESPONSE`.

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- server/core-api.test.js server.test.js`

Expected: capability, proxy, CORS, SSE, and token tests pass.

```powershell
git add frontend/server.js frontend/server.test.js frontend/server/core-api.js frontend/server/core-api.test.js
git commit -m "feat(server): bridge dashboard core capabilities"
```

### Task 5: Robust Cancellable Chat Stream Client

**Files:**
- Create: `frontend/src/services/chat-stream.ts`
- Create: `frontend/src/tests/chat-stream.test.ts`

**Interfaces:**
- Produces: `streamChat(request, handlers, signal): Promise<void>` and `parseSseEvents(buffer): { events, remainder }`.
- Consumes: POST `/api/ollama/chat/stream` SSE frames.

- [ ] **Step 1: Write failing parser tests**

```ts
import { describe, expect, it, vi } from 'vitest';
import { parseSseEvents, streamChat } from '../services/chat-stream';

it('parses LF, CRLF, and a cross-chunk remainder', () => {
  const parsed = parseSseEvents('data: {"message":{"content":"a"}}\r\n\r\ndata: [DO');
  expect(parsed.events).toEqual(['{"message":{"content":"a"}}']);
  expect(parsed.remainder).toBe('data: [DO');
});

it('emits deltas and stops at DONE', async () => {
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('data: {"message":{"content":"hello"}}\n\n'));
    controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n'));
    controller.close();
  }});
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
  const onDelta = vi.fn();
  await streamChat({ model: 'test', messages: [] }, { onDelta }, new AbortController().signal);
  expect(onDelta).toHaveBeenCalledWith('hello');
});
```

- [ ] **Step 2: Run red test**

Run: `npm --prefix frontend test -- src/tests/chat-stream.test.ts`

Expected: FAIL because `chat-stream.ts` does not exist.

- [ ] **Step 3: Implement parsing and streaming**

`parseSseEvents` splits on `/\r?\n\r?\n/`, keeps the final incomplete segment, extracts every `data:` line, and returns data payload strings. `streamChat` posts JSON, checks `response.ok` and `response.body`, decodes with `{ stream: true }`, parses each event, calls `onDelta` for `frame.message.content`, calls optional `onUsage` for a final usage frame, throws `JarvisApiError` for server `error` frames, and processes the decoder flush plus remaining buffer before returning.

```ts
export interface ChatRequest { model: string; messages: Array<{ role: 'user' | 'assistant'; content: string }> }
export interface ChatHandlers { onDelta(content: string): void; onUsage?(usage: { prompt: number; completion: number }): void }

export function parseSseEvents(buffer: string) {
  const parts = buffer.split(/\r?\n\r?\n/);
  const remainder = parts.pop() ?? '';
  const events = parts.flatMap((part) => part.split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.replace(/^data:\s?/, '').trim()));
  return { events, remainder };
}
```

- [ ] **Step 4: Add abort and failure tests**

Test that an already-aborted signal rejects with `AbortError`, a 503 response throws `JarvisApiError`, and a valid event followed by a malformed JSON event preserves the first delta and throws a parser error with code `INVALID_SSE_FRAME`.

- [ ] **Step 5: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/chat-stream.test.ts`

Run: `npm --prefix frontend run typecheck`

Expected: parser, abort, and type checks pass.

```powershell
git add frontend/src/services/chat-stream.ts frontend/src/tests/chat-stream.test.ts
git commit -m "feat(frontend): add resilient chat stream client"
```

### Task 6: Shared Polling Resources with Stale-Data Retention

**Files:**
- Create: `frontend/src/primitives/create-polling-resource.ts`
- Create: `frontend/src/app/runtime-resources.tsx`
- Create: `frontend/src/tests/polling-resource.test.ts`

**Interfaces:**
- Produces: `createPollingResource<T>(options): PollingResource<T>`, `RuntimeResourcesProvider`, and `useRuntimeResources()`.
- Consumes: `jarvisApi.system`, `ollamaStatus`, `gitStatus`, `tokenUsage`, and `capabilities`.

- [ ] **Step 1: Write failing fake-timer tests**

```ts
import { createRoot } from 'solid-js';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPollingResource } from '../primitives/create-polling-resource';

afterEach(() => vi.useRealTimers());

it('retains the last value and becomes stale after a refresh failure', async () => {
  vi.useFakeTimers();
  const load = vi.fn()
    .mockResolvedValueOnce({ value: 1 })
    .mockRejectedValueOnce(new Error('offline'));

  let dispose = () => undefined;
  const resource = createRoot((rootDispose) => {
    dispose = rootDispose;
    return createPollingResource({ load, intervalMs: 1000, staleAfterMs: 1000 });
  });
  await resource.refresh();
  expect(resource.phase()).toBe('ready');
  await resource.refresh();
  expect(resource.phase()).toBe('stale');
  expect(resource.data()).toEqual({ value: 1 });
  dispose();
});
```

- [ ] **Step 2: Run red test**

Run: `npm --prefix frontend test -- src/tests/polling-resource.test.ts`

Expected: FAIL because the polling primitive does not exist.

- [ ] **Step 3: Implement the polling state machine**

Expose accessors for `data`, `phase`, `error`, `updatedAt`, and `refresh`. Start in `loading`; set `ready` or `empty` after success; set `stale` after a failure when data exists; set `error` when no data exists. Use one recursive `setTimeout`; double the delay after automatic failures up to `maxBackoffMs`; reset after success or manual refresh. Abort the prior request before each new request and on cleanup.

```ts
export interface PollingResource<T> {
  data: Accessor<T | undefined>;
  phase: Accessor<ResourcePhase>;
  error: Accessor<Error | undefined>;
  updatedAt: Accessor<number | undefined>;
  refresh(): Promise<void>;
}

export interface PollingOptions<T> {
  load(signal: AbortSignal): Promise<T>;
  intervalMs: number;
  staleAfterMs: number;
  maxBackoffMs?: number;
  isEmpty?(value: T): boolean;
  enabled?: Accessor<boolean>;
}
```

Register exactly one module-level `visibilitychange` listener that updates a shared `pageVisible` signal. Do not run automatic loads while hidden; run one immediate refresh when visibility returns.

- [ ] **Step 4: Add pause, cancel, and backoff tests**

Use fake timers to prove hidden pages do not invoke `load`, a second refresh aborts the first controller, successful refresh resets backoff, and `isEmpty` produces `empty` rather than `ready`.

- [ ] **Step 5: Implement the runtime resource context**

Create one resource each for system (3s), Ollama (30s), Git (15s), Token (5s), and capabilities (30s). Export a context value with these exact keys. The Provider owns the resources, so Topbar, StatusRail, and views share the same requests.

```ts
export interface RuntimeResources {
  system: PollingResource<SystemStats>;
  ollama: PollingResource<OllamaStatus>;
  git: PollingResource<GitStatus>;
  tokens: PollingResource<TokenUsageSnapshot>;
  capabilities: PollingResource<{ core_api: CapabilityState }>;
}
```

Export `RuntimeResourcesProvider` with an optional `value?: RuntimeResources` prop. Production creates the five resources when `value` is absent; tests pass a complete deterministic value. `useRuntimeResources()` throws a clear error when called outside the Provider.

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/polling-resource.test.ts`

Run: `npm --prefix frontend run typecheck`

Expected: resource state, visibility, cancellation, context types, and backoff tests pass.

```powershell
git add frontend/src/primitives frontend/src/app/runtime-resources.tsx frontend/src/tests/polling-resource.test.ts
git commit -m "feat(frontend): share resilient runtime resources"
```

### Task 7: Design Tokens and Accessible UI Primitives

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/components.css`
- Modify: `frontend/src/styles/global.css`
- Create: `frontend/src/components/ui/IconButton.tsx`
- Create: `frontend/src/components/ui/StatusIndicator.tsx`
- Create: `frontend/src/components/ui/ResourceState.tsx`
- Create: `frontend/src/components/ui/ConfirmDialog.tsx`
- Create: `frontend/src/components/ui/ToastHost.tsx`
- Create: `frontend/src/tests/ui-primitives.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Produces: project-styled primitives consumed by every view and layout component.
- Consumes: Kobalte Tooltip, AlertDialog, Toast and Lucide icon components.

- [ ] **Step 1: Install approved UI dependencies**

Run: `npm --prefix frontend install @kobalte/core lucide-solid`

Expected: both packages appear in runtime dependencies.

- [ ] **Step 2: Write failing accessibility tests**

```tsx
import { fireEvent, render, screen } from '@solidjs/testing-library';
import { describe, expect, it, vi } from 'vitest';
import { RefreshCw } from 'lucide-solid';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { IconButton } from '../components/ui/IconButton';
import { ResourceState } from '../components/ui/ResourceState';

it('gives icon controls an accessible name', () => {
  render(() => <IconButton label="刷新模型" icon={RefreshCw} onClick={() => undefined} />);
  expect(screen.getByRole('button', { name: '刷新模型' })).not.toBeNull();
});

it('confirms destructive actions explicitly', async () => {
  const confirm = vi.fn();
  render(() => <ConfirmDialog title="清空对话？" triggerLabel="清空对话" onConfirm={confirm} />);
  fireEvent.click(screen.getByRole('button', { name: '清空对话' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认清空' }));
  expect(confirm).toHaveBeenCalledOnce();
});

it('renders a retry action for error state', () => {
  render(() => <ResourceState phase="error" title="系统指标不可用" onRetry={() => undefined} />);
  expect(screen.getByRole('button', { name: '重试' })).not.toBeNull();
});
```

- [ ] **Step 3: Run red test**

Run: `npm --prefix frontend test -- src/tests/ui-primitives.test.tsx`

Expected: FAIL because the UI wrappers do not exist.

- [ ] **Step 4: Implement the primitives**

`IconButton` accepts `{ label, icon, onClick, disabled, disabledReason, variant }`, renders a stable `36px` button, uses Kobalte Tooltip for `label` or `disabledReason`, and renders the Lucide component at `18px`. `StatusIndicator` accepts `tone: 'success' | 'warning' | 'error' | 'neutral'` and includes visible text, not color alone. `ResourceState` covers all six phases with stable minimum height; only `error` and `stale` render retry controls. `ConfirmDialog` uses Kobalte AlertDialog and restores focus to its trigger. `ToastHost.tsx` exports `ToastProvider`, `ToastHost`, and `useToast`; the context API is `{ success(message: string): void; error(message: string): void }`.

- [ ] **Step 5: Implement tokens and component rules**

Define every approved color as a CSS variable in `tokens.css`; set `color-scheme: dark`. In `global.css`, remove radial/linear backgrounds, retain the reset, define visible `:focus-visible`, and preserve reduced-motion behavior. In `components.css`, define `.icon-button`, `.status-indicator`, `.resource-state`, `.skeleton`, `.dialog-*`, and `.toast-*` without radius above `8px`.

```css
:root {
  --color-bg: #0a0d10;
  --color-rail: #0f1419;
  --color-surface: #151b21;
  --color-surface-elevated: #1b232b;
  --color-border: #2c353d;
  --color-text: #edf2f4;
  --color-muted: #8f9ba5;
  --color-accent: #42c8bd;
  --color-success: #56c984;
  --color-warning: #e6ad54;
  --color-error: #eb6975;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
}
```

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/ui-primitives.test.tsx`

Run: `npm --prefix frontend run typecheck`

Expected: accessible-name, confirmation, resource state, and type checks pass.

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/components/ui frontend/src/styles frontend/src/tests/ui-primitives.test.tsx
git commit -m "feat(frontend): establish accessible graphite UI system"
```

### Task 8: Functional Chat View

**Files:**
- Create: `frontend/src/views/ChatView.tsx`
- Create: `frontend/src/tests/chat-view.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Produces: `<ChatView />` with model selection, streaming, stop, retry, confirmation, and Markdown/GFM rendering.
- Consumes: `jarvisApi.models`, `streamChat`, Kobalte Select, UI primitives, and Toast context.

- [ ] **Step 1: Install approved Markdown dependencies**

Run: `npm --prefix frontend install solid-markdown remark-gfm`

Expected: both packages appear in runtime dependencies.

- [ ] **Step 2: Write failing view tests**

Mock `jarvisApi.models` and `streamChat`. Test the following exact flow: the model list loads; the first model is selected; entering “检查项目” enables “发送”; clicking “发送” adds the user message and an assistant streaming row; clicking “停止生成” aborts the controller but preserves emitted assistant text; clicking “重试” resubmits the last user message; clicking “清空对话” requires `ConfirmDialog` confirmation.

```tsx
it('stops streaming without deleting generated content', async () => {
  render(() => <ToastProvider><ChatView /></ToastProvider>);
  fireEvent.input(await screen.findByLabelText('消息输入'), { target: { value: '检查项目' } });
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  expect(await screen.findByText('部分响应')).not.toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '停止生成' }));
  expect(screen.getByText('部分响应')).not.toBeNull();
});
```

- [ ] **Step 3: Run red test**

Run: `npm --prefix frontend test -- src/tests/chat-view.test.tsx`

Expected: FAIL because `ChatView.tsx` does not exist.

- [ ] **Step 4: Implement the state machine**

Use signals for `models`, `selectedModel`, `messages`, `input`, `phase`, and `error`; keep the active `AbortController` in a local variable. Derive `canSend` with `createMemo`. `sendMessage(text, historyOverride?)` must append exactly one user row and one assistant row, pass all previous messages to `streamChat`, update only the final assistant row on each delta, and leave partial content in place after non-abort failures. Abort in `onCleanup`.

Render Kobalte Select for models, Lucide `RefreshCw`, `Trash2`, `Square`, `Send`, and `RotateCcw` controls, `SolidMarkdown` with `remarkGfm`, a disabled reason when Ollama has no models, and an `aria-live="polite"` message list. Do not pass or render raw HTML.

- [ ] **Step 5: Add keyboard and Markdown tests**

Prove Enter sends, Shift+Enter preserves a newline, an assistant string containing `` `npm run build` `` renders a `<code>` element, and clearing restores focus to the input.

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/chat-stream.test.ts src/tests/chat-view.test.tsx`

Run: `npm --prefix frontend run typecheck`

Expected: stream and view tests pass.

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/views/ChatView.tsx frontend/src/tests/chat-view.test.tsx
git commit -m "feat(frontend): build controllable local chat workspace"
```

### Task 9: Runtime, Models, and Shared Status Rail

**Files:**
- Create: `frontend/src/views/RuntimeView.tsx`
- Create: `frontend/src/views/ModelsView.tsx`
- Create: `frontend/src/components/layout/StatusRail.tsx`
- Create: `frontend/src/tests/runtime-views.test.tsx`
- Modify: `frontend/src/components/ChartWidget.tsx`

**Interfaces:**
- Produces: runtime detail view, model inventory view, and cross-view status rail.
- Consumes: `useRuntimeResources()`, `ResourceState`, `StatusIndicator`, `IconButton`, and Chart.js.

- [ ] **Step 1: Write failing resource-view tests**

Wrap the views in `<RuntimeResourcesProvider value={resources}>` with ready, degraded, and error resources. Assert RuntimeView renders CPU, memory, disk, the “当前服务会话” Token label, and degraded field text; ModelsView lists models and uses “未检测到本地模型” only for a successful empty list; StatusRail renders the same resource timestamps and exposes a named refresh button.

- [ ] **Step 2: Run red test**

Run: `npm --prefix frontend test -- src/tests/runtime-views.test.tsx`

Expected: FAIL because the views and status rail do not exist.

- [ ] **Step 3: Refine ChartWidget**

Replace `any` chart references with `Chart<'line'> | null`, accept nullable data by filtering unavailable samples, use the graphite tokens for axes/tooltips, and expose `aria-label={props.title}` on the canvas container. Keep `animation: false`; destroy the chart in `onCleanup`.

- [ ] **Step 4: Implement RuntimeView**

Render a page heading, three stable metric cells, memory/disk byte details, resource metadata, and separate CPU/memory/disk charts only when each metric exists. Render Token latest/totals/samples from the shared token resource, label totals “当前服务会话”, and show the empty state “尚无模型调用记录” when `latest` is null.

- [ ] **Step 5: Implement ModelsView and StatusRail**

ModelsView shows Ollama online/offline, version, runtime, GPU name, installed model count, size formatting, and last refresh. StatusRail shows compact System, Ollama, Git, and Token summaries without nesting cards; each section uses its resource phase and one refresh action. It never converts `null` usage into `0%`.

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/runtime-views.test.tsx`

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Expected: component tests, strict types, and production bundle pass.

```powershell
git add frontend/src/views/RuntimeView.tsx frontend/src/views/ModelsView.tsx frontend/src/components/layout/StatusRail.tsx frontend/src/components/ChartWidget.tsx frontend/src/tests/runtime-views.test.tsx
git commit -m "feat(frontend): add truthful runtime and model views"
```

### Task 10: Repository, Memory, Plugin, and Activity Views

**Files:**
- Create: `frontend/src/views/RepositoryView.tsx`
- Create: `frontend/src/views/MemoryView.tsx`
- Create: `frontend/src/views/PluginsView.tsx`
- Create: `frontend/src/components/layout/ActivityDock.tsx`
- Create: `frontend/src/tests/domain-views.test.tsx`

**Interfaces:**
- Produces: three remaining domain views and a collapsible event/activity surface.
- Consumes: `jarvisApi.gitLog`, `memories`, `storeMemory`, `plugins`, `pluginAction`, `events`, and capabilities.

- [ ] **Step 1: Write failing domain-view tests**

Test RepositoryView with clean and dirty worktrees; MemoryView with available entries, search filtering, and a successful store action; PluginsView with available plugins and with `CORE_API_NOT_CONFIGURED`; ActivityDock with events and unavailable core API. Assert unavailable capability text is “Core API 未连接” and is not an empty-list message.

- [ ] **Step 2: Run red test**

Run: `npm --prefix frontend test -- src/tests/domain-views.test.tsx`

Expected: FAIL because the views do not exist.

- [ ] **Step 3: Implement RepositoryView**

Use shared Git status plus one view-local `gitLog` request. Render branch, clean/dirty status, staged flags, changed paths, commit hash/subject/author/date, retry state, and refresh time. Keep all actions read-only; do not add stage, commit, checkout, or discard controls.

- [ ] **Step 4: Implement MemoryView**

Use a view-owned polling resource enabled only while mounted. Derive filtered entries from `query`, `type`, and `tags` with `createMemo`. Provide a Kobalte Dialog form with title, type, tags, and content; submit through `storeMemory`, show Toast success/error, close only on success, and immediately refresh the list.

- [ ] **Step 5: Implement PluginsView and ActivityDock**

PluginsView renders id, name, version, status, and permissions. When the Core API is available, render `load` for discovered plugins, `enable` for loaded or disabled plugins, and `disable` for enabled plugins; require confirmation for disable. When Core API is unavailable, render no lifecycle controls. ActivityDock uses Kobalte Collapsible, displays the newest event timestamp/type/source, caps visible events at 100, and renders capability errors distinctly from a successful empty history.

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/domain-views.test.tsx`

Run: `npm --prefix frontend run typecheck`

Expected: repository, memory, plugin, event, and capability-state tests pass.

```powershell
git add frontend/src/views/RepositoryView.tsx frontend/src/views/MemoryView.tsx frontend/src/views/PluginsView.tsx frontend/src/components/layout/ActivityDock.tsx frontend/src/tests/domain-views.test.tsx
git commit -m "feat(frontend): add repository memory and plugin workspaces"
```

### Task 11: Responsive Application Shell and Six-View Navigation

**Files:**
- Create: `frontend/src/app/navigation.ts`
- Create: `frontend/src/components/layout/Sidebar.tsx`
- Create: `frontend/src/components/layout/Topbar.tsx`
- Create: `frontend/src/components/layout/MobileNav.tsx`
- Create: `frontend/src/components/layout/AppShell.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/tests/app-shell.test.tsx`
- Modify: `frontend/src/styles/components.css`

**Interfaces:**
- Produces: the approved task-first shell and functional primary navigation.
- Consumes: all six views, RuntimeResourcesProvider, ToastProvider, StatusRail, and ActivityDock.

- [ ] **Step 1: Write failing navigation tests**

Render `App` with API requests mocked. Assert the six desktop navigation buttons have Chinese accessible names; clicking “运行监控” displays its `h1`; clicking “插件与工具” displays its `h1`; only one main view exists at a time; the active button has `aria-current="page"`; the mobile “更多” control opens access to Models, Memory, and Plugins.

- [ ] **Step 2: Run red test**

Run: `npm --prefix frontend test -- src/tests/app-shell.test.tsx`

Expected: FAIL because current navigation never changes view.

- [ ] **Step 3: Define navigation metadata**

```ts
import { Bot, Boxes, GitBranch, MemoryStick, MessageSquare, MonitorActivity } from 'lucide-solid';

export type ViewId = 'chat' | 'runtime' | 'repository' | 'models' | 'memory' | 'plugins';
export const navigation = [
  { id: 'chat', label: '对话', icon: MessageSquare, mobile: 'primary' },
  { id: 'runtime', label: '运行监控', icon: MonitorActivity, mobile: 'primary' },
  { id: 'repository', label: '代码仓库', icon: GitBranch, mobile: 'primary' },
  { id: 'models', label: '本地模型', icon: Bot, mobile: 'more' },
  { id: 'memory', label: '记忆', icon: MemoryStick, mobile: 'more' },
  { id: 'plugins', label: '插件与工具', icon: Boxes, mobile: 'more' },
] as const;
```

- [ ] **Step 4: Implement shell composition**

`App` owns `activeView` and renders lazy imports through a `Switch`. Wrap AppShell with RuntimeResourcesProvider and ToastProvider. Sidebar is `216px` above `1280px`, icon-only between `768px` and `1279px`, and absent below `768px`. StatusRail is approximately `320px` on desktop, collapsible at medium width, and opens in a Kobalte Dialog drawer on mobile. MobileNav stays below content without covering the composer. Topbar shows the current view title, a derived overall health indicator, and the clock.

- [ ] **Step 5: Implement responsive CSS**

Use explicit grid tracks and `minmax(0, 1fr)`. Set shell height to `100dvh`; make only view content scroll; reserve ActivityDock and MobileNav heights. Add media queries at exactly `1279px` and `767px`. Add tests that CSS contains stable navigation/status widths and that DOM order is Sidebar, main, StatusRail on desktop.

- [ ] **Step 6: Verify and commit**

Run: `npm --prefix frontend test -- src/tests/app-shell.test.tsx`

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Expected: all six views are reachable, strict types pass, and Vite emits lazy view chunks.

```powershell
git add frontend/src/app/navigation.ts frontend/src/components/layout frontend/src/App.tsx frontend/src/main.tsx frontend/src/styles/components.css frontend/src/tests/app-shell.test.tsx
git commit -m "feat(frontend): ship responsive command center shell"
```

### Task 12: Remove Legacy Dashboard Paths and Consolidate Tests

**Files:**
- Delete: `frontend/src/components/ChatWidget.tsx`
- Delete: `frontend/src/components/GitWidget.tsx`
- Delete: `frontend/src/components/OllamaMonitorWidget.tsx`
- Delete: `frontend/src/components/SystemMonitorWidget.tsx`
- Delete: `frontend/src/components/TokenWidget.tsx`
- Delete: `frontend/src/components/GithubIntelligenceWidget.tsx`
- Delete: `frontend/src/components/TokenUsageDashboardWidget.tsx`
- Delete: `frontend/src/components/WidgetContainer.tsx`
- Delete: `frontend/src/core/brain/github-dashboard-widget.ts`
- Delete: `frontend/src/core/brain/token-usage-widget.ts`
- Delete: `frontend/src/widget-engine/base-widget.ts`
- Delete: `frontend/src/styles/widget.css`
- Delete: `frontend/src/tests/widgets.test.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: one Solid component path with no Dashboard `innerHTML` rendering or duplicate widget contracts.
- Consumes: the six new views and consolidated styles.

- [ ] **Step 1: Add a failing source guard**

Create a test in `frontend/src/tests/app-shell.test.tsx` that reads non-test frontend source through `import.meta.glob(['../**/*.{ts,tsx}', '!../tests/**'], { query: '?raw', import: 'default', eager: true })` and asserts no Dashboard source contains `.innerHTML =`, `class GithubDashboardWidget`, `class TokenUsageWidget`, or letter-only refresh/clear controls.

- [ ] **Step 2: Run the guard and verify red**

Run: `npm --prefix frontend test -- src/tests/app-shell.test.tsx`

Expected: FAIL on the legacy wrappers and widget classes.

- [ ] **Step 3: Delete legacy files and imports**

Remove the listed files, remove `widget.css` from `main.tsx`, remove the obsolete widget exports from `types/index.ts`, and verify no imports reference the deleted modules.

- [ ] **Step 4: Search and verify**

Run: `rg -n "innerHTML|GithubDashboardWidget|TokenUsageWidget|ChatWidget|class=\"icon-button\"[^>]*>\s*[RC]\s*<" frontend/src`

Expected: no matches.

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Expected: the complete frontend suite, strict typecheck, and production build pass.

- [ ] **Step 5: Commit**

```powershell
git add -A frontend/src
git commit -m "refactor(frontend): remove legacy dashboard widgets"
```

### Task 13: Deterministic Playwright Browser Verification

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/command-center.spec.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `npm run test:e2e` with deterministic API interception and desktop/mobile projects.
- Consumes: Vite dev server and the finished application shell.

- [ ] **Step 1: Install Playwright and add scripts**

Run: `npm --prefix frontend install -D @playwright/test`

Run: `npm --prefix frontend exec playwright install chromium`

Add scripts:

```json
"test:e2e": "playwright test",
"test:e2e:headed": "playwright test --headed"
```

Ignore `frontend/test-results/`, `frontend/playwright-report/`, and `.test-*.png`.

- [ ] **Step 2: Write the failing browser test**

Configure one Chromium project and run the same test at `1440x900` and `390x844`. Intercept every `/api` route with deterministic responses. The chat SSE response must contain one assistant delta and a final usage frame.

```ts
test('loads and navigates the daily command center', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') errors.push(message.text());
  });
  await page.goto('/');
  await expect(page).toHaveTitle(/J\.A\.R\.V\.I\.S\./);
  await expect(page.getByRole('heading', { name: '指挥中心' })).toBeVisible();
  await page.getByRole('button', { name: '运行监控' }).click();
  await expect(page.getByRole('heading', { name: '运行监控' })).toBeVisible();
  expect(errors).toEqual([]);
});
```

Add a chat test that sends a prompt and observes assistant text; add a mobile test that opens “更多”, enters “记忆”, returns to “对话”, and checks `document.documentElement.scrollWidth === document.documentElement.clientWidth`.

At the end of each viewport test, write a screenshot to `testInfo.outputPath('command-center.png')`. Keep Playwright output ignored and use the resulting desktop/mobile images as QA evidence before cleanup.

- [ ] **Step 3: Run red browser test**

Run: `npm --prefix frontend run test:e2e`

Expected: FAIL until selectors, routing, or API mocks exactly match the implemented UI.

- [ ] **Step 4: Align test IDs and API fixtures without weakening assertions**

Fix accessible names or deterministic fixtures in application code and the test. Do not replace role/name assertions with broad CSS selectors. Ensure no screenshot, trace, or report is committed.

- [ ] **Step 5: Verify and commit**

Run: `npm --prefix frontend run test:e2e`

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Expected: browser, component, server, type, and build checks pass.

```powershell
git add .gitignore frontend/package.json frontend/package-lock.json frontend/playwright.config.ts frontend/e2e
git commit -m "test(frontend): verify command center in browser"
```

### Task 14: Documentation, Iteration 93 Ledger, and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/SETUP.md`
- Modify: `AGENTS.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_93.md`
- Delete: `docs/reports/AUDIT_REPORT_83.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_docs_setup.py`
- Modify: `tests/test_iteration_ledger.py`

**Interfaces:**
- Produces: reproducible startup/verification docs and a consistent 84-93 rolling audit window.
- Consumes: final test counts and commands from this implementation.

- [ ] **Step 1: Extend documentation guards before changing docs**

Add assertions that `docs/SETUP.md` documents `JARVIS_CORE_API_URL`, `npm run test:e2e`, and Chromium installation; assert the report index names Iteration 93 and the audit range `84-93`.

```py
def test_documents_core_api_and_browser_verification(self):
    self.assertIn("JARVIS_CORE_API_URL", self.text)
    self.assertIn("npm run test:e2e", self.text)
    self.assertIn("playwright install chromium", self.text)
```

- [ ] **Step 2: Run doc guards and verify red**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_docs_setup tests.test_iteration_ledger`

Expected: FAIL because Iteration 93 and new setup commands are not documented.

- [ ] **Step 3: Update current documentation**

Document the six views, Express BFF, `JARVIS_CORE_API_URL=http://127.0.0.1:8080`, dependency installation, Vite/Express startup, Playwright browser installation, and the full verification commands. Refresh source/test counts from `rg --files` and actual test output; do not copy counts from the design spec.

- [ ] **Step 4: Create Iteration 93 evidence and roll history**

Create `AUDIT_REPORT_93.md` with exact H1, Iteration, Date, Status, user-visible changes, files changed, and a verification table. Add Iteration 93 to the top of `CHANGELOG.md`, include every changed top-level scope, and record the actual `tests/run_all.py` count. Remove the complete Iteration 83 changelog entry and `AUDIT_REPORT_83.md`. Update the report index to latest 93 and range 84-93.

- [ ] **Step 5: Run the full fresh verification matrix**

Run each command separately and record its exact result:

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests
cd frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
```

Expected: every command exits `0`; the two browser viewports complete; no framework overlay or relevant console error/warning appears.

- [ ] **Step 6: Update evidence with actual counts and re-run guards**

Replace provisional test counts in Iteration 93 docs with the fresh results, then run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_docs_setup tests.test_iteration_ledger tests.test_readme
git diff --check
```

Expected: documentation guards pass and `git diff --check` reports no errors.

- [ ] **Step 7: Commit the verified delivery**

```powershell
git add README.md docs/SETUP.md AGENTS.md docs/reports CHANGELOG.md tests/test_docs_setup.py tests/test_iteration_ledger.py
git commit -m "docs: record Iteration 93 command center delivery"
```

---

## Spec Coverage Matrix

| Approved requirement | Implemented by |
|---|---|
| Six real primary views | Tasks 8-11 |
| Graphite UI, Kobalte, Lucide, accessible controls | Task 7 |
| Desktop, medium, and mobile task-first layout | Tasks 11 and 13 |
| Typed API boundary and six resource phases | Tasks 1 and 6 |
| Real CPU, memory, disk, and Token data | Tasks 2, 3, and 9 |
| Core API capability distinction and proxy | Tasks 4 and 10 |
| Cancellable/retryable SSE chat | Tasks 5 and 8 |
| No Dashboard `innerHTML` or letter icons | Tasks 7 and 12 |
| Lazy views and scoped Chart.js work | Tasks 9 and 11 |
| Unit, component, server, browser, Python, build checks | Tasks 1-14 |
| Documentation and rolling iteration evidence | Task 14 |
