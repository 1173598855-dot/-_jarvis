import {
  Match,
  Suspense,
  Switch,
  createSignal,
  lazy,
  type Component,
} from 'solid-js';
import { RuntimeResourcesProvider } from './app/runtime-resources';
import type { ViewId } from './app/navigation';
import { AppShell } from './components/layout/AppShell';
import { ToastProvider } from './components/ui/ToastHost';

const ChatView = lazy(() => import('./views/ChatView').then((module) => ({
  default: module.ChatView,
})));
const RuntimeView = lazy(() => import('./views/RuntimeView').then((module) => ({
  default: module.RuntimeView,
})));
const RepositoryView = lazy(() => import('./views/RepositoryView').then((module) => ({
  default: module.RepositoryView,
})));
const ModelsView = lazy(() => import('./views/ModelsView').then((module) => ({
  default: module.ModelsView,
})));
const MemoryView = lazy(() => import('./views/MemoryView').then((module) => ({
  default: module.MemoryView,
})));
const PluginsView = lazy(() => import('./views/PluginsView').then((module) => ({
  default: module.PluginsView,
})));

export const App: Component = () => {
  const [activeView, setActiveView] = createSignal<ViewId>('chat');

  const view = () => (
    <Suspense fallback={<div class="view-loading" aria-label="正在加载视图" />}>
      <Switch>
        <Match when={activeView() === 'chat'}><ChatView /></Match>
        <Match when={activeView() === 'runtime'}><RuntimeView /></Match>
        <Match when={activeView() === 'repository'}><RepositoryView /></Match>
        <Match when={activeView() === 'models'}><ModelsView /></Match>
        <Match when={activeView() === 'memory'}><MemoryView /></Match>
        <Match when={activeView() === 'plugins'}><PluginsView /></Match>
      </Switch>
    </Suspense>
  );

  return (
    <ToastProvider>
      <RuntimeResourcesProvider>
        <AppShell activeView={activeView()} onNavigate={setActiveView}>
          {view()}
        </AppShell>
      </RuntimeResourcesProvider>
    </ToastProvider>
  );
};
