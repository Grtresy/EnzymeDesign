import {
  FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
  FILE_WORKSPACE_PUBLIC_V2_SCHEMA,
  requireExactReleaseIdentity,
  requireFileWorkspaceV2Projection,
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
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalJsonValue(value)));
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

  async _sendMutation(sessionId, path, payload, idempotencyKey) {
    if (typeof idempotencyKey !== "string" || !idempotencyKey.trim()) {
      throw new WebUiContractError(
        "web_ui_idempotency_key_required",
        "exact @2 mutation requires one explicit UI gesture identity",
      );
    }
    const { verified } = await this.inspectWorkspace(sessionId);
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
    // The mutation body is not treated as canonical @2 state. Re-inspect the
    // exact Session projection after the command response instead.
    const canonical = await this.inspectWorkspace(sessionId);
    return { responseStatus: response.status, ...canonical };
  }

  postMessage(sessionId, payload, idempotencyKey) {
    return this._sendMutation(
      sessionId,
      `/v3/sessions/${sessionId}/messages`,
      payload,
      idempotencyKey,
    );
  }

  drainRuntime(sessionId, payload, idempotencyKey) {
    return this._sendMutation(
      sessionId,
      `/v3/sessions/${sessionId}/runtime/drain`,
      { ...payload, auto_enqueue_ready_tasks: false },
      idempotencyKey,
    );
  }
}

export function buildHostV2Paths(sessionId) {
  return {
    workspace: `/v3/sessions/${sessionId}/workspace`,
    messages: `/v3/sessions/${sessionId}/messages`,
    runtimeDrain: `/v3/sessions/${sessionId}/runtime/drain`,
  };
}
