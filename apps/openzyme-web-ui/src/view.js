function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortDigest(value) {
  const text = String(value ?? "");
  return text.length > 20 ? `${text.slice(0, 18)}…` : text || "none";
}

function renderJsonFact(value) {
  return `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
}

function renderRecords(title, records, identityFields = []) {
  if (!records.length) return `<section><h3>${escapeHtml(title)}</h3><p class="empty-copy">None.</p></section>`;
  return `<section><h3>${escapeHtml(title)}</h3><ol class="record-list">${records.map((record) => {
    const identity = identityFields.map((field) => record[field]).find(Boolean)
      ?? record.schema_version
      ?? "record";
    return `<li><strong>${escapeHtml(identity)}</strong>${renderJsonFact(record)}</li>`;
  }).join("")}</ol></section>`;
}

export function renderCoreWorkspace(shell) {
  const core = shell.core;
  const workspace = core.workspace;
  return `<div class="stack">
    <section><h3>Workspace provisioning</h3>${renderJsonFact(workspace.provisioning)}</section>
    ${renderRecords("Workspace generations", workspace.generations, ["workspace_id"])}
    ${renderRecords("Workspace runtime bindings", workspace.runtime_bindings, ["workspace_id"])}
    ${renderRecords("Verified checkpoints", workspace.checkpoints, ["checkpoint_id"])}
    ${renderRecords("Revision/path verifications", workspace.revision_path_verifications, ["verification_id"])}
    ${renderRecords("Immutable publications", core.publications, ["publication_ref", "publication_id"])}
  </div>`;
}

export function renderCoreRuntime(shell) {
  return `<div class="stack">
    ${renderRecords("Durable runtime commands", shell.core.runtime.commands, ["command_id"])}
    ${renderRecords("Runtime signals", shell.core.runtime.signals, ["signal_id"])}
    ${renderRecords("Runtime turn commands", shell.core.runtime.turn_commands, ["command_id"])}
    ${renderRecords("Runtime outcome receipts", shell.core.runtime.outcomes, ["receipt_id"])}
    ${renderRecords("Runtime outcome consumptions", shell.core.runtime.outcome_consumptions, ["consumption_id"])}
    ${renderRecords("Workflow authority bindings", shell.core.runtime.workflow_authority.bindings, ["authority_id"])}
    ${renderRecords("Signal authority links", shell.core.runtime.workflow_authority.signal_links, ["signal_id"])}
    ${renderRecords("Controlled operations", shell.core.operations.controlled, ["operation_id"])}
    ${renderRecords("Continuations", shell.core.operations.continuations, ["continuation_id"])}
    ${renderRecords("Failure observations", shell.core.failures.observations, ["failure_id", "diagnostic_id"])}
  </div>`;
}

export function renderToolAffordances(shell) {
  const affordances = shell.toolAffordances;
  const exposure = shell.core.tool_reflection.tool_exposure;
  const exposureFacts = `<dl class="facts compact-facts"><div><dt>Direct</dt><dd>${escapeHtml(exposure.direct_tool_names.join(", ") || "none")}</dd></div><div><dt>Deferred</dt><dd>${escapeHtml(exposure.deferred_tool_names.join(", ") || "none")}</dd></div><div><dt>Expansions</dt><dd>${exposure.command_expansions.length}</dd></div></dl>`;
  if (!affordances.length) return `${exposureFacts}<p class="empty-copy">No publicly exposed tool affordances.</p>`;
  return `${exposureFacts}<ol class="record-list">${affordances.map((item) => {
    const blockers = item.blockers.map((blocker) => blocker.code).join(", ") || "none";
    return `<li><strong>${escapeHtml(item.tool_name)}</strong><span>${escapeHtml(item.state)}</span><small>routes ${escapeHtml(item.route_ids.join(", ") || "none")} · blockers ${escapeHtml(blockers)}</small></li>`;
  }).join("")}</ol>`;
}

export function renderProjectionChangeObservations(shell) {
  const records = renderRecords(
    "Verified projection change observations",
    shell.projectionObservations ?? [],
    ["observation_id"],
  );
  return `<p class="status-line">These browser-local observations are derived only after exact Host projection verification; they are not a Host event stream.</p>${records}`;
}

export function renderExtensionSections(shell) {
  const entries = Object.entries(shell.extensionRendering.renderedSections);
  if (!entries.length) return "";
  return `<section><h2>Extension views</h2>${entries.map(([sectionId, rendered]) => (
    `<article><h3>${escapeHtml(sectionId)}</h3>${typeof rendered === "string" ? rendered : renderJsonFact(rendered)}</article>`
  )).join("")}</section>`;
}

function renderConversation(shell) {
  return renderRecords(
    "Ordered user / assistant / tool transcript",
    shell.core.conversation.transcript.messages,
    ["message_id"],
  );
}

function renderApprovals(shell, disabled) {
  if (!shell.core.approvals.length) {
    return `<section><h3>Approvals</h3><p class="empty-copy">None.</p></section>`;
  }
  return `<section><h3>Approvals</h3><ol class="record-list">${shell.core.approvals.map((approval) => {
    const controls = approval.status === "pending"
      ? `<div class="action-row"><button type="button" data-action="approval-decision" data-approval-id="${escapeHtml(approval.approval_id)}" data-decision="approved" ${disabled ? "disabled" : ""}>Approve</button><button type="button" class="button-warning" data-action="approval-decision" data-approval-id="${escapeHtml(approval.approval_id)}" data-decision="rejected" ${disabled ? "disabled" : ""}>Reject</button></div>`
      : "";
    return `<li><strong>${escapeHtml(approval.approval_id)}</strong>${renderJsonFact(approval)}${controls}</li>`;
  }).join("")}</ol></section>`;
}

function renderBlockingState(state) {
  const error = state.error || state.shell?.blockingError || "exact @2 contract is unavailable";
  return `<main class="app-shell"><section class="error-banner" role="alert"><h1>OpenZyme UI is non-operational</h1><p>${escapeHtml(error)}</p><p>No mutation was sent and no legacy fallback was used.</p></section></main>`;
}

export function renderApp(state) {
  if (state.loading && !state.shell) {
    return `<main class="app-shell"><p class="status-line">Loading exact file_workspace_public@2…</p></main>`;
  }
  if (!state.shell || state.error || state.shell.contractBlocked) return renderBlockingState(state);
  const shell = state.shell;
  const session = shell.core.session;
  const readiness = session.resident_readiness;
  const messageDisabled = !shell.messageAllowed || state.messageBusy || state.drainBusy || state.approvalBusy;
  const drainDisabled = !shell.runtimeDrainAllowed || state.messageBusy || state.drainBusy || state.approvalBusy;
  const approvalDisabled = !shell.approvalDecisionAllowed || state.messageBusy || state.drainBusy || state.approvalBusy;
  const pendingSignals = shell.core.runtime.signals.filter((item) => item.status === "pending").length;
  const queuedCopy = pendingSignals
    ? `<p class="status-line">${pendingSignals} signal(s) queued. Runtime has not executed them until an explicit bounded drain command is accepted.</p>`
    : "";
  const provisioning = shell.core.workspace.provisioning;
  const projectionPollingStatus = state.projectionPollingStatus ?? "unknown";
  const blockedCopy = readiness.readiness === "blocked"
    ? `<div class="error-banner" role="alert">Workspace provisioning is blocked. Failure ${escapeHtml(readiness.failure_id)}; code ${escapeHtml(provisioning.error_code)}; diagnostic ${escapeHtml(provisioning.diagnostic_id)}; effect ${escapeHtml(provisioning.effect_certainty)}; mutation ${escapeHtml(provisioning.mutation_applied)}; retry ${escapeHtml(provisioning.retry_permitted)}; reconcile ${escapeHtml(provisioning.reconcile_required)}; next action ${escapeHtml(readiness.next_action)}.</div>`
    : "";
  return `<main class="app-shell chat-workspace">
    <header class="conversation-header">
      <div><p class="eyebrow">OpenZyme Kernel workspace</p><h1>${escapeHtml(session.title ?? session.session_id)}</h1><p>${escapeHtml(session.objective ?? "")}</p></div>
      <dl class="facts compact-facts"><div><dt>Session</dt><dd>${escapeHtml(session.session_id)}</dd></div><div><dt>Resident readiness</dt><dd>${escapeHtml(readiness.readiness)}</dd></div><div><dt>Next action</dt><dd>${escapeHtml(readiness.next_action)}</dd></div><div><dt>Projection polling</dt><dd>${escapeHtml(projectionPollingStatus)}</dd></div><div><dt>Schema</dt><dd>${escapeHtml(shell.schemaVersion)}</dd></div><div><dt>Release</dt><dd>${escapeHtml(shortDigest(shell.release.release_digest))}</dd></div><div><dt>Binding</dt><dd>${escapeHtml(shortDigest(shell.core.capability_binding.binding_digest))}</dd></div></dl>
    </header>
    ${state.mutationError ? `<div class="error-banner" role="alert">${escapeHtml(state.mutationError)}</div>` : ""}
    ${blockedCopy}
    ${readiness.readiness === "provisioning" ? `<p class="status-line">Workspace provisioning is durable and still in progress. Message, runtime and approval commands remain disabled. Next action: ${escapeHtml(readiness.next_action)}.</p>` : ""}
    ${queuedCopy}
    ${state.lastMutationReceipt ? `<section><h2>Latest admission receipt (not workspace truth)</h2>${renderJsonFact(state.lastMutationReceipt)}</section>` : ""}
    ${state.runtimeCommandStatus ? `<section><h2>Polled runtime command</h2>${renderJsonFact(state.runtimeCommandStatus.command)}</section>` : ""}
    <section class="conversation-panel">${renderConversation(shell)}</section>
    <form id="message-form" class="composer-panel" autocomplete="off">
      <textarea name="message" rows="3" placeholder="Message OpenZyme" required ${messageDisabled ? "disabled" : ""}></textarea>
      <input name="workflow_refs" type="text" aria-label="Exact workflow refs" placeholder="Exact workflow refs, sorted and comma-separated; empty selects none" ${messageDisabled ? "disabled" : ""}>
      <button type="submit" ${messageDisabled ? "disabled" : ""}>Send</button>
    </form>
    <section class="action-row"><button type="button" data-action="runtime-drain" ${drainDisabled ? "disabled" : ""}>Run bounded runtime drain</button><button type="button" data-action="refresh" ${state.refreshing ? "disabled" : ""}>Refresh</button></section>
    <section><h2>Kernel task and authority truth</h2>
      ${renderRecords("Tasks", shell.core.tasks, ["task_id"])}
      ${renderRecords("Agents", shell.core.agents, ["agent_member_id", "agent_id"])}
      ${renderRecords("Delegations and protocol", shell.core.protocol.records, ["protocol_ref"])}
      ${renderRecords("Inbox", shell.core.protocol.inbox, ["message_id"])}
      ${renderApprovals(shell, approvalDisabled)}
      ${renderRecords("Authority leases", shell.core.authority_leases, ["lease_id"])}
    </section>
    <section><h2>Workspace and publication truth</h2>${renderCoreWorkspace(shell)}</section>
    <section><h2>Projection change observations</h2>${renderProjectionChangeObservations(shell)}</section>
    <section><h2>Runtime, operation and failure truth</h2>${renderCoreRuntime(shell)}</section>
    <section><h2>Effective tool affordances</h2>${renderToolAffordances(shell)}</section>
    ${renderExtensionSections(shell)}
  </main>`;
}
