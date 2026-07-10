import * as Select from '@kobalte/core/select';
import ChevronDown from 'lucide-solid/icons/chevron-down';
import RefreshCw from 'lucide-solid/icons/refresh-cw';
import RotateCcw from 'lucide-solid/icons/rotate-ccw';
import Send from 'lucide-solid/icons/send';
import Square from 'lucide-solid/icons/square';
import Trash2 from 'lucide-solid/icons/trash-2';
import remarkGfm from 'remark-gfm';
import { SolidMarkdown } from 'solid-markdown';
import {
  For,
  Show,
  createMemo,
  createSignal,
  onCleanup,
  onMount,
} from 'solid-js';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { IconButton } from '../components/ui/IconButton';
import { useToast } from '../components/ui/ToastHost';
import type { ChatMessage } from '../services/chat-stream';
import { streamChat } from '../services/chat-stream';
import { jarvisApi } from '../services/jarvis-api';
import type { OllamaModel } from '../types/api';

interface ViewMessage extends ChatMessage {
  id: number;
  streaming?: boolean;
  failed?: boolean;
}

type ChatPhase = 'idle' | 'streaming';
type ModelPhase = 'loading' | 'ready' | 'empty' | 'error';

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '对话请求失败';
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError';
}

export function ChatView() {
  const toast = useToast();
  const [models, setModels] = createSignal<OllamaModel[]>([]);
  const [selectedModel, setSelectedModel] = createSignal<OllamaModel | null>(null);
  const [modelPhase, setModelPhase] = createSignal<ModelPhase>('loading');
  const [messages, setMessages] = createSignal<ViewMessage[]>([]);
  const [input, setInput] = createSignal('');
  const [phase, setPhase] = createSignal<ChatPhase>('idle');
  const [error, setError] = createSignal<string>();
  let activeController: AbortController | undefined;
  let inputElement: HTMLTextAreaElement | undefined;
  let nextMessageId = 0;

  const canSend = createMemo(() => (
    input().trim().length > 0
    && selectedModel() !== null
    && phase() !== 'streaming'
  ));

  const loadModels = async () => {
    setModelPhase('loading');
    try {
      const response = await jarvisApi.models();
      setModels(response.models);
      setSelectedModel((current) => (
        response.models.find((model) => model.name === current?.name)
        || response.models[0]
        || null
      ));
      setModelPhase(response.models.length ? 'ready' : 'empty');
    } catch (loadError) {
      setModels([]);
      setSelectedModel(null);
      setModelPhase('error');
      toast.error(errorMessage(loadError));
    }
  };

  const sendMessage = async (
    text: string,
    historyOverride: ViewMessage[] = messages(),
  ) => {
    const content = text.trim();
    const model = selectedModel();
    if (!content || !model || phase() === 'streaming') return;

    const userMessage: ViewMessage = {
      id: nextMessageId++,
      role: 'user',
      content,
    };
    const assistantMessage: ViewMessage = {
      id: nextMessageId++,
      role: 'assistant',
      content: '',
      streaming: true,
    };
    const requestMessages: ChatMessage[] = [
      ...historyOverride.map(({ role, content: previousContent }) => ({
        role,
        content: previousContent,
      })),
      { role: 'user', content },
    ];

    setMessages([...historyOverride, userMessage, assistantMessage]);
    setInput('');
    setError(undefined);
    setPhase('streaming');
    const controller = new AbortController();
    activeController = controller;

    try {
      await streamChat(
        { model: model.name, messages: requestMessages },
        {
          onDelta(delta) {
            setMessages((current) => current.map((message) => (
              message.id === assistantMessage.id
                ? { ...message, content: message.content + delta }
                : message
            )));
          },
        },
        controller.signal,
      );
    } catch (streamError) {
      if (!isAbortError(streamError)) {
        const message = errorMessage(streamError);
        setError(message);
        setMessages((current) => current.map((item) => (
          item.id === assistantMessage.id ? { ...item, failed: true } : item
        )));
        toast.error(message);
      }
    } finally {
      setMessages((current) => current.map((message) => (
        message.id === assistantMessage.id
          ? { ...message, streaming: false }
          : message
      )));
      if (activeController === controller) {
        activeController = undefined;
        setPhase('idle');
      }
    }
  };

  const stopStreaming = () => {
    activeController?.abort();
  };

  const retryLastPrompt = () => {
    const lastUserMessage = messages().findLast((message) => message.role === 'user');
    if (lastUserMessage) void sendMessage(lastUserMessage.content);
  };

  const clearConversation = () => {
    activeController?.abort();
    setMessages([]);
    setInput('');
    setError(undefined);
    setTimeout(() => inputElement?.focus(), 0);
  };

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void sendMessage(input());
    }
  };

  onMount(() => void loadModels());
  onCleanup(() => activeController?.abort());

  return (
    <section class="chat-view" aria-labelledby="chat-view-title">
      <header class="chat-view__header">
        <div>
          <h1 id="chat-view-title">指挥中心</h1>
          <p>通过 Ollama 运行模型，响应仅在本机处理。</p>
        </div>
        <div class="chat-view__toolbar">
          <Select.Root<OllamaModel>
            options={models()}
            optionValue="name"
            optionTextValue="name"
            value={selectedModel()}
            onChange={setSelectedModel}
            disabled={modelPhase() !== 'ready'}
            placeholder={modelPhase() === 'loading' ? '加载模型…' : '无可用模型'}
            itemComponent={(props) => (
              <Select.Item item={props.item} class="model-select__item">
                <Select.ItemLabel>{props.item.rawValue.name}</Select.ItemLabel>
              </Select.Item>
            )}
          >
            <Select.HiddenSelect />
            <Select.Label class="sr-only">模型</Select.Label>
            <Select.Trigger class="model-select__trigger" aria-label="模型">
              <Select.Value<OllamaModel>>
                {(state) => state.selectedOption().name}
              </Select.Value>
              <Select.Icon class="model-select__icon">
                <ChevronDown size={16} strokeWidth={1.8} aria-hidden="true" />
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content class="model-select__content">
                <Select.Listbox class="model-select__listbox" />
              </Select.Content>
            </Select.Portal>
          </Select.Root>
          <IconButton
            label="刷新模型"
            icon={RefreshCw}
            onClick={() => void loadModels()}
            disabled={modelPhase() === 'loading'}
            disabledReason="正在刷新模型"
          />
          <Show when={messages().length > 0}>
            <ConfirmDialog
              title="清空对话？"
              description="当前消息将被移除，此操作无法撤销。"
              triggerLabel="清空对话"
              triggerIcon={Trash2}
              confirmLabel="确认清空"
              onConfirm={clearConversation}
              tone="danger"
            />
          </Show>
        </div>
      </header>

      <div class="chat-view__messages" aria-live="polite" aria-label="对话消息">
        <Show
          when={messages().length > 0}
          fallback={(
            <div class="chat-empty">
              <strong>准备接收指令</strong>
              <span>选择本地模型后开始对话。</span>
            </div>
          )}
        >
          <For each={messages()}>
            {(message) => (
              <article class={`chat-message chat-message--${message.role}`}>
                <div class="chat-message__meta">
                  {message.role === 'user' ? '你' : 'J.A.R.V.I.S.'}
                  <Show when={message.streaming}>
                    <span class="chat-message__streaming">生成中</span>
                  </Show>
                  <Show when={message.failed}>
                    <span class="chat-message__failed">未完成</span>
                  </Show>
                </div>
                <div class="chat-message__content">
                  <Show when={message.content} fallback={<span class="chat-cursor" aria-label="正在生成" />}>
                    {message.role === 'assistant'
                      ? (
                        <SolidMarkdown
                          children={message.content}
                          renderingStrategy="reconcile"
                          remarkPlugins={[remarkGfm]}
                          skipHtml
                        />
                      )
                      : <p>{message.content}</p>}
                  </Show>
                </div>
              </article>
            )}
          </For>
        </Show>
      </div>

      <Show when={error()}>
        {(message) => <p class="chat-view__error" role="status">{message()}</p>}
      </Show>

      <div class="chat-composer">
        <textarea
          ref={inputElement}
          class="chat-composer__input"
          aria-label="消息输入"
          placeholder={modelPhase() === 'empty' ? 'Ollama 中没有可用模型' : '输入消息…'}
          value={input()}
          rows={3}
          onInput={(event) => setInput(event.currentTarget.value)}
          onKeyDown={handleKeyDown}
        />
        <div class="chat-composer__actions">
          <Show when={phase() === 'streaming'} fallback={(
            <>
              <Show when={messages().some((message) => message.role === 'user')}>
                <IconButton
                  label="重试"
                  icon={RotateCcw}
                  onClick={retryLastPrompt}
                  disabled={!selectedModel()}
                  disabledReason="没有可用模型"
                />
              </Show>
              <IconButton
                label="发送"
                icon={Send}
                onClick={() => void sendMessage(input())}
                disabled={!canSend()}
                disabledReason={!selectedModel() ? '没有可用模型' : '请输入消息'}
                variant="accent"
              />
            </>
          )}>
            <IconButton
              label="停止生成"
              icon={Square}
              onClick={stopStreaming}
              variant="danger"
            />
          </Show>
        </div>
      </div>
    </section>
  );
}
