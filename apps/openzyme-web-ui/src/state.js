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
  workspace.scientific_evidence ??= {
    schema_version: "v3.scientific_evidence.v1",
    active: false,
    providers: [],
    quorum: { status: "not_evaluated", cutover_eligible: false, members: [] },
    citations: [],
    operations: [],
    artifacts: [],
    reports: [],
    cutover: { status: "not_evaluated", eligible: false, blocker_codes: [], warning_codes: [] },
  };
  workspace.capabilities ??= {};
  workspace.scientific_attempts ??= {
    schema_id: "scientific_attempt_workspace@1",
    authorizations: [],
    attempts: [],
  };
  workspace.failure_observations ??= [];
  workspace.runtime_state ??= {
    warnings: [],
    task_attention: [],
    warning_count: 0,
    needs_attention_count: 0,
  };
}

function fingerprint(value) {
  return JSON.stringify(value ?? null);
}

const AGENT_TRACE_PROJECTION_SCHEMA_VERSION = "v1";
const AGENT_STEP_PUBLIC_KEYS = [
  "step_id",
  "session_id",
  "agent_id",
  "actor_kind",
  "role",
  "call_index",
  "task_id",
  "lane_id",
  "correlation_id",
  "signal_id",
  "wakeup_reason",
  "restore_context_digest",
  "tool_catalog_digest",
  "created_at",
];
const REDACTED = "[redacted]";
const SENSITIVE_KEY_FRAGMENTS = [
  "secret",
  "token",
  "password",
  "credential",
  "private_key",
  "api_key",
];
const PRIVATE_KEY_FRAGMENTS = [
  "storage_uri",
  "source_storage_uri",
  "intermediate_storage_uri",
  "local_path",
  "remote_path",
  "host_path",
  "runner_config",
  "runner_path",
  "ssh",
  "config",
];
const PRIVATE_EXACT_KEYS = new Set(["code", "content", "pipeline_code", "source_code"]);
const PRIVATE_STRING_PREFIXES = ["artifact://", "storage://", "s3://", "file://"];
const PRIVATE_PATH_PREFIXES = ["/home/", "/tmp/", "/var/", "/mnt/", "/data/", "~"];

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function sanitizePublicToolArgs(value, key = "") {
  const keyLower = key.toLowerCase();
  if (PRIVATE_EXACT_KEYS.has(keyLower)) {
    return REDACTED;
  }
  if (SENSITIVE_KEY_FRAGMENTS.some((fragment) => keyLower.includes(fragment))) {
    return REDACTED;
  }
  if (PRIVATE_KEY_FRAGMENTS.some((fragment) => keyLower.includes(fragment))) {
    return REDACTED;
  }
  if (Array.isArray(value)) {
    return value.slice(0, 20).map((item) => sanitizePublicToolArgs(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([itemKey, item]) => [
        String(itemKey),
        sanitizePublicToolArgs(item, String(itemKey)),
      ]),
    );
  }
  if (typeof value === "string") {
    if (PRIVATE_STRING_PREFIXES.some((prefix) => value.startsWith(prefix))) {
      return REDACTED;
    }
    if (PRIVATE_PATH_PREFIXES.some((prefix) => value.startsWith(prefix))) {
      return REDACTED;
    }
    if (value.length > 1200) {
      return `${value.slice(0, 1200)}... [truncated]`;
    }
  }
  return value;
}

function publicAgentStep(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const projected = {};
  for (const key of AGENT_STEP_PUBLIC_KEYS) {
    if (hasOwn(value, key)) {
      projected[key] = value[key];
    }
  }
  return Object.keys(projected).length ? projected : null;
}

function publicToolCall(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return {
    call_id: value.call_id,
    tool_name: value.tool_name,
    task_id: value.task_id,
    lane_id: value.lane_id,
    args_public: sanitizePublicToolArgs(value.args_public ?? {}),
  };
}

function publicTracePayload(event) {
  const payload = event.payload ?? event;
  const agentStep = publicAgentStep(payload.agent_step) ?? publicAgentStep(payload);
  const trace = {
    trace_id: payload.trace_id ?? event.event_id,
    actor_ref: payload.actor_ref ?? "harness",
    actor_kind: payload.actor_kind ?? agentStep?.actor_kind ?? "master",
    display_name: payload.display_name ?? "OpenZyme",
    role: payload.role ?? agentStep?.role ?? "master",
    call_index: payload.call_index ?? agentStep?.call_index,
    created_at: payload.created_at ?? event.created_at,
    response_text: payload.response_text ?? "",
    tool_calls: (Array.isArray(payload.tool_calls) ? payload.tool_calls : [])
      .map((toolCall) => publicToolCall(toolCall))
      .filter((toolCall) => toolCall !== null),
    projection_schema_version: AGENT_TRACE_PROJECTION_SCHEMA_VERSION,
  };
  const stepId = payload.step_id ?? agentStep?.step_id;
  if (stepId !== undefined && stepId !== null) {
    trace.step_id = stepId;
  }
  const toolCatalogDigest = payload.tool_catalog_digest ?? agentStep?.tool_catalog_digest;
  if (toolCatalogDigest !== undefined && toolCatalogDigest !== null) {
    trace.tool_catalog_digest = toolCatalogDigest;
  }
  const restoreContextDigest = payload.restore_context_digest ?? agentStep?.restore_context_digest;
  if (restoreContextDigest !== undefined && restoreContextDigest !== null) {
    trace.restore_context_digest = restoreContextDigest;
  }
  if (agentStep !== null) {
    trace.agent_step = agentStep;
  }
  return trace;
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
    "research.summary.updated",
    "research.evidence.recorded",
    "artifact.recorded",
    "sdk_controlled_operation.updated",
    "sdk_controlled_operation.approval_resolved",
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
      const trace = publicTracePayload(event);
      if (hasTraceEntry(workspace, trace)) {
        return workspace;
      }
      const next = structuredClone(workspace);
      const actorRef = trace.actor_ref ?? "harness";
      next.agent_traces ??= {};
      next.agent_traces[actorRef] = [
        ...(next.agent_traces[actorRef] ?? []),
        trace,
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
    case "research.evidence.recorded":
    case "sdk_controlled_operation.updated":
    case "sdk_controlled_operation.approval_resolved": {
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
    selectedArtifactId: "",
    sidebarExpandedSessionIds: [],
    sessionSummaries: [],
    runtimeHealth: null,
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
      runtimeHealth: "",
      approvals: {},
    },
  };
}
