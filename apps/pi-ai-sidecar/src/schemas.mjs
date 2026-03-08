import { StringEnum, Type } from "@mariozechner/pi-ai";

const LooseObject = Type.Object({}, { additionalProperties: true });
const NullableString = Type.Union([Type.String(), Type.Null()]);
const NullableToolAction = Type.Union([
  Type.Object(
    {
      tool: Type.String({ minLength: 1 }),
      inputs: LooseObject,
      risk_level: Type.Optional(Type.String({ minLength: 1 })),
    },
    { additionalProperties: false }
  ),
  Type.Null(),
]);

export const SUPPORTED_OPERATIONS = new Set([
  "derive_design_contract",
  "build_working_plan",
  "propose_candidate_actions",
  "select_action",
  "build_clarification_interrupt",
  "summarize_observation",
]);

export const RESULT_SCHEMAS = {
  derive_design_contract: Type.Object(
    {
      summary: Type.String({ minLength: 1 }),
      goals: Type.Array(Type.String()),
      constraints: Type.Array(Type.String()),
      assumptions: Type.Array(Type.String()),
      open_questions: Type.Array(Type.String()),
    },
    { additionalProperties: false }
  ),
  build_working_plan: Type.Object(
    {
      summary: Type.String({ minLength: 1 }),
      candidate_actions: Type.Array(Type.String()),
      steps: Type.Array(
        Type.Object(
          {
            id: Type.String({ minLength: 1 }),
            title: Type.String({ minLength: 1 }),
            tool: Type.Optional(Type.String({ minLength: 1 })),
            inputs: Type.Optional(LooseObject),
          },
          { additionalProperties: false }
        )
      ),
    },
    { additionalProperties: false }
  ),
  propose_candidate_actions: Type.Array(actionSchema()),
  select_action: actionSchema(),
  build_clarification_interrupt: Type.Object(
    {
      interrupt_id: Type.String({ minLength: 1 }),
      kind: StringEnum(["clarification_request"]),
      status: StringEnum(["pending"]),
      title: Type.String({ minLength: 1 }),
      prompt: Type.String({ minLength: 1 }),
      created_at: Type.String({ minLength: 1 }),
      related_action_id: Type.Optional(NullableString),
      gate_id: Type.Optional(NullableString),
    },
    { additionalProperties: false }
  ),
  summarize_observation: Type.Object(
    {
      summary: Type.String({ minLength: 1 }),
    },
    { additionalProperties: false }
  ),
};

export function validateRequest(payload) {
  if (!isObject(payload)) {
    throw new Error("Request must be an object.");
  }
  if (typeof payload.requestId !== "string" || !payload.requestId.trim()) {
    throw new Error("requestId is required.");
  }
  if (typeof payload.operation !== "string" || !SUPPORTED_OPERATIONS.has(payload.operation)) {
    throw new Error("operation is invalid.");
  }
  if (!isObject(payload.context)) {
    throw new Error("context is required.");
  }
  if (!isObject(payload.backend)) {
    throw new Error("backend is required.");
  }
  return payload;
}

export function validateOperationResult(operation, value) {
  switch (operation) {
    case "derive_design_contract":
      return validateDesignContract(value);
    case "build_working_plan":
      return validateWorkingPlan(value);
    case "propose_candidate_actions":
      if (!Array.isArray(value)) {
        throw new Error("Candidate actions must be an array.");
      }
      return value.map(validateAction);
    case "select_action":
      return validateAction(value);
    case "build_clarification_interrupt":
      return validateInterrupt(value);
    case "summarize_observation":
      return validateSummary(value);
    default:
      throw new Error(`Unsupported operation: ${operation}`);
  }
}

function validateDesignContract(value) {
  const payload = ensureObject(value, "Design contract must be an object.");
  return {
    summary: requireString(payload.summary, "Design contract summary is required."),
    goals: requireStringList(payload.goals, "Design contract goals must be an array."),
    constraints: requireStringList(payload.constraints, "Design contract constraints must be an array."),
    assumptions: requireStringList(payload.assumptions, "Design contract assumptions must be an array."),
    open_questions: requireStringList(payload.open_questions, "Design contract open_questions must be an array."),
  };
}

function validateWorkingPlan(value) {
  const payload = ensureObject(value, "Working plan must be an object.");
  const steps = Array.isArray(payload.steps) ? payload.steps : [];
  return {
    summary: requireString(payload.summary, "Working plan summary is required."),
    candidate_actions: requireStringList(
      payload.candidate_actions,
      "Working plan candidate_actions must be an array."
    ),
    steps: steps.map((item) => {
      const step = ensureObject(item, "Working plan step must be an object.");
      const normalized = {
        id: requireString(step.id, "Working plan step id is required."),
        title: requireString(step.title, "Working plan step title is required."),
      };
      if (typeof step.tool === "string" && step.tool.trim()) {
        normalized.tool = step.tool;
      }
      if (isObject(step.inputs)) {
        normalized.inputs = step.inputs;
      }
      return normalized;
    }),
  };
}

function validateAction(value) {
  const payload = ensureObject(value, "Action must be an object.");
  const toolAction = payload.tool_action;
  return {
    action_id: requireString(payload.action_id, "Action id is required."),
    action_revision: Number.isInteger(payload.action_revision) ? payload.action_revision : 1,
    kind: requireString(payload.kind, "Action kind is required."),
    title: requireString(payload.title, "Action title is required."),
    rationale: requireString(payload.rationale, "Action rationale is required."),
    tool_action: toolAction == null ? null : validateToolAction(toolAction),
    gate_id: optionalString(payload.gate_id),
  };
}

function validateToolAction(value) {
  const payload = ensureObject(value, "tool_action must be an object.");
  return {
    tool: requireString(payload.tool, "Tool action tool is required."),
    inputs: isObject(payload.inputs) ? payload.inputs : {},
    risk_level: typeof payload.risk_level === "string" && payload.risk_level.trim() ? payload.risk_level : "normal",
  };
}

function validateInterrupt(value) {
  const payload = ensureObject(value, "Interrupt must be an object.");
  return {
    interrupt_id: requireString(payload.interrupt_id, "Interrupt id is required."),
    kind: requireString(payload.kind, "Interrupt kind is required."),
    status: requireString(payload.status, "Interrupt status is required."),
    title: requireString(payload.title, "Interrupt title is required."),
    prompt: requireString(payload.prompt, "Interrupt prompt is required."),
    created_at: requireString(payload.created_at, "Interrupt created_at is required."),
    related_action_id: optionalString(payload.related_action_id),
    gate_id: optionalString(payload.gate_id),
  };
}

function validateSummary(value) {
  if (typeof value === "string") {
    return { summary: requireString(value, "Summary is required.") };
  }
  const payload = ensureObject(value, "Summary result must be an object.");
  return {
    summary: requireString(payload.summary, "Summary is required."),
  };
}

function actionSchema() {
  return Type.Object(
    {
      action_id: Type.String({ minLength: 1 }),
      action_revision: Type.Optional(Type.Integer({ minimum: 1 })),
      kind: StringEnum(["tool", "clarification", "complete", "noop"]),
      title: Type.String({ minLength: 1 }),
      rationale: Type.String({ minLength: 1 }),
      tool_action: Type.Optional(NullableToolAction),
      gate_id: Type.Optional(NullableString),
    },
    { additionalProperties: false }
  );
}

function ensureObject(value, message) {
  if (!isObject(value)) {
    throw new Error(message);
  }
  return value;
}

function requireString(value, message) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(message);
  }
  return value;
}

function requireStringList(value, message) {
  if (!Array.isArray(value)) {
    throw new Error(message);
  }
  return value.map((item) => requireString(item, message));
}

function optionalString(value) {
  if (value == null) {
    return null;
  }
  return requireString(value, "Expected optional string.");
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
