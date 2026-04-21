function ensureWorkspace(workspace) {
  if (!workspace?.session) {
    throw new Error("v3 workspace projection is required");
  }
  workspace.conversation ??= [];
  workspace.task_board ??= { items: [] };
  workspace.lane_board ??= { lanes: [] };
  workspace.pending_approvals ??= [];
  workspace.activity_feed ??= [];
  workspace.artifacts ??= [];
  workspace.reports ??= [];
  workspace.capabilities ??= {};
}

export function reduceWorkspaceWithEvent(workspace, event) {
  ensureWorkspace(workspace);
  const next = structuredClone(workspace);
  const payload = event.payload ?? event;
  const alreadySeen = [
    ...(next.conversation ?? []),
    ...(next.activity_feed ?? []),
  ].some((item) => item.event_id && item.event_id === event.event_id);
  if (alreadySeen) {
    return next;
  }
  switch (event.event_type) {
    case "conversation.user_message":
      next.conversation = [
        ...(next.conversation ?? []),
        { role: "user", content: payload.content ?? "", event_id: event.event_id },
      ];
      return next;
    case "conversation.assistant_message":
      next.conversation = [
        ...(next.conversation ?? []),
        { role: "assistant", content: payload.content ?? "", event_id: event.event_id },
      ];
      return next;
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
    case "approval.requested":
    case "approval.resolved":
    case "engine.invocation.started":
    case "engine.invocation.updated":
    case "engine.invocation.completed":
    case "artifact.recorded":
    case "report.generated":
    case "session.created":
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
    default:
      return next;
  }
}

export function buildInitialViewState() {
  return {
    currentProjectId: "proj_001",
    currentSessionId: "",
    workspace: null,
    errorMessage: "",
    busy: false,
  };
}
