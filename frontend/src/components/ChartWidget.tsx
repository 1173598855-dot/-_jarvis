/**
 * ChartWidget — Chart.js 实时折线图容器
 * Phase 10: Widget 引擎增强
 *
 * 支持外部通过 ref 调用 pushData() 更新图表数据
 */

import { Component, onMount, onCleanup } from 'solid-js';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

interface ChartWidgetProps {
  title: string;
  labels: string[];
  datasets: Array<{
    label: string;
    data: number[];
    color: string;
    unit?: string;
  }>;
  maxDataPoints?: number;
  yMin?: number;
  yMax?: number;
  height?: number;
  onReady?: (api: ChartPushApi) => void;
}

export interface ChartPushApi {
  pushData(labels: string[], datasets: number[][]): void;
}

export const ChartWidget: Component<ChartWidgetProps> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chart: any = null;

  onMount(() => {
    if (!canvasRef) return;

    const ctx = canvasRef.getContext('2d');
    if (!ctx) return;

    chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [...props.labels],
        datasets: props.datasets.map((ds) => ({
          label: ds.label,
          data: [...ds.data],
          borderColor: ds.color,
          backgroundColor: ds.color + '18',
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: ds.color,
          tension: 0.35,
          fill: true,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: {
          intersect: false,
          mode: 'index',
        },
        plugins: {
          legend: {
            display: props.datasets.length > 1,
            labels: {
              color: '#94a3b8',
              boxWidth: 10,
              padding: 10,
              font: { size: 10, family: "'JetBrains Mono', 'Fira Code', monospace" },
            },
          },
          tooltip: {
            backgroundColor: 'rgba(15, 23, 42, 0.95)',
            titleColor: '#00F0FF',
            bodyColor: '#e2e8f0',
            borderColor: 'rgba(0, 240, 255, 0.3)',
            borderWidth: 1,
            padding: 10,
            cornerRadius: 6,
            bodyFont: { family: "'JetBrains Mono', 'Fira Code', monospace", size: 11 },
            callbacks: {
              label: (context: any) => {
                const ds = props.datasets[context.datasetIndex];
                const unit = ds.unit || '%';
                return `${context.dataset.label}: ${context.parsed.y.toFixed(1)}${unit}`;
              },
            },
          },
        },
        scales: {
          x: {
            display: true,
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: {
              color: '#64748b',
              maxTicksLimit: 8,
              font: { size: 9, family: "'JetBrains Mono', 'Fira Code', monospace" },
            },
          },
          y: {
            min: props.yMin ?? 0,
            max: props.yMax ?? 100,
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: {
              color: '#64748b',
              font: { size: 9, family: "'JetBrains Mono', 'Fira Code', monospace" },
              callback: (val: any) => `${val}%`,
              stepSize: 25,
            },
          },
        },
      },
    });

    // 通知父组件 API 已就绪
    if (props.onReady) {
      props.onReady({
        pushData: (newLabels: string[], newDatasets: number[][]) => {
          if (!chart) return;
          chart.data.labels = newLabels;
          newDatasets.forEach((data, i) => {
            if (chart.data.datasets[i]) {
              chart.data.datasets[i].data = data;
            }
          });
          chart.update('none');
        },
      });
    }
  });

  onCleanup(() => {
    if (chart) {
      chart.destroy();
      chart = null;
    }
  });

  return (
    <div class="chart-widget" style={{ height: `${props.height || 140}px` }}>
      <canvas ref={canvasRef!} />
    </div>
  );
};
