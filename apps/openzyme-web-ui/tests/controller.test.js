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
    report_drafts: [],
    reports: [],
    capabilities: {},
    conversation: [],
    agent_traces: {},
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

function buildManualTimeouts() {
  let nextId = 1;
  const pending = new Map();
  return {
    setTimeout(callback, delay) {
      const id = nextId;
      nextId += 1;
      pending.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) {
      pending.delete(id);
    },
    get size() {
      return pending.size;
    },
    nextDelay() {
      return pending.values().next().value?.delay;
    },
    async runNext() {
      const next = pending.entries().next();
      assert.equal(next.done, false, "expected a scheduled timeout");
      const [id, scheduled] = next.value;
      pending.delete(id);
      await scheduled.callback();
    },
  };
}

test("workspace controller bootstraps with project session summaries", async () => {
  const fakeClient = {
    async listV3Sessions() {
      return [{ session_id: "sess_001", title: "Plan with V3", updated_at: "2026-04-21T00:00:00+00:00" }];
    },
    async getV3RuntimeHealth() {
      return {
        schema_version: "v3.runtime_health.v1",
        status: "degraded",
        deployment_profile: "local-dev",
        storage_profile: "single_process_sqlite",
        components: {},
      };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.bootstrap();

  assert.equal(controller.state.currentProjectId, "proj_001");
  assert.equal(controller.state.sessionSummaries.length, 1);
  assert.equal(controller.state.runtimeHealth.status, "degraded");
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
  assert.equal(controller.state.mobilePane, "inspector");

  controller.selectMobilePane("sessions");
  assert.equal(controller.state.mobilePane, "sessions");
});

test("periodic workspace reconciliation discovers a committed approval without an SSE event", async () => {
  const timeouts = buildManualTimeouts();
  let workspaceReads = 0;
  const fakeClient = {
    async listV3Sessions() {
      return [];
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
    async getV3Session() {
      workspaceReads += 1;
      const workspace = buildV3ApprovalWorkspace();
      return { session: workspace.session, workspace };
    },
  };
  const controller = new WorkspaceController(fakeClient, () => {}, {
    workspaceReconcileIntervalMs: 5_000,
    setReconcileTimeout: timeouts.setTimeout,
    clearReconcileTimeout: timeouts.clearTimeout,
  });

  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  assert.equal(controller.state.workspace.pending_approvals.length, 0);
  assert.equal(timeouts.size, 1);
  assert.equal(timeouts.nextDelay(), 5_000);

  await timeouts.runNext();

  assert.equal(workspaceReads, 1);
  assert.equal(controller.state.workspace.pending_approvals[0].approval_id, "appr_v3_001");
  assert.equal(timeouts.size, 1);
});

test("stale periodic workspace responses do not overwrite the currently selected session", async () => {
  const timeouts = buildManualTimeouts();
  let releaseStaleRead;
  let markStaleReadStarted;
  const staleReadStarted = new Promise((resolve) => {
    markStaleReadStarted = resolve;
  });
  const staleRead = new Promise((resolve) => {
    releaseStaleRead = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [];
    },
    async createV3Session() {
      return {
        session_id: "sess_001",
        workspace: buildV3Workspace("sess_001", "First"),
        events: [],
      };
    },
    streamV3Session() {
      return { close() {} };
    },
    async getV3Session(sessionId) {
      if (sessionId === "sess_001") {
        markStaleReadStarted();
        return staleRead;
      }
      const workspace = buildV3Workspace("sess_002", "Second");
      return { session: workspace.session, workspace };
    },
  };
  const controller = new WorkspaceController(fakeClient, () => {}, {
    workspaceReconcileIntervalMs: 5_000,
    setReconcileTimeout: timeouts.setTimeout,
    clearReconcileTimeout: timeouts.clearTimeout,
  });

  await controller.createSession({ project_id: "proj_001", objective: "First" });
  const pendingStaleRefresh = timeouts.runNext();
  await staleReadStarted;
  assert.equal(timeouts.size, 0, "reconciliation must not overlap its in-flight read");

  await controller.selectSession("sess_002", "conversation");
  const staleWorkspace = buildV3ApprovalWorkspace();
  releaseStaleRead({ session: staleWorkspace.session, workspace: staleWorkspace });
  await pendingStaleRefresh;

  assert.equal(controller.state.currentSessionId, "sess_002");
  assert.equal(controller.state.workspace.session.session_id, "sess_002");
  assert.equal(controller.state.workspace.session.title, "Second");
  assert.equal(controller.state.workspace.pending_approvals.length, 0);
});

test("stale periodic workspace responses do not restore an approval after resolution", async () => {
  const timeouts = buildManualTimeouts();
  let releaseStaleRead;
  let markStaleReadStarted;
  const staleReadStarted = new Promise((resolve) => {
    markStaleReadStarted = resolve;
  });
  const staleRead = new Promise((resolve) => {
    releaseStaleRead = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [];
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
    async getV3Session() {
      markStaleReadStarted();
      return staleRead;
    },
    async resolveV3Approval() {
      const workspace = buildV3Workspace();
      return { session_id: "sess_001", workspace, events: [] };
    },
  };
  const controller = new WorkspaceController(fakeClient, () => {}, {
    workspaceReconcileIntervalMs: 5_000,
    setReconcileTimeout: timeouts.setTimeout,
    clearReconcileTimeout: timeouts.clearTimeout,
  });

  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  const pendingStaleRefresh = timeouts.runNext();
  await staleReadStarted;

  await controller.resolveApproval("appr_v3_001", "approved");
  assert.equal(controller.state.workspace.pending_approvals.length, 0);

  const staleWorkspace = buildV3ApprovalWorkspace();
  releaseStaleRead({ session: staleWorkspace.session, workspace: staleWorkspace });
  await pendingStaleRefresh;

  assert.equal(controller.state.workspace.pending_approvals.length, 0);
});

test("stale periodic workspace responses do not overwrite a message response", async () => {
  const timeouts = buildManualTimeouts();
  let releaseStaleRead;
  let markStaleReadStarted;
  const staleReadStarted = new Promise((resolve) => {
    markStaleReadStarted = resolve;
  });
  const staleRead = new Promise((resolve) => {
    releaseStaleRead = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [];
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
    async getV3Session() {
      markStaleReadStarted();
      return staleRead;
    },
    async postV3Message() {
      const workspace = buildV3Workspace();
      workspace.conversation = [
        { role: "user", content: "hello", event_id: "evt_user_001" },
      ];
      return { session_id: "sess_001", workspace, events: [] };
    },
  };
  const controller = new WorkspaceController(fakeClient, () => {}, {
    workspaceReconcileIntervalMs: 5_000,
    setReconcileTimeout: timeouts.setTimeout,
    clearReconcileTimeout: timeouts.clearTimeout,
  });

  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  const pendingStaleRefresh = timeouts.runNext();
  await staleReadStarted;

  await controller.sendMessage("hello");
  assert.equal(controller.state.workspace.conversation[0].event_id, "evt_user_001");

  const staleWorkspace = buildV3Workspace();
  releaseStaleRead({ session: staleWorkspace.session, workspace: staleWorkspace });
  await pendingStaleRefresh;

  assert.equal(controller.state.workspace.conversation[0].event_id, "evt_user_001");
});

test("a hung old-session reconciliation cannot starve the newly selected session", async () => {
  const timeouts = buildManualTimeouts();
  let releaseOldRead;
  let markOldReadStarted;
  let oldSignal = null;
  let newSessionReads = 0;
  const oldReadStarted = new Promise((resolve) => {
    markOldReadStarted = resolve;
  });
  const oldRead = new Promise((resolve) => {
    releaseOldRead = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [];
    },
    async createV3Session() {
      return {
        session_id: "sess_001",
        workspace: buildV3Workspace("sess_001", "First"),
        events: [],
      };
    },
    streamV3Session() {
      return { close() {} };
    },
    async getV3Session(sessionId, options = {}) {
      if (sessionId === "sess_001") {
        oldSignal = options.signal;
        markOldReadStarted();
        return oldRead;
      }
      newSessionReads += 1;
      const workspace = buildV3Workspace("sess_002", "Second");
      if (newSessionReads > 1) {
        workspace.pending_approvals = [
          { approval_id: "appr_new_session", status: "pending" },
        ];
      }
      return { session: workspace.session, workspace };
    },
  };
  const controller = new WorkspaceController(fakeClient, () => {}, {
    workspaceReconcileIntervalMs: 5_000,
    setReconcileTimeout: timeouts.setTimeout,
    clearReconcileTimeout: timeouts.clearTimeout,
  });

  await controller.createSession({ project_id: "proj_001", objective: "First" });
  const pendingOldRefresh = timeouts.runNext();
  await oldReadStarted;

  await controller.selectSession("sess_002", "conversation");
  assert.equal(oldSignal?.aborted, true);
  assert.equal(timeouts.size, 1);

  await timeouts.runNext();

  assert.equal(newSessionReads, 2);
  assert.equal(
    controller.state.workspace.pending_approvals[0].approval_id,
    "appr_new_session",
  );

  const oldWorkspace = buildV3Workspace("sess_001", "First");
  releaseOldRead({ session: oldWorkspace.session, workspace: oldWorkspace });
  await pendingOldRefresh;
  assert.equal(controller.state.currentSessionId, "sess_002");
});

test("a stale periodic response cannot overwrite a newer SSE approval event", async () => {
  const timeouts = buildManualTimeouts();
  let releaseStaleRead;
  let markStaleReadStarted;
  let streamHandler = null;
  const staleReadStarted = new Promise((resolve) => {
    markStaleReadStarted = resolve;
  });
  const staleRead = new Promise((resolve) => {
    releaseStaleRead = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [];
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
      markStaleReadStarted();
      return staleRead;
    },
  };
  const controller = new WorkspaceController(fakeClient, () => {}, {
    workspaceReconcileIntervalMs: 5_000,
    setReconcileTimeout: timeouts.setTimeout,
    clearReconcileTimeout: timeouts.clearTimeout,
  });

  await controller.createSession({ project_id: "proj_001", objective: "Plan with V3" });
  const pendingStaleRefresh = timeouts.runNext();
  await staleReadStarted;

  streamHandler?.({
    event_id: "evt_approval_requested",
    event_type: "approval.requested",
    created_at: "2026-04-21T00:00:01+00:00",
    payload: { approval_id: "appr_from_sse", status: "pending" },
  });
  assert.equal(
    controller.state.workspace.pending_approvals[0].approval_id,
    "appr_from_sse",
  );

  const staleWorkspace = buildV3Workspace();
  releaseStaleRead({ session: staleWorkspace.session, workspace: staleWorkspace });
  await pendingStaleRefresh;

  assert.equal(
    controller.state.workspace.pending_approvals[0].approval_id,
    "appr_from_sse",
  );
});

test("workspace controller selects artifact details in outputs", async () => {
  const controller = new WorkspaceController({});
  controller.state.workspace = {
    ...buildV3Workspace(),
    artifacts: [{ artifact_id: "art_001", relative_path: "runs/result.pdbqt", kind: "result" }],
  };
  controller.state.currentSessionId = "sess_001";

  controller.selectArtifact("art_001");

  assert.equal(controller.state.currentSection, "outputs");
  assert.equal(controller.state.selectedTeammateAgentId, "");
  assert.equal(controller.state.selectedArtifactId, "art_001");
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
    payload: { decision: "approved" },
  });
  assert.equal(controller.state.workspace.pending_approvals.length, 0);
});

test("sendMessage is ignored while another request is already in flight", async () => {
  let postCalls = 0;
  let postPayload = null;
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
    async postV3Message(_sessionId, payload) {
      postCalls += 1;
      postPayload = payload;
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
  assert.equal(controller.state.messageBusy, true);
  assert.equal(controller.state.workspace.conversation.at(-1).content, "hello");
  assert.equal(controller.state.workspace.conversation.at(-1).pending, true);
  await controller.sendMessage("hello again");
  releasePost();
  await pending;

  assert.equal(postCalls, 1);
  assert.deepEqual(postPayload, { message: "hello" });
});

test("llm response stream events update traces while sendMessage is in flight", async () => {
  let streamHandler = null;
  let releasePost;
  const postPromise = new Promise((resolve) => {
    releasePost = resolve;
  });
  const fakeClient = {
    async listV3Sessions() {
      return [];
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
    async postV3Message() {
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
  assert.equal(controller.state.messageBusy, true);

  streamHandler?.({
    event_id: "evt_trace_001",
    event_type: "llm.response.created",
    created_at: "2026-04-21T00:00:01+00:00",
    payload: {
      trace_id: "trace_001",
      actor_ref: "harness",
      actor_kind: "master",
      display_name: "OpenZyme",
      role: "master",
      call_index: 1,
      created_at: "2026-04-21T00:00:01+00:00",
      response_text: "I will create a task before answering.",
      tool_calls: [
        {
          call_id: "call_task_create",
          tool_name: "task.create",
          task_id: "task_001",
          lane_id: null,
          args_public: { subject: "Realtime trace task" },
        },
      ],
    },
  });

  assert.equal(controller.state.messageBusy, true);
  assert.equal(
    controller.state.workspace.agent_traces.harness[0].response_text,
    "I will create a task before answering.",
  );
  assert.equal(
    controller.state.workspace.agent_traces.harness[0].tool_calls[0].tool_name,
    "task.create",
  );

  releasePost();
  await pending;
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

test("failed sendMessage keeps the user message and appends chat error", async () => {
  const fakeClient = {
    async postV3Message() {
      throw new Error("LLM provider unavailable");
    },
  };
  const controller = new WorkspaceController(fakeClient);
  controller.state.currentProjectId = "proj_001";
  controller.state.currentSessionId = "sess_001";
  controller.state.workspace = buildV3Workspace("sess_001", "First");

  const success = await controller.sendMessage("hello");

  assert.equal(success, false);
  assert.equal(controller.state.workspace.conversation.length, 2);
  assert.equal(controller.state.workspace.conversation[0].role, "user");
  assert.equal(controller.state.workspace.conversation[0].content, "hello");
  assert.equal(controller.state.workspace.conversation[1].role, "assistant");
  assert.equal(controller.state.workspace.conversation[1].error, true);
  assert.match(controller.state.workspace.conversation[1].content, /LLM provider unavailable/);
});
