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

const PERMISSIONS: WidgetPermission[] = ['llm_access'];

export class TokenUsageWidget implements IXiaoYiWidget {
  readonly id = 'token-usage';
  readonly title = 'Token 消耗仪表盘';
  readonly dimensions = DIMENSIONS;
  readonly permissions = PERMISSIONS;

  async render(): Promise<string> {
    return `
      <section class="jarvis-widget" data-widget-id="${this.id}">
        <header>
          <h2>${this.title}</h2>
          <span class="badge">Phase 10 监控面板</span>
        </header>
        <div class="metrics">
          <div class="metric">
            <span class="label">输入 Token</span>
            <span class="value">--</span>
          </div>
          <div class="metric">
            <span class="label">输出 Token</span>
            <span class="value">--</span>
          </div>
          <div class="metric">
            <span class="label">累计成本</span>
            <span class="value">待接入计费模型</span>
          </div>
        </div>
        <p class="note">当前为占位视图，后续接入 \`ollama_manager\` 与计费适配器。</p>
      </section>
    `;
  }
}
