import {
  FILE_WORKSPACE_PUBLIC_SCHEMA,
  reduceFileWorkspaceEvent,
  requireWorkspaceChangedPathsPage,
} from "./file_workspace_state.js";

function ensureWorkspace(workspace) {
  if (!workspace?.session || workspace.schema_version !== FILE_WORKSPACE_PUBLIC_SCHEMA) {
    throw new Error("current file-workspace projection is required");
  }
}

export function eventRequiresWorkspaceRefresh(event) {
  return event?.schema_version === FILE_WORKSPACE_PUBLIC_SCHEMA;
}

export function reduceWorkspaceWithEvent(workspace, event) {
  ensureWorkspace(workspace);
  const reduced = reduceFileWorkspaceEvent(
    {
      blocked: false,
      refresh_required: false,
      last_event_id: workspace.last_event_id ?? null,
    },
    event,
  );
  if (reduced.blocked) {
    return {
      ...structuredClone(workspace),
      contract_blocked: true,
      contract_error: reduced.blocking_error,
    };
  }
  if (reduced.last_event_id === workspace.last_event_id) {
    return workspace;
  }
  return {
    ...structuredClone(workspace),
    refresh_required: true,
    last_event_id: reduced.last_event_id,
  };
}

export function mergeWorkspaceChangedPathsPage(workspace, workspaceId, payload) {
  ensureWorkspace(workspace);
  const status = (workspace.workspace_status ?? []).find(
    (item) => item.workspace_id === workspaceId,
  );
  if (!status) {
    throw new Error("changed-paths page workspace is not present in current projection");
  }
  const page = requireWorkspaceChangedPathsPage(payload, {
    workspaceId,
    workspaceGeneration: status.workspace_generation,
  });
  const next = structuredClone(workspace);
  const nextStatus = next.workspace_status.find((item) => item.workspace_id === workspaceId);
  nextStatus.changed_paths = [...(nextStatus.changed_paths ?? []), ...page.paths];
  nextStatus.changed_paths_continuation = page.continuation;
  nextStatus.changed_paths_truncated = page.continuation !== null || page.source_truncated;
  return next;
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
  const next = [
    ...sessionSummaries.filter((item) => item.session_id !== summary.session_id),
    summary,
  ];
  next.sort((left, right) => {
    const updated = String(right.updated_at ?? "").localeCompare(
      String(left.updated_at ?? ""),
    );
    return updated || String(right.session_id).localeCompare(String(left.session_id));
  });
  return next;
}

function initialProjectId() {
  if (typeof window === "undefined") {
    return "proj_001";
  }
  const params = new URLSearchParams(window.location.search);
  return params.get("project_id") || params.get("project") || "proj_001";
}

export function buildInitialViewState() {
  return {
    currentProjectId: initialProjectId(),
    currentSessionId: "",
    currentSection: "conversation",
    mobilePane: "conversation",
    selectedTeammateAgentId: "",
    sidebarExpandedSessionIds: [],
    sessionSummaries: [],
    runtimeHealth: null,
    workspace: null,
    sidebarBusy: false,
    messageBusy: false,
    refreshingWorkspace: false,
    createSessionBusy: false,
    pendingApprovalId: "",
    pendingWorkspacePathId: "",
    errors: {
      sidebar: "",
      createSession: "",
      session: "",
      message: "",
      runtimeHealth: "",
      approvals: {},
      changedPaths: {},
    },
  };
}
