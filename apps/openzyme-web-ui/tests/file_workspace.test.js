import assert from "node:assert/strict";
import test from "node:test";

import {
  FILE_WORKSPACE_PUBLIC_SCHEMA,
  reduceFileWorkspaceEvent,
  requireFileWorkspaceProjection,
} from "../src/file_workspace_state.js";
import {
  renderExecutorOwnerWorkspace,
  renderFileWorkspaceOutputs,
} from "../src/file_workspace_view.js";
import {
  buildSessionSummaryFromWorkspace,
  reduceWorkspaceWithEvent,
} from "../src/state.js";

const toolCatalogDigest = `sha256:${"1".repeat(64)}`;
const schemaBundleDigest = `sha256:${"2".repeat(64)}`;

function workspace() {
  return {
    schema_version: FILE_WORKSPACE_PUBLIC_SCHEMA,
    tool_catalog_digest: toolCatalogDigest,
    schema_bundle_digest: schemaBundleDigest,
    session: {
      session_id: "session-1",
      project_id: "project-1",
      objective: "Publish revision-bound scientific files",
      status: "active",
      created_at: "2026-08-17T00:00:00+00:00",
      updated_at: "2026-08-17T00:01:00+00:00",
    },
    conversation: [{ role: "user", content: "Inspect the revision" }],
    agent_workspaces: [],
    workspace_status: [],
    private_revisions: [],
    published_revisions: [
      {
        publication_id: "publication-1",
        commit: "a".repeat(40),
        manifest_digest: `sha256:${"3".repeat(64)}`,
      },
    ],
    reports: [],
    scientific_deliverables: [
      {
        scientific_role: "reference_sequence",
        path: "scientific/reference.fasta",
        content_digest: `sha256:${"4".repeat(64)}`,
      },
    ],
    external_jobs: [],
    external_job_results: [],
    capability_leases: [],
    failure_observations: [],
  };
}

test("current file-workspace projection closes its release identity", () => {
  const source = workspace();
  const projection = requireFileWorkspaceProjection(source, {
    toolCatalogDigest,
    schemaBundleDigest,
  });
  assert.deepEqual(projection, source);
  projection.published_revisions.length = 0;
  assert.equal(source.published_revisions.length, 1);
});

test("stale projection and event schemas fail closed", () => {
  assert.throws(
    () => requireFileWorkspaceProjection(
      { ...workspace(), schema_version: "stale@1" },
      { toolCatalogDigest, schemaBundleDigest },
    ),
    /unsupported file-workspace public schema/,
  );
  assert.deepEqual(
    reduceFileWorkspaceEvent({ blocked: false }, { schema_version: "stale@1" }),
    {
      blocked: true,
      blocking_error: "stale file-workspace event contract",
    },
  );
});

test("current events request refresh without fabricating state", () => {
  const source = workspace();
  const reduced = reduceWorkspaceWithEvent(source, {
    schema_version: FILE_WORKSPACE_PUBLIC_SCHEMA,
    event_id: "event-1",
  });
  assert.equal(reduced.refresh_required, true);
  assert.equal(reduced.last_event_id, "event-1");
  assert.equal(reduced.published_revisions[0].publication_id, "publication-1");
});

test("file outputs render immutable revision and scientific identities", () => {
  const html = renderFileWorkspaceOutputs(workspace());
  assert.match(html, /Published revisions/);
  assert.match(html, /publication-1/);
  assert.match(html, /reference_sequence/);
  assert.match(html, /scientific\/reference\.fasta/);
});

test("executor owner view exposes only bounded workspace facts", () => {
  const html = renderExecutorOwnerWorkspace({
    workspace_id: "workspace-1",
    workspace_generation: 2,
    login_alias: "agent_executor",
    workspace_path: "/srv/openzyme/workspaces/workspace-1",
  });
  assert.match(html, /workspace-1/);
  assert.match(html, /agent_executor/);
  assert.doesNotMatch(html, /token|credential/i);
});

test("session summaries are derived from the current projection", () => {
  const summary = buildSessionSummaryFromWorkspace(workspace());
  assert.equal(summary.session_id, "session-1");
  assert.equal(summary.latest_message_preview, "Inspect the revision");
});
