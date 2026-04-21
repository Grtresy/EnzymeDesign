import test from "node:test";
import assert from "node:assert/strict";

import { WorkspaceController } from "../src/controller.js";

function buildV3Workspace() {
  return {
    session: {
      session_id: "sess_001",
      project_id: "proj_001",
      objective: "Plan with V3",
      status: "active",
    },
    task_board: { items: [] },
    lane_board: { lanes: [] },
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

test("workspace controller bootstraps into an empty v3-only state", async () => {
  const controller = new WorkspaceController({});
  controller.state.workspace = buildV3Workspace();
  controller.state.currentSessionId = "sess_001";

  await controller.bootstrap();

  assert.equal(controller.state.currentSessionId, "");
  assert.equal(controller.state.workspace, null);
  assert.equal(controller.state.busy, false);
});

test("workspace controller creates v3 chat sessions and applies message events", async () => {
  let streamHandler = null;
  const fakeClient = {
    async createV3Session() {
      return {
        session_id: "sess_001",
        workspace: buildV3Workspace(),
        events: [{ event_id: "evt_session", event_type: "session.created", payload: {}, created_at: "now" }],
      };
    },
    streamV3Session(_sessionId, onEvent) {
      streamHandler = onEvent;
      return { close() {} };
    },
    async postV3Message() {
      return {
        session_id: "sess_001",
        status: "completed",
        outputs: ["Received: hello"],
        workspace: buildV3Workspace(),
        events: [
          {
            event_id: "evt_user",
            event_type: "conversation.user_message",
            payload: { content: "hello" },
            created_at: "now",
          },
          {
            event_id: "evt_agent",
            event_type: "conversation.assistant_message",
            payload: { content: "Received: hello" },
            created_at: "now",
          },
        ],
      };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  assert.equal(controller.state.currentSessionId, "sess_001");

  await controller.sendMessage("hello");
  assert.equal(controller.state.workspace.conversation.length, 2);
  assert.equal(controller.state.workspace.conversation[1].content, "Received: hello");

  streamHandler?.({
    event_id: "evt_tool",
    event_type: "tool.completed",
    payload: { tool_name: "task.create" },
    created_at: "now",
  });
  assert.equal(controller.state.workspace.activity_feed[0].event_type, "tool.completed");
});

test("workspace controller resolves v3 approvals through the session control plane", async () => {
  let resolveCall = null;
  const fakeClient = {
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
  assert.equal(controller.state.workspace.pending_approvals[0].approval_id, "appr_v3_001");

  await controller.resolveApproval("approved");

  assert.deepEqual(resolveCall, {
    approvalId: "appr_v3_001",
    payload: { decision: "approved", actor_ref: "user" },
  });
  assert.equal(controller.state.workspace.pending_approvals.length, 0);
  assert.equal(controller.state.workspace.activity_feed[0].event_type, "approval.resolved");
});

test("session stream events from a stale session are ignored", async () => {
  let streamHandler = null;
  const fakeClient = {
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
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  controller.state.currentSessionId = "sess_002";

  streamHandler?.({
    event_id: "evt_tool",
    event_type: "tool.completed",
    payload: { tool_name: "task.create" },
    created_at: "now",
  });

  assert.equal(controller.state.workspace.activity_feed.length, 0);
});

test("sendMessage is ignored while another request is already in flight", async () => {
  let postCalls = 0;
  let releasePost;
  const postPromise = new Promise((resolve) => {
    releasePost = resolve;
  });
  const fakeClient = {
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
