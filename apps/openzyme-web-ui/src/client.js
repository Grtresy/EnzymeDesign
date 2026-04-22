const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
};

const v3EventTypes = [
  "session.created",
  "conversation.user_message",
  "conversation.assistant_message",
  "inbox.delivered",
  "agent.message.delivered",
  "background.completed",
  "message.received",
  "message.sent",
  "tool.invoked",
  "tool.completed",
  "task.created",
  "task.updated",
  "lane.created",
  "lane.claimed",
  "lane.released",
  "lane.removed",
  "approval.requested",
  "approval.resolved",
  "engine.invocation.started",
  "engine.invocation.updated",
  "engine.invocation.completed",
  "artifact.recorded",
  "report.generated",
];

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

  createV3Session(payload) {
    return requestJson(this.baseUrl, "/v3/sessions", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  }

  getV3Session(sessionId) {
    return requestJson(this.baseUrl, `/v3/sessions/${sessionId}`);
  }

  postV3Message(sessionId, payload) {
    return requestJson(this.baseUrl, `/v3/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  }

  resolveV3Approval(approvalId, payload) {
    return requestJson(this.baseUrl, `/v3/approvals/${approvalId}/resolve`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  }

  streamV3Session(sessionId, onEvent) {
    const source = new EventSource(buildUrl(this.baseUrl, `/v3/sessions/${sessionId}/events?replay=1&follow=1`));
    for (const eventType of v3EventTypes) {
      source.addEventListener(eventType, (message) => {
        onEvent(JSON.parse(message.data));
      });
    }
    return source;
  }
}

export function buildHostPaths(projectId, sessionId) {
  return {
    v3ProjectSessions: `/v3/projects/${projectId}/sessions`,
    v3CreateSession: "/v3/sessions",
    v3Session: `/v3/sessions/${sessionId}`,
    v3Messages: `/v3/sessions/${sessionId}/messages`,
    v3Events: `/v3/sessions/${sessionId}/events?replay=1&follow=1`,
    v3ApprovalResolve: "/v3/approvals/appr_001/resolve",
  };
}
