import * as Collapsible from '@kobalte/core/collapsible';
import ChevronDown from 'lucide-solid/icons/chevron-down';
import ChevronUp from 'lucide-solid/icons/chevron-up';
import {
  For,
  Show,
  createMemo,
  createSignal,
} from 'solid-js';
import { useRuntimeResources } from '../../app/runtime-resources';
import { createPollingResource } from '../../primitives/create-polling-resource';
import { jarvisApi } from '../../services/jarvis-api';
import { ResourceState } from '../ui/ResourceState';
import { StatusIndicator } from '../ui/StatusIndicator';

function eventTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || '时间不可用';
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function timestamp(value: string) {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function ActivityDock() {
  const resources = useRuntimeResources();
  const [open, setOpen] = createSignal(false);
  const coreAvailable = () => (
    resources.capabilities.data()?.core_api.available === true
  );
  const activity = createPollingResource({
    load: (signal) => jarvisApi.events(100, signal),
    intervalMs: 10_000,
    enabled: coreAvailable,
    classify: (value) => value.events.length ? 'ready' : 'empty',
  });
  const visibleEvents = createMemo(() => (
    [...(activity.data()?.events || [])]
      .sort((left, right) => timestamp(right.timestamp) - timestamp(left.timestamp))
      .slice(0, 100)
  ));
  const newest = () => visibleEvents()[0];
  const capabilityLoading = () => resources.capabilities.phase() === 'loading';

  return (
    <Collapsible.Root class="activity-dock" open={open()} onOpenChange={setOpen}>
      <div class="activity-dock__bar">
        <div class="activity-dock__label">
          <StatusIndicator
            label="后台活动"
            tone={coreAvailable() ? 'success' : 'warning'}
            compact
          />
          <Show
            when={coreAvailable()}
            fallback={(
              <strong>{capabilityLoading() ? '正在检查 Core API' : 'Core API 未连接'}</strong>
            )}
          >
            <Show when={newest()} fallback={<strong>暂无活动记录</strong>}>
              {(event) => (
                <div class="activity-dock__latest">
                  <time>{eventTime(event().timestamp)}</time>
                  <strong>{event().type}</strong>
                  <span>{event().source || '未知来源'}</span>
                </div>
              )}
            </Show>
          </Show>
        </div>
        <Collapsible.Trigger
          class="activity-dock__trigger"
          aria-label={open() ? '收起活动' : '展开活动'}
          disabled={!coreAvailable()}
        >
          {open()
            ? <ChevronDown size={17} aria-hidden="true" />
            : <ChevronUp size={17} aria-hidden="true" />}
        </Collapsible.Trigger>
      </div>

      <Collapsible.Content class="activity-dock__content">
        <ResourceState
          phase={activity.phase()}
          title={activity.phase() === 'empty' ? '暂无活动记录' : '活动历史不可用'}
          description={activity.error()?.message}
          onRetry={() => void activity.refresh()}
        >
          <ol class="activity-list">
            <For each={visibleEvents()}>
              {(event) => (
                <li class="activity-row">
                  <time>{eventTime(event.timestamp)}</time>
                  <strong>{event.type}</strong>
                  <span>{event.source || '未知来源'}</span>
                  <code>{event.payload}</code>
                </li>
              )}
            </For>
          </ol>
        </ResourceState>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}
