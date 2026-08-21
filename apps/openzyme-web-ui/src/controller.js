import { buildCoreShellState, reduceCoreShellEvent } from "./core_shell.js";

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
    this.state = {
      sessionId: "",
      shell: null,
      loading: false,
      refreshing: false,
      messageBusy: false,
      drainBusy: false,
      error: "",
      mutationError: "",
      lastMutationStatus: null,
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
    if (!Number.isFinite(this.reconcileIntervalMs) || this.reconcileIntervalMs <= 0) return;
    this.reconcileTimeout = this.setReconcileTimeout?.(async () => {
      this.reconcileTimeout = null;
      if (!this.state.messageBusy && !this.state.drainBusy) await this.refresh();
      this._scheduleReconciliation();
    }, this.reconcileIntervalMs);
    this.reconcileTimeout?.unref?.();
  }

  _adoptProjection(projection) {
    this.state.shell = buildCoreShellState(
      projection,
      this.rendererRegistry,
      { expectedRendererCatalogDigest: this.expectedRendererCatalogDigest },
    );
    this.state.error = "";
  }

  async bootstrap(sessionId) {
    this.requestGeneration += 1;
    const generation = this.requestGeneration;
    this._cancelReconciliation();
    this.state = {
      ...this.state,
      sessionId,
      shell: null,
      loading: true,
      refreshing: false,
      error: "",
      mutationError: "",
    };
    this._emit();
    try {
      if (!sessionId) throw new Error("exact @2 Web UI requires one configured session_id");
      const { projection } = await this.client.inspectWorkspace(sessionId);
      if (generation !== this.requestGeneration) return false;
      this._adoptProjection(projection);
      this._scheduleReconciliation();
      return true;
    } catch (error) {
      if (generation !== this.requestGeneration) return false;
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
    if (!this.state.sessionId || this.state.refreshing) return false;
    const generation = this.requestGeneration;
    this.state.refreshing = true;
    this._emit();
    try {
      const { projection } = await this.client.inspectWorkspace(this.state.sessionId);
      if (generation !== this.requestGeneration) return false;
      this._adoptProjection(projection);
      return true;
    } catch (error) {
      if (generation === this.requestGeneration) this.state.error = error.message;
      return false;
    } finally {
      if (generation === this.requestGeneration) {
        this.state.refreshing = false;
        this._emit();
      }
    }
  }

  async sendMessage(message, idempotencyKey) {
    const trimmed = String(message ?? "").trim();
    if (!trimmed || this.state.messageBusy || !this.state.shell?.mutationAllowed) return false;
    this.state.messageBusy = true;
    this.state.mutationError = "";
    this._emit();
    try {
      const result = await this.client.postMessage(
        this.state.sessionId,
        { message: trimmed },
        idempotencyKey,
      );
      this._adoptProjection(result.projection);
      this.state.lastMutationStatus = result.responseStatus;
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
    if (this.state.drainBusy || !this.state.shell?.mutationAllowed) return false;
    if (!Number.isInteger(maxSignals) || maxSignals <= 0) return false;
    if (!Number.isInteger(maxStepsPerAgent) || maxStepsPerAgent <= 0) return false;
    this.state.drainBusy = true;
    this.state.mutationError = "";
    this._emit();
    try {
      const result = await this.client.drainRuntime(
        this.state.sessionId,
        { max_signals: maxSignals, max_steps_per_agent: maxStepsPerAgent },
        idempotencyKey,
      );
      this._adoptProjection(result.projection);
      this.state.lastMutationStatus = result.responseStatus;
      return true;
    } catch (error) {
      this.state.mutationError = error.message;
      return false;
    } finally {
      this.state.drainBusy = false;
      this._emit();
    }
  }

  acceptEvent(event) {
    if (!this.state.shell) return false;
    this.state.shell = reduceCoreShellEvent(this.state.shell, event);
    this._emit();
    if (this.state.shell.refreshRequired && this.state.shell.mutationAllowed) {
      void this.refresh();
    }
    return true;
  }

  close() {
    this.requestGeneration += 1;
    this._cancelReconciliation();
  }
}

export const WorkspaceController = WorkspaceControllerV2;
