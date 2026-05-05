import {
  buildInitialViewState,
  buildSessionSummaryFromWorkspace,
  eventRequiresWorkspaceRefresh,
  reduceWorkspaceWithEvent,
  upsertSessionSummary,
} from "./state.js";

export class WorkspaceController {
  constructor(client, onChange = () => {}) {
    this.client = client;
    this.onChange = onChange;
    this.state = buildInitialViewState();
    this.stream = null;
    this.requestVersion = 0;
    this.messageRequestVersion = 0;
    this.approvalRequestVersion = 0;
    this.refreshRequestVersion = 0;
    this.refreshTimeout = null;
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
    if (this.refreshTimeout) {
      clearTimeout(this.refreshTimeout);
      this.refreshTimeout = null;
    }
  }

  _beginRequest() {
    this.requestVersion += 1;
    return this.requestVersion;
  }

  _isCurrentRequest(version) {
    return version === this.requestVersion;
  }

  _setExpandedSession(sessionId) {
    this.state.sidebarExpandedSessionIds = Array.from(
      new Set([sessionId, ...this.state.sidebarExpandedSessionIds]),
    );
  }

  _syncSummaryFromWorkspace() {
    if (!this.state.workspace?.session) {
      return;
    }
    this.state.sessionSummaries = upsertSessionSummary(
      this.state.sessionSummaries,
      buildSessionSummaryFromWorkspace(this.state.workspace),
    );
  }

  _clearErrors(...keys) {
    for (const key of keys) {
      if (key === "approvals") {
        this.state.errors.approvals = {};
      } else {
        this.state.errors[key] = "";
      }
    }
  }

  _setApprovalError(approvalId, message) {
    this.state.errors.approvals = {
      ...this.state.errors.approvals,
      [approvalId]: message,
    };
  }

  _clearApprovalError(approvalId) {
    const next = { ...this.state.errors.approvals };
    delete next[approvalId];
    this.state.errors.approvals = next;
  }

  _appendOptimisticUserMessage(message) {
    if (!this.state.workspace?.session) {
      return null;
    }
    const optimisticId = `local_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    this.state.workspace = structuredClone(this.state.workspace);
    this.state.workspace.conversation = [
      ...(this.state.workspace.conversation ?? []),
      {
        role: "user",
        content: message,
        event_id: optimisticId,
        pending: true,
      },
    ];
    return optimisticId;
  }

  _appendMessageError(optimisticId, message) {
    if (!this.state.workspace?.session) {
      return;
    }
    this.state.workspace = structuredClone(this.state.workspace);
    this.state.workspace.conversation = [
      ...(this.state.workspace.conversation ?? []),
      {
        role: "assistant",
        content: `Message failed: ${message}`,
        event_id: optimisticId ? `${optimisticId}_error` : `local_error_${Date.now()}`,
        error: true,
      },
    ];
  }

  async _refreshSessionSummaries(projectId = this.state.currentProjectId) {
    this.state.sessionSummaries = await this.client.listV3Sessions(projectId);
  }

  async _refreshCurrentWorkspace(sessionId, version) {
    if (!sessionId || this.state.currentSessionId !== sessionId) {
      return;
    }
    this.state.refreshingWorkspace = true;
    this._emit();
    try {
      const response = await this.client.getV3Session(sessionId);
      if (this.state.currentSessionId !== sessionId || version !== this.refreshRequestVersion) {
        return;
      }
      this.state.workspace = response.workspace;
      this._syncSummaryFromWorkspace();
      this._clearErrors("session");
    } catch (error) {
      if (this.state.currentSessionId !== sessionId || version !== this.refreshRequestVersion) {
        return;
      }
      this.state.errors.session = error.message;
    } finally {
      if (this.state.currentSessionId !== sessionId || version !== this.refreshRequestVersion) {
        return;
      }
      this.state.refreshingWorkspace = false;
      this._emit();
    }
  }

  _scheduleWorkspaceRefresh(sessionId) {
    if (!sessionId || this.state.currentSessionId !== sessionId) {
      return;
    }
    this.refreshRequestVersion += 1;
    const version = this.refreshRequestVersion;
    if (this.refreshTimeout) {
      clearTimeout(this.refreshTimeout);
    }
    this.refreshTimeout = setTimeout(() => {
      this.refreshTimeout = null;
      void this._refreshCurrentWorkspace(sessionId, version);
    }, 150);
  }

  _connectV3Stream(sessionId) {
    this._disconnectStream();
    this.stream = this.client.streamV3Session(sessionId, (event) => {
      if (!this.state.workspace?.session || this.state.currentSessionId !== sessionId) {
        return;
      }
      if (eventRequiresWorkspaceRefresh(event)) {
        this._scheduleWorkspaceRefresh(sessionId);
      }
      const nextWorkspace = reduceWorkspaceWithEvent(this.state.workspace, event);
      if (nextWorkspace === this.state.workspace) {
        return;
      }
      this.state.workspace = nextWorkspace;
      this._syncSummaryFromWorkspace();
      this._emit();
    });
  }

  async bootstrap() {
    const requestVersion = this._beginRequest();
    this._disconnectStream();
    this.messageRequestVersion += 1;
    this.approvalRequestVersion += 1;
    this.state.workspace = null;
    this.state.currentSessionId = "";
    this.state.currentSection = "conversation";
    this.state.selectedTeammateAgentId = "";
    this.state.sidebarExpandedSessionIds = [];
    this._clearErrors("sidebar", "createSession", "session", "message", "approvals");
    this.state.sidebarBusy = true;
    this.state.messageBusy = false;
    this.state.createSessionBusy = false;
    this.state.pendingApprovalId = "";
    this.state.refreshingWorkspace = false;
    this._emit();
    try {
      await this._refreshSessionSummaries();
    } catch (error) {
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.errors.sidebar = error.message;
    } finally {
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.sidebarBusy = false;
      this._emit();
    }
  }

  async createSession(payload) {
    if (this.state.createSessionBusy) {
      return false;
    }
    const requestVersion = this._beginRequest();
    this.messageRequestVersion += 1;
    this.approvalRequestVersion += 1;
    this.state.createSessionBusy = true;
    this._clearErrors("createSession", "session");
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
      this.state.currentSection = "conversation";
      this.state.selectedTeammateAgentId = "";
      this._setExpandedSession(response.session_id);
      this._syncSummaryFromWorkspace();
      await this._refreshSessionSummaries(this.state.currentProjectId);
      this._connectV3Stream(response.session_id);
      return true;
    } catch (error) {
      if (!this._isCurrentRequest(requestVersion)) {
        return false;
      }
      this.state.errors.createSession = error.message;
    } finally {
      if (!this._isCurrentRequest(requestVersion)) {
        return false;
      }
      this.state.createSessionBusy = false;
      this._emit();
    }
    return false;
  }

  async selectSession(sessionId, section = "conversation") {
    if (!sessionId || this.state.sidebarBusy) {
      return;
    }
    const requestVersion = this._beginRequest();
    this.messageRequestVersion += 1;
    this.approvalRequestVersion += 1;
    this.state.sidebarBusy = true;
    this.state.currentSessionId = sessionId;
    this.state.currentSection = section;
    this.state.selectedTeammateAgentId = "";
    this._setExpandedSession(sessionId);
    this._clearErrors("session", "message", "approvals");
    this.state.pendingApprovalId = "";
    this.state.messageBusy = false;
    this._emit();
    try {
      const response = await this.client.getV3Session(sessionId);
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.workspace = response.workspace;
      this._syncSummaryFromWorkspace();
      await this._refreshSessionSummaries(this.state.currentProjectId);
      this._connectV3Stream(sessionId);
    } catch (error) {
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.errors.session = error.message;
      this.state.workspace = null;
    } finally {
      if (!this._isCurrentRequest(requestVersion)) {
        return;
      }
      this.state.sidebarBusy = false;
      this._emit();
    }
  }

  selectSection(section) {
    this.state.currentSection = section || "conversation";
    this.state.selectedTeammateAgentId = "";
    this._emit();
  }

  selectTeammate(agentId) {
    if (!agentId || !this.state.workspace?.session) {
      return;
    }
    this.state.currentSection = "team";
    this.state.selectedTeammateAgentId = agentId;
    this._emit();
  }

  toggleSessionTree(sessionId) {
    if (this.state.sidebarExpandedSessionIds.includes(sessionId)) {
      this.state.sidebarExpandedSessionIds = this.state.sidebarExpandedSessionIds.filter((item) => item !== sessionId);
    } else {
      this._setExpandedSession(sessionId);
    }
    this._emit();
  }

  async sendMessage(message) {
    const trimmedMessage = message.trim();
    if (!this.state.currentSessionId || this.state.messageBusy || !trimmedMessage) {
      return false;
    }
    const sessionId = this.state.currentSessionId;
    this.messageRequestVersion += 1;
    const requestVersion = this.messageRequestVersion;
    this.state.messageBusy = true;
    this._clearErrors("message");
    const optimisticId = this._appendOptimisticUserMessage(trimmedMessage);
    this._emit();
    try {
      const response = await this.client.postV3Message(sessionId, { message: trimmedMessage });
      if (requestVersion !== this.messageRequestVersion) {
        return false;
      }
      if (this.state.currentSessionId !== sessionId) {
        await this._refreshSessionSummaries(this.state.currentProjectId);
        return false;
      }
      this.state.workspace = response.workspace;
      this._syncSummaryFromWorkspace();
      await this._refreshSessionSummaries(this.state.currentProjectId);
      return true;
    } catch (error) {
      if (requestVersion !== this.messageRequestVersion || this.state.currentSessionId !== sessionId) {
        return false;
      }
      this._appendMessageError(optimisticId, error.message);
      this.state.errors.message = error.message;
    } finally {
      if (requestVersion === this.messageRequestVersion && this.state.currentSessionId === sessionId) {
        this.state.messageBusy = false;
        this._emit();
      }
    }
    return false;
  }

  async resolveApproval(approvalId, decision) {
    if (!this.state.currentSessionId || !this.state.workspace?.session || !approvalId) {
      return false;
    }
    const sessionId = this.state.currentSessionId;
    this.approvalRequestVersion += 1;
    const requestVersion = this.approvalRequestVersion;
    this.state.pendingApprovalId = approvalId;
    this._clearApprovalError(approvalId);
    this._emit();
    try {
      const response = await this.client.resolveV3Approval(approvalId, { decision, actor_ref: "user" });
      if (requestVersion !== this.approvalRequestVersion) {
        return false;
      }
      if (this.state.currentSessionId !== sessionId) {
        await this._refreshSessionSummaries(this.state.currentProjectId);
        return false;
      }
      this.state.workspace = response.workspace;
      this._syncSummaryFromWorkspace();
      await this._refreshSessionSummaries(this.state.currentProjectId);
      return true;
    } catch (error) {
      if (requestVersion !== this.approvalRequestVersion || this.state.currentSessionId !== sessionId) {
        return false;
      }
      this._setApprovalError(approvalId, error.message);
    } finally {
      if (requestVersion === this.approvalRequestVersion && this.state.currentSessionId === sessionId) {
        this.state.pendingApprovalId = "";
        this._emit();
      }
    }
    return false;
  }
}
