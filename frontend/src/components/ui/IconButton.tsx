import * as Tooltip from '@kobalte/core/tooltip';
import { Dynamic } from 'solid-js/web';
import type { LucideIcon } from 'lucide-solid';

export interface IconButtonProps {
  label: string;
  icon: LucideIcon;
  onClick(): void;
  disabled?: boolean;
  disabledReason?: string;
  variant?: 'default' | 'accent' | 'danger';
  class?: string;
}

export function IconButton(props: IconButtonProps) {
  const tooltipText = () => props.disabledReason || props.label;
  const handleClick = () => {
    if (!props.disabled) props.onClick();
  };

  return (
    <Tooltip.Root openDelay={350} closeDelay={0}>
      <Tooltip.Trigger
        as="button"
        type="button"
        class={`icon-button icon-button--${props.variant || 'default'} ${props.class || ''}`}
        aria-label={props.label}
        aria-disabled={props.disabled || undefined}
        onClick={handleClick}
      >
        <Dynamic component={props.icon} size={18} strokeWidth={1.8} aria-hidden="true" />
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content class="tooltip-content">
          {tooltipText()}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
