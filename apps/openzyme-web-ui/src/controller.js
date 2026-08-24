import {
  buildCoreShellState,
  reduceCoreShellProjectionObservation,
} from "./core_shell.js";

export class WorkspaceControllerV2 {
  constructor({
    client,
    rendererRegistry,
    expectedRendererCatalogDigest,
    onChange = () => {},
    reconcileIntervalMs = 5_000,
    setReconcileTimeout = globalThis.setTimeout?.bind(globalThis),
    clearReconcileTimeout = globalThis.clearTimeout?.bind(globalThis),
  }) {
    this.client = client;
    this.rendererRegistry = rendererRegistry;
    this.expectedRendererCatalogDigest = expectedRendererCatalogDigest;
    this.onChange = onChange;
    this.reconcileIntervalMs = reconcileIntervalMs;
    this.setReconcileTimeout = setReconcileTimeout;
    this.clearReconcileTimeout = clearReconcileTimeout;
    this.reconcileTimeout = null;
    this.requestGeneration = 0;
    this.closed = false;
    this.state = {
      sessionId: "",
      shell: null,
      loading: false,
      refreshing: false,
      messageBusy: false,
      drainBusy: false,
      approvalBusy: false,
      activeRuntimeCommandId: null,
      runtimeCommandStatus: null,
      lastMutationReceipt: null,
      error: "",
      mutationError: "",
      lastMutationStatus: null,
      projectionPollingStatus: "idle",
      projectionPollingError: "",
      projectionReconnectCount: 0,
    };
  }

  snapshot() {
    return structuredClone(this.state);
  }

  _emit() {
    this.onChange(this.snapshot());
  }

  _cancelReconciliation() {
    if (this.reconcileTimeout !== null) {
      this.clearReconcileTimeout?.(this.reconcileTimeout);
      this.reconcileTimeout = null;
    }
  }

  _scheduleReconciliation() {
    this._cancelReconciliation();
    if (
      this.closed
      || !Number.isFinite(this.reconcileIntervalMs)
      || this.reconcileIntervalMs <= 0
    ) return;
    const generation = this.requestGeneration;
    this.reconcileTimeout = this.setReconcileTimeout?.(async () => {
      this.reconcileTimeout = null;
      if (this.closed || generation !== this.requestGeneration) return;
      if (!this.state.messageBusy && !this.state.drainBusy && !this.state.approvalBusy) {
        await this.refresh();
        if (this.state.activeRuntimeCommandId) await this.pollRuntimeCommand();
      }
      if (!this.closed && generation === this.requestGeneration) {
        this._scheduleReconciliation();
      }
    }, this.reconcileIntervalMs);
    this.reconcileTimeout?.unref?.();
  }

  _blockForProjectionPolling(error, status = "reconnecting") {
    this.state.projectionPollingStatus = status;
    this.state.projectionPollingError = error.message;
    if (status === "reconnecting") this.state.projectionReconnectCount += 1;
    if (this.state.shell) {
      this.state.shell = {
        ...this.state.shell,
        contractBlocked: true,
        mutationAllowed: false,
        messageAllowed: false,
        runtimeDrainAllowed: false,
        approvalDecisionAllowed: false,
        refreshRequired: false,
        blockingError: `verified workspace projection polling unavailable: ${error.message}`,
      };
    }
  }

  _adoptProjectionResult(result) {
    if (this.closed) return false;
    try {
      if (
        !result
        || typeof result !== "object"
        || typeof result.changed !== "boolean"
        || !result.projection
        || typeof result.verified?.projectionDigest !== "string"
        || !/^sha256:[0-9a-f]{64}$/.test(result.verified.projectionDigest)
        || (result.changed && !result.observation)
        || (!result.changed && result.observation !== null)
      ) {
        throw new Error("workspace projection polling returned an invalid closed result");
      }
      const previousObservations = this.state.shell?.projectionObservations ?? [];
      const previousProjectionDigest = this.state.shell?.currentProjectionDigest ?? null;
      if (
        previousProjectionDigest !== null
        && !result.changed
        && result.verified.projectionDigest !== previousProjectionDigest
      ) {
        throw new Error("unchanged workspace projection advanced its digest");
      }
      let shell = buildCoreShellState(
        result.projection,
        this.rendererRegistry,
        {
          expectedRendererCatalogDigest: this.expectedRendererCatalogDigest,
          projectionDigest: result.verified.projectionDigest,
          projectionObservations: previousObservations,
        },
      );
      if (result.changed) {
        shell = reduceCoreShellProjectionObservation(shell, result.observation);
      }
      this.state.shell = shell;
      if (
        shell.contractBlocked
        && shell.blockingError.startsWith("workspace projection observation rejected:")
      ) {
        throw new Error(shell.blockingError);
      }
    } catch (error) {
      this._blockForProjectionPolling(error, "failed");
      return false;
    }
    this.state.projectionPollingStatus = "connected";
    this.state.projectionPollingError = "";
    this.state.error = "";
    return true;
  }

  async bootstrap(sessionId) {
    this.requestGeneration += 1;
    const generation = this.requestGeneration;
    this.closed = false;
    this._cancelReconciliation();
    this.state = {
      ...this.state,
      sessionId,
      shell: null,
      loading: true,
      refreshing: false,
      error: "",
      mutationError: "",
      projectionPollingStatus: "connecting",
      projectionPollingError: "",
      projectionReconnectCount: 0,
    };
    this._emit();
    try {
      if (!sessionId) throw new Error("exact @2 Web UI requires one configured session_id");
      if (typeof this.client.pollWorkspaceProjection !== "function") {
        throw new Error("Host workspace projection polling transport is unavailable");
      }
      const result = await this.client.pollWorkspaceProjection(sessionId, null);
      if (generation !== this.requestGeneration) return false;
      if (!this._adoptProjectionResult(result)) return false;
      this._scheduleReconciliation();
      return true;
    } catch (error) {
      if (generation !== this.requestGeneration) return false;
      this._blockForProjectionPolling(error, "failed");
      this.state.error = error.message;
      return false;
    } finally {
      if (generation === this.requestGeneration) {
        this.state.loading = false;
        this._emit();
      }
    }
  }

  async refresh() {
    if (this.closed || !this.state.sessionId || this.state.refreshing) return false;
    const generation = this.requestGeneration;
    this.state.refreshing = true;
    this._emit();
    try {
      if (typeof this.client.pollWorkspaceProjection !== "function") {
        throw new Error("Host workspace projection polling transport is unavailable");
      }
      const result = await this.client.pollWorkspaceProjection(
        this.state.sessionId,
        this.state.shell?.currentProjectionDigest ?? null,
      );
      if (generation !== this.requestGeneration) return false;
      return this._adoptProjectionResult(result);
    } catch (error) {
      if (generation === this.requestGeneration) {
        this._blockForProjectionPolling(error);
      }
      return false;
    } finally {
      if (generation === this.requestGeneration) {
        this.state.refreshing = false;
        this._emit();
      }
    }
  }

  async sendMessage(message, idempotencyKey, workflowRefs = []) {
    const trimmed = String(message ?? "").trim();
    if (!trimmed || this.state.messageBusy || !this.state.shell?.messageAllowed) return false;
    this.state.messageBusy = true;
    const generation = this.requestGeneration;
    this.state.mutationError = "";
    this._emit();
    try {
      const result = await this.client.postMessage(
        this.state.sessionId,
        { message: trimmed, workflow_refs: structuredClone(workflowRefs) },
        idempotencyKey,
        this.state.shell.currentProjectionDigest,
      );
      if (this.closed || generation !== this.requestGeneration) return false;
      if (!this._adoptProjectionResult(result)) return false;
      this.state.lastMutationStatus = result.responseStatus;
      this.state.lastMutationReceipt = structuredClone(
        result.mutationReceipt ?? null,
      );
      return true;
    } catch (error) {
      this.state.mutationError = error.message;
      return false;
    } finally {
      this.state.messageBusy = false;
      this._emit();
    }
  }

  async drainRuntime({ maxSignals = 3, maxStepsPerAgent = 8 }, idempotencyKey) {
    if (this.state.drainBusy || !this.state.shell?.runtimeDrainAllowed) return false;
    if (!Number.isInteger(maxSignals) || maxSignals <= 0) return false;
    if (!Number.isInteger(maxStepsPerAgent) || maxStepsPerAgent <= 0) return false;
    this.state.drainBusy = true;
    const generation = this.requestGeneration;
    this.state.mutationError = "";
    this._emit();
    try {
      const result = await this.client.drainRuntime(
        this.state.sessionId,
        { max_signals: maxSignals, max_steps_per_agent: maxStepsPerAgent },
        idempotencyKey,
        this.state.shell.currentProjectionDigest,
      );
      if (this.closed || generation !== this.requestGeneration) return false;
      if (!this._adoptProjectionResult(result)) return false;
      this.state.lastMutationStatus = result.responseStatus;
      this.state.lastMutationReceipt = structuredClone(
        result.mutationReceipt ?? null,
      );
      const runtimeCommandId = result.mutationReceipt?.result?.runtime_command_id;
      if (typeof runtimeCommandId === "string" && runtimeCommandId) {
        this.state.activeRuntimeCommandId = runtimeCommandId;
        await this.pollRuntimeCommand();
        if (this.closed || generation !== this.requestGeneration) return false;
      }
      return true;
    } catch (error) {
      this.state.mutationError = error.message;
      return false;
    } finally {
      this.state.drainBusy = false;
      this._emit();
    }
  }

  async pollRuntimeCommand() {
    const commandId = this.state.activeRuntimeCommandId;
    if (
      this.closed
      || !commandId
      || typeof this.client.inspectRuntimeCommand !== "function"
    ) return false;
    const generation = this.requestGeneration;
    try {
      const status = await this.client.inspectRuntimeCommand(
        this.state.sessionId,
        commandId,
      );
      if (this.closed || generation !== this.requestGeneration) return false;
      this.state.runtimeCommandStatus = status;
      if (["completed", "failed", "locked", "cancelled"].includes(status.command.status)) {
        this.state.activeRuntimeCommandId = null;
        await this.refresh();
      }
      this._emit();
      return true;
    } catch (error) {
      this.state.mutationError = error.message;
      this._emit();
      return false;
    }
  }

  async decideApproval(approvalId, decision, idempotencyKey) {
    if (
      this.state.approvalBusy
      || !this.state.shell?.approvalDecisionAllowed
      || !["approved", "rejected"].includes(decision)
    ) return false;
    const approval = this.state.shell.core.approvals.find(
      (item) => item.approval_id === approvalId,
    );
    if (!approval || approval.status !== "pending" || typeof approval.intent_digest !== "string") {
      return false;
    }
    this.state.approvalBusy = true;
    const generation = this.requestGeneration;
    this.state.mutationError = "";
    this._emit();
    try {
      const result = await this.client.decideApproval(
        this.state.sessionId,
        approvalId,
        {
          decision,
          intent_digest: approval.intent_digest,
          resolution_ref: idempotencyKey,
        },
        idempotencyKey,
        this.state.shell.currentProjectionDigest,
      );
      if (this.closed || generation !== this.requestGeneration) return false;
      if (!this._adoptProjectionResult(result)) return false;
      this.state.lastMutationStatus = result.responseStatus;
      this.state.lastMutationReceipt = structuredClone(
        result.mutationReceipt ?? null,
      );
      return true;
    } catch (error) {
      this.state.mutationError = error.message;
      return false;
    } finally {
      this.state.approvalBusy = false;
      this._emit();
    }
  }

  acceptProjectionObservation(observation) {
    if (this.closed || !this.state.shell) return false;
    this.state.shell = reduceCoreShellProjectionObservation(
      this.state.shell,
      observation,
    );
    if (
      this.state.shell.contractBlocked
      && this.state.shell.blockingError.startsWith(
        "workspace projection observation rejected:",
      )
    ) {
      this.state.projectionPollingStatus = "failed";
      this.state.projectionPollingError = this.state.shell.blockingError;
    }
    this._emit();
    return !this.state.shell.contractBlocked;
  }

  close() {
    this.requestGeneration += 1;
    this.closed = true;
    this._cancelReconciliation();
    this.state.loading = false;
    this.state.refreshing = false;
    this.state.messageBusy = false;
    this.state.drainBusy = false;
    this.state.approvalBusy = false;
    this.state.activeRuntimeCommandId = null;
    this.state.projectionPollingStatus = "closed";
    this.state.projectionPollingError = "";
    if (this.state.shell) {
      this.state.shell = {
        ...this.state.shell,
        mutationAllowed: false,
        messageAllowed: false,
        runtimeDrainAllowed: false,
        approvalDecisionAllowed: false,
      };
    }
    this._emit();
  }
}

export const WorkspaceController = WorkspaceControllerV2;
