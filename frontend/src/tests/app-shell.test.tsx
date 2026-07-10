import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
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
// @ts-expect-error Vitest runs in Node while the browser tsconfig excludes Node globals.
import { readFileSync } from 'node:fs';
import { App } from '../App';

const componentsCss = readFileSync('src/styles/components.css', 'utf8');
const frontendSources = import.meta.glob(
  ['../**/*.{ts,tsx}', '!../tests/**'],
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>;

const apiMocks = vi.hoisted(() => ({
  system: vi.fn(),
  ollamaStatus: vi.fn(),
  gitStatus: vi.fn(),
  tokenUsage: vi.fn(),
  capabilities: vi.fn(),
  models: vi.fn(),
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

vi.mock('../services/chat-stream', () => ({
  streamChat: vi.fn(async () => undefined),
}));

beforeAll(() => {
  Object.defineProperty(window, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

beforeEach(() => {
  for (const mock of Object.values(apiMocks)) mock.mockReset();
  apiMocks.system.mockResolvedValue({
    cpu: { usage: 12, cores: 8, model: 'CPU' },
    memory: { total: 100, used: 50, free: 50, usage: 50 },
    disk: { total: 100, used: 25, free: 75, usage: 25 },
    gpu: [],
    meta: { status: 'ready', source: 'test', unavailable_fields: [] },
  });
  apiMocks.ollamaStatus.mockResolvedValue({
    running: true,
    version: '0.5.7',
    models: [{ name: 'qwen2.5:7b', size: 4_700_000_000 }],
    gpu_available: false,
  });
  apiMocks.gitStatus.mockResolvedValue({
    branch: 'codex/jarvis-command-center',
    clean: true,
    changedFiles: [],
    count: 0,
  });
  apiMocks.tokenUsage.mockResolvedValue({
    latest: null,
    totals: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
    samples: [],
    session_started_at: 1_700_000_000_000,
  });
  apiMocks.capabilities.mockResolvedValue({
    core_api: { configured: false, available: false, base_url: null },
  });
  apiMocks.models.mockResolvedValue({
    models: [{ name: 'qwen2.5:7b', size: 4_700_000_000 }],
  });
  apiMocks.gitLog.mockResolvedValue({ commits: [] });
  apiMocks.memories.mockResolvedValue({ entries: [] });
  apiMocks.plugins.mockResolvedValue({ plugins: [] });
  apiMocks.events.mockResolvedValue({ events: [] });
  apiMocks.storeMemory.mockResolvedValue({ success: true, path: 'memory.md' });
  apiMocks.pluginAction.mockResolvedValue({ success: true });
});

afterEach(() => cleanup());

describe('application navigation', () => {
  it('exposes six Chinese desktop destinations and one active view', async () => {
    render(() => <App />);
    const sidebar = screen.getByRole('navigation', { name: '主导航' });
    const desktop = within(sidebar);
    const labels = ['对话', '运行监控', '代码仓库', '本地模型', '记忆', '插件与工具'];

    for (const label of labels) {
      expect(desktop.getByRole('button', { name: label })).not.toBeNull();
    }
    expect(desktop.getByRole('button', { name: '对话' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getAllByTestId('active-view')).toHaveLength(1);

    fireEvent.click(desktop.getByRole('button', { name: '运行监控' }));
    expect(await screen.findByRole('heading', { name: '运行监控', level: 1 })).not.toBeNull();
    expect(desktop.getByRole('button', { name: '运行监控' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getAllByTestId('active-view')).toHaveLength(1);

    fireEvent.click(desktop.getByRole('button', { name: '插件与工具' }));
    expect(await screen.findByRole('heading', { name: '插件与工具', level: 1 })).not.toBeNull();
    expect(screen.getAllByTestId('active-view')).toHaveLength(1);
  });

  it('opens Models, Memory, and Plugins from the mobile more control', async () => {
    render(() => <App />);
    const mobile = screen.getByRole('navigation', { name: '移动导航' });

    fireEvent.click(within(mobile).getByRole('button', { name: '更多' }));
    const dialog = await screen.findByRole('dialog', { name: '更多视图' });
    const menu = within(dialog);
    expect(menu.getByRole('button', { name: '本地模型' })).not.toBeNull();
    expect(menu.getByRole('button', { name: '记忆' })).not.toBeNull();
    expect(menu.getByRole('button', { name: '插件与工具' })).not.toBeNull();

    fireEvent.click(menu.getByRole('button', { name: '记忆' }));
    expect(await screen.findByRole('heading', { name: '记忆', level: 1 })).not.toBeNull();
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '更多视图' })).toBeNull());
  });
});

describe('application shell structure', () => {
  it('keeps Sidebar, main, and StatusRail in document order', () => {
    render(() => <App />);

    expect(
      Array.from(document.querySelectorAll('[data-shell-region]'))
        .map((element) => element.getAttribute('data-shell-region')),
    ).toEqual(['sidebar', 'main', 'status']);
  });

  it('locks stable tracks and exact responsive breakpoints', () => {
    expect(componentsCss).toContain('grid-template-columns: 216px minmax(0, 1fr) 320px');
    expect(componentsCss).toContain('@media (max-width: 1279px)');
    expect(componentsCss).toContain('@media (max-width: 767px)');
    expect(componentsCss).toContain('height: 100dvh');
  });

  it('contains no legacy HTML widget rendering or letter-only controls', () => {
    const source = Object.values(frontendSources).join('\n');

    expect(source).not.toContain('.innerHTML =');
    expect(source).not.toContain('class GithubDashboardWidget');
    expect(source).not.toContain('class TokenUsageWidget');
    expect(source).not.toMatch(/class=["']icon-button["'][^>]*>\s*[RC]\s*</);
  });
});
