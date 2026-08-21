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
    ${renderRecords("Workspace generations", workspace.generations, ["workspace_id"])}
    ${renderRecords("Workspace runtime bindings", workspace.runtime_bindings, ["workspace_id"])}
    ${renderRecords("Verified checkpoints", workspace.checkpoints, ["checkpoint_id"])}
    ${renderRecords("Revision/path verifications", workspace.revision_path_verifications, ["verification_id"])}
    ${renderRecords("Immutable publications", core.publications, ["publication_ref", "publication_id"])}
  </div>`;
}

export function renderCoreRuntime(shell) {
  return `<div class="stack">
    ${renderRecords("Runtime signals", shell.core.runtime.signals, ["signal_id"])}
    ${renderRecords("Runtime turn commands", shell.core.runtime.turn_commands, ["command_id"])}
    ${renderRecords("Controlled operations", shell.core.operations.controlled, ["operation_id"])}
    ${renderRecords("Continuations", shell.core.operations.continuations, ["continuation_id"])}
    ${renderRecords("Failure observations", shell.core.failures.observations, ["failure_id", "diagnostic_id"])}
  </div>`;
}

export function renderToolAffordances(shell) {
  const affordances = shell.toolAffordances;
  if (!affordances.length) return `<p class="empty-copy">No declared tool affordances.</p>`;
  return `<ol class="record-list">${affordances.map((item) => {
    const blockers = item.blockers.map((blocker) => blocker.code).join(", ") || "none";
    return `<li><strong>${escapeHtml(item.tool_name)}</strong><span>${escapeHtml(item.state)}</span><small>routes ${escapeHtml(item.route_ids.join(", ") || "none")} · blockers ${escapeHtml(blockers)}</small></li>`;
  }).join("")}</ol>`;
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
    "Conversation",
    shell.core.conversation.messages,
    ["message_id", "event_id"],
  );
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
  const mutationDisabled = !shell.mutationAllowed || state.messageBusy || state.drainBusy;
  return `<main class="app-shell chat-workspace">
    <header class="conversation-header">
      <div><p class="eyebrow">OpenZyme Kernel workspace</p><h1>${escapeHtml(session.title ?? session.session_id)}</h1><p>${escapeHtml(session.objective ?? "")}</p></div>
      <dl class="facts compact-facts"><div><dt>Session</dt><dd>${escapeHtml(session.session_id)}</dd></div><div><dt>Schema</dt><dd>${escapeHtml(shell.schemaVersion)}</dd></div><div><dt>Release</dt><dd>${escapeHtml(shortDigest(shell.release.release_digest))}</dd></div><div><dt>Binding</dt><dd>${escapeHtml(shortDigest(shell.core.capability_binding.binding_digest))}</dd></div></dl>
    </header>
    ${state.mutationError ? `<div class="error-banner" role="alert">${escapeHtml(state.mutationError)}</div>` : ""}
    <section class="conversation-panel">${renderConversation(shell)}</section>
    <form id="message-form" class="composer-panel" autocomplete="off">
      <textarea name="message" rows="3" placeholder="Message OpenZyme" required ${mutationDisabled ? "disabled" : ""}></textarea>
      <button type="submit" ${mutationDisabled ? "disabled" : ""}>Send</button>
    </form>
    <section class="action-row"><button type="button" data-action="runtime-drain" ${mutationDisabled ? "disabled" : ""}>Run bounded runtime drain</button><button type="button" data-action="refresh" ${state.refreshing ? "disabled" : ""}>Refresh</button></section>
    <section><h2>Kernel task and authority truth</h2>
      ${renderRecords("Tasks", shell.core.tasks, ["task_id"])}
      ${renderRecords("Agents", shell.core.agents, ["agent_member_id", "agent_id"])}
      ${renderRecords("Approvals", shell.core.approvals, ["approval_id"])}
      ${renderRecords("Authority leases", shell.core.authority_leases, ["lease_id"])}
    </section>
    <section><h2>Workspace and publication truth</h2>${renderCoreWorkspace(shell)}</section>
    <section><h2>Runtime, operation and failure truth</h2>${renderCoreRuntime(shell)}</section>
    <section><h2>Effective tool affordances</h2>${renderToolAffordances(shell)}</section>
    ${renderExtensionSections(shell)}
  </main>`;
}
