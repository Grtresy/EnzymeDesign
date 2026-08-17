function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

const sectionLabels = {
  conversation: "Conversation",
  team: "Team",
  tasks: "Tasks",
  lanes: "Lanes",
  outputs: "Files & Revisions",
  evidence: "Scientific Deliverables",
  attempts: "External Jobs",
  capabilities: "Capability Leases",
  failures: "Failures & Recovery",
  activity: "Activity",
};

function renderPanelError(message) {
  return message ? `<p class="error-banner" role="alert">${escapeHtml(message)}</p>` : "";
}

function renderStatusChip(status, label = status) {
  const normalized = String(status ?? "unknown").replaceAll("_", "-");
  return `<span class="evidence-status" data-evidence-status="${escapeHtml(normalized)}">${escapeHtml(label ?? "unknown")}</span>`;
}

function digestPrefix(value) {
  const text = String(value ?? "");
  return text.length > 22 ? `${text.slice(0, 22)}…` : text || "none";
}

function renderEmptyConversation(viewState) {
  return `
    <div class="empty-chat" id="conversation-workspace">
      <p class="eyebrow">OpenZyme V3</p>
      <h2>Select a session or create a new one</h2>
      <p class="status-line">Conversation stays here; typed workspace state is in the inspector.</p>
      ${renderPanelError(viewState?.errors?.session ?? "")}
    </div>
  `;
}

function renderRecordList(items, renderItem, emptyCopy) {
  if (!items.length) {
    return `<p class="empty-copy">${escapeHtml(emptyCopy)}</p>`;
  }
  return `<ul class="record-list">${items.map(renderItem).join("")}</ul>`;
}

export function renderV3TaskBoard(workspace) {
  return renderRecordList(
    workspace.task_board?.items ?? [],
    (item) => {
      const task = item.task ?? item;
      return `<li><strong>${escapeHtml(task.subject ?? task.task_id)}</strong><span>${escapeHtml(task.task_id)} · ${escapeHtml(task.status)} · ${escapeHtml(item.bucket ?? "unbucketed")}</span></li>`;
    },
    "No tasks yet.",
  );
}

export function renderV3Delegation(workspace) {
  return renderRecordList(
    workspace.agents ?? [],
    (agent) => `<li><strong>${escapeHtml(agent.name ?? agent.agent_id)}</strong><span>${escapeHtml(agent.role)} · ${escapeHtml(agent.status)} · ${escapeHtml(agent.task_id ?? "no task")}</span><small>${escapeHtml(agent.member_id)} · ${escapeHtml(agent.lane_id ?? "no lane")}</small></li>`,
    "No delegated teammates yet.",
  );
}

export function renderV3Lanes(workspace) {
  return renderRecordList(
    workspace.lane_board?.lanes ?? [],
    (item) => {
      const lane = item.lane ?? item;
      return `<li><strong>${escapeHtml(lane.name ?? lane.lane_id)}</strong><span>${escapeHtml(lane.lane_id)} · ${escapeHtml(lane.status)}</span></li>`;
    },
    "No lanes yet.",
  );
}

export function renderV3Approvals(workspace, viewState) {
  const approvals = workspace.pending_approvals ?? [];
  if (!approvals.length) {
    return "";
  }
  return `<div class="approval-stack" aria-label="Pending approvals" aria-live="polite">${approvals.map((approval) => `
    <article class="approval-card" role="region" aria-label="Approval required">
      <div class="approval-heading"><span class="approval-mark" aria-hidden="true">!</span><div><p class="eyebrow">Approval required</p><h3>${escapeHtml(approval.requested_action)}</h3></div></div>
      <dl class="facts compact-facts">
        <div><dt>Approval</dt><dd>${escapeHtml(approval.approval_id)}</dd></div>
        <div><dt>Kind</dt><dd>${escapeHtml(approval.kind)}</dd></div>
        <div><dt>Task</dt><dd>${escapeHtml(approval.task_id ?? "none")}</dd></div>
        <div><dt>Lane</dt><dd>${escapeHtml(approval.lane_id ?? "none")}</dd></div>
      </dl>
      ${renderPanelError(viewState.errors.approvals?.[approval.approval_id] ?? "")}
      <div class="action-row approval-actions">
        <button type="button" data-v3-approval-decision="approved" data-approval-id="${escapeHtml(approval.approval_id)}" ${viewState.pendingApprovalId === approval.approval_id ? "disabled" : ""}>Approve</button>
        <button type="button" class="button-secondary button-warning" data-v3-approval-decision="rejected" data-approval-id="${escapeHtml(approval.approval_id)}" ${viewState.pendingApprovalId === approval.approval_id ? "disabled" : ""}>Reject</button>
      </div>
    </article>`).join("")}</div>`;
}

export function renderV3Conversation(workspace) {
  const conversation = workspace.conversation ?? [];
  if (!conversation.length) {
    return `<p class="empty-copy">Send a message to start the session.</p>`;
  }
  return `<ol class="chat-list">${conversation.map((item) => `
    <li class="chat-message ${item.role === "user" ? "from-user" : "from-agent"}${item.error ? " is-error" : ""}" data-message-id="${escapeHtml(item.message_id ?? item.event_id ?? "")}">
      <span>${escapeHtml(item.role === "user" ? "You" : "OpenZyme")}${item.created_at ? ` · ${escapeHtml(item.created_at)}` : ""}</span>
      <p>${escapeHtml(item.content)}</p>
    </li>`).join("")}</ol>`;
}

export function renderTeammateTrace(workspace, agentId) {
  const agent = (workspace.agents ?? []).find((item) => item.agent_id === agentId);
  if (!agent) {
    return `<p class="empty-copy">The selected teammate is unavailable.</p>`;
  }
  return `<div class="readonly-banner"><strong>${escapeHtml(agent.name ?? agent.agent_id)}</strong><span>${escapeHtml(agent.role)} · ${escapeHtml(agent.status)} · read-only member state</span></div>`;
}

function renderChangedPaths(workspace) {
  const statuses = workspace.workspace_status ?? [];
  return statuses.map((status) => `
    <section>
      <h3>Workspace ${escapeHtml(status.workspace_id)}</h3>
      <dl class="facts compact-facts">
        <div><dt>Generation</dt><dd>${escapeHtml(status.workspace_generation)}</dd></div>
        <div><dt>State</dt><dd>${escapeHtml(status.status)}</dd></div>
        <div><dt>Dirty state</dt><dd>${escapeHtml(status.dirty_state)}</dd></div>
        <div><dt>HEAD</dt><dd>${escapeHtml(digestPrefix(status.head_commit))}</dd></div>
      </dl>
      ${renderRecordList(
        status.changed_paths ?? [],
        (path) => `<li><strong>${escapeHtml(path)}</strong><span>changed path</span></li>`,
        "No changed paths in the bounded status page.",
      )}
      ${status.changed_paths_truncated ? `<p class="status-line">More paths exist; request the next bounded page for this generation.</p>` : ""}
    </section>`).join("");
}

export function renderV3Outputs(workspace) {
  const privateRevisions = workspace.private_revisions ?? [];
  const publications = workspace.published_revisions ?? [];
  const reports = workspace.reports ?? [];
  const owner = workspace.executor_owner_workspace;
  return `<div class="stack">
    ${renderChangedPaths(workspace) || `<p class="empty-copy">No agent workspace status yet.</p>`}
    <section><h3>Private revisions</h3>${renderRecordList(privateRevisions, (revision) => `<li><strong>${escapeHtml(digestPrefix(revision.commit))}</strong><span>${escapeHtml(revision.workspace_id)} · generation ${escapeHtml(revision.workspace_generation)} · private</span><small>tree ${escapeHtml(digestPrefix(revision.tree))}</small></li>`, "No private committed revision yet.")}</section>
    <section><h3>Immutable publications</h3>${renderRecordList(publications, (publication) => `<li><strong>${escapeHtml(publication.publication_ref)}</strong><span>${escapeHtml(digestPrefix(publication.commit))} · ${escapeHtml(publication.publisher_agent_member_id)}</span><small>manifest ${escapeHtml(digestPrefix(publication.manifest_digest))}</small></li>`, "No immutable publication yet.")}</section>
    <section><h3>Reports</h3>${renderRecordList(reports, (report) => `<li><strong>${escapeHtml(report.title ?? report.report_id)}</strong><span>${escapeHtml(report.status)} · version ${escapeHtml(report.report_version)}</span><small>${escapeHtml(report.content_ref_id ?? "no source ref")}</small></li>`, "No report yet.")}</section>
    ${owner ? `<section aria-label="Owner executor workspace"><h3>Your executor workspace</h3><dl class="facts compact-facts"><div><dt>Workspace</dt><dd>${escapeHtml(owner.workspace_id)}</dd></div><div><dt>Generation</dt><dd>${escapeHtml(owner.workspace_generation)}</dd></div><div><dt>Login alias</dt><dd>${escapeHtml(owner.login_alias)}</dd></div><div><dt>Workspace path</dt><dd>${escapeHtml(owner.workspace_path)}</dd></div><div><dt>Lease</dt><dd>${escapeHtml(owner.capability_lease_id)}</dd></div></dl></section>` : ""}
  </div>`;
}

export function renderV3ScientificEvidence(workspace) {
  const deliverables = workspace.scientific_deliverables ?? [];
  return renderRecordList(
    deliverables,
    (item) => `<li><strong>${escapeHtml(item.path)}</strong><span>${escapeHtml(item.scientific_role)} · ${escapeHtml(item.publication_id)}</span><small>${escapeHtml(digestPrefix(item.content_digest))} · ${escapeHtml(item.commit)}</small></li>`,
    "No scientific deliverables have been finalized.",
  );
}

export function renderV3ScientificAttempts(workspace) {
  const jobs = workspace.external_jobs ?? [];
  const results = workspace.external_job_results ?? [];
  return `<div class="stack"><section><h3>External jobs</h3>${renderRecordList(jobs, (job) => `<li><strong>${escapeHtml(job.execution_id)}</strong><span>${escapeHtml(job.lifecycle_state)} · ${escapeHtml(job.effect_certainty)}</span><small>source ${escapeHtml(digestPrefix(job.source_commit))} · accepted ${escapeHtml(job.accepted_at)}</small></li>`, "No external job has been accepted.")}</section><section><h3>External job results</h3>${renderRecordList(results, (result) => `<li><strong>${escapeHtml(result.result_id)}</strong><span>${escapeHtml(result.terminal_state)} · exit ${escapeHtml(result.exit_code ?? "unknown")}</span><small>${escapeHtml(digestPrefix(result.result_digest))} · source ${escapeHtml(digestPrefix(result.source_commit))}</small></li>`, "No external job result yet.")}</section></div>`;
}

export function renderV3Capabilities(workspace) {
  return renderRecordList(
    workspace.capability_leases ?? [],
    (lease) => `<li><strong>${escapeHtml(lease.profile)} ${renderStatusChip(lease.status)}</strong><span>${escapeHtml(lease.agent_member_id)} · generation ${escapeHtml(lease.workspace_generation)}</span><small>${escapeHtml((lease.capabilities ?? []).join(", ") || "no capabilities")} · fence ${escapeHtml(lease.state_version)}</small></li>`,
    "No capability lease is visible.",
  );
}

export function renderV3Failures(workspace) {
  const failures = workspace.failure_observations ?? [];
  return renderRecordList(
    failures.slice().reverse(),
    (failure) => `<li><strong>${escapeHtml(failure.failure_class)} ${renderStatusChip(failure.recoverability)}</strong><span>${escapeHtml(failure.safe_summary)}</span><small>${escapeHtml(failure.failure_id)} · effect ${escapeHtml(failure.effect_certainty)}</small></li>`,
    "No structured failure or recovery attention is recorded.",
  );
}

export function renderV3Activity(workspace) {
  return renderRecordList(
    (workspace.activity_feed ?? []).slice(0, 200),
    (event) => `<li><strong>${escapeHtml(event.event_type)}</strong><span>${escapeHtml(event.created_at ?? "")}</span><small>${escapeHtml(event.event_id)}</small></li>`,
    "No activity yet.",
  );
}

function renderSessionFacts(workspace) {
  const session = workspace.session;
  return `<dl class="facts"><div><dt>Session</dt><dd>${escapeHtml(session.session_id)}</dd></div><div><dt>Status</dt><dd>${escapeHtml(session.status)}</dd></div><div><dt>Project</dt><dd>${escapeHtml(session.project_id)}</dd></div><div><dt>Repository binding</dt><dd>${escapeHtml(session.repository_binding_status)}</dd></div><div><dt>Schema</dt><dd>${escapeHtml(workspace.schema_version)}</dd></div><div><dt>Catalog</dt><dd>${escapeHtml(digestPrefix(workspace.tool_catalog_digest))}</dd></div></dl>`;
}

export function renderInspectorContent(viewState) {
  const workspace = viewState.workspace;
  if (!workspace?.session) {
    return `<p class="empty-copy">Select a session to inspect structured state.</p>`;
  }
  if (workspace.contract_blocked) {
    return `<div class="error-banner" role="alert"><strong>Workspace contract blocked.</strong><p>${escapeHtml(workspace.contract_error)}</p></div>`;
  }
  const renderers = {
    team: renderV3Delegation,
    tasks: renderV3TaskBoard,
    lanes: renderV3Lanes,
    outputs: renderV3Outputs,
    evidence: renderV3ScientificEvidence,
    attempts: renderV3ScientificAttempts,
    capabilities: renderV3Capabilities,
    failures: renderV3Failures,
    activity: renderV3Activity,
  };
  return renderers[viewState.currentSection]?.(workspace) ?? renderSessionFacts(workspace);
}

export function renderSidebarStatus(viewState) {
  const runtime = viewState.runtimeHealth;
  return `<p class="status-line">Project <strong>${escapeHtml(viewState.currentProjectId)}</strong></p><p class="status-line">Runtime <strong>${escapeHtml(runtime?.status ?? "unknown")}</strong>${runtime?.deployment_profile ? ` · ${escapeHtml(runtime.deployment_profile)}` : ""}</p>${renderPanelError(viewState.errors?.runtimeHealth ?? "")}${renderPanelError(viewState.errors?.createSession ?? "")}`;
}

export function renderSessionTree(viewState) {
  if (viewState.errors?.sidebar || viewState.errors?.session) {
    return `${renderPanelError(viewState.errors?.sidebar || viewState.errors?.session)}${viewState.sessionSummaries.length ? "" : `<p class="empty-copy">Sessions could not be loaded.</p>`}`;
  }
  if (!viewState.sessionSummaries.length) {
    return `<p class="empty-copy">No sessions yet.</p>`;
  }
  return `<ul class="tree-list">${viewState.sessionSummaries.map((session) => {
    const expanded = viewState.sidebarExpandedSessionIds.includes(session.session_id);
    const active = viewState.currentSessionId === session.session_id;
    const teammates = active ? viewState.workspace?.agents ?? [] : [];
    return `<li class="tree-node session-node"><div class="session-row ${active ? "is-active" : ""}"><button type="button" class="tree-toggle" data-action="toggle-session" data-session-id="${escapeHtml(session.session_id)}" aria-expanded="${expanded}">${expanded ? "▾" : "▸"}</button><button type="button" class="session-select" data-action="select-session" data-session-id="${escapeHtml(session.session_id)}" ${viewState.sidebarBusy ? "disabled" : ""}><strong>${escapeHtml(session.title || session.objective)}</strong><span>${escapeHtml(session.objective)}</span><small>${escapeHtml(session.status)}${session.pending_approval_count ? ` · ${session.pending_approval_count} approval` : ""}</small></button></div>${expanded ? `<ul class="section-tree">${Object.entries(sectionLabels).map(([key, label]) => `<li><button type="button" class="section-select ${active && viewState.currentSection === key ? "is-current" : ""}" data-action="select-section" data-session-id="${escapeHtml(session.session_id)}" data-section="${escapeHtml(key)}">${escapeHtml(label)}</button>${key === "team" && teammates.length ? `<ul class="teammate-tree">${teammates.map((agent) => `<li><button type="button" class="teammate-select ${viewState.selectedTeammateAgentId === agent.agent_id ? "is-current" : ""}" data-action="select-teammate" data-session-id="${escapeHtml(session.session_id)}" data-agent-id="${escapeHtml(agent.agent_id)}">${escapeHtml(agent.name ?? agent.agent_id)}</button></li>`).join("")}</ul>` : ""}</li>`).join("")}</ul>` : ""}</li>`;
  }).join("")}</ul>`;
}

export function renderConversationHeader(viewState) {
  const workspace = viewState.workspace;
  if (!workspace?.session) return "";
  return `<div class="conversation-title-block"><p class="eyebrow">${escapeHtml(viewState.selectedTeammateAgentId ? "Teammate" : "Conversation")}</p><h2>${escapeHtml(viewState.selectedTeammateAgentId || workspace.session.title || workspace.session.objective)}</h2><p class="status-line">${escapeHtml(workspace.session.objective)}</p><p class="session-meta">${escapeHtml(workspace.session.session_id)}</p></div><div class="header-status-stack">${viewState.refreshingWorkspace ? `<span class="status-chip">Refreshing…</span>` : ""}<div class="session-badge">${escapeHtml(workspace.session.status)}</div></div>`;
}

export function renderComposerStatus(viewState) {
  if (viewState.errors?.message) return renderPanelError(viewState.errors.message);
  if (viewState.workspace?.contract_blocked) return `<span class="error-banner">Contract mismatch: controls disabled.</span>`;
  if (viewState.messageBusy) return `<span class="status-line">Waiting for OpenZyme response…</span>`;
  return `<span class="status-line">Selected section: ${escapeHtml(sectionLabels[viewState.currentSection] ?? "Conversation")}</span>`;
}

export function renderInspectorHeader(viewState) {
  return `<h2>${escapeHtml(sectionLabels[viewState.currentSection] ?? "Conversation")}</h2><span>${escapeHtml(viewState.workspace?.session?.session_id ?? "No session")}</span>`;
}

function renderInspectorTabs(viewState) {
  return `<nav class="inspector-tabs" aria-label="Workspace inspector sections">${Object.entries(sectionLabels).filter(([key]) => key !== "conversation").map(([key, label]) => `<button type="button" class="inspector-tab ${viewState.currentSection === key ? "is-current" : ""}" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="${escapeHtml(key)}" aria-pressed="${viewState.currentSection === key}">${escapeHtml(label)}</button>`).join("")}</nav>`;
}

export function renderSidebar(viewState) {
  return `<section class="sidebar-shell"><div class="sidebar-panel"><p class="brand-wordmark">OpenZyme</p><p class="eyebrow">Research workspace</p><h1>${escapeHtml(viewState.currentProjectId)}</h1><div id="sidebar-status-root">${renderSidebarStatus(viewState)}</div><details class="new-session-disclosure"><summary>New session</summary><form id="create-session-form" class="compact-form" autocomplete="off"><input type="hidden" name="project_id" value="${escapeHtml(viewState.currentProjectId)}"/><label>Title<input name="title" placeholder="Optional session title"/></label><label>Objective<textarea name="objective" rows="3" placeholder="What should this session accomplish?" required></textarea></label><button id="create-session-submit" type="submit" ${viewState.createSessionBusy ? "disabled" : ""}>New Session</button></form></details></div><div class="tree-panel"><div class="tree-header"><h2>Sessions</h2><span id="session-count-root">${viewState.sidebarBusy ? "Loading..." : viewState.sessionSummaries.length}</span></div><div id="sidebar-tree-root">${renderSessionTree(viewState)}</div></div></section>`;
}

export function renderMainColumn(viewState) {
  const workspace = viewState.workspace;
  if (!workspace?.session) return renderEmptyConversation(viewState);
  const blocked = Boolean(workspace.contract_blocked);
  if (viewState.selectedTeammateAgentId) {
    return `<section class="main-column-shell" id="conversation-workspace"><header class="conversation-header" id="conversation-header-root">${renderConversationHeader(viewState)}</header><section class="conversation-panel"><div id="conversation-list-root">${renderTeammateTrace(workspace, viewState.selectedTeammateAgentId)}</div><div id="approval-stack-root">${renderV3Approvals(workspace, viewState)}</div></section></section>`;
  }
  return `<section class="main-column-shell" id="conversation-workspace"><header class="conversation-header" id="conversation-header-root">${renderConversationHeader(viewState)}</header><section class="conversation-panel"><div id="conversation-list-root">${renderV3Conversation(workspace)}</div><div id="approval-stack-root">${renderV3Approvals(workspace, viewState)}</div></section><form id="message-form" class="composer-panel" autocomplete="off"><textarea name="message" rows="3" placeholder="Message OpenZyme" ${viewState.messageBusy || blocked ? "disabled" : ""} required></textarea><div class="composer-actions"><div id="composer-status-root">${renderComposerStatus(viewState)}</div><div class="composer-send-group"><span class="composer-shortcut-hint">Ctrl+Enter to send</span><button id="message-submit" type="submit" ${viewState.messageBusy || blocked ? "disabled" : ""}>Send</button></div></div></form></section>`;
}

export function renderInspector(viewState) {
  return `<aside class="inspector-panel" aria-label="Workspace inspector"><div class="tree-header" id="inspector-header-root">${renderInspectorHeader(viewState)}</div>${renderInspectorTabs(viewState)}<div id="inspector-content-root">${renderInspectorContent(viewState)}</div></aside>`;
}

function renderRail(viewState) {
  const pending = viewState.workspace?.pending_approvals?.length ?? 0;
  return `<nav class="workspace-rail"><div class="rail-monogram">OZ</div><button type="button" data-action="select-mobile-pane" data-pane="sessions">S</button><button type="button" data-action="select-mobile-pane" data-pane="conversation">C</button><button type="button" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="team">T</button><button type="button" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="tasks">✓</button><button type="button" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="outputs">F</button>${pending ? `<span class="rail-attention">${pending}</span>` : ""}</nav>`;
}

function renderMobileNavigation(viewState) {
  return `<nav class="mobile-workspace-nav">${[["sessions", "Sessions"], ["conversation", "Conversation"], ["inspector", "Inspector"]].map(([pane, label]) => `<button type="button" data-action="select-mobile-pane" data-pane="${pane}" class="${viewState.mobilePane === pane ? "is-current" : ""}">${label}</button>`).join("")}</nav>`;
}

export function renderAppShell(viewState) {
  return `<main class="app-shell chat-workspace" data-mobile-pane="${escapeHtml(viewState.mobilePane ?? "conversation")}">${renderRail(viewState)}${renderMobileNavigation(viewState)}<section id="sidebar-column-root">${renderSidebar(viewState)}</section><section id="main-column-root">${renderMainColumn(viewState)}</section><section id="inspector-column-root">${renderInspector(viewState)}</section></main>`;
}

export function renderApp(viewState) {
  return renderAppShell(viewState);
}
