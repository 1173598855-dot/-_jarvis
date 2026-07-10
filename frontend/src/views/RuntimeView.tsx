import { Show } from 'solid-js';
import { useRuntimeResources } from '../app/runtime-resources';
import { ChartWidget } from '../components/ChartWidget';
import { ResourceState } from '../components/ui/ResourceState';

function formatBytes(value: number | null) {
  if (value === null) return '不可用';
  if (value === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  return `${(value / 1024 ** index).toFixed(1)} ${units[index]}`;
}

function formatPercent(value: number | null) {
  return value === null ? '不可用' : `${value.toFixed(1)}%`;
}

function formatTime(value: number | undefined) {
  if (value === undefined) return '尚未更新';
  return new Date(value).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function RuntimeView() {
  const resources = useRuntimeResources();
  const stats = () => resources.system.data();
  const tokenSnapshot = () => resources.tokens.data();
  const systemLabel = () => [formatTime(resources.system.updatedAt())];

  return (
    <div class="view-stack">
      <header class="view-heading">
        <div>
          <h1>运行监控</h1>
          <p>本机硬件负载与当前服务会话用量。</p>
        </div>
      </header>

      <section class="view-section" aria-labelledby="system-runtime-title">
        <div class="section-heading">
          <div>
            <h2 id="system-runtime-title">系统资源</h2>
            <p>{stats()?.cpu.model || '硬件信息不可用'}</p>
          </div>
          <time>{formatTime(resources.system.updatedAt())}</time>
        </div>
        <ResourceState
          phase={resources.system.phase()}
          title="系统指标不可用"
          description={resources.system.error()?.message}
          onRetry={() => void resources.system.refresh()}
        >
          <Show when={stats()}>
            {(current) => (
              <>
                <div class="metric-grid metric-grid--three">
                  <div class="metric-cell" data-testid="runtime-metric-cpu">
                    <span>CPU</span>
                    <strong>{formatPercent(current().cpu.usage)}</strong>
                    <small>{current().cpu.cores === null ? '核心数不可用' : `${current().cpu.cores} 核心`}</small>
                  </div>
                  <div class="metric-cell" data-testid="runtime-metric-memory">
                    <span>内存</span>
                    <strong>{formatPercent(current().memory.usage)}</strong>
                    <small>{formatBytes(current().memory.used)} / {formatBytes(current().memory.total)}</small>
                  </div>
                  <div class="metric-cell" data-testid="runtime-metric-disk">
                    <span>磁盘</span>
                    <strong>{formatPercent(current().disk.usage)}</strong>
                    <small>{formatBytes(current().disk.used)} / {formatBytes(current().disk.total)}</small>
                  </div>
                </div>

                <Show when={current().meta.unavailable_fields.length > 0}>
                  <p class="degraded-fields">
                    不可用字段：{current().meta.unavailable_fields.join('、')}
                  </p>
                </Show>

                <div class="runtime-charts">
                  <Show when={current().cpu.usage !== null}>
                    <ChartWidget
                      title="CPU 使用率趋势"
                      labels={systemLabel()}
                      datasets={[{
                        label: 'CPU',
                        data: [current().cpu.usage],
                        color: '#42c8bd',
                        unit: '%',
                      }]}
                      yMin={0}
                      yMax={100}
                      height={120}
                    />
                  </Show>
                  <Show when={current().memory.usage !== null}>
                    <ChartWidget
                      title="内存使用率趋势"
                      labels={systemLabel()}
                      datasets={[{
                        label: '内存',
                        data: [current().memory.usage],
                        color: '#8e91c9',
                        unit: '%',
                      }]}
                      yMin={0}
                      yMax={100}
                      height={120}
                    />
                  </Show>
                  <Show when={current().disk.usage !== null}>
                    <ChartWidget
                      title="磁盘使用率趋势"
                      labels={systemLabel()}
                      datasets={[{
                        label: '磁盘',
                        data: [current().disk.usage],
                        color: '#e6ad54',
                        unit: '%',
                      }]}
                      yMin={0}
                      yMax={100}
                      height={120}
                    />
                  </Show>
                </div>

                <p class="resource-source">
                  数据源：{current().meta.source}
                </p>
              </>
            )}
          </Show>
        </ResourceState>
      </section>

      <section class="view-section" aria-labelledby="token-runtime-title">
        <div class="section-heading">
          <div>
            <h2 id="token-runtime-title">Token 用量</h2>
            <p>当前 Express 服务进程内累计数据。</p>
          </div>
          <time>{formatTime(resources.tokens.updatedAt())}</time>
        </div>
        <ResourceState
          phase={resources.tokens.phase()}
          title={resources.tokens.phase() === 'empty' ? '尚无模型调用记录' : 'Token 数据不可用'}
          description={resources.tokens.error()?.message}
          onRetry={() => void resources.tokens.refresh()}
        >
          <Show when={tokenSnapshot()}>
            {(snapshot) => (
              <>
                <div class="session-heading">
                  <strong>当前服务会话</strong>
                  <span>启动于 {formatTime(snapshot().session_started_at)}</span>
                </div>
                <div class="metric-grid metric-grid--three">
                  <div class="metric-cell">
                    <span>Prompt</span>
                    <strong>{snapshot().totals.prompt_tokens.toLocaleString()}</strong>
                    <small>累计输入</small>
                  </div>
                  <div class="metric-cell">
                    <span>Completion</span>
                    <strong>{snapshot().totals.completion_tokens.toLocaleString()}</strong>
                    <small>累计输出</small>
                  </div>
                  <div class="metric-cell">
                    <span>Total</span>
                    <strong>{snapshot().totals.total_tokens.toLocaleString()}</strong>
                    <small>会话总量</small>
                  </div>
                </div>

                <Show when={snapshot().latest}>
                  {(latest) => (
                    <p class="latest-sample">
                      最近一次：{latest().prompt_tokens.toLocaleString()} 输入 / {latest().completion_tokens.toLocaleString()} 输出
                    </p>
                  )}
                </Show>

                <Show when={snapshot().samples.length > 0}>
                  <ChartWidget
                    title="Token 调用趋势"
                    labels={snapshot().samples.map((sample) => formatTime(sample.timestamp))}
                    datasets={[
                      {
                        label: 'Prompt',
                        data: snapshot().samples.map((sample) => sample.prompt_tokens),
                        color: '#42c8bd',
                        unit: ' tk',
                      },
                      {
                        label: 'Completion',
                        data: snapshot().samples.map((sample) => sample.completion_tokens),
                        color: '#8e91c9',
                        unit: ' tk',
                      },
                    ]}
                    maxDataPoints={60}
                    yMin={0}
                    height={150}
                  />
                </Show>
              </>
            )}
          </Show>
        </ResourceState>
      </section>
    </div>
  );
}
