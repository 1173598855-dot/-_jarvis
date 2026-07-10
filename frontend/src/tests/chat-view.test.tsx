import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@solidjs/testing-library';
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import { ToastProvider } from '../components/ui/ToastHost';
import { ChatView } from '../views/ChatView';

const mocks = vi.hoisted(() => ({
  models: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock('../services/jarvis-api', () => ({
  jarvisApi: {
    models: mocks.models,
  },
}));

vi.mock('../services/chat-stream', () => ({
  streamChat: mocks.streamChat,
}));

function renderChat() {
  return render(() => (
    <ToastProvider>
      <ChatView />
    </ToastProvider>
  ));
}

beforeAll(() => {
  Object.defineProperty(window, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  });
});

async function enterMessage(message = '检查项目') {
  const input = await screen.findByLabelText<HTMLTextAreaElement>('消息输入');
  fireEvent.input(input, { target: { value: message } });
  return input;
}

beforeEach(() => {
  mocks.models.mockReset().mockResolvedValue({
    models: [
      { name: 'qwen2.5:7b', size: 4_700_000_000 },
      { name: 'deepseek-r1:8b', size: 5_100_000_000 },
    ],
  });
  mocks.streamChat.mockReset().mockImplementation(async (_request, handlers) => {
    handlers.onDelta('部分响应');
  });
});

afterEach(() => {
  cleanup();
});

describe('ChatView', () => {
  it('loads models, selects the first model, and enables send for non-empty input', async () => {
    renderChat();

    const modelSelect = await screen.findByRole('button', { name: /^模型/ });
    expect(modelSelect.textContent).toContain('qwen2.5:7b');

    const sendButton = screen.getByRole<HTMLButtonElement>('button', { name: '发送' });
    expect(sendButton.getAttribute('aria-disabled')).toBe('true');
    await enterMessage();
    expect(sendButton.hasAttribute('aria-disabled')).toBe(false);
  });

  it('adds user and assistant rows while streamed text arrives', async () => {
    renderChat();
    await enterMessage();
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('检查项目')).not.toBeNull();
    expect(await screen.findByText('部分响应')).not.toBeNull();
    expect(mocks.streamChat).toHaveBeenCalledWith(
      {
        model: 'qwen2.5:7b',
        messages: [{ role: 'user', content: '检查项目' }],
      },
      expect.objectContaining({ onDelta: expect.any(Function) }),
      expect.any(AbortSignal),
    );
  });

  it('stops streaming without deleting generated content', async () => {
    let capturedSignal: AbortSignal | undefined;
    mocks.streamChat.mockImplementation(async (_request, handlers, signal) => {
      capturedSignal = signal;
      handlers.onDelta('部分响应');
      await new Promise<void>((_resolve, reject) => {
        signal.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        }, { once: true });
      });
    });
    renderChat();
    await enterMessage();
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('部分响应')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '停止生成' }));

    await waitFor(() => expect(capturedSignal?.aborted).toBe(true));
    expect(screen.getByText('部分响应')).not.toBeNull();
  });

  it('retries the last user prompt', async () => {
    renderChat();
    await enterMessage();
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByText('部分响应');

    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    await waitFor(() => expect(mocks.streamChat).toHaveBeenCalledTimes(2));
    const retryRequest = mocks.streamChat.mock.calls[1][0];
    expect(retryRequest.messages.at(-1)).toEqual({
      role: 'user',
      content: '检查项目',
    });
  });

  it('requires confirmation before clearing and restores input focus', async () => {
    renderChat();
    const input = await enterMessage();
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByText('部分响应');

    const clearButton = screen.getByRole('button', { name: '清空对话' });
    expect(clearButton.querySelector('svg')).not.toBeNull();
    fireEvent.click(clearButton);
    expect(screen.getByText('检查项目')).not.toBeNull();

    fireEvent.click(await screen.findByRole('button', { name: '确认清空' }));

    await waitFor(() => expect(screen.queryByText('检查项目')).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(input));
  });

  it('sends with Enter and keeps Shift+Enter content intact', async () => {
    renderChat();
    const input = await enterMessage('第一行\n第二行');

    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(mocks.streamChat).not.toHaveBeenCalled();
    expect(input.value).toBe('第一行\n第二行');

    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(mocks.streamChat).toHaveBeenCalledOnce());
  });

  it('renders assistant Markdown as safe semantic elements', async () => {
    mocks.streamChat.mockImplementation(async (_request, handlers) => {
      handlers.onDelta('执行 `npm run build`');
    });
    renderChat();
    await enterMessage();
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    const code = await screen.findByText('npm run build');
    expect(code.tagName).toBe('CODE');
  });
});
