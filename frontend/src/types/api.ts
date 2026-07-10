export type ResourcePhase =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'degraded'
  | 'error';

export interface ApiMeta {
  status: 'ready' | 'degraded';
  source: string;
  unavailable_fields: string[];
}

export interface SystemMetric {
  total: number | null;
  used: number | null;
  free: number | null;
  usage: number | null;
}

export interface SystemStats {
  cpu: {
    usage: number | null;
    cores: number | null;
    model: string | null;
  };
  memory: SystemMetric;
  disk: SystemMetric;
  gpu: Array<{ model?: string; vendor?: string }>;
  meta: ApiMeta;
}

export interface OllamaModel {
  name: string;
  size?: number | string;
  modified_at?: string;
  digest?: string;
}

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

export interface TokenTotals {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface TokenUsageSnapshot {
  latest: TokenSample | null;
  totals: TokenTotals;
  samples: TokenSample[];
  session_started_at: number;
}

export interface GitChangedFile {
  status: string;
  file: string;
  staged: boolean;
}

export interface GitStatus {
  branch: string;
  clean: boolean;
  changedFiles: GitChangedFile[];
  count: number;
}

export interface GitCommit {
  hash: string;
  author: string;
  email: string;
  date: string;
  subject: string;
}

export interface MemoryEntry {
  id: string;
  type: string;
  title: string;
  content: string;
  tags: string[];
  created_at: string;
}

export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  status: string;
  permissions: string[];
}

export interface EventInfo {
  type: string;
  payload: string;
  timestamp: string;
  source: string;
}

export interface CapabilityState {
  configured: boolean;
  available: boolean;
  base_url: string | null;
}

export interface ApiErrorPayload {
  error?: string | {
    code?: string;
    message?: string;
    details?: unknown;
  };
}
