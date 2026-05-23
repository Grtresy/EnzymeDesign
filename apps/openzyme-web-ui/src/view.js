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

const privateArtifactKeys = new Set(["storage_uri", "source_storage_uri", "intermediate_storage_uri", "local_path"]);

function sanitizeArtifactMetadata(value) {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeArtifactMetadata(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !privateArtifactKeys.has(key))
        .map(([key, item]) => [key, sanitizeArtifactMetadata(item)]),
    );
  }
  return value;
}

function buildArtifactTree(artifacts) {
  const root = { directories: new Map(), files: [] };
  for (const artifact of artifacts) {
    const relativePath = String(artifact.relative_path || artifact.title || artifact.artifact_id || "artifact");
    const segments = relativePath.split("/").filter(Boolean);
    const fileName = segments.pop() || String(artifact.title || artifact.artifact_id || "artifact");
    let cursor = root;
    for (const segment of segments) {
      if (!cursor.directories.has(segment)) {
        cursor.directories.set(segment, { directories: new Map(), files: [] });
      }
      cursor = cursor.directories.get(segment);
    }
    cursor.files.push({ artifact, fileName });
  }
  return root;
}

function renderArtifactTreeNode(node, selectedArtifactId) {
  const directoryHtml = Array.from(node.directories.entries())
    .map(
      ([name, child]) => `
        <li class="artifact-directory">
          <details open>
            <summary>${escapeHtml(name)}</summary>
            <ul class="artifact-tree">
              ${renderArtifactTreeNode(child, selectedArtifactId)}
            </ul>
          </details>
        </li>
      `,
    )
    .join("");
  const fileHtml = node.files
    .map(({ artifact, fileName }) => {
      const artifactId = artifact.artifact_id ?? "";
      return `
        <li>
          <button
            type="button"
            class="artifact-file ${selectedArtifactId === artifactId ? "is-selected" : ""}"
            data-action="select-artifact"
            data-artifact-id="${escapeHtml(artifactId)}"
          >
            <strong>${escapeHtml(fileName)}</strong>
            <span>${escapeHtml(artifact.kind ?? "artifact")} · ${escapeHtml(artifactId)}</span>
          </button>
        </li>
      `;
    })
    .join("");
  return `${directoryHtml}${fileHtml}`;
}

function renderArtifactValue(value) {
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => String(item)).join(", ") : "none";
  }
  if (value && typeof value === "object") {
    const keys = Object.keys(value);
    return keys.length ? keys.join(", ") : "none";
  }
  return value ?? "none";
}

function renderArtifactFacts(artifact) {
  const provenance = artifact.provenance ?? {};
  const facts = [
    ["Artifact", artifact.artifact_id],
    ["Kind", artifact.kind],
    ["Path", artifact.relative_path],
    ["Task", provenance.task_id ?? artifact.task_id],
    ["Lane", provenance.lane_id ?? artifact.lane_id],
    ["Invocation", provenance.invocation_id ?? artifact.invocation_id],
    ["Run", provenance.run_id ?? artifact.run_id],
    ["Format", provenance.format],
    ["Produced By", provenance.produced_by],
    ["Provider", provenance.provider],
    ["External ID", provenance.external_id],
    ["Source Locator", provenance.source_locator],
    ["Source Artifacts", provenance.source_artifact_ids],
    ["Input Artifacts", provenance.input_artifact_ids],
    ["Preprocess Artifacts", provenance.preprocess_artifact_ids],
    ["Runner Run", provenance.runner_run_id],
    ["Pipeline Invocation", provenance.pipeline_invocation_id],
    ["Code Digest", provenance.code_digest],
    ["Tool Contract", provenance.tool_contract],
  ];
  return `
    <dl class="facts compact-facts artifact-facts">
      ${facts
        .map(
          ([label, value]) => `
            <div>
              <dt>${escapeHtml(label)}</dt>
              <dd>${escapeHtml(renderArtifactValue(value))}</dd>
            </div>
          `,
        )
        .join("")}
    </dl>
  `;
}

function renderArtifactDetail(artifact) {
  if (!artifact) {
    return `<p class="empty-copy">No artifact selected.</p>`;
  }
  const metadata = sanitizeArtifactMetadata(artifact.metadata ?? {});
  const provenance = sanitizeArtifactMetadata(artifact.provenance ?? {});
  return `
    <article class="artifact-detail" aria-label="Artifact details">
      <header>
        <p class="eyebrow">Artifact</p>
        <h4>${escapeHtml(artifact.title ?? artifact.relative_path ?? artifact.artifact_id)}</h4>
      </header>
      ${renderArtifactFacts(artifact)}
      <div class="artifact-json-stack">
        <section>
          <h5>Provenance</h5>
          <pre>${escapeHtml(JSON.stringify(provenance, null, 2))}</pre>
        </section>
        <section>
          <h5>Metadata</h5>
          <pre>${escapeHtml(JSON.stringify(metadata, null, 2))}</pre>
        </section>
      </div>
    </article>
  `;
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
          return `
            <li>
              <strong>${escapeHtml(agent.name ?? agent.agent_id ?? "agent")}</strong>
              <span>${escapeHtml(agent.role ?? "worker")} · ${escapeHtml(agent.status ?? "unknown")} · ${escapeHtml(agent.task_id ?? "no-task")}</span>
              <small>${escapeHtml(latestCorrelation)}${pendingCount ? ` · ${pendingCount} pending` : ""}</small>
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

function renderToolCallCard(toolCall) {
  return `
    <article class="tool-call-card">
      <div>
        <strong>${escapeHtml(toolCall.tool_name ?? "tool")}</strong>
        <span>${escapeHtml(toolCall.call_id ?? "")}</span>
      </div>
      <dl class="facts compact-facts">
        <div><dt>Task</dt><dd>${escapeHtml(toolCall.task_id ?? "none")}</dd></div>
        <div><dt>Lane</dt><dd>${escapeHtml(toolCall.lane_id ?? "none")}</dd></div>
      </dl>
      <pre>${escapeHtml(JSON.stringify(toolCall.args_public ?? {}, null, 2))}</pre>
    </article>
  `;
}

function renderTraceStep(step, { teammate = false } = {}) {
  const hasText = Boolean(String(step.response_text ?? "").trim());
  const toolCalls = step.tool_calls ?? [];
  return `
    <li class="trace-step ${teammate ? "from-teammate" : "from-agent"}" data-trace-id="${escapeHtml(step.trace_id ?? "")}">
      <div class="trace-step-header">
        <span>${escapeHtml(step.display_name ?? step.actor_ref ?? "agent")}</span>
        <small>${escapeHtml(step.role ?? "")} · call ${escapeHtml(step.call_index ?? "")}</small>
      </div>
      ${
        step.initial_prompt
          ? `<article class="trace-seed-card">
              <strong>Role seed</strong>
              <dl class="facts compact-facts">
                <div><dt>Identity</dt><dd>${escapeHtml(step.initial_prompt.identity ?? "")}</dd></div>
                <div><dt>Role</dt><dd>${escapeHtml(step.initial_prompt.role ?? "")}</dd></div>
                <div><dt>Task</dt><dd>${escapeHtml(step.initial_prompt.task_id ?? "")}</dd></div>
                <div><dt>Lane</dt><dd>${escapeHtml(step.initial_prompt.lane_id ?? "none")}</dd></div>
                <div><dt>Correlation</dt><dd>${escapeHtml(step.initial_prompt.correlation_id ?? "")}</dd></div>
              </dl>
              <p>${escapeHtml(step.initial_prompt.instructions ?? "")}</p>
              <pre>${escapeHtml(step.initial_prompt.seed_message ?? "")}</pre>
            </article>`
          : ""
      }
      ${hasText ? `<p>${escapeHtml(step.response_text)}</p>` : ""}
      ${toolCalls.length ? `<div class="tool-call-stack">${toolCalls.map(renderToolCallCard).join("")}</div>` : ""}
    </li>
  `;
}

function buildMasterConversationTimeline(workspace) {
  const harnessTrace = workspace.agent_traces?.harness ?? [];
  if (!harnessTrace.length) {
    return (workspace.conversation ?? []).map((item) => ({ type: "conversation", item }));
  }
  return [
    ...(workspace.conversation ?? [])
      .filter((item) => item.role === "user" || item.error)
      .map((item) => ({ type: "conversation", item, created_at: item.created_at ?? "" })),
    ...harnessTrace.map((item) => ({ type: "trace", item, created_at: item.created_at ?? "" })),
  ].sort((left, right) => String(left.created_at ?? "").localeCompare(String(right.created_at ?? "")));
}

export function renderV3Conversation(workspace) {
  const timeline = buildMasterConversationTimeline(workspace);
  if (!timeline.length) {
    return `<p class="empty-copy">Send a message to start the session.</p>`;
  }
  return `
    <ol class="chat-list">
      ${timeline
        .map((entry) => {
          if (entry.type === "trace") {
            return renderTraceStep(entry.item);
          }
          const item = entry.item;
          return `
            <li class="chat-message ${item.role === "user" ? "from-user" : "from-agent"}${item.error ? " is-error" : ""}" data-message-id="${escapeHtml(item.message_id ?? item.event_id ?? "")}">
              <span>${escapeHtml(item.role === "user" ? "You" : "OpenZyme")}</span>
              <p>${escapeHtml(item.content)}</p>
            </li>
          `;
        })
        .join("")}
    </ol>
  `;
}

export function renderTeammateTrace(workspace, agentId) {
  const agent = (workspace.delegation?.agents ?? []).find((item) => item.agent?.agent_id === agentId)?.agent ?? {};
  const traces = workspace.agent_traces?.[agentId] ?? [];
  return `
    <div class="readonly-banner">
      <strong>${escapeHtml(agent.name ?? agentId)}</strong>
      <span>${escapeHtml(agent.role ?? "teammate")} trace is read-only.</span>
    </div>
    ${
      traces.length
        ? `<ol class="chat-list trace-list">${traces.map((step) => renderTraceStep(step, { teammate: true })).join("")}</ol>`
        : `<p class="empty-copy">No teammate trace has been recorded yet.</p>`
    }
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

export function renderV3Outputs(workspace, viewState = {}) {
  const artifacts = workspace.artifacts ?? [];
  const drafts = workspace.report_drafts ?? [];
  const reports = workspace.reports ?? [];
  const selectedArtifact = artifacts.find((artifact) => artifact.artifact_id === viewState.selectedArtifactId) ?? artifacts[0] ?? null;
  const selectedArtifactId = selectedArtifact?.artifact_id ?? "";
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
              <div class="artifact-browser">
                <nav aria-label="Artifact tree">
                  <ul class="artifact-tree">
                    ${renderArtifactTreeNode(buildArtifactTree(artifacts), selectedArtifactId)}
                  </ul>
                </nav>
                ${renderArtifactDetail(selectedArtifact)}
              </div>
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
      return renderV3Outputs(workspace, viewState);
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
          const teammates = isActive ? viewState.workspace?.delegation?.agents ?? [] : [];
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
                  <span>${escapeHtml(session.objective)}</span>
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
                              ${
                                sectionKey === "team" && teammates.length
                                  ? `<ul class="teammate-tree" role="group">
                                      ${teammates
                                        .map((item) => {
                                          const agent = item.agent ?? {};
                                          return `
                                            <li>
                                              <button
                                                type="button"
                                                class="teammate-select ${viewState.selectedTeammateAgentId === agent.agent_id ? "is-current" : ""}"
                                                data-action="select-teammate"
                                                data-session-id="${escapeHtml(session.session_id)}"
                                                data-agent-id="${escapeHtml(agent.agent_id ?? "")}"
                                                ${viewState.sidebarBusy ? "disabled" : ""}
                                              >${escapeHtml(agent.name ?? agent.agent_id ?? "teammate")}</button>
                                            </li>
                                          `;
                                        })
                                        .join("")}
                                    </ul>`
                                  : ""
                              }
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
      <p class="eyebrow">${escapeHtml(viewState.selectedTeammateAgentId ? "Teammate Trace" : "Conversation")}</p>
      <h2>${escapeHtml(viewState.selectedTeammateAgentId || workspace.session.title || workspace.session.objective)}</h2>
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
  if (viewState.messageBusy) {
    return `<span class="status-line">Waiting for OpenZyme response…</span>`;
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
  if (viewState.selectedTeammateAgentId) {
    return `
      <section class="main-column-shell">
        <header class="panel conversation-header" id="conversation-header-root">${renderConversationHeader(viewState)}</header>
        <section class="panel conversation-panel">
          <div id="conversation-list-root">${renderTeammateTrace(workspace, viewState.selectedTeammateAgentId)}</div>
        </section>
      </section>
    `;
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
          <div class="composer-send-group">
            <span class="composer-shortcut-hint">Ctrl+Enter to send</span>
            <button id="message-submit" type="submit" ${viewState.messageBusy ? "disabled" : ""}>Send</button>
          </div>
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
