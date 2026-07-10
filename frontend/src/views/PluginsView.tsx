import { Download, Play, Power } from 'lucide-solid';
import { For, Show, createSignal } from 'solid-js';
import { useRuntimeResources } from '../app/runtime-resources';
import { createPollingResource } from '../primitives/create-polling-resource';
import { jarvisApi } from '../services/jarvis-api';
import type { PluginInfo } from '../types/api';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { ResourceState } from '../components/ui/ResourceState';
import { StatusIndicator } from '../components/ui/StatusIndicator';
import { useToast } from '../components/ui/ToastHost';

type PluginAction = 'load' | 'enable' | 'disable';

function lifecycleAction(status: string): PluginAction | undefined {
  if (status === 'discovered' || status === 'unloaded') return 'load';
  if (status === 'loaded' || status === 'disabled') return 'enable';
  if (status === 'enabled') return 'disable';
  return undefined;
}

function actionLabel(action: PluginAction) {
  if (action === 'load') return '加载';
  if (action === 'enable') return '启用';
  return '停用';
}

function statusTone(status: string) {
  if (status === 'enabled') return 'success' as const;
  if (status === 'error') return 'error' as const;
  if (status === 'disabled') return 'warning' as const;
  return 'neutral' as const;
}

export function PluginsView() {
  const resources = useRuntimeResources();
  const toast = useToast();
  const [pendingPlugin, setPendingPlugin] = createSignal<string>();
  const coreAvailable = () => (
    resources.capabilities.data()?.core_api.available === true
  );
  const plugins = createPollingResource({
    load: jarvisApi.plugins,
    intervalMs: 30_000,
    enabled: coreAvailable,
    classify: (value) => value.plugins.length ? 'ready' : 'empty',
  });

  const runAction = async (action: PluginAction, plugin: PluginInfo) => {
    if (pendingPlugin()) return;
    setPendingPlugin(plugin.id);
    try {
      await jarvisApi.pluginAction(action, plugin.id);
      await plugins.refresh();
      toast.success(`${plugin.name} 已${actionLabel(action)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '插件操作失败');
    } finally {
      setPendingPlugin(undefined);
    }
  };

  const capabilityLoading = () => resources.capabilities.phase() === 'loading';

  return (
    <div class="view-stack">
      <header class="view-heading">
        <div>
          <h1>插件与工具</h1>
          <p>查看插件权限，并通过受控 Core API 管理生命周期。</p>
        </div>
      </header>

      <Show
        when={coreAvailable()}
        fallback={(
          <div class="capability-state" role="status">
            <strong>{capabilityLoading() ? '正在检查 Core API' : 'Core API 未连接'}</strong>
            <span>插件清单与生命周期控制暂不可用。</span>
          </div>
        )}
      >
        <section class="view-section" aria-labelledby="plugin-list-title">
          <div class="section-heading">
            <div>
              <h2 id="plugin-list-title">已发现插件</h2>
              <p>{plugins.data()?.plugins.length || 0} 个插件实例</p>
            </div>
          </div>
          <ResourceState
            phase={plugins.phase()}
            title={plugins.phase() === 'empty' ? '未检测到插件' : '插件列表不可用'}
            description={plugins.error()?.message}
            onRetry={() => void plugins.refresh()}
          >
            <Show when={plugins.data()}>
              {(collection) => (
                <div class="plugin-list" role="list">
                  <For each={collection().plugins}>
                    {(plugin) => {
                      const action = () => lifecycleAction(plugin.status);
                      return (
                        <article class="plugin-row" role="listitem">
                          <div class="plugin-row__main">
                            <div class="plugin-row__heading">
                              <div>
                                <strong>{plugin.name}</strong>
                                <code>{plugin.id}</code>
                              </div>
                              <StatusIndicator
                                label={plugin.status}
                                tone={statusTone(plugin.status)}
                                compact
                              />
                            </div>
                            <span class="plugin-version">v{plugin.version}</span>
                            <div class="permission-list" aria-label="插件权限">
                              <Show when={plugin.permissions.length > 0} fallback={<span>无声明权限</span>}>
                                <For each={plugin.permissions}>
                                  {(permission) => <code>{permission}</code>}
                                </For>
                              </Show>
                            </div>
                          </div>
                          <Show when={action()}>
                            {(nextAction) => (
                              <div class="plugin-row__action">
                                <Show
                                  when={nextAction() === 'disable'}
                                  fallback={(
                                    <button
                                      type="button"
                                      class="button button--secondary button--with-icon"
                                      aria-label={`${actionLabel(nextAction())} ${plugin.name}`}
                                      disabled={pendingPlugin() === plugin.id}
                                      onClick={() => void runAction(nextAction(), plugin)}
                                    >
                                      {nextAction() === 'load'
                                        ? <Download size={16} aria-hidden="true" />
                                        : <Play size={16} aria-hidden="true" />}
                                      {actionLabel(nextAction())}
                                    </button>
                                  )}
                                >
                                  <ConfirmDialog
                                    title={`停用 ${plugin.name}？`}
                                    description="插件将停止接收事件，之后仍可重新启用。"
                                    triggerLabel={`停用 ${plugin.name}`}
                                    triggerIcon={Power}
                                    confirmLabel="确认停用"
                                    onConfirm={() => void runAction('disable', plugin)}
                                    tone="danger"
                                  />
                                </Show>
                              </div>
                            )}
                          </Show>
                        </article>
                      );
                    }}
                  </For>
                </div>
              )}
            </Show>
          </ResourceState>
        </section>
      </Show>
    </div>
  );
}
