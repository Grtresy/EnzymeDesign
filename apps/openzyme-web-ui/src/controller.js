import { buildInitialViewState, reduceWorkspaceWithEvent } from "./state.js";

export class WorkspaceController {
  constructor(client, onChange = () => {}) {
    this.client = client;
    this.onChange = onChange;
    this.state = buildInitialViewState();
    this.stream = null;
    this.requestVersion = 0;
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

  _beginRequest() {
    this.requestVersion += 1;
    return this.requestVersion;
  }

  _isCurrentRequest(version) {
    return version === this.requestVersion;
  }

  _connectV3Stream(sessionId) {
    this._disconnectStream();
    this.stream = this.client.streamV3Session(sessionId, (event) => {
      if (!this.state.workspace?.session || this.state.currentSessionId !== sessionId) {
        return;
      }
      this.state.workspace = reduceWorkspaceWithEvent(this.state.workspace, event);
      this._emit();
    });
  }

  async bootstrap() {
    this._disconnectStream();
    this.state.workspace = null;
    this.state.currentSessionId = "";
    this.state.errorMessage = "";
    this.state.busy = false;
    this._emit();
  }

  async createSession(payload) {
    if (this.state.busy) {
      return;
    }
    const requestVersion = this._beginRequest();
    this.state.busy = true;
    this._emit();
    try {
      const response = await this.client.createV3Session({
        ...payload,
        project_id: payload.project_id || this.state.currentProjectId || "proj_001",
      });
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.workspace = response.workspace;
      this.state.currentSessionId = response.session_id;
      this.state.currentProjectId = response.workspace.session.project_id;
      for (const event of response.events ?? []) {
        this.state.workspace = reduceWorkspaceWithEvent(this.state.workspace, event);
      }
      this.state.errorMessage = "";
      this._connectV3Stream(response.session_id);
    } catch (error) {
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.errorMessage = error.message;
    } finally {
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.busy = false;
      this._emit();
    }
  }

  async sendMessage(message) {
    if (!this.state.currentSessionId || this.state.busy) {
      return;
    }
    this.state.busy = true;
    this._emit();
    try {
      const response = await this.client.postV3Message(this.state.currentSessionId, { message });
      this.state.workspace = response.workspace;
      for (const event of response.events ?? []) {
        this.state.workspace = reduceWorkspaceWithEvent(this.state.workspace, event);
      }
      this.state.errorMessage = "";
    } catch (error) {
      this.state.errorMessage = error.message;
    } finally {
      this.state.busy = false;
      this._emit();
    }
  }

  async resolveApproval(decision) {
    if (!this.state.currentSessionId || !this.state.workspace?.session || this.state.busy) {
      return;
    }
    const approvalId = this.state.workspace.pending_approvals?.[0]?.approval_id;
    if (!approvalId) {
      return;
    }
    this.state.busy = true;
    this._emit();
    try {
      const response = await this.client.resolveV3Approval(approvalId, { decision, actor_ref: "user" });
      this.state.workspace = response.workspace;
      for (const event of response.events ?? []) {
        this.state.workspace = reduceWorkspaceWithEvent(this.state.workspace, event);
      }
      this.state.errorMessage = "";
    } catch (error) {
      this.state.errorMessage = error.message;
    } finally {
      this.state.busy = false;
      this._emit();
    }
  }
}
