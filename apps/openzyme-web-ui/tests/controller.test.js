import test from "node:test";
import assert from "node:assert/strict";

import { WorkspaceController } from "../src/controller.js";

function buildPendingWorkspace() {
  return {
    episode_id: "ep_001",
    workflow: {
      episode_id: "ep_001",
      objective: "Improve thermostability",
      current_phase: "execution",
      episode_status: "interrupted",
      progress: {
        phase: "execution",
        active_node: "approval_gate",
        status: "waiting",
        updated_at: "2026-04-11T00:00:00+00:00",
        message: "Waiting for approval",
      },
      pending_interrupt: { type: "approval", approval_id: "appr_001" },
      pending_approval: {
        approval_id: "appr_001",
        requested_action: "Approve execution submission",
        created_at: "2026-04-11T00:00:00+00:00",
      },
      updated_at: "2026-04-11T00:00:00+00:00",
    },
    pending_actions: [
      {
        approval_id: "appr_001",
        requested_action: "Approve execution submission",
        status: "pending",
        created_at: "2026-04-11T00:00:00+00:00",
      },
    ],
    runs: [],
    artifacts: [],
    report: null,
  };
}

function buildCompletedWorkspace() {
  return {
    episode_id: "ep_001",
    workflow: {
      episode_id: "ep_001",
      objective: "Improve thermostability",
      current_phase: "execution",
      episode_status: "completed",
      progress: {
        phase: "execution",
        active_node: "execute_runner",
        status: "succeeded",
        updated_at: "2026-04-11T00:02:00+00:00",
        message: "Execution finished",
      },
      pending_interrupt: null,
      pending_approval: null,
      updated_at: "2026-04-11T00:02:00+00:00",
    },
    pending_actions: [],
    runs: [
      {
        run_id: "run_001",
        episode_id: "ep_001",
        status: "succeeded",
        execution_mode: "ssh",
        created_at: "2026-04-11T00:01:00+00:00",
        completed_at: "2026-04-11T00:02:00+00:00",
      },
    ],
    artifacts: [
      {
        artifact_id: "art_001",
        episode_id: "ep_001",
        run_id: "run_001",
        kind: "result",
        storage_uri: "/tmp/result.json",
        created_at: "2026-04-11T00:02:00+00:00",
      },
    ],
    report: null,
  };
}

test("workspace controller closes the loop from create through approval output visibility", async () => {
  let streamHandler = null;
  const changes = [];
  const fakeClient = {
    async createEpisode() {
      return { episode_id: "ep_001", workspace: buildPendingWorkspace() };
    },
    async resumeEpisode() {
      return { episode_id: "ep_001", workspace: buildCompletedWorkspace() };
    },
    async resolveApproval() {
      return { episode_id: "ep_001", workspace: buildCompletedWorkspace() };
    },
    streamEpisode(_episodeId, onEvent) {
      streamHandler = onEvent;
      return { close() {} };
    },
  };

  const controller = new WorkspaceController(fakeClient, (snapshot) => {
    changes.push(snapshot);
  });

  await controller.createEpisode({
    project_id: "proj_001",
    objective: "Improve thermostability",
  });
  assert.equal(controller.state.currentEpisodeId, "ep_001");
  assert.equal(controller.state.workspace.pending_actions.length, 1);

  await controller.resolveApproval("approved");
  assert.equal(controller.state.workspace.runs[0].run_id, "run_001");
  assert.equal(controller.state.workspace.artifacts[0].artifact_id, "art_001");

  streamHandler?.({
    event_type: "workflow.artifact_available",
    artifact: {
      artifact_id: "art_002",
      episode_id: "ep_001",
      run_id: "run_001",
      kind: "log",
      storage_uri: "/tmp/stdout.log",
      created_at: "2026-04-11T00:03:00+00:00",
    },
  });
  assert.equal(controller.state.workspace.artifacts.length, 2);
  assert.ok(changes.length >= 3);
});
