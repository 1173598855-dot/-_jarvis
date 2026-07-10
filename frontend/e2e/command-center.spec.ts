import {
  expect,
  test,
  type Page,
  type Route,
} from '@playwright/test';

const jsonHeaders = { 'Content-Type': 'application/json' };

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });
}

async function installApiFixtures(page: Page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === '/api/ollama/chat/stream') {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        body: [
          'data: {"message":{"content":"已完成项目检查。"}}\n\n',
          'data: {"done":true,"prompt_eval_count":8,"eval_count":6}\n\n',
          'data: [DONE]\n\n',
        ].join(''),
      });
      return;
    }

    const fixtures: Record<string, unknown> = {
      '/api/health': { status: 'healthy' },
      '/api/system/stats': {
        cpu: { usage: 18.4, cores: 16, model: 'AMD Ryzen 9 7950X' },
        memory: {
          total: 68_719_476_736,
          used: 31_457_280_000,
          free: 37_262_196_736,
          usage: 45.8,
        },
        disk: {
          total: 2_000_000_000_000,
          used: 820_000_000_000,
          free: 1_180_000_000_000,
          usage: 41,
        },
        gpu: [{ vendor: 'NVIDIA', model: 'RTX 4090' }],
        meta: {
          status: 'ready',
          source: 'systeminformation',
          unavailable_fields: [],
        },
      },
      '/api/ollama/status': {
        running: true,
        version: '0.5.7',
        models: [
          { name: 'qwen2.5:7b', size: 4_700_000_000 },
          { name: 'deepseek-r1:8b', size: 5_100_000_000 },
        ],
        gpu_available: true,
        gpu_name: 'RTX 4090',
      },
      '/api/ollama/models': {
        models: [
          { name: 'qwen2.5:7b', size: 4_700_000_000 },
          { name: 'deepseek-r1:8b', size: 5_100_000_000 },
        ],
      },
      '/api/ollama/token-usage': {
        latest: {
          prompt_tokens: 12,
          completion_tokens: 18,
          total_tokens: 30,
          timestamp: 1_700_000_000_000,
        },
        totals: {
          prompt_tokens: 120,
          completion_tokens: 180,
          total_tokens: 300,
        },
        samples: [{
          prompt_tokens: 12,
          completion_tokens: 18,
          total_tokens: 30,
          timestamp: 1_700_000_000_000,
        }],
        session_started_at: 1_699_999_000_000,
      },
      '/api/git/status': {
        branch: 'codex/jarvis-command-center',
        clean: false,
        changedFiles: [{
          status: ' M',
          file: 'frontend/src/App.tsx',
          staged: false,
        }],
        count: 1,
      },
      '/api/git/log': {
        commits: [{
          hash: 'abc12345',
          author: 'Codex',
          email: 'codex@example.com',
          date: '2026-07-10T10:00:00+08:00',
          subject: 'feat: command center',
        }],
      },
      '/api/capabilities': {
        core_api: {
          configured: true,
          available: true,
          base_url: 'http://127.0.0.1:8080',
        },
      },
      '/api/memory/entries': {
        entries: [{
          id: 'memory-1',
          type: 'project',
          title: '项目测试约定',
          content: '提交前运行全量测试。',
          tags: ['testing'],
          created_at: '2026-07-10T10:00:00+08:00',
        }],
      },
      '/api/plugins': {
        plugins: [{
          id: 'event-logger',
          name: 'Event Logger',
          version: '1.0.0',
          status: 'enabled',
          permissions: ['events:read'],
        }],
      },
      '/api/events': {
        events: [{
          type: 'system.ready',
          payload: 'Command center ready',
          timestamp: '2026-07-10T10:01:00+08:00',
          source: 'runtime',
        }],
      },
    };

    if (path === '/api/memory/store' || path.startsWith('/api/plugins/')) {
      await fulfillJson(route, { success: true });
      return;
    }
    if (path in fixtures) {
      await fulfillJson(route, fixtures[path]);
      return;
    }

    await fulfillJson(route, {
      error: { code: 'UNHANDLED_FIXTURE', message: `No fixture for ${path}` },
    }, 500);
  });
}

function trackConsole(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      errors.push(message.text());
    }
  });
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test('loads and navigates the daily command center', async ({ page }, testInfo) => {
  const errors = trackConsole(page);
  await page.goto('/');

  await expect(page).toHaveTitle(/J\.A\.R\.V\.I\.S\./);
  await expect(page.getByRole('heading', { name: '指挥中心', level: 1 })).toBeVisible();

  const views = [
    { label: '运行监控', heading: '运行监控', mobileMore: false },
    { label: '代码仓库', heading: '代码仓库', mobileMore: false },
    { label: '本地模型', heading: '本地模型', mobileMore: true },
    { label: '记忆', heading: '记忆', mobileMore: true },
    { label: '插件与工具', heading: '插件与工具', mobileMore: true },
  ];

  for (const view of views) {
    if (testInfo.project.name === 'mobile' && view.mobileMore) {
      await page.getByRole('button', { name: '更多', exact: true }).click();
      const moreDialog = page.getByRole('dialog', { name: '更多视图' });
      await expect(moreDialog).toBeVisible();
      await moreDialog.getByRole('button', { name: view.label, exact: true }).click();
    } else {
      await page.getByRole('button', { name: view.label, exact: true }).click();
    }
    await expect(page.getByRole('heading', { name: view.heading, level: 1 })).toBeVisible();
  }

  await page.getByRole('button', { name: '运行监控', exact: true }).click();
  await expect(page.getByRole('heading', { name: '运行监控', level: 1 })).toBeVisible();
  await expect(page.locator('.command-shell')).toBeVisible();
  expect(await page.evaluate(() => (
    document.documentElement.scrollWidth === document.documentElement.clientWidth
  ))).toBe(true);
  expect(errors).toEqual([]);

  await page.screenshot({
    path: testInfo.outputPath('command-center.png'),
    fullPage: false,
  });
});

test('streams a local assistant response', async ({ page }, testInfo) => {
  const errors = trackConsole(page);
  await page.goto('/');

  const input = page.getByLabel('消息输入');
  await input.fill('检查项目状态');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.getByText('已完成项目检查。')).toBeVisible();
  expect(errors).toEqual([]);

  await page.screenshot({
    path: testInfo.outputPath('command-center.png'),
    fullPage: false,
  });
});

test('mobile more navigation returns to chat without overflow', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'mobile-only navigation flow');
  const errors = trackConsole(page);
  await page.goto('/');

  await page.getByRole('button', { name: '更多' }).click();
  const moreDialog = page.getByRole('dialog', { name: '更多视图' });
  await expect(moreDialog).toBeVisible();
  await moreDialog.getByRole('button', { name: '记忆' }).click();
  await expect(page.getByRole('heading', { name: '记忆', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: '对话' }).click();
  await expect(page.getByRole('heading', { name: '指挥中心', level: 1 })).toBeVisible();
  expect(await page.evaluate(() => (
    document.documentElement.scrollWidth === document.documentElement.clientWidth
  ))).toBe(true);
  expect(errors).toEqual([]);

  await page.screenshot({
    path: testInfo.outputPath('command-center.png'),
    fullPage: false,
  });
});
