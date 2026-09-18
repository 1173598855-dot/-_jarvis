import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseSseEvents, streamChat } from '../services/chat-stream';

afterEach(() => {
  vi.unstubAllGlobals();
});

function streamResponse(chunks: string[], status = 200) {
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(new TextEncoder().encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(body, { status });
}

describe('parseSseEvents', () => {
  it('parses CRLF events and keeps a cross-chunk remainder', () => {
    const parsed = parseSseEvents(
      'data: {"message":{"content":"a"}}\r\n\r\ndata: [DO',
    );

    expect(parsed.events).toEqual(['{"message":{"content":"a"}}']);
    expect(parsed.remainder).toBe('data: [DO');
  });
});

describe('streamChat', () => {
  it('cancels and rejects an oversized unterminated SSE remainder', async () => {
    const cancel = vi.fn();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(
          `data: ${'x'.repeat(70 * 1024)}`,
        ));
      },
      cancel,
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })));

    await expect(streamChat(
      { model: 'test', messages: [] },
      { onDelta: () => undefined },
      new AbortController().signal,
    )).rejects.toMatchObject({ code: 'SSE_STREAM_TOO_LARGE', status: 502 });
    expect(cancel).toHaveBeenCalled();
  });

  it('rejects an oversized SSE event before parsing or emitting it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      `data: ${'x'.repeat(70 * 1024)}\n\n`,
    ])));
    const onDelta = vi.fn();

    await expect(streamChat(
      { model: 'test', messages: [] },
      { onDelta },
      new AbortController().signal,
    )).rejects.toMatchObject({ code: 'SSE_STREAM_TOO_LARGE', status: 502 });
    expect(onDelta).not.toHaveBeenCalled();
  });

  it('emits deltas and usage before stopping at DONE', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      'data: {"model":"test","content":"hel',
      'lo","done":false}\n\ndata: {"model":"test","content":"","done":true,"prompt_eval_count":7,"eval_count":5}\n\n',
      'data: [DONE]\n\n',
    ])));
    const onDelta = vi.fn();
    const onUsage = vi.fn();

    await streamChat(
      { model: 'test', messages: [] },
      { onDelta, onUsage },
      new AbortController().signal,
    );

    expect(onDelta).toHaveBeenCalledWith('hello');
    expect(onUsage).toHaveBeenCalledWith({ prompt: 7, completion: 5 });
  });

  it('consumes canonical content frames and their usage counters', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      'data: {"model":"test","content":"hello","done":false}\n\n',
      'data: {"model":"test","content":"","done":true,"prompt_eval_count":7,"eval_count":5}\n\n',
      'data: [DONE]\n\n',
    ])));
    const onDelta = vi.fn();
    const onUsage = vi.fn();

    await streamChat(
      { model: 'test', messages: [] },
      { onDelta, onUsage },
      new AbortController().signal,
    );

    expect(onDelta).toHaveBeenCalledWith('hello');
    expect(onUsage).toHaveBeenCalledWith({ prompt: 7, completion: 5 });
  });

  it('rejects nested canonical error frames with their stable code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      'data: {"error":{"code":"OLLAMA_STREAM_ERROR","message":"offline"}}\n\n',
    ])));

    await expect(streamChat(
      { model: 'test', messages: [] },
      { onDelta: () => undefined },
      new AbortController().signal,
    )).rejects.toMatchObject({ code: 'OLLAMA_STREAM_ERROR', status: 502 });
  });

  it('preserves earlier deltas and rejects malformed frames', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      'data: {"model":"test","content":"kept","done":false}\n\n',
      'data: not-json\n\n',
    ])));
    const onDelta = vi.fn();

    await expect(streamChat(
      { model: 'test', messages: [] },
      { onDelta },
      new AbortController().signal,
    )).rejects.toMatchObject({ code: 'INVALID_SSE_FRAME' });
    expect(onDelta).toHaveBeenCalledWith('kept');
  });

  it('turns HTTP failures into typed API errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        error: { code: 'OLLAMA_OFFLINE', message: 'Ollama 未连接' },
      }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      },
    )));

    await expect(streamChat(
      { model: 'test', messages: [] },
      { onDelta: () => undefined },
      new AbortController().signal,
    )).rejects.toMatchObject({ code: 'OLLAMA_OFFLINE', status: 503 });
  });

  it('rejects before fetch when already aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(streamChat(
      { model: 'test', messages: [] },
      { onDelta: () => undefined },
      controller.signal,
    )).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
