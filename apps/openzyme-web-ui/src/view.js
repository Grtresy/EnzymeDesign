function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

const PHASE_ORDER = ["intake", "design", "report_review"];

function buildPhaseStatusMap(workspace) {
  const currentPhase = workspace.workflow.current_phase;
  const currentIndex = PHASE_ORDER.indexOf(currentPhase);
  return PHASE_ORDER.map((phase, index) => {
    let status = "upcoming";
    if (currentIndex === -1) {
      status = phase === currentPhase ? "active" : "upcoming";
    } else if (index < currentIndex) {
      status = "completed";
    } else if (index === currentIndex) {
      status = "active";
    }
    return { phase, status };
  });
}

function renderPhaseRail(workspace) {
  const items = buildPhaseStatusMap(workspace)
    .map(
      ({ phase, status }) => `
        <li class="phase-pill phase-pill-${escapeHtml(status)}">
          <span>${escapeHtml(phase)}</span>
          <small>${escapeHtml(status)}</small>
        </li>
      `,
    )
    .join("");
  return `
    <div class="stack">
      <p class="helper-copy">Create Episode will auto-run the workflow until the next approval gate. Completed phases stay visible here so the flow does not look skipped.</p>
      <ul class="phase-rail">${items}</ul>
    </div>
  `;
}

function renderProjectShell(viewState) {
  const projectOptions = viewState.projects.length
    ? viewState.projects
        .map(
          (project) => `
            <option value="${escapeHtml(project.project_id)}" ${project.project_id === viewState.currentProjectId ? "selected" : ""}>
              ${escapeHtml(project.name)}
            </option>
          `,
        )
        .join("")
    : '<option value="">No projects loaded</option>';

  const episodeItems = viewState.episodes.length
    ? viewState.episodes
        .map(
          (episode) => `
            <button
              type="button"
              class="episode-chip ${episode.episode_id === viewState.currentEpisodeId ? "is-active" : ""}"
              data-episode-id="${escapeHtml(episode.episode_id)}"
            >
              <span>${escapeHtml(episode.objective)}</span>
              <small>${escapeHtml(episode.status)}</small>
            </button>
          `,
        )
        .join("")
    : '<p class="empty-state">No persisted episodes yet for this project.</p>';

  return `
    <aside class="panel shell-panel">
      <div class="shell-block">
        <p class="eyebrow">Project Shell</p>
        <label>
          Active Project
          <select id="project-select">${projectOptions}</select>
        </label>
      </div>
      <div class="shell-block">
        <div class="shell-heading">
          <h3>Episodes</h3>
          <span>${escapeHtml(String(viewState.episodes.length))}</span>
        </div>
        <div class="episode-list">${episodeItems}</div>
      </div>
    </aside>
  `;
}

function renderPendingApproval(workspace) {
  const approval = workspace.workflow.pending_approval;
  const interrupt = workspace.workflow.pending_interrupt;
  if (!approval && !interrupt) {
    return '<p class="empty-state">No pending approval or interrupt.</p>';
  }
  const interruptQuestion = interrupt?.details?.question
    ? `<p><strong>Question:</strong> ${escapeHtml(interrupt.details.question)}</p>`
    : "";
  return `
    <div class="callout">
      <p><strong>Pending approval:</strong> ${escapeHtml(approval?.requested_action ?? "None")}</p>
      <p><strong>Interrupt type:</strong> ${escapeHtml(interrupt?.type ?? "none")}</p>
      ${interruptQuestion}
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
  const research = workspace.research ?? {
    status: "idle",
    completion_reason: null,
    clarification_question: null,
    evidence: [],
    unresolved_gaps: [],
    summary: null,
    turns: [],
  };
  if (!research.evidence.length && !research.summary) {
    return `
      <div class="stack">
        <p class="empty-state">No research evidence loaded yet.</p>
        <p><strong>Status:</strong> ${escapeHtml(research.status ?? "idle")}</p>
        ${research.clarification_question ? `<p><strong>Clarification:</strong> ${escapeHtml(research.clarification_question)}</p>` : ""}
      </div>
    `;
  }
  return `
    <div class="stack">
      <p><strong>Status:</strong> ${escapeHtml(research.status ?? "completed")}</p>
      ${research.completion_reason ? `<p><strong>Completion reason:</strong> ${escapeHtml(research.completion_reason)}</p>` : ""}
      ${research.clarification_question ? `<p><strong>Clarification:</strong> ${escapeHtml(research.clarification_question)}</p>` : ""}
      ${research.summary ? `<p><strong>Summary:</strong> ${escapeHtml(research.summary.summary)}</p>` : ""}
      <ul class="data-list">
        ${research.evidence
          .map(
            (evidence) => `
              <li>
                <span>${escapeHtml(evidence.evidence_id)}</span>
                <span>${escapeHtml(evidence.summary)}</span>
                <span>${escapeHtml(evidence.query)}</span>
                <span>${escapeHtml((evidence.source_refs ?? []).map((source) => source.locator).join(" | ") || "no sources")}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
      ${
        research.turns?.length
          ? `
            <div class="stack">
              <p><strong>Recent research turns:</strong></p>
              <ul class="data-list">
                ${research.turns
                  .slice(-5)
                  .map(
                    (turn) => `
                      <li>
                        <span>${escapeHtml(`#${turn.turn_index}`)}</span>
                        <span>${escapeHtml(turn.action_kind)}</span>
                        <span>${escapeHtml(turn.status)}</span>
                      </li>
                    `,
                  )
                  .join("")}
              </ul>
            </div>
          `
          : ""
      }
      ${
        research.unresolved_gaps.length
          ? `<p><strong>Open gaps:</strong> ${escapeHtml(research.unresolved_gaps.map((gap) => gap.summary).join(" | "))}</p>`
          : ""
      }
    </div>
  `;
}

function renderDesignWorkspace(workspace) {
  const design = workspace.design ?? { artifacts: [], focused_artifact_ids: [], turns: [] };
  if (!design.artifacts.length) {
    return '<p class="empty-state">No design artifacts available yet.</p>';
  }
  return `
    <div class="stack">
      <p><strong>Focused artifacts:</strong> ${escapeHtml((design.focused_artifact_ids ?? []).join(" | ") || "none")}</p>
      <ul class="data-list">
        ${design.artifacts
          .map(
            (artifact) => `
              <li>
                <span>${escapeHtml(artifact.artifact_id)}</span>
                <span>${escapeHtml(artifact.title ?? artifact.kind)}</span>
                <span>${escapeHtml((artifact.tags ?? []).join(", ") || "n/a")}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
      ${
        design.turns?.length
          ? `
            <div class="stack">
              <p><strong>Recent turns:</strong></p>
              <ul class="data-list">
                ${design.turns
                  .slice(-5)
                  .map(
                    (turn) => `
                      <li>
                        <span>${escapeHtml(`#${turn.turn_index}`)}</span>
                        <span>${escapeHtml(turn.action_kind)}</span>
                        <span>${escapeHtml(turn.status)}</span>
                      </li>
                    `,
                  )
                  .join("")}
              </ul>
            </div>
          `
          : ""
      }
    </div>
  `;
}

function renderOperatorPane(workspace) {
  const approval = workspace.workflow.pending_approval;
  return `
    <div class="stack">
      <p><strong>Next action:</strong> ${escapeHtml(workspace.workflow.progress.message ?? "No pending operator action")}</p>
      <p><strong>Wait state:</strong> ${escapeHtml(workspace.workflow.summary?.wait_state ?? "none")}</p>
      ${
        approval
          ? `<p><strong>Why you are here:</strong> Create Episode already finished the earlier phases and paused at the first approval gate: ${escapeHtml(approval.requested_action)}.</p>`
          : ""
      }
      ${renderPendingApproval(workspace)}
    </div>
  `;
}

function renderReport(workspace) {
  if (!workspace.report) {
    return '<p class="empty-state">Final report is not available yet.</p>';
  }
  return `
    <div class="stack report-stack">
      <p><strong>${escapeHtml(workspace.report.title)}</strong></p>
      <p>${escapeHtml(workspace.report.summary)}</p>
      <p><strong>Stage summary:</strong> ${escapeHtml(workspace.report.stage_summary)}</p>
      <dl class="facts">
        <div><dt>Status</dt><dd>${escapeHtml(workspace.report.status)}</dd></div>
        <div><dt>Artifact</dt><dd>${escapeHtml(workspace.report.artifact_id ?? "none")}</dd></div>
        <div><dt>URI</dt><dd>${escapeHtml(workspace.report.artifact_storage_uri ?? "n/a")}</dd></div>
      </dl>
    </div>
  `;
}

function renderV3TaskBoard(workspace) {
  const items = workspace.task_board?.items ?? [];
  if (!items.length) {
    return `<p class="empty-copy">No tasks yet.</p>`;
  }
  return `
    <ul class="record-list">
      ${items
        .map((item) => {
          const task = item.task;
          return `<li><strong>${escapeHtml(task.subject)}</strong><span>${escapeHtml(task.task_id)} · ${escapeHtml(task.status)} · ${escapeHtml(item.bucket)}</span></li>`;
        })
        .join("")}
    </ul>
  `;
}

function renderV3Lanes(workspace) {
  const lanes = workspace.lane_board?.lanes ?? [];
  if (!lanes.length) {
    return `<p class="empty-copy">No lanes yet.</p>`;
  }
  return `
    <ul class="record-list">
      ${lanes
        .map((item) => {
          const lane = item.lane;
          return `<li><strong>${escapeHtml(lane.name)}</strong><span>${escapeHtml(lane.lane_id)} · ${escapeHtml(lane.status)} · ${escapeHtml(lane.cwd)}</span></li>`;
        })
        .join("")}
    </ul>
  `;
}

function renderV3Conversation(workspace) {
  const conversation = workspace.conversation ?? [];
  if (!conversation.length) {
    return `<p class="empty-copy">Start the session with a message.</p>`;
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

function renderV3Activity(workspace) {
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

function renderV3Workspace(workspace, viewState) {
  const session = workspace.session;
  const reports = workspace.reports ?? [];
  const artifacts = workspace.artifacts ?? [];
  return `
    <section class="workspace-board v3-workspace">
      <article class="panel hero-panel chat-hero">
        <p class="eyebrow">Session ${escapeHtml(session.session_id)}</p>
        <h2>${escapeHtml(session.objective)}</h2>
        <p class="status-line">Status: <strong>${escapeHtml(session.status)}</strong></p>
      </article>
      <article class="panel pane chat-pane">
        <h3>Conversation</h3>
        ${renderV3Conversation(workspace)}
        <form id="message-form" class="message-form">
          <input name="message" placeholder="Send a message to the harness" ${viewState.busy ? "disabled" : ""} required />
          <button type="submit" ${viewState.busy ? "disabled" : ""}>Send</button>
        </form>
      </article>
      <article class="panel pane task-pane">
        <h3>Task Board</h3>
        ${renderV3TaskBoard(workspace)}
      </article>
      <article class="panel pane lane-pane">
        <h3>Lanes</h3>
        ${renderV3Lanes(workspace)}
      </article>
      <article class="panel pane activity-pane">
        <h3>Activity</h3>
        ${renderV3Activity(workspace)}
      </article>
      <article class="panel pane report-pane">
        <h3>Outputs</h3>
        <dl class="facts">
          <div><dt>Artifacts</dt><dd>${artifacts.length}</dd></div>
          <div><dt>Reports</dt><dd>${reports.length}</dd></div>
          <div><dt>Capabilities</dt><dd>${Object.keys(workspace.capabilities ?? {}).length}</dd></div>
        </dl>
      </article>
    </section>
  `;
}

export function renderWorkspaceShell(viewState) {
  const workspace = viewState.workspace;
  const workspaceBody =
    workspace === null
      ? `
        <section class="workspace-board">
          <article class="panel intro-panel">
            <p class="eyebrow">Workspace</p>
            <h2>Select an Episode or Create a New One</h2>
            <p>Use the project shell to inspect persisted episodes, or start a new routed workflow that will move through intake, design, and report review.</p>
          </article>
        </section>
      `
      : workspace.session
        ? renderV3Workspace(workspace, viewState)
        : `
        <section class="workspace-board">
          <article class="panel hero-panel">
            <p class="eyebrow">Episode ${escapeHtml(workspace.episode_id)}</p>
            <h2>${escapeHtml(workspace.workflow.objective)}</h2>
            <p class="status-line">Phase: <strong>${escapeHtml(workspace.workflow.current_phase)}</strong> · Status: <strong>${escapeHtml(workspace.workflow.episode_status)}</strong></p>
            <p>${escapeHtml(workspace.workflow.progress.message ?? "No progress message")}</p>
            ${
              workspace.workflow.summary
                ? `<p><strong>Summary:</strong> ${escapeHtml(
                    `Evidence ${workspace.workflow.summary.evidence_count}, artifacts ${workspace.workflow.summary.artifact_count}, report ${workspace.workflow.summary.report_status ?? "pending"}`,
                  )}</p>`
                : ""
            }
            ${renderPhaseRail(workspace)}
            <div class="action-row">
              <button type="button" data-action="resume">Resume Episode</button>
            </div>
          </article>
          <article class="panel pane workflow-pane">
            <h3>Workflow</h3>
            <p class="helper-copy">The current node is the place where the workflow paused, not the whole history. Use the phase rail and panes below to inspect the current design context, runs, and final report.</p>
            <dl class="facts">
              <div><dt>Active node</dt><dd>${escapeHtml(workspace.workflow.progress.active_node)}</dd></div>
              <div><dt>Progress status</dt><dd>${escapeHtml(workspace.workflow.progress.status)}</dd></div>
              <div><dt>Updated at</dt><dd>${escapeHtml(workspace.workflow.progress.updated_at)}</dd></div>
              <div><dt>Report status</dt><dd>${escapeHtml(workspace.workflow.summary?.report_status ?? "pending")}</dd></div>
            </dl>
          </article>
          <article class="panel pane operator-pane">
            <h3>Operator</h3>
            ${renderOperatorPane(workspace)}
          </article>
          <article class="panel pane evidence-pane">
            <h3>Evidence And Runs</h3>
            <div class="stack">
              <section>
                <h4>Evidence</h4>
                ${renderEvidence(workspace)}
              </section>
              <section>
                <h4>Runs</h4>
                ${renderRuns(workspace)}
              </section>
              <section>
                <h4>Artifacts</h4>
                ${renderArtifacts(workspace)}
              </section>
              <section>
                <h4>Design Workspace</h4>
                ${renderDesignWorkspace(workspace)}
              </section>
            </div>
          </article>
          <article class="panel pane report-pane">
            <h3>Report</h3>
            ${renderReport(workspace)}
          </article>
        </section>
      `;

  return `
    <section class="workspace-shell">
      ${renderProjectShell(viewState)}
      ${workspaceBody}
    </section>
  `;
}

export function renderApp(viewState) {
  return `
    <section class="panel form-panel">
      <form id="create-episode-form">
        <label>
          Project ID
          <input name="project_id" value="${escapeHtml(viewState.currentProjectId || "proj_001")}" required />
        </label>
        <label>
          Objective
          <input name="objective" value="Plan an enzyme design workflow from a paper" required />
        </label>
        <button type="submit">${viewState.busy ? "Working..." : "Create V3 Session"}</button>
      </form>
      ${viewState.errorMessage ? `<p class="error-banner">${escapeHtml(viewState.errorMessage)}</p>` : ""}
    </section>
    ${renderWorkspaceShell(viewState)}
  `;
}
