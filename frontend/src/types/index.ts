/**
 * 前端类型定义 — 从 src/types/index.ts 萃取
 * Phase 9: Solid.js Dashboard
 */

export interface OllamaStatus {
  running: boolean;
  version?: string;
  models: Array<{ name: string; size: string }>;
  gpu_available: boolean;
  gpu_name?: string;
}

export interface SystemStats {
  cpu: { usage: number; cores: number; model: string };
  memory: { total: number; used: number; free: number; usage: number };
  disk: { total: number; used: number; free: number; usage: number };
}

export interface WidgetState {
  [key: string]: unknown;
}

export interface IXiaoYiWidget {
  id: string;
  title: string;
  dimensions: {
    minW: number;
    minH: number;
    defaultW: number;
    defaultH: number;
  };
  permissions: Array<'network' | 'system_monitor' | 'llm_access'>;
  render(): string; // Solid.js JSX element
  onRefresh?(): Promise<void>;
  onMount?(): void;
  onUnmount?(): void;
}
