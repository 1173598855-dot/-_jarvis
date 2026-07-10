import { describe, it, expect } from 'vitest';
import { GithubDashboardWidget } from '../core/brain/github-dashboard-widget';
import { TokenUsageWidget } from '../core/brain/token-usage-widget';

describe('Widget engine', () => {
  it('renders github dashboard widget', async () => {
    const widget = new GithubDashboardWidget();
    const html = await widget.render();

    expect(html).toContain('GitHub 情报看板');
    expect(html).toContain('CanopyKit');
    expect(html).toContain('LibreChat');
    expect(html).toContain('AI Interpreter');
  });

  it('renders token usage widget', async () => {
    const widget = new TokenUsageWidget();
    const html = await widget.render();

    expect(html).toContain('Token 消耗仪表盘');
    expect(html).toContain('输入 Token');
    expect(html).toContain('输出 Token');
  });
});
