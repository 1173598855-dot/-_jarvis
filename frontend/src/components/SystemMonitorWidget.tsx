import { Component, createSignal, onCleanup, onMount } from 'solid-js';
import { ChartPushApi, ChartWidget } from './ChartWidget';

interface SystemStats {
  cpu: { usage: number; cores: number; model: string };
  memory: { total: number; used: number; free: number; usage: number };
  disk: { total: number; used: number; free: number; usage: number };
}

const MAX_POINTS = 30;
const FETCH_INTERVAL = 3000;

export const SystemMonitorWidget: Component = () => {
  const [stats, setStats] = createSignal<SystemStats | null>(null);
  const [cpuHistory, setCpuHistory] = createSignal<number[]>([]);
  const [memHistory, setMemHistory] = createSignal<number[]>([]);
  const [diskHistory, setDiskHistory] = createSignal<number[]>([]);
  const [labels, setLabels] = createSignal<string[]>([]);

  let cpuChartApi: ChartPushApi | null = null;
  let memChartApi: ChartPushApi | null = null;
  let diskChartApi: ChartPushApi | null = null;
  let intervalId: number | undefined;

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / Math.pow(1024, index)).toFixed(1)} ${units[index]}`;
  };

  const formatTime = (ts: number) => {
    return new Date(ts).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  };

  const pushChartData = () => {
    const chartLabels = labels();
    if (!chartLabels.length) return;
    cpuChartApi?.pushData(chartLabels, [cpuHistory()]);
    memChartApi?.pushData(chartLabels, [memHistory()]);
    diskChartApi?.pushData(chartLabels, [diskHistory()]);
  };

  const appendPoint = (data: SystemStats) => {
    setCpuHistory((prev) => [...prev, data.cpu.usage].slice(-MAX_POINTS));
    setMemHistory((prev) => [...prev, data.memory.usage].slice(-MAX_POINTS));
    setDiskHistory((prev) => [...prev, data.disk.usage].slice(-MAX_POINTS));
    setLabels((prev) => [...prev, formatTime(Date.now())].slice(-MAX_POINTS));
  };

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/system/stats');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: SystemStats = await res.json();
      setStats(data);
      appendPoint(data);
      queueMicrotask(pushChartData);
    } catch (err) {
      console.error('[SystemMonitorWidget] fetch failed:', err);
    }
  };

  onMount(() => {
    fetchStats();
    intervalId = window.setInterval(fetchStats, FETCH_INTERVAL);
  });

  onCleanup(() => {
    if (intervalId) window.clearInterval(intervalId);
  });

  return (
    <section class="panel compact-panel system-panel">
      <div class="panel-header">
        <div>
          <p class="eyebrow">Telemetry</p>
          <h2>System</h2>
        </div>
        <span class="muted-text">{stats()?.cpu.cores || '--'} cores</span>
      </div>

      {stats() ? (
        <>
          <div class="metrics-row">
            <div class="metric-box">
              <span class="metric-label">CPU</span>
              <strong>{stats()!.cpu.usage.toFixed(0)}%</strong>
            </div>
            <div class="metric-box">
              <span class="metric-label">Memory</span>
              <strong>{stats()!.memory.usage.toFixed(0)}%</strong>
            </div>
            <div class="metric-box">
              <span class="metric-label">Disk</span>
              <strong>{stats()!.disk.usage.toFixed(0)}%</strong>
            </div>
          </div>

          <div class="usage-detail">
            <span>Memory</span>
            <span>{formatBytes(stats()!.memory.used)} / {formatBytes(stats()!.memory.total)}</span>
          </div>
          <div class="usage-detail">
            <span>Disk</span>
            <span>{formatBytes(stats()!.disk.used)} / {formatBytes(stats()!.disk.total)}</span>
          </div>

          <ChartWidget
            title="cpu"
            labels={labels()}
            datasets={[{ label: 'CPU', data: cpuHistory(), color: '#20d6d2', unit: '%' }]}
            height={82}
            onReady={(api) => { cpuChartApi = api; }}
          />
          <ChartWidget
            title="memory"
            labels={labels()}
            datasets={[{ label: 'Memory', data: memHistory(), color: '#8b8cf6', unit: '%' }]}
            height={82}
            onReady={(api) => { memChartApi = api; }}
          />
          <ChartWidget
            title="disk"
            labels={labels()}
            datasets={[{ label: 'Disk', data: diskHistory(), color: '#f0b35a', unit: '%' }]}
            height={82}
            onReady={(api) => { diskChartApi = api; }}
          />
        </>
      ) : (
        <div class="loading-state">Loading system telemetry...</div>
      )}
    </section>
  );
};
