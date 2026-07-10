import {
  createContext,
  useContext,
  type ParentComponent,
} from 'solid-js';
import {
  createPollingResource,
  type PollingResource,
} from '../primitives/create-polling-resource';
import { jarvisApi } from '../services/jarvis-api';
import type {
  CapabilityState,
  GitStatus,
  OllamaStatus,
  SystemStats,
  TokenUsageSnapshot,
} from '../types/api';

export interface RuntimeResources {
  system: PollingResource<SystemStats>;
  ollama: PollingResource<OllamaStatus>;
  git: PollingResource<GitStatus>;
  tokens: PollingResource<TokenUsageSnapshot>;
  capabilities: PollingResource<{ core_api: CapabilityState }>;
}

const RuntimeResourcesContext = createContext<RuntimeResources>();

function createRuntimeResources(): RuntimeResources {
  return {
    system: createPollingResource({
      load: jarvisApi.system,
      intervalMs: 3000,
      classify: (value) => value.meta.status,
    }),
    ollama: createPollingResource({
      load: jarvisApi.ollamaStatus,
      intervalMs: 30_000,
      classify: (value) => value.running ? 'ready' : 'degraded',
    }),
    git: createPollingResource({
      load: jarvisApi.gitStatus,
      intervalMs: 15_000,
    }),
    tokens: createPollingResource({
      load: jarvisApi.tokenUsage,
      intervalMs: 5000,
      classify: (value) => value.latest ? 'ready' : 'empty',
    }),
    capabilities: createPollingResource({
      load: jarvisApi.capabilities,
      intervalMs: 30_000,
      classify: (value) => value.core_api.available ? 'ready' : 'degraded',
    }),
  };
}

export const RuntimeResourcesProvider: ParentComponent<{
  value?: RuntimeResources;
}> = (props) => {
  const resources = props.value || createRuntimeResources();
  return (
    <RuntimeResourcesContext.Provider value={resources}>
      {props.children}
    </RuntimeResourcesContext.Provider>
  );
};

export function useRuntimeResources() {
  const resources = useContext(RuntimeResourcesContext);
  if (!resources) {
    throw new Error('useRuntimeResources 必须在 RuntimeResourcesProvider 内使用');
  }
  return resources;
}
