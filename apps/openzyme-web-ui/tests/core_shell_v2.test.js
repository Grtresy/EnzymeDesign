import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { buildCoreShellState, reduceCoreShellEvent } from "../src/core_shell.js";
import { ExtensionRendererRegistry } from "../src/extension_renderer_loader.js";
import { requireAvailableTool } from "../src/file_workspace_v2_state.js";


const digest = (character) => `sha256:${character.repeat(64)}`;

function core() {
  const bindingDigest = digest("1");
  return {
    agents: [],
    approvals: [],
    authority_leases: [],
    capability_binding: { binding_digest: bindingDigest },
    conversation: { memories: [], messages: [] },
    failures: { observations: [] },
    lanes: [],
    operations: {
      command_receipts: [],
      continuations: [],
      controlled: [],
      publication_intents: [],
      task_evidence: [],
    },
    protocol: { inbox: [], records: [] },
    publications: [],
    runtime: {
      continuation_intents: [],
      outcome_consumptions: [],
      session_leases: [],
      settlement_intents: [],
      signals: [],
      turn_commands: [],
    },
    session: { session_id: "session-1" },
    tasks: [],
    tool_reflection: {
      declared_tool_catalog_digest: digest("8"),
      affordance_snapshot_digest: digest("9"),
      capability_binding_digest: bindingDigest,
      available_tool_names: [],
      affordances: [],
    },
    workspace: {
      checkpoints: [],
      generations: [],
      repository_binding_pins: [],
      revision_path_verifications: [],
      runtime_bindings: [],
    },
  };
}

function projection(extensions = {}) {
  return {
    schema_version: "file_workspace_public@2",
    release: {
      schema_version: "openzyme_layered_release_identity@1",
      kernel_contract_digest: digest("a"),
      core_schema_digest: digest("b"),
      adapter_bundle_digest: digest("c"),
      declared_tool_catalog_digest: digest("8"),
      route_catalog_digest: digest("d"),
      migration_catalog_digest: digest("e"),
      workspace_backend_digest: digest("f"),
      release_digest: digest("2"),
      public_contract_digest: digest("3"),
      extension_bundle_digest: digest("4"),
      projection_catalog_digest: digest("5"),
      host_build_digest: digest("6"),
      client_build_digest: digest("7"),
    },
    core: core(),
    extensions,
  };
}

function registry(entries = [], rendererCatalogDigest = digest("8")) {
  return new ExtensionRendererRegistry({ rendererCatalogDigest, entries });
}

test("plugin-free @2 projection yields a Core-only mutable shell", () => {
  const shell = buildCoreShellState(projection(), registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });

  assert.equal(shell.core.session.session_id, "session-1");
  assert.deepEqual(shell.extensionRendering.renderedSections, {});
  assert.equal(shell.contractBlocked, false);
  assert.equal(shell.mutationAllowed, true);
  assert.equal("extensions" in shell.core, false);
});

test("extension payload is handled only by its exact manifest renderer", () => {
  const sectionContractDigest = digest("9");
  const rendererContractDigest = digest("a");
  const science = {
    attempts: [{ attempt_id: "attempt-1", scientific_terminal: "closed" }],
  };
  const shell = buildCoreShellState(
    projection({
      "openzyme.science@1": {
        section_contract_digest: sectionContractDigest,
        payload: science,
        next_cursor: null,
        projection_digest: digest("b"),
      },
    }),
    registry([{
      sectionId: "openzyme.science@1",
      sectionContractDigest,
      rendererId: "openzyme.science.renderer@1",
      rendererContractDigest,
      render(payload, identity) {
        return {
          attemptCount: payload.attempts.length,
          rendererId: identity.rendererId,
        };
      },
    }]),
    { expectedRendererCatalogDigest: digest("8") },
  );

  assert.deepEqual(shell.extensionRendering.renderedSections, {
    "openzyme.science@1": {
      attemptCount: 1,
      rendererId: "openzyme.science.renderer@1",
    },
  });
  assert.equal("attempts" in shell.core, false);
  assert.equal("scientific_terminal" in shell.core, false);
  assert.equal(shell.mutationAllowed, true);
});

test("missing or stale renderer identity blocks mutation without fallback", () => {
  const payload = projection({
    "openzyme.reporting@1": {
      section_contract_digest: digest("c"),
      payload: { reports: [] },
      next_cursor: null,
      projection_digest: digest("d"),
    },
  });
  const missing = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });
  assert.equal(missing.mutationAllowed, false);
  assert.deepEqual(missing.extensionRendering.renderedSections, {});
  assert.equal(
    missing.extensionRendering.blockers[0].code,
    "extension_renderer_missing",
  );

  const staleCatalog = buildCoreShellState(payload, registry([], digest("e")), {
    expectedRendererCatalogDigest: digest("8"),
  });
  assert.equal(staleCatalog.mutationAllowed, false);
  assert.deepEqual(
    staleCatalog.extensionRendering.blockers.map((item) => item.code),
    ["renderer_catalog_drift", "extension_renderer_missing"],
  );
});

test("Core section rejects extension semantics while extension namespace permits them", () => {
  const invalid = projection();
  invalid.core.reports = [];
  assert.throws(
    () => buildCoreShellState(invalid, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /core fields are closed/,
  );

  const extensionPayload = projection({
    "openzyme.reporting@1": {
      section_contract_digest: digest("f"),
      payload: { reports: [] },
      next_cursor: null,
      projection_digest: digest("0"),
    },
  });
  assert.doesNotThrow(() => buildCoreShellState(
    extensionPayload,
    registry([{
      sectionId: "openzyme.reporting@1",
      sectionContractDigest: digest("f"),
      rendererId: "openzyme.reporting.renderer@1",
      rendererContractDigest: digest("1"),
      render: () => ({ rendered: true }),
    }]),
    { expectedRendererCatalogDigest: digest("8") },
  ));
});

test("Core object subsection fields are closed", () => {
  const invalid = projection();
  invalid.core.workspace.legacy_status = [];
  assert.throws(
    () => buildCoreShellState(invalid, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /core\.workspace fields are closed/,
  );
});

test("stale @2 event blocks Core mutation instead of translating it", () => {
  const shell = buildCoreShellState(projection(), registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });
  const blocked = reduceCoreShellEvent(shell, {
    schema_version: "file_workspace_public@1",
    event_id: "event-old",
  });
  assert.equal(blocked.contractBlocked, true);
  assert.equal(blocked.mutationAllowed, false);
  assert.equal(blocked.refreshRequired, false);
});

test("renderer registry rejects duplicate section ownership", () => {
  const entry = {
    sectionId: "openzyme.science@1",
    sectionContractDigest: digest("2"),
    rendererId: "openzyme.science.renderer@1",
    rendererContractDigest: digest("3"),
    render: () => ({}),
  };
  assert.throws(
    () => registry([entry, entry]),
    /duplicated/,
  );
});

test("inactive or degraded plugin affordance stays visible but cannot dispatch", () => {
  for (const [state, blockerCode] of [
    ["blocked_dependency", "plugin_inactive"],
    ["blocked_qualification", "plugin_degraded"],
  ]) {
    const payload = projection();
    payload.core.tool_reflection.affordances = [{
      tool_name: "openzyme.science.inspect",
      tool_contract_digest: digest("1"),
      state,
      required_authorities: [],
      route_ids: [],
      route_refs: [],
      blockers: [{ code: blockerCode, requirement: null, target_id: null }],
    }];
    const shell = buildCoreShellState(payload, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    });

    assert.equal(shell.mutationAllowed, true);
    assert.equal(shell.toolAffordances[0].state, state);
    assert.throws(
      () => requireAvailableTool(shell, "openzyme.science.inspect"),
      new RegExp(`${blockerCode}.*fallback_performed=false`),
    );
  }
});

test("available tool list and affordance state must agree exactly", () => {
  const payload = projection();
  payload.core.tool_reflection.available_tool_names = ["workspace.status"];
  assert.throws(
    () => buildCoreShellState(payload, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /available tool names differ/,
  );
});

test("packaged TypeScript contract snapshot names the exact @2 ownership split", async () => {
  const declaration = await readFile(
    new URL("../src/file_workspace_v2_types.d.ts", import.meta.url),
    "utf8",
  );
  for (const required of [
    "file_workspace_public@2",
    "LayeredReleaseIdentityV2",
    "FileWorkspaceV2Core",
    "PublicToolAffordanceState",
    "extensions: Record<string, FileWorkspaceV2ExtensionSection>",
  ]) {
    assert.equal(declaration.includes(required), true, required);
  }
  for (const forbidden of ["scientific_attempts", "reports:", "hpc_workspaces"] ) {
    assert.equal(declaration.includes(forbidden), false, forbidden);
  }
});
