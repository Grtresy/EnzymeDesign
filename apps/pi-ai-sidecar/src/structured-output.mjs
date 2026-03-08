const OPERATION_NORMALIZERS = {
  propose_candidate_actions(value) {
    return Array.isArray(value) ? value.map(normalizeActionPayload) : value;
  },
  select_action: normalizeActionPayload,
  build_clarification_interrupt: normalizeInterruptPayload,
};

export function normalizeStructuredToolCall(operation, toolCall) {
  if (!isObject(toolCall)) {
    return toolCall;
  }
  return {
    ...toolCall,
    arguments: normalizeStructuredArguments(operation, toolCall.arguments),
  };
}

export function normalizeStructuredArguments(operation, value) {
  const normalizer = OPERATION_NORMALIZERS[operation];
  return typeof normalizer === "function" ? normalizer(value) : value;
}

function normalizeActionPayload(value) {
  if (!isObject(value)) {
    return value;
  }
  return {
    ...value,
    tool_action: parseNullableJson(value.tool_action),
    gate_id: normalizeNullableString(value.gate_id),
  };
}

function normalizeInterruptPayload(value) {
  if (!isObject(value)) {
    return value;
  }
  return {
    ...value,
    related_action_id: normalizeNullableString(value.related_action_id),
    gate_id: normalizeNullableString(value.gate_id),
  };
}

function parseNullableJson(value) {
  const normalized = parseLooseJsonValue(value);
  return normalized == null ? null : normalized;
}

function normalizeNullableString(value) {
  return value === "null" ? null : value;
}

function parseLooseJsonValue(value) {
  if (typeof value !== "string") {
    return value;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return value;
  }
  if (trimmed === "null") {
    return null;
  }
  const first = trimmed[0];
  if (first !== "{" && first !== "[") {
    return value;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
