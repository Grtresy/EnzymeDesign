import assert from "node:assert/strict";
import test from "node:test";

import {
  buildHostV2Paths,
  canonicalSha256Digest,
  HostApiV2Client,
  WebUiContractError,
} from "../src/client.js";

const digest = (character) => `sha256:${character.repeat(64)}`;

function release() {
  return {
    schema_version: "openzyme_layered_release_identity@1",
    kernel_contract_digest: digest("a"),
    core_schema_digest: digest("b"),
    adapter_bundle_digest: digest("c"),
    extension_bundle_digest: digest("d"),
    declared_tool_catalog_digest: digest("e"),
    route_catalog_digest: digest("f"),
    projection_catalog_digest: digest("1"),
    migration_catalog_digest: digest("2"),
    workspace_backend_digest: digest("3"),
    host_build_digest: digest("4"),
    client_build_digest: digest("5"),
    release_digest: digest("6"),
    public_contract_digest: digest("7"),
  };
}

function runtimeCommand(status = "accepted") {
  const terminal = ["completed", "failed", "locked", "cancelled"].includes(status);
  return {
    schema_version: "runtime_command_public@1",
    command_id: "runtime-drain-1",
    session_id: "session-1",
    command_type: "runtime.drain",
    request_digest: digest("d"),
    idempotency_key: "runtime-drain-1",
    status,
    max_signals: 3,
    max_steps_per_agent: 8,
    auto_enqueue_ready_tasks: false,
    state_version: 1,
    fencing_token: 0,
    accepted_at: "2026-08-24T00:00:00Z",
    claim_owner: null,
    lease_expires_at: null,
    bounded_outcome_summary: terminal ? {
      schema_version: "runtime_command_outcome_summary_public@1",
      processed_signals: 1,
      turn_count: 1,
      turns_digest: digest("e"),
      runtime_executed: true,
      task_transition_performed: false,
      fallback_performed: false,
    } : null,
    failure_id: status === "failed" ? "failure-runtime-drain-1" : null,
    diagnostic_id: status === "failed" ? "diagnostic-runtime-drain-1" : null,
    error_code: status === "failed" ? "runtime_context_identity_stale" : null,
    safe_error_summary: status === "failed"
      ? "Runtime context projection failed before provider invocation."
      : null,
    safe_retry_hint: status === "failed"
      ? "Inspect the exact diagnostic; no provider or fallback ran."
      : null,
    started_at: null,
    completed_at: terminal ? "2026-08-24T00:00:01Z" : null,
  };
}

function projection(expectedRelease = release()) {
  const binding = digest("8");
  return {
    schema_version: "file_workspace_public@2",
    release: expectedRelease,
    core: {
      agents: [],
      approvals: [],
      authority_leases: [],
      capability_binding: { binding_digest: binding },
      conversation: {
        memories: [], messages: [],
        transcript: {
          schema_version: "ordered_transcript@1", messages: [],
          transcript_digest: "sha256:4cebf6af4adaee585bed6af9d28e906c6dc55111de3fe19d746eb7f6df43bbd0",
        },
      },
      failures: { observations: [] },
      lanes: [],
      operations: {
        command_receipts: [], continuations: [], controlled: [],
        publication_intents: [], task_evidence: [],
      },
      protocol: { inbox: [], records: [] },
      publications: [],
      runtime: {
        commands: [],
        continuation_intents: [], outcome_consumptions: [], session_leases: [],
        settlement_intents: [], signals: [], turn_commands: [], outcomes: [],
        workflow_authority: {
          schema_version: "workflow_authority_projection@1",
          bindings: [], signal_links: [],
        },
      },
      session: {
        session_id: "session-1", objective: "Verify exact UI",
        resident_readiness: {
          schema_version: "resident_teammate_readiness@1",
          readiness: "ready", workspace_id: "workspace-1",
          workspace_generation: 1, provisioning_intent_id: "provisioning-1",
          provisioning_intent_digest: digest("b"), failure_id: null,
          next_action: "message_or_drain",
        },
      },
      tasks: [],
      tool_reflection: {
        declared_tool_catalog_digest: expectedRelease.declared_tool_catalog_digest,
        affordance_snapshot_digest: digest("9"),
        capability_binding_digest: binding,
        available_tool_names: [],
        affordances: [],
        tool_exposure: {
          schema_version: "tool_exposure_public@1",
          exposure_snapshot_id: "exposure-1",
          exposure_snapshot_digest: digest("c"),
          direct_tool_names: [], deferred_tool_names: [], command_expansions: [],
        },
      },
      workspace: {
        checkpoints: [], generations: [], repository_binding_pins: [],
        revision_path_verifications: [], runtime_bindings: [],
        provisioning: {
          schema_version: "workspace_provisioning_public@2",
          intent_id: "provisioning-1", intent_digest: digest("b"), status: "ready",
          intent_state_version: 2,
          workspace_id: "workspace-1", workspace_generation: 1,
          runtime_binding_id: "runtime-binding-1", failure_id: null,
          error_code: null, effect_certainty: "effect_known", mutation_applied: true,
          fallback_performed: false, retry_permitted: false,
          reconcile_required: false, diagnostic_id: null,
          next_action: "message_or_drain",
          reconciliation: null,
        },
      },
    },
    extensions: {},
  };
}

class Headers {
  constructor(values) {
    this.values = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key.toLowerCase(), value]),
    );
  }

  get(name) {
    return this.values[name.toLowerCase()] ?? null;
  }
}

async function workspaceResponse(payload = projection(), overrides = {}) {
  const projectionDigest = await canonicalSha256Digest(payload);
  return {
    ok: true,
    status: 200,
    headers: new Headers({
      "content-type": "application/vnd.openzyme.file-workspace+json;version=2",
      "openzyme-workspace-contract": "file_workspace_public@2",
      "openzyme-release-digest": payload.release.release_digest,
      "openzyme-public-contract-digest": payload.release.public_contract_digest,
      "openzyme-projection-digest": projectionDigest,
      "openzyme-capability-binding-digest": payload.core.capability_binding.binding_digest,
      "openzyme-affordance-snapshot-digest": payload.core.tool_reflection.affordance_snapshot_digest,
      ...overrides,
    }),
    async json() { return structuredClone(payload); },
  };
}

test("exact @2 workspace read verifies body and all response identities", async () => {
  const requests = [];
  const response = await workspaceResponse();
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return response;
    },
  });

  const result = await client.inspectWorkspace("session-1");

  assert.equal(result.projection.core.session.session_id, "session-1");
  assert.equal(requests[0].url, "/v3/sessions/session-1/workspace");
  assert.equal(
    requests[0].options.headers.Accept,
    "application/vnd.openzyme.file-workspace+json;version=2",
  );
  assert.equal(requests[0].options.headers["OpenZyme-Client-Build-Digest"], digest("5"));
});

test("workspace polling emits one verified change observation and suppresses unchanged state", async () => {
  const response = await workspaceResponse();
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => response,
  });

  const first = await client.pollWorkspaceProjection("session-1", null);
  const second = await client.pollWorkspaceProjection(
    "session-1",
    first.verified.projectionDigest,
  );

  assert.equal(first.changed, true);
  assert.equal(
    first.observation.schema_version,
    "file_workspace_projection_observation@1",
  );
  assert.equal(
    first.observation.source,
    "verified_workspace_projection_poll",
  );
  assert.equal(first.observation.facts.readiness, "ready");
  assert.equal(second.changed, false);
  assert.equal(second.observation, null);
});

test("workspace polling rejects a noncanonical cursor before transport", async () => {
  let dispatched = false;
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => {
      dispatched = true;
      throw new Error("transport must not be reached");
    },
  });

  await assert.rejects(
    client.pollWorkspaceProjection("session-1", "projection-latest"),
    (error) => error.code === "web_ui_workspace_projection_cursor_invalid",
  );
  assert.equal(dispatched, false);
});

test("artifact-era or @1 body is rejected without synthesis", async () => {
  const response = await workspaceResponse();
  response.json = async () => ({ schema_version: "file_workspace_public@1", artifacts: [] });
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => response,
  });

  await assert.rejects(
    client.inspectWorkspace("session-1"),
    /fields are closed|unsupported file_workspace_public@2 schema/,
  );
});

test("extension section payload drift is rejected before rendering", async () => {
  const payload = projection();
  payload.extensions["openzyme.science@1"] = {
    section_contract_digest: digest("a"),
    payload: { attempts: [] },
    next_cursor: null,
    projection_digest: digest("b"),
  };
  const response = await workspaceResponse(payload);
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => response,
  });

  await assert.rejects(
    client.inspectWorkspace("session-1"),
    (error) => error.code === "web_ui_extension_projection_digest_mismatch",
  );
});

test("mutation binds inspected identities and re-inspects canonical @2 state", async () => {
  const inspected = await workspaceResponse();
  const mutation = {
    ok: true,
    status: 202,
    headers: inspected.headers,
    async json() { return { legacy_workspace: "must-not-be-consumed" }; },
  };
  const responses = [inspected, mutation, inspected];
  const requests = [];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return responses.shift();
    },
  });

  const result = await client.postMessage(
    "session-1",
    { message: "continue", workflow_refs: [] },
    "web-ui:message:1",
  );

  assert.equal(result.responseStatus, 202);
  assert.deepEqual(result.mutationReceipt, { legacy_workspace: "must-not-be-consumed" });
  assert.deepEqual(requests.map((item) => item.options.method ?? "GET"), ["GET", "POST", "GET"]);
  assert.equal(requests[1].options.headers["Idempotency-Key"], "web-ui:message:1");
  assert.equal(
    requests[1].options.headers["OpenZyme-Capability-Binding-Digest"],
    digest("8"),
  );
});

test("approval decision uses the exact approval route and gesture identity", async () => {
  const inspected = await workspaceResponse();
  const mutation = {
    ok: true,
    status: 202,
    headers: inspected.headers,
    async json() { return { command_id: "approval-command-1" }; },
  };
  const responses = [inspected, mutation, inspected];
  const requests = [];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return responses.shift();
    },
  });

  await client.decideApproval(
    "session-1",
    "approval-1",
    {
      decision: "approved",
      intent_digest: digest("d"),
      resolution_ref: "web-ui:approval:1",
    },
    "web-ui:approval:1",
  );

  assert.equal(
    requests[1].url,
    "/v3/sessions/session-1/approvals/approval-1/decision",
  );
  assert.equal(requests[1].options.headers["Idempotency-Key"], "web-ui:approval:1");
  assert.deepEqual(JSON.parse(requests[1].options.body), {
    decision: "approved",
    intent_digest: digest("d"),
    resolution_ref: "web-ui:approval:1",
  });
});

test("post-dispatch identity drift is unknown-effect and never falls back", async () => {
  const inspected = await workspaceResponse();
  const mutation = await workspaceResponse(projection(), {
    "openzyme-projection-digest": digest("0"),
  });
  mutation.status = 202;
  const responses = [inspected, mutation];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => responses.shift(),
  });

  await assert.rejects(
    client.postMessage(
      "session-1",
      { message: "continue", workflow_refs: [] },
      "web-ui:message:2",
    ),
    (error) => {
      assert.equal(error instanceof WebUiContractError, true);
      assert.equal(error.code, "web_ui_mutation_response_identity_mismatch");
      assert.equal(error.mutationApplied, null);
      assert.equal(error.effectCertainty, "dispatch_in_doubt");
      assert.equal(error.fallbackPerformed, false);
      return true;
    },
  );
});

test("mutation rejects an unseen projection change before POST", async () => {
  const inspected = await workspaceResponse();
  const requests = [];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return inspected;
    },
  });

  await assert.rejects(
    client.postMessage(
      "session-1",
      { message: "continue", workflow_refs: [] },
      "web-ui:message:stale",
      digest("0"),
    ),
    (error) => error.code === "web_ui_mutation_projection_stale",
  );
  assert.deepEqual(
    requests.map((item) => item.options.method ?? "GET"),
    ["GET"],
  );
});

test("runtime command polling is observation-only and bound to the inspected projection", async () => {
  const inspected = await workspaceResponse();
  const projectionDigest = await canonicalSha256Digest(projection());
  const commandStatus = {
    ok: true,
    status: 200,
    headers: inspected.headers,
    async json() {
      return {
        schema_version: "runtime_command_status@1",
        session_id: "session-1",
        command: runtimeCommand("completed"),
        projection_digest: projectionDigest,
        mutation_applied: false,
        fallback_performed: false,
      };
    },
  };
  const requests = [];
  const responses = [commandStatus];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return responses.shift();
    },
  });

  const result = await client.inspectRuntimeCommand(
    "session-1",
    "runtime-drain-1",
  );

  assert.equal(result.command.status, "completed");
  assert.equal(
    result.command.bounded_outcome_summary.schema_version,
    "runtime_command_outcome_summary_public@1",
  );
  assert.deepEqual(requests.map((item) => item.options.method ?? "GET"), ["GET"]);
  assert.equal(
    requests[0].url,
    "/v3/sessions/session-1/runtime/commands/runtime-drain-1",
  );
});

test("runtime command status exposes safe failure IDs and rejects private fields", async () => {
  const inspected = await workspaceResponse();
  const projectionDigest = await canonicalSha256Digest(projection());
  const responseFor = (command) => ({
    ok: true,
    status: 200,
    headers: inspected.headers,
    async json() {
      return {
        schema_version: "runtime_command_status@1",
        session_id: "session-1",
        command,
        projection_digest: projectionDigest,
        mutation_applied: false,
        fallback_performed: false,
      };
    },
  });
  const safeClient = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => responseFor(runtimeCommand("failed")),
  });

  const safe = await safeClient.inspectRuntimeCommand(
    "session-1",
    "runtime-drain-1",
  );

  assert.equal(safe.command.failure_id, "failure-runtime-drain-1");
  assert.equal(safe.command.diagnostic_id, "diagnostic-runtime-drain-1");
  assert.equal(JSON.stringify(safe.command).includes("private_context"), false);

  const hostile = runtimeCommand("failed");
  hostile.traceback_text = "PRIVATE TRACEBACK";
  const hostileClient = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => responseFor(hostile),
  });
  await assert.rejects(
    hostileClient.inspectRuntimeCommand("session-1", "runtime-drain-1"),
    (error) => error.code === "web_ui_runtime_command_payload_invalid",
  );
});

test("runtime command polling strictly validates the public outcome summary", async () => {
  const inspected = await workspaceResponse();
  const projectionDigest = await canonicalSha256Digest(projection());
  const cases = [
    ["internal turns", (summary) => {
      summary.turns = [{ command_id: "private-turn" }];
    }],
    ["count mismatch", (summary) => { summary.turn_count = 0; }],
    ["fallback claim", (summary) => { summary.fallback_performed = true; }],
    ["execution mismatch", (summary) => { summary.runtime_executed = false; }],
    ["unbounded count", (summary) => {
      summary.processed_signals = 1_025;
      summary.turn_count = 1_025;
    }],
  ];
  for (const [name, mutate] of cases) {
    const command = runtimeCommand("completed");
    mutate(command.bounded_outcome_summary);
    const response = {
      ok: true,
      status: 200,
      headers: inspected.headers,
      async json() {
        return {
          schema_version: "runtime_command_status@1",
          session_id: "session-1",
          command,
          projection_digest: projectionDigest,
          mutation_applied: false,
          fallback_performed: false,
        };
      },
    };
    const client = new HostApiV2Client({
      expectedRelease: release(),
      fetchImpl: async () => response,
    });
    await assert.rejects(
      client.inspectRuntimeCommand("session-1", "runtime-drain-1"),
      (error) => error.code === "web_ui_runtime_command_payload_invalid",
      name,
    );
  }
});

test("message wire requires explicit empty workflow_refs and rejects mixed aliases", async () => {
  let dispatched = false;
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => {
      dispatched = true;
      throw new Error("transport must not be reached");
    },
  });

  await assert.rejects(
    client.postMessage("session-1", { message: "continue" }, "gesture-1"),
    (error) => error.code === "web_ui_workflow_selection_required",
  );
  await assert.rejects(
    client.postMessage(
      "session-1",
      { message: "continue", workflow_refs: [], skill_keys: ["legacy"] },
      "gesture-2",
    ),
    (error) => error.code === "web_ui_workflow_selection_ambiguous",
  );
  assert.equal(dispatched, false);
});

test("resident mutation is disabled client-side until readiness is ready", async () => {
  const pending = projection();
  pending.core.session.resident_readiness.readiness = "provisioning";
  pending.core.session.resident_readiness.next_action = "wait_for_provisioning_worker";
  pending.core.workspace.provisioning.status = "pending";
  pending.core.workspace.provisioning.runtime_binding_id = null;
  pending.core.workspace.provisioning.effect_certainty = null;
  pending.core.workspace.provisioning.mutation_applied = null;
  pending.core.workspace.provisioning.next_action = "wait_for_provisioning_worker";
  const inspected = await workspaceResponse(pending);
  const requests = [];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return inspected;
    },
  });

  await assert.rejects(
    client.postMessage(
      "session-1",
      { message: "continue", workflow_refs: [] },
      "gesture-1",
    ),
    (error) => error.code === "web_ui_resident_teammate_not_ready",
  );
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.method, undefined);
});

test("successful mutation with non-202 status is rejected as post-dispatch drift", async () => {
  const inspected = await workspaceResponse();
  const wrongStatus = {
    ...inspected,
    status: 200,
    async json() { return { status: "accepted" }; },
  };
  const responses = [inspected, wrongStatus];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => responses.shift(),
  });

  await assert.rejects(
    client.drainRuntime(
      "session-1",
      { max_signals: 1, max_steps_per_agent: 1 },
      "drain-1",
    ),
    (error) => {
      assert.equal(error.code, "web_ui_admission_status_invalid");
      assert.equal(error.mutationApplied, null);
      return true;
    },
  );
});

test("transcript inner digest drift is rejected even when projection envelope is bound", async () => {
  const drifted = projection();
  drifted.core.conversation.transcript.transcript_digest = digest("0");
  const response = await workspaceResponse(drifted);
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => response,
  });

  await assert.rejects(
    client.inspectWorkspace("session-1"),
    (error) => error.code === "web_ui_transcript_digest_mismatch",
  );
});

test("buildHostV2Paths exposes only activated exact @2 routes", () => {
  assert.deepEqual(buildHostV2Paths("session-1"), {
    workspace: "/v3/sessions/session-1/workspace",
    messages: "/v3/sessions/session-1/messages",
    runtimeDrain: "/v3/sessions/session-1/runtime/drain",
  });
});
