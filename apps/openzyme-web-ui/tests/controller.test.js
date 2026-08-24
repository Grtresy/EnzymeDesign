import assert from "node:assert/strict";
import test from "node:test";

import { canonicalSha256Digest } from "../src/client.js";
import { WorkspaceControllerV2 } from "../src/controller.js";
import { ExtensionRendererRegistry } from "../src/extension_renderer_loader.js";
import {
  buildFileWorkspaceV2ProjectionObservation,
} from "../src/file_workspace_v2_state.js";

const digest = (character) => `sha256:${character.repeat(64)}`;

function projection(extensions = {}) {
  const release = {
    schema_version: "openzyme_layered_release_identity@1",
    kernel_contract_digest: digest("a"), core_schema_digest: digest("b"),
    adapter_bundle_digest: digest("c"), extension_bundle_digest: digest("d"),
    declared_tool_catalog_digest: digest("e"), route_catalog_digest: digest("f"),
    projection_catalog_digest: digest("1"), migration_catalog_digest: digest("2"),
    workspace_backend_digest: digest("3"), host_build_digest: digest("4"),
    client_build_digest: digest("5"), release_digest: digest("6"),
    public_contract_digest: digest("7"),
  };
  return {
    schema_version: "file_workspace_public@2",
    release,
    core: {
      agents: [], approvals: [], authority_leases: [],
      capability_binding: { binding_digest: digest("8") },
      conversation: {
        memories: [], messages: [],
        transcript: {
          schema_version: "ordered_transcript@1", messages: [],
          transcript_digest: "sha256:4cebf6af4adaee585bed6af9d28e906c6dc55111de3fe19d746eb7f6df43bbd0",
        },
      },
      failures: { observations: [] }, lanes: [],
      operations: {
        command_receipts: [], continuations: [], controlled: [],
        publication_intents: [], task_evidence: [],
      },
      protocol: { inbox: [], records: [] }, publications: [],
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
        session_id: "session-1", objective: "Test UI controller",
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
        declared_tool_catalog_digest: release.declared_tool_catalog_digest,
        affordance_snapshot_digest: digest("9"),
        capability_binding_digest: digest("8"),
        available_tool_names: [], affordances: [],
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
    extensions,
  };
}

async function projectionResult(payload, previousProjectionDigest = null) {
  const projectionDigest = await canonicalSha256Digest(payload);
  const changed = projectionDigest !== previousProjectionDigest;
  return {
    projection: structuredClone(payload),
    verified: { projectionDigest },
    changed,
    observation: changed
      ? buildFileWorkspaceV2ProjectionObservation({
        projection: payload,
        projectionDigest,
        previousProjectionDigest,
      })
      : null,
  };
}

function controller(client, entries = [], options = {}) {
  const transportClient = { ...client };
  if (typeof transportClient.pollWorkspaceProjection !== "function") {
    transportClient.pollWorkspaceProjection = async (sessionId, previousDigest) => {
      const inspected = await client.inspectWorkspace(sessionId);
      return projectionResult(inspected.projection, previousDigest);
    };
  }
  for (const method of ["postMessage", "drainRuntime", "decideApproval"]) {
    if (typeof client[method] !== "function") continue;
    transportClient[method] = async (...args) => {
      const result = await client[method](...args);
      if (typeof result.changed === "boolean") return result;
      return {
        ...result,
        ...await projectionResult(result.projection, args[args.length - 1]),
      };
    };
  }
  return new WorkspaceControllerV2({
    client: transportClient,
    rendererRegistry: new ExtensionRendererRegistry({
      rendererCatalogDigest: digest("a"),
      entries,
    }),
    expectedRendererCatalogDigest: digest("a"),
    reconcileIntervalMs: options.reconcileIntervalMs ?? 0,
    setReconcileTimeout: options.setReconcileTimeout,
    clearReconcileTimeout: options.clearReconcileTimeout,
  });
}

test("controller bootstraps a Plugin-free exact @2 Core shell", async () => {
  const calls = [];
  const subject = controller({
    async inspectWorkspace(sessionId) {
      calls.push(sessionId);
      return { projection: projection() };
    },
  });

  assert.equal(await subject.bootstrap("session-1"), true);
  assert.deepEqual(calls, ["session-1"]);
  assert.equal(subject.state.shell.core.session.session_id, "session-1");
  assert.equal(subject.state.shell.mutationAllowed, true);
  assert.deepEqual(subject.state.shell.extensionRendering.renderedSections, {});
  assert.equal(subject.state.projectionPollingStatus, "connected");
});

test("projection polling reconnects fail closed and close fences the timer", async () => {
  const payload = projection();
  const scheduled = [];
  const cleared = [];
  let pollCount = 0;
  const subject = controller({
    async pollWorkspaceProjection(_sessionId, previousDigest) {
      pollCount += 1;
      if (pollCount === 2) throw new Error("temporary projection poll failure");
      return projectionResult(payload, previousDigest);
    },
  }, [], {
    reconcileIntervalMs: 10,
    setReconcileTimeout(callback) {
      const handle = { callback, unref() {} };
      scheduled.push(handle);
      return handle;
    },
    clearReconcileTimeout(handle) {
      cleared.push(handle);
    },
  });

  assert.equal(await subject.bootstrap("session-1"), true);
  const firstTimer = scheduled.shift();
  await firstTimer.callback();
  assert.equal(subject.state.projectionPollingStatus, "reconnecting");
  assert.equal(subject.state.projectionReconnectCount, 1);
  assert.equal(subject.state.shell.mutationAllowed, false);

  const retryTimer = scheduled.shift();
  await retryTimer.callback();
  assert.equal(subject.state.projectionPollingStatus, "connected");
  assert.equal(subject.state.shell.mutationAllowed, true);
  assert.equal(pollCount, 3);

  const activeTimer = scheduled[0];
  subject.close();
  assert.equal(subject.state.projectionPollingStatus, "closed");
  assert.equal(subject.state.shell.mutationAllowed, false);
  assert.equal(cleared.includes(activeTimer), true);

  await activeTimer.callback();
  assert.equal(pollCount, 3);
  assert.equal(scheduled.length, 1);
});

test("close rejects an in-flight projection response without reopening controls", async () => {
  const initial = projection();
  const changed = projection();
  changed.core.session.objective = "must not be adopted after close";
  let pollCount = 0;
  let resolvePending;
  const subject = controller({
    async pollWorkspaceProjection(_sessionId, previousDigest) {
      pollCount += 1;
      if (pollCount === 1) return projectionResult(initial, previousDigest);
      return new Promise((resolve) => {
        resolvePending = resolve;
      });
    },
  });
  await subject.bootstrap("session-1");

  const pending = subject.refresh();
  subject.close();
  resolvePending(await projectionResult(
    changed,
    subject.state.shell.currentProjectionDigest,
  ));

  assert.equal(await pending, false);
  assert.equal(subject.state.projectionPollingStatus, "closed");
  assert.equal(subject.state.shell.mutationAllowed, false);
  assert.notEqual(
    subject.state.shell.core.session.objective,
    "must not be adopted after close",
  );
});

test("controller sends one explicit gesture identity and adopts re-inspected state", async () => {
  const next = projection();
  next.core.conversation.messages.push({ message_id: "message-1", content: "done" });
  const calls = [];
  const subject = controller({
    async inspectWorkspace() { return { projection: projection() }; },
    async postMessage(...args) {
      calls.push(args);
      return {
        responseStatus: 202,
        mutationReceipt: { operation: "message.admit" },
        projection: next,
      };
    },
  });
  await subject.bootstrap("session-1");
  const initialProjectionDigest = subject.state.shell.currentProjectionDigest;

  assert.equal(await subject.sendMessage("continue", "web-ui:message:1"), true);
  assert.deepEqual(calls, [[
    "session-1",
    { message: "continue", workflow_refs: [] },
    "web-ui:message:1",
    initialProjectionDigest,
  ]]);
  assert.equal(subject.state.shell.core.conversation.messages[0].message_id, "message-1");
  assert.deepEqual(subject.state.lastMutationReceipt, { operation: "message.admit" });
});

test("controller preserves one exact canonical workflow selection", async () => {
  const calls = [];
  const subject = controller({
    async inspectWorkspace() { return { projection: projection() }; },
    async postMessage(...args) {
      calls.push(args);
      return {
        responseStatus: 202,
        mutationReceipt: { operation: "message.admit" },
        projection: projection(),
      };
    },
  });
  await subject.bootstrap("session-1");

  assert.equal(
    await subject.sendMessage(
      "use selected workflow",
      "web-ui:message:workflow",
      ["enzymedesign.workflow.aox@1"],
    ),
    true,
  );

  assert.deepEqual(calls[0][1], {
    message: "use selected workflow",
    workflow_refs: ["enzymedesign.workflow.aox@1"],
  });
});

test("missing extension renderer disables all mutation controls", async () => {
  const science = projection({
    "openzyme.science@1": {
      section_contract_digest: digest("b"),
      payload: { attempts: [] },
      next_cursor: null,
      projection_digest: digest("c"),
    },
  });
  let mutationCalled = false;
  const subject = controller({
    async inspectWorkspace() { return { projection: science }; },
    async postMessage() { mutationCalled = true; },
  });
  assert.equal(await subject.bootstrap("session-1"), true);

  assert.equal(subject.state.shell.mutationAllowed, false);
  assert.equal(await subject.sendMessage("continue", "web-ui:message:2"), false);
  assert.equal(mutationCalled, false);
});

test("artifact-era projection observation makes the controller explicitly non-operational", async () => {
  const subject = controller({
    async inspectWorkspace() { return { projection: projection() }; },
  });
  await subject.bootstrap("session-1");

  subject.acceptProjectionObservation({
    schema_version: "file_workspace_public@1",
    observation_id: "old",
  });

  assert.equal(subject.state.shell.contractBlocked, true);
  assert.equal(subject.state.shell.mutationAllowed, false);
  assert.match(subject.state.shell.blockingError, /observation rejected/);
});

test("provisioning readiness disables message and drain without dispatch", async () => {
  const pending = projection();
  pending.core.session.resident_readiness.readiness = "provisioning";
  pending.core.session.resident_readiness.next_action = "wait_for_provisioning_worker";
  pending.core.workspace.provisioning.status = "pending";
  pending.core.workspace.provisioning.runtime_binding_id = null;
  pending.core.workspace.provisioning.effect_certainty = null;
  pending.core.workspace.provisioning.mutation_applied = null;
  pending.core.workspace.provisioning.next_action = "wait_for_provisioning_worker";
  pending.core.approvals.push({
    approval_id: "approval-1",
    intent_digest: digest("d"),
    status: "pending",
  });
  let dispatched = false;
  const subject = controller({
    async inspectWorkspace() { return { projection: pending }; },
    async postMessage() { dispatched = true; },
    async drainRuntime() { dispatched = true; },
    async decideApproval() { dispatched = true; },
  });

  await subject.bootstrap("session-1");

  assert.equal(subject.state.shell.residentReady, false);
  assert.equal(await subject.sendMessage("must queue later", "gesture-1"), false);
  assert.equal(await subject.drainRuntime({}, "gesture-2"), false);
  assert.equal(
    await subject.decideApproval("approval-1", "approved", "gesture-3"),
    false,
  );
  assert.equal(dispatched, false);
});

test("approval decision schedules through Host and adopts canonical projection", async () => {
  const current = projection();
  current.core.approvals.push({
    approval_id: "approval-1",
    intent_digest: digest("d"),
    status: "pending",
  });
  const settled = structuredClone(current);
  settled.core.approvals[0].status = "approved";
  const calls = [];
  const subject = controller({
    async inspectWorkspace() { return { projection: current }; },
    async decideApproval(...args) {
      calls.push(args);
      return {
        responseStatus: 202,
        mutationReceipt: { operation: "approval.decide" },
        projection: settled,
      };
    },
  });
  await subject.bootstrap("session-1");
  const initialProjectionDigest = subject.state.shell.currentProjectionDigest;

  assert.equal(
    await subject.decideApproval("approval-1", "approved", "approval-gesture-1"),
    true,
  );
  assert.deepEqual(calls, [[
    "session-1",
    "approval-1",
    {
      decision: "approved",
      intent_digest: digest("d"),
      resolution_ref: "approval-gesture-1",
    },
    "approval-gesture-1",
    initialProjectionDigest,
  ]]);
  assert.equal(subject.state.shell.core.approvals[0].status, "approved");
  assert.deepEqual(subject.state.lastMutationReceipt, { operation: "approval.decide" });
});

test("accepted drain command is polled without resubmission", async () => {
  const calls = [];
  const subject = controller({
    async inspectWorkspace() { return { projection: projection() }; },
    async drainRuntime() {
      calls.push("drain");
      return {
        responseStatus: 202,
        mutationReceipt: { result: { runtime_command_id: "runtime-drain-1" } },
        projection: projection(),
      };
    },
    async inspectRuntimeCommand(sessionId, commandId) {
      calls.push([sessionId, commandId]);
      return {
        schema_version: "runtime_command_status@1",
        command: { command_id: commandId, status: "accepted" },
      };
    },
  });
  await subject.bootstrap("session-1");

  assert.equal(await subject.drainRuntime({}, "runtime-gesture-1"), true);
  assert.deepEqual(calls, ["drain", ["session-1", "runtime-drain-1"]]);
  assert.equal(subject.state.activeRuntimeCommandId, "runtime-drain-1");
  assert.equal(subject.state.runtimeCommandStatus.command.status, "accepted");
});

test("terminal runtime status refreshes canonical assistant transcript", async () => {
  const initial = projection();
  const settled = projection();
  settled.core.conversation.transcript.messages = [{
    schema_version: "resident_transcript_message@1",
    ordinal: 1,
    message_id: "assistant-1",
    role: "assistant",
    content: "canonical answer",
    correlation_id: "correlation-1",
    tool_call_id: null,
    source_command_id: "turn-command-1",
    source_outcome_id: "outcome-1",
    created_at: "2026-08-24T00:00:00Z",
  }];
  let inspections = 0;
  const calls = [];
  const subject = controller({
    async inspectWorkspace() {
      inspections += 1;
      return { projection: inspections === 1 ? initial : settled };
    },
    async drainRuntime() {
      calls.push("drain");
      return {
        responseStatus: 202,
        mutationReceipt: { result: { runtime_command_id: "runtime-drain-1" } },
        projection: initial,
      };
    },
    async inspectRuntimeCommand() {
      calls.push("status");
      return {
        schema_version: "runtime_command_status@1",
        command: { command_id: "runtime-drain-1", status: "completed" },
      };
    },
  });
  await subject.bootstrap("session-1");

  assert.equal(await subject.drainRuntime({}, "runtime-gesture-1"), true);

  assert.deepEqual(calls, ["drain", "status"]);
  assert.equal(subject.state.activeRuntimeCommandId, null);
  assert.equal(
    subject.state.shell.core.conversation.transcript.messages[0].content,
    "canonical answer",
  );
  assert.equal(inspections, 2);
});
