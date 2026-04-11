import { complete, getModel, validateToolCall } from "@mariozechner/pi-ai";

import { SidecarError, normalizeProviderError } from "./errors.mjs";
import { TOOL_PARAMETER_SCHEMAS, validateOperationResult } from "./schemas.mjs";
import { normalizeStructuredToolCall } from "./structured-output.mjs";

const EMIT_RESULT_TOOL = "emit_structured_result";

export async function executeOperation(request, sidecarConfig) {
  const operation = request.operation;
  const timeoutMs = Math.round(sidecarConfig.timeoutSeconds * 1000);
  try {
    const raw = await withTimeout(resolveResult(request, sidecarConfig), timeoutMs);
    try {
      return validateOperationResult(operation, raw);
    } catch (error) {
      throw new SidecarError("schema-validation", String(error?.message || error), {
        retryable: false,
        cause: error,
      });
    }
  } catch (error) {
    if (error instanceof SidecarError) {
      throw error;
    }
    if (error?.name === "AbortError") {
      throw new SidecarError("timeout", `Timed out while running ${operation}.`, { retryable: true, cause: error });
    }
    throw normalizeProviderError(error);
  }
}

async function resolveResult(request, sidecarConfig) {
  if (sidecarConfig.provider === "fake") {
    return fakeResult(request, sidecarConfig);
  }

  const { model, options } = buildInvocation(sidecarConfig);
  const tools = [
    {
      name: EMIT_RESULT_TOOL,
      description: "Return the final structured JSON result for this host-agent operation.",
      parameters: TOOL_PARAMETER_SCHEMAS[request.operation],
    },
  ];

  const response = await complete(
    model,
    {
      systemPrompt: buildSystemPrompt(request.operation),
      messages: [{ role: "user", content: buildUserPrompt(request) }],
      tools,
    },
    options
  );

  const toolCall = response.content.find(
    (block) => block.type === "toolCall" && block.name === EMIT_RESULT_TOOL
  );
  if (!toolCall) {
    throw new SidecarError(
      "schema-validation",
      `Model did not return structured output for ${request.operation}.`
    );
  }
  try {
    return validateToolCall(tools, normalizeStructuredToolCall(request.operation, toolCall));
  } catch (error) {
    throw new SidecarError("schema-validation", String(error?.message || error), {
      retryable: false,
      cause: error,
    });
  }
}

export function buildInvocation(sidecarConfig, env = process.env) {
  if (sidecarConfig.apiStyle === "fake") {
    return { model: null, options: {} };
  }
  if (sidecarConfig.apiStyle === "builtin") {
    return {
      model: getModel(sidecarConfig.provider, sidecarConfig.model),
      options: {},
    };
  }
  const apiKey = resolveApiKey(sidecarConfig, env);
  if (sidecarConfig.apiStyle === "openai-compatible") {
    return {
      model: buildOpenAICompatibleModel(sidecarConfig),
      options: { apiKey },
    };
  }
  if (sidecarConfig.apiStyle === "anthropic-compatible") {
    return {
      model: buildAnthropicCompatibleModel(sidecarConfig),
      options: { apiKey },
    };
  }
  throw new SidecarError("invalid-request", `Unsupported apiStyle ${sidecarConfig.apiStyle}.`);
}

function buildOpenAICompatibleModel(sidecarConfig) {
  return {
    id: sidecarConfig.model,
    name: sidecarConfig.model,
    api: "openai-completions",
    provider: sidecarConfig.provider,
    baseUrl: sidecarConfig.baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 32768,
  };
}

function buildAnthropicCompatibleModel(sidecarConfig) {
  return {
    id: sidecarConfig.model,
    name: sidecarConfig.model,
    api: "anthropic-messages",
    provider: sidecarConfig.provider,
    baseUrl: sidecarConfig.baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 200000,
    maxTokens: 8192,
  };
}

function resolveApiKey(sidecarConfig, env) {
  const envName = sidecarConfig.apiKeyEnv;
  const apiKey = envName ? String(env[envName] || "").trim() : "";
  if (!apiKey) {
    throw new SidecarError(
      "provider-auth",
      `Missing API key. Set ${envName || "the configured API key env var"} for provider ${sidecarConfig.provider}.`,
      { retryable: false }
    );
  }
  return apiKey;
}

function buildSystemPrompt(operation) {
  return [
    "You are a structured host-agent backend.",
    `Perform the requested operation: ${operation}.`,
    "You must respond by calling the provided tool exactly once.",
    "Do not return prose outside the tool call.",
  ].join(" ");
}

function buildUserPrompt(request) {
  return JSON.stringify(
    {
      operation: request.operation,
      requestId: request.requestId,
      backend: request.backend,
      context: request.context,
    },
    null,
    2
  );
}

async function fakeResult(request, sidecarConfig) {
  switch (sidecarConfig.fakeMode) {
    case "provider-error":
      throw new SidecarError("provider-unavailable", "Fake provider is unavailable.", { retryable: true });
    case "timeout":
      await new Promise((resolve) => setTimeout(resolve, Math.round(sidecarConfig.timeoutSeconds * 1000) + 50));
      return { summary: "too late" };
    case "invalid-structure":
      return { wrong: true };
    default:
      return fakeSuccess(request);
  }
}

function fakeSuccess(request) {
  const episode = request.context?.state?.episode_id || "unknown";
  const objective = request.context?.state?.objective || "unknown objective";
  const candidates = Array.isArray(request.context?.candidates) ? request.context.candidates : [];
  const observation = request.context?.observation || null;
  switch (request.operation) {
    case "derive_design_contract":
      return {
        summary: objective,
        goals: [objective],
        constraints: ["Operate within the Host runtime boundary."],
        assumptions: [`Episode ${episode} remains the source of truth.`],
        open_questions: [],
      };
    case "build_working_plan":
      return {
        summary: `Advance episode ${episode}`,
        candidate_actions: candidates.map((item) => item.title || item.kind || "action"),
        steps: candidates
          .filter((item) => item.tool_action)
          .map((item) => ({
            id: item.action_id,
            title: item.title,
            tool: item.tool_action.tool,
            inputs: item.tool_action.inputs,
          })),
      };
    case "propose_candidate_actions":
      if (observation?.payload?.status === "completed") {
        return [
          {
            action_id: `action-${episode}-complete`,
            kind: "complete",
            title: "Complete episode",
            rationale: "The latest observation completed successfully.",
            tool_action: null,
          },
        ];
      }
      return [
        {
          action_id: `action-${episode}-tool`,
          kind: "tool",
          title: "Prepare receptor context",
          rationale: "Create a preprocessing result before downstream analysis.",
          tool_action: {
            tool: "prepare_receptor",
            inputs: { input: "data/inputs/receptor.pdb" },
            risk_level: "normal",
          },
        },
      ];
    case "select_action":
      return candidates[0] || {
        action_id: `action-${episode}-fallback`,
        kind: "clarification",
        title: "Request clarification",
        rationale: "No candidate action was available.",
        tool_action: null,
      };
    case "build_clarification_interrupt":
      return {
        interrupt_id: `interrupt-${episode}`,
        kind: "clarification_request",
        status: "pending",
        title: "Human feedback required",
        prompt: request.context?.reason || "Additional guidance is required.",
        created_at: new Date().toISOString(),
        related_action_id: request.context?.state?.selected_action?.action_id || null,
        gate_id: null,
      };
    case "summarize_observation":
      return {
        summary: observation?.summary || "Observation recorded.",
      };
    default:
      throw new SidecarError("invalid-request", `Unsupported fake operation ${request.operation}.`);
  }
}

function withTimeout(promise, timeoutMs) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new SidecarError("timeout", "Provider request timed out.", { retryable: true })), timeoutMs)
    ),
  ]);
}
