function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function renderPendingApproval(workspace) {
  const approval = workspace.workflow.pending_approval;
  const interrupt = workspace.workflow.pending_interrupt;
  if (!approval && !interrupt) {
    return '<p class="empty-state">No pending approval or interrupt.</p>';
  }
  return `
    <div class="callout">
      <p><strong>Pending approval:</strong> ${escapeHtml(approval?.requested_action ?? "None")}</p>
      <p><strong>Interrupt type:</strong> ${escapeHtml(interrupt?.type ?? "none")}</p>
      <div class="action-row">
        <button type="button" data-action="approve">Approve</button>
        <button type="button" class="secondary" data-action="reject">Reject</button>
      </div>
    </div>
  `;
}

function renderRuns(workspace) {
  if (!workspace.runs.length) {
    return '<p class="empty-state">No run records yet.</p>';
  }
  return `
    <ul class="data-list">
      ${workspace.runs
        .map(
          (run) => `
            <li>
              <span>${escapeHtml(run.run_id)}</span>
              <span>${escapeHtml(run.status)}</span>
              <span>${escapeHtml(run.execution_mode)}</span>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderArtifacts(workspace) {
  if (!workspace.artifacts.length) {
    return '<p class="empty-state">No artifacts available yet.</p>';
  }
  return `
    <ul class="data-list">
      ${workspace.artifacts
        .map(
          (artifact) => `
            <li>
              <span>${escapeHtml(artifact.kind)}</span>
              <span>${escapeHtml(artifact.artifact_id)}</span>
              <span>${escapeHtml(artifact.storage_uri)}</span>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

export function renderWorkspaceShell(viewState) {
  const workspace = viewState.workspace;
  if (!workspace) {
    return `
      <section class="panel intro-panel">
        <h2>Create a New Episode</h2>
        <p>Use the Host command surface to start the Phase B closed loop.</p>
      </section>
    `;
  }

  return `
    <section class="workspace-grid">
      <article class="panel hero-panel">
        <p class="eyebrow">Episode ${escapeHtml(workspace.episode_id)}</p>
        <h2>${escapeHtml(workspace.workflow.objective)}</h2>
        <p class="status-line">Phase: <strong>${escapeHtml(workspace.workflow.current_phase)}</strong> · Status: <strong>${escapeHtml(workspace.workflow.episode_status)}</strong></p>
        <p>${escapeHtml(workspace.workflow.progress.message ?? "No progress message")}</p>
        <div class="action-row">
          <button type="button" data-action="resume">Resume Episode</button>
        </div>
      </article>
      <article class="panel">
        <h3>Workflow</h3>
        <dl class="facts">
          <div><dt>Active node</dt><dd>${escapeHtml(workspace.workflow.progress.active_node)}</dd></div>
          <div><dt>Progress status</dt><dd>${escapeHtml(workspace.workflow.progress.status)}</dd></div>
          <div><dt>Updated at</dt><dd>${escapeHtml(workspace.workflow.progress.updated_at)}</dd></div>
        </dl>
      </article>
      <article class="panel">
        <h3>Pending Action</h3>
        ${renderPendingApproval(workspace)}
      </article>
      <article class="panel">
        <h3>Runs</h3>
        ${renderRuns(workspace)}
      </article>
      <article class="panel">
        <h3>Artifacts</h3>
        ${renderArtifacts(workspace)}
      </article>
    </section>
  `;
}

export function renderApp(viewState) {
  return `
    <section class="panel form-panel">
      <form id="create-episode-form">
        <label>
          Project ID
          <input name="project_id" value="proj_001" required />
        </label>
        <label>
          Objective
          <input name="objective" value="Improve thermostability" required />
        </label>
        <button type="submit">${viewState.busy ? "Working..." : "Create Episode"}</button>
      </form>
      ${viewState.errorMessage ? `<p class="error-banner">${escapeHtml(viewState.errorMessage)}</p>` : ""}
    </section>
    ${renderWorkspaceShell(viewState)}
  `;
}
