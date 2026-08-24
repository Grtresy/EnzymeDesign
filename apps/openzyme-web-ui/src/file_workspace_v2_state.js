export const FILE_WORKSPACE_PUBLIC_V2_SCHEMA = "file_workspace_public@2";
export const FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE =
  "application/vnd.openzyme.file-workspace+json;version=2";
export const FILE_WORKSPACE_PROJECTION_OBSERVATION_SCHEMA =
  "file_workspace_projection_observation@1";
export const FILE_WORKSPACE_PROJECTION_OBSERVATION_FACTS_SCHEMA =
  "resident_workspace_projection_change_facts@1";
export const FILE_WORKSPACE_PROJECTION_OBSERVATION_HISTORY_LIMIT = 64;

export const FILE_WORKSPACE_V2_CORE_FIELDS = Object.freeze([
  "agents",
  "approvals",
  "authority_leases",
  "capability_binding",
  "conversation",
  "failures",
  "lanes",
  "operations",
  "protocol",
  "publications",
  "runtime",
  "session",
  "tasks",
  "tool_reflection",
  "workspace",
]);

const ARRAY_CORE_FIELDS = new Set([
  "agents",
  "approvals",
  "authority_leases",
  "lanes",
  "publications",
  "tasks",
]);

const FORBIDDEN_CORE_TOKENS = new Set([
  "agentcapabilitylease",
  "agentcapabilityleaseid",
  "agentcapabilityleases",
  "alphafold",
  "aox",
  "arti" + "fact",
  "arti" + "factcatalog",
  "arti" + "factindex",
  "arti" + "factkind",
  "arti" + "facts",
  "arti" + "factset",
  "boundedstderr",
  "boundedstdout",
  "claimtoken",
  "compute",
  "context",
  "deliveryleasetoken",
  "docking",
  "fpocket",
  "hpc",
  "hpcstageref",
  "hpcworkspaces",
  "hmmer",
  "leasetoken",
  "privatecontext",
  "privatefailure",
  "reportdrafts",
  "reports",
  "research",
  "researchfiles",
  "revisionexecutions",
  "runtimeleasetoken",
  "scientificattempts",
  "scientificdeliverables",
  "scientificselections",
  "sessionleasetoken",
  "signalclaimtoken",
  "stderr",
  "stdout",
  "storageuri",
  "toolrequests",
  "traceback",
  "tracebacktext",
  "vina",
]);

const FORBIDDEN_CORE_FRAGMENTS = [
  "accesstoken",
  "credential",
  "hostpath",
  "lfsobjectlocator",
  "lfsobjectroot",
  "lfslocator",
  "loginalias",
  "privatekey",
  "privateref",
  "refreshtoken",
  "remoteroot",
  "repositoryroot",
  "schedulerhandle",
];

const DIGEST = /^sha256:[0-9a-f]{64}$/;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$/;
const MACHINE_IDENTIFIER = /^[A-Za-z][A-Za-z0-9._:@-]{0,127}$/;
export const FILE_WORKSPACE_V2_RELEASE_FIELDS = Object.freeze([
  "adapter_bundle_digest",
  "client_build_digest",
  "core_schema_digest",
  "declared_tool_catalog_digest",
  "extension_bundle_digest",
  "host_build_digest",
  "kernel_contract_digest",
  "migration_catalog_digest",
  "projection_catalog_digest",
  "public_contract_digest",
  "release_digest",
  "route_catalog_digest",
  "schema_version",
  "workspace_backend_digest",
]);
const OBJECT_SECTION_FIELDS = Object.freeze({
  conversation: {
    memories: "array",
    messages: "array",
    transcript: "object",
  },
  failures: { observations: "array" },
  operations: {
    command_receipts: "array",
    continuations: "array",
    controlled: "array",
    publication_intents: "array",
    task_evidence: "array",
  },
  protocol: { inbox: "array", records: "array" },
  runtime: {
    commands: "array",
    continuation_intents: "array",
    outcome_consumptions: "array",
    outcomes: "array",
    session_leases: "array",
    settlement_intents: "array",
    signals: "array",
    turn_commands: "array",
    workflow_authority: "object",
  },
  workspace: {
    checkpoints: "array",
    generations: "array",
    provisioning: "object",
    repository_binding_pins: "array",
    revision_path_verifications: "array",
    runtime_bindings: "array",
  },
});
const TOOL_REFLECTION_FIELDS = Object.freeze([
  "affordance_snapshot_digest",
  "affordances",
  "available_tool_names",
  "capability_binding_digest",
  "declared_tool_catalog_digest",
  "tool_exposure",
]);
const TOOL_AFFORDANCE_FIELDS = Object.freeze([
  "blockers",
  "required_authorities",
  "route_ids",
  "route_refs",
  "state",
  "tool_contract_digest",
  "tool_name",
]);
const PUBLIC_TOOL_STATES = new Set([
  "available",
  "available_with_approval",
  "blocked_dependency",
  "blocked_configuration",
  "blocked_qualification",
  "blocked_authority",
  "blocked_provisioning",
  "temporarily_unavailable",
]);
const PROJECTION_OBSERVATION_FIELDS = Object.freeze([
  "facts",
  "observation_id",
  "observation_kind",
  "previous_projection_digest",
  "projection_digest",
  "public_contract_digest",
  "release_digest",
  "schema_version",
  "session_id",
  "source",
]);
const PROJECTION_OBSERVATION_FACT_FIELDS = Object.freeze([
  "failure_ids",
  "latest_runtime_command",
  "next_action",
  "pending_approval_ids",
  "pending_signal_count",
  "provisioning_intent_id",
  "provisioning_intent_state_version",
  "readiness",
  "runtime_command_count",
  "schema_version",
  "transcript_digest",
  "workspace_generation",
  "workspace_id",
]);
const PROJECTION_OBSERVATION_RUNTIME_COMMAND_FIELDS = Object.freeze([
  "command_id",
  "schema_version",
  "state_version",
  "status",
]);

function normalizedToken(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]/g, "");
}

function requireDigest(value, field) {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new Error(`${field} must be a canonical SHA-256 digest`);
  }
}

function requireIdentifier(value, field) {
  if (
    typeof value !== "string"
    || !value
    || value.length > 256
    || !IDENTIFIER.test(value)
  ) {
    throw new Error(`${field} must be one exact bounded identifier`);
  }
}

function requireMachineIdentifier(value, field) {
  if (typeof value !== "string" || !MACHINE_IDENTIFIER.test(value)) {
    throw new Error(`${field} must be one safe machine identifier`);
  }
}

function requirePublicFailureText(value, field, { nullable = false, max = 16_384 } = {}) {
  if (nullable && value === null) return;
  if (
    typeof value !== "string"
    || !value
    || value.length > max
    || PUBLIC_FAILURE_UNSAFE_TEXT_PATTERNS.some((pattern) => pattern.test(value))
  ) {
    throw new Error(`${field} must be bounded public-safe text`);
  }
}

function requireNullableIdentifier(value, field) {
  if (value !== null) requireIdentifier(value, field);
}

function requireNullableBoundedText(value, field) {
  if (value !== null && (typeof value !== "string" || value.length > 8_192)) {
    throw new Error(`${field} must be bounded text or null`);
  }
}

function requireExactKeys(value, expected, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${field} must be an object`);
  }
  const observed = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (JSON.stringify(observed) !== JSON.stringify(wanted)) {
    throw new Error(`${field} fields are closed`);
  }
}

function requireNullableString(value, field) {
  if (value !== null && (typeof value !== "string" || !value)) {
    throw new Error(`${field} must be a non-empty string or null`);
  }
}

function requireResidentReadiness(session) {
  const readiness = session.resident_readiness;
  requireExactKeys(readiness, [
    "failure_id",
    "next_action",
    "provisioning_intent_digest",
    "provisioning_intent_id",
    "readiness",
    "schema_version",
    "workspace_generation",
    "workspace_id",
  ], "core.session.resident_readiness");
  if (
    readiness.schema_version !== "resident_teammate_readiness@1"
    || !["provisioning", "ready", "blocked"].includes(readiness.readiness)
    || typeof readiness.workspace_id !== "string"
    || !readiness.workspace_id
    || !Number.isInteger(readiness.workspace_generation)
    || readiness.workspace_generation < 1
    || typeof readiness.provisioning_intent_id !== "string"
    || !readiness.provisioning_intent_id
    || typeof readiness.next_action !== "string"
    || !readiness.next_action
  ) {
    throw new Error("resident teammate readiness is invalid");
  }
  requireDigest(
    readiness.provisioning_intent_digest,
    "resident_readiness.provisioning_intent_digest",
  );
  requireNullableString(readiness.failure_id, "resident_readiness.failure_id");
  if ((readiness.readiness === "blocked") !== (readiness.failure_id !== null)) {
    throw new Error("blocked readiness and failure identity must agree");
  }
}

function requireProvisioningProjection(workspace) {
  const provisioning = workspace.provisioning;
  requireExactKeys(provisioning, [
    "diagnostic_id",
    "effect_certainty",
    "error_code",
    "failure_id",
    "fallback_performed",
    "intent_digest",
    "intent_id",
    "intent_state_version",
    "mutation_applied",
    "next_action",
    "reconciliation",
    "reconcile_required",
    "retry_permitted",
    "runtime_binding_id",
    "schema_version",
    "status",
    "workspace_generation",
    "workspace_id",
  ], "core.workspace.provisioning");
  if (
    provisioning.schema_version !== "workspace_provisioning_public@2"
    || !["pending", "claimed", "ready", "blocked", "cancelled"].includes(
      provisioning.status,
    )
    || typeof provisioning.intent_id !== "string"
    || !provisioning.intent_id
    || typeof provisioning.workspace_id !== "string"
    || !provisioning.workspace_id
    || !Number.isInteger(provisioning.workspace_generation)
    || provisioning.workspace_generation < 1
    || !Number.isInteger(provisioning.intent_state_version)
    || provisioning.intent_state_version < 1
    || typeof provisioning.fallback_performed !== "boolean"
    || provisioning.fallback_performed
    || typeof provisioning.retry_permitted !== "boolean"
    || provisioning.retry_permitted
    || typeof provisioning.reconcile_required !== "boolean"
    || typeof provisioning.next_action !== "string"
    || !provisioning.next_action
  ) {
    throw new Error("workspace provisioning projection is invalid");
  }
  requireDigest(provisioning.intent_digest, "workspace.provisioning.intent_digest");
  for (const field of [
    "runtime_binding_id",
    "failure_id",
    "error_code",
    "effect_certainty",
    "diagnostic_id",
  ]) {
    requireNullableString(provisioning[field], `workspace.provisioning.${field}`);
  }
  if (provisioning.mutation_applied !== null && typeof provisioning.mutation_applied !== "boolean") {
    throw new Error("workspace provisioning mutation fact is invalid");
  }
  requireProvisioningReconciliation(provisioning);
}

function requireProvisioningReconciliation(provisioning) {
  const reconciliation = provisioning.reconciliation;
  if (reconciliation === null) return;
  requireExactKeys(reconciliation, [
    "attempt",
    "blocked_intent_digest",
    "blocked_intent_state_version",
    "diagnostic_id",
    "dispatch_receipt_digest",
    "effect_certainty",
    "failure_id",
    "fallback_performed",
    "mutation_applied",
    "next_action",
    "parent_reconciliation_id",
    "reconcile_required",
    "reconciliation_digest",
    "reconciliation_id",
    "requested_at",
    "requested_claim_seconds",
    "result_receipt_digest",
    "result_receipt_id",
    "retry_permitted",
    "schema_version",
    "settled_at",
    "source_receipt_digest",
    "source_receipt_id",
    "status",
  ], "core.workspace.provisioning.reconciliation");
  if (
    reconciliation.schema_version
      !== "workspace_provisioning_reconciliation_public@1"
    || provisioning.status !== "blocked"
    || provisioning.effect_certainty !== "dispatch_in_doubt"
    || provisioning.reconcile_required !== true
    || !["pending", "claimed", "ready", "blocked"].includes(
      reconciliation.status,
    )
    || !Number.isInteger(reconciliation.attempt)
    || reconciliation.attempt < 1
    || !Number.isInteger(reconciliation.blocked_intent_state_version)
    || reconciliation.blocked_intent_state_version < 1
    || typeof reconciliation.reconciliation_id !== "string"
    || !reconciliation.reconciliation_id
    || typeof reconciliation.source_receipt_id !== "string"
    || !reconciliation.source_receipt_id
    || typeof reconciliation.requested_at !== "string"
    || !reconciliation.requested_at
    || !Number.isInteger(reconciliation.requested_claim_seconds)
    || reconciliation.requested_claim_seconds < 1
    || reconciliation.requested_claim_seconds > 86400
    || reconciliation.fallback_performed !== false
    || reconciliation.retry_permitted !== false
    || typeof reconciliation.reconcile_required !== "boolean"
  ) {
    throw new Error("workspace provisioning reconciliation is invalid");
  }
  for (const field of [
    "reconciliation_digest",
    "blocked_intent_digest",
    "source_receipt_digest",
    "dispatch_receipt_digest",
  ]) {
    requireDigest(reconciliation[field], `workspace.reconciliation.${field}`);
  }
  for (const field of [
    "parent_reconciliation_id",
    "result_receipt_id",
    "failure_id",
    "diagnostic_id",
    "settled_at",
  ]) {
    requireNullableString(reconciliation[field], `workspace.reconciliation.${field}`);
  }
  if (reconciliation.result_receipt_digest !== null) {
    requireDigest(
      reconciliation.result_receipt_digest,
      "workspace.reconciliation.result_receipt_digest",
    );
  }
  if (
    reconciliation.mutation_applied !== null
    && typeof reconciliation.mutation_applied !== "boolean"
  ) {
    throw new Error("workspace reconciliation mutation fact is invalid");
  }
  const terminal = ["ready", "blocked"].includes(reconciliation.status);
  if (
    terminal !== (reconciliation.result_receipt_id !== null)
    || terminal !== (reconciliation.result_receipt_digest !== null)
    || terminal !== (reconciliation.settled_at !== null)
    || (reconciliation.status === "ready" && (
      reconciliation.effect_certainty !== "terminal_known"
      || reconciliation.mutation_applied !== true
      || reconciliation.reconcile_required
      || reconciliation.failure_id !== null
      || reconciliation.diagnostic_id !== null
    ))
    || (reconciliation.status === "blocked" && (
      reconciliation.failure_id === null
      || reconciliation.diagnostic_id === null
      || (reconciliation.effect_certainty === "no_effect" && (
        reconciliation.mutation_applied !== false
        || reconciliation.reconcile_required
      ))
      || (reconciliation.effect_certainty === "dispatch_in_doubt" && (
        reconciliation.mutation_applied !== null
        || !reconciliation.reconcile_required
      ))
      || (["effect_known", "terminal_known"].includes(
        reconciliation.effect_certainty,
      ) && (
        typeof reconciliation.mutation_applied !== "boolean"
        || reconciliation.reconcile_required
      ))
      || ![
        "no_effect", "dispatch_in_doubt", "effect_known", "terminal_known",
      ].includes(reconciliation.effect_certainty)
    ))
    || (!terminal && (
      reconciliation.effect_certainty !== null
      || reconciliation.mutation_applied !== null
      || reconciliation.reconcile_required
      || reconciliation.failure_id !== null
      || reconciliation.diagnostic_id !== null
    ))
  ) {
    throw new Error("workspace reconciliation settlement is invalid");
  }
}

function requireResidentProvisioningConsistency(core) {
  const readiness = core.session.resident_readiness;
  const provisioning = core.workspace.provisioning;
  const reconciliation = provisioning.reconciliation;
  const effectiveReady = reconciliation !== null
    ? reconciliation.status === "ready"
    : provisioning.status === "ready";
  const expectedReadiness = reconciliation !== null
    ? (effectiveReady ? "ready" : "blocked")
    : {
      pending: "provisioning",
      claimed: "provisioning",
      ready: "ready",
      blocked: "blocked",
      cancelled: "blocked",
    }[provisioning.status];
  const expectedFailureId = reconciliation === null
    ? provisioning.failure_id
    : reconciliation.status === "ready"
      ? null
      : reconciliation.status === "blocked"
        ? reconciliation.failure_id
        : provisioning.failure_id;
  if (
    readiness.readiness !== expectedReadiness
    || readiness.workspace_id !== provisioning.workspace_id
    || readiness.workspace_generation !== provisioning.workspace_generation
    || readiness.provisioning_intent_id !== provisioning.intent_id
    || readiness.provisioning_intent_digest !== provisioning.intent_digest
    || readiness.failure_id !== expectedFailureId
  ) {
    throw new Error("resident readiness differs from workspace provisioning truth");
  }
  if (
    effectiveReady !== (provisioning.runtime_binding_id !== null)
  ) {
    throw new Error("workspace readiness and runtime binding identity differ");
  }
  if (readiness.failure_id !== null) {
    const matches = core.failures.observations.filter(
      (item) => item?.failure_id === readiness.failure_id,
    );
    if (matches.length !== 1) {
      throw new Error("resident readiness failure does not resolve exactly once");
    }
  }
}

function requireWorkflowAuthorityProjection(runtime) {
  const authority = runtime.workflow_authority;
  requireExactKeys(
    authority,
    ["bindings", "schema_version", "signal_links"],
    "core.runtime.workflow_authority",
  );
  if (
    authority.schema_version !== "workflow_authority_projection@1"
    || !Array.isArray(authority.bindings)
    || !Array.isArray(authority.signal_links)
    || authority.bindings.some((item) => item?.schema_version !== "workflow_authority_binding@1")
    || authority.signal_links.some((item) => item?.schema_version !== "runtime_signal_authority_link@1")
  ) {
    throw new Error("workflow authority projection is invalid");
  }
}

const RUNTIME_COMMAND_FIELDS = Object.freeze([
  "accepted_at",
  "auto_enqueue_ready_tasks",
  "bounded_outcome_summary",
  "claim_owner",
  "command_id",
  "command_type",
  "completed_at",
  "diagnostic_id",
  "error_code",
  "failure_id",
  "fencing_token",
  "idempotency_key",
  "lease_expires_at",
  "max_signals",
  "max_steps_per_agent",
  "request_digest",
  "safe_error_summary",
  "safe_retry_hint",
  "schema_version",
  "session_id",
  "started_at",
  "state_version",
  "status",
]);

const RUNTIME_COMMAND_OUTCOME_SUMMARY_FIELDS = Object.freeze([
  "fallback_performed",
  "processed_signals",
  "runtime_executed",
  "schema_version",
  "task_transition_performed",
  "turn_count",
  "turns_digest",
]);

const RUNTIME_TURN_COMMAND_FIELDS = Object.freeze([
  "adapter_bundle_digest",
  "affordance_snapshot_digest",
  "affordance_snapshot_id",
  "agent_id",
  "agent_member_id",
  "capability_binding_digest",
  "capability_binding_id",
  "capability_binding_revision",
  "command_id",
  "context_digest",
  "continuation_id",
  "declared_tool_catalog_digest",
  "distribution_id",
  "distribution_manifest_digest",
  "extension_bundle_digest",
  "lane_id",
  "max_duration_seconds",
  "max_input_units",
  "max_output_units",
  "max_steps",
  "message_count",
  "process_epoch",
  "release_digest",
  "runtime_adapter_contract_digest",
  "runtime_adapter_id",
  "runtime_fence",
  "runtime_lease_generation",
  "schema_version",
  "session_id",
  "signal_attempt",
  "signal_authority_link_digest",
  "signal_id",
  "source_command_digest",
  "task_id",
  "tool_exposure_snapshot_digest",
  "tool_exposure_snapshot_id",
  "turn_id",
  "workflow_authority_digest",
  "workflow_authority_epoch",
  "workflow_authority_id",
]);

const RUNTIME_OUTCOME_RECEIPT_FIELDS = Object.freeze([
  "accepted_at",
  "outcome",
  "receipt_id",
  "schema_version",
  "source_receipt_digest",
]);

const RUNTIME_OUTCOME_FIELDS = Object.freeze([
  "agent_id",
  "agent_member_id",
  "command_id",
  "continuation_id",
  "correlation_id",
  "disposition",
  "failure",
  "lane_id",
  "message_count",
  "outcome_id",
  "process_epoch",
  "runtime_fence",
  "runtime_lease_generation",
  "schema_version",
  "session_id",
  "signal_attempt",
  "signal_id",
  "source_command_digest",
  "source_outcome_digest",
  "summary",
  "task_id",
  "tool_exposure_snapshot_digest",
  "tool_exposure_snapshot_id",
  "tool_request_count",
  "tool_request_digest",
  "turn_id",
  "usage",
  "waiting_approval_id",
  "workflow_authority_digest",
  "workflow_authority_epoch",
  "workflow_authority_id",
]);

const RUNTIME_USAGE_FIELDS = Object.freeze([
  "input_units",
  "output_units",
  "provider_reported",
  "schema_version",
  "total_units",
]);

const RUNTIME_FAILURE_PUBLIC_FIELDS = Object.freeze([
  "diagnostic_id",
  "effect_certainty",
  "error_code",
  "failure_id",
  "fallback_performed",
  "mutation_applied",
  "next_action",
  "reconcile_required",
  "safe_summary",
  "schema_version",
]);

const RUNTIME_OUTCOME_CONSUMPTION_FIELDS = Object.freeze([
  "agent_id",
  "agent_member_id",
  "command_digest",
  "command_id",
  "consumed_at",
  "consumption_digest",
  "consumption_id",
  "continuation_intent_id",
  "outcome_digest",
  "outcome_id",
  "outcome_receipt_digest",
  "outcome_receipt_id",
  "schema_version",
  "session_id",
  "settlement_intent_id",
  "signal_attempt",
  "signal_id",
]);

const FAILURE_OBSERVATION_FIELDS = Object.freeze([
  "actor_kind",
  "agent_id",
  "cause_chain",
  "component",
  "created_at",
  "diagnostic_id",
  "effect_certainty",
  "error_code",
  "evidence_refs",
  "facts",
  "failure_class",
  "failure_id",
  "fallback_performed",
  "identities",
  "lane_id",
  "likely_causes",
  "mutation_applied",
  "next_action",
  "operation",
  "phase",
  "recoverability",
  "retry_eligibility",
  "safe_hint",
  "safe_summary",
  "schema_version",
  "session_id",
  "source_kind",
  "source_ref",
  "source_version",
  "task_id",
]);

const FAILURE_PUBLIC_FACT_FIELDS = new Set([
  "active_epoch_id",
  "capability_id",
  "component_id",
  "distribution_id",
  "driver_id",
  "epoch_id",
  "expected_digest",
  "expected_manifest_digest",
  "fallback_performed",
  "missing_ids",
  "missing_kinds",
  "missing_port_contracts",
  "mutation_applied",
  "observed_digest",
  "observed_manifest_digest",
  "plugin_id",
  "plugin_ids",
  "prior_output_message_count",
  "prior_tool_request_count",
  "process_epoch",
  "provider_backend_identity_digest",
  "provider_id",
  "provider_plugin_ids",
  "reconcile_required",
  "requested_epoch_id",
  "retry_eligibility",
  "retry_performed",
  "route_id",
  "route_ids",
  "session_id",
  "surface",
  "surface_kind",
  "target_id",
  "tool_exposure_snapshot_id",
  "unexpected_ids",
  "unexpected_kinds",
  "verification_kind",
  "workflow_authority_epoch",
  "workflow_authority_id",
  "workspace_generation",
]);

const FAILURE_PUBLIC_IDENTITY_FIELDS = new Set([
  "agent_member_id",
  "authority_id",
  "capability_id",
  "command_id",
  "component_id",
  "correlation_id",
  "distribution_id",
  "driver_id",
  "intent_id",
  "lane_id",
  "plugin_id",
  "process_identity",
  "provider_id",
  "request_id",
  "route_id",
  "session_id",
  "signal_id",
  "source_ref",
  "source_version",
  "target_id",
  "task_id",
  "tool_exposure_snapshot_id",
  "workflow_authority_id",
  "workspace_id",
]);

const FAILURE_CLASSES = new Set([
  "validation",
  "tool",
  "provider",
  "controlled_effect",
  "harness",
  "runtime",
  "system",
]);
const FAILURE_RECOVERABILITY = new Set([
  "agent_can_retry",
  "agent_can_replan",
  "reconciliation_required",
  "authorization_required",
  "runtime_retry",
  "terminal",
]);
const FAILURE_EFFECT_CERTAINTY = new Set([
  "no_effect",
  "dispatch_in_doubt",
  "effect_known",
  "terminal_known",
]);
const FAILURE_RETRY_ELIGIBILITY = new Set([
  "same_phase_safe",
  "verify_then_retry",
  "reconcile_required",
  "terminal",
]);
const FAILURE_ACTOR_KINDS = new Set(["harness", "system", "agent"]);
const PUBLIC_FAILURE_UNSAFE_TEXT_PATTERNS = Object.freeze([
  /\bBearer\s+[A-Za-z0-9._~+/=-]+/i,
  /\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b/,
  /(?:authorization|cookie|set[_-]?cookie|password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s&,]+/i,
  /(?:storage|s3|gs|gcs|azure|ssh|scp|file|postgres|postgresql|redis|mongodb(?:\+srv)?|mysql|mariadb|amqp|amqps):\/\//i,
  /(?:^|[\s"'<>(:;,])(?:\/(?:app|cluster|code|data|etc|gpfs|home|lustre|mnt|opt|private|project|root|run|scratch|srv|tmp|usr|var|Users)\/|~\/|[A-Za-z]:[\\/])/,
]);

function requirePositiveInteger(value, field) {
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`${field} must be a positive integer`);
  }
}

function requireRuntimeCommandOutcomeSummary(summary) {
  if (summary === null) return;
  requireExactKeys(
    summary,
    RUNTIME_COMMAND_OUTCOME_SUMMARY_FIELDS,
    "runtime command outcome summary",
  );
  if (
    summary.schema_version !== "runtime_command_outcome_summary_public@1"
    || !Number.isInteger(summary.processed_signals)
    || summary.processed_signals < 0
    || summary.processed_signals > 1_024
    || !Number.isInteger(summary.turn_count)
    || summary.turn_count < 0
    || summary.turn_count > 1_024
    || typeof summary.runtime_executed !== "boolean"
    || typeof summary.task_transition_performed !== "boolean"
    || typeof summary.fallback_performed !== "boolean"
  ) {
    throw new Error("runtime command outcome summary is invalid");
  }
  requireDigest(summary.turns_digest, "runtime command outcome summary turns_digest");
  if (summary.turn_count !== summary.processed_signals) {
    throw new Error("runtime command outcome summary turn count is inconsistent");
  }
  if (summary.fallback_performed) {
    throw new Error("runtime command outcome summary cannot report fallback");
  }
  if (summary.runtime_executed !== (summary.processed_signals > 0)) {
    throw new Error("runtime command outcome summary execution fact is inconsistent");
  }
}

function requireRuntimeTurnCommand(command, expectedSessionId, expectedRelease) {
  requireExactKeys(
    command,
    RUNTIME_TURN_COMMAND_FIELDS,
    "runtime turn command",
  );
  if (command.schema_version !== "runtime_turn_command_public@1") {
    throw new Error("runtime turn command schema version is invalid");
  }
  for (const field of [
    "command_id",
    "turn_id",
    "session_id",
    "agent_id",
    "agent_member_id",
    "signal_id",
    "distribution_id",
    "capability_binding_id",
    "affordance_snapshot_id",
    "workflow_authority_id",
    "tool_exposure_snapshot_id",
    "runtime_adapter_id",
  ]) {
    requireIdentifier(command[field], `runtime turn command ${field}`);
  }
  for (const field of ["task_id", "lane_id", "continuation_id"]) {
    requireNullableIdentifier(command[field], `runtime turn command ${field}`);
  }
  for (const field of [
    "distribution_manifest_digest",
    "release_digest",
    "adapter_bundle_digest",
    "extension_bundle_digest",
    "declared_tool_catalog_digest",
    "capability_binding_digest",
    "affordance_snapshot_digest",
    "workflow_authority_digest",
    "signal_authority_link_digest",
    "tool_exposure_snapshot_digest",
    "context_digest",
    "runtime_adapter_contract_digest",
    "source_command_digest",
  ]) {
    requireDigest(command[field], `runtime turn command ${field}`);
  }
  for (const field of [
    "signal_attempt",
    "runtime_lease_generation",
    "runtime_fence",
    "process_epoch",
    "capability_binding_revision",
    "workflow_authority_epoch",
    "message_count",
    "max_steps",
    "max_duration_seconds",
    "max_input_units",
    "max_output_units",
  ]) {
    requirePositiveInteger(command[field], `runtime turn command ${field}`);
  }
  if (command.message_count > 512) {
    throw new Error("runtime turn command message_count exceeds the public bound");
  }
  if (expectedSessionId !== undefined && command.session_id !== expectedSessionId) {
    throw new Error("runtime turn command belongs to another Session");
  }
  if (
    expectedRelease
    && (
      command.release_digest !== expectedRelease.release_digest
      || command.adapter_bundle_digest !== expectedRelease.adapter_bundle_digest
      || command.extension_bundle_digest !== expectedRelease.extension_bundle_digest
      || command.declared_tool_catalog_digest
        !== expectedRelease.declared_tool_catalog_digest
    )
  ) {
    throw new Error("runtime turn command release identity drifted");
  }
}

function requireRuntimeUsage(usage) {
  if (usage === null) return;
  requireExactKeys(usage, RUNTIME_USAGE_FIELDS, "runtime usage");
  if (usage.schema_version !== "runtime_usage@1") {
    throw new Error("runtime usage schema version is invalid");
  }
  for (const field of ["input_units", "output_units", "total_units"]) {
    if (!Number.isInteger(usage[field]) || usage[field] < 0) {
      throw new Error(`runtime usage ${field} is invalid`);
    }
  }
  if (usage.total_units < usage.input_units + usage.output_units) {
    throw new Error("runtime usage total is smaller than its components");
  }
  if (typeof usage.provider_reported !== "boolean") {
    throw new Error("runtime usage provider_reported must be boolean");
  }
}

function requireRuntimeFailurePublic(failure) {
  if (failure === null) return;
  requireExactKeys(
    failure,
    RUNTIME_FAILURE_PUBLIC_FIELDS,
    "runtime failure summary",
  );
  if (failure.schema_version !== "runtime_failure_public@1") {
    throw new Error("runtime failure summary schema version is invalid");
  }
  for (const field of [
    "failure_id",
    "error_code",
    "diagnostic_id",
    "next_action",
  ]) {
    requireIdentifier(failure[field], `runtime failure ${field}`);
  }
  if (
    typeof failure.safe_summary !== "string"
    || !failure.safe_summary
    || failure.safe_summary.length > 16_384
  ) {
    throw new Error("runtime failure safe_summary must be bounded");
  }
  if (
    typeof failure.fallback_performed !== "boolean"
    || typeof failure.reconcile_required !== "boolean"
    || (
      failure.mutation_applied !== null
      && typeof failure.mutation_applied !== "boolean"
    )
  ) {
    throw new Error("runtime failure effect facts are invalid");
  }
  if (failure.effect_certainty === "no_effect") {
    if (failure.mutation_applied !== false || failure.reconcile_required) {
      throw new Error("no-effect runtime failure facts are inconsistent");
    }
  } else if (failure.effect_certainty === "dispatch_in_doubt") {
    if (failure.mutation_applied !== null || !failure.reconcile_required) {
      throw new Error("uncertain runtime failure facts are inconsistent");
    }
  } else if (["effect_known", "terminal_known"].includes(failure.effect_certainty)) {
    if (
      typeof failure.mutation_applied !== "boolean"
      || failure.reconcile_required
    ) {
      throw new Error("known runtime failure facts are inconsistent");
    }
  } else {
    throw new Error("runtime failure effect certainty is invalid");
  }
}

function requireRuntimeOutcomeReceipt(receipt, expectedSessionId) {
  requireExactKeys(
    receipt,
    RUNTIME_OUTCOME_RECEIPT_FIELDS,
    "runtime turn outcome receipt",
  );
  if (receipt.schema_version !== "runtime_turn_outcome_receipt_public@1") {
    throw new Error("runtime turn outcome receipt schema version is invalid");
  }
  requireIdentifier(receipt.receipt_id, "runtime outcome receipt_id");
  requireIdentifier(receipt.accepted_at, "runtime outcome accepted_at");
  requireDigest(
    receipt.source_receipt_digest,
    "runtime outcome source_receipt_digest",
  );
  const outcome = receipt.outcome;
  requireExactKeys(outcome, RUNTIME_OUTCOME_FIELDS, "runtime turn outcome");
  if (outcome.schema_version !== "runtime_turn_outcome_public@1") {
    throw new Error("runtime turn outcome schema version is invalid");
  }
  for (const field of [
    "outcome_id",
    "command_id",
    "turn_id",
    "session_id",
    "agent_id",
    "agent_member_id",
    "signal_id",
    "workflow_authority_id",
    "tool_exposure_snapshot_id",
  ]) {
    requireIdentifier(outcome[field], `runtime outcome ${field}`);
  }
  for (const field of [
    "continuation_id",
    "waiting_approval_id",
    "task_id",
    "lane_id",
    "correlation_id",
  ]) {
    requireNullableIdentifier(outcome[field], `runtime outcome ${field}`);
  }
  for (const field of [
    "source_command_digest",
    "workflow_authority_digest",
    "tool_exposure_snapshot_digest",
    "tool_request_digest",
    "source_outcome_digest",
  ]) {
    requireDigest(outcome[field], `runtime outcome ${field}`);
  }
  for (const field of [
    "signal_attempt",
    "runtime_lease_generation",
    "runtime_fence",
    "process_epoch",
    "workflow_authority_epoch",
  ]) {
    requirePositiveInteger(outcome[field], `runtime outcome ${field}`);
  }
  if (
    !Number.isInteger(outcome.message_count)
    || outcome.message_count < 0
    || outcome.message_count > 512
    || !Number.isInteger(outcome.tool_request_count)
    || outcome.tool_request_count < 0
    || outcome.tool_request_count > 64
  ) {
    throw new Error("runtime outcome message/tool request counts are invalid");
  }
  if (
    typeof outcome.summary !== "string"
    || !outcome.summary
    || outcome.summary.length > 16_384
    || ![
      "ready_for_next_step",
      "waiting_approval",
      "waiting_continuation",
      "idle",
      "step_limit_reached",
      "failed",
    ].includes(outcome.disposition)
  ) {
    throw new Error("runtime turn outcome summary or disposition is invalid");
  }
  requireRuntimeUsage(outcome.usage);
  requireRuntimeFailurePublic(outcome.failure);
  if ((outcome.disposition === "failed") !== (outcome.failure !== null)) {
    throw new Error("runtime turn outcome failure and disposition differ");
  }
  if (
    (outcome.disposition === "waiting_approval")
      !== (outcome.waiting_approval_id !== null)
  ) {
    throw new Error("runtime outcome approval wait identity is inconsistent");
  }
  if (
    (outcome.disposition === "waiting_continuation")
      !== (outcome.continuation_id !== null)
  ) {
    throw new Error("runtime outcome continuation identity is inconsistent");
  }
  if (expectedSessionId !== undefined && outcome.session_id !== expectedSessionId) {
    throw new Error("runtime outcome belongs to another Session");
  }
}

function requireRuntimeOutcomeConsumptions(consumptions, expectedSessionId) {
  if (!Array.isArray(consumptions) || consumptions.length > 4_096) {
    throw new Error("runtime outcome consumptions must be a bounded array");
  }
  const consumptionIds = new Set();
  for (const consumption of consumptions) {
    requireExactKeys(
      consumption,
      RUNTIME_OUTCOME_CONSUMPTION_FIELDS,
      "runtime outcome consumption",
    );
    if (consumption.schema_version !== "runtime_outcome_consumption_public@1") {
      throw new Error("runtime outcome consumption schema version is invalid");
    }
    for (const field of [
      "consumption_id",
      "command_id",
      "outcome_id",
      "outcome_receipt_id",
      "session_id",
      "agent_id",
      "agent_member_id",
      "signal_id",
      "settlement_intent_id",
    ]) {
      requireIdentifier(consumption[field], `runtime outcome consumption ${field}`);
    }
    requireNullableIdentifier(
      consumption.continuation_intent_id,
      "runtime outcome consumption continuation_intent_id",
    );
    for (const field of [
      "consumption_digest",
      "command_digest",
      "outcome_digest",
      "outcome_receipt_digest",
    ]) {
      requireDigest(consumption[field], `runtime outcome consumption ${field}`);
    }
    requirePositiveInteger(
      consumption.signal_attempt,
      "runtime outcome consumption signal_attempt",
    );
    if (
      typeof consumption.consumed_at !== "string"
      || !consumption.consumed_at
      || consumption.consumed_at.length > 256
    ) {
      throw new Error("runtime outcome consumption consumed_at is invalid");
    }
    if (consumption.session_id !== expectedSessionId) {
      throw new Error("runtime outcome consumption belongs to another Session");
    }
    if (consumptionIds.has(consumption.consumption_id)) {
      throw new Error("runtime outcome consumption identity is duplicated");
    }
    consumptionIds.add(consumption.consumption_id);
  }
}

function requireRuntimeCommands(
  runtime,
  expectedSessionId = undefined,
  expectedRelease = undefined,
) {
  if (
    runtime.commands.length > 4_096
    || runtime.turn_commands.length > 4_096
    || runtime.outcomes.length > 4_096
    || runtime.outcome_consumptions.length > 4_096
  ) {
    throw new Error("runtime command, turn and outcome projections must be bounded");
  }
  const commandIds = new Set();
  for (const command of runtime.commands) {
    requireExactKeys(command, RUNTIME_COMMAND_FIELDS, "runtime command");
    if (
      command.schema_version !== "runtime_command_public@1"
      || command.command_type !== "runtime.drain"
      || !["accepted", "claimed", "completed", "failed", "locked", "cancelled"].includes(
        command.status,
      )
      || !Number.isInteger(command.max_signals)
      || command.max_signals < 1
      || !Number.isInteger(command.max_steps_per_agent)
      || command.max_steps_per_agent < 1
      || !Number.isInteger(command.state_version)
      || command.state_version < 1
      || !Number.isInteger(command.fencing_token)
      || command.fencing_token < 0
      || typeof command.auto_enqueue_ready_tasks !== "boolean"
    ) {
      throw new Error("runtime command projection is invalid");
    }
    for (const field of ["command_id", "session_id", "idempotency_key", "accepted_at"]) {
      requireIdentifier(command[field], `runtime command ${field}`);
    }
    if (commandIds.has(command.command_id)) {
      throw new Error("runtime command identity is duplicated");
    }
    commandIds.add(command.command_id);
    if (expectedSessionId !== undefined && command.session_id !== expectedSessionId) {
      throw new Error("runtime command belongs to another Session");
    }
    requireDigest(command.request_digest, "runtime command request_digest");
    for (const field of [
      "claim_owner", "lease_expires_at", "failure_id", "diagnostic_id", "error_code",
      "started_at", "completed_at",
    ]) {
      requireNullableIdentifier(command[field], `runtime command ${field}`);
    }
    for (const field of ["safe_error_summary", "safe_retry_hint"]) {
      requireNullableBoundedText(command[field], `runtime command ${field}`);
    }
    requireRuntimeCommandOutcomeSummary(command.bounded_outcome_summary);
    if (
      command.status === "claimed"
      && ["claim_owner", "lease_expires_at", "started_at"]
        .some((field) => command[field] === null)
    ) {
      throw new Error("claimed runtime command lacks claim identity");
    }
    if (
      ["completed", "failed", "locked", "cancelled"].includes(command.status)
      && command.completed_at === null
    ) {
      throw new Error("terminal runtime command lacks completion identity");
    }
    if (
      command.status === "failed"
      && (command.failure_id === null || command.diagnostic_id === null)
    ) {
      throw new Error("failed runtime command lacks failure identities");
    }
    if (
      command.status !== "failed"
      && (command.failure_id !== null || command.diagnostic_id !== null)
    ) {
      throw new Error("non-failed runtime command carries failure identities");
    }
  }

  const turnCommandIds = new Set();
  for (const command of runtime.turn_commands) {
    requireRuntimeTurnCommand(command, expectedSessionId, expectedRelease);
    if (turnCommandIds.has(command.command_id)) {
      throw new Error("runtime turn command identity is duplicated");
    }
    turnCommandIds.add(command.command_id);
  }

  const receiptIds = new Set();
  const outcomeIds = new Set();
  for (const receipt of runtime.outcomes) {
    requireRuntimeOutcomeReceipt(receipt, expectedSessionId);
    if (receiptIds.has(receipt.receipt_id)) {
      throw new Error("runtime outcome receipt identity is duplicated");
    }
    if (outcomeIds.has(receipt.outcome.outcome_id)) {
      throw new Error("runtime outcome identity is duplicated");
    }
    receiptIds.add(receipt.receipt_id);
    outcomeIds.add(receipt.outcome.outcome_id);
  }
  requireRuntimeOutcomeConsumptions(
    runtime.outcome_consumptions,
    expectedSessionId,
  );
}

export function requireRuntimeCommandStatusRecord(command, sessionId, commandId) {
  requireRuntimeCommands({
    commands: [command],
    outcome_consumptions: [],
    turn_commands: [],
    outcomes: [],
  }, sessionId);
  if (command.session_id !== sessionId || command.command_id !== commandId) {
    throw new Error("runtime command differs from the requested exact identity");
  }
  return structuredClone(command);
}

function requirePublicFailureFactValue(value, field, depth = 0) {
  if (typeof value === "boolean" || Number.isInteger(value)) return;
  if (typeof value === "string") {
    requirePublicFailureText(value, field);
    return;
  }
  if (Array.isArray(value) && value.length <= 64 && depth < 64) {
    value.forEach((item) => requirePublicFailureFactValue(item, field, depth + 1));
    return;
  }
  throw new Error(`${field} contains a non-public value`);
}

function requirePublicFailureMapping(value, allowedFields, field, identities = false) {
  if (
    !value
    || typeof value !== "object"
    || Array.isArray(value)
    || Object.keys(value).some((name) => !allowedFields.has(name))
  ) {
    throw new Error(`${field} fields are closed`);
  }
  for (const [name, item] of Object.entries(value)) {
    if (identities) {
      requirePublicFailureText(item, `${field}.${name}`);
    } else {
      requirePublicFailureFactValue(item, `${field}.${name}`);
    }
  }
}

function requireFailureObservations(failures, expectedSessionId) {
  const observations = failures.observations;
  if (!Array.isArray(observations) || observations.length > 4_096) {
    throw new Error("public failure observations must be a bounded array");
  }
  const failureIds = new Set();
  for (const failure of observations) {
    if (failure?.schema_version === "failure_observation@1") {
      throw new Error("legacy failure observation is not public-compatible");
    }
    requireExactKeys(
      failure,
      FAILURE_OBSERVATION_FIELDS,
      "public failure observation",
    );
    if (failure.schema_version !== "failure_observation@2") {
      throw new Error("public failure observation schema version is invalid");
    }
    requireIdentifier(failure.failure_id, "public failure failure_id");
    requireIdentifier(failure.session_id, "public failure session_id");
    if (failure.session_id !== expectedSessionId) {
      throw new Error("public failure observation belongs to another Session");
    }
    if (failureIds.has(failure.failure_id)) {
      throw new Error("public failure observation identity is duplicated");
    }
    failureIds.add(failure.failure_id);
    for (const field of [
      "phase",
      "error_code",
      "component",
      "operation",
      "diagnostic_id",
      "next_action",
    ]) {
      requireMachineIdentifier(failure[field], `public failure ${field}`);
    }
    requirePublicFailureText(failure.source_kind, "public failure source_kind", {
      max: 256,
    });
    for (const field of [
      "source_ref",
      "source_version",
      "safe_summary",
      "created_at",
    ]) {
      requirePublicFailureText(failure[field], `public failure ${field}`);
    }
    requirePublicFailureText(failure.safe_hint, "public failure safe_hint", {
      nullable: true,
    });
    for (const field of ["task_id", "lane_id", "agent_id"]) {
      requireNullableIdentifier(failure[field], `public failure ${field}`);
    }
    if (
      !FAILURE_CLASSES.has(failure.failure_class)
      || !FAILURE_RECOVERABILITY.has(failure.recoverability)
      || !FAILURE_EFFECT_CERTAINTY.has(failure.effect_certainty)
      || !FAILURE_RETRY_ELIGIBILITY.has(failure.retry_eligibility)
      || !FAILURE_ACTOR_KINDS.has(failure.actor_kind)
    ) {
      throw new Error("public failure classification facts are invalid");
    }
    if (
      (failure.mutation_applied !== null
        && typeof failure.mutation_applied !== "boolean")
      || typeof failure.fallback_performed !== "boolean"
    ) {
      throw new Error("public failure mutation/fallback facts are invalid");
    }
    requirePublicFailureMapping(
      failure.facts,
      FAILURE_PUBLIC_FACT_FIELDS,
      "public failure facts",
    );
    requirePublicFailureMapping(
      failure.identities,
      FAILURE_PUBLIC_IDENTITY_FIELDS,
      "public failure identities",
      true,
    );
    for (const field of ["likely_causes", "evidence_refs"]) {
      const entries = failure[field];
      if (!Array.isArray(entries) || entries.length > 64) {
        throw new Error(`public failure ${field} must be a bounded array`);
      }
      entries.forEach((entry) => (
        requirePublicFailureText(entry, `public failure ${field}`)
      ));
    }
    if (!Array.isArray(failure.cause_chain) || failure.cause_chain.length > 64) {
      throw new Error("public failure cause_chain must be a bounded array");
    }
    for (const cause of failure.cause_chain) {
      requireExactKeys(
        cause,
        ["code", "message_digest", "type"],
        "public failure cause",
      );
      requireMachineIdentifier(cause.type, "public failure cause type");
      requireMachineIdentifier(cause.code, "public failure cause code");
      requireDigest(cause.message_digest, "public failure cause message_digest");
    }
  }
}

function requireOrderedTranscript(conversation) {
  const transcript = conversation.transcript;
  requireExactKeys(
    transcript,
    ["messages", "schema_version", "transcript_digest"],
    "core.conversation.transcript",
  );
  if (
    transcript.schema_version !== "ordered_transcript@1"
    || !Array.isArray(transcript.messages)
  ) {
    throw new Error("ordered transcript projection is invalid");
  }
  requireDigest(transcript.transcript_digest, "conversation.transcript_digest");
  const messageIds = new Set();
  transcript.messages.forEach((message, index) => {
    requireExactKeys(message, [
      "content",
      "correlation_id",
      "created_at",
      "message_id",
      "ordinal",
      "role",
      "schema_version",
      "source_command_id",
      "source_outcome_id",
      "tool_call_id",
    ], "ordered transcript message");
    if (
      message.schema_version !== "resident_transcript_message@1"
      || message.ordinal !== index + 1
      || !["user", "assistant", "tool"].includes(message.role)
      || typeof message.message_id !== "string"
      || !message.message_id
      || typeof message.content !== "string"
      || typeof message.created_at !== "string"
      || !message.created_at
      || messageIds.has(message.message_id)
    ) {
      throw new Error("ordered transcript message is invalid");
    }
    messageIds.add(message.message_id);
    for (const field of [
      "correlation_id",
      "tool_call_id",
      "source_command_id",
      "source_outcome_id",
    ]) {
      requireNullableString(message[field], `transcript message ${field}`);
    }
    if ((message.role === "tool") !== (message.tool_call_id !== null)) {
      throw new Error("tool transcript message identity is invalid");
    }
  });
}

function requireToolExposure(reflection) {
  const exposure = reflection.tool_exposure;
  requireExactKeys(exposure, [
    "command_expansions",
    "deferred_tool_names",
    "direct_tool_names",
    "exposure_snapshot_digest",
    "exposure_snapshot_id",
    "schema_version",
  ], "core.tool_reflection.tool_exposure");
  if (
    exposure.schema_version !== "tool_exposure_public@1"
    || typeof exposure.exposure_snapshot_id !== "string"
    || !exposure.exposure_snapshot_id
    || !Array.isArray(exposure.direct_tool_names)
    || !Array.isArray(exposure.deferred_tool_names)
    || !Array.isArray(exposure.command_expansions)
  ) {
    throw new Error("public tool exposure is invalid");
  }
  requireDigest(
    exposure.exposure_snapshot_digest,
    "tool_exposure.exposure_snapshot_digest",
  );
  const direct = new Set(exposure.direct_tool_names);
  const deferred = new Set(exposure.deferred_tool_names);
  if (
    direct.size !== exposure.direct_tool_names.length
    || deferred.size !== exposure.deferred_tool_names.length
    || [...direct].some((name) => deferred.has(name))
    || [...direct, ...deferred].some((name) => typeof name !== "string" || !name)
  ) {
    throw new Error("public Direct/Deferred tool names are invalid");
  }
  for (const expansion of exposure.command_expansions) {
    requireExactKeys(expansion, [
      "command_id",
      "expanded_tool_names",
      "expansion_digest",
      "expansion_id",
      "expansion_revision",
      "schema_version",
    ], "public command tool expansion");
    if (
      expansion.schema_version !== "command_tool_expansion_public@1"
      || typeof expansion.expansion_id !== "string"
      || !expansion.expansion_id
      || typeof expansion.command_id !== "string"
      || !expansion.command_id
      || !Number.isInteger(expansion.expansion_revision)
      || expansion.expansion_revision < 1
      || !Array.isArray(expansion.expanded_tool_names)
      || !expansion.expanded_tool_names.length
      || JSON.stringify(expansion.expanded_tool_names)
        !== JSON.stringify([...new Set(expansion.expanded_tool_names)].sort())
      || expansion.expanded_tool_names.some((name) => !deferred.has(name))
    ) {
      throw new Error("public command tool expansion is invalid");
    }
    requireDigest(expansion.expansion_digest, "command expansion digest");
  }
  return exposure;
}

function rejectExtensionFieldsInCore(value, path = "core") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => rejectExtensionFieldsInCore(item, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, nested] of Object.entries(value)) {
    const token = normalizedToken(key);
    if (
      FORBIDDEN_CORE_TOKENS.has(token)
      || FORBIDDEN_CORE_FRAGMENTS.some((fragment) => token.includes(fragment))
    ) {
      throw new Error(`file_workspace_public@2 core contains forbidden field ${path}.${key}`);
    }
    rejectExtensionFieldsInCore(nested, `${path}.${key}`);
  }
}

function requireRelease(release) {
  requireExactKeys(release, FILE_WORKSPACE_V2_RELEASE_FIELDS, "file_workspace_public@2 release");
  if (release.schema_version !== "openzyme_layered_release_identity@1") {
    throw new Error("file_workspace_public@2 release schema is unsupported");
  }
  for (const field of FILE_WORKSPACE_V2_RELEASE_FIELDS.filter((name) => name !== "schema_version")) {
    requireDigest(release[field], `release.${field}`);
  }
}

export function requireExactReleaseIdentity(observed, expected) {
  requireRelease(observed);
  requireRelease(expected);
  for (const field of FILE_WORKSPACE_V2_RELEASE_FIELDS) {
    if (observed[field] !== expected[field]) {
      throw new Error(`file_workspace_public@2 release identity drift: ${field}`);
    }
  }
  return structuredClone(observed);
}

function requireToolReflection(core, release) {
  const reflection = core.tool_reflection;
  requireExactKeys(reflection, TOOL_REFLECTION_FIELDS, "core.tool_reflection");
  requireDigest(reflection.declared_tool_catalog_digest, "tool_reflection.declared_tool_catalog_digest");
  requireDigest(reflection.affordance_snapshot_digest, "tool_reflection.affordance_snapshot_digest");
  requireDigest(reflection.capability_binding_digest, "tool_reflection.capability_binding_digest");
  requireDigest(core.capability_binding.binding_digest, "capability_binding.binding_digest");
  if (reflection.declared_tool_catalog_digest !== release.declared_tool_catalog_digest) {
    throw new Error("tool reflection belongs to another declared catalog");
  }
  if (reflection.capability_binding_digest !== core.capability_binding.binding_digest) {
    throw new Error("tool reflection belongs to another capability binding");
  }
  if (!Array.isArray(reflection.available_tool_names) || !Array.isArray(reflection.affordances)) {
    throw new Error("tool reflection collections are invalid");
  }
  const observed = new Set();
  const visible = [];
  for (const affordance of reflection.affordances) {
    requireExactKeys(affordance, TOOL_AFFORDANCE_FIELDS, "tool affordance");
    if (typeof affordance.tool_name !== "string" || !affordance.tool_name) {
      throw new Error("tool affordance name is invalid");
    }
    if (observed.has(affordance.tool_name)) {
      throw new Error("tool affordance name is duplicated");
    }
    observed.add(affordance.tool_name);
    requireDigest(affordance.tool_contract_digest, `${affordance.tool_name}.tool_contract_digest`);
    if (!PUBLIC_TOOL_STATES.has(affordance.state)) {
      throw new Error("tool affordance state is invalid");
    }
    for (const field of ["blockers", "required_authorities", "route_ids", "route_refs"]) {
      if (!Array.isArray(affordance[field])) {
        throw new Error(`tool affordance ${field} is invalid`);
      }
    }
    if (affordance.state === "available" || affordance.state === "available_with_approval") {
      if (affordance.blockers.length) {
        throw new Error("available tool affordance contains blockers");
      }
      visible.push(affordance.tool_name);
    }
  }
  const exposure = requireToolExposure(reflection);
  const disclosed = new Set([
    ...exposure.direct_tool_names,
    ...exposure.deferred_tool_names,
  ]);
  if (
    observed.size !== disclosed.size
    || [...observed].some((name) => !disclosed.has(name))
  ) {
    throw new Error("public affordances differ from Direct/Deferred exposure");
  }
  const direct = new Set(exposure.direct_tool_names);
  const callable = visible.filter((name) => direct.has(name));
  if (JSON.stringify(reflection.available_tool_names) !== JSON.stringify(callable)) {
    throw new Error("available tool names differ from callable Direct affordances");
  }
}

function requireCore(core, release) {
  requireExactKeys(core, FILE_WORKSPACE_V2_CORE_FIELDS, "file_workspace_public@2 core");
  for (const field of FILE_WORKSPACE_V2_CORE_FIELDS) {
    if (ARRAY_CORE_FIELDS.has(field)) {
      if (!Array.isArray(core[field])) {
        throw new Error(`file_workspace_public@2 core.${field} must be an array`);
      }
    } else if (!core[field] || typeof core[field] !== "object" || Array.isArray(core[field])) {
      throw new Error(`file_workspace_public@2 core.${field} must be an object`);
    }
  }
  for (const [section, fields] of Object.entries(OBJECT_SECTION_FIELDS)) {
    requireExactKeys(core[section], Object.keys(fields), `core.${section}`);
    for (const [field, kind] of Object.entries(fields)) {
      const value = core[section][field];
      if (kind === "array" && !Array.isArray(value)) {
        throw new Error(`core.${section}.${field} must be an array`);
      }
      if (
        kind === "object"
        && (!value || typeof value !== "object" || Array.isArray(value))
      ) {
        throw new Error(`core.${section}.${field} must be an object`);
      }
    }
  }
  requireResidentReadiness(core.session);
  requireProvisioningProjection(core.workspace);
  requireFailureObservations(core.failures, core.session.session_id);
  requireResidentProvisioningConsistency(core);
  requireWorkflowAuthorityProjection(core.runtime);
  requireRuntimeCommands(core.runtime, core.session.session_id, release);
  requireOrderedTranscript(core.conversation);
  rejectExtensionFieldsInCore(core);
  requireToolReflection(core, release);
}

function requireExtensionSections(extensions) {
  if (!extensions || typeof extensions !== "object" || Array.isArray(extensions)) {
    throw new Error("file_workspace_public@2 extensions must be an object");
  }
  for (const [sectionId, section] of Object.entries(extensions)) {
    if (!sectionId || sectionId.trim() !== sectionId) {
      throw new Error("extension section id is invalid");
    }
    requireExactKeys(
      section,
      ["next_cursor", "payload", "projection_digest", "section_contract_digest"],
      `extensions.${sectionId}`,
    );
    requireDigest(section.section_contract_digest, `${sectionId}.section_contract_digest`);
    requireDigest(section.projection_digest, `${sectionId}.projection_digest`);
    if (section.next_cursor !== null && typeof section.next_cursor !== "string") {
      throw new Error(`${sectionId}.next_cursor is invalid`);
    }
    if (!section.payload || typeof section.payload !== "object" || Array.isArray(section.payload)) {
      throw new Error(`${sectionId}.payload must be an object`);
    }
  }
}

export function requireFileWorkspaceV2Projection(payload) {
  requireExactKeys(payload, ["core", "extensions", "release", "schema_version"], "file_workspace_public@2");
  if (payload.schema_version !== FILE_WORKSPACE_PUBLIC_V2_SCHEMA) {
    throw new Error("unsupported file_workspace_public@2 schema");
  }
  requireRelease(payload.release);
  requireCore(payload.core, payload.release);
  requireExtensionSections(payload.extensions);
  return structuredClone(payload);
}

function sortedUniqueIdentifiers(values, field) {
  if (!Array.isArray(values)) throw new Error(`${field} must be an array`);
  const sorted = [...new Set(values)].sort();
  if (
    JSON.stringify(values) !== JSON.stringify(sorted)
    || values.some((value) => {
      try {
        requireIdentifier(value, field);
        return false;
      } catch {
        return true;
      }
    })
  ) {
    throw new Error(`${field} must contain sorted unique exact identities`);
  }
  return sorted;
}

function projectionChangeFacts(core) {
  const readiness = core.session.resident_readiness;
  const provisioning = core.workspace.provisioning;
  const commands = core.runtime.commands;
  const latest = commands.length ? commands[commands.length - 1] : null;
  return {
    schema_version: FILE_WORKSPACE_PROJECTION_OBSERVATION_FACTS_SCHEMA,
    readiness: readiness.readiness,
    next_action: readiness.next_action,
    workspace_id: readiness.workspace_id,
    workspace_generation: readiness.workspace_generation,
    provisioning_intent_id: readiness.provisioning_intent_id,
    provisioning_intent_state_version: provisioning.intent_state_version,
    transcript_digest: core.conversation.transcript.transcript_digest,
    pending_signal_count: core.runtime.signals.filter(
      (signal) => signal?.status === "pending",
    ).length,
    runtime_command_count: commands.length,
    latest_runtime_command: latest === null
      ? null
      : {
        schema_version: "runtime_command_projection_fact@1",
        command_id: latest.command_id,
        status: latest.status,
        state_version: latest.state_version,
      },
    pending_approval_ids: core.approvals
      .filter((approval) => approval?.status === "pending")
      .map((approval) => approval.approval_id)
      .sort(),
    failure_ids: core.failures.observations
      .map((failure) => failure?.failure_id)
      .filter((failureId) => typeof failureId === "string" && failureId)
      .sort(),
  };
}

function requireProjectionObservationFacts(facts) {
  requireExactKeys(
    facts,
    PROJECTION_OBSERVATION_FACT_FIELDS,
    "workspace projection change facts",
  );
  if (
    facts.schema_version !== FILE_WORKSPACE_PROJECTION_OBSERVATION_FACTS_SCHEMA
    || !["provisioning", "ready", "blocked"].includes(facts.readiness)
    || typeof facts.next_action !== "string"
    || !facts.next_action
    || !Number.isInteger(facts.workspace_generation)
    || facts.workspace_generation < 1
    || !Number.isInteger(facts.provisioning_intent_state_version)
    || facts.provisioning_intent_state_version < 1
    || !Number.isInteger(facts.pending_signal_count)
    || facts.pending_signal_count < 0
    || !Number.isInteger(facts.runtime_command_count)
    || facts.runtime_command_count < 0
  ) {
    throw new Error("workspace projection change facts are invalid");
  }
  for (const field of ["workspace_id", "provisioning_intent_id"]) {
    requireIdentifier(facts[field], `workspace projection observation ${field}`);
  }
  requireDigest(
    facts.transcript_digest,
    "workspace projection observation transcript_digest",
  );
  sortedUniqueIdentifiers(
    facts.pending_approval_ids,
    "workspace projection observation pending_approval_ids",
  );
  sortedUniqueIdentifiers(
    facts.failure_ids,
    "workspace projection observation failure_ids",
  );
  if (facts.latest_runtime_command !== null) {
    requireExactKeys(
      facts.latest_runtime_command,
      PROJECTION_OBSERVATION_RUNTIME_COMMAND_FIELDS,
      "workspace projection observation latest runtime command",
    );
    if (
      facts.latest_runtime_command.schema_version !== "runtime_command_projection_fact@1"
      || !["accepted", "claimed", "completed", "failed", "locked", "cancelled"]
        .includes(facts.latest_runtime_command.status)
      || !Number.isInteger(facts.latest_runtime_command.state_version)
      || facts.latest_runtime_command.state_version < 1
    ) {
      throw new Error("workspace projection observation runtime command fact is invalid");
    }
    requireIdentifier(
      facts.latest_runtime_command.command_id,
      "workspace projection observation runtime command_id",
    );
  }
}

export function requireFileWorkspaceV2ProjectionObservation(observation, options = {}) {
  requireExactKeys(
    observation,
    PROJECTION_OBSERVATION_FIELDS,
    "workspace projection change observation",
  );
  if (
    observation.schema_version !== FILE_WORKSPACE_PROJECTION_OBSERVATION_SCHEMA
    || observation.observation_kind !== "workspace_projection_change"
    || observation.source !== "verified_workspace_projection_poll"
  ) {
    throw new Error("workspace projection observation contract is unsupported");
  }
  for (const field of [
    "observation_id",
    "projection_digest",
    "release_digest",
    "public_contract_digest",
  ]) {
    requireDigest(observation[field], `workspace projection observation ${field}`);
  }
  if (observation.observation_id !== observation.projection_digest) {
    throw new Error("workspace projection observation identity differs from its projection");
  }
  if (observation.previous_projection_digest !== null) {
    requireDigest(
      observation.previous_projection_digest,
      "workspace projection observation previous_projection_digest",
    );
    if (observation.previous_projection_digest === observation.projection_digest) {
      throw new Error("workspace projection observation did not advance projection identity");
    }
  }
  requireIdentifier(observation.session_id, "workspace projection observation session_id");
  requireProjectionObservationFacts(observation.facts);
  if (
    options.expectedRelease
    && (
      observation.release_digest !== options.expectedRelease.release_digest
      || observation.public_contract_digest
        !== options.expectedRelease.public_contract_digest
    )
  ) {
    throw new Error("workspace projection observation release identity drifted");
  }
  if (
    options.expectedSessionId !== undefined
    && observation.session_id !== options.expectedSessionId
  ) {
    throw new Error("workspace projection observation Session identity drifted");
  }
  if (
    Object.hasOwn(options, "expectedPreviousProjectionDigest")
    && observation.previous_projection_digest
      !== options.expectedPreviousProjectionDigest
  ) {
    throw new Error("workspace projection observation cursor is stale");
  }
  if (
    options.expectedProjectionDigest !== undefined
    && observation.projection_digest !== options.expectedProjectionDigest
  ) {
    throw new Error("workspace projection observation body/header identity drifted");
  }
  if (
    options.expectedCore
    && JSON.stringify(observation.facts)
      !== JSON.stringify(projectionChangeFacts(options.expectedCore))
  ) {
    throw new Error("workspace projection observation facts differ from verified projection");
  }
  return structuredClone(observation);
}

export function buildFileWorkspaceV2ProjectionObservation({
  projection,
  projectionDigest,
  previousProjectionDigest = null,
}) {
  const canonical = requireFileWorkspaceV2Projection(projection);
  const observation = {
    schema_version: FILE_WORKSPACE_PROJECTION_OBSERVATION_SCHEMA,
    observation_id: projectionDigest,
    observation_kind: "workspace_projection_change",
    source: "verified_workspace_projection_poll",
    session_id: canonical.core.session.session_id,
    release_digest: canonical.release.release_digest,
    public_contract_digest: canonical.release.public_contract_digest,
    previous_projection_digest: previousProjectionDigest,
    projection_digest: projectionDigest,
    facts: projectionChangeFacts(canonical.core),
  };
  return requireFileWorkspaceV2ProjectionObservation(observation, {
    expectedRelease: canonical.release,
    expectedSessionId: canonical.core.session.session_id,
    expectedPreviousProjectionDigest: previousProjectionDigest,
    expectedProjectionDigest: projectionDigest,
    expectedCore: canonical.core,
  });
}

export function requireAvailableTool(coreState, toolName) {
  const affordance = coreState?.core?.tool_reflection?.affordances?.find(
    (item) => item.tool_name === toolName,
  );
  if (!affordance) {
    throw new Error(`tool ${toolName} is absent from the exact affordance snapshot`);
  }
  if (affordance.state !== "available" && affordance.state !== "available_with_approval") {
    const blockerCodes = affordance.blockers.map((item) => item.code).join(",") || affordance.state;
    throw new Error(`tool ${toolName} is blocked: ${blockerCodes}; fallback_performed=false`);
  }
  const direct = coreState?.core?.tool_reflection?.tool_exposure?.direct_tool_names;
  if (!Array.isArray(direct) || !direct.includes(toolName)) {
    throw new Error(
      `tool ${toolName} is Deferred or Hidden and is not callable; fallback_performed=false`,
    );
  }
  return structuredClone(affordance);
}

export function reduceFileWorkspaceV2ProjectionObservation(state, observation) {
  try {
    const previousProjectionDigest = state.projectionObservations.length
      ? state.projectionObservations[state.projectionObservations.length - 1]
        .projection_digest
      : null;
    const accepted = requireFileWorkspaceV2ProjectionObservation(observation, {
      expectedRelease: state.release,
      expectedSessionId: state.core.session.session_id,
      expectedPreviousProjectionDigest: previousProjectionDigest,
      expectedProjectionDigest: state.currentProjectionDigest,
      expectedCore: state.core,
    });
    return {
      ...state,
      refreshRequired: false,
      lastProjectionObservationId: accepted.observation_id,
      projectionObservations: [...state.projectionObservations, accepted]
        .slice(-FILE_WORKSPACE_PROJECTION_OBSERVATION_HISTORY_LIMIT),
    };
  } catch (error) {
    return {
      ...state,
      contractBlocked: true,
      mutationAllowed: false,
      messageAllowed: false,
      runtimeDrainAllowed: false,
      approvalDecisionAllowed: false,
      refreshRequired: false,
      blockingError: `workspace projection observation rejected: ${error.message}`,
    };
  }
}
