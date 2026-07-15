import { spawn } from 'child_process';
import { createServer } from 'net';
import path from 'path';
import { fileURLToPath } from 'url';

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const viteBin = path.join(frontendDir, 'node_modules', 'vite', 'bin', 'vite.js');
const playwrightBin = path.join(
  frontendDir,
  'node_modules',
  '@playwright',
  'test',
  'cli.js',
);

function waitForExit(child) {
  return new Promise((resolve) => {
    child.once('exit', (code, signal) => resolve({ code, signal }));
  });
}

export function assertPortAvailable(host, port) {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.unref();
    probe.once('error', (error) => {
      reject(new Error(`Vite port ${host}:${port} is already in use: ${error.message}`));
    });
    probe.listen(port, host, () => {
      probe.close(resolve);
    });
  });
}

async function waitForServer(child, url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Vite exited before becoming ready (${child.exitCode})`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Vite is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Vite did not become ready within ${timeoutMs}ms`);
}

async function stopServer(child) {
  if (child.exitCode !== null) return;
  const exited = waitForExit(child);
  child.kill('SIGTERM');
  const stopped = await Promise.race([
    exited.then(() => true),
    new Promise((resolve) => setTimeout(() => resolve(false), 5_000)),
  ]);
  if (!stopped) {
    child.kill('SIGKILL');
    await exited;
  }
}

async function main() {
  await assertPortAvailable('127.0.0.1', 5173);
  const vite = spawn(
    process.execPath,
    [viteBin, '--host', '127.0.0.1', '--strictPort'],
    {
      cwd: frontendDir,
      stdio: 'inherit',
      windowsHide: true,
    },
  );

  try {
    await waitForServer(vite, 'http://127.0.0.1:5173');
    const playwright = spawn(
      process.execPath,
      [playwrightBin, 'test', ...process.argv.slice(2)],
      {
        cwd: frontendDir,
        env: { ...process.env, JARVIS_EXTERNAL_E2E_SERVER: '1' },
        stdio: 'inherit',
        windowsHide: true,
      },
    );
    const result = await waitForExit(playwright);
    if (result.signal) return 1;
    return result.code ?? 1;
  } finally {
    await stopServer(vite);
  }
}

const isDirectRun = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isDirectRun) {
  process.exitCode = await main();
}
