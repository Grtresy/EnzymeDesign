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

  _connectStream(episodeId) {
    if (this.stream) {
      this.stream.close();
    }
    this.stream = this.client.streamEpisode(episodeId, (event) => {
      if (!this.state.workspace) {
        return;
      }
      this.state.workspace = reduceWorkspaceWithEvent(this.state.workspace, event);
      this._emit();
    });
  }

  async createEpisode(payload) {
    this.state.busy = true;
    this._emit();
    try {
      const response = await this.client.createEpisode(payload);
      this.state.workspace = response.workspace;
      this.state.currentEpisodeId = response.episode_id;
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
