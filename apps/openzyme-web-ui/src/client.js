import { requireFileWorkspaceProjection } from "./file_workspace_state.js";
import { FILE_WORKSPACE_RELEASE } from "./file_workspace_release.js";

const jsonHeaders = {
  Accept: FILE_WORKSPACE_RELEASE.mediaType,
  "Content-Type": "application/json",
  "OpenZyme-Workspace-Contract": FILE_WORKSPACE_RELEASE.schemaVersion,
  "OpenZyme-Tool-Catalog-Digest": FILE_WORKSPACE_RELEASE.toolCatalogDigest,
  "OpenZyme-Schema-Bundle-Digest": FILE_WORKSPACE_RELEASE.schemaBundleDigest,
  "OpenZyme-Client-Kind": "web-ui",
  "OpenZyme-Client-Build-Digest": FILE_WORKSPACE_RELEASE.uiBuildDigest,
};

function commandHeaders() {
  const key = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return { ...jsonHeaders, "Idempotency-Key": `web-${key}` };
}

function buildUrl(baseUrl, path) {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

async function requestJson(baseUrl, path, options = {}) {
  const response = await fetch(buildUrl(baseUrl, path), {
    ...options,
    headers: { ...jsonHeaders, ...(options.headers ?? {}) },
  });
  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try {
      const parsed = JSON.parse(raw);
      detail = parsed.detail ?? parsed.error?.message ?? raw;
    } catch {
      detail = raw;
    }
    throw new Error(detail || `Request failed with status ${response.status}`);
  }
  return response.json();
}

export class HostApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  listV3Sessions(projectId) {
    return requestJson(this.baseUrl, `/v3/projects/${projectId}/sessions`);
  }

  getV3RuntimeHealth() {
    return requestJson(this.baseUrl, "/v3/runtime/health");
  }

  drainV3Runtime(sessionId, payload = {}) {
    return requestJson(this.baseUrl, `/v3/sessions/${sessionId}/runtime/drain`, {
      method: "POST",
      headers: commandHeaders(),
      body: JSON.stringify(payload),
    });
  }

  getV3RuntimeCommand(sessionId, commandId) {
    return requestJson(
      this.baseUrl,
      `/v3/sessions/${sessionId}/runtime/commands/${commandId}`,
    );
  }

  createV3Session(payload) {
    return requestJson(this.baseUrl, "/v3/sessions", {
      method: "POST",
      headers: commandHeaders(),
      body: JSON.stringify(payload),
    }).then((response) => this._requireWorkspaceResponse(response));
  }

  getV3Session(sessionId, options = {}) {
    return requestJson(this.baseUrl, `/v3/sessions/${sessionId}`, options)
      .then((response) => this._requireWorkspaceResponse(response));
  }

  postV3Message(sessionId, payload) {
    return requestJson(this.baseUrl, `/v3/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: commandHeaders(),
      body: JSON.stringify(payload),
    }).then((response) => this._requireWorkspaceResponse(response));
  }

  resolveV3Approval(approvalId, payload) {
    return requestJson(this.baseUrl, `/v3/approvals/${approvalId}/resolve`, {
      method: "POST",
      headers: commandHeaders(),
      body: JSON.stringify(payload),
    }).then((response) => this._requireWorkspaceResponse(response));
  }

  listLlmDebugCalls(params = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && String(value).trim() !== "") {
        query.set(key, String(value));
      }
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return requestJson(this.baseUrl, `/debug/llm-calls${suffix}`);
  }

  getLlmDebugCall(debugId) {
    return requestJson(this.baseUrl, `/debug/llm-calls/${debugId}`);
  }

  clearLlmDebugCalls() {
    return requestJson(this.baseUrl, "/debug/llm-calls/clear", {
      method: "POST",
      headers: commandHeaders(),
    });
  }

  streamV3Session(sessionId, onEvent) {
    const query = new URLSearchParams({
      replay: "1",
      follow: "1",
      envelope: "1",
      workspace_contract: FILE_WORKSPACE_RELEASE.schemaVersion,
      tool_catalog_digest: FILE_WORKSPACE_RELEASE.toolCatalogDigest,
      schema_bundle_digest: FILE_WORKSPACE_RELEASE.schemaBundleDigest,
      client_kind: "web-ui",
      client_build_digest: FILE_WORKSPACE_RELEASE.uiBuildDigest,
    });
    const source = new EventSource(
      buildUrl(this.baseUrl, `/v3/sessions/${sessionId}/events?${query.toString()}`),
    );
    source.addEventListener("openzyme.event", (message) => {
      const event = JSON.parse(message.data);
      if (event.schema_version !== FILE_WORKSPACE_RELEASE.schemaVersion) {
        onEvent({
          schema_version: event.schema_version,
          event_id: event.event_id,
        });
        source.close();
        return;
      }
      onEvent(event);
    });
    return source;
  }

  _requireWorkspaceResponse(response) {
    if (!response?.workspace) {
      throw new Error("file-workspace response is missing workspace state");
    }
    return {
      ...response,
      workspace: requireFileWorkspaceProjection(response.workspace, {
        toolCatalogDigest: FILE_WORKSPACE_RELEASE.toolCatalogDigest,
        schemaBundleDigest: FILE_WORKSPACE_RELEASE.schemaBundleDigest,
      }),
    };
  }
}

export function buildHostPaths(projectId, sessionId) {
  return {
    v3ProjectSessions: `/v3/projects/${projectId}/sessions`,
    v3RuntimeHealth: "/v3/runtime/health",
    v3RuntimeDrain: `/v3/sessions/${sessionId}/runtime/drain`,
    v3RuntimeCommand: `/v3/sessions/${sessionId}/runtime/commands/runtime_command_001`,
    v3CreateSession: "/v3/sessions",
    v3Session: `/v3/sessions/${sessionId}`,
    v3Messages: `/v3/sessions/${sessionId}/messages`,
    v3Events: `/v3/sessions/${sessionId}/events?replay=1&follow=1&envelope=1`,
    v3ApprovalResolve: "/v3/approvals/appr_001/resolve",
    debugLlmCalls: "/debug/llm-calls",
    debugLlmCall: "/debug/llm-calls/llmdbg_001",
    debugLlmClear: "/debug/llm-calls/clear",
  };
}
