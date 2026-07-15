// @vitest-environment node

import { createServer } from 'net';
import { afterEach, describe, expect, test } from 'vitest';
import { assertPortAvailable } from './run-e2e.js';

let occupied;

afterEach(async () => {
  if (occupied) {
    await new Promise((resolve) => occupied.close(resolve));
    occupied = undefined;
  }
});

describe('E2E server ownership', () => {
  test('rejects an already occupied Vite port before spawning', async () => {
    occupied = createServer();
    await new Promise((resolve) => occupied.listen(0, '127.0.0.1', resolve));
    const { port } = occupied.address();

    await expect(assertPortAvailable('127.0.0.1', port)).rejects.toThrow(
      /already in use/,
    );
  });
});
