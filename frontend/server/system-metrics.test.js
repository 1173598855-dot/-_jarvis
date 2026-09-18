// @vitest-environment node

import { describe, expect, test } from 'vitest';
import { readSystemStats } from './system-metrics.js';

describe('readSystemStats', () => {
  test('returns real provider values with ready metadata', async () => {
    const stats = await readSystemStats({
      currentLoad: async () => ({ currentLoad: 17.25 }),
      cpu: async () => ({ cores: 8, brand: 'Test CPU' }),
      mem: async () => ({ total: 1000, active: 600, available: 400 }),
      fsSize: async () => [
        { size: 2000, used: 500 },
        { size: 1000, used: 250 },
      ],
      networkInterfaces: async () => [
        { iface: 'Ethernet', ip4: '192.0.2.10', operstate: 'up' },
      ],
      graphics: async () => ({ controllers: [] }),
    });

    expect(stats.cpu).toEqual({
      usage: 17.3,
      cores: 8,
      model: 'Test CPU',
    });
    expect(stats.memory).toEqual({
      total: 1000,
      used: 600,
      free: 400,
      usage: 60,
    });
    expect(stats.disk).toEqual({
      total: 3000,
      used: 750,
      free: 2250,
      usage: 25,
    });
    expect(stats.network).toEqual({
      interfaces: [{ name: 'Ethernet', ip: '192.0.2.10', status: 'up' }],
    });
    expect(stats.meta).toEqual({
      status: 'ready',
      source: 'systeminformation',
      unavailable_fields: [],
    });
  });

  test('preserves available fields and marks provider failures', async () => {
    const stats = await readSystemStats({
      currentLoad: async () => {
        throw new Error('cpu unavailable');
      },
      cpu: async () => ({ cores: 8, brand: 'Test CPU' }),
      mem: async () => ({ total: 1000, active: 500, available: 500 }),
      fsSize: async () => {
        throw new Error('disk unavailable');
      },
      networkInterfaces: async () => {
        throw new Error('network unavailable');
      },
      graphics: async () => ({ controllers: [] }),
    });

    expect(stats.cpu.usage).toBeNull();
    expect(stats.memory.usage).toBe(50);
    expect(stats.disk.usage).toBeNull();
    expect(stats.network.interfaces).toEqual([]);
    expect(stats.meta.status).toBe('degraded');
    expect(stats.meta.unavailable_fields).toEqual(['cpu.usage', 'disk', 'network']);
  });

  test('bounds slow provider probes and reports their unavailable fields', async () => {
    const never = new Promise(() => {});
    const startedAt = Date.now();
    const stats = await readSystemStats({
      currentLoad: async () => never,
      cpu: async () => ({ cores: 8, brand: 'Test CPU' }),
      mem: async () => ({ total: 1000, active: 500, available: 500 }),
      fsSize: async () => [{ size: 2000, used: 500 }],
      networkInterfaces: async () => [],
      graphics: async () => ({ controllers: [] }),
    }, 25);

    expect(Date.now() - startedAt).toBeLessThan(250);
    expect(stats.cpu.usage).toBeNull();
    expect(stats.memory.usage).toBe(50);
    expect(stats.meta.status).toBe('degraded');
    expect(stats.meta.unavailable_fields).toContain('cpu.usage');
  });
});
