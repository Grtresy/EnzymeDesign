import assert from "node:assert/strict";
import test from "node:test";

import { WorkspaceControllerV2 } from "../src/controller.js";
import { ExtensionRendererRegistry } from "../src/extension_renderer_loader.js";

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
      conversation: { memories: [], messages: [] },
      failures: { observations: [] }, lanes: [],
      operations: {
        command_receipts: [], continuations: [], controlled: [],
        publication_intents: [], task_evidence: [],
      },
      protocol: { inbox: [], records: [] }, publications: [],
      runtime: {
        continuation_intents: [], outcome_consumptions: [], session_leases: [],
        settlement_intents: [], signals: [], turn_commands: [],
      },
      session: { session_id: "session-1", objective: "Test UI controller" },
      tasks: [],
      tool_reflection: {
        declared_tool_catalog_digest: release.declared_tool_catalog_digest,
        affordance_snapshot_digest: digest("9"),
        capability_binding_digest: digest("8"),
        available_tool_names: [], affordances: [],
      },
      workspace: {
        checkpoints: [], generations: [], repository_binding_pins: [],
        revision_path_verifications: [], runtime_bindings: [],
      },
    },
    extensions,
  };
}

function controller(client, entries = []) {
  return new WorkspaceControllerV2({
    client,
    rendererRegistry: new ExtensionRendererRegistry({
      rendererCatalogDigest: digest("a"),
      entries,
    }),
    expectedRendererCatalogDigest: digest("a"),
    reconcileIntervalMs: 0,
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
});

test("controller sends one explicit gesture identity and adopts re-inspected state", async () => {
  const next = projection();
  next.core.conversation.messages.push({ message_id: "message-1", content: "done" });
  const calls = [];
  const subject = controller({
    async inspectWorkspace() { return { projection: projection() }; },
    async postMessage(...args) {
      calls.push(args);
      return { responseStatus: 200, projection: next };
    },
  });
  await subject.bootstrap("session-1");

  assert.equal(await subject.sendMessage("continue", "web-ui:message:1"), true);
  assert.deepEqual(calls, [[
    "session-1",
    { message: "continue" },
    "web-ui:message:1",
  ]]);
  assert.equal(subject.state.shell.core.conversation.messages[0].message_id, "message-1");
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
  await subject.bootstrap("session-1");

  assert.equal(subject.state.shell.mutationAllowed, false);
  assert.equal(await subject.sendMessage("continue", "web-ui:message:2"), false);
  assert.equal(mutationCalled, false);
});

test("artifact-era event makes the controller explicitly non-operational", async () => {
  const subject = controller({
    async inspectWorkspace() { return { projection: projection() }; },
  });
  await subject.bootstrap("session-1");

  subject.acceptEvent({ schema_version: "file_workspace_public@1", event_id: "old" });

  assert.equal(subject.state.shell.contractBlocked, true);
  assert.equal(subject.state.shell.mutationAllowed, false);
  assert.match(subject.state.shell.blockingError, /stale/);
});
