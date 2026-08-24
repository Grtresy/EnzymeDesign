import {
  buildFileWorkspaceV2ProjectionObservation,
  FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
  FILE_WORKSPACE_PUBLIC_V2_SCHEMA,
  requireExactReleaseIdentity,
  requireFileWorkspaceV2Projection,
  requireRuntimeCommandStatusRecord,
} from "./file_workspace_v2_state.js";

function buildUrl(baseUrl, path) {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function headerValue(response, name) {
  return response.headers?.get?.(name)
    ?? response.headers?.[name]
    ?? response.headers?.[name.toLowerCase()]
    ?? "";
}

function canonicalJsonValue(value) {
  if (Array.isArray(value)) return value.map(canonicalJsonValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalJsonValue(value[key])]),
    );
  }
  return value;
}

export async function canonicalSha256Digest(value) {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new Error("Web Crypto SHA-256 is required for exact @2 verification");
  const bytes = new TextEncoder().encode(
    `${JSON.stringify(canonicalJsonValue(value))}\n`,
  );
  const digest = new Uint8Array(await subtle.digest("SHA-256", bytes));
  return `sha256:${Array.from(digest, (item) => item.toString(16).padStart(2, "0")).join("")}`;
}

export class WebUiContractError extends Error {
  constructor(code, message, {
    mutationApplied = false,
    effectCertainty = "no_effect",
  } = {}) {
    super(message);
    this.name = "WebUiContractError";
    this.code = code;
    this.mutationApplied = mutationApplied;
    this.effectCertainty = effectCertainty;
    this.fallbackPerformed = false;
  }
}

async function readJson(response, { mutationDispatched = false } = {}) {
  try {
    return await response.json();
  } catch (error) {
    throw new WebUiContractError(
      "web_ui_response_json_invalid",
      "Host response is not one valid JSON value",
      mutationDispatched
        ? { mutationApplied: null, effectCertainty: "dispatch_in_doubt" }
        : {},
    );
  }
}

async function requireOk(response, { mutationDispatched = false } = {}) {
  if (response.ok) return;
  let message = `Host request failed with status ${response.status}`;
  try {
    const payload = await response.json();
    message = payload?.detail ?? payload?.error?.message ?? message;
  } catch {
    // The bounded status is still safe to report; do not infer a response body.
  }
  throw new WebUiContractError(
    "web_ui_host_request_failed",
    message,
    mutationDispatched
      ? { mutationApplied: null, effectCertainty: "dispatch_in_doubt" }
      : {},
  );
}

async function verifyExtensionDigests(projection) {
  for (const [sectionId, section] of Object.entries(projection.extensions)) {
    const observed = await canonicalSha256Digest({
      section_id: sectionId,
      section_contract_digest: section.section_contract_digest,
      payload: section.payload,
      next_cursor: section.next_cursor,
    });
    if (observed !== section.projection_digest) {
      throw new WebUiContractError(
        "web_ui_extension_projection_digest_mismatch",
        `extension projection digest drift: ${sectionId}`,
      );
    }
  }
}

async function verifyResidentInnerDigests(projection) {
  const transcript = projection.core.conversation.transcript;
  const observedTranscriptDigest = await canonicalSha256Digest({
    schema_version: transcript.schema_version,
    messages: transcript.messages,
  });
  if (observedTranscriptDigest !== transcript.transcript_digest) {
    throw new WebUiContractError(
      "web_ui_transcript_digest_mismatch",
      "canonical resident transcript digest drift",
    );
  }
}

function requireResidentReady(projection) {
  const readiness = projection.core.session.resident_readiness;
  if (readiness.readiness === "ready") return;
  throw new WebUiContractError(
    "web_ui_resident_teammate_not_ready",
    `resident teammate is ${readiness.readiness}; next_action=${readiness.next_action}`,
  );
}

function requireCanonicalSelection(values, fieldName) {
  if (
    !Array.isArray(values)
    || values.some((item) => (
      typeof item !== "string"
      || !item
      || item.length > 256
      || item.trim() !== item
      || !/^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$/.test(item)
    ))
    || JSON.stringify(values) !== JSON.stringify([...new Set(values)].sort())
  ) {
    throw new WebUiContractError(
      "web_ui_workflow_selection_invalid",
      `${fieldName} must be a sorted, unique array of exact identifiers`,
    );
  }
}

function requireCanonicalMessagePayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new WebUiContractError(
      "web_ui_message_payload_invalid",
      "message admission payload must be one object",
    );
  }
  const allowed = new Set([
    "lane_id", "message", "message_id", "skill_keys", "task_id", "workflow_refs",
  ]);
  if (Object.keys(payload).some((name) => !allowed.has(name))) {
    throw new WebUiContractError(
      "web_ui_message_payload_invalid",
      "message admission payload fields are closed",
    );
  }
  if (
    typeof payload.message !== "string"
    || !payload.message
    || payload.message.trim() !== payload.message
    || payload.message.length > 131_072
  ) {
    throw new WebUiContractError(
      "web_ui_message_payload_invalid",
      "message text must be bounded, non-empty and trimmed",
    );
  }
  const hasWorkflowRefs = Object.hasOwn(payload, "workflow_refs");
  const hasSkillKeys = Object.hasOwn(payload, "skill_keys");
  if (hasWorkflowRefs === hasSkillKeys) {
    throw new WebUiContractError(
      hasWorkflowRefs
        ? "web_ui_workflow_selection_ambiguous"
        : "web_ui_workflow_selection_required",
      "provide canonical workflow_refs or compatibility skill_keys, including an explicit []",
    );
  }
  requireCanonicalSelection(
    payload[hasWorkflowRefs ? "workflow_refs" : "skill_keys"],
    hasWorkflowRefs ? "workflow_refs" : "skill_keys",
  );
  for (const fieldName of ["message_id", "task_id", "lane_id"]) {
    if (
      Object.hasOwn(payload, fieldName)
      && (typeof payload[fieldName] !== "string" || !payload[fieldName])
    ) {
      throw new WebUiContractError(
        "web_ui_message_scope_invalid",
        `${fieldName} must be one exact non-empty identity`,
      );
    }
  }
  return structuredClone(payload);
}

export class HostApiV2Client {
  constructor({
    baseUrl = "",
    expectedRelease,
    authToken = null,
    fetchImpl = globalThis.fetch,
  }) {
    this.baseUrl = baseUrl;
    this.expectedRelease = requireExactReleaseIdentity(expectedRelease, expectedRelease);
    this.fetchImpl = fetchImpl;
    this.authorization = authToken ? `Bearer ${authToken}` : "Bearer local-dev";
  }

  _baseHeaders() {
    return {
      Accept: FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
      Authorization: this.authorization,
      "OpenZyme-Workspace-Contract": FILE_WORKSPACE_PUBLIC_V2_SCHEMA,
      "OpenZyme-Client-Kind": "web-ui",
      "OpenZyme-Client-Build-Digest": this.expectedRelease.client_build_digest,
    };
  }

  async inspectWorkspace(sessionId, options = {}) {
    const response = await this.fetchImpl(
      buildUrl(this.baseUrl, `/v3/sessions/${sessionId}/workspace`),
      { ...options, headers: { ...this._baseHeaders(), ...(options.headers ?? {}) } },
    );
    await requireOk(response);
    if (!headerValue(response, "content-type").includes(FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE)) {
      throw new WebUiContractError(
        "web_ui_workspace_media_type_mismatch",
        "Host response media type is not exact file_workspace_public@2",
      );
    }
    const projection = requireFileWorkspaceV2Projection(await readJson(response));
    requireExactReleaseIdentity(projection.release, this.expectedRelease);
    await verifyExtensionDigests(projection);
    await verifyResidentInnerDigests(projection);
    const projectionDigest = await canonicalSha256Digest(projection);
    const bindingDigest = projection.core.capability_binding.binding_digest;
    const affordanceDigest = projection.core.tool_reflection.affordance_snapshot_digest;
    const expectedHeaders = {
      "openzyme-workspace-contract": FILE_WORKSPACE_PUBLIC_V2_SCHEMA,
      "openzyme-release-digest": this.expectedRelease.release_digest,
      "openzyme-public-contract-digest": this.expectedRelease.public_contract_digest,
      "openzyme-projection-digest": projectionDigest,
      "openzyme-capability-binding-digest": bindingDigest,
      "openzyme-affordance-snapshot-digest": affordanceDigest,
    };
    for (const [name, expected] of Object.entries(expectedHeaders)) {
      if (headerValue(response, name) !== expected) {
        throw new WebUiContractError(
          "web_ui_response_identity_mismatch",
          `Host response identity drift: ${name}`,
        );
      }
    }
    return {
      projection,
      verified: {
        ...expectedHeaders,
        projectionDigest,
        bindingDigest,
        affordanceDigest,
      },
    };
  }

  async pollWorkspaceProjection(
    sessionId,
    previousProjectionDigest = null,
    options = {},
  ) {
    if (
      previousProjectionDigest !== null
      && !/^sha256:[0-9a-f]{64}$/.test(previousProjectionDigest)
    ) {
      throw new WebUiContractError(
        "web_ui_workspace_projection_cursor_invalid",
        "workspace projection polling requires one canonical prior projection digest",
      );
    }
    const inspection = await this.inspectWorkspace(sessionId, options);
    const projectionDigest = inspection.verified.projectionDigest;
    if (projectionDigest === previousProjectionDigest) {
      return {
        ...inspection,
        changed: false,
        observation: null,
      };
    }
    let observation;
    try {
      observation = buildFileWorkspaceV2ProjectionObservation({
        projection: inspection.projection,
        projectionDigest,
        previousProjectionDigest,
      });
    } catch (error) {
      throw new WebUiContractError(
        "web_ui_workspace_projection_observation_invalid",
        `verified Host projection could not form a closed change observation: ${error.message}`,
      );
    }
    return {
      ...inspection,
      changed: true,
      observation,
    };
  }

  async _sendMutation(
    sessionId,
    path,
    payload,
    idempotencyKey,
    expectedProjectionDigest = null,
  ) {
    if (typeof idempotencyKey !== "string" || !idempotencyKey.trim()) {
      throw new WebUiContractError(
        "web_ui_idempotency_key_required",
        "exact @2 mutation requires one explicit UI gesture identity",
      );
    }
    const { projection: inspected, verified } = await this.inspectWorkspace(sessionId);
    if (
      expectedProjectionDigest !== null
      && (
        !/^sha256:[0-9a-f]{64}$/.test(expectedProjectionDigest)
        || verified.projectionDigest !== expectedProjectionDigest
      )
    ) {
      throw new WebUiContractError(
        "web_ui_mutation_projection_stale",
        "workspace projection changed before mutation admission; refresh is required",
      );
    }
    requireResidentReady(inspected);
    const response = await this.fetchImpl(buildUrl(this.baseUrl, path), {
      method: "POST",
      headers: {
        ...this._baseHeaders(),
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "OpenZyme-Release-Digest": this.expectedRelease.release_digest,
        "OpenZyme-Public-Contract-Digest": this.expectedRelease.public_contract_digest,
        "OpenZyme-Projection-Digest": verified.projectionDigest,
        "OpenZyme-Capability-Binding-Digest": verified.bindingDigest,
        "OpenZyme-Affordance-Snapshot-Digest": verified.affordanceDigest,
      },
      body: JSON.stringify(payload),
    });
    await requireOk(response, { mutationDispatched: true });
    if (response.status !== 202) {
      throw new WebUiContractError(
        "web_ui_admission_status_invalid",
        `exact resident admission requires HTTP 202, observed ${response.status}`,
        { mutationApplied: null, effectCertainty: "dispatch_in_doubt" },
      );
    }
    const mutationHeaders = {
      "openzyme-workspace-contract": FILE_WORKSPACE_PUBLIC_V2_SCHEMA,
      "openzyme-release-digest": this.expectedRelease.release_digest,
      "openzyme-public-contract-digest": this.expectedRelease.public_contract_digest,
      "openzyme-projection-digest": verified.projectionDigest,
      "openzyme-capability-binding-digest": verified.bindingDigest,
      "openzyme-affordance-snapshot-digest": verified.affordanceDigest,
    };
    for (const [name, expected] of Object.entries(mutationHeaders)) {
      if (headerValue(response, name) !== expected) {
        throw new WebUiContractError(
          "web_ui_mutation_response_identity_mismatch",
          `post-dispatch Host identity drift: ${name}`,
          { mutationApplied: null, effectCertainty: "dispatch_in_doubt" },
        );
      }
    }
    const mutationReceipt = await readJson(response, { mutationDispatched: true });
    // The mutation body is not treated as canonical @2 state. Re-inspect the
    // exact Session projection after the command response instead.
    const canonical = await this.pollWorkspaceProjection(
      sessionId,
      verified.projectionDigest,
    );
    return { responseStatus: response.status, mutationReceipt, ...canonical };
  }

  async postMessage(
    sessionId,
    payload,
    idempotencyKey,
    expectedProjectionDigest = null,
  ) {
    return this._sendMutation(
      sessionId,
      `/v3/sessions/${sessionId}/messages`,
      requireCanonicalMessagePayload(payload),
      idempotencyKey,
      expectedProjectionDigest,
    );
  }

  async drainRuntime(
    sessionId,
    payload,
    idempotencyKey,
    expectedProjectionDigest = null,
  ) {
    if (
      !payload
      || typeof payload !== "object"
      || Array.isArray(payload)
      || JSON.stringify(Object.keys(payload).sort())
        !== JSON.stringify(["max_signals", "max_steps_per_agent"])
      || !Number.isInteger(payload.max_signals)
      || payload.max_signals <= 0
      || !Number.isInteger(payload.max_steps_per_agent)
      || payload.max_steps_per_agent <= 0
    ) {
      throw new WebUiContractError(
        "web_ui_runtime_budget_invalid",
        "runtime drain requires exact positive max_signals and max_steps_per_agent",
      );
    }
    return this._sendMutation(
      sessionId,
      `/v3/sessions/${sessionId}/runtime/drain`,
      { ...payload, auto_enqueue_ready_tasks: false },
      idempotencyKey,
      expectedProjectionDigest,
    );
  }

  async decideApproval(
    sessionId,
    approvalId,
    payload,
    idempotencyKey,
    expectedProjectionDigest = null,
  ) {
    if (typeof approvalId !== "string" || !approvalId.trim()) {
      throw new WebUiContractError(
        "web_ui_approval_id_required",
        "approval decision requires one exact approval identity",
      );
    }
    if (
      !payload
      || typeof payload !== "object"
      || Array.isArray(payload)
      || JSON.stringify(Object.keys(payload).sort())
        !== JSON.stringify(["decision", "intent_digest", "resolution_ref"])
      || !["approved", "rejected"].includes(payload.decision)
      || !/^sha256:[0-9a-f]{64}$/.test(payload.intent_digest)
      || typeof payload.resolution_ref !== "string"
      || !payload.resolution_ref
    ) {
      throw new WebUiContractError(
        "web_ui_approval_decision_invalid",
        "approval decision payload is not bound to one exact pending intent",
      );
    }
    return this._sendMutation(
      sessionId,
      `/v3/sessions/${sessionId}/approvals/${approvalId}/decision`,
      payload,
      idempotencyKey,
      expectedProjectionDigest,
    );
  }

  async inspectRuntimeCommand(sessionId, commandId) {
    if (typeof commandId !== "string" || !commandId.trim()) {
      throw new WebUiContractError(
        "web_ui_runtime_command_id_required",
        "runtime command polling requires one exact command identity",
      );
    }
    const response = await this.fetchImpl(
      buildUrl(
        this.baseUrl,
        `/v3/sessions/${sessionId}/runtime/commands/${commandId}`,
      ),
      { headers: this._baseHeaders() },
    );
    await requireOk(response);
    if (!headerValue(response, "content-type").includes(FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE)) {
      throw new WebUiContractError(
        "web_ui_runtime_command_media_type_mismatch",
        "runtime command response is not exact file_workspace_public@2",
      );
    }
    const expectedHeaders = {
      "openzyme-workspace-contract": FILE_WORKSPACE_PUBLIC_V2_SCHEMA,
      "openzyme-release-digest": this.expectedRelease.release_digest,
      "openzyme-public-contract-digest": this.expectedRelease.public_contract_digest,
    };
    for (const [name, expected] of Object.entries(expectedHeaders)) {
      if (headerValue(response, name) !== expected) {
        throw new WebUiContractError(
          "web_ui_runtime_command_identity_mismatch",
          `runtime command response identity drift: ${name}`,
        );
      }
    }
    for (const name of [
      "openzyme-projection-digest",
      "openzyme-capability-binding-digest",
      "openzyme-affordance-snapshot-digest",
    ]) {
      if (!/^sha256:[0-9a-f]{64}$/.test(headerValue(response, name))) {
        throw new WebUiContractError(
          "web_ui_runtime_command_identity_mismatch",
          `runtime command response identity is invalid: ${name}`,
        );
      }
    }
    const payload = await readJson(response);
    const observedFields = Object.keys(payload ?? {}).sort();
    const expectedFields = [
      "command",
      "fallback_performed",
      "mutation_applied",
      "projection_digest",
      "schema_version",
      "session_id",
    ];
    if (
      JSON.stringify(observedFields) !== JSON.stringify(expectedFields)
      || payload.schema_version !== "runtime_command_status@1"
      || payload.session_id !== sessionId
      || payload.projection_digest !== headerValue(response, "openzyme-projection-digest")
      || payload.mutation_applied !== false
      || payload.fallback_performed !== false
      || !payload.command
      || typeof payload.command !== "object"
      || Array.isArray(payload.command)
      || payload.command.command_id !== commandId
    ) {
      throw new WebUiContractError(
        "web_ui_runtime_command_payload_invalid",
        "runtime command status does not match the requested exact identity",
      );
    }
    try {
      requireRuntimeCommandStatusRecord(payload.command, sessionId, commandId);
    } catch (error) {
      throw new WebUiContractError(
        "web_ui_runtime_command_payload_invalid",
        `runtime command record violates the closed contract: ${error.message}`,
      );
    }
    return structuredClone(payload);
  }
}

export function buildHostV2Paths(sessionId) {
  return {
    workspace: `/v3/sessions/${sessionId}/workspace`,
    messages: `/v3/sessions/${sessionId}/messages`,
    runtimeDrain: `/v3/sessions/${sessionId}/runtime/drain`,
  };
}
