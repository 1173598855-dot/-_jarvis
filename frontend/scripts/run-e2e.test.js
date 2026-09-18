// @vitest-environment node

import { createServer } from 'net';
import { afterEach, describe, expect, test } from 'vitest';
import { assertPortAvailable } from './run-e2e.js';

let occupied;
const originalE2EPort = process.env.JARVIS_E2E_PORT;

afterEach(async () => {
  if (occupied) {
    await new Promise((resolve) => occupied.close(resolve));
    occupied = undefined;
  }
  if (originalE2EPort === undefined) {
    delete process.env.JARVIS_E2E_PORT;
  } else {
    process.env.JARVIS_E2E_PORT = originalE2EPort;
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

describe('E2E port resolution', () => {
  async function resolvePort() {
    const { resolveE2EPort } = await import('./e2e-port.js');
    return resolveE2EPort();
  }

  test('defaults to port 5173 when no override is provided', async () => {
    delete process.env.JARVIS_E2E_PORT;
    await expect(resolvePort()).resolves.toBe(5173);
  });

  test('accepts a valid JARVIS_E2E_PORT override', async () => {
    process.env.JARVIS_E2E_PORT = '5174';
    await expect(resolvePort()).resolves.toBe(5174);
  });

  test.each(['', '  ', '5174.5', '+5174', '-5174', '0', '65536', 'port'])
  ('rejects invalid JARVIS_E2E_PORT values: %j', async (value) => {
    process.env.JARVIS_E2E_PORT = value;
    await expect(resolvePort()).rejects.toThrow(
      'Invalid JARVIS_E2E_PORT: expected a decimal integer from 1 through 65535',
    );
  });
});
