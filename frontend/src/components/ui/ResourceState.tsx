import { Show, type JSX } from 'solid-js';
import type { ResourcePhase } from '../../types/api';

export interface ResourceStateProps {
  phase: ResourcePhase;
  title?: string;
  description?: string;
  onRetry?(): void;
  children?: JSX.Element;
}

const defaultTitles: Record<ResourcePhase, string> = {
  loading: '正在加载',
  ready: '',
  empty: '暂无数据',
  stale: '数据暂时无法刷新',
  degraded: '部分数据不可用',
  error: '数据加载失败',
};

export function ResourceState(props: ResourceStateProps) {
  const title = () => props.title || defaultTitles[props.phase];
  const hasContent = () => ['ready', 'stale', 'degraded'].includes(props.phase);

  return (
    <div class={`resource-state resource-state--${props.phase}`} data-phase={props.phase}>
      <Show when={props.phase === 'loading'}>
        <div class="resource-skeleton" aria-label={title()} aria-busy="true">
          <span />
          <span />
          <span />
        </div>
      </Show>

      <Show when={props.phase !== 'loading' && props.phase !== 'ready'}>
        <div class="resource-state__message" role={props.phase === 'error' ? 'alert' : 'status'}>
          <strong>{title()}</strong>
          <Show when={props.description}>
            <span>{props.description}</span>
          </Show>
          <Show when={props.onRetry && (props.phase === 'error' || props.phase === 'stale')}>
            <button type="button" class="text-button" onClick={() => props.onRetry?.()}>
              重试
            </button>
          </Show>
        </div>
      </Show>

      <Show when={hasContent()}>{props.children}</Show>
    </div>
  );
}
