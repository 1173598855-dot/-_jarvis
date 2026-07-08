/**
 * 小奕 J.A.R.V.I.S. — 核心类型定义
 * @core/types
 */

// ============================================================
// IXiaoYiWidget — Widget 统一接口契约
// ============================================================
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
  render(): JSX.Element;
  onRefresh(): Promise<void>;
}

// ============================================================
// Agent 消息类型
// ============================================================
export interface AgentMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  metadata?: Record<string, unknown>;
}

export interface AgentTask {
  id: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  result?: unknown;
  error?: string;
  createdAt: number;
  completedAt?: number;
}

// ============================================================
// 记忆系统类型
// ============================================================
export interface MemoryEntry {
  id: string;
  type: 'user' | 'feedback' | 'project' | 'reference';
  content: string;
  metadata: Record<string, unknown>;
  createdAt: number;
  lastAccessed: number;
  accessCount: number;
}

export interface MemoryIndex {
  entries: MemoryEntry[];
  lastConsolidated: number;
  totalEntries: number;
}

// ============================================================
// Skill 系统类型
// ============================================================
export interface SkillManifest {
  name: string;
  version: string;
  description: string;
  author?: string;
  permissions: string[];
  denied: string[];
  runtime: 'python' | 'node' | 'rust';
  sandbox: boolean;
  dependencies?: string[];
  triggers?: string[];
}

export interface SkillExecutionResult {
  success: boolean;
  output?: unknown;
  error?: string;
  duration: number;
}

// ============================================================
// Plugin 沙箱类型
// ============================================================
export interface PluginManifest extends SkillManifest {
  entryPoint: string;
  apiVersion: string;
}

export interface SandboxConfig {
  runtime: 'uv' | 'venv' | 'worker_threads' | 'vm2';
  permissions: string[];
  deniedApis: string[];
  timeout: number;
  memoryLimit: string;
}

// ============================================================
// 终端执行器类型（萃取自 Open Interpreter）
// ============================================================
export interface TerminalCommand {
  id: string;
  command: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  timeout?: number;
}

export interface TerminalResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  duration: number;
  success: boolean;
}

export interface TerminalExecutorConfig {
  allowedCommands: string[];
  deniedCommands: string[];
  sandbox: boolean;
  maxConcurrency: number;
  defaultTimeout: number;
}

// ============================================================
// 记忆向量化类型（萃取自 Mem0）
// ============================================================
export interface VectorMemoryConfig {
  provider: 'ollama' | 'openai' | 'local';
  model: string;
  dimension: number;
  collectionName: string;
}

export interface VectorEntry {
  id: string;
  text: string;
  vector: number[];
  metadata: Record<string, unknown>;
  userId?: string;
  agentId?: string;
}

export interface SearchResult {
  entry: VectorEntry;
  score: number;
}

// ============================================================
// Ollama 管理器类型（萃取自 AnythingLLM）
// ============================================================
export interface OllamaModel {
  name: string;
  size: string;
  digest: string;
  modifiedAt: string;
  details?: {
    format: string;
    family: string;
    parameterSize: string;
    quantizationLevel: string;
  };
}

export interface OllamaConfig {
  baseUrl: string;
  defaultModel: string;
  timeout: number;
  stream: boolean;
}

export interface OllamaChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface OllamaChatResponse {
  model: string;
  message: OllamaChatMessage;
  done: boolean;
  totalDuration?: number;
  evalCount?: number;
}

// ============================================================
// 系统监控类型
// ============================================================
export interface SystemStats {
  cpu: {
    usage: number;
    cores: number;
    model: string;
  };
  memory: {
    total: number;
    used: number;
    free: number;
    usage: number;
  };
  disk: {
    total: number;
    used: number;
    free: number;
    usage: number;
  };
  network: {
    interfaces: Array<{
      name: string;
      ip: string;
      status: 'up' | 'down';
    }>;
  };
}

export interface OllamaStatus {
  running: boolean;
  version?: string;
  models: OllamaModel[];
  gpu: {
    available: boolean;
    name?: string;
    memory?: number;
  };
}

// ============================================================
// 设计令牌类型
// ============================================================
export interface DesignTokens {
  colors: {
    canvas: string;
    card: string;
    cardAlpha: number;
    highlight: string;
    secondary: string;
    border: string;
    success: string;
    warning: string;
    danger: string;
  };
  blur: {
    md: number;
    lg: number;
    xl: number;
  };
  transitions: {
    fast: number;
    slow: number;
  };
  typography: {
    fontFamily: string;
    fontSize: {
      xs: string;
      sm: string;
      base: string;
      lg: string;
      xl: string;
      '2xl': string;
    };
  };
}

// ============================================================
// 演进进度类型
// ============================================================
export interface EvolutionMetrics {
  iteration: number;
  timestamp: number;
  scores: {
    maintainability: number;
    extensibility: number;
    performance: number;
    security: number;
  };
  techDebt: number;
  testCoverage: number;
  widgetCount: number;
  skillCount: number;
}

export interface AuditReport {
  iteration: number;
  timestamp: string;
  status: 'healthy' | 'warning' | 'critical';
  summary: string;
  githubLearnings: Array<{
    project: string;
    url: string;
    stars: number;
    extracted: string;
  }>;
  security: {
    astScans: number;
    blockedRisks: number;
    sandboxSkills: number;
    rollbacks: number;
  };
  ui: {
    fps: number;
    memory: number;
    widgets: number;
  };
  tests: {
    unitCoverage: number;
    integrationPassRate: number;
    bugsFixed: number;
  };
  nextLoop: string[];
}
