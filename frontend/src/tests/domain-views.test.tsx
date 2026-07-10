import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@solidjs/testing-library';
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import type { JSX } from 'solid-js';
import {
  RuntimeResourcesProvider,
  type RuntimeResources,
} from '../app/runtime-resources';
import { ActivityDock } from '../components/layout/ActivityDock';
import { ToastProvider } from '../components/ui/ToastHost';
import type { PollingResource } from '../primitives/create-polling-resource';
import type {
  CapabilityState,
  GitStatus,
  ResourcePhase,
} from '../types/api';
import { MemoryView } from '../views/MemoryView';
import { PluginsView } from '../views/PluginsView';
import { RepositoryView } from '../views/RepositoryView';

const apiMocks = vi.hoisted(() => ({
  gitLog: vi.fn(),
  memories: vi.fn(),
  storeMemory: vi.fn(),
  plugins: vi.fn(),
  pluginAction: vi.fn(),
  events: vi.fn(),
}));

vi.mock('../services/jarvis-api', () => ({
  jarvisApi: apiMocks,
}));

function fixedResource<T>(
  value: T | undefined,
  phase: ResourcePhase = 'ready',
): PollingResource<T> {
  return {
    data: () => value,
    phase: () => phase,
    error: () => phase === 'error' ? new Error('offline') : undefined,
    updatedAt: () => 1_700_000_000_000,
    refresh: vi.fn(async () => undefined),
  };
}

function createResources(options: {
  git?: GitStatus;
  capability?: CapabilityState;
} = {}): RuntimeResources {
  return {
    system: fixedResource({
      cpu: { usage: 10, cores: 8, model: 'CPU' },
      memory: { total: 100, used: 50, free: 50, usage: 50 },
      disk: { total: 100, used: 20, free: 80, usage: 20 },
      gpu: [],
      meta: { status: 'ready', source: 'test', unavailable_fields: [] },
    }),
    ollama: fixedResource({
      running: true,
      version: '0.5.7',
      models: [],
      gpu_available: false,
    }),
    git: fixedResource(options.git || {
      branch: 'codex/jarvis-command-center',
      clean: false,
      changedFiles: [{
        status: 'M ',
        file: 'frontend/src/App.tsx',
        staged: true,
      }],
      count: 1,
    }),
    tokens: fixedResource({
      latest: null,
      totals: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
      samples: [],
      session_started_at: 1_700_000_000_000,
    }, 'empty'),
    capabilities: fixedResource({
      core_api: options.capability || {
        configured: true,
        available: true,
        base_url: 'http://127.0.0.1:8080',
      },
    }),
  };
}

function renderDomain(component: () => JSX.Element, resources = createResources()) {
  return render(() => (
    <ToastProvider>
      <RuntimeResourcesProvider value={resources}>
        {component()}
      </RuntimeResourcesProvider>
    </ToastProvider>
  ));
}

beforeAll(() => {
  Object.defineProperty(window, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  });
});

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.gitLog.mockResolvedValue({
    commits: [{
      hash: 'abc12345',
      author: 'Codex',
      email: 'codex@example.com',
      date: '2026-07-10T10:00:00+08:00',
      subject: 'feat: command center',
    }],
  });
  apiMocks.memories.mockResolvedValue({
    entries: [
      {
        id: 'memory-1',
        type: 'project',
        title: '部署流程',
        content: '先运行全部测试',
        tags: ['release'],
        created_at: '2026-07-10T10:00:00+08:00',
      },
      {
        id: 'memory-2',
        type: 'user',
        title: '个人偏好',
        content: '使用简体中文',
        tags: ['language'],
        created_at: '2026-07-09T10:00:00+08:00',
      },
    ],
  });
  apiMocks.storeMemory.mockResolvedValue({ success: true, path: '.auto-memory/new.md' });
  apiMocks.plugins.mockResolvedValue({
    plugins: [
      {
        id: 'discovered-plugin',
        name: 'Discovery Plugin',
        version: '1.0.0',
        status: 'discovered',
        permissions: ['events:read'],
      },
      {
        id: 'enabled-plugin',
        name: 'Enabled Plugin',
        version: '2.0.0',
        status: 'enabled',
        permissions: ['memory:read'],
      },
      {
        id: 'disabled-plugin',
        name: 'Disabled Plugin',
        version: '3.0.0',
        status: 'disabled',
        permissions: [],
      },
    ],
  });
  apiMocks.pluginAction.mockResolvedValue({ success: true });
  apiMocks.events.mockResolvedValue({
    events: [
      {
        type: 'plugin.enabled',
        payload: 'enabled-plugin',
        timestamp: '2026-07-10T10:01:00+08:00',
        source: 'plugin-manager',
      },
      {
        type: 'memory.stored',
        payload: 'memory-1',
        timestamp: '2026-07-10T10:00:00+08:00',
        source: 'memory-store',
      },
    ],
  });
});

afterEach(() => cleanup());

describe('RepositoryView', () => {
  it('shows dirty paths, staging state, and read-only commit history', async () => {
    renderDomain(() => <RepositoryView />);

    expect(screen.getByText('codex/jarvis-command-center')).not.toBeNull();
    expect(screen.getByText('1 个文件变更')).not.toBeNull();
    expect(screen.getByText('frontend/src/App.tsx')).not.toBeNull();
    expect(screen.getByText('已暂存')).not.toBeNull();
    expect(await screen.findByText('feat: command center')).not.toBeNull();
    expect(screen.getByText('abc12345')).not.toBeNull();
    expect(screen.queryByRole('button', { name: /提交|暂存|丢弃|切换分支/ })).toBeNull();
  });

  it('renders a clean worktree without a changed-file list', () => {
    const resources = createResources({
      git: {
        branch: 'main',
        clean: true,
        changedFiles: [],
        count: 0,
      },
    });
    renderDomain(() => <RepositoryView />, resources);

    expect(screen.getByText('工作区干净')).not.toBeNull();
    expect(screen.queryByText('frontend/src/App.tsx')).toBeNull();
  });
});

describe('MemoryView', () => {
  it('filters entries and stores a new memory before closing the dialog', async () => {
    renderDomain(() => <MemoryView />);

    expect(await screen.findByText('部署流程')).not.toBeNull();
    expect(screen.getByText('个人偏好')).not.toBeNull();
    fireEvent.input(screen.getByLabelText('搜索记忆'), {
      target: { value: '部署' },
    });
    expect(screen.getByText('部署流程')).not.toBeNull();
    expect(screen.queryByText('个人偏好')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '新建记忆' }));
    fireEvent.input(await screen.findByLabelText('标题'), {
      target: { value: '测试约定' },
    });
    fireEvent.change(screen.getByLabelText('类型'), {
      target: { value: 'project' },
    });
    fireEvent.input(screen.getByLabelText('标签'), {
      target: { value: 'testing, frontend' },
    });
    fireEvent.input(screen.getByLabelText('内容'), {
      target: { value: '提交前运行全部前端测试。' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存记忆' }));

    await waitFor(() => expect(apiMocks.storeMemory).toHaveBeenCalledWith({
      type: 'project',
      title: '测试约定',
      content: '提交前运行全部前端测试。',
      tags: ['testing', 'frontend'],
    }));
    expect(await screen.findByText('记忆已保存')).not.toBeNull();
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(apiMocks.memories.mock.calls.length).toBeGreaterThan(1);
  });

  it('disables memory creation when the Core API is unavailable', () => {
    const resources = createResources({
      capability: {
        configured: false,
        available: false,
        base_url: null,
      },
    });
    renderDomain(() => <MemoryView />, resources);

    expect(screen.getByText('Core API 未连接')).not.toBeNull();
    expect(screen.getByRole<HTMLButtonElement>('button', { name: '新建记忆' }).disabled).toBe(true);
    expect(apiMocks.memories).not.toHaveBeenCalled();
  });
});

describe('PluginsView', () => {
  it('maps lifecycle controls to plugin status and confirms disable', async () => {
    renderDomain(() => <PluginsView />);

    expect(await screen.findByText('Discovery Plugin')).not.toBeNull();
    expect(screen.getByText('discovered-plugin')).not.toBeNull();
    expect(screen.getByText('events:read')).not.toBeNull();
    expect(screen.getByRole('button', { name: '加载 Discovery Plugin' })).not.toBeNull();
    expect(screen.getByRole('button', { name: '启用 Disabled Plugin' })).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '停用 Enabled Plugin' }));
    expect(apiMocks.pluginAction).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: '确认停用' }));
    await waitFor(() => expect(apiMocks.pluginAction).toHaveBeenCalledWith(
      'disable',
      'enabled-plugin',
    ));
  });

  it('shows capability failure instead of a false empty state', () => {
    const resources = createResources({
      capability: {
        configured: false,
        available: false,
        base_url: null,
      },
    });
    renderDomain(() => <PluginsView />, resources);

    expect(screen.getByText('Core API 未连接')).not.toBeNull();
    expect(screen.queryByText('未检测到插件')).toBeNull();
    expect(apiMocks.plugins).not.toHaveBeenCalled();
  });
});

describe('ActivityDock', () => {
  it('shows the newest event and caps expanded history at 100 rows', async () => {
    apiMocks.events.mockResolvedValue({
      events: Array.from({ length: 101 }, (_, index) => ({
        type: index === 100 ? 'newest.event' : `event.${index}`,
        payload: `payload-${index}`,
        timestamp: new Date(1_700_000_000_000 + index * 1000).toISOString(),
        source: index === 100 ? 'newest-source' : 'event-bus',
      })),
    });
    renderDomain(() => <ActivityDock />);

    expect(await screen.findByText('newest.event')).not.toBeNull();
    expect(screen.getByText('newest-source')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '展开活动' }));
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(100));
  });

  it('distinguishes unavailable Core API from an empty event history', () => {
    const resources = createResources({
      capability: {
        configured: false,
        available: false,
        base_url: null,
      },
    });
    renderDomain(() => <ActivityDock />, resources);

    expect(screen.getByText('Core API 未连接')).not.toBeNull();
    expect(screen.queryByText('暂无活动记录')).toBeNull();
    expect(apiMocks.events).not.toHaveBeenCalled();
  });
});
