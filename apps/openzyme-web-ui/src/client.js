const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
};

function commandHeaders() {
  const key = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return { ...jsonHeaders, "Idempotency-Key": `web-${key}` };
}

function buildUrl(baseUrl, path) {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

async function requestJson(baseUrl, path, options = {}) {
  const response = await fetch(buildUrl(baseUrl, path), options);
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

  createV3Session(payload) {
    return requestJson(this.baseUrl, "/v3/sessions", {
      method: "POST",
      headers: commandHeaders(),
      body: JSON.stringify(payload),
    });
  }

  getV3Session(sessionId) {
    return requestJson(this.baseUrl, `/v3/sessions/${sessionId}`);
  }

  postV3Message(sessionId, payload) {
    return requestJson(this.baseUrl, `/v3/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: commandHeaders(),
      body: JSON.stringify(payload),
    });
  }

  resolveV3Approval(approvalId, payload) {
    return requestJson(this.baseUrl, `/v3/approvals/${approvalId}/resolve`, {
      method: "POST",
      headers: commandHeaders(),
      body: JSON.stringify(payload),
    });
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
    const source = new EventSource(
      buildUrl(this.baseUrl, `/v3/sessions/${sessionId}/events?replay=1&follow=1&envelope=1`),
    );
    source.addEventListener("openzyme.event", (message) => {
      onEvent(JSON.parse(message.data));
    });
    return source;
  }
}

export function buildHostPaths(projectId, sessionId) {
  return {
    v3ProjectSessions: `/v3/projects/${projectId}/sessions`,
    v3RuntimeHealth: "/v3/runtime/health",
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
