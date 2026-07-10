import type {
  IXiaoYiWidget,
  WidgetDimensions,
  WidgetPermission,
} from '../../widget-engine/base-widget';

const DIMENSIONS: WidgetDimensions = {
  minW: 3,
  minH: 2,
  defaultW: 6,
  defaultH: 4,
};

const PERMISSIONS: WidgetPermission[] = ['network'];

export class GithubDashboardWidget implements IXiaoYiWidget {
  readonly id = 'github-dashboard';
  readonly title = 'GitHub 情报看板';
  readonly dimensions = DIMENSIONS;
  readonly permissions = PERMISSIONS;

  async render(): Promise<string> {
    return `
      <section class="jarvis-widget" data-widget-id="${this.id}">
        <header>
          <h2>${this.title}</h2>
          <span class="badge">Phase 3 情报摘要</span>
        </header>
        <div class="grid">
          <article>
            <h3>CanopyKit</h3>
            <p>多 Agent 协调运行时，适合映射到 Phase 8/11 的编排与沙箱能力。</p>
            <a href="https://github.com/redkauribrewersyeast417/CanopyKit" target="_blank" rel="noreferrer">查看仓库</a>
          </article>
          <article>
            <h3>LibreChat</h3>
            <p>统一聊天入口 + Skills/MCP，可参考 Phase 9/10 的前端与市场设计。</p>
            <a href="https://github.com/danny-avila/LibreChat" target="_blank" rel="noreferrer">查看仓库</a>
          </article>
          <article>
            <h3>AI Interpreter</h3>
            <p>实时会议翻译解释器，可作为 Phase 10/11 的多模态 Widget 参考。</p>
            <a href="https://github.com/AntonMinin/ai-interpreter" target="_blank" rel="noreferrer">查看仓库</a>
          </article>
        </div>
      </section>
    `;
  }
}
