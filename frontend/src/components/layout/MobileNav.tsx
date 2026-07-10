import * as Dialog from '@kobalte/core/dialog';
import Ellipsis from 'lucide-solid/icons/ellipsis';
import X from 'lucide-solid/icons/x';
import {
  For,
  createSignal,
} from 'solid-js';
import { Dynamic } from 'solid-js/web';
import {
  navigation,
  type ViewId,
} from '../../app/navigation';

export interface MobileNavProps {
  activeView: ViewId;
  onNavigate(view: ViewId): void;
}

export function MobileNav(props: MobileNavProps) {
  const [moreOpen, setMoreOpen] = createSignal(false);
  const primary = navigation.filter((item) => item.mobile === 'primary');
  const more = navigation.filter((item) => item.mobile === 'more');
  const moreIsActive = () => more.some((item) => item.id === props.activeView);

  const navigate = (view: ViewId) => {
    props.onNavigate(view);
    setMoreOpen(false);
  };

  return (
    <nav class="mobile-navigation" aria-label="移动导航">
      <For each={primary}>
        {(item) => (
          <button
            type="button"
            aria-label={item.label}
            aria-current={props.activeView === item.id ? 'page' : undefined}
            onClick={() => navigate(item.id)}
          >
            <Dynamic component={item.icon} size={19} strokeWidth={1.8} aria-hidden="true" />
            <span>{item.label === '运行监控' ? '运行' : item.label.replace('代码', '')}</span>
          </button>
        )}
      </For>

      <Dialog.Root open={moreOpen()} onOpenChange={setMoreOpen}>
        <Dialog.Trigger
          class="mobile-navigation__more"
          aria-label="更多"
          aria-current={moreIsActive() ? 'page' : undefined}
        >
          <Ellipsis size={20} strokeWidth={1.8} aria-hidden="true" />
          <span>更多</span>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay class="dialog-overlay" />
          <div class="mobile-more-positioner">
            <Dialog.Content class="mobile-more-content">
              <div class="mobile-more-header">
                <Dialog.Title>更多视图</Dialog.Title>
                <Dialog.CloseButton aria-label="关闭更多视图">
                  <X size={18} aria-hidden="true" />
                </Dialog.CloseButton>
              </div>
              <div class="mobile-more-list">
                <For each={more}>
                  {(item) => (
                    <button
                      type="button"
                      aria-label={item.label}
                      aria-current={props.activeView === item.id ? 'page' : undefined}
                      onClick={() => navigate(item.id)}
                    >
                      <Dynamic component={item.icon} size={18} strokeWidth={1.8} aria-hidden="true" />
                      <span>{item.label}</span>
                    </button>
                  )}
                </For>
              </div>
            </Dialog.Content>
          </div>
        </Dialog.Portal>
      </Dialog.Root>
    </nav>
  );
}
