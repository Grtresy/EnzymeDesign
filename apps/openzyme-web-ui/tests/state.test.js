import assert from "node:assert/strict";
import test from "node:test";

import {
  FILE_WORKSPACE_PUBLIC_SCHEMA,
  requireFileWorkspaceProjection,
} from "../src/file_workspace_state.js";
import {
  mergeWorkspaceChangedPathsPage,
  reduceWorkspaceWithEvent,
} from "../src/state.js";

const toolCatalogDigest = `sha256:${"1".repeat(64)}`;
const schemaBundleDigest = `sha256:${"2".repeat(64)}`;

function workspace() {
  return {
    schema_version: FILE_WORKSPACE_PUBLIC_SCHEMA,
    tool_catalog_digest: toolCatalogDigest,
    schema_bundle_digest: schemaBundleDigest,
    session: { session_id: "session-1", project_id: "project-1" },
    agent_workspaces: [],
    workspace_status: [{
      workspace_id: "workspace-1",
      workspace_generation: 4,
      changed_paths: ["README.md"],
      changed_paths_truncated: true,
      changed_paths_continuation: "observation-1:100",
    }],
    private_revisions: [],
    published_revisions: [],
    reports: [],
    scientific_deliverables: [],
    external_jobs: [],
    external_job_results: [],
    capability_leases: [],
    failure_observations: [],
  };
}

test("public workspace contract requires structured diagnostics and rejects private payload", () => {
  assert.throws(
    () => requireFileWorkspaceProjection(
      { ...workspace(), failure_observations: undefined },
      { toolCatalogDigest, schemaBundleDigest },
    ),
    /section failure_observations is invalid/,
  );
  assert.throws(
    () => requireFileWorkspaceProjection(
      {
        ...workspace(),
        failure_observations: [{
          failure_id: "failure-1",
          private_diagnostic: { traceback: "token=secret" },
        }],
      },
      { toolCatalogDigest, schemaBundleDigest },
    ),
    /private diagnostic field private_diagnostic is forbidden/,
  );
});

test("changed-path page merges only into the exact workspace generation", () => {
  const source = workspace();
  const merged = mergeWorkspaceChangedPathsPage(source, "workspace-1", {
    schema_version: "workspace_changed_paths_page@1",
    workspace_id: "workspace-1",
    workspace_generation: 4,
    paths: ["scientific/result.json"],
    continuation: null,
    source_truncated: false,
  });
  assert.deepEqual(
    merged.workspace_status[0].changed_paths,
    ["README.md", "scientific/result.json"],
  );
  assert.equal(merged.workspace_status[0].changed_paths_continuation, null);
  assert.deepEqual(source.workspace_status[0].changed_paths, ["README.md"]);

  assert.throws(
    () => mergeWorkspaceChangedPathsPage(source, "workspace-1", {
      schema_version: "workspace_changed_paths_page@1",
      workspace_id: "workspace-1",
      workspace_generation: 3,
      paths: [],
      continuation: null,
    }),
    /workspace identity is stale/,
  );
});

test("stale event blocks state instead of fabricating a refresh", () => {
  const reduced = reduceWorkspaceWithEvent(workspace(), {
    schema_version: "file_workspace_public@0",
    event_id: "event-stale",
  });
  assert.equal(reduced.contract_blocked, true);
  assert.equal(reduced.refresh_required, undefined);
  assert.match(reduced.contract_error, /stale file-workspace event contract/);
});
