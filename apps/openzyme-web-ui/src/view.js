function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function renderEmptyState() {
  return `
    <section class="workspace-board v3-workspace">
      <article class="panel hero-panel chat-hero">
        <p class="eyebrow">OpenZyme V3</p>
        <h2>Session Workspace</h2>
        <p class="status-line">Create a session, then send a message to the harness.</p>
      </article>
    </section>
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
              <div class="action-row">
                <button type="button" data-v3-approval-decision="approved" ${viewState.busy ? "disabled" : ""}>Approve</button>
                <button type="button" data-v3-approval-decision="rejected" ${viewState.busy ? "disabled" : ""}>Reject</button>
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
            <li class="chat-message ${item.role === "user" ? "from-user" : "from-agent"}">
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
  const reports = workspace.reports ?? [];
  if (!artifacts.length && !reports.length) {
    return `<p class="empty-copy">No artifacts or reports yet.</p>`;
  }
  return `
    <div class="stack">
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
        .slice(0, 8)
        .map((event) => `<li><strong>${escapeHtml(event.event_type)}</strong><span>${escapeHtml(event.created_at ?? "")}</span></li>`)
        .join("")}
    </ul>
  `;
}

export function renderV3Hero(workspace) {
  const session = workspace.session ?? {};
  return `
    <p class="eyebrow">OpenZyme V3</p>
    <h2>${escapeHtml(session.objective)}</h2>
    <p class="status-line">Session: <strong>${escapeHtml(session.session_id)}</strong> · Status: <strong>${escapeHtml(session.status)}</strong></p>
  `;
}

export function renderV3Workspace(workspace, viewState) {
  return `
    <section class="workspace-board v3-workspace">
      <article class="panel hero-panel chat-hero" id="v3-hero-panel">
        ${renderV3Hero(workspace)}
      </article>
      <article class="panel pane chat-pane">
        <h3>Conversation</h3>
        <div id="v3-conversation-list">${renderV3Conversation(workspace)}</div>
        <div id="v3-approval-stack">${renderV3Approvals(workspace, viewState)}</div>
        <form id="message-form" class="message-form" autocomplete="off">
          <input
            name="message"
            placeholder="Send a message to the harness"
            autocomplete="off"
            autocapitalize="off"
            autocorrect="off"
            spellcheck="false"
            ${viewState.busy ? "disabled" : ""}
            required
          />
          <button type="submit" ${viewState.busy ? "disabled" : ""}>Send</button>
        </form>
      </article>
      <article class="panel pane task-pane">
        <h3>Task Board</h3>
        <div id="v3-task-board">${renderV3TaskBoard(workspace)}</div>
      </article>
      <article class="panel pane lane-pane">
        <h3>Lanes</h3>
        <div id="v3-lane-board">${renderV3Lanes(workspace)}</div>
      </article>
      <article class="panel pane activity-pane">
        <h3>Activity</h3>
        <div id="v3-activity-feed">${renderV3Activity(workspace)}</div>
      </article>
      <article class="panel pane report-pane">
        <h3>Outputs</h3>
        <div id="v3-outputs">${renderV3Outputs(workspace)}</div>
      </article>
      <article class="panel pane capability-pane">
        <h3>Capabilities</h3>
        <div id="v3-capabilities">${renderV3Capabilities(workspace)}</div>
      </article>
    </section>
  `;
}

export function renderFormPanel(viewState) {
  return `
    <section class="panel form-panel">
      <h1>OpenZyme V3</h1>
      <p class="status-line">Session-first workspace for the harness control plane.</p>
      <form id="create-session-form" autocomplete="off">
        <label>
          Project ID
          <input
            name="project_id"
            value="${escapeHtml(viewState.currentProjectId || "proj_001")}"
            autocomplete="off"
            autocapitalize="off"
            autocorrect="off"
            spellcheck="false"
            required
          />
        </label>
        <label>
          Objective
          <input
            name="objective"
            value="Plan an enzyme design workflow from a paper"
            autocomplete="off"
            autocapitalize="off"
            autocorrect="off"
            spellcheck="false"
            required
          />
        </label>
        <button type="submit" ${viewState.busy ? "disabled" : ""}>Create Session</button>
      </form>
      ${viewState.errorMessage ? `<p class="error-banner">${escapeHtml(viewState.errorMessage)}</p>` : ""}
    </section>
  `;
}

export function renderApp(viewState) {
  return `
    <main class="app-shell">
      <div id="form-panel-root">${renderFormPanel(viewState)}</div>
      <div id="workspace-shell-root">
        ${viewState.workspace?.session ? renderV3Workspace(viewState.workspace, viewState) : renderEmptyState()}
      </div>
    </main>
  `;
}
