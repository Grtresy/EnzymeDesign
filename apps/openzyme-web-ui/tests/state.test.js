import test from "node:test";
import assert from "node:assert/strict";

import { buildInitialViewState, reduceWorkspaceWithEvent } from "../src/state.js";
import { renderApp } from "../src/view.js";

function buildV3Workspace() {
  return {
    session: {
      session_id: "sess_001",
      project_id: "proj_001",
      objective: "Plan an enzyme design workflow",
      status: "active",
    },
    task_board: {
      items: [
        {
          task: {
            task_id: "task_001",
            subject: "Extract goals",
            status: "todo",
          },
          bucket: "ready",
        },
      ],
    },
    lane_board: {
      lanes: [
        {
          lane: {
            lane_id: "lane_001",
            name: "analysis",
            status: "idle",
            cwd: "/tmp/lane_001",
          },
          tasks: [],
          ready_task_ids: [],
        },
      ],
    },
    pending_approvals: [],
    activity_feed: [],
    artifacts: [{ artifact_id: "art_001", title: "stdout.log", kind: "log" }],
    reports: [{ report_id: "report_001", title: "Summary report", status: "ready" }],
    capabilities: {
      execution: [{ invocation_id: "inv_001", status: "succeeded" }],
    },
  };
}

test("view state starts in v3 session mode", () => {
  const state = buildInitialViewState();
  const html = renderApp(state);
  assert.equal(state.currentProjectId, "proj_001");
  assert.equal(state.currentSessionId, "");
  assert.match(html, /Create Session/);
  assert.match(html, /Session-first workspace for the harness control plane/);
  assert.doesNotMatch(html, /Episode/);
});

test("v3 conversation events render as chat", () => {
  let workspace = buildV3Workspace();
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_user",
    event_type: "conversation.user_message",
    created_at: "2026-04-20T00:00:00+00:00",
    payload: { content: "Start planning" },
  });
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_agent",
    event_type: "conversation.assistant_message",
    created_at: "2026-04-20T00:00:01+00:00",
    payload: { content: "Received: Start planning" },
  });

  const html = renderApp({
    currentProjectId: "proj_001",
    currentSessionId: "sess_001",
    workspace,
    errorMessage: "",
    busy: false,
  });

  assert.match(html, /Conversation/);
  assert.match(html, /Start planning/);
  assert.match(html, /Received: Start planning/);
  assert.match(html, /Extract goals/);
  assert.match(html, /analysis/);
  assert.match(html, /Summary report/);
  assert.match(html, /execution/);
});

test("v3 pending approvals render as session approval cards", () => {
  const workspace = {
    ...buildV3Workspace(),
    pending_approvals: [
      {
        approval_id: "appr_v3_001",
        kind: "execution_launch",
        requested_action: "Approve fpocket execution",
        task_id: "task_001",
        lane_id: "lane_001",
      },
    ],
  };

  const html = renderApp({
    currentProjectId: "proj_001",
    currentSessionId: "sess_001",
    workspace,
    errorMessage: "",
    busy: false,
  });

  assert.match(html, /Approve fpocket execution/);
  assert.match(html, /data-v3-approval-decision="approved"/);
  assert.match(html, /data-v3-approval-decision="rejected"/);
});

test("activity events append to the v3 activity feed", () => {
  const workspace = reduceWorkspaceWithEvent(buildV3Workspace(), {
    event_id: "evt_tool",
    event_type: "tool.completed",
    created_at: "2026-04-20T00:00:02+00:00",
    payload: { tool_name: "task.create" },
  });

  assert.equal(workspace.activity_feed[0].event_type, "tool.completed");
  const html = renderApp({
    currentProjectId: "proj_001",
    currentSessionId: "sess_001",
    workspace,
    errorMessage: "",
    busy: false,
  });
  assert.match(html, /tool.completed/);
});
