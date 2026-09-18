import Blocks from 'lucide-solid/icons/blocks';
import Braces from 'lucide-solid/icons/braces';
import Download from 'lucide-solid/icons/download';
import PackageSearch from 'lucide-solid/icons/package-search';
import Play from 'lucide-solid/icons/play';
import Power from 'lucide-solid/icons/power';
import Wrench from 'lucide-solid/icons/wrench';
import {
  For,
  Match,
  Show,
  Switch,
  createMemo,
  createSignal,
} from 'solid-js';
import { useRuntimeResources } from '../app/runtime-resources';
import { createPollingResource } from '../primitives/create-polling-resource';
import { jarvisApi } from '../services/jarvis-api';
import type {
  CapabilityKind,
  CapabilityRecord,
  PluginInfo,
} from '../types/api';
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

function kindLabel(kind: CapabilityKind) {
  if (kind === 'skill') return 'Skill';
  if (kind === 'plugin') return 'Plugin';
  if (kind === 'role_tool') return '角色工具';
  return 'UI 组件';
}

function compatibilityTone(status: CapabilityRecord['compatibility']['status']) {
  if (status === 'compatible') return 'success' as const;
  if (status === 'incompatible') return 'error' as const;
  return 'neutral' as const;
}

function provenanceTone(status: CapabilityRecord['provenance']['status']) {
  if (status === 'verified') return 'success' as const;
  if (status === 'incomplete') return 'warning' as const;
  return 'neutral' as const;
}

function healthTone(status: CapabilityRecord['health']['status']) {
  if (status === 'healthy') return 'success' as const;
  if (status === 'degraded') return 'warning' as const;
  return 'error' as const;
}

function riskTone(level: CapabilityRecord['risk']['level']) {
  if (level === 'low') return 'success' as const;
  if (level === 'medium') return 'warning' as const;
  return 'error' as const;
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
  const registry = createPollingResource({
    load: jarvisApi.capabilityRegistry,
    intervalMs: 30_000,
    enabled: coreAvailable,
    classify: (value) => {
      if (value.issues.length > 0 || value.capabilities.some(
        (capability) => capability.health.status !== 'healthy',
      )) return 'degraded';
      return value.capabilities.length === 0 ? 'empty' : 'ready';
    },
  });
  const kindCounts = createMemo(() => {
    const counts: Record<CapabilityKind, number> = {
      skill: 0,
      plugin: 0,
      role_tool: 0,
      ui_component: 0,
    };
    for (const capability of registry.data()?.capabilities || []) {
      counts[capability.kind] += 1;
    }
    return counts;
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
  const registryTitle = () => {
    if (registry.phase() === 'loading') return '正在读取能力注册表';
    if (registry.phase() === 'empty') return '未发现已注册能力';
    if (registry.phase() === 'degraded') return '部分能力元数据异常';
    if (registry.phase() === 'stale') return '能力注册表刷新失败';
    return '能力注册表不可用';
  };

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
        <section class="view-section" aria-labelledby="capability-registry-title">
          <div class="section-heading section-heading--capabilities">
            <div>
              <h2 id="capability-registry-title">能力注册表</h2>
              <p>{registry.data()?.count || 0} 个本地记录</p>
            </div>
            <Show when={registry.data()}>
              <div class="capability-summary" aria-label="能力类型统计">
                <span>{kindCounts().skill} Skill</span>
                <span>{kindCounts().plugin} Plugin</span>
                <span>{kindCounts().role_tool} 角色工具</span>
                <span>{kindCounts().ui_component} UI 组件</span>
              </div>
            </Show>
          </div>
          <ResourceState
            phase={registry.phase()}
            title={registryTitle()}
            description={registry.error()?.message}
            onRetry={() => void registry.refresh()}
          >
            <Show when={registry.data()}>
              {(snapshot) => (
                <div class="capability-list" role="list">
                  <For each={snapshot().capabilities}>
                    {(capability) => (
                      <article
                        class="capability-record"
                        role="listitem"
                        aria-label={`能力 ${capability.name}`}
                      >
                        <span class="capability-record__icon" aria-hidden="true">
                          <Switch>
                            <Match when={capability.kind === 'skill'}>
                              <Blocks size={17} />
                            </Match>
                            <Match when={capability.kind === 'plugin'}>
                              <PackageSearch size={17} />
                            </Match>
                            <Match when={capability.kind === 'role_tool'}>
                              <Wrench size={17} />
                            </Match>
                            <Match when={capability.kind === 'ui_component'}>
                              <Braces size={17} />
                            </Match>
                          </Switch>
                        </span>
                        <div class="capability-record__body">
                          <div class="capability-record__heading">
                            <div class="capability-record__identity">
                              <strong>{capability.name}</strong>
                              <code>{capability.capability_id}</code>
                            </div>
                            <StatusIndicator
                              label={capability.lifecycle}
                              tone={statusTone(capability.lifecycle)}
                              compact
                            />
                          </div>
                          <Show when={capability.description}>
                            <p>{capability.description}</p>
                          </Show>
                          <div class="capability-record__origin">
                            <span>{kindLabel(capability.kind)}</span>
                            <code>{capability.relative_path}</code>
                            <span>{capability.provenance.source_url || '本地仓库'}</span>
                            <span>{capability.provenance.license || '许可证未知'}</span>
                          </div>
                          <div class="capability-record__signals" aria-label="能力状态">
                            <StatusIndicator
                              label={`来源 ${capability.provenance.status}`}
                              tone={provenanceTone(capability.provenance.status)}
                              compact
                            />
                            <StatusIndicator
                              label={`兼容 ${capability.compatibility.status}`}
                              tone={compatibilityTone(capability.compatibility.status)}
                              compact
                            />
                            <StatusIndicator
                              label={`健康 ${capability.health.status}`}
                              tone={healthTone(capability.health.status)}
                              compact
                            />
                            <StatusIndicator
                              label={`风险 ${capability.risk.level}`}
                              tone={riskTone(capability.risk.level)}
                              compact
                            />
                          </div>
                          <div class="permission-list" aria-label="能力权限">
                            <Show
                              when={capability.permissions.length > 0}
                              fallback={<span>无声明权限</span>}
                            >
                              <For each={capability.permissions}>
                                {(permission) => <code>{permission}</code>}
                              </For>
                            </Show>
                          </div>
                        </div>
                      </article>
                    )}
                  </For>
                </div>
              )}
            </Show>
          </ResourceState>
        </section>

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
