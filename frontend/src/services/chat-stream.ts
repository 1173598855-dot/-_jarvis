import { JarvisApiError } from './jarvis-api';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  model: string;
  messages: ChatMessage[];
}

export interface ChatHandlers {
  onDelta(content: string): void;
  onUsage?(usage: { prompt: number; completion: number }): void;
}

export function parseSseEvents(buffer: string) {
  const parts = buffer.split(/\r?\n\r?\n/);
  const remainder = parts.pop() ?? '';
  const events = parts.flatMap((part) => part
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.replace(/^data:\s?/, '').trim()));

  return { events, remainder };
}

function abortIfNeeded(signal: AbortSignal) {
  if (signal.aborted) {
    throw new DOMException('The operation was aborted.', 'AbortError');
  }
}

function processEvent(data: string, handlers: ChatHandlers) {
  if (!data || data === '[DONE]') {
    return data === '[DONE]';
  }

  let frame: {
    error?: { code?: string; message?: string };
    content?: string;
    done?: boolean;
    prompt_eval_count?: number;
    eval_count?: number;
  };

  try {
    frame = JSON.parse(data);
  } catch (error) {
    throw new JarvisApiError(
      '收到无效的流式响应',
      'INVALID_SSE_FRAME',
      200,
      error,
    );
  }

  if (frame.error) {
    throw new JarvisApiError(
      frame.error.message || '聊天请求失败',
      frame.error.code || 'CHAT_STREAM_ERROR',
      502,
    );
  }

  if (frame.content) {
    handlers.onDelta(frame.content);
  }

  if (
    frame.done
    && Number.isFinite(frame.prompt_eval_count)
    && Number.isFinite(frame.eval_count)
  ) {
    handlers.onUsage?.({
      prompt: frame.prompt_eval_count as number,
      completion: frame.eval_count as number,
    });
  }

  return false;
}

async function responseError(response: Response) {
  const payload = await response.json().catch(() => ({})) as {
    error?: string | { code?: string; message?: string; details?: unknown };
  };
  const error = payload.error;
  if (typeof error === 'string') {
    return new JarvisApiError(error, 'HTTP_ERROR', response.status);
  }
  return new JarvisApiError(
    error?.message || `聊天请求失败（HTTP ${response.status}）`,
    error?.code || 'HTTP_ERROR',
    response.status,
    error?.details,
  );
}

export async function streamChat(
  request: ChatRequest,
  handlers: ChatHandlers,
  signal: AbortSignal,
) {
  abortIfNeeded(signal);
  const response = await fetch('/api/ollama/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw await responseError(response);
  }
  if (!response.body) {
    throw new JarvisApiError(
      '流式响应不可用',
      'CHAT_STREAM_UNAVAILABLE',
      response.status,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    abortIfNeeded(signal);
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseEvents(buffer);
    buffer = parsed.remainder;

    for (const event of parsed.events) {
      if (processEvent(event, handlers)) {
        await reader.cancel();
        return;
      }
    }
  }

  buffer += decoder.decode();
  const finalEvents = parseSseEvents(buffer ? `${buffer}\n\n` : '').events;
  for (const event of finalEvents) {
    if (processEvent(event, handlers)) return;
  }
}
