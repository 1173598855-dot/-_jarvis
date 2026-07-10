import { For, Show } from 'solid-js';
import { useRuntimeResources } from '../app/runtime-resources';
import { ResourceState } from '../components/ui/ResourceState';
import { StatusIndicator } from '../components/ui/StatusIndicator';

function formatModelSize(value: number | string | undefined) {
  if (typeof value === 'string') return value;
  if (typeof value !== 'number') return '大小不可用';
  if (value === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  return `${(value / 1024 ** index).toFixed(1)} ${units[index]}`;
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

export function ModelsView() {
  const resources = useRuntimeResources();
  const status = () => resources.ollama.data();
  const viewPhase = () => {
    const phase = resources.ollama.phase();
    if (phase === 'ready' && status()?.models.length === 0) return 'empty';
    return phase;
  };

  return (
    <div class="view-stack">
      <header class="view-heading view-heading--with-status">
        <div>
          <h1>模型</h1>
          <p>Ollama 运行时与本地已安装模型清单。</p>
        </div>
        <Show when={status()}>
          {(ollama) => (
            <StatusIndicator
              label={ollama().running ? 'Ollama 在线' : 'Ollama 离线'}
              tone={ollama().running ? 'success' : 'error'}
            />
          )}
        </Show>
      </header>

      <section class="view-section" aria-labelledby="model-runtime-title">
        <div class="section-heading">
          <div>
            <h2 id="model-runtime-title">运行时</h2>
            <p>最后刷新 {formatTime(resources.ollama.updatedAt())}</p>
          </div>
        </div>
        <ResourceState
          phase={resources.ollama.phase()}
          title="模型状态不可用"
          description={resources.ollama.error()?.message}
          onRetry={() => void resources.ollama.refresh()}
        >
          <Show when={status()}>
            {(ollama) => (
              <div class="runtime-facts">
                <div>
                  <span>服务</span>
                  <strong>{ollama().running ? '运行中' : '未连接'}</strong>
                </div>
                <div>
                  <span>版本</span>
                  <strong>{ollama().version ? `Ollama ${ollama().version}` : '版本不可用'}</strong>
                </div>
                <div>
                  <span>GPU</span>
                  <strong>{ollama().gpu_name || (ollama().gpu_available ? 'GPU 可用' : '未检测到 GPU')}</strong>
                </div>
                <div>
                  <span>模型</span>
                  <strong>{ollama().models.length} 个</strong>
                </div>
              </div>
            )}
          </Show>
        </ResourceState>
      </section>

      <section class="view-section" aria-labelledby="installed-models-title">
        <div class="section-heading">
          <div>
            <h2 id="installed-models-title">已安装模型</h2>
            <p>{status()?.models.length || 0} 个已安装模型</p>
          </div>
        </div>
        <ResourceState
          phase={viewPhase()}
          title={viewPhase() === 'empty' ? '未检测到本地模型' : '模型清单不可用'}
          description={resources.ollama.error()?.message}
          onRetry={() => void resources.ollama.refresh()}
        >
          <Show when={status()}>
            {(ollama) => (
              <div class="model-list" role="list">
                <For each={ollama().models}>
                  {(model) => (
                    <div class="model-row" role="listitem">
                      <div>
                        <strong>{model.name}</strong>
                        <Show when={model.digest}>
                          <code>{model.digest?.slice(0, 12)}</code>
                        </Show>
                      </div>
                      <span>{formatModelSize(model.size)}</span>
                    </div>
                  )}
                </For>
              </div>
            )}
          </Show>
        </ResourceState>
      </section>
    </div>
  );
}
