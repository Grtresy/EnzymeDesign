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

function renderEvidence(workspace) {
  const research = workspace.research ?? { evidence: [], unresolved_gaps: [], summary: null };
  if (!research.evidence.length && !research.summary) {
    return '<p class="empty-state">No research evidence loaded yet.</p>';
  }
  return `
    <div class="stack">
      ${research.summary ? `<p><strong>Summary:</strong> ${escapeHtml(research.summary.summary)}</p>` : ""}
      <ul class="data-list">
        ${research.evidence
          .map(
            (evidence) => `
              <li>
                <span>${escapeHtml(evidence.evidence_id)}</span>
                <span>${escapeHtml(evidence.summary)}</span>
                <span>${escapeHtml(evidence.query)}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
      ${
        research.unresolved_gaps.length
          ? `<p><strong>Open gaps:</strong> ${escapeHtml(research.unresolved_gaps.map((gap) => gap.summary).join(" | "))}</p>`
          : ""
      }
    </div>
  `;
}

function renderCandidates(workspace) {
  const design = workspace.design ?? { candidates: [], selected_candidate: null };
  if (!design.candidates.length) {
    return '<p class="empty-state">No design candidates available yet.</p>';
  }
  return `
    <div class="stack">
      ${
        design.selected_candidate
          ? `<p><strong>Selected:</strong> ${escapeHtml(design.selected_candidate.candidate_id)} · ${escapeHtml(design.selected_candidate.rationale)}</p>`
          : '<p class="empty-state">No selected candidate yet.</p>'
      }
      <ul class="data-list">
        ${design.candidates
          .map(
            (candidate) => `
              <li>
                <span>${escapeHtml(candidate.candidate_id)}</span>
                <span>${escapeHtml(candidate.title)}</span>
                <span>${escapeHtml(candidate.ranking?.rank ?? "n/a")}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
    </div>
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
        ${
          workspace.workflow.summary
            ? `<p><strong>Summary:</strong> ${escapeHtml(
                `Evidence ${workspace.workflow.summary.evidence_count}, candidates ${workspace.workflow.summary.candidate_count}, wait ${workspace.workflow.summary.wait_state ?? "none"}`,
              )}</p>`
            : ""
        }
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
      <article class="panel">
        <h3>Evidence</h3>
        ${renderEvidence(workspace)}
      </article>
      <article class="panel">
        <h3>Candidates</h3>
        ${renderCandidates(workspace)}
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
