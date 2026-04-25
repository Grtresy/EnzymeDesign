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
  outputs: "Outputs",
  capabilities: "Capabilities",
  activity: "Activity",
};

function renderEmptyConversation(viewState) {
  return `
    <div class="empty-chat">
      <p class="eyebrow">OpenZyme V3</p>
      <h2>Select a session or create a new one</h2>
      <p class="status-line">The center column stays focused on the conversation. Operational detail lives in the inspector.</p>
      ${viewState?.errors?.session ? `<p class="error-banner" role="alert">${escapeHtml(viewState.errors.session)}</p>` : ""}
    </div>
  `;
}

function renderPanelError(message) {
  if (!message) {
    return "";
  }
  return `<p class="error-banner" role="alert">${escapeHtml(message)}</p>`;
}

export function renderV3TaskBoard(workspace) {
  const items = workspace.task_board?.items ?? [];
  if (!items.length) {
    return `<p class="empty-copy">No tasks yet.</p>`;
  }
  return `
    <ul class="record-list">
      ${items
        .map((item) => {
          const task = item.task ?? {};
          return `<li><strong>${escapeHtml(task.subject)}</strong><span>${escapeHtml(task.task_id)} · ${escapeHtml(task.status)} · ${escapeHtml(item.bucket)}</span></li>`;
        })
        .join("")}
    </ul>
  `;
}

export function renderV3Delegation(workspace) {
  const agents = workspace.delegation?.agents ?? [];
  if (!agents.length) {
    return `<p class="empty-copy">No delegated teammates yet.</p>`;
  }
  return `
    <ul class="record-list">
      ${agents
        .map((item) => {
          const agent = item.agent ?? {};
          const latestCorrelation = item.latest_correlation_id ?? item.correlation_ids?.[0] ?? "none";
          const pendingCount = (item.pending_correlation_ids ?? []).length;
          const unreadCount = item.unread_inbox_count ?? 0;
          const signalCount = item.pending_signal_count ?? 0;
          const wakeup = item.wakeup_reason ?? item.latest_signal_reason ?? "";
          return `
            <li>
              <strong>${escapeHtml(agent.name ?? agent.agent_id ?? "agent")}</strong>
              <span>${escapeHtml(agent.role ?? "worker")} · ${escapeHtml(agent.status ?? "unknown")} · ${escapeHtml(agent.task_id ?? "no-task")}</span>
              <small>${escapeHtml(latestCorrelation)}${pendingCount ? ` · ${pendingCount} pending` : ""}${unreadCount ? ` · ${unreadCount} unread` : ""}${signalCount ? ` · ${signalCount} wakeups` : ""}${wakeup ? ` · ${escapeHtml(wakeup)}` : ""}</small>
            </li>
          `;
        })
        .join("")}
    </ul>
  `;
}

export function renderV3Lanes(workspace) {
  const lanes = workspace.lane_board?.lanes ?? [];
  if (!lanes.length) {
    return `<p class="empty-copy">No lanes yet.</p>`;
  }
  return `
    <ul class="record-list">
      ${lanes
        .map((item) => {
          const lane = item.lane ?? {};
          return `<li><strong>${escapeHtml(lane.name)}</strong><span>${escapeHtml(lane.lane_id)} · ${escapeHtml(lane.status)} · ${escapeHtml(lane.cwd)}</span></li>`;
        })
        .join("")}
    </ul>
  `;
}

export function renderV3Approvals(workspace, viewState) {
  const approvals = workspace.pending_approvals ?? [];
  if (!approvals.length) {
    return "";
  }
  return `
    <div class="approval-stack" aria-label="Pending approvals">
      ${approvals
        .map(
          (approval) => `
            <article class="approval-card">
              <p class="eyebrow">${escapeHtml(approval.kind ?? "approval")}</p>
              <h4>${escapeHtml(approval.requested_action ?? "Review requested action")}</h4>
              <dl class="facts compact-facts">
                <div><dt>Approval</dt><dd>${escapeHtml(approval.approval_id)}</dd></div>
                <div><dt>Task</dt><dd>${escapeHtml(approval.task_id ?? "none")}</dd></div>
                <div><dt>Lane</dt><dd>${escapeHtml(approval.lane_id ?? "none")}</dd></div>
              </dl>
              ${renderPanelError(viewState.errors.approvals?.[approval.approval_id] ?? "")}
              <div class="action-row">
                <button
                  type="button"
                  data-v3-approval-decision="approved"
                  data-approval-id="${escapeHtml(approval.approval_id)}"
                  ${viewState.pendingApprovalId === approval.approval_id ? "disabled" : ""}
                >Approve</button>
                <button
                  type="button"
                  data-v3-approval-decision="rejected"
                  data-approval-id="${escapeHtml(approval.approval_id)}"
                  ${viewState.pendingApprovalId === approval.approval_id ? "disabled" : ""}
                >Reject</button>
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

export function renderV3Conversation(workspace) {
  const conversation = workspace.conversation ?? [];
  if (!conversation.length) {
    return `<p class="empty-copy">Send a message to start the session.</p>`;
  }
  return `
    <ol class="chat-list">
      ${conversation
        .map(
          (item) => `
            <li class="chat-message ${item.role === "user" ? "from-user" : "from-agent"}" data-message-id="${escapeHtml(item.message_id ?? item.event_id ?? "")}">
              <span>${escapeHtml(item.role === "user" ? "You" : "OpenZyme")}</span>
              <p>${escapeHtml(item.content)}</p>
            </li>
          `,
        )
        .join("")}
    </ol>
  `;
}

export function renderV3Capabilities(workspace) {
  const entries = Object.entries(workspace.capabilities ?? {}).flatMap(([capabilityKey, items]) =>
    (items ?? []).map((item) => ({ capabilityKey, item })),
  );
  if (!entries.length) {
    return `<p class="empty-copy">No capability invocations yet.</p>`;
  }
  return `
    <ul class="record-list">
      ${entries
        .map(
          ({ capabilityKey, item }) => `
            <li>
              <strong>${escapeHtml(capabilityKey)}</strong>
              <span>${escapeHtml(item.invocation_id ?? "invocation")} · ${escapeHtml(item.status ?? "unknown")}</span>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

export function renderV3Outputs(workspace) {
  const artifacts = workspace.artifacts ?? [];
  const drafts = workspace.report_drafts ?? [];
  const reports = workspace.reports ?? [];
  if (!artifacts.length && !drafts.length && !reports.length) {
    return `<p class="empty-copy">No artifacts, drafts, or reports yet.</p>`;
  }
  return `
    <div class="stack">
      ${
        drafts.length
          ? `<section>
              <h4>Report Drafts</h4>
              <ul class="record-list">
                ${drafts
                  .map(
                    (draft) => `
                      <li>
                        <strong>${escapeHtml(draft.title ?? draft.draft_id)}</strong>
                        <span>${escapeHtml(draft.status ?? "unknown")} · ${escapeHtml(draft.draft_id)}</span>
                      </li>
                    `,
                  )
                  .join("")}
              </ul>
            </section>`
          : ""
      }
      ${
        reports.length
          ? `<section>
              <h4>Reports</h4>
              <ul class="record-list">
                ${reports
                  .map(
                    (report) => `
                      <li>
                        <strong>${escapeHtml(report.title ?? report.report_id)}</strong>
                        <span>${escapeHtml(report.status ?? "unknown")} · ${escapeHtml(report.report_id)}</span>
                      </li>
                    `,
                  )
                  .join("")}
              </ul>
            </section>`
          : ""
      }
      ${
        artifacts.length
          ? `<section>
              <h4>Artifacts</h4>
              <ul class="record-list">
                ${artifacts
                  .map(
                    (artifact) => `
                      <li>
                        <strong>${escapeHtml(artifact.title ?? artifact.relative_path ?? artifact.artifact_id)}</strong>
                        <span>${escapeHtml(artifact.kind ?? "artifact")} · ${escapeHtml(artifact.artifact_id)}</span>
                      </li>
                    `,
                  )
                  .join("")}
              </ul>
            </section>`
          : ""
      }
    </div>
  `;
}

export function renderV3Activity(workspace) {
  const events = workspace.activity_feed ?? [];
  if (!events.length) {
    return `<p class="empty-copy">No activity yet.</p>`;
  }
  return `
    <ul class="activity-list">
      ${events
        .slice(0, 10)
        .map((event) => `<li><strong>${escapeHtml(event.event_type)}</strong><span>${escapeHtml(event.created_at ?? "")}</span></li>`)
        .join("")}
    </ul>
  `;
}

function renderSessionFacts(workspace) {
  const session = workspace.session ?? {};
  return `
    <dl class="facts">
      <div><dt>Session</dt><dd>${escapeHtml(session.session_id)}</dd></div>
      <div><dt>Status</dt><dd>${escapeHtml(session.status)}</dd></div>
      <div><dt>Project</dt><dd>${escapeHtml(session.project_id)}</dd></div>
      <div><dt>Created</dt><dd>${escapeHtml(session.created_at ?? "")}</dd></div>
      <div><dt>Updated</dt><dd>${escapeHtml(session.updated_at ?? "")}</dd></div>
    </dl>
  `;
}

export function renderInspectorContent(viewState) {
  const workspace = viewState.workspace;
  if (!workspace?.session) {
    return `<p class="empty-copy">Select a session to inspect structured state.</p>`;
  }
  switch (viewState.currentSection) {
    case "team":
      return renderV3Delegation(workspace);
    case "tasks":
      return renderV3TaskBoard(workspace);
    case "lanes":
      return renderV3Lanes(workspace);
    case "outputs":
      return renderV3Outputs(workspace);
    case "capabilities":
      return renderV3Capabilities(workspace);
    case "activity":
      return renderV3Activity(workspace);
    default:
      return renderSessionFacts(workspace);
  }
}

export function renderSidebarStatus(viewState) {
  return `
    <p class="status-line">Project <strong>${escapeHtml(viewState.currentProjectId)}</strong></p>
    ${renderPanelError(viewState.errors?.createSession ?? "")}
  `;
}

export function renderSessionTree(viewState) {
  if (viewState.errors?.sidebar || viewState.errors?.session) {
    return `
      ${renderPanelError(viewState.errors?.sidebar || viewState.errors?.session)}
      ${viewState.sessionSummaries.length ? "" : `<p class="empty-copy">Sessions could not be loaded.</p>`}
    `;
  }
  if (!viewState.sessionSummaries.length) {
    return `<p class="empty-copy">No sessions yet.</p>`;
  }
  return `
    <ul class="tree-list" role="tree">
      ${viewState.sessionSummaries
        .map((session) => {
          const isExpanded = viewState.sidebarExpandedSessionIds.includes(session.session_id);
          const isActive = viewState.currentSessionId === session.session_id;
          return `
            <li class="tree-node session-node" role="treeitem" aria-expanded="${isExpanded}">
              <div class="session-row ${isActive ? "is-active" : ""}">
                <button
                  type="button"
                  class="tree-toggle"
                  data-action="toggle-session"
                  data-session-id="${escapeHtml(session.session_id)}"
                  aria-label="${isExpanded ? "Collapse" : "Expand"}"
                >${isExpanded ? "▾" : "▸"}</button>
                <button
                  type="button"
                  class="session-select"
                  data-action="select-session"
                  data-session-id="${escapeHtml(session.session_id)}"
                  ${viewState.sidebarBusy ? "disabled" : ""}
                >
                  <strong>${escapeHtml(session.title || session.objective)}</strong>
                  <span>${escapeHtml(session.latest_message_preview || session.objective)}</span>
                  <small>${escapeHtml(session.status)}${session.pending_approval_count ? ` · ${session.pending_approval_count} approval` : ""}</small>
                </button>
              </div>
              ${
                isExpanded
                  ? `<ul class="section-tree" role="group">
                      ${Object.entries(sectionLabels)
                        .map(
                          ([sectionKey, label]) => `
                            <li>
                              <button
                                type="button"
                                class="section-select ${isActive && viewState.currentSection === sectionKey ? "is-current" : ""}"
                                data-action="select-section"
                                data-session-id="${escapeHtml(session.session_id)}"
                                data-section="${escapeHtml(sectionKey)}"
                                ${viewState.sidebarBusy ? "disabled" : ""}
                              >${escapeHtml(label)}</button>
                            </li>
                          `,
                        )
                        .join("")}
                    </ul>`
                  : ""
              }
            </li>
          `;
        })
        .join("")}
    </ul>
  `;
}

export function renderConversationHeader(viewState) {
  const workspace = viewState.workspace;
  if (!workspace?.session) {
    return "";
  }
  return `
    <div>
      <p class="eyebrow">Conversation</p>
      <h2>${escapeHtml(workspace.session.title ?? workspace.session.objective)}</h2>
      <p class="status-line">${escapeHtml(workspace.session.objective)}</p>
    </div>
    <div class="header-status-stack">
      ${viewState.refreshingWorkspace ? `<span class="status-chip">Refreshing…</span>` : ""}
      <div class="session-badge">${escapeHtml(workspace.session.status)}</div>
    </div>
  `;
}

export function renderComposerStatus(viewState) {
  if (viewState.errors?.message) {
    return renderPanelError(viewState.errors.message);
  }
  return `<span class="status-line">Selected section: ${escapeHtml(sectionLabels[viewState.currentSection] ?? "Conversation")}</span>`;
}

export function renderInspectorHeader(viewState) {
  return `
    <h3>${escapeHtml(sectionLabels[viewState.currentSection] ?? "Conversation")}</h3>
    ${
      viewState.workspace?.session
        ? `<span>${escapeHtml(viewState.workspace.session.session_id)}</span>`
        : `<span>No session</span>`
    }
  `;
}

export function renderSidebar(viewState) {
  return `
    <section class="sidebar-shell">
      <div class="panel sidebar-panel">
        <p class="eyebrow">OpenZyme V3</p>
        <h1>Workspace</h1>
        <div id="sidebar-status-root">${renderSidebarStatus(viewState)}</div>
        <form id="create-session-form" class="compact-form" autocomplete="off">
          <input type="hidden" name="project_id" value="${escapeHtml(viewState.currentProjectId)}" />
          <label>
            Title
            <input
              name="title"
              placeholder="Optional session title"
              autocomplete="off"
              autocapitalize="off"
              autocorrect="off"
              spellcheck="false"
            />
          </label>
          <label>
            Objective
            <textarea
              name="objective"
              rows="3"
              placeholder="What should this session accomplish?"
              autocomplete="off"
              autocapitalize="off"
              autocorrect="off"
              spellcheck="false"
              required
            ></textarea>
          </label>
          <button id="create-session-submit" type="submit" ${viewState.createSessionBusy ? "disabled" : ""}>New Session</button>
        </form>
      </div>
      <div class="panel tree-panel">
        <div class="tree-header">
          <h3>Sessions</h3>
          <span id="session-count-root">${viewState.sidebarBusy ? "Loading..." : `${viewState.sessionSummaries.length}`}</span>
        </div>
        <div id="sidebar-tree-root">${renderSessionTree(viewState)}</div>
      </div>
    </section>
  `;
}

export function renderMainColumn(viewState) {
  const workspace = viewState.workspace;
  if (!workspace?.session) {
    return renderEmptyConversation(viewState);
  }
  return `
    <section class="main-column-shell">
      <header class="panel conversation-header" id="conversation-header-root">${renderConversationHeader(viewState)}</header>
      <section class="panel conversation-panel">
        <div id="conversation-list-root">${renderV3Conversation(workspace)}</div>
        <div id="approval-stack-root">${renderV3Approvals(workspace, viewState)}</div>
      </section>
      <form id="message-form" class="panel composer-panel" autocomplete="off">
        <textarea
          name="message"
          rows="3"
          placeholder="Message the harness"
          autocomplete="off"
          autocapitalize="off"
          autocorrect="off"
          spellcheck="false"
          ${viewState.messageBusy ? "disabled" : ""}
          required
        ></textarea>
        <div class="composer-actions">
          <div id="composer-status-root">${renderComposerStatus(viewState)}</div>
          <button id="message-submit" type="submit" ${viewState.messageBusy ? "disabled" : ""}>Send</button>
        </div>
      </form>
    </section>
  `;
}

export function renderInspector(viewState) {
  return `
    <section class="panel inspector-panel">
      <div class="tree-header" id="inspector-header-root">${renderInspectorHeader(viewState)}</div>
      <div id="inspector-content-root">${renderInspectorContent(viewState)}</div>
    </section>
  `;
}

export function renderAppShell(viewState) {
  return `
    <main class="app-shell chat-workspace">
      <section id="sidebar-column-root">${renderSidebar(viewState)}</section>
      <section id="main-column-root">${renderMainColumn(viewState)}</section>
      <section id="inspector-column-root">${renderInspector(viewState)}</section>
    </main>
  `;
}

export function renderApp(viewState) {
  return renderAppShell(viewState);
}
