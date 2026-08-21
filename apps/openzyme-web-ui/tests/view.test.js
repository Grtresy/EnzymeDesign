import assert from "node:assert/strict";
import test from "node:test";

import { buildCoreShellState } from "../src/core_shell.js";
import { ExtensionRendererRegistry } from "../src/extension_renderer_loader.js";
import { renderApp, renderCoreWorkspace, renderToolAffordances } from "../src/view.js";

const digest = (character) => `sha256:${character.repeat(64)}`;

function shell() {
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
  const payload = {
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
      protocol: { inbox: [], records: [] },
      publications: [{ publication_ref: "refs/openzyme/publication-1", commit: "abc" }],
      runtime: {
        continuation_intents: [], outcome_consumptions: [], session_leases: [],
        settlement_intents: [], signals: [], turn_commands: [],
      },
      session: { session_id: "session-1", objective: "Render Kernel truth" },
      tasks: [],
      tool_reflection: {
        declared_tool_catalog_digest: release.declared_tool_catalog_digest,
        affordance_snapshot_digest: digest("9"),
        capability_binding_digest: digest("8"),
        available_tool_names: [],
        affordances: [{
          tool_name: "workspace.exec",
          tool_contract_digest: digest("0"),
          state: "blocked_authority",
          required_authorities: ["workspace.process.exec"],
          route_ids: [], route_refs: [],
          blockers: [{ code: "authority_missing", requirement: null, target_id: null }],
        }],
      },
      workspace: {
        checkpoints: [],
        generations: [{ workspace_id: "workspace-1", generation: 2, status: "ready" }],
        repository_binding_pins: [], revision_path_verifications: [], runtime_bindings: [],
      },
    },
    extensions: {},
  };
  return buildCoreShellState(
    payload,
    new ExtensionRendererRegistry({ rendererCatalogDigest: digest("a") }),
    { expectedRendererCatalogDigest: digest("a") },
  );
}

test("Core view renders workspace revision/publication truth without product placeholders", () => {
  const html = renderCoreWorkspace(shell());
  assert.match(html, /workspace-1/);
  assert.match(html, /refs\/openzyme\/publication-1/);
  assert.doesNotMatch(html, /Scientific|Research|HPC|Report/);
});

test("blocked affordance remains visible with its exact blocker", () => {
  const html = renderToolAffordances(shell());
  assert.match(html, /workspace\.exec/);
  assert.match(html, /blocked_authority/);
  assert.match(html, /authority_missing/);
});

test("Plugin-free Standard shell stays usable and has no empty extension panel", () => {
  const html = renderApp({
    shell: shell(), loading: false, refreshing: false,
    messageBusy: false, drainBusy: false, error: "", mutationError: "",
  });
  assert.match(html, /OpenZyme Kernel workspace/);
  assert.match(html, /Message OpenZyme/);
  assert.doesNotMatch(html, /Extension views/);
});

test("contract blocker removes every mutation control", () => {
  const blocked = shell();
  blocked.contractBlocked = true;
  blocked.mutationAllowed = false;
  blocked.blockingError = "renderer_catalog_drift";
  const html = renderApp({ shell: blocked, loading: false, error: "" });
  assert.match(html, /non-operational/);
  assert.match(html, /renderer_catalog_drift/);
  assert.doesNotMatch(html, /<form|runtime-drain/);
});
