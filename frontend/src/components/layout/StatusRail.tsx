import { Show, type JSX } from 'solid-js';
import RefreshCw from 'lucide-solid/icons/refresh-cw';
import { useRuntimeResources } from '../../app/runtime-resources';
import type { PollingResource } from '../../primitives/create-polling-resource';
import { IconButton } from '../ui/IconButton';
import { ResourceState } from '../ui/ResourceState';
import { StatusIndicator } from '../ui/StatusIndicator';

function formatTime(value: number | undefined) {
  if (value === undefined) return '--:--:--';
  return new Date(value).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function formatPercent(value: number | null) {
  return value === null ? '不可用' : `${value.toFixed(1)}%`;
}

function toneForPhase(phase: ReturnType<PollingResource<unknown>['phase']>) {
  if (phase === 'ready') return 'success' as const;
  if (phase === 'error') return 'error' as const;
  if (phase === 'degraded' || phase === 'stale') return 'warning' as const;
  return 'neutral' as const;
}

interface StatusSectionProps {
  title: string;
  refreshLabel: string;
  resource: PollingResource<unknown>;
  renderEmpty?: boolean;
  children: JSX.Element;
}

function StatusSection(props: StatusSectionProps) {
  const contentPhase = () => (
    props.renderEmpty && props.resource.phase() === 'empty'
      ? 'ready'
      : props.resource.phase()
  );

  return (
    <section class="status-rail__section">
      <div class="status-rail__heading">
        <StatusIndicator
          label={props.title}
          tone={toneForPhase(props.resource.phase())}
          compact
        />
        <IconButton
          label={props.refreshLabel}
          icon={RefreshCw}
          onClick={() => void props.resource.refresh()}
          class="status-rail__refresh"
        />
      </div>
      <ResourceState
        phase={contentPhase()}
        title={`${props.title}状态不可用`}
        description={props.resource.error()?.message}
        onRetry={() => void props.resource.refresh()}
      >
        {props.children}
      </ResourceState>
      <time class="status-rail__time">
        {formatTime(props.resource.updatedAt())}
      </time>
    </section>
  );
}

export function StatusRail() {
  const resources = useRuntimeResources();
  const system = () => resources.system.data();
  const ollama = () => resources.ollama.data();
  const git = () => resources.git.data();
  const tokens = () => resources.tokens.data();

  return (
    <aside class="status-rail" aria-label="实时状态">
      <header class="status-rail__title">
        <h2>实时状态</h2>
        <span>共享轮询资源</span>
      </header>

      <StatusSection
        title="系统"
        refreshLabel="刷新系统状态"
        resource={resources.system}
      >
        <Show when={system()}>
          {(stats) => (
            <div class="status-rail__summary" data-testid="status-rail-cpu">
              <strong>{formatPercent(stats().cpu.usage)}</strong>
              <span>CPU · 内存 {formatPercent(stats().memory.usage)}</span>
            </div>
          )}
        </Show>
      </StatusSection>

      <StatusSection
        title="Ollama"
        refreshLabel="刷新 Ollama 状态"
        resource={resources.ollama}
      >
        <Show when={ollama()}>
          {(status) => (
            <div class="status-rail__summary">
              <strong>{status().running ? '在线' : '离线'}</strong>
              <span>{status().models.length} 个本地模型</span>
            </div>
          )}
        </Show>
      </StatusSection>

      <StatusSection
        title="Git"
        refreshLabel="刷新 Git 状态"
        resource={resources.git}
      >
        <Show when={git()}>
          {(status) => (
            <div class="status-rail__summary">
              <strong class="status-rail__branch">{status().branch}</strong>
              <span>{status().clean ? '工作区干净' : `${status().count} 个文件变更`}</span>
            </div>
          )}
        </Show>
      </StatusSection>

      <StatusSection
        title="Token"
        refreshLabel="刷新 Token 状态"
        resource={resources.tokens}
        renderEmpty
      >
        <Show when={tokens()}>
          {(snapshot) => (
            <div class="status-rail__summary">
              <strong>{(() => {
                const latest = snapshot().latest;
                return latest ? latest.total_tokens.toLocaleString() : '尚无记录';
              })()}</strong>
              <span>最近一次调用</span>
            </div>
          )}
        </Show>
      </StatusSection>
    </aside>
  );
}
