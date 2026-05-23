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
    agent_traces: {},
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

test("session tree shows title and objective instead of conversation preview", () => {
  const html = renderApp({
    ...buildInitialViewState(),
    sessionSummaries: [
      {
        session_id: "sess_001",
        project_id: "proj_001",
        title: "Thermostability run",
        objective: "Design a thermostable enzyme candidate",
        status: "active",
        updated_at: "2026-04-21T00:00:00+00:00",
        latest_message_preview: "This is a full assistant response that belongs in the chat transcript, not the session sidebar.",
        pending_approval_count: 0,
      },
    ],
  });

  assert.match(html, /Thermostability run/);
  assert.match(html, /Design a thermostable enzyme candidate/);
  assert.doesNotMatch(html, /full assistant response/);
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

test("llm response events update agent traces without duplicates", () => {
  let workspace = buildV3Workspace();
  const event = {
    event_id: "evt_trace",
    event_type: "llm.response.created",
    created_at: "2026-04-21T00:00:02+00:00",
    payload: {
      trace_id: "trace_001",
      actor_ref: "harness",
      actor_kind: "master",
      display_name: "OpenZyme",
      role: "master",
      call_index: 1,
      created_at: "2026-04-21T00:00:02+00:00",
      response_text: "I will create a task.",
      tool_calls: [{ call_id: "call_001", tool_name: "task.create", args_public: { subject: "Plan" } }],
    },
  };

  workspace = reduceWorkspaceWithEvent(workspace, event);
  const second = reduceWorkspaceWithEvent(workspace, event);

  assert.equal(workspace.agent_traces.harness.length, 1);
  assert.equal(workspace.agent_traces.harness[0].tool_calls[0].tool_name, "task.create");
  assert.equal(second, workspace);
});

test("master conversation renders trace text and tool-call request cards", () => {
  const workspace = {
    ...buildV3Workspace(),
    conversation: [{ role: "user", content: "Start planning", created_at: "2026-04-21T00:00:01+00:00" }],
    agent_traces: {
      harness: [
        {
          trace_id: "trace_001",
          actor_ref: "harness",
          actor_kind: "master",
          display_name: "OpenZyme",
          role: "master",
          call_index: 1,
          created_at: "2026-04-21T00:00:02+00:00",
          response_text: "I will create a task.",
          tool_calls: [{ call_id: "call_001", tool_name: "task.create", args_public: { subject: "Plan" } }],
        },
      ],
    },
  };

  const html = renderApp({
    ...buildInitialViewState(),
    currentSessionId: "sess_001",
    sidebarExpandedSessionIds: ["sess_001"],
    sessionSummaries: [buildSessionSummaryFromWorkspace(workspace)],
    workspace,
  });

  assert.match(html, /Start planning/);
  assert.match(html, /I will create a task/);
  assert.match(html, /task\.create/);
  assert.doesNotMatch(html, /Received: Start planning/);
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

test("outputs render artifacts as a relative path tree with duplicate leaves", () => {
  const workspace = {
    ...buildV3Workspace(),
    artifacts: [
      {
        artifact_id: "art_alpha",
        title: "result.pdbqt",
        kind: "result",
        relative_path: "runs/run_001/results/result.pdbqt",
        provenance: {
          task_id: "task_001",
          lane_id: "lane_001",
          invocation_id: "inv_exec_001",
          run_id: "run_exec_001",
          format: "pdbqt",
          code_digest: "sha256:alpha",
        },
      },
      {
        artifact_id: "art_beta",
        title: "duplicate result",
        kind: "result",
        relative_path: "runs/run_001/results/result.pdbqt",
        provenance: { format: "pdbqt", code_digest: "sha256:beta" },
      },
    ],
  };

  const html = renderApp({
    ...buildInitialViewState(),
    currentSessionId: "sess_001",
    currentSection: "outputs",
    selectedArtifactId: "art_alpha",
    sessionSummaries: [buildSessionSummaryFromWorkspace(workspace)],
    workspace,
  });

  assert.match(html, /<summary>runs<\/summary>/);
  assert.match(html, /<summary>run_001<\/summary>/);
  assert.match(html, /<summary>results<\/summary>/);
  assert.equal(html.match(/data-action="select-artifact"/g)?.length, 2);
  assert.match(html, /art_alpha/);
  assert.match(html, /art_beta/);
  assert.match(html, /sha256:alpha/);
});

test("outputs fall back to the first artifact detail and sanitize storage paths", () => {
  const workspace = {
    ...buildV3Workspace(),
    artifacts: [
      {
        artifact_id: "art_first",
        title: "summary.json",
        kind: "report",
        relative_path: "reports/summary.json",
        storage_uri: "/tmp/host/summary.json",
        metadata: {
          storage_uri: "/tmp/host/metadata.json",
          nested: { local_path: "/tmp/host/local.json", visible: "kept" },
        },
        provenance: {
          task_id: "task_001",
          invocation_id: "inv_report_001",
          format: "json",
          produced_by: "reporter",
          input_artifact_ids: ["art_input"],
          preprocess_artifact_ids: [],
          tool_contract: { adapter_id: "report" },
        },
      },
      {
        artifact_id: "art_second",
        title: "table.csv",
        kind: "result",
        relative_path: "reports/table.csv",
        provenance: { code_digest: "sha256:second" },
      },
    ],
  };

  const html = renderApp({
    ...buildInitialViewState(),
    currentSessionId: "sess_001",
    currentSection: "outputs",
    selectedArtifactId: "missing_artifact",
    sessionSummaries: [buildSessionSummaryFromWorkspace(workspace)],
    workspace,
  });

  assert.match(html, /summary\.json/);
  assert.match(html, /task_001/);
  assert.match(html, /inv_report_001/);
  assert.match(html, /json/);
  assert.match(html, /reporter/);
  assert.match(html, /art_input/);
  assert.match(html, /adapter_id/);
  assert.match(html, /kept/);
  assert.doesNotMatch(html, /storage_uri/);
  assert.doesNotMatch(html, /local_path/);
  assert.doesNotMatch(html, /\/tmp\/host/);
  assert.doesNotMatch(html, /sha256:second/);
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

test("session tree nests teammate names and teammate trace is read-only", () => {
  const workspace = {
    ...buildV3Workspace(),
    agent_traces: {
      "agent:researcher": [
        {
          trace_id: "trace_agent_001",
          actor_ref: "agent:researcher",
          actor_kind: "teammate",
          display_name: "researcher",
          role: "researcher",
          call_index: 1,
          created_at: "2026-04-21T00:00:03+00:00",
          response_text: "I found two papers.",
          tool_calls: [{ call_id: "call_search", tool_name: "deep_research.start", args_public: { task_id: "task_001" } }],
          initial_prompt: {
            identity: "agent:researcher",
            role: "researcher",
            task_id: "task_001",
            lane_id: "lane_001",
            correlation_id: "corr_001",
            instructions: "Find papers.",
            seed_message: "Task task_001: Find papers.",
          },
        },
      ],
    },
  };

  const html = renderApp({
    ...buildInitialViewState(),
    currentSessionId: "sess_001",
    currentSection: "team",
    selectedTeammateAgentId: "agent:researcher",
    sidebarExpandedSessionIds: ["sess_001"],
    sessionSummaries: [buildSessionSummaryFromWorkspace(workspace)],
    workspace,
  });

  assert.match(html, /data-action="select-teammate"/);
  assert.match(html, /I found two papers/);
  assert.match(html, /Role seed/);
  assert.match(html, /trace is read-only/);
  assert.doesNotMatch(html, /id="message-form"/);
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
