import {
  Chart,
  registerables,
  type ChartDataset,
  type TooltipItem,
} from 'chart.js';
import {
  createEffect,
  onCleanup,
  onMount,
  type Component,
} from 'solid-js';

Chart.register(...registerables);

interface ChartDatasetInput {
  label: string;
  data: Array<number | null>;
  color: string;
  unit?: string;
}

interface ChartWidgetProps {
  title: string;
  labels: string[];
  datasets: ChartDatasetInput[];
  maxDataPoints?: number;
  yMin?: number;
  yMax?: number;
  height?: number;
  onReady?: (api: ChartPushApi) => void;
}

export interface ChartPushApi {
  pushData(labels: string[], datasets: Array<Array<number | null>>): void;
}

interface NormalizedChartData {
  labels: string[];
  datasets: ChartDatasetInput[];
}

function normalizeData(
  labels: string[],
  datasets: ChartDatasetInput[],
  maxDataPoints?: number,
): NormalizedChartData {
  const availableIndexes = labels
    .map((_, index) => index)
    .filter((index) => datasets.some((dataset) => (
      typeof dataset.data[index] === 'number'
      && Number.isFinite(dataset.data[index])
    )));
  const indexes = maxDataPoints
    ? availableIndexes.slice(-maxDataPoints)
    : availableIndexes;

  return {
    labels: indexes.map((index) => labels[index]),
    datasets: datasets.map((dataset) => ({
      ...dataset,
      data: indexes.map((index) => dataset.data[index] ?? null),
    })),
  };
}

function toChartDatasets(
  datasets: ChartDatasetInput[],
): Array<ChartDataset<'line', Array<number | null>>> {
  return datasets.map((dataset) => ({
    label: dataset.label,
    data: dataset.data,
    borderColor: dataset.color,
    backgroundColor: `${dataset.color}18`,
    borderWidth: 2,
    pointRadius: 0,
    pointHoverRadius: 4,
    pointHoverBackgroundColor: dataset.color,
    tension: 0.32,
    fill: true,
    spanGaps: true,
  }));
}

export const ChartWidget: Component<ChartWidgetProps> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chart: Chart<'line'> | null = null;

  onMount(() => {
    const context = canvasRef?.getContext('2d');
    if (!context) return;

    const initial = normalizeData(
      props.labels,
      props.datasets,
      props.maxDataPoints,
    );
    chart = new Chart<'line'>(context, {
      type: 'line',
      data: {
        labels: initial.labels,
        datasets: toChartDatasets(initial.datasets),
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
              color: '#8f9ba5',
              boxWidth: 10,
              padding: 10,
              font: {
                size: 10,
                family: "'JetBrains Mono', 'Cascadia Code', monospace",
              },
            },
          },
          tooltip: {
            backgroundColor: '#1b232b',
            titleColor: '#75ded5',
            bodyColor: '#edf2f4',
            borderColor: '#2c353d',
            borderWidth: 1,
            padding: 10,
            cornerRadius: 6,
            bodyFont: {
              family: "'JetBrains Mono', 'Cascadia Code', monospace",
              size: 11,
            },
            callbacks: {
              label: (context: TooltipItem<'line'>) => {
                const dataset = props.datasets[context.datasetIndex];
                const unit = dataset?.unit || '%';
                const value = context.parsed.y;
                return `${context.dataset.label}: ${value === null ? '不可用' : value.toFixed(1)}${value === null ? '' : unit}`;
              },
            },
          },
        },
        scales: {
          x: {
            display: true,
            grid: { color: 'rgba(143, 155, 165, 0.08)' },
            ticks: {
              color: '#66737d',
              maxTicksLimit: 8,
              font: {
                size: 9,
                family: "'JetBrains Mono', 'Cascadia Code', monospace",
              },
            },
          },
          y: {
            min: props.yMin ?? 0,
            max: props.yMax,
            grid: { color: 'rgba(143, 155, 165, 0.08)' },
            ticks: {
              color: '#66737d',
              font: {
                size: 9,
                family: "'JetBrains Mono', 'Cascadia Code', monospace",
              },
              callback: (value) => `${value}${props.datasets[0]?.unit || '%'}`,
            },
          },
        },
      },
    });

    createEffect(() => {
      const next = normalizeData(
        props.labels,
        props.datasets,
        props.maxDataPoints,
      );
      if (!chart) return;
      chart.data.labels = next.labels;
      chart.data.datasets = toChartDatasets(next.datasets);
      chart.update('none');
    });

    props.onReady?.({
      pushData(newLabels, newDatasets) {
        if (!chart) return;
        const next = normalizeData(
          newLabels,
          props.datasets.map((dataset, index) => ({
            ...dataset,
            data: newDatasets[index] || [],
          })),
          props.maxDataPoints,
        );
        chart.data.labels = next.labels;
        chart.data.datasets = toChartDatasets(next.datasets);
        chart.update('none');
      },
    });
  });

  onCleanup(() => {
    chart?.destroy();
    chart = null;
  });

  return (
    <div
      class="chart-widget"
      style={{ height: `${props.height || 140}px` }}
      role="img"
      aria-label={props.title}
    >
      <canvas ref={canvasRef} aria-hidden="true" />
    </div>
  );
};
