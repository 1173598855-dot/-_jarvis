import { Component, createSignal, onCleanup, onMount } from 'solid-js';
import { ChartPushApi, ChartWidget } from './ChartWidget';

interface TokenData {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  timestamp: number;
}

const MAX_POINTS = 20;
const FETCH_INTERVAL = 5000;

export const TokenWidget: Component = () => {
  const [latest, setLatest] = createSignal<TokenData | null>(null);
  const [labels, setLabels] = createSignal<string[]>([]);
  const [promptHistory, setPromptHistory] = createSignal<number[]>([]);
  const [completionHistory, setCompletionHistory] = createSignal<number[]>([]);

  let promptChartApi: ChartPushApi | null = null;
  let completionChartApi: ChartPushApi | null = null;
  let intervalId: number | undefined;

  const formatTime = (ts: number) => {
    return new Date(ts).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  };

  const totalTokens = () => {
    const current = latest();
    if (!current) return 0;
    return current.total_tokens || current.prompt_tokens + current.completion_tokens;
  };

  const pushChartData = () => {
    const chartLabels = labels();
    if (!chartLabels.length) return;
    promptChartApi?.pushData(chartLabels, [promptHistory()]);
    completionChartApi?.pushData(chartLabels, [completionHistory()]);
  };

  const fetchTokens = async () => {
    try {
      const res = await fetch('/api/ollama/token-usage');
      if (!res.ok) return;
      const data: TokenData = await res.json();
      setLatest(data);
      setPromptHistory((prev) => [...prev, data.prompt_tokens].slice(-MAX_POINTS));
      setCompletionHistory((prev) => [...prev, data.completion_tokens].slice(-MAX_POINTS));
      setLabels((prev) => [...prev, formatTime(Date.now())].slice(-MAX_POINTS));
      queueMicrotask(pushChartData);
    } catch (err) {
      console.error('[TokenWidget] fetch failed:', err);
    }
  };

  onMount(() => {
    fetchTokens();
    intervalId = window.setInterval(fetchTokens, FETCH_INTERVAL);
  });

  onCleanup(() => {
    if (intervalId) window.clearInterval(intervalId);
  });

  return (
    <section class="panel token-panel">
      <div class="panel-header">
        <div>
          <p class="eyebrow">Usage</p>
          <h2>Token activity</h2>
        </div>
        <span class="muted-text">rolling sample</span>
      </div>

      {latest() ? (
        <>
          <div class="token-summary">
            <div>
              <span class="stat-label">Prompt</span>
              <strong>{latest()!.prompt_tokens.toLocaleString()}</strong>
            </div>
            <div>
              <span class="stat-label">Completion</span>
              <strong>{latest()!.completion_tokens.toLocaleString()}</strong>
            </div>
            <div>
              <span class="stat-label">Total</span>
              <strong>{totalTokens().toLocaleString()}</strong>
            </div>
          </div>

          <div class="dual-chart">
            <ChartWidget
              title="prompt-tokens"
              labels={labels()}
              datasets={[{ label: 'Prompt', data: promptHistory(), color: '#20d6d2', unit: ' tk' }]}
              yMin={0}
              height={108}
              onReady={(api) => { promptChartApi = api; }}
            />
            <ChartWidget
              title="completion-tokens"
              labels={labels()}
              datasets={[{ label: 'Completion', data: completionHistory(), color: '#8b8cf6', unit: ' tk' }]}
              yMin={0}
              height={108}
              onReady={(api) => { completionChartApi = api; }}
            />
          </div>
        </>
      ) : (
        <div class="loading-state">Waiting for token data...</div>
      )}
    </section>
  );
};
