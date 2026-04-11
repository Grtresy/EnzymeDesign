const OPERATION_NORMALIZERS = {
  propose_candidate_actions(value) {
    if (isObject(value) && Array.isArray(value.actions)) {
      return value.actions.map(normalizeActionPayload);
    }
    return Array.isArray(value) ? value.map(normalizeActionPayload) : value;
  },
  select_action: normalizeActionPayload,
  build_clarification_interrupt: normalizeInterruptPayload,
};

export function normalizeStructuredToolCall(operation, toolCall) {
  if (!isObject(toolCall)) {
    return toolCall;
  }
  const normalizedArguments = normalizeStructuredArguments(operation, toolCall.arguments);
  return {
    ...toolCall,
    arguments: wrapToolCallArguments(operation, normalizedArguments),
  };
}

export function normalizeStructuredArguments(operation, value) {
  const normalizer = OPERATION_NORMALIZERS[operation];
  return typeof normalizer === "function" ? normalizer(value) : value;
}

function wrapToolCallArguments(operation, value) {
  if (operation === "propose_candidate_actions" && Array.isArray(value)) {
    return { actions: value };
  }
  return value;
}

function normalizeActionPayload(value) {
  if (!isObject(value)) {
    return value;
  }
  return {
    ...value,
    tool_action: normalizeToolAction(value.tool_action),
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
  if (value == null || value === "null") {
    return null;
  }
  return typeof value === "string" ? value : null;
}

function normalizeToolAction(value) {
  const normalized = parseNullableJson(value);
  if (!isObject(normalized)) {
    return normalized;
  }
  const tool = normalizeToolName(normalized.tool);
  return {
    ...normalized,
    tool,
    inputs: normalizeToolInputs(tool, normalized.inputs),
  };
}

function normalizeToolName(value) {
  if (typeof value !== "string") {
    return value;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return value;
  }
  const parts = trimmed.split("/");
  return parts[parts.length - 1];
}

function normalizeToolInputs(tool, value) {
  if (!isObject(value)) {
    return value;
  }
  const aliases = {
    fpocket: { input_file: "structure_path", pdb: "structure_path" },
    tunnels: { input_file: "structure_path", pdb: "structure_path" },
    hhblits: { input_file: "query_fasta" },
    vina: {
      receptor_file: "receptor_path",
      ligand_file: "ligand_path",
      receptor_pdbqt: "receptor_path",
      ligand_pdbqt: "ligand_path",
    },
  };
  const mapping = aliases[tool] || {};
  const normalized = {};
  for (const [key, entry] of Object.entries(value)) {
    normalized[mapping[key] || key] = entry;
  }
  return normalized;
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
