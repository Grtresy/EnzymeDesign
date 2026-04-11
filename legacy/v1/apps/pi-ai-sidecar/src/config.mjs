import { readFileSync } from "node:fs";
import path from "node:path";

const DEFAULT_CONFIG = {
  backend: "llm-sidecar",
  provider: "fake",
  model: "fake-structured-agent",
  timeoutSeconds: 30,
  allowFallback: true,
  apiStyle: "builtin",
  apiKeyEnv: "OPENAI_API_KEY",
  baseUrl: "",
};

export function resolveConfigPath(argv, env, cwd = process.cwd()) {
  const flagIndex = argv.indexOf("--config");
  if (flagIndex >= 0 && argv[flagIndex + 1]) {
    return path.resolve(cwd, argv[flagIndex + 1]);
  }
  if (env.ENZYME_PI_AI_SIDECAR_CONFIG) {
    return path.resolve(cwd, env.ENZYME_PI_AI_SIDECAR_CONFIG);
  }
  return path.resolve(cwd, "config", "example.json");
}

export function loadSidecarConfig(configPath, env = process.env) {
  const payload = JSON.parse(readFileSync(configPath, "utf-8"));
  const scoped = isObject(payload.llm_sidecar) ? payload.llm_sidecar : payload;
  const provider = (env.ENZYME_AGENT_PROVIDER || scoped.provider || payload.provider || DEFAULT_CONFIG.provider).trim();
  const model = (env.ENZYME_AGENT_MODEL || scoped.model || payload.model || DEFAULT_CONFIG.model).trim();
  const timeoutValue =
    env.ENZYME_AGENT_TIMEOUT_SECONDS ??
    scoped.timeout_seconds ??
    scoped.timeoutSeconds ??
    payload.timeoutSeconds;
  const allowFallbackValue =
    env.ENZYME_AGENT_ALLOW_FALLBACK ??
    scoped.allow_fallback ??
    scoped.allowFallback ??
    payload.allowFallback;
  const baseUrl = normalizeOptionalString(
    env.ENZYME_AGENT_BASE_URL ?? scoped.base_url ?? scoped.baseUrl ?? payload.baseUrl ?? DEFAULT_CONFIG.baseUrl
  );
  const apiStyle = normalizeApiStyle(
    env.ENZYME_AGENT_API_STYLE ?? scoped.api_style ?? scoped.apiStyle ?? inferApiStyle(provider, baseUrl)
  );
  const apiKeyEnv = normalizeOptionalString(
    env.ENZYME_AGENT_API_KEY_ENV ?? scoped.api_key_env ?? scoped.apiKeyEnv ?? inferApiKeyEnv(apiStyle)
  );
  return {
    backend: String(payload.backend || DEFAULT_CONFIG.backend),
    provider,
    model,
    timeoutSeconds: normalizeTimeout(timeoutValue),
    allowFallback: normalizeBoolean(allowFallbackValue, DEFAULT_CONFIG.allowFallback),
    fakeMode: env.ENZYME_PI_AI_FAKE_MODE || payload.fakeMode || "success",
    apiStyle,
    apiKeyEnv,
    baseUrl,
    configPath,
  };
}

function normalizeTimeout(value) {
  const numeric = Number(value ?? DEFAULT_CONFIG.timeoutSeconds);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    throw new Error("timeoutSeconds must be a positive number.");
  }
  return numeric;
}

function normalizeBoolean(value, fallback) {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true") {
      return true;
    }
    if (normalized === "false") {
      return false;
    }
  }
  return fallback;
}

function inferApiStyle(provider, baseUrl) {
  if (provider === "fake") {
    return "fake";
  }
  if (baseUrl) {
    if (provider === "anthropic-compatible" || baseUrl.includes("/anthropic")) {
      return "anthropic-compatible";
    }
    return "openai-compatible";
  }
  return DEFAULT_CONFIG.apiStyle;
}

function inferApiKeyEnv(apiStyle) {
  switch (apiStyle) {
    case "anthropic-compatible":
      return "ANTHROPIC_API_KEY";
    case "openai-compatible":
      return "OPENAI_API_KEY";
    default:
      return DEFAULT_CONFIG.apiKeyEnv;
  }
}

function normalizeApiStyle(value) {
  const rendered = String(value || DEFAULT_CONFIG.apiStyle).trim().toLowerCase();
  if (["fake", "builtin", "openai-compatible", "anthropic-compatible"].includes(rendered)) {
    return rendered;
  }
  throw new Error(`Unsupported apiStyle: ${value}`);
}

function normalizeOptionalString(value) {
  if (value == null) {
    return "";
  }
  return String(value).trim();
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
