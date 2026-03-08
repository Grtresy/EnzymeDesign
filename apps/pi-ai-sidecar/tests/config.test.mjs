import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { loadSidecarConfig } from "../src/config.mjs";
import { buildInvocation } from "../src/provider.mjs";

test("loadSidecarConfig reads nested llm_sidecar config for runtime projects", () => {
  const configPath = writeTempConfig({
    backend: "llm-sidecar",
    llm_sidecar: {
      provider: "zhipu-coding",
      model: "GLM-4.7",
      api_style: "openai-compatible",
      base_url: "https://open.bigmodel.cn/api/coding/paas/v4",
      api_key_env: "ZHIPUAI_API_KEY",
      timeout_seconds: 12,
      allow_fallback: false,
    },
  });

  const config = loadSidecarConfig(configPath, {});

  assert.equal(config.provider, "zhipu-coding");
  assert.equal(config.model, "GLM-4.7");
  assert.equal(config.apiStyle, "openai-compatible");
  assert.equal(config.baseUrl, "https://open.bigmodel.cn/api/coding/paas/v4");
  assert.equal(config.apiKeyEnv, "ZHIPUAI_API_KEY");
  assert.equal(config.timeoutSeconds, 12);
  assert.equal(config.allowFallback, false);
});

test("buildInvocation creates custom OpenAI-compatible model for Zhipu", () => {
  const { model, options } = buildInvocation(
    {
      provider: "zhipu-coding",
      model: "GLM-4.7",
      apiStyle: "openai-compatible",
      apiKeyEnv: "ZHIPUAI_API_KEY",
      baseUrl: "https://open.bigmodel.cn/api/coding/paas/v4",
    },
    { ZHIPUAI_API_KEY: "secret-token" }
  );

  assert.equal(model.api, "openai-completions");
  assert.equal(model.provider, "zhipu-coding");
  assert.equal(model.baseUrl, "https://open.bigmodel.cn/api/coding/paas/v4");
  assert.equal(options.apiKey, "secret-token");
});

function writeTempConfig(payload) {
  const tmpDir = mkdtempSync(path.join(os.tmpdir(), "pi-ai-sidecar-config-"));
  const configPath = path.join(tmpDir, "agent_backend.json");
  writeFileSync(configPath, JSON.stringify(payload, null, 2), "utf-8");
  return configPath;
}
