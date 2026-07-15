import { timingSafeEqual } from 'node:crypto';

const DEFAULT_ALLOWED_ORIGINS = [
  'http://localhost:5173',
  'http://127.0.0.1:5173',
];

function allowedOriginsFrom(environment) {
  const configured = (environment.JARVIS_ALLOWED_ORIGINS || '')
    .split(',')
    .map((origin) => origin.trim())
    .filter((origin) => origin && origin !== '*');
  return configured.length > 0 ? configured : DEFAULT_ALLOWED_ORIGINS;
}

function exactTokenMatch(expectedToken, providedToken) {
  if (!expectedToken || typeof providedToken !== 'string') return false;
  const expected = Buffer.from(expectedToken);
  const provided = Buffer.from(providedToken);
  return expected.length === provided.length && timingSafeEqual(expected, provided);
}

export function createRuntimeSecurity(environment = process.env) {
  const token = environment.JARVIS_TERMINAL_TOKEN || '';
  const terminalEnabled = environment.JARVIS_TERMINAL_ENABLED === 'true' && Boolean(token);

  return {
    host: environment.JARVIS_HOST || '127.0.0.1',
    allowedOrigins: allowedOriginsFrom(environment),
    terminalEnabled,
    isAuthorized(providedToken) {
      return terminalEnabled && exactTokenMatch(token, providedToken);
    },
  };
}
