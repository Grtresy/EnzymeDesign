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
  outputs: "Artifacts & Reports",
  evidence: "Scientific Evidence",
  attempts: "Scientific Attempts",
  capabilities: "Capabilities",
  failures: "Failures & Recovery",
  activity: "Activity",
};

function renderEmptyConversation(viewState) {
  return `
    <div class="empty-chat" id="conversation-workspace">
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

function digestPrefix(value) {
  const text = String(value ?? "");
  if (!text) {
    return "none";
  }
  return text.length > 22 ? `${text.slice(0, 22)}…` : text;
}

function renderStatusChip(status, label = status) {
  const normalized = String(status ?? "unknown").replaceAll("_", "-");
  return `<span class="evidence-status" data-evidence-status="${escapeHtml(normalized)}">${escapeHtml(label ?? "unknown")}</span>`;
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
            <span>${escapeHtml(artifact.kind ?? "artifact")} · ${escapeHtml(artifactId)}${artifact.version_count > 1 ? ` · ${escapeHtml(artifact.version_count)} versions` : ""}</span>
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
    <div class="approval-stack" aria-label="Pending approvals" aria-live="polite">
      ${approvals
        .map(
          (approval) => {
            const operation = approval.operation ?? {};
            const sandboxRun = approval.sandbox_run ?? {};
            return `
            <article class="approval-card" role="region" aria-label="Approval required">
              <div class="approval-heading">
                <span class="approval-mark" aria-hidden="true">!</span>
                <div><p class="eyebrow">Approval required</p><h3>${escapeHtml(approval.requested_action ?? "Review requested action")}</h3></div>
              </div>
              <dl class="facts compact-facts">
                <div><dt>Approval</dt><dd>${escapeHtml(approval.approval_id)}</dd></div>
                <div><dt>Task</dt><dd>${escapeHtml(approval.task_id ?? "none")}</dd></div>
                <div><dt>Lane</dt><dd>${escapeHtml(approval.lane_id ?? "none")}</dd></div>
                <div><dt>Operation ID</dt><dd>${escapeHtml(operation.operation_id ?? "none")}</dd></div>
                <div><dt>Operation</dt><dd>${escapeHtml(operation.logical_operation_key ?? "none")}</dd></div>
                <div><dt>Identity digest</dt><dd>${escapeHtml(digestPrefix(operation.operation_digest))}</dd></div>
                <div><dt>Route policy</dt><dd>${escapeHtml(operation.route_policy_id ?? "none")}</dd></div>
                <div><dt>Backend</dt><dd>${escapeHtml(operation.selected_backend ?? operation.backend_category ?? "unknown")}</dd></div>
                <div><dt>Run</dt><dd>${escapeHtml(sandboxRun.sandbox_run_id ?? operation.sandbox_run_id ?? "none")}</dd></div>
              </dl>
              ${renderPanelError(viewState.errors.approvals?.[approval.approval_id] ?? "")}
              <div class="action-row approval-actions">
                <button
                  type="button"
                  data-v3-approval-decision="approved"
                  data-approval-id="${escapeHtml(approval.approval_id)}"
                  ${viewState.pendingApprovalId === approval.approval_id ? "disabled" : ""}
                  aria-busy="${viewState.pendingApprovalId === approval.approval_id}"
                >${viewState.pendingApprovalId === approval.approval_id ? "Resolving..." : "Approve"}</button>
                <button
                  type="button"
                  class="button-secondary button-warning"
                  data-v3-approval-decision="rejected"
                  data-approval-id="${escapeHtml(approval.approval_id)}"
                  ${viewState.pendingApprovalId === approval.approval_id ? "disabled" : ""}
                  aria-busy="${viewState.pendingApprovalId === approval.approval_id}"
                >Reject</button>
              </div>
            </article>
          `;
          },
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
        <small>${escapeHtml(step.role ?? "")} · call ${escapeHtml(step.call_index ?? "")}${step.created_at ? ` · ${escapeHtml(step.created_at)}` : ""}</small>
      </div>
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
              <span>${escapeHtml(item.role === "user" ? "You" : "OpenZyme")}${item.created_at ? ` · ${escapeHtml(item.created_at)}` : ""}</span>
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
  const sandboxRuns = workspace.sandbox_runs ?? [];
  if (!entries.length && !sandboxRuns.length) {
    return `<p class="empty-copy">No capability invocations yet.</p>`;
  }
  return `
    <ul class="record-list">
      ${entries
        .map(
          ({ capabilityKey, item }) => `
            <li>
              <strong>${escapeHtml(capabilityKey)}</strong>
              <span>${escapeHtml(item.invocation_id ?? item.operation_id ?? "invocation")} · ${escapeHtml(item.status ?? "unknown")}</span>
              ${
                item.logical_operation_key
                  ? `<small>${escapeHtml(item.logical_operation_key)} · ${escapeHtml(item.selected_backend ?? item.backend_category ?? "backend")} · ${escapeHtml(digestPrefix(item.operation_digest))}</small>`
                  : ""
              }
            </li>
          `,
        )
        .join("")}
      ${sandboxRuns
        .map(
          (run) => `
            <li>
              <strong>sandbox.run</strong>
              <span>${escapeHtml(run.sandbox_run_id ?? "run")} · ${escapeHtml(run.status ?? "unknown")}</span>
              <small>${escapeHtml(run.error_code ?? run.cwd ?? "")}</small>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

export function renderV3Outputs(workspace, viewState = {}) {
  const artifactIndex = workspace.artifact_index ?? [];
  const artifacts = artifactIndex.length
    ? artifactIndex.map((entry) => ({
        ...(entry.latest ?? {}),
        artifact_id: entry.latest_artifact_id ?? entry.latest?.artifact_id,
        relative_path: entry.relative_path,
        version_count: entry.version_count,
        artifact_ids: entry.artifact_ids,
      }))
    : workspace.artifacts ?? [];
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
              <h3>Report Drafts</h3>
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
              <h3>Reports</h3>
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
              <h3>Artifacts</h3>
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

export function renderV3ScientificEvidence(workspace) {
  const evidence = workspace.scientific_evidence ?? {};
  const providers = evidence.providers ?? [];
  const quorum = evidence.quorum ?? {};
  const operations = evidence.operations ?? [];
  const artifacts = evidence.artifacts ?? [];
  const reports = evidence.reports ?? [];
  const citations = evidence.citations ?? [];
  const cutover = evidence.cutover ?? {};
  if (!evidence.active && !operations.length) {
    return `<p class="empty-copy">No cutover evidence has been evaluated for this session.</p>`;
  }
  return `
    <div class="stack evidence-stack" data-cutover-eligible="${cutover.eligible === true}">
      <section class="evidence-overview" aria-label="Cutover eligibility">
        <div>
          <p class="eyebrow">Attempt eligibility</p>
          <h3>${escapeHtml(cutover.status ?? "not_evaluated")}</h3>
        </div>
        ${renderStatusChip(cutover.status, cutover.eligible === true ? "eligible" : "fail-closed")}
        <dl class="facts compact-facts">
          <div><dt>Literature quorum</dt><dd>${escapeHtml(quorum.status ?? "not_evaluated")}</dd></div>
          <div><dt>Scientific outcome</dt><dd>${escapeHtml(evidence.scientific_outcome ?? "unknown")}</dd></div>
          <div><dt>Offline verifier</dt><dd>${escapeHtml(evidence.verifier?.status ?? "missing")}</dd></div>
        </dl>
        ${
          evidence.scientific_outcome === "empty_result"
            ? `<p class="status-line">Healthy empty result: execution may be complete, but no candidate discovery is claimed.</p>`
            : ""
        }
        ${
          (cutover.blocker_codes ?? []).length
            ? `<div class="evidence-blockers" role="status"><strong>Fail-closed blockers</strong><ul>${cutover.blocker_codes.map((code) => `<li>${escapeHtml(code)}</li>`).join("")}</ul></div>`
            : ""
        }
        ${
          (cutover.warning_codes ?? []).length
            ? `<div class="evidence-warnings"><strong>Degradation</strong><ul>${cutover.warning_codes.map((code) => `<li>${escapeHtml(code)}</li>`).join("")}</ul></div>`
            : ""
        }
      </section>
      <section>
        <h3>Provider quorum</h3>
        <ul class="record-list evidence-records">
          ${providers
            .map(
              (provider) => `
                <li>
                  <strong>${escapeHtml(provider.provider ?? "provider")}</strong>
                  <span>${escapeHtml(provider.requirement ?? "unknown")} · ${escapeHtml(provider.outcome ?? "unknown")} · ${escapeHtml(provider.item_count ?? 0)} records</span>
                  <small>request ${escapeHtml(digestPrefix(provider.request_digest))} · response ${escapeHtml(digestPrefix(provider.response_digest))}${provider.error_code ? ` · ${escapeHtml(provider.error_code)}` : ""}</small>
                </li>
              `,
            )
            .join("") || `<li><span>No provider receipts.</span></li>`}
        </ul>
      </section>
      <section>
        <h3>Operation identity & approval continuity</h3>
        <ul class="record-list evidence-records">
          ${operations
            .map(
              (operation) => `
                <li data-operation-id="${escapeHtml(operation.operation_id ?? "")}">
                  <strong>${escapeHtml(operation.logical_operation_key ?? operation.operation_id ?? "operation")}</strong>
                  <span>${escapeHtml(operation.operation_id ?? "none")} · ${escapeHtml(operation.status ?? "unknown")}</span>
                  <small>identity ${escapeHtml(digestPrefix(operation.operation_digest))} · approval ${escapeHtml(operation.approval_id ?? "none")} / ${escapeHtml(operation.approval_state ?? "none")} · ${escapeHtml(operation.route_policy_id ?? "unrouted")} → ${escapeHtml(operation.selected_backend ?? operation.backend_category ?? "unknown")}</small>
                </li>
              `,
            )
            .join("") || `<li><span>No controlled operations.</span></li>`}
        </ul>
      </section>
      <section>
        <h3>Artifacts & report evidence</h3>
        <ul class="record-list evidence-records">
          ${artifacts
            .filter(
              (artifact) =>
                (artifact.cutover_eligible !== null && artifact.cutover_eligible !== undefined)
                || artifact.schema_id
                || artifact.content_digest,
            )
            .map(
              (artifact) => `
                <li>
                  <strong>${escapeHtml(artifact.title ?? artifact.artifact_id ?? "artifact")}</strong>
                  <span>${escapeHtml(artifact.schema_id ?? artifact.kind ?? "artifact")} · eligible ${escapeHtml(artifact.cutover_eligible ?? "unverified")}</span>
                  <small>${escapeHtml(artifact.artifact_id ?? "none")} · ${escapeHtml(digestPrefix(artifact.content_digest ?? artifact.sealed_digest))}</small>
                </li>
              `,
            )
            .join("") || `<li><span>No cutover-scoped artifacts.</span></li>`}
          ${reports
            .map(
              (report) => `
                <li>
                  <strong>${escapeHtml(report.title ?? report.report_id ?? "report")}</strong>
                  <span>${escapeHtml(report.status ?? "unknown")} · published ${escapeHtml(report.published === true)} · eligible ${escapeHtml(report.cutover_eligible === true)}</span>
                  <small>${escapeHtml(report.report_id ?? "none")} · artifact ${escapeHtml(report.artifact_id ?? "none")}</small>
                </li>
              `,
            )
            .join("")}
        </ul>
      </section>
      ${
        citations.length
          ? `<section><h3>Safe citations</h3><ul class="record-list evidence-records">${citations
              .map(
                (citation) => `<li><strong>${escapeHtml(citation.title ?? citation.source_ref_id)}</strong><span>${escapeHtml(citation.provider ?? "provider")} · PMID ${escapeHtml(citation.pmid ?? "none")} · DOI ${escapeHtml(citation.doi ?? "none")}</span><small>${escapeHtml(citation.source_ref_id ?? "none")} · ${escapeHtml(digestPrefix(citation.response_digest))}</small></li>`,
              )
              .join("")}</ul></section>`
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

export function renderV3ScientificAttempts(workspace) {
  const projection = workspace.scientific_attempts ?? {};
  const authorizations = projection.authorizations ?? [];
  const attempts = projection.attempts ?? [];
  if (!authorizations.length && !attempts.length) {
    return `<p class="empty-copy">No scientific attempt authority has been recorded.</p>`;
  }
  return `
    <div class="evidence-layout">
      <section>
        <h3>Attempt authority</h3>
        <ul class="record-list">
          ${authorizations
            .map(
              (authority) => `<li>
                <strong>${escapeHtml(authority.workflow_id ?? "workflow")} ${renderStatusChip(authority.status ?? "unknown")}</strong>
                <span>${escapeHtml(authority.envelope_id ?? "envelope")} · campaign ${escapeHtml(authority.campaign_id ?? "none")}</span>
                <small>attempts ${escapeHtml(authority.attempts?.consumed ?? 0)} / ${escapeHtml(authority.attempts?.max ?? 0)} · remaining ${escapeHtml(authority.attempts?.remaining ?? 0)}</small>
                <small>MICU ${escapeHtml(authority.resources?.micu?.reserved ?? 0)} / ${escapeHtml(authority.resources?.micu?.max ?? 0)} · expires ${escapeHtml(authority.expires_at ?? "none")}</small>
              </li>`,
            )
            .join("") || `<li><span>No durable authorization envelope.</span></li>`}
        </ul>
      </section>
      <section>
        <h3>Attempts and selected chains</h3>
        <ul class="record-list evidence-records">
          ${attempts
            .map((attempt) => {
              const selections = attempt.selections ?? [];
              const selected = selections.find(
                (item) => item.selection_id === attempt.selection_head?.selection_id,
              );
              const dispositions = selected?.dispositions ?? [];
              const adoptions = selected?.adoptions ?? [];
              return `<li>
                <strong>${escapeHtml(attempt.attempt_id ?? "attempt")} ${renderStatusChip(attempt.status ?? "unknown")}</strong>
                <span>${escapeHtml(attempt.scope ?? "scope")} · ordinal ${escapeHtml(attempt.ordinal ?? "none")} · selection ${escapeHtml(attempt.selection_head?.selection_id ?? "none")}</span>
                <small>occurrences ${escapeHtml(selected?.occurrences?.length ?? 0)} · dispositions ${escapeHtml(dispositions.length)} · adopted roles ${escapeHtml(adoptions.map((item) => item.workflow_role).join(", ") || "none")}</small>
                ${
                  dispositions.length
                    ? `<small>Disposition audit: ${escapeHtml(dispositions.map((item) => `${item.operation_id}:${item.kind}`).join(" | "))}</small>`
                    : ""
                }
                <small>closure ${escapeHtml(attempt.closure?.closure_id ?? "not sealed")} · universe ${escapeHtml(digestPrefix(selected?.operation_universe_digest))}</small>
              </li>`;
            })
            .join("") || `<li><span>No attempts consumed from the envelope.</span></li>`}
        </ul>
      </section>
    </div>
  `;
}

export function renderV3Failures(workspace) {
  const failures = workspace.failure_observations ?? [];
  const attention = workspace.runtime_state?.task_attention ?? [];
  if (!failures.length && !attention.length) {
    return `<p class="empty-copy">No structured failure or recovery attention is recorded.</p>`;
  }
  return `
    <div class="evidence-layout">
      ${
        attention.length
          ? `<section><h3>Runtime attention</h3><ul class="record-list">${attention
              .map(
                (item) => `<li><strong>${escapeHtml(item.task_id ?? "session")}</strong><span>${escapeHtml((item.reasons ?? []).join(", ") || "attention required")}</span><small>${escapeHtml((item.failure_observation_ids ?? []).join(", ") || "No linked failure id")}</small></li>`,
              )
              .join("")}</ul></section>`
          : ""
      }
      <section>
        <h3>Failure observations</h3>
        <ul class="record-list">
          ${failures
            .slice()
            .reverse()
            .map((failure) => {
              const likelyCauses = failure.likely_causes ?? [];
              const facts = failure.facts ?? {};
              const factSummary = Object.entries(facts)
                .slice(0, 8)
                .map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`)
                .join(" · ");
              return `<li>
                <strong>${escapeHtml(failure.error_code ?? "runtime_error")} ${renderStatusChip(failure.actor_kind ?? "system")}</strong>
                <span>${escapeHtml(failure.safe_summary ?? "Failure recorded")}</span>
                <small>${escapeHtml(failure.failure_id ?? "unknown")} · recoverability ${escapeHtml(failure.recoverability ?? "unknown")} · effect ${escapeHtml(failure.effect_certainty ?? "unknown")} · retry ${escapeHtml(failure.retry_eligibility ?? "unknown")}</small>
                ${factSummary ? `<small>Harness facts: ${escapeHtml(factSummary)}</small>` : ""}
                ${likelyCauses.length ? `<small>Likely causes: ${escapeHtml(likelyCauses.join(" | "))}</small>` : ""}
                ${
                  failure.agent_hypothesis
                    ? `<small>Agent hypothesis (${escapeHtml(failure.agent_hypothesis_confidence ?? "unspecified")}): ${escapeHtml(failure.agent_hypothesis)}</small>`
                    : ""
                }
                ${failure.safe_hint ? `<small>Recovery boundary: ${escapeHtml(failure.safe_hint)}</small>` : ""}
              </li>`;
            })
            .join("")}
        </ul>
      </section>
    </div>
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
    case "evidence":
      return renderV3ScientificEvidence(workspace);
    case "attempts":
      return renderV3ScientificAttempts(workspace);
    case "capabilities":
      return renderV3Capabilities(workspace);
    case "failures":
      return renderV3Failures(workspace);
    case "activity":
      return renderV3Activity(workspace);
    default:
      return renderSessionFacts(workspace);
  }
}

export function renderSidebarStatus(viewState) {
  const runtime = viewState.runtimeHealth;
  const runtimeStatus = runtime?.status ?? "unknown";
  return `
    <p class="status-line">Project <strong>${escapeHtml(viewState.currentProjectId)}</strong></p>
    <p class="status-line" data-runtime-health="${escapeHtml(runtimeStatus)}">
      Runtime <strong>${escapeHtml(runtimeStatus)}</strong>
      ${runtime?.deployment_profile ? ` · ${escapeHtml(runtime.deployment_profile)}` : ""}
    </p>
    ${renderPanelError(viewState.errors?.runtimeHealth ?? "")}
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
    <ul class="tree-list">
      ${viewState.sessionSummaries
        .map((session) => {
          const isExpanded = viewState.sidebarExpandedSessionIds.includes(session.session_id);
          const isActive = viewState.currentSessionId === session.session_id;
          const teammates = isActive ? viewState.workspace?.delegation?.agents ?? [] : [];
          return `
            <li class="tree-node session-node">
              <div class="session-row ${isActive ? "is-active" : ""}">
                <button
                  type="button"
                  class="tree-toggle"
                  data-action="toggle-session"
                  data-session-id="${escapeHtml(session.session_id)}"
                  aria-label="${isExpanded ? "Collapse" : "Expand"}"
                  aria-expanded="${isExpanded}"
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
                  ? `<ul class="section-tree">
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
                                  ? `<ul class="teammate-tree">
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
    <div class="conversation-title-block">
      <p class="eyebrow">${escapeHtml(viewState.selectedTeammateAgentId ? "Teammate Trace" : "Conversation")}</p>
      <h2>${escapeHtml(viewState.selectedTeammateAgentId || workspace.session.title || workspace.session.objective)}</h2>
      <p class="status-line">${escapeHtml(workspace.session.objective)}</p>
      <p class="session-meta">${escapeHtml(workspace.session.session_id)}${workspace.session.created_at ? ` · ${escapeHtml(workspace.session.created_at)}` : ""}</p>
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
    <h2>${escapeHtml(sectionLabels[viewState.currentSection] ?? "Conversation")}</h2>
    ${
      viewState.workspace?.session
        ? `<span>${escapeHtml(viewState.workspace.session.session_id)}</span>`
        : `<span>No session</span>`
    }
  `;
}

function renderInspectorTabs(viewState) {
  return `
    <nav class="inspector-tabs" aria-label="Workspace inspector sections">
      ${Object.entries(sectionLabels)
        .filter(([key]) => key !== "conversation")
        .map(([key, label]) => `<button type="button" class="inspector-tab ${viewState.currentSection === key ? "is-current" : ""}" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="${escapeHtml(key)}" aria-pressed="${viewState.currentSection === key}">${escapeHtml(label)}</button>`)
        .join("")}
    </nav>
  `;
}

export function renderSidebar(viewState) {
  return `
    <section class="sidebar-shell">
      <div class="sidebar-panel">
        <p class="brand-wordmark">OpenZyme</p>
        <p class="eyebrow">Research workspace</p>
        <h1>${escapeHtml(viewState.currentProjectId)}</h1>
        <div id="sidebar-status-root">${renderSidebarStatus(viewState)}</div>
        <details class="new-session-disclosure">
          <summary>New session</summary>
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
        </details>
      </div>
      <div class="tree-panel">
        <div class="tree-header">
          <h2>Sessions</h2>
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
      <section class="main-column-shell" id="conversation-workspace" aria-label="Teammate trace workspace">
        <header class="conversation-header" id="conversation-header-root">${renderConversationHeader(viewState)}</header>
        <section class="conversation-panel">
          <div id="conversation-list-root">${renderTeammateTrace(workspace, viewState.selectedTeammateAgentId)}</div>
          <div id="approval-stack-root">${renderV3Approvals(workspace, viewState)}</div>
        </section>
      </section>
    `;
  }
  return `
    <section class="main-column-shell" id="conversation-workspace" aria-label="Conversation workspace">
      <header class="conversation-header" id="conversation-header-root">${renderConversationHeader(viewState)}</header>
      <section class="conversation-panel">
        <div id="conversation-list-root">${renderV3Conversation(workspace)}</div>
        <div id="approval-stack-root">${renderV3Approvals(workspace, viewState)}</div>
      </section>
      <form id="message-form" class="composer-panel" autocomplete="off" aria-label="Message OpenZyme">
        <textarea
          name="message"
          rows="3"
          placeholder="Message OpenZyme"
          aria-label="Message OpenZyme"
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
    <aside class="inspector-panel" aria-label="Workspace inspector">
      <div class="tree-header" id="inspector-header-root">${renderInspectorHeader(viewState)}</div>
      ${renderInspectorTabs(viewState)}
      <div id="inspector-content-root">${renderInspectorContent(viewState)}</div>
    </aside>
  `;
}

function renderRail(viewState) {
  const pending = viewState.workspace?.pending_approvals?.length ?? 0;
  return `
    <nav class="workspace-rail" aria-label="Primary workspace navigation">
      <div class="rail-monogram" aria-label="OpenZyme">OZ</div>
      <button type="button" data-action="select-mobile-pane" data-pane="sessions" aria-label="Sessions" title="Sessions">S</button>
      <button type="button" data-action="select-mobile-pane" data-pane="conversation" aria-label="Conversation" title="Conversation">C</button>
      <button type="button" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="team" aria-label="Team" title="Team">T</button>
      <button type="button" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="tasks" aria-label="Tasks" title="Tasks">✓</button>
      <button type="button" data-action="select-section" data-session-id="${escapeHtml(viewState.currentSessionId)}" data-section="outputs" aria-label="Artifacts and reports" title="Artifacts and reports">A</button>
      ${pending ? `<span class="rail-attention" aria-label="${pending} pending approvals">${pending}</span>` : ""}
    </nav>
  `;
}

function renderMobileNavigation(viewState) {
  return `
    <nav class="mobile-workspace-nav" aria-label="Workspace panels">
      ${[["sessions", "Sessions"], ["conversation", "Conversation"], ["inspector", "Inspector"]]
        .map(([pane, label]) => `<button type="button" data-action="select-mobile-pane" data-pane="${pane}" class="${viewState.mobilePane === pane ? "is-current" : ""}" aria-pressed="${viewState.mobilePane === pane}">${label}</button>`)
        .join("")}
    </nav>
  `;
}

export function renderAppShell(viewState) {
  return `
    <main class="app-shell chat-workspace" data-mobile-pane="${escapeHtml(viewState.mobilePane ?? "conversation")}">
      ${renderRail(viewState)}
      ${renderMobileNavigation(viewState)}
      <section id="sidebar-column-root" aria-label="Sessions">${renderSidebar(viewState)}</section>
      <section id="main-column-root">${renderMainColumn(viewState)}</section>
      <section id="inspector-column-root">${renderInspector(viewState)}</section>
    </main>
  `;
}

export function renderApp(viewState) {
  return renderAppShell(viewState);
}
