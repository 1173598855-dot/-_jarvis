export function createTokenUsageStore({
  maxSamples = 60,
  now = Date.now,
} = {}) {
  const sampleLimit = Math.max(1, Math.floor(maxSamples));
  const sessionStartedAt = now();
  let latest = null;
  let totals = {
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
  };
  let samples = [];

  return {
    recordFrame(frame) {
      if (!frame?.done) {
        return false;
      }

      if (frame.prompt_eval_count == null || frame.eval_count == null) {
        return false;
      }

      const promptTokens = Number(frame.prompt_eval_count);
      const completionTokens = Number(frame.eval_count);
      if (
        !Number.isFinite(promptTokens)
        || !Number.isFinite(completionTokens)
        || promptTokens < 0
        || completionTokens < 0
      ) {
        return false;
      }

      latest = {
        prompt_tokens: promptTokens,
        completion_tokens: completionTokens,
        total_tokens: promptTokens + completionTokens,
        timestamp: now(),
      };
      totals = {
        prompt_tokens: totals.prompt_tokens + promptTokens,
        completion_tokens: totals.completion_tokens + completionTokens,
        total_tokens: totals.total_tokens + promptTokens + completionTokens,
      };
      samples = [...samples, latest].slice(-sampleLimit);
      return true;
    },

    snapshot() {
      return {
        latest: latest ? { ...latest } : null,
        totals: { ...totals },
        samples: samples.map((sample) => ({ ...sample })),
        session_started_at: sessionStartedAt,
      };
    },
  };
}
