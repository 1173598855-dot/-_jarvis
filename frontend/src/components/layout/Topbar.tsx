import {
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-solid';
import {
  createSignal,
  onCleanup,
  onMount,
} from 'solid-js';
import { useRuntimeResources } from '../../app/runtime-resources';
import { IconButton } from '../ui/IconButton';
import { StatusIndicator } from '../ui/StatusIndicator';

export interface TopbarProps {
  title: string;
  statusOpen: boolean;
  onToggleStatus(): void;
  onOpenStatusDrawer(): void;
}

function formatClock(date: Date) {
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function Topbar(props: TopbarProps) {
  const resources = useRuntimeResources();
  const [clock, setClock] = createSignal(formatClock(new Date()));
  let clockTimer: number | undefined;

  const overallHealth = () => {
    const phases = [
      resources.system.phase(),
      resources.ollama.phase(),
      resources.git.phase(),
      resources.capabilities.phase(),
    ];
    if (phases.some((phase) => phase === 'error')) {
      return { label: '服务异常', tone: 'error' as const };
    }
    if (phases.some((phase) => phase === 'stale' || phase === 'degraded')) {
      return { label: '部分服务受限', tone: 'warning' as const };
    }
    if (phases.some((phase) => phase === 'loading')) {
      return { label: '正在连接', tone: 'neutral' as const };
    }
    return { label: '本地服务正常', tone: 'success' as const };
  };

  onMount(() => {
    clockTimer = window.setInterval(() => setClock(formatClock(new Date())), 1000);
  });

  onCleanup(() => {
    if (clockTimer !== undefined) window.clearInterval(clockTimer);
  });

  return (
    <header class="command-topbar">
      <div class="command-topbar__identity">
        <strong class="command-topbar__mobile-brand">J.A.R.V.I.S.</strong>
        <span class="command-topbar__title">{props.title}</span>
      </div>
      <div class="command-topbar__actions">
        <StatusIndicator
          label={overallHealth().label}
          tone={overallHealth().tone}
          compact
        />
        <time class="command-topbar__clock">{clock()}</time>
        <IconButton
          label={props.statusOpen ? '收起状态栏' : '展开状态栏'}
          icon={props.statusOpen ? PanelRightClose : PanelRightOpen}
          onClick={props.onToggleStatus}
          class="command-topbar__status-toggle"
        />
        <IconButton
          label="打开状态抽屉"
          icon={PanelRightOpen}
          onClick={props.onOpenStatusDrawer}
          class="command-topbar__drawer-trigger"
        />
      </div>
    </header>
  );
}
