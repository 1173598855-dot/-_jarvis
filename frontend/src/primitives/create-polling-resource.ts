import {
  createEffect,
  createSignal,
  onCleanup,
  onMount,
  type Accessor,
} from 'solid-js';
import type { ResourcePhase } from '../types/api';

const [pageVisible, setPageVisible] = createSignal(
  typeof document === 'undefined' || document.visibilityState !== 'hidden',
);
let visibilityListenerInitialized = false;

function ensureVisibilityListener() {
  if (visibilityListenerInitialized || typeof document === 'undefined') return;
  document.addEventListener('visibilitychange', () => {
    setPageVisible(document.visibilityState !== 'hidden');
  });
  visibilityListenerInitialized = true;
}

export interface PollingResource<T> {
  data: Accessor<T | undefined>;
  phase: Accessor<ResourcePhase>;
  error: Accessor<Error | undefined>;
  updatedAt: Accessor<number | undefined>;
  refresh(): Promise<void>;
}

export interface PollingOptions<T> {
  load(signal: AbortSignal): Promise<T>;
  intervalMs: number;
  maxBackoffMs?: number;
  autoStart?: boolean;
  enabled?: Accessor<boolean>;
  classify?(value: T): 'ready' | 'empty' | 'degraded';
}

export function createPollingResource<T>(
  options: PollingOptions<T>,
): PollingResource<T> {
  const [data, setData] = createSignal<T>();
  const [phase, setPhase] = createSignal<ResourcePhase>('loading');
  const [error, setError] = createSignal<Error>();
  const [updatedAt, setUpdatedAt] = createSignal<number>();
  const autoStart = options.autoStart !== false;
  const enabled = options.enabled || (() => true);
  const maxBackoff = options.maxBackoffMs || options.intervalMs * 8;

  let controller: AbortController | undefined;
  let timerId: number | undefined;
  let requestVersion = 0;
  let backoffMs = options.intervalMs;
  let started = false;
  let disposed = false;

  const active = () => pageVisible() && enabled();

  function clearTimer() {
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
      timerId = undefined;
    }
  }

  function schedule(delayMs: number) {
    clearTimer();
    if (!autoStart || disposed || !active()) return;
    timerId = window.setTimeout(() => {
      timerId = undefined;
      void refresh();
    }, delayMs);
  }

  async function refresh() {
    const version = ++requestVersion;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;

    if (data() === undefined) {
      setPhase('loading');
    }

    try {
      const value = await options.load(requestController.signal);
      if (disposed || version !== requestVersion) return;

      setData(() => value);
      setError(undefined);
      setUpdatedAt(Date.now());
      setPhase(options.classify?.(value) || 'ready');
      backoffMs = options.intervalMs;
    } catch (caught) {
      if (disposed || version !== requestVersion) return;
      const nextError = caught instanceof Error
        ? caught
        : new Error(String(caught));
      if (nextError.name === 'AbortError') return;

      setError(nextError);
      setPhase(data() === undefined ? 'error' : 'stale');
      backoffMs = Math.min(backoffMs * 2, maxBackoff);
    } finally {
      if (version === requestVersion) {
        if (controller === requestController) controller = undefined;
        schedule(backoffMs);
      }
    }
  }

  onMount(() => {
    ensureVisibilityListener();
    if (!autoStart) return;
    started = true;
    if (active()) void refresh();
  });

  createEffect(() => {
    const isActive = active();
    if (!started) return;

    if (!isActive) {
      clearTimer();
      controller?.abort();
      return;
    }

    schedule(0);
  });

  onCleanup(() => {
    disposed = true;
    clearTimer();
    controller?.abort();
  });

  return { data, phase, error, updatedAt, refresh };
}
