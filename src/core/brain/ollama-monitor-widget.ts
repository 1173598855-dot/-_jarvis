/**
 * OllamaMonitorWidget — Ollama 实时监控 Widget
 * 首批 Widget 组件之一
 * 萃取自 AnythingLLM 的 Ollama 集成架构
 */

import { BaseWidget } from '../core/widget-engine';
import type { IXiaoYiWidget, OllamaStatus, OllamaModel } from '../../types';

export class OllamaMonitorWidget extends BaseWidget implements IXiaoYiWidget {
  id = 'ollama-monitor';
  title = 'Ollama 本地 LLM 监控';
  permissions = ['system_monitor', 'llm_access'];

  dimensions = {
    minW: 350,
    minH: 250,
    defaultW: 450,
    defaultH: 320,
  };

  private status: OllamaStatus | null = null;
  private refreshInterval: number | null = null;

  async onRefresh(): Promise<void> {
    try {
      // 调用 Ollama Manager API 获取状态
      const response = await fetch('/api/ollama/status');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      this.status = await response.json();
      this.setState({ status: this.status });
    } catch (error) {
      console.error(`[OllamaMonitorWidget] 刷新失败:`, error);
      this.setState({
        status: {
          running: false,
          models: [],
          gpu_available: false,
        },
      });
    }
  }

  render(): JSX.Element {
    const { status } = this.state;

    if (!status) {
      return (
        <div className="widget-card backdrop-blur-md">
          <h3 className="widget-title">{this.title}</h3>
          <div className="widget-loading">正在加载...</div>
        </div>
      );
    }

    return (
      <div className="widget-card backdrop-blur-md">
        <h3 className="widget-title">{this.title}</h3>

        {/* 服务状态指示 */}
        <div className="widget-status-row">
          <span className={`status-indicator ${status.running ? 'online' : 'offline'}`}>
            {status.running ? '🟢' : '🔴'}
          </span>
          <span className="status-text">
            {status.running ? '运行中' : '未启动'}
          </span>
          {status.version && (
            <span className="version-badge">v{status.version}</span>
          )}
        </div>

        {/* GPU 状态 */}
        <div className="widget-section">
          <div className="section-label">GPU 加速</div>
          <div className="gpu-status">
            {status.gpu_available ? (
              <>
                <span className="gpu-icon">🚀</span>
                <span className="gpu-name">{status.gpu_name || 'GPU 可用'}</span>
              </>
            ) : (
              <>
                <span className="gpu-icon">💻</span>
                <span className="gpu-name">CPU 模式</span>
              </>
            )}
          </div>
        </div>

        {/* 已安装模型列表 */}
        <div className="widget-section">
          <div className="section-label">
            已安装模型 ({status.models?.length || 0})
          </div>
          <div className="models-list">
            {status.models && status.models.length > 0 ? (
              status.models.slice(0, 5).map((model: OllamaModel) => (
                <div key={model.name} className="model-item">
                  <span className="model-name">{model.name}</span>
                  <span className="model-size">
                    {model.size ? `${(parseInt(model.size) / 1073741824).toFixed(1)} GB` : ''}
                  </span>
                </div>
              ))
            ) : (
              <div className="no-models">暂无模型 — 使用 ollama pull 拉取</div>
            )}
          </div>
        </div>

        {/* 快捷操作 */}
        <div className="widget-actions">
          <button className="action-btn" onClick={() => this.refresh()}>
            刷新
          </button>
          <button className="action-btn secondary" onClick={() => this.openOllamaCLI()}>
            打开终端
          </button>
        </div>
      </div>
    );
  }

  private openOllamaCLI(): void {
    // 触发系统终端打开 Ollama CLI
    console.log('[OllamaMonitorWidget] 打开 Ollama CLI');
  }

  // 生命周期：挂载时启动自动刷新
  onMount(): void {
    this.refresh();
    // 每 30 秒自动刷新
    this.refreshInterval = window.setInterval(() => {
      this.refresh();
    }, 30000);
  }

  // 生命周期：卸载时清理定时器
  onUnmount(): void {
    if (this.refreshInterval) {
      window.clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }
}
