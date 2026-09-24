import {
  cleanup,
  fireEvent,
  render,
  screen,
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
import {
  RuntimeResourcesProvider,
  type RuntimeResources,
} from '../app/runtime-resources';
import { StatusRail } from '../components/layout/StatusRail';
import { ChartWidget } from '../components/ChartWidget';
import type { PollingResource } from '../primitives/create-polling-resource';
import type { OllamaStatus, ResourcePhase } from '../types/api';
import { ModelsView } from '../views/ModelsView';
import { RuntimeView } from '../views/RuntimeView';

const chartMocks = vi.hoisted(() => ({
  configs: [] as Array<{
    data: {
      labels: string[];
      datasets: Array<{ data: Array<number | null> }>;
    };
  }>,
  destroy: vi.fn(),
  update: vi.fn(),
}));

vi.mock('chart.js', () => {
  class ChartMock {
    static register() {}

    data: {
      labels: string[];
      datasets: Array<{ data: Array<number | null> }>;
    };

    constructor(_context: unknown, config: (typeof chartMocks.configs)[number]) {
      chartMocks.configs.push(config);
      this.data = config.data;
    }

    update = chartMocks.update;
    destroy = chartMocks.destroy;
  }

  const component = {};
  return {
    CategoryScale: component,
    Filler: component,
    Legend: component,
    LinearScale: component,
    LineController: component,
    LineElement: component,
    PointElement: component,
    Tooltip: component,
    Chart: ChartMock,
  };
});

const UPDATED_AT = 1_700_000_000_000;

function fixedResource<T>(
  value: T | undefined,
  phase: ResourcePhase = 'ready',
  updatedAt = UPDATED_AT,
) {
  const refresh = vi.fn(async () => undefined);
  const resource: PollingResource<T> = {
    data: () => value,
    phase: () => phase,
    error: () => phase === 'error' ? new Error('offline') : undefined,
    updatedAt: () => updatedAt,
    refresh,
  };
  return { resource, refresh };
}

function readyResources() {
  const system = fixedResource({
    cpu: { usage: 17.4, cores: 16, model: 'Test CPU' },
    memory: {
      total: 32 * 1024 ** 3,
      used: 20 * 1024 ** 3,
      free: 12 * 1024 ** 3,
      usage: 62.5,
    },
    disk: {
      total: 1024 ** 4,
      used: 512 * 1024 ** 3,
      free: 512 * 1024 ** 3,
      usage: 50,
    },
    gpu: [{ model: 'RTX 4090', vendor: 'NVIDIA' }],
    meta: {
      status: 'ready' as const,
      source: 'systeminformation',
      unavailable_fields: [],
    },
  });
  const ollama = fixedResource({
    running: true,
    version: '0.5.7',
    models: [
      { name: 'qwen2.5:7b', size: 4_700_000_000 },
      { name: 'deepseek-r1:8b', size: 5_100_000_000 },
    ],
    gpu_available: true,
    gpu_name: 'RTX 4090',
  });
  const git = fixedResource({
    branch: 'codex/jarvis-command-center',
    clean: false,
    changedFiles: [{ status: 'M', file: 'frontend/src/App.tsx', staged: false }],
    count: 1,
  });
  const tokens = fixedResource({
    latest: {
      prompt_tokens: 12,
      completion_tokens: 18,
      total_tokens: 30,
      timestamp: UPDATED_AT,
    },
    totals: {
      prompt_tokens: 20,
      completion_tokens: 28,
      total_tokens: 48,
    },
    samples: [{
      prompt_tokens: 12,
      completion_tokens: 18,
      total_tokens: 30,
      timestamp: UPDATED_AT,
    }],
    session_started_at: UPDATED_AT - 60_000,
  });
  const capabilities = fixedResource({
    core_api: {
      configured: true,
      available: true,
      base_url: 'http://127.0.0.1:8080',
    },
  });

  const resources: RuntimeResources = {
    system: system.resource,
    ollama: ollama.resource,
    git: git.resource,
    tokens: tokens.resource,
    capabilities: capabilities.resource,
  };

  return {
    resources,
    refresh: {
      system: system.refresh,
      ollama: ollama.refresh,
      git: git.refresh,
      tokens: tokens.refresh,
    },
  };
}

function renderWithResources(
  component: () => ReturnType<typeof RuntimeView>,
  resources: RuntimeResources,
) {
  return render(() => (
    <RuntimeResourcesProvider value={resources}>
      {component()}
    </RuntimeResourcesProvider>
  ));
}

beforeAll(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    {} as CanvasRenderingContext2D,
  );
});

beforeEach(() => {
  chartMocks.configs.length = 0;
  chartMocks.destroy.mockClear();
  chartMocks.update.mockClear();
});

afterEach(() => cleanup());

describe('RuntimeView', () => {
  it('renders truthful system metrics and current service-session tokens', () => {
    const { resources } = readyResources();
    renderWithResources(() => <RuntimeView />, resources);

    expect(screen.getByTestId('runtime-metric-cpu').textContent).toContain('17.4%');
    expect(screen.getByTestId('runtime-metric-memory').textContent).toContain('62.5%');
    expect(screen.getByTestId('runtime-metric-disk').textContent).toContain('50.0%');
    expect(screen.getByText('当前服务会话')).not.toBeNull();
    expect(screen.getByText('48')).not.toBeNull();
  });

  it('names unavailable fields without turning them into percentages', () => {
    const fixture = readyResources();
    const stats = fixture.resources.system.data()!;
    fixture.resources.system = fixedResource({
      ...stats,
      cpu: { ...stats.cpu, usage: null },
      disk: { total: null, used: null, free: null, usage: null },
      meta: {
        ...stats.meta,
        status: 'degraded' as const,
        unavailable_fields: ['cpu.usage', 'disk'],
      },
    }, 'degraded').resource;

    renderWithResources(() => <RuntimeView />, fixture.resources);

    expect(screen.getByText('不可用字段：cpu.usage、disk')).not.toBeNull();
    expect(screen.getByTestId('runtime-metric-cpu').textContent).toContain('不可用');
    expect(screen.queryByText('0%')).toBeNull();
  });
});

describe('ModelsView', () => {
  it('lists installed models and runtime details', () => {
    const { resources } = readyResources();
    renderWithResources(() => <ModelsView />, resources);

    expect(screen.getByText('qwen2.5:7b')).not.toBeNull();
    expect(screen.getByText('deepseek-r1:8b')).not.toBeNull();
    expect(screen.getByText('2 个已安装模型')).not.toBeNull();
    expect(screen.getByText('Ollama 0.5.7')).not.toBeNull();
    expect(screen.getByText('RTX 4090')).not.toBeNull();
  });

  it('uses the empty label only for a successful empty model list', () => {
    const emptyFixture = readyResources();
    const ollama = emptyFixture.resources.ollama.data()!;
    emptyFixture.resources.ollama = fixedResource({ ...ollama, models: [] }).resource;
    const emptyRender = renderWithResources(() => <ModelsView />, emptyFixture.resources);
    expect(screen.getByText('未检测到本地模型')).not.toBeNull();
    emptyRender.unmount();

    const errorFixture = readyResources();
    errorFixture.resources.ollama = fixedResource<OllamaStatus>(undefined, 'error').resource;
    renderWithResources(() => <ModelsView />, errorFixture.resources);
    expect(screen.getByText('模型状态不可用')).not.toBeNull();
    expect(screen.queryByText('未检测到本地模型')).toBeNull();
  });
});

describe('StatusRail', () => {
  it('reuses resource timestamps and exposes named refresh actions', () => {
    const { resources, refresh } = readyResources();
    renderWithResources(() => <StatusRail />, resources);

    expect(screen.getAllByText(new Date(UPDATED_AT).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }))).toHaveLength(4);

    fireEvent.click(screen.getByRole('button', { name: '刷新系统状态' }));
    expect(refresh.system).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: '刷新 Ollama 状态' })).not.toBeNull();
    expect(screen.getByRole('button', { name: '刷新 Git 状态' })).not.toBeNull();
    expect(screen.getByRole('button', { name: '刷新 Token 状态' })).not.toBeNull();
  });

  it('never reports an unavailable CPU value as zero', () => {
    const fixture = readyResources();
    const stats = fixture.resources.system.data()!;
    fixture.resources.system = fixedResource({
      ...stats,
      cpu: { ...stats.cpu, usage: null },
      meta: {
        ...stats.meta,
        status: 'degraded' as const,
        unavailable_fields: ['cpu.usage'],
      },
    }, 'degraded').resource;
    renderWithResources(() => <StatusRail />, fixture.resources);

    expect(screen.getByTestId('status-rail-cpu').textContent).toContain('不可用');
    expect(screen.getByTestId('status-rail-cpu').textContent).not.toContain('0%');
  });

  it('shows a successful empty Token session as no records', () => {
    const fixture = readyResources();
    const snapshot = fixture.resources.tokens.data()!;
    fixture.resources.tokens = fixedResource({
      ...snapshot,
      latest: null,
      samples: [],
    }, 'empty').resource;
    renderWithResources(() => <StatusRail />, fixture.resources);

    expect(screen.getByText('尚无记录')).not.toBeNull();
    expect(screen.queryByText('Token状态不可用')).toBeNull();
  });
});

describe('ChartWidget', () => {
  it('labels the canvas container and filters fully unavailable samples', () => {
    const view = render(() => (
      <ChartWidget
        title="CPU 使用率趋势"
        labels={['10:00', '10:01', '10:02']}
        datasets={[{
          label: 'CPU',
          data: [12, null, 18],
          color: '#42c8bd',
        }]}
      />
    ));

    expect(screen.getByRole('img', { name: 'CPU 使用率趋势' })).not.toBeNull();
    expect(chartMocks.configs[0].data.labels).toEqual(['10:00', '10:02']);
    expect(chartMocks.configs[0].data.datasets[0].data).toEqual([12, 18]);
    view.unmount();
    expect(chartMocks.destroy).toHaveBeenCalledOnce();
  });
});
