import { For } from 'solid-js';
import { Dynamic } from 'solid-js/web';
import {
  navigation,
  type ViewId,
} from '../../app/navigation';

export interface SidebarProps {
  activeView: ViewId;
  onNavigate(view: ViewId): void;
}

export function Sidebar(props: SidebarProps) {
  return (
    <aside
      class="command-sidebar"
      data-shell-region="sidebar"
      aria-label="J.A.R.V.I.S."
    >
      <div class="command-sidebar__brand">
        <div class="command-sidebar__mark" aria-hidden="true">J</div>
        <div class="command-sidebar__brand-copy">
          <strong>J.A.R.V.I.S.</strong>
          <span>本地智能中枢</span>
        </div>
      </div>

      <nav class="command-sidebar__nav" aria-label="主导航">
        <For each={navigation}>
          {(item) => (
            <button
              type="button"
              class="command-sidebar__item"
              aria-label={item.label}
              aria-current={props.activeView === item.id ? 'page' : undefined}
              title={item.label}
              onClick={() => props.onNavigate(item.id)}
            >
              <Dynamic
                component={item.icon}
                size={18}
                strokeWidth={1.8}
                aria-hidden="true"
              />
              <span>{item.label}</span>
            </button>
          )}
        </For>
      </nav>

      <div class="command-sidebar__footer">
        <span>Runtime</span>
        <strong>Solid + Express</strong>
      </div>
    </aside>
  );
}
