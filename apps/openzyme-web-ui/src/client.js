const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
};

const workflowEventTypes = [
  "workflow.phase_changed",
  "workflow.progress_updated",
  "workflow.summary_updated",
  "workflow.interrupt_pending",
  "workflow.approval_pending",
  "workflow.run_status_changed",
  "workflow.artifact_available",
  "workflow.evidence_updated",
  "workflow.design_workspace_updated",
  "workflow.report_available",
];

function buildUrl(baseUrl, path) {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

async function requestJson(baseUrl, path, options = {}) {
  const response = await fetch(buildUrl(baseUrl, path), options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with status ${response.status}`);
  }
  return response.json();
}

export class HostApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  getProjects() {
    return requestJson(this.baseUrl, "/projects");
  }

  getProjectEpisodes(projectId) {
    return requestJson(this.baseUrl, `/projects/${projectId}/episodes`);
  }

  getWorkspace(episodeId) {
    return requestJson(this.baseUrl, `/episodes/${episodeId}/workspace`);
  }

  getWorkflow(episodeId) {
    return requestJson(this.baseUrl, `/episodes/${episodeId}/workflow`);
  }

  getPendingActions(episodeId) {
    return requestJson(this.baseUrl, `/episodes/${episodeId}/pending-actions`);
  }

  getRuns(episodeId) {
    return requestJson(this.baseUrl, `/episodes/${episodeId}/runs`);
  }

  getArtifacts(episodeId) {
    return requestJson(this.baseUrl, `/episodes/${episodeId}/artifacts`);
  }

  getReports(episodeId) {
    return requestJson(this.baseUrl, `/episodes/${episodeId}/reports`);
  }

  createEpisode(payload) {
    return requestJson(this.baseUrl, "/commands/create_episode", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  }

  resumeEpisode(payload) {
    return requestJson(this.baseUrl, "/commands/resume_episode", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  }

  resolveApproval(payload) {
    return requestJson(this.baseUrl, "/commands/resolve_approval", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });
  }

  streamEpisode(episodeId, onEvent) {
    const source = new EventSource(buildUrl(this.baseUrl, `/episodes/${episodeId}/stream?replay=1`));
    for (const eventType of workflowEventTypes) {
      source.addEventListener(eventType, (message) => {
        onEvent(JSON.parse(message.data));
      });
    }
    return source;
  }
}

export function buildHostPaths(episodeId) {
  return {
    projects: "/projects",
    projectEpisodes: "/projects/proj_001/episodes",
    workspace: `/episodes/${episodeId}/workspace`,
    workflow: `/episodes/${episodeId}/workflow`,
    pendingActions: `/episodes/${episodeId}/pending-actions`,
    runs: `/episodes/${episodeId}/runs`,
    artifacts: `/episodes/${episodeId}/artifacts`,
    reports: `/episodes/${episodeId}/reports`,
    stream: `/episodes/${episodeId}/stream?replay=1`,
    createEpisode: "/commands/create_episode",
    resumeEpisode: "/commands/resume_episode",
    resolveApproval: "/commands/resolve_approval",
  };
}
