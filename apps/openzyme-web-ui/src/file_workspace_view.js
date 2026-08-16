function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function renderList(items, identity, summary) {
  if (!items.length) {
    return '<p class="empty-copy">No records.</p>';
  }
  return `<ul class="record-list">${items
    .map((item) => `<li><strong>${escapeHtml(identity(item))}</strong><span>${escapeHtml(summary(item))}</span></li>`)
    .join("")}</ul>`;
}

export function renderFileWorkspaceOutputs(workspace) {
  return `
    <section>
      <h3>Published revisions</h3>
      ${renderList(
        workspace.published_revisions,
        (item) => item.publication_id,
        (item) => `${item.commit} · ${item.manifest_digest}`,
      )}
    </section>
    <section>
      <h3>Reports</h3>
      ${renderList(
        workspace.reports,
        (item) => item.title || item.report_id,
        (item) => `${item.status} · ${item.content_ref_id}`,
      )}
    </section>
    <section>
      <h3>Scientific deliverables</h3>
      ${renderList(
        workspace.scientific_deliverables,
        (item) => item.scientific_role,
        (item) => `${item.path} · ${item.content_digest}`,
      )}
    </section>
    <section>
      <h3>External jobs and results</h3>
      ${renderList(
        workspace.external_jobs,
        (item) => item.handle_id,
        (item) => `${item.backend} · ${item.source_commit}`,
      )}
      ${renderList(
        workspace.external_job_results,
        (item) => item.result_id,
        (item) => `${item.terminal_state} · exit ${item.exit_code ?? "none"}`,
      )}
    </section>
  `;
}

export function renderExecutorOwnerWorkspace(view) {
  if (!view) {
    return '<p class="empty-copy">No authorized executor workspace.</p>';
  }
  return `<dl class="facts compact-facts">
    <div><dt>Workspace</dt><dd>${escapeHtml(view.workspace_id)}</dd></div>
    <div><dt>Generation</dt><dd>${escapeHtml(view.workspace_generation)}</dd></div>
    <div><dt>Login</dt><dd>${escapeHtml(view.login_alias)}</dd></div>
    <div><dt>Path</dt><dd>${escapeHtml(view.workspace_path)}</dd></div>
  </dl>`;
}
