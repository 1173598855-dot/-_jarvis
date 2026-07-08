/**
 * SystemMonitorWidget — 系统硬件监视器 Widget
 * 首批 Widget 组件之一
 *
 * 功能：
 * - CPU 使用率实时监控
 * - 内存使用率监控
 * - 磁盘使用率监控
 * - 网络状态监控
 */

import { BaseWidget } from './base-widget';
import type { IXiaoYiWidget, SystemStats } from '../../types';

export class SystemMonitorWidget extends BaseWidget implements IXiaoYiWidget {
  id = 'system-monitor';
  title = '系统硬件监视器';
  permissions = ['system_monitor'];

  dimensions = {
    minW: 350,
    minH: 280,
    defaultW: 450,
    defaultH: 350,
  };

  private refreshInterval: number | null = null;

  async onRefresh(): Promise<void> {
    try {
      // 调用系统 API 获取状态
      const response = await fetch('/api/system/stats');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const stats: SystemStats = await response.json();
      this.setState({ stats });
    } catch (error) {
      console.error('[SystemMonitorWidget] 刷新失败:', error);
      this.setState({
        stats: {
          cpu: { usage: 0, cores: 0, model: 'N/A' },
          memory: { total: 0, used: 0, free: 0, usage: 0 },
          disk: { total: 0, used: 0, free: 0, usage: 0 },
          network: { interfaces: [] },
        } as SystemStats,
      });
    }
  }

  render() {
    const stats = this.state.stats as SystemStats | undefined;

    if (!stats) {
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

        {/* CPU */}
        <div className="widget-section">
          <div className="section-label">CPU</div>
          <div className="metric-row">
            <span className="metric-name">使用率</span>
            <div className="progress-bar-container">
              <div
                className="progress-bar-fill"
                style={{
                  width: `${Math.min(stats.cpu.usage, 100)}%`,
                  backgroundColor: this.getUsageColor(stats.cpu.usage),
                }}
              />
            </div>
            <span className="metric-value">{stats.cpu.usage.toFixed(1)}%</span>
          </div>
          <div className="metric-detail">
            {stats.cpu.model} · {stats.cpu.cores} 核
          </div>
        </div>

        {/* 内存 */}
        <div className="widget-section">
          <div className="section-label">内存</div>
          <div className="metric-row">
            <span className="metric-name">使用率</span>
            <div className="progress-bar-container">
              <div
                className="progress-bar-fill"
                style={{
                  width: `${Math.min(stats.memory.usage, 100)}%`,
                  backgroundColor: this.getUsageColor(stats.memory.usage),
                }}
              />
            </div>
            <span className="metric-value">{stats.memory.usage.toFixed(1)}%</span>
          </div>
          <div className="metric-detail">
            {this.formatBytes(stats.memory.used)} / {this.formatBytes(stats.memory.total)}
          </div>
        </div>

        {/* 磁盘 */}
        <div className="widget-section">
          <div className="section-label">磁盘</div>
          <div className="metric-row">
            <span className="metric-name">使用率</span>
            <div className="progress-bar-container">
              <div
                className="progress-bar-fill"
                style={{
                  width: `${Math.min(stats.disk.usage, 100)}%`,
                  backgroundColor: this.getUsageColor(stats.disk.usage),
                }}
              />
            </div>
            <span className="metric-value">{stats.disk.usage.toFixed(1)}%</span>
          </div>
          <div className="metric-detail">
            {this.formatBytes(stats.disk.used)} / {this.formatBytes(stats.disk.total)}
          </div>
        </div>

        {/* 网络 */}
        <div className="widget-section">
          <div className="section-label">网络</div>
          <div className="network-interfaces">
            {stats.network.interfaces.length > 0 ? (
              stats.network.interfaces.map((iface, idx) => (
                <div key={idx} className="network-item">
                  <span className={`network-status ${iface.status}`}>
                    {iface.status === 'up' ? '🟢' : '🔴'}
                  </span>
                  <span className="network-name">{iface.name}</span>
                  <span className="network-ip">{iface.ip}</span>
                </div>
              ))
            ) : (
              <div className="no-data">无网络接口信息</div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ============================================================
  // 生命周期
  // ============================================================

  onMount(): void {
    this.refresh();
    // 每 5 秒刷新
    this.refreshInterval = window.setInterval(() => {
      this.refresh();
    }, 5000);
  }

  onUnmount(): void {
    if (this.refreshInterval) {
      window.clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  // ============================================================
  // 工具方法
  // ============================================================

  private getUsageColor(usage: number): string {
    if (usage < 50) return '#10b981'; // 绿色
    if (usage < 80) return '#f59e0b'; // 黄色
    return '#ef4444'; // 红色
  }

  private formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
  }
}
