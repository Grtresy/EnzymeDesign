import { buildInitialViewState, reduceWorkspaceWithEvent } from "./state.js";

export class WorkspaceController {
  constructor(client, onChange = () => {}) {
    this.client = client;
    this.onChange = onChange;
    this.state = buildInitialViewState();
    this.stream = null;
  }

  snapshot() {
    return structuredClone(this.state);
  }

  _emit() {
    this.onChange(this.snapshot());
  }

  _disconnectStream() {
    if (this.stream) {
      this.stream.close();
      this.stream = null;
    }
  }

  _connectStream(episodeId) {
    this._disconnectStream();
    this.stream = this.client.streamEpisode(episodeId, (event) => {
      if (!this.state.workspace) {
        return;
      }
      this.state.workspace = reduceWorkspaceWithEvent(this.state.workspace, event);
      this._emit();
    });
  }

  async bootstrap({ projectId = "", episodeId = "" } = {}) {
    this.state.busy = true;
    this._emit();
    try {
      this.state.projects = await this.client.getProjects();
      this.state.currentProjectId = projectId || this.state.projects[0]?.project_id || "";
      if (!this.state.currentProjectId) {
        this.state.episodes = [];
        this.state.currentEpisodeId = "";
        this.state.workspace = null;
        this._disconnectStream();
        this.state.errorMessage = "";
        return;
      }
      await this._loadProjectEpisodes(this.state.currentProjectId, {
        preferredEpisodeId: episodeId,
        connectStream: true,
      });
      this.state.errorMessage = "";
    } catch (error) {
      this.state.errorMessage = error.message;
    } finally {
      this.state.busy = false;
      this._emit();
    }
  }

  async _loadProjectEpisodes(projectId, { preferredEpisodeId = "", connectStream = false } = {}) {
    this.state.episodes = await this.client.getProjectEpisodes(projectId);
    this.state.currentEpisodeId = preferredEpisodeId || this.state.episodes.at(-1)?.episode_id || "";
    if (!this.state.currentEpisodeId) {
      this.state.workspace = null;
      this._disconnectStream();
      return;
    }
    this.state.workspace = await this.client.getWorkspace(this.state.currentEpisodeId);
    if (connectStream) {
      this._connectStream(this.state.currentEpisodeId);
    }
  }

  async selectProject(projectId) {
    this.state.busy = true;
    this._emit();
    try {
      this.state.currentProjectId = projectId;
      await this._loadProjectEpisodes(projectId, { connectStream: true });
      this.state.errorMessage = "";
    } catch (error) {
      this.state.errorMessage = error.message;
    } finally {
      this.state.busy = false;
      this._emit();
    }
  }

  async selectEpisode(episodeId) {
    this.state.busy = true;
    this._emit();
    try {
      this.state.currentEpisodeId = episodeId;
      this.state.workspace = await this.client.getWorkspace(episodeId);
      this._connectStream(episodeId);
      this.state.errorMessage = "";
    } catch (error) {
      this.state.errorMessage = error.message;
    } finally {
      this.state.busy = false;
      this._emit();
    }
  }

  async createEpisode(payload) {
    this.state.busy = true;
    this._emit();
    try {
      const response = await this.client.createEpisode({
        ...payload,
        project_id: payload.project_id || this.state.currentProjectId,
      });
      this.state.workspace = response.workspace;
      this.state.currentEpisodeId = response.episode_id;
      this.state.currentProjectId = response.workspace.workflow.project_id;
      this.state.episodes = await this.client.getProjectEpisodes(this.state.currentProjectId);
      this.state.errorMessage = "";
      this._connectStream(response.episode_id);
    } catch (error) {
      this.state.errorMessage = error.message;
    } finally {
      this.state.busy = false;
      this._emit();
    }
  }

  async resumeEpisode(resumePayload = { approved: true }) {
    const response = await this.client.resumeEpisode({
      episode_id: this.state.currentEpisodeId,
      resume_payload: resumePayload,
    });
    this.state.workspace = response.workspace;
    this._emit();
  }

  async resolveApproval(decision) {
    const approvalId = this.state.workspace?.workflow?.pending_approval?.approval_id;
    const response = await this.client.resolveApproval({
      episode_id: this.state.currentEpisodeId,
      approval_id: approvalId,
      decision,
    });
    this.state.workspace = response.workspace;
    this._emit();
  }
}
