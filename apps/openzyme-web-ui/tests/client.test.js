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
      conversation: { memories: [], messages: [] },
      failures: { observations: [] },
      lanes: [],
      operations: {
        command_receipts: [], continuations: [], controlled: [],
        publication_intents: [], task_evidence: [],
      },
      protocol: { inbox: [], records: [] },
      publications: [],
      runtime: {
        continuation_intents: [], outcome_consumptions: [], session_leases: [],
        settlement_intents: [], signals: [], turn_commands: [],
      },
      session: { session_id: "session-1", objective: "Verify exact UI" },
      tasks: [],
      tool_reflection: {
        declared_tool_catalog_digest: expectedRelease.declared_tool_catalog_digest,
        affordance_snapshot_digest: digest("9"),
        capability_binding_digest: binding,
        available_tool_names: [],
        affordances: [],
      },
      workspace: {
        checkpoints: [], generations: [], repository_binding_pins: [],
        revision_path_verifications: [], runtime_bindings: [],
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
    { message: "continue" },
    "web-ui:message:1",
  );

  assert.equal(result.responseStatus, 202);
  assert.deepEqual(requests.map((item) => item.options.method ?? "GET"), ["GET", "POST", "GET"]);
  assert.equal(requests[1].options.headers["Idempotency-Key"], "web-ui:message:1");
  assert.equal(
    requests[1].options.headers["OpenZyme-Capability-Binding-Digest"],
    digest("8"),
  );
});

test("post-dispatch identity drift is unknown-effect and never falls back", async () => {
  const inspected = await workspaceResponse();
  const mutation = await workspaceResponse(projection(), {
    "openzyme-projection-digest": digest("0"),
  });
  const responses = [inspected, mutation];
  const client = new HostApiV2Client({
    expectedRelease: release(),
    fetchImpl: async () => responses.shift(),
  });

  await assert.rejects(
    client.postMessage("session-1", { message: "continue" }, "web-ui:message:2"),
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

test("buildHostV2Paths exposes only activated exact @2 routes", () => {
  assert.deepEqual(buildHostV2Paths("session-1"), {
    workspace: "/v3/sessions/session-1/workspace",
    messages: "/v3/sessions/session-1/messages",
    runtimeDrain: "/v3/sessions/session-1/runtime/drain",
  });
});
