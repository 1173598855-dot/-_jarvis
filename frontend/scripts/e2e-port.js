const INVALID_PORT_MESSAGE =
  'Invalid JARVIS_E2E_PORT: expected a decimal integer from 1 through 65535';

export function resolveE2EPort(value = process.env.JARVIS_E2E_PORT) {
  if (value === undefined) return 5173;
  if (typeof value !== 'string' || !/^[0-9]+$/.test(value)) {
    throw new Error(INVALID_PORT_MESSAGE);
  }

  const port = Number(value);
  if (port < 1 || port > 65535) {
    throw new Error(INVALID_PORT_MESSAGE);
  }
  return port;
}
