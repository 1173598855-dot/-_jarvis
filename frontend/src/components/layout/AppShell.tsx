import * as Dialog from '@kobalte/core/dialog';
import { X } from 'lucide-solid';
import {
  createSignal,
  type JSX,
} from 'solid-js';
import {
  navigationItem,
  type ViewId,
} from '../../app/navigation';
import { ActivityDock } from './ActivityDock';
import { MobileNav } from './MobileNav';
import { Sidebar } from './Sidebar';
import { StatusRail } from './StatusRail';
import { Topbar } from './Topbar';

export interface AppShellProps {
  activeView: ViewId;
  onNavigate(view: ViewId): void;
  children: JSX.Element;
}

export function AppShell(props: AppShellProps) {
  const [statusOpen, setStatusOpen] = createSignal(true);
  const [drawerOpen, setDrawerOpen] = createSignal(false);

  return (
    <div class={`command-shell ${statusOpen() ? '' : 'command-shell--status-collapsed'}`}>
      <Sidebar activeView={props.activeView} onNavigate={props.onNavigate} />

      <div class="command-shell__center">
        <Topbar
          title={navigationItem(props.activeView).label}
          statusOpen={statusOpen()}
          onToggleStatus={() => setStatusOpen((open) => !open)}
          onOpenStatusDrawer={() => setDrawerOpen(true)}
        />
        <main
          class="command-shell__viewport"
          data-shell-region="main"
          aria-label={`${navigationItem(props.activeView).label}工作区`}
        >
          <div class="active-view" data-testid="active-view">
            {props.children}
          </div>
        </main>
        <ActivityDock />
        <MobileNav activeView={props.activeView} onNavigate={props.onNavigate} />
      </div>

      <div class="command-shell__status" data-shell-region="status">
        <StatusRail />
      </div>

      <Dialog.Root open={drawerOpen()} onOpenChange={setDrawerOpen}>
        <Dialog.Portal>
          <Dialog.Overlay class="dialog-overlay" />
          <div class="mobile-status-positioner">
            <Dialog.Content class="mobile-status-content">
              <div class="mobile-status-header">
                <Dialog.Title>实时状态</Dialog.Title>
                <Dialog.CloseButton aria-label="关闭状态抽屉">
                  <X size={18} aria-hidden="true" />
                </Dialog.CloseButton>
              </div>
              <StatusRail />
            </Dialog.Content>
          </div>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
