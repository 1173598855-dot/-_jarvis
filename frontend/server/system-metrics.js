import si from 'systeminformation';

const HARDWARE_CACHE_MS = 60_000;
const DEFAULT_PROBE_TIMEOUT_MS = 3_000;
const EMPTY_METRIC = Object.freeze({
  total: null,
  used: null,
  free: null,
  usage: null,
});

let hardwareCache = null;
let hardwareExpiresAt = 0;

const round = (value) => Math.round(value * 10) / 10;

function withTimeout(operation, timeoutMs) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(
      () => reject(new Error(`System metric probe timed out after ${timeoutMs}ms`)),
      timeoutMs,
    );
  });

  return Promise.race([
    Promise.resolve().then(operation),
    timeout,
  ]).finally(() => clearTimeout(timeoutId));
}

async function loadHardware(provider) {
  const [cpu, graphics] = await Promise.all([
    provider.cpu(),
    provider.graphics(),
  ]);
  return { cpu, graphics };
}

async function readHardware(provider) {
  if (provider !== si) {
    return loadHardware(provider);
  }

  if (hardwareCache && Date.now() < hardwareExpiresAt) {
    return hardwareCache;
  }

  hardwareCache = await loadHardware(provider);
  hardwareExpiresAt = Date.now() + HARDWARE_CACHE_MS;
  return hardwareCache;
}

function normalizeMemory(memory) {
  if (!memory || !Number.isFinite(memory.total) || memory.total <= 0) {
    return { ...EMPTY_METRIC };
  }

  const used = Number.isFinite(memory.active) ? memory.active : memory.used;
  const free = Number.isFinite(memory.available)
    ? memory.available
    : memory.total - used;

  return {
    total: memory.total,
    used,
    free,
    usage: round((used / memory.total) * 100),
  };
}

function normalizeDisk(disks) {
  if (!Array.isArray(disks) || disks.length === 0) {
    return { ...EMPTY_METRIC };
  }

  const totals = disks.reduce(
    (sum, disk) => ({
      total: sum.total + (Number(disk.size) || 0),
      used: sum.used + (Number(disk.used) || 0),
    }),
    { total: 0, used: 0 },
  );

  if (totals.total <= 0) {
    return { ...EMPTY_METRIC };
  }

  return {
    total: totals.total,
    used: totals.used,
    free: totals.total - totals.used,
    usage: round((totals.used / totals.total) * 100),
  };
}

function normalizeNetwork(interfaces) {
  if (!Array.isArray(interfaces)) {
    return { interfaces: [] };
  }

  return {
    interfaces: interfaces.map((item) => ({
      name: item.iface || item.ifaceName || '',
      ip: item.ip4 || '',
      status: item.operstate || 'unknown',
    })),
  };
}

export async function readSystemStats(
  provider = si,
  probeTimeoutMs = DEFAULT_PROBE_TIMEOUT_MS,
) {
  const [loadResult, memoryResult, diskResult, networkResult, hardwareResult] =
    await Promise.allSettled([
      withTimeout(() => provider.currentLoad(), probeTimeoutMs),
      withTimeout(() => provider.mem(), probeTimeoutMs),
      withTimeout(() => provider.fsSize(), probeTimeoutMs),
      withTimeout(() => provider.networkInterfaces(), probeTimeoutMs),
      withTimeout(() => readHardware(provider), probeTimeoutMs),
    ]);

  const unavailableFields = [];
  const load = loadResult.status === 'fulfilled' ? loadResult.value : null;
  const memory = memoryResult.status === 'fulfilled' ? memoryResult.value : null;
  const disks = diskResult.status === 'fulfilled' ? diskResult.value : null;
  const network = networkResult.status === 'fulfilled' ? networkResult.value : null;
  const hardware = hardwareResult.status === 'fulfilled'
    ? hardwareResult.value
    : null;

  if (!load || !Number.isFinite(load.currentLoad)) {
    unavailableFields.push('cpu.usage');
  }
  if (!memory) {
    unavailableFields.push('memory');
  }
  if (!Array.isArray(disks) || disks.length === 0) {
    unavailableFields.push('disk');
  }
  if (!Array.isArray(network)) {
    unavailableFields.push('network');
  }
  if (!hardware) {
    unavailableFields.push('hardware');
  }

  return {
    cpu: {
      usage: Number.isFinite(load?.currentLoad)
        ? round(load.currentLoad)
        : null,
      cores: Number.isFinite(hardware?.cpu?.cores)
        ? hardware.cpu.cores
        : null,
      model: hardware?.cpu?.brand || null,
    },
    memory: normalizeMemory(memory),
    disk: normalizeDisk(disks),
    network: normalizeNetwork(network),
    gpu: hardware?.graphics?.controllers?.map((controller) => ({
      model: controller.model,
      vendor: controller.vendor,
    })) || [],
    meta: {
      status: unavailableFields.length > 0 ? 'degraded' : 'ready',
      source: 'systeminformation',
      unavailable_fields: unavailableFields,
    },
  };
}
