import * as Toast from '@kobalte/core/toast';
import { toaster } from '@kobalte/core/toast';
import {
  createContext,
  useContext,
  type ParentComponent,
} from 'solid-js';
import CheckCircle2 from 'lucide-solid/icons/circle-check-big';
import CircleAlert from 'lucide-solid/icons/circle-alert';
import X from 'lucide-solid/icons/x';

export interface ToastApi {
  success(message: string): void;
  error(message: string): void;
}

const ToastContext = createContext<ToastApi>();

function showToast(tone: 'success' | 'error', message: string) {
  toaster.show((toastProps) => (
    <Toast.Root
      toastId={toastProps.toastId}
      class={`toast toast--${tone}`}
    >
      {tone === 'success'
        ? <CheckCircle2 size={18} aria-hidden="true" />
        : <CircleAlert size={18} aria-hidden="true" />}
      <Toast.Title class="toast__title">{message}</Toast.Title>
      <Toast.CloseButton class="toast__close" aria-label="关闭通知">
        <X size={16} aria-hidden="true" />
      </Toast.CloseButton>
    </Toast.Root>
  ));
}

export function ToastHost() {
  return (
    <Toast.Region aria-label="通知">
      <Toast.List class="toast-list" />
    </Toast.Region>
  );
}

export const ToastProvider: ParentComponent = (props) => {
  const api: ToastApi = {
    success: (message) => showToast('success', message),
    error: (message) => showToast('error', message),
  };

  return (
    <ToastContext.Provider value={api}>
      {props.children}
      <ToastHost />
    </ToastContext.Provider>
  );
};

export function useToast() {
  const toast = useContext(ToastContext);
  if (!toast) throw new Error('useToast 必须在 ToastProvider 内使用');
  return toast;
}
