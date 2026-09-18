function coreError(code, message, cause) {
  return Object.assign(new Error(message), { code, cause });
}

const MAX_CORE_API_RESPONSE_BYTES = 8 * 1024 * 1024;

async function cancelReader(reader, reason) {
  try {
    await reader.cancel(reason);
  } catch {
    // The bounded failure remains authoritative if cancellation also fails.
  }
}

async function readBoundedJsonResponse(response, signal) {
  const reader = response.body?.getReader();
  const contentLength = response.headers.get('content-length')?.trim();
  if (
    reader
    && contentLength
    && /^\d+$/.test(contentLength)
    && BigInt(contentLength) > BigInt(MAX_CORE_API_RESPONSE_BYTES)
  ) {
    void cancelReader(reader, new RangeError('Core API response is too large'));
    throw new RangeError('Core API response is too large');
  }

  if (!reader) {
    return JSON.parse('');
  }

  const chunks = [];
  let totalBytes = 0;
  const abortBody = () => {
    void cancelReader(reader, signal.reason);
  };
  signal.addEventListener('abort', abortBody, { once: true });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (signal.aborted) {
        throw signal.reason || new Error('Core API request aborted');
      }
      if (done) break;
      if (!(value instanceof Uint8Array)) {
        throw new TypeError('Core API response body must contain bytes');
      }

      totalBytes += value.byteLength;
      if (totalBytes > MAX_CORE_API_RESPONSE_BYTES) {
        void cancelReader(reader, new RangeError('Core API response is too large'));
        throw new RangeError('Core API response is too large');
      }
      chunks.push(value);
    }
  } finally {
    signal.removeEventListener('abort', abortBody);
    try {
      reader.releaseLock();
    } catch {
      // A failed stream may already have released or invalidated its lock.
    }
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}

export function createCoreApiClient({
  baseUrl = '',
  fetchImpl = fetch,
  timeoutMs = 3000,
} = {}) {
  const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, '');

  async function request(path, init = {}, { timeoutMs: requestTimeoutMs } = {}) {
    if (!normalizedBaseUrl) {
      throw coreError('CORE_API_NOT_CONFIGURED', 'Core API 未配置');
    }

    const effectiveTimeoutMs = requestTimeoutMs ?? timeoutMs;
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, effectiveTimeoutMs);
    let response;

    try {
      try {
        response = await fetchImpl(`${normalizedBaseUrl}${path}`, {
          ...init,
          signal: controller.signal,
        });
      } catch (error) {
        throw coreError('CORE_API_UNAVAILABLE', 'Core API 未连接', error);
      }

      try {
        return {
          status: response.status,
          body: await readBoundedJsonResponse(response, controller.signal),
        };
      } catch (error) {
        if (timedOut) {
          throw coreError('CORE_API_UNAVAILABLE', 'Core API 未连接', error);
        }
        throw coreError(
          'CORE_API_INVALID_RESPONSE',
          'Core API 返回了无效 JSON',
          error,
        );
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  return {
    request,

    async status() {
      if (!normalizedBaseUrl) {
        return {
          configured: false,
          available: false,
          base_url: null,
        };
      }

      try {
        const result = await request('/api/health');
        return {
          configured: true,
          available: result.status >= 200 && result.status < 300,
          base_url: normalizedBaseUrl,
        };
      } catch {
        return {
          configured: true,
          available: false,
          base_url: normalizedBaseUrl,
        };
      }
    },
  };
}
