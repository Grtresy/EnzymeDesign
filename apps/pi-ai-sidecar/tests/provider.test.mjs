import test from "node:test";
import assert from "node:assert/strict";

import { normalizeStructuredArguments, normalizeStructuredToolCall } from "../src/structured-output.mjs";

test("normalizeStructuredArguments parses stringified action payload fields", () => {
  const value = normalizeStructuredArguments("select_action", {
    action_id: "action-1",
    kind: "tool",
    title: "Prepare receptor context",
    rationale: "Need preprocessing first.",
    tool_action: "{\"tool\":\"prepare_receptor\",\"inputs\":{\"input\":\"data/inputs/receptor.pdb\"},\"risk_level\":\"normal\"}",
    gate_id: "null",
  });

  assert.deepEqual(value.tool_action, {
    tool: "prepare_receptor",
    inputs: { input: "data/inputs/receptor.pdb" },
    risk_level: "normal",
  });
  assert.equal(value.gate_id, null);
});

test("normalizeStructuredArguments parses stringified nulls in interrupt payloads", () => {
  const value = normalizeStructuredArguments("build_clarification_interrupt", {
    interrupt_id: "int-1",
    kind: "clarification_request",
    status: "pending",
    title: "Need input",
    prompt: "Provide receptor path",
    created_at: "2026-03-08T00:00:00Z",
    related_action_id: "null",
    gate_id: "null",
  });

  assert.equal(value.related_action_id, null);
  assert.equal(value.gate_id, null);
});

test("normalizeStructuredArguments parses arrays of candidate actions", () => {
  const value = normalizeStructuredArguments("propose_candidate_actions", [
    {
      action_id: "action-1",
      kind: "tool",
      title: "Prepare receptor context",
      rationale: "Need preprocessing first.",
      tool_action: "{\"tool\":\"prepare_receptor\",\"inputs\":{\"input\":\"data/inputs/receptor.pdb\"}}",
      gate_id: "null",
    },
  ]);

  assert.deepEqual(value, [
    {
      action_id: "action-1",
      kind: "tool",
      title: "Prepare receptor context",
      rationale: "Need preprocessing first.",
      tool_action: {
        tool: "prepare_receptor",
        inputs: { input: "data/inputs/receptor.pdb" },
      },
      gate_id: null,
    },
  ]);
});

test("normalizeStructuredArguments leaves non-JSON strings unchanged", () => {
  const value = normalizeStructuredArguments("select_action", {
    action_id: "action-2",
    kind: "tool",
    title: "Keep literal",
    rationale: "Tool action is malformed and should pass through unchanged for validation.",
    tool_action: "prepare_receptor(input=data/inputs/receptor.pdb)",
    gate_id: "gate-1",
  });

  assert.equal(value.tool_action, "prepare_receptor(input=data/inputs/receptor.pdb)");
  assert.equal(value.gate_id, "gate-1");
});

test("normalizeStructuredToolCall rewrites tool call arguments in place-safe fashion", () => {
  const rawToolCall = {
    type: "toolCall",
    name: "emit_structured_result",
    arguments: {
      action_id: "action-3",
      kind: "tool",
      title: "Prepare receptor context",
      rationale: "Need preprocessing first.",
      tool_action: "{\"tool\":\"prepare_receptor\",\"inputs\":{\"input\":\"data/inputs/receptor.pdb\"}}",
      gate_id: "null",
    },
  };

  const value = normalizeStructuredToolCall("select_action", rawToolCall);

  assert.notEqual(value, rawToolCall);
  assert.deepEqual(value.arguments.tool_action, {
    tool: "prepare_receptor",
    inputs: { input: "data/inputs/receptor.pdb" },
  });
  assert.equal(value.arguments.gate_id, null);
  assert.equal(typeof rawToolCall.arguments.tool_action, "string");
});
