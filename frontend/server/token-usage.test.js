// @vitest-environment node

import { describe, expect, test } from 'vitest';
import { createTokenUsageStore } from './token-usage.js';

describe('createTokenUsageStore', () => {
  test('records only final frames and accumulates deterministic totals', () => {
    let timestamp = 1000;
    const store = createTokenUsageStore({
      maxSamples: 2,
      now: () => timestamp++,
    });

    store.recordFrame({
      done: false,
      prompt_eval_count: 99,
      eval_count: 99,
    });
    store.recordFrame({
      done: true,
      prompt_eval_count: 7,
      eval_count: 5,
    });
    store.recordFrame({
      done: true,
      prompt_eval_count: 3,
      eval_count: 2,
    });

    expect(store.snapshot()).toMatchObject({
      latest: {
        prompt_tokens: 3,
        completion_tokens: 2,
        total_tokens: 5,
      },
      totals: {
        prompt_tokens: 10,
        completion_tokens: 7,
        total_tokens: 17,
      },
    });
    expect(store.snapshot().samples).toHaveLength(2);
  });

  test('ignores final frames without numeric usage fields', () => {
    const store = createTokenUsageStore();

    expect(store.recordFrame({ done: true })).toBe(false);
    expect(store.snapshot().latest).toBeNull();
    expect(store.snapshot().totals.total_tokens).toBe(0);
  });
});
