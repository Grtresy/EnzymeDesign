import assert from "node:assert/strict";
import test from "node:test";

import { WorkspaceController } from "../src/controller.js";

function workspace() {
  return {
    schema_version: "file_workspace_public@1",
    session: { session_id: "session-1", project_id: "project-1" },
    workspace_status: [{
      workspace_id: "workspace-1",
      workspace_generation: 2,
      changed_paths: ["README.md"],
      changed_paths_truncated: true,
      changed_paths_continuation: "observation-1:100",
    }],
  };
}

function controllerWith(client) {
  const controller = new WorkspaceController(client);
  controller.state.currentSessionId = "session-1";
  controller.state.workspace = workspace();
  return controller;
}

test("controller consumes a bounded changed-path page without refreshing unrelated state", async () => {
  const calls = [];
  const controller = controllerWith({
    async getV3WorkspaceChangedPathsPage(...args) {
      calls.push(args);
      return {
        schema_version: "workspace_changed_paths_page@1",
        workspace_id: "workspace-1",
        workspace_generation: 2,
        paths: ["scientific/result.json"],
        continuation: null,
        source_truncated: false,
      };
    },
  });
  assert.equal(await controller.loadMoreChangedPaths("workspace-1"), true);
  assert.deepEqual(calls, [[
    "session-1",
    "workspace-1",
    2,
    "observation-1:100",
  ]]);
  assert.deepEqual(
    controller.state.workspace.workspace_status[0].changed_paths,
    ["README.md", "scientific/result.json"],
  );
  assert.equal(controller.state.pendingWorkspacePathId, "");
});

test("controller discards a late page after workspace generation changes", async () => {
  let resolvePage;
  const controller = controllerWith({
    getV3WorkspaceChangedPathsPage() {
      return new Promise((resolve) => {
        resolvePage = resolve;
      });
    },
  });
  const pending = controller.loadMoreChangedPaths("workspace-1");
  controller.state.workspace.workspace_status[0].workspace_generation = 3;
  resolvePage({
    schema_version: "workspace_changed_paths_page@1",
    workspace_id: "workspace-1",
    workspace_generation: 2,
    paths: ["must-not-merge.txt"],
    continuation: null,
    source_truncated: false,
  });
  assert.equal(await pending, false);
  assert.deepEqual(controller.state.workspace.workspace_status[0].changed_paths, ["README.md"]);
});

test("controller exposes pagination failure without fallback or inferred success", async () => {
  const controller = controllerWith({
    async getV3WorkspaceChangedPathsPage() {
      throw new Error("changed_paths_identity_stale: expected generation 2, observed 3");
    },
  });
  assert.equal(await controller.loadMoreChangedPaths("workspace-1"), false);
  assert.match(
    controller.state.errors.changedPaths["workspace-1"],
    /expected generation 2, observed 3/,
  );
  assert.equal(
    controller.state.workspace.workspace_status[0].changed_paths_continuation,
    "observation-1:100",
  );
});
