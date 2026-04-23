import test from "node:test";
import assert from "node:assert/strict";

import { WorkspaceController } from "../src/controller.js";

function buildV3Workspace(sessionId = "sess_001", title = "Plan with V3") {
  return {
    session: {
      session_id: sessionId,
      project_id: "proj_001",
      title,
      objective: title,
      status: "active",
      created_at: "2026-04-21T00:00:00+00:00",
      updated_at: "2026-04-21T00:00:00+00:00",
    },
    task_board: { items: [] },
    lane_board: { lanes: [] },
    delegation: { agents: [] },
    pending_approvals: [],
    activity_feed: [],
    artifacts: [],
    reports: [],
    capabilities: {},
    conversation: [],
  };
}

function buildV3ApprovalWorkspace() {
  return {
    ...buildV3Workspace(),
    pending_approvals: [
      {
        approval_id: "appr_v3_001",
        kind: "execution_launch",
        requested_action: "Approve execution launch for task Run fpocket",
        task_id: "task_execution",
        lane_id: "lane_001",
        status: "pending",
      },
    ],
  };
}

test("workspace controller bootstraps with project session summaries", async () => {
  const fakeClient = {
    async listV3Sessions() {
      return [{ session_id: "sess_001", title: "Plan with V3", updated_at: "2026-04-21T00:00:00+00:00" }];
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.bootstrap();

  assert.equal(controller.state.currentProjectId, "proj_001");
  assert.equal(controller.state.sessionSummaries.length, 1);
  assert.equal(controller.state.sidebarBusy, false);
});

test("workspace controller creates v3 sessions and opens the conversation view", async () => {
  let streamHandler = null;
  const fakeClient = {
    async listV3Sessions() {
      return [{ session_id: "sess_001", title: "Plan with V3", updated_at: "2026-04-21T00:00:00+00:00" }];
    },
    async createV3Session() {
      return {
        session_id: "sess_001",
        workspace: buildV3Workspace(),
        events: [],
      };
    },
    streamV3Session(_sessionId, onEvent) {
      streamHandler = onEvent;
      return { close() {} };
    },
    async getV3Session() {
      return { session: buildV3Workspace().session, workspace: buildV3Workspace() };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  assert.equal(controller.state.currentSessionId, "sess_001");
  assert.equal(controller.state.currentSection, "conversation");
  assert.deepEqual(controller.state.sidebarExpandedSessionIds, ["sess_001"]);

  streamHandler?.({
    event_id: "evt_tool",
    event_type: "tool.completed",
    payload: { tool_name: "task.create" },
    created_at: "now",
  });
  assert.equal(controller.state.workspace.activity_feed[0].event_type, "tool.completed");

  const activityFeedRef = controller.state.workspace.activity_feed;
  streamHandler?.({
    event_id: "evt_tool",
    event_type: "tool.completed",
    payload: { tool_name: "task.create" },
    created_at: "now",
  });
  assert.equal(controller.state.workspace.activity_feed, activityFeedRef);
});

test("selectSession loads a workspace and can switch inspector sections", async () => {
  const fakeClient = {
    async listV3Sessions() {
      return [{ session_id: "sess_001", title: "Plan with V3", updated_at: "2026-04-21T00:00:00+00:00" }];
    },
    async getV3Session() {
      return { session: buildV3Workspace().session, workspace: buildV3Workspace() };
    },
    streamV3Session() {
      return { close() {} };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.selectSession("sess_001", "tasks");
  assert.equal(controller.state.currentSessionId, "sess_001");
  assert.equal(controller.state.currentSection, "tasks");

  controller.selectSection("activity");
  assert.equal(controller.state.currentSection, "activity");
});

test("workspace controller resolves v3 approvals and refreshes summaries", async () => {
  let resolveCall = null;
  const fakeClient = {
    async listV3Sessions() {
      return [{ session_id: "sess_001", title: "Plan with V3", updated_at: "2026-04-21T00:00:00+00:00" }];
    },
    async createV3Session() {
      return {
        session_id: "sess_001",
        workspace: buildV3ApprovalWorkspace(),
        events: [],
      };
    },
    streamV3Session() {
      return { close() {} };
    },
    async resolveV3Approval(approvalId, payload) {
      resolveCall = { approvalId, payload };
      return {
        session_id: "sess_001",
        status: "completed",
        outputs: ["execution.resume completed."],
        workspace: buildV3Workspace(),
        events: [
          {
            event_id: "evt_approval",
            event_type: "approval.resolved",
            payload: { approval_id: approvalId, decision: payload.decision },
            created_at: "now",
          },
        ],
      };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  await controller.resolveApproval("appr_v3_001", "approved");

  assert.deepEqual(resolveCall, {
    approvalId: "appr_v3_001",
    payload: { decision: "approved", actor_ref: "user" },
  });
  assert.equal(controller.state.workspace.pending_approvals.length, 0);
});

test("sendMessage is ignored while another request is already in flight", async () => {
  let postCalls = 0;
  let releasePost;
  const postPromise = new Promise((resolve) => {
    releasePost = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [{ session_id: "sess_001", title: "Plan with V3", updated_at: "2026-04-21T00:00:00+00:00" }];
    },
    async createV3Session() {
      return {
        session_id: "sess_001",
        workspace: buildV3Workspace(),
        events: [],
      };
    },
    streamV3Session() {
      return { close() {} };
    },
    async postV3Message() {
      postCalls += 1;
      await postPromise;
      return {
        session_id: "sess_001",
        status: "completed",
        outputs: [],
        workspace: buildV3Workspace(),
        events: [],
      };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });

  const pending = controller.sendMessage("hello");
  await Promise.resolve();
  await controller.sendMessage("hello again");
  releasePost();
  await pending;

  assert.equal(postCalls, 1);
});

test("stale sendMessage responses do not overwrite the currently selected session", async () => {
  let releasePost;
  const postPromise = new Promise((resolve) => {
    releasePost = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [];
    },
    async getV3Session(sessionId) {
      return {
        session: buildV3Workspace(sessionId, sessionId).session,
        workspace: buildV3Workspace(sessionId, sessionId),
      };
    },
    streamV3Session() {
      return { close() {} };
    },
    async postV3Message() {
      await postPromise;
      return {
        session_id: "sess_001",
        status: "completed",
        outputs: [],
        workspace: buildV3Workspace("sess_001", "First"),
        events: [],
      };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  controller.state.currentProjectId = "proj_001";
  controller.state.currentSessionId = "sess_001";
  controller.state.workspace = buildV3Workspace("sess_001", "First");

  const pending = controller.sendMessage("hello");
  await Promise.resolve();
  await controller.selectSession("sess_002", "conversation");
  releasePost();
  await pending;

  assert.equal(controller.state.currentSessionId, "sess_002");
  assert.equal(controller.state.workspace.session.session_id, "sess_002");
  assert.equal(controller.state.messageBusy, false);
});
