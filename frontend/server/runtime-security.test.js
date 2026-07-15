import { describe, expect, test } from 'vitest';
import { createRuntimeSecurity } from './runtime-security.js';

describe('runtime security defaults', () => {
  test('uses loopback host, explicit local origins, and disables terminal access', () => {
    const security = createRuntimeSecurity({});

    expect(security.host).toBe('127.0.0.1');
    expect(security.allowedOrigins).toEqual([
      'http://localhost:5173',
      'http://127.0.0.1:5173',
    ]);
    expect(security.terminalEnabled).toBe(false);
    expect(security.isAuthorized('anything')).toBe(false);
  });

  test('requires an exact terminal capability token after explicit enablement', () => {
    const security = createRuntimeSecurity({
      JARVIS_TERMINAL_ENABLED: 'true',
      JARVIS_TERMINAL_TOKEN: 'test-token',
    });

    expect(security.terminalEnabled).toBe(true);
    expect(security.isAuthorized('test-token')).toBe(true);
    expect(security.isAuthorized('wrong-token')).toBe(false);
  });
});
