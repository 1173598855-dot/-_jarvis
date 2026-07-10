import { Component, createMemo, createSignal, onCleanup, onMount } from 'solid-js';

interface OllamaModel {
  name: string;
  size?: number | string;
}

interface OllamaStatus {
  running: boolean;
  version?: string;
  models: OllamaModel[];
  gpu_available?: boolean;
  gpu_name?: string;
}

export const OllamaMonitorWidget: Component = () => {
  const [status, setStatus] = createSignal<OllamaStatus | null>(null);
  const [lastUpdated, setLastUpdated] = createSignal('');
  let intervalId: number | undefined;

  const formatSize = (size?: number | string) => {
    const numeric = typeof size === 'string' ? Number(size) : size;
    if (!numeric || Number.isNaN(numeric)) return '';
    return `${(numeric / 1024 / 1024 / 1024).toFixed(1)} GB`;
  };

  const modelCount = createMemo(() => status()?.models?.length || 0);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/ollama/status');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStatus({
        running: Boolean(data.running ?? data.models?.length),
        version: data.version,
        models: data.models || [],
        gpu_available: Boolean(data.gpu_available),
        gpu_name: data.gpu_name,
      });
      setLastUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (err) {
      console.error('[OllamaMonitorWidget] fetch failed:', err);
      setStatus({ running: false, models: [] });
    }
  };

  onMount(() => {
    fetchStatus();
    intervalId = window.setInterval(fetchStatus, 30000);
  });

  onCleanup(() => {
    if (intervalId) window.clearInterval(intervalId);
  });

  return (
    <section class="panel compact-panel">
      <div class="panel-header">
        <div>
          <p class="eyebrow">Models</p>
          <h2>Ollama</h2>
        </div>
        <button class="icon-button" type="button" onClick={fetchStatus} title="Refresh Ollama status">
          <span aria-hidden="true">R</span>
        </button>
      </div>

      <div class="split-status">
        <span class={`status-pill ${status()?.running ? 'online' : 'offline'}`}>
          <span class="status-dot" />
          {status()?.running ? 'Online' : 'Offline'}
        </span>
        <span class="muted-text">{lastUpdated() || 'Waiting'}</span>
      </div>

      <div class="stat-strip">
        <div>
          <span class="stat-label">Installed</span>
          <strong>{modelCount()}</strong>
        </div>
        <div>
          <span class="stat-label">Runtime</span>
          <strong>{status()?.gpu_available ? 'GPU' : 'CPU'}</strong>
        </div>
      </div>

      <div class="model-list">
        {(status()?.models || []).slice(0, 4).map((model) => (
          <div class="model-row">
            <span class="model-name">{model.name}</span>
            <span class="model-size">{formatSize(model.size)}</span>
          </div>
        ))}
        {status() && modelCount() === 0 && (
          <div class="empty-line">No local models detected.</div>
        )}
      </div>
    </section>
  );
};
