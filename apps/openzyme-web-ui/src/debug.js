import { HostApiClient } from "./client.js";

const client = new HostApiClient(window.OPENZYME_HOST_API_BASE ?? "");
const app = document.querySelector("#debug-app");

const state = {
  records: [],
  selected: null,
  loading: false,
  detailLoading: false,
  error: "",
  filters: {
    limit: 100,
    purpose: "",
    kind: "",
    status: "",
    session_id: "",
  },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function prettyJson(value) {
  return escapeHtml(JSON.stringify(value ?? null, null, 2));
}

function formatMeta(record) {
  const context = record.request_context ?? {};
  return [
    record.purpose,
    record.kind,
    record.status,
    context.session_id ? `session ${context.session_id}` : "",
  ].filter(Boolean).join(" · ");
}

function renderRecords() {
  if (state.loading) {
    return `<p class="empty-copy">Loading LLM calls...</p>`;
  }
  if (!state.records.length) {
    return `<p class="empty-copy">No LLM calls captured yet.</p>`;
  }
  return `
    <ol class="debug-list">
      ${state.records.map((record) => `
        <li>
          <button type="button" class="debug-row ${state.selected?.debug_id === record.debug_id ? "is-selected" : ""}" data-debug-id="${escapeHtml(record.debug_id)}">
            <span class="debug-row-title">${escapeHtml(record.purpose)} <small>${escapeHtml(record.status)}</small></span>
            <span class="debug-row-meta">${escapeHtml(formatMeta(record))}</span>
            <span class="debug-row-meta">${escapeHtml(record.created_at)} · ${escapeHtml(record.duration_ms)} ms</span>
          </button>
        </li>
      `).join("")}
    </ol>
  `;
}

function renderDetail() {
  if (state.detailLoading) {
    return `<p class="empty-copy">Loading detail...</p>`;
  }
  if (!state.selected) {
    return `<p class="empty-copy">Select a call to inspect request and response payloads.</p>`;
  }
  const record = state.selected;
  return `
    <section class="debug-detail-header">
      <h2>${escapeHtml(record.purpose)}</h2>
      <p>${escapeHtml(formatMeta(record))}</p>
      <p>${escapeHtml(record.debug_id)} · ${escapeHtml(record.duration_ms)} ms</p>
    </section>
    <section class="debug-json-grid">
      <article>
        <h3>Context</h3>
        <pre>${prettyJson(record.request_context)}</pre>
      </article>
      <article>
        <h3>Request</h3>
        <pre>${prettyJson(record.request)}</pre>
      </article>
      <article>
        <h3>Response</h3>
        <pre>${prettyJson(record.response)}</pre>
      </article>
      <article>
        <h3>Error</h3>
        <pre>${prettyJson(record.error)}</pre>
      </article>
    </section>
  `;
}

function render() {
  app.innerHTML = `
    <header class="debug-header">
      <div>
        <p class="eyebrow">OpenZyme Debug</p>
        <h1>LLM Calls</h1>
      </div>
      <nav>
        <a href="/ui/">Workspace</a>
      </nav>
    </header>
    <form id="debug-filters" class="debug-filters">
      <label>Limit <input name="limit" type="number" min="1" max="500" value="${escapeHtml(state.filters.limit)}" /></label>
      <label>Purpose <input name="purpose" value="${escapeHtml(state.filters.purpose)}" placeholder="v3_harness_loop" /></label>
      <label>Kind
        <select name="kind">
          <option value="">Any</option>
          <option value="tool_calling" ${state.filters.kind === "tool_calling" ? "selected" : ""}>tool_calling</option>
          <option value="structured_output" ${state.filters.kind === "structured_output" ? "selected" : ""}>structured_output</option>
        </select>
      </label>
      <label>Status
        <select name="status">
          <option value="">Any</option>
          <option value="succeeded" ${state.filters.status === "succeeded" ? "selected" : ""}>succeeded</option>
          <option value="error" ${state.filters.status === "error" ? "selected" : ""}>error</option>
        </select>
      </label>
      <label>Session <input name="session_id" value="${escapeHtml(state.filters.session_id)}" /></label>
      <button type="submit">Refresh</button>
      <button type="button" id="debug-clear">Clear</button>
    </form>
    ${state.error ? `<p class="error-copy">${escapeHtml(state.error)}</p>` : ""}
    <section class="debug-layout">
      <aside>${renderRecords()}</aside>
      <main>${renderDetail()}</main>
    </section>
  `;
}

async function loadRecords() {
  state.loading = true;
  state.error = "";
  render();
  try {
    state.records = await client.listLlmDebugCalls(state.filters);
    if (state.selected && !state.records.some((record) => record.debug_id === state.selected.debug_id)) {
      state.selected = null;
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.loading = false;
    render();
  }
}

async function loadDetail(debugId) {
  state.detailLoading = true;
  state.error = "";
  render();
  try {
    state.selected = await client.getLlmDebugCall(debugId);
  } catch (error) {
    state.error = error.message;
  } finally {
    state.detailLoading = false;
    render();
  }
}

app.addEventListener("submit", (event) => {
  if (!(event.target instanceof HTMLFormElement) || event.target.id !== "debug-filters") {
    return;
  }
  event.preventDefault();
  const data = new FormData(event.target);
  state.filters = {
    limit: Number(data.get("limit") || 100),
    purpose: String(data.get("purpose") ?? "").trim(),
    kind: String(data.get("kind") ?? "").trim(),
    status: String(data.get("status") ?? "").trim(),
    session_id: String(data.get("session_id") ?? "").trim(),
  };
  void loadRecords();
});

app.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const row = target.closest("[data-debug-id]");
  if (row instanceof HTMLElement) {
    void loadDetail(row.dataset.debugId);
    return;
  }
  if (target.id === "debug-clear") {
    void client.clearLlmDebugCalls().then(() => {
      state.records = [];
      state.selected = null;
      render();
    }).catch((error) => {
      state.error = error.message;
      render();
    });
  }
});

render();
void loadRecords();
