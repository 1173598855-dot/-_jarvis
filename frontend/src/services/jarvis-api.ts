import type {
  ApiErrorPayload,
  CapabilityState,
  EventInfo,
  GitCommit,
  GitStatus,
  MemoryEntry,
  OllamaModel,
  OllamaStatus,
  PluginInfo,
  SystemStats,
  TokenUsageSnapshot,
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

function errorDetails(payload: ApiErrorPayload, status: number) {
  if (typeof payload.error === 'string') {
    return {
      code: 'HTTP_ERROR',
      message: payload.error,
      details: undefined,
    };
  }

  return {
    code: payload.error?.code || 'HTTP_ERROR',
    message: payload.error?.message || `请求失败（HTTP ${status}）`,
    details: payload.error?.details,
  };
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  });
  const payload = await response.json().catch(() => ({})) as T & ApiErrorPayload;

  if (!response.ok) {
    const error = errorDetails(payload, response.status);
    throw new JarvisApiError(
      error.message,
      error.code,
      response.status,
      error.details,
    );
  }

  return payload;
}

export const jarvisApi = {
  health: (signal?: AbortSignal) =>
    requestJson<{ status: string }>('/api/health', { signal }),

  system: (signal?: AbortSignal) =>
    requestJson<SystemStats>('/api/system/stats', { signal }),

  ollamaStatus: (signal?: AbortSignal) =>
    requestJson<OllamaStatus>('/api/ollama/status', { signal }),

  models: (signal?: AbortSignal) =>
    requestJson<{ models: OllamaModel[] }>('/api/ollama/models', { signal }),

  tokenUsage: (signal?: AbortSignal) =>
    requestJson<TokenUsageSnapshot>('/api/ollama/token-usage', { signal }),

  gitStatus: (signal?: AbortSignal) =>
    requestJson<GitStatus>('/api/git/status', { signal }),

  gitLog: (limit = 20, signal?: AbortSignal) =>
    requestJson<{ commits: GitCommit[] }>(`/api/git/log?limit=${limit}`, { signal }),

  capabilities: (signal?: AbortSignal) =>
    requestJson<{ core_api: CapabilityState }>('/api/capabilities', { signal }),

  memories: (signal?: AbortSignal) =>
    requestJson<{ entries: MemoryEntry[] }>('/api/memory/entries', { signal }),

  storeMemory: (
    body: { type: string; title: string; content: string; tags: string[] },
    signal?: AbortSignal,
  ) => requestJson<{ success: boolean; path: string; id: string; type: string }>('/api/memory/store', {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  }),

  plugins: (signal?: AbortSignal) =>
    requestJson<{ plugins: PluginInfo[] }>('/api/plugins', { signal }),

  pluginAction: (
    action: 'load' | 'enable' | 'disable',
    plugin_id: string,
    signal?: AbortSignal,
  ) => requestJson<Record<string, unknown>>(`/api/plugins/${action}`, {
    method: 'POST',
    body: JSON.stringify({ plugin_id }),
    signal,
  }),

  events: (limit = 100, signal?: AbortSignal) =>
    requestJson<{ events: EventInfo[] }>(`/api/events?limit=${limit}`, { signal }),
};
