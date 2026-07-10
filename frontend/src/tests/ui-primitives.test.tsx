import { fireEvent, render, screen } from '@solidjs/testing-library';
import { RefreshCw } from 'lucide-solid';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { IconButton } from '../components/ui/IconButton';
import { ResourceState } from '../components/ui/ResourceState';
import { ToastProvider, useToast } from '../components/ui/ToastHost';

beforeAll(() => {
  Object.defineProperty(window, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  });
});

describe('UI primitives', () => {
  it('gives icon controls an accessible name', () => {
    render(() => (
      <IconButton
        label="刷新模型"
        icon={RefreshCw}
        onClick={() => undefined}
      />
    ));

    expect(screen.getByRole('button', { name: '刷新模型' })).not.toBeNull();
  });

  it('confirms destructive actions explicitly', async () => {
    const onConfirm = vi.fn();
    render(() => (
      <ConfirmDialog
        title="清空对话？"
        description="当前消息将被移除。"
        triggerLabel="清空对话"
        confirmLabel="确认清空"
        onConfirm={onConfirm}
      />
    ));

    fireEvent.click(screen.getByRole('button', { name: '清空对话' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认清空' }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('renders a retry action for an error resource', () => {
    render(() => (
      <ResourceState
        phase="error"
        title="系统指标不可用"
        onRetry={() => undefined}
      />
    ));

    expect(screen.getByText('系统指标不可用')).not.toBeNull();
    expect(screen.getByRole('button', { name: '重试' })).not.toBeNull();
  });

  it('announces success feedback through the toast context', async () => {
    const Trigger = () => {
      const toast = useToast();
      return (
        <button type="button" onClick={() => toast.success('记忆已保存')}>
          保存
        </button>
      );
    };

    render(() => (
      <ToastProvider>
        <Trigger />
      </ToastProvider>
    ));
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    expect(await screen.findByText('记忆已保存')).not.toBeNull();
  });
});
