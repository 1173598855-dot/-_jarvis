function coreError(code, message, cause) {
  return Object.assign(new Error(message), { code, cause });
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
    const timeout = setTimeout(() => controller.abort(), effectiveTimeoutMs);
    let response;

    try {
      response = await fetchImpl(`${normalizedBaseUrl}${path}`, {
        ...init,
        signal: controller.signal,
      });
    } catch (error) {
      throw coreError('CORE_API_UNAVAILABLE', 'Core API 未连接', error);
    } finally {
      clearTimeout(timeout);
    }

    try {
      return {
        status: response.status,
        body: await response.json(),
      };
    } catch (error) {
      throw coreError(
        'CORE_API_INVALID_RESPONSE',
        'Core API 返回了无效 JSON',
        error,
      );
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
