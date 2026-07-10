import { Component, createEffect, createSignal, onCleanup, onMount } from 'solid-js';

interface ChatWidgetProps {
  onModelsLoaded?: (models: string[]) => void;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const starterPrompts = [
  'Summarize the current JARVIS project state.',
  'Help me plan the next autonomous evolution step.',
  'Review the dashboard architecture and suggest risks.',
];

export const ChatWidget: Component<ChatWidgetProps> = (props) => {
  const [models, setModels] = createSignal<string[]>([]);
  const [selectedModel, setSelectedModel] = createSignal('');
  const [messages, setMessages] = createSignal<Message[]>([]);
  const [input, setInput] = createSignal('');
  const [isStreaming, setIsStreaming] = createSignal(false);
  const [isConnected, setIsConnected] = createSignal(false);
  const [error, setError] = createSignal('');

  let controller: AbortController | null = null;
  let messagesEndRef: HTMLDivElement | undefined;
  let textareaRef: HTMLTextAreaElement | undefined;

  const fetchModels = async () => {
    try {
      const res = await fetch('/api/ollama/models');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const modelList = data.models?.map((model: any) => model.name) || [];
      setModels(modelList);
      setIsConnected(modelList.length > 0);
      setError(modelList.length ? '' : 'No local models found.');
      if (modelList.length > 0 && !selectedModel()) {
        setSelectedModel(modelList[0]);
      }
      props.onModelsLoaded?.(modelList);
    } catch (err: any) {
      setIsConnected(false);
      setError(err.message || 'Cannot reach Ollama.');
    }
  };

  onMount(fetchModels);

  onCleanup(() => {
    controller?.abort();
  });

  createEffect(() => {
    messagesEndRef?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  });

  createEffect(() => {
    if (!textareaRef) return;
    textareaRef.style.height = 'auto';
    textareaRef.style.height = `${Math.min(textareaRef.scrollHeight, 160)}px`;
  });

  const sendMessage = async (preset?: string) => {
    const text = (preset ?? input()).trim();
    if (!text || isStreaming()) return;
    if (!selectedModel()) {
      setError('Select a model before sending.');
      return;
    }

    setError('');
    const userMsg: Message = { role: 'user', content: text };
    const history = [...messages(), userMsg];
    setMessages([...history, { role: 'assistant', content: '' }]);
    setInput('');
    setIsStreaming(true);

    controller = new AbortController();

    try {
      const res = await fetch('/api/ollama/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: selectedModel(),
          messages: history.map((msg) => ({ role: msg.role, content: msg.content })),
        }),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body?.getReader();
      if (!reader) throw new Error('Response stream is unavailable.');

      const decoder = new TextDecoder();
      let buffered = '';
      let fullContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffered += decoder.decode(value, { stream: true });
        const events = buffered.split('\n\n');
        buffered = events.pop() || '';

        for (const event of events) {
          const line = event.split('\n').find((item) => item.startsWith('data:'));
          if (!line) continue;
          const dataStr = line.replace(/^data:\s*/, '').trim();
          if (!dataStr || dataStr === '[DONE]') continue;

          const json = JSON.parse(dataStr);
          if (json.error) throw new Error(json.error);
          if (json.message?.content) {
            fullContent += json.message.content;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { role: 'assistant', content: fullContent };
              return next;
            });
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        const message = err.message || 'Chat request failed.';
        setError(message);
        setMessages((prev) => {
          const next = [...prev];
          if (next[next.length - 1]?.role === 'assistant') {
            next[next.length - 1] = { role: 'assistant', content: `Request failed: ${message}` };
          }
          return next;
        });
      }
    } finally {
      setIsStreaming(false);
      controller = null;
    }
  };

  const clearChat = () => {
    controller?.abort();
    setIsStreaming(false);
    setMessages([]);
    setError('');
  };

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  };

  return (
    <section class="panel chat-panel">
      <div class="panel-header chat-header">
        <div>
          <p class="eyebrow">Local model</p>
          <h2>Chat workspace</h2>
        </div>
        <div class="chat-tools">
          <select
            class="model-select"
            value={selectedModel()}
            onChange={(event) => setSelectedModel(event.currentTarget.value)}
            disabled={models().length === 0 || isStreaming()}
            aria-label="Select Ollama model"
          >
            {models().length === 0 ? (
              <option value="">No models</option>
            ) : (
              models().map((model) => <option value={model}>{model}</option>)
            )}
          </select>
          <button class="icon-button" type="button" onClick={fetchModels} title="Refresh models">
            <span aria-hidden="true">R</span>
          </button>
          <button class="icon-button" type="button" onClick={clearChat} title="Clear chat">
            <span aria-hidden="true">C</span>
          </button>
        </div>
      </div>

      <div class="connection-row">
        <span class={`status-pill ${isConnected() ? 'online' : 'offline'}`}>
          <span class="status-dot" />
          {isConnected() ? 'Ollama connected' : 'Ollama offline'}
        </span>
        <span class="muted-text">{selectedModel() || 'No model selected'}</span>
      </div>

      <div class="chat-messages" aria-live="polite">
        {messages().length === 0 && (
          <div class="empty-chat">
            <h3>Ask the local model</h3>
            <p>Use the model as a project copilot for planning, review, debugging, and local reasoning.</p>
            <div class="prompt-row">
              {starterPrompts.map((prompt) => (
                <button type="button" onClick={() => sendMessage(prompt)} disabled={!isConnected()}>
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages().map((msg) => (
          <article class={`message ${msg.role}`}>
            <div class="message-meta">{msg.role === 'user' ? 'You' : selectedModel() || 'Assistant'}</div>
            <div class="message-bubble">
              {msg.content || <span class="typing-cursor" aria-label="Assistant is typing" />}
            </div>
          </article>
        ))}
        <div ref={messagesEndRef!} />
      </div>

      {error() && <div class="error-banner">{error()}</div>}

      <div class="composer">
        <textarea
          ref={textareaRef!}
          value={input()}
          onInput={(event) => setInput(event.currentTarget.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask JARVIS anything... Enter to send, Shift+Enter for a new line"
          rows={1}
          disabled={isStreaming() || !isConnected()}
          aria-label="Message input"
        />
        <button
          class="send-button"
          type="button"
          onClick={() => sendMessage()}
          disabled={isStreaming() || !input().trim() || !isConnected()}
        >
          {isStreaming() ? 'Sending' : 'Send'}
        </button>
      </div>
    </section>
  );
};
