export class SidecarError extends Error {
  constructor(category, summary, { retryable = false, cause = null } = {}) {
    super(summary);
    this.name = "SidecarError";
    this.category = category;
    this.summary = summary;
    this.retryable = retryable;
    this.cause = cause;
  }
}

export function normalizeProviderError(error) {
  if (error instanceof SidecarError) {
    return error;
  }
  const message = String(error?.message || error || "Unknown provider error");
  const lower = message.toLowerCase();
  if (lower.includes("timeout") || lower.includes("aborted")) {
    return new SidecarError("timeout", message, { retryable: true, cause: error });
  }
  if (lower.includes("auth") || lower.includes("api key") || lower.includes("unauthorized")) {
    return new SidecarError("provider-auth", message, { retryable: false, cause: error });
  }
  if (lower.includes("rate") || lower.includes("429")) {
    return new SidecarError("provider-rate-limit", message, { retryable: true, cause: error });
  }
  if (lower.includes("unavailable") || lower.includes("503")) {
    return new SidecarError("provider-unavailable", message, { retryable: true, cause: error });
  }
  return new SidecarError("provider-error", message, { retryable: false, cause: error });
}
