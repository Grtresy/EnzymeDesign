import test from "node:test";
import assert from "node:assert/strict";

import {
  buildInitialViewState,
  buildSessionSummaryFromWorkspace,
  reduceWorkspaceWithEvent,
  upsertSessionSummary,
} from "../src/state.js";
import { renderApp } from "../src/view.js";

function buildV3Workspace() {
  return {
    session: {
      session_id: "sess_001",
      project_id: "proj_001",
      title: "Plan with V3",
      objective: "Plan an enzyme design workflow",
      status: "active",
      created_at: "2026-04-21T00:00:00+00:00",
      updated_at: "2026-04-21T00:00:00+00:00",
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
    delegation: {
      agents: [
        {
          agent: {
            agent_id: "agent:researcher",
            name: "researcher",
            role: "researcher",
            status: "active",
            task_id: "task_001",
          },
          correlation_ids: ["corr_001"],
          latest_correlation_id: "corr_001",
          latest_message_type: "delegation_request",
          latest_message_at: "2026-04-21T00:00:00+00:00",
          pending_correlation_ids: ["corr_001"],
          thread_summaries: [],
        },
      ],
    },
    pending_approvals: [],
    activity_feed: [],
    artifacts: [{ artifact_id: "art_001", title: "stdout.log", kind: "log" }],
    report_drafts: [{ draft_id: "draft_001", title: "Workspace draft", status: "ready" }],
    reports: [{ report_id: "report_001", title: "Summary report", status: "ready" }],
    capabilities: {
      execution: [{ invocation_id: "inv_001", status: "succeeded" }],
    },
    conversation: [],
  };
}

test("view state starts in three-column session mode", () => {
  const state = buildInitialViewState();
  const html = renderApp(state);
  assert.equal(state.currentProjectId, "proj_001");
  assert.equal(state.currentSection, "conversation");
  assert.match(html, /Workspace/);
  assert.match(html, /Sessions/);
  assert.match(html, /Select a session or create a new one/);
});

test("session summary is derived from workspace and sorted to the top", () => {
  const summaryA = buildSessionSummaryFromWorkspace(buildV3Workspace());
  const summaryB = { ...summaryA, session_id: "sess_002", updated_at: "2026-04-20T00:00:00+00:00" };
  const sorted = upsertSessionSummary([summaryB], summaryA);
  assert.equal(sorted[0].session_id, "sess_001");
  assert.equal(sorted[0].latest_message_preview, "");
});

test("v3 conversation events render in the central chat column", () => {
  let workspace = buildV3Workspace();
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_user",
    event_type: "conversation.user_message",
    created_at: "2026-04-21T00:00:01+00:00",
    payload: { content: "Start planning" },
  });
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_agent",
    event_type: "conversation.assistant_message",
    created_at: "2026-04-21T00:00:02+00:00",
    payload: { content: "Received: Start planning" },
  });

  const html = renderApp({
    currentProjectId: "proj_001",
    currentSessionId: "sess_001",
    currentSection: "tasks",
    sidebarExpandedSessionIds: ["sess_001"],
    sessionSummaries: [buildSessionSummaryFromWorkspace(workspace)],
    workspace,
    errorMessage: "",
    sidebarBusy: false,
    messageBusy: false,
  });

  assert.match(html, /Start planning/);
  assert.match(html, /Received: Start planning/);
  assert.match(html, /Extract goals/);
  assert.match(html, /Conversation/);
  assert.match(html, /Tasks/);
});

test("report draft events are tracked in activity and rendered in outputs", () => {
  let workspace = buildV3Workspace();
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_draft",
    event_type: "report_draft.updated",
    created_at: "2026-04-21T00:00:06+00:00",
    payload: { draft_id: "draft_001", status: "ready", title: "Workspace draft" },
  });

  const html = renderApp({
    currentProjectId: "proj_001",
    currentSessionId: "sess_001",
    currentSection: "outputs",
    sidebarExpandedSessionIds: ["sess_001"],
    sessionSummaries: [buildSessionSummaryFromWorkspace(workspace)],
    workspace,
    errorMessage: "",
    sidebarBusy: false,
    messageBusy: false,
  });

  assert.equal(workspace.activity_feed[0].event_type, "report_draft.updated");
  assert.match(html, /Report Drafts/);
  assert.match(html, /Workspace draft/);
});

test("team inspector renders delegated teammate status", () => {
  const workspace = buildV3Workspace();
  const html = renderApp({
    currentProjectId: "proj_001",
    currentSessionId: "sess_001",
    currentSection: "team",
    sidebarExpandedSessionIds: ["sess_001"],
    sessionSummaries: [buildSessionSummaryFromWorkspace(workspace)],
    workspace,
    errorMessage: "",
    sidebarBusy: false,
    messageBusy: false,
  });

  assert.match(html, /Team/);
  assert.match(html, /researcher/);
  assert.match(html, /task_001/);
});

test("approval events update pending approvals and activity", () => {
  let workspace = buildV3Workspace();
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_approval_requested",
    event_type: "approval.requested",
    created_at: "2026-04-21T00:00:03+00:00",
    payload: { approval_id: "appr_001", requested_action: "Approve execution" },
  });
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_approval_resolved",
    event_type: "approval.resolved",
    created_at: "2026-04-21T00:00:04+00:00",
    payload: { approval_id: "appr_001", decision: "approved" },
  });

  assert.equal(workspace.pending_approvals.length, 0);
  assert.equal(workspace.activity_feed[0].event_type, "approval.resolved");
});

test("duplicate events are ignored without cloning the workspace", () => {
  const workspace = buildV3Workspace();
  const duplicate = {
    event_id: "evt_dup",
    event_type: "tool.completed",
    created_at: "2026-04-21T00:00:05+00:00",
    payload: { tool_name: "task.create" },
  };
  const first = reduceWorkspaceWithEvent(workspace, duplicate);
  const second = reduceWorkspaceWithEvent(first, duplicate);
  assert.notEqual(first, workspace);
  assert.equal(second, first);
});

test("workspace snapshots are not duplicated when the same conversation event is replayed", () => {
  const workspace = {
    ...buildV3Workspace(),
    conversation: [
      {
        message_id: "msg_001",
        role: "user",
        content: "Start planning",
        created_at: "2026-04-21T00:00:01+00:00",
      },
    ],
  };
  const next = reduceWorkspaceWithEvent(workspace, {
    event_id: "evt_user",
    event_type: "conversation.user_message",
    created_at: "2026-04-21T00:00:01+00:00",
    payload: { message_id: "msg_001", content: "Start planning" },
  });
  assert.equal(next, workspace);
});
