function ensureWorkspace(workspace) {
  if (!workspace?.session) {
    throw new Error("v3 workspace projection is required");
  }
  workspace.conversation ??= [];
  workspace.task_board ??= { items: [] };
  workspace.lane_board ??= { lanes: [] };
  workspace.delegation ??= { agents: [] };
  workspace.agent_traces ??= {};
  workspace.pending_approvals ??= [];
  workspace.activity_feed ??= [];
  workspace.artifacts ??= [];
  workspace.artifact_index ??= [];
  workspace.sandbox_runs ??= [];
  workspace.report_drafts ??= [];
  workspace.reports ??= [];
  workspace.capabilities ??= {};
}

function fingerprint(value) {
  return JSON.stringify(value ?? null);
}

function hasConversationEntry(workspace, role, content, messageId) {
  return (workspace.conversation ?? []).some((item) => {
    if (messageId && item.message_id) {
      return item.message_id === messageId;
    }
    return item.role === role && item.content === content;
  });
}

function hasActivityEntry(workspace, event) {
  const payload = event.payload ?? event;
  const candidate = `${event.event_type}|${event.created_at ?? ""}|${fingerprint(payload)}`;
  return (workspace.activity_feed ?? []).some((item) => {
    if (item.event_id && event.event_id && item.event_id === event.event_id) {
      return true;
    }
    const existing = `${item.event_type}|${item.created_at ?? ""}|${fingerprint(item.payload)}`;
    return existing === candidate;
  });
}

function hasTraceEntry(workspace, trace) {
  const actorRef = trace.actor_ref ?? "harness";
  return (workspace.agent_traces?.[actorRef] ?? []).some((item) => {
    if (item.trace_id && trace.trace_id) {
      return item.trace_id === trace.trace_id;
    }
    return item.call_index === trace.call_index && item.created_at === trace.created_at;
  });
}

export function eventRequiresWorkspaceRefresh(event) {
  return new Set([
    "task.created",
    "task.updated",
    "lane.created",
    "lane.claimed",
    "lane.released",
    "lane.removed",
    "engine.invocation.started",
    "engine.invocation.updated",
    "engine.invocation.completed",
    "artifact.recorded",
    "sandbox.run.updated",
    "report_draft.updated",
    "report.generated",
    "report.updated",
    "agent.spawned",
    "agent.delegated",
    "agent.woken",
    "agent.idle",
    "agent.inbox_unread",
    "agent.task_claimed",
    "agent.shutdown_requested",
    "agent.shutdown_completed",
    "agent.wakeup_pending",
    "agent.runtime_signal.updated",
    "agent.status_updated",
    "agent.message.delivered",
    "background.completed",
  ]).has(event.event_type);
}

export function reduceWorkspaceWithEvent(workspace, event) {
  ensureWorkspace(workspace);
  switch (event.event_type) {
    case "conversation.user_message": {
      const payload = event.payload ?? event;
      if (hasConversationEntry(workspace, "user", payload.content ?? "", payload.message_id ?? null)) {
        return workspace;
      }
      const next = structuredClone(workspace);
      next.conversation = [
        ...(next.conversation ?? []),
        {
          role: "user",
          content: payload.content ?? "",
          message_id: payload.message_id,
          created_at: event.created_at,
          event_id: event.event_id,
        },
      ];
      return next;
    }
    case "conversation.assistant_message": {
      const payload = event.payload ?? event;
      if (hasConversationEntry(workspace, "assistant", payload.content ?? "", payload.message_id ?? null)) {
        return workspace;
      }
      const next = structuredClone(workspace);
      next.conversation = [
        ...(next.conversation ?? []),
        {
          role: "assistant",
          content: payload.content ?? "",
          message_id: payload.message_id,
          created_at: event.created_at,
          event_id: event.event_id,
        },
      ];
      return next;
    }
    case "llm.response.created": {
      const payload = event.payload ?? event;
      if (hasTraceEntry(workspace, payload)) {
        return workspace;
      }
      const next = structuredClone(workspace);
      const actorRef = payload.actor_ref ?? "harness";
      next.agent_traces ??= {};
      next.agent_traces[actorRef] = [
        ...(next.agent_traces[actorRef] ?? []),
        {
          ...payload,
          trace_id: payload.trace_id ?? event.event_id,
          created_at: payload.created_at ?? event.created_at,
        },
      ].sort((left, right) => {
        const byTime = String(left.created_at ?? "").localeCompare(String(right.created_at ?? ""));
        return byTime || Number(left.call_index ?? 0) - Number(right.call_index ?? 0);
      });
      return next;
    }
    case "approval.requested": {
      const payload = event.payload ?? event;
      const next = structuredClone(workspace);
      if (!(workspace.pending_approvals ?? []).some((approval) => approval.approval_id === payload.approval_id)) {
        next.pending_approvals = [
          ...(next.pending_approvals ?? []),
          { ...payload, event_id: event.event_id },
        ];
      }
      if (!hasActivityEntry(next, event)) {
        next.activity_feed = [
          {
            event_id: event.event_id,
            event_type: event.event_type,
            created_at: event.created_at,
            payload,
          },
          ...(next.activity_feed ?? []),
        ];
      }
      return next;
    }
    case "approval.resolved": {
      const payload = event.payload ?? event;
      const next = structuredClone(workspace);
      next.pending_approvals = (next.pending_approvals ?? []).filter(
        (approval) => approval.approval_id !== payload.approval_id,
      );
      if (!hasActivityEntry(next, event)) {
        next.activity_feed = [
          {
            event_id: event.event_id,
            event_type: event.event_type,
            created_at: event.created_at,
            payload,
          },
          ...(next.activity_feed ?? []),
        ];
      }
      return next;
    }
    case "inbox.delivered":
    case "agent.message.delivered":
    case "background.completed":
    case "message.received":
    case "message.sent":
    case "tool.invoked":
    case "tool.completed":
    case "task.created":
    case "task.updated":
    case "lane.created":
    case "lane.claimed":
    case "lane.released":
    case "lane.removed":
    case "engine.invocation.started":
    case "engine.invocation.updated":
    case "engine.invocation.completed":
    case "artifact.recorded":
    case "sandbox.run.updated":
    case "report_draft.updated":
    case "report.generated":
    case "report.updated":
    case "session.created":
    case "agent.spawned":
    case "agent.delegated":
    case "agent.woken":
    case "agent.idle":
    case "agent.inbox_unread":
    case "agent.task_claimed":
    case "agent.shutdown_requested":
    case "agent.shutdown_completed":
    case "agent.wakeup_pending":
    case "agent.runtime_signal.updated":
    case "agent.status_updated":
    case "memory.compacted":
    case "research.summary.updated":
    case "research.evidence.recorded": {
      if (hasActivityEntry(workspace, event)) {
        return workspace;
      }
      const payload = event.payload ?? event;
      const next = structuredClone(workspace);
      next.activity_feed = [
        {
          event_id: event.event_id,
          event_type: event.event_type,
          created_at: event.created_at,
          payload,
        },
        ...(next.activity_feed ?? []),
      ];
      return next;
    }
    default:
      return workspace;
  }
}

export function buildSessionSummaryFromWorkspace(workspace) {
  ensureWorkspace(workspace);
  const session = workspace.session;
  const conversation = workspace.conversation ?? [];
  const latestMessage = conversation.length ? conversation.at(-1)?.content ?? "" : "";
  return {
    session_id: session.session_id,
    project_id: session.project_id,
    title: session.title ?? session.objective,
    objective: session.objective,
    status: session.status,
    created_at: session.created_at ?? "",
    updated_at: session.updated_at ?? "",
    latest_message_preview: latestMessage,
    pending_approval_count: (workspace.pending_approvals ?? []).length,
  };
}

export function upsertSessionSummary(sessionSummaries, summary) {
  const next = [...sessionSummaries.filter((item) => item.session_id !== summary.session_id), summary];
  next.sort((left, right) => {
    const updated = String(right.updated_at ?? "").localeCompare(String(left.updated_at ?? ""));
    return updated || String(right.session_id).localeCompare(String(left.session_id));
  });
  return next;
}

export function buildInitialViewState() {
  return {
    currentProjectId: "proj_001",
    currentSessionId: "",
    currentSection: "conversation",
    selectedTeammateAgentId: "",
    selectedArtifactId: "",
    sidebarExpandedSessionIds: [],
    sessionSummaries: [],
      workspace: null,
    sidebarBusy: false,
    messageBusy: false,
    refreshingWorkspace: false,
    createSessionBusy: false,
    pendingApprovalId: "",
    errors: {
      sidebar: "",
      createSession: "",
      session: "",
      message: "",
      approvals: {},
    },
  };
}
