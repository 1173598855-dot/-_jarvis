import * as AlertDialog from '@kobalte/core/alert-dialog';
import { createSignal } from 'solid-js';

export interface ConfirmDialogProps {
  title: string;
  description: string;
  triggerLabel: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm(): void;
  tone?: 'default' | 'danger';
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  const [open, setOpen] = createSignal(false);
  const confirm = () => {
    props.onConfirm();
    setOpen(false);
  };

  return (
    <AlertDialog.Root open={open()} onOpenChange={setOpen}>
      <AlertDialog.Trigger class="icon-button" aria-label={props.triggerLabel}>
        {props.triggerLabel}
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay class="dialog-overlay" />
        <div class="dialog-positioner">
          <AlertDialog.Content class="dialog-content">
            <AlertDialog.Title class="dialog-title">
              {props.title}
            </AlertDialog.Title>
            <AlertDialog.Description class="dialog-description">
              {props.description}
            </AlertDialog.Description>
            <div class="dialog-actions">
              <AlertDialog.CloseButton
                class="button button--secondary"
                aria-label={props.cancelLabel || '取消'}
              >
                {props.cancelLabel || '取消'}
              </AlertDialog.CloseButton>
              <button
                type="button"
                class={`button ${props.tone === 'danger' ? 'button--danger' : 'button--primary'}`}
                aria-label={props.confirmLabel}
                onClick={confirm}
              >
                {props.confirmLabel}
              </button>
            </div>
          </AlertDialog.Content>
        </div>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
