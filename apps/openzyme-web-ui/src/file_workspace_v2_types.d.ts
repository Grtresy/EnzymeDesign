export type Sha256Digest = `sha256:${string}`;

export type PublicToolAffordanceState =
  | "available"
  | "available_with_approval"
  | "blocked_dependency"
  | "blocked_configuration"
  | "blocked_qualification"
  | "blocked_authority"
  | "blocked_provisioning"
  | "temporarily_unavailable";

export interface PublicToolAffordance {
  tool_name: string;
  tool_contract_digest: Sha256Digest;
  state: PublicToolAffordanceState;
  required_authorities: string[];
  route_ids: string[];
  route_refs: Record<string, unknown>[];
  blockers: Array<{
    code: string;
    requirement: string | null;
    target_id: string | null;
  }>;
}

export interface RuntimeCommandPublicV1 {
  schema_version: "runtime_command_public@1";
  command_id: string;
  session_id: string;
  command_type: "runtime.drain";
  request_digest: Sha256Digest;
  idempotency_key: string;
  status: "accepted" | "claimed" | "completed" | "failed" | "locked" | "cancelled";
  max_signals: number;
  max_steps_per_agent: number;
  auto_enqueue_ready_tasks: boolean;
  state_version: number;
  fencing_token: number;
  accepted_at: string;
  claim_owner: string | null;
  lease_expires_at: string | null;
  bounded_outcome_summary: RuntimeCommandOutcomeSummaryPublicV1 | null;
  failure_id: string | null;
  diagnostic_id: string | null;
  error_code: string | null;
  safe_error_summary: string | null;
  safe_retry_hint: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface RuntimeCommandOutcomeSummaryPublicV1 {
  schema_version: "runtime_command_outcome_summary_public@1";
  processed_signals: number;
  turn_count: number;
  turns_digest: Sha256Digest;
  runtime_executed: boolean;
  task_transition_performed: boolean;
  fallback_performed: boolean;
}

export interface RuntimeTurnCommandPublicV1 {
  schema_version: "runtime_turn_command_public@1";
  command_id: string;
  turn_id: string;
  session_id: string;
  agent_id: string;
  agent_member_id: string;
  signal_id: string;
  signal_attempt: number;
  runtime_lease_generation: number;
  runtime_fence: number;
  process_epoch: number;
  distribution_id: string;
  distribution_manifest_digest: Sha256Digest;
  release_digest: Sha256Digest;
  adapter_bundle_digest: Sha256Digest;
  extension_bundle_digest: Sha256Digest;
  declared_tool_catalog_digest: Sha256Digest;
  capability_binding_id: string;
  capability_binding_revision: number;
  capability_binding_digest: Sha256Digest;
  affordance_snapshot_id: string;
  affordance_snapshot_digest: Sha256Digest;
  workflow_authority_id: string;
  workflow_authority_epoch: number;
  workflow_authority_digest: Sha256Digest;
  signal_authority_link_digest: Sha256Digest;
  tool_exposure_snapshot_id: string;
  tool_exposure_snapshot_digest: Sha256Digest;
  context_digest: Sha256Digest;
  message_count: number;
  runtime_adapter_id: string;
  runtime_adapter_contract_digest: Sha256Digest;
  max_steps: number;
  max_duration_seconds: number;
  max_input_units: number;
  max_output_units: number;
  task_id: string | null;
  lane_id: string | null;
  continuation_id: string | null;
  source_command_digest: Sha256Digest;
}

export interface RuntimeUsageV1 {
  schema_version: "runtime_usage@1";
  input_units: number;
  output_units: number;
  total_units: number;
  provider_reported: boolean;
}

export interface RuntimeFailurePublicV1 {
  schema_version: "runtime_failure_public@1";
  failure_id: string;
  error_code: string;
  safe_summary: string;
  diagnostic_id: string;
  effect_certainty:
    | "no_effect"
    | "dispatch_in_doubt"
    | "effect_known"
    | "terminal_known";
  mutation_applied: boolean | null;
  fallback_performed: boolean;
  reconcile_required: boolean;
  next_action: string;
}

export interface RuntimeTurnOutcomePublicV1 {
  schema_version: "runtime_turn_outcome_public@1";
  outcome_id: string;
  command_id: string;
  source_command_digest: Sha256Digest;
  turn_id: string;
  session_id: string;
  agent_id: string;
  agent_member_id: string;
  signal_id: string;
  signal_attempt: number;
  runtime_lease_generation: number;
  runtime_fence: number;
  process_epoch: number;
  workflow_authority_id: string;
  workflow_authority_epoch: number;
  workflow_authority_digest: Sha256Digest;
  tool_exposure_snapshot_id: string;
  tool_exposure_snapshot_digest: Sha256Digest;
  disposition:
    | "ready_for_next_step"
    | "waiting_approval"
    | "waiting_continuation"
    | "idle"
    | "step_limit_reached"
    | "failed";
  summary: string;
  message_count: number;
  tool_request_count: number;
  tool_request_digest: Sha256Digest;
  usage: RuntimeUsageV1 | null;
  continuation_id: string | null;
  waiting_approval_id: string | null;
  failure: RuntimeFailurePublicV1 | null;
  task_id: string | null;
  lane_id: string | null;
  correlation_id: string | null;
  source_outcome_digest: Sha256Digest;
}

export interface RuntimeTurnOutcomeReceiptPublicV1 {
  schema_version: "runtime_turn_outcome_receipt_public@1";
  receipt_id: string;
  outcome: RuntimeTurnOutcomePublicV1;
  accepted_at: string;
  source_receipt_digest: Sha256Digest;
}

export interface RuntimeOutcomeConsumptionPublicV1 {
  schema_version: "runtime_outcome_consumption_public@1";
  consumption_id: string;
  consumption_digest: Sha256Digest;
  command_id: string;
  command_digest: Sha256Digest;
  outcome_id: string;
  outcome_digest: Sha256Digest;
  outcome_receipt_id: string;
  outcome_receipt_digest: Sha256Digest;
  session_id: string;
  agent_id: string;
  agent_member_id: string;
  signal_id: string;
  signal_attempt: number;
  continuation_intent_id: string | null;
  settlement_intent_id: string;
  consumed_at: string;
}

export type FailurePublicFactValue =
  | boolean
  | number
  | string
  | FailurePublicFactValue[];

export type FailurePublicFactName =
  | "active_epoch_id"
  | "capability_id"
  | "component_id"
  | "distribution_id"
  | "driver_id"
  | "epoch_id"
  | "expected_digest"
  | "expected_manifest_digest"
  | "fallback_performed"
  | "missing_ids"
  | "missing_kinds"
  | "missing_port_contracts"
  | "mutation_applied"
  | "observed_digest"
  | "observed_manifest_digest"
  | "plugin_id"
  | "plugin_ids"
  | "prior_output_message_count"
  | "prior_tool_request_count"
  | "process_epoch"
  | "provider_backend_identity_digest"
  | "provider_id"
  | "provider_plugin_ids"
  | "reconcile_required"
  | "requested_epoch_id"
  | "retry_eligibility"
  | "retry_performed"
  | "route_id"
  | "route_ids"
  | "session_id"
  | "surface"
  | "surface_kind"
  | "target_id"
  | "tool_exposure_snapshot_id"
  | "unexpected_ids"
  | "unexpected_kinds"
  | "verification_kind"
  | "workflow_authority_epoch"
  | "workflow_authority_id"
  | "workspace_generation";

export type FailurePublicIdentityName =
  | "agent_member_id"
  | "authority_id"
  | "capability_id"
  | "command_id"
  | "component_id"
  | "correlation_id"
  | "distribution_id"
  | "driver_id"
  | "intent_id"
  | "lane_id"
  | "plugin_id"
  | "process_identity"
  | "provider_id"
  | "request_id"
  | "route_id"
  | "session_id"
  | "signal_id"
  | "source_ref"
  | "source_version"
  | "target_id"
  | "task_id"
  | "tool_exposure_snapshot_id"
  | "workflow_authority_id"
  | "workspace_id";

export interface FailureObservationPublicV2 {
  schema_version: "failure_observation@2";
  failure_id: string;
  session_id: string;
  source_kind: string;
  source_ref: string;
  source_version: string;
  phase: string;
  failure_class:
    | "validation"
    | "tool"
    | "provider"
    | "controlled_effect"
    | "harness"
    | "runtime"
    | "system";
  recoverability:
    | "agent_can_retry"
    | "agent_can_replan"
    | "reconciliation_required"
    | "authorization_required"
    | "runtime_retry"
    | "terminal";
  effect_certainty:
    | "no_effect"
    | "dispatch_in_doubt"
    | "effect_known"
    | "terminal_known";
  retry_eligibility:
    | "same_phase_safe"
    | "verify_then_retry"
    | "reconcile_required"
    | "terminal";
  actor_kind: "harness" | "system" | "agent";
  error_code: string;
  safe_summary: string;
  facts: Partial<Record<FailurePublicFactName, FailurePublicFactValue>>;
  likely_causes: string[];
  evidence_refs: string[];
  created_at: string;
  task_id: string | null;
  lane_id: string | null;
  agent_id: string | null;
  safe_hint: string | null;
  component: string;
  operation: string;
  identities: Partial<Record<FailurePublicIdentityName, string>>;
  mutation_applied: boolean | null;
  fallback_performed: boolean;
  cause_chain: Array<{
    type: string;
    code: string;
    message_digest: Sha256Digest;
  }>;
  diagnostic_id: string;
  next_action: string;
}

export interface RuntimeCommandStatusV1 {
  schema_version: "runtime_command_status@1";
  session_id: string;
  command: RuntimeCommandPublicV1;
  projection_digest: Sha256Digest;
  mutation_applied: false;
  fallback_performed: false;
}

export interface FileWorkspaceProjectionObservationV1 {
  schema_version: "file_workspace_projection_observation@1";
  observation_id: Sha256Digest;
  observation_kind: "workspace_projection_change";
  source: "verified_workspace_projection_poll";
  session_id: string;
  release_digest: Sha256Digest;
  public_contract_digest: Sha256Digest;
  previous_projection_digest: Sha256Digest | null;
  projection_digest: Sha256Digest;
  facts: {
    schema_version: "resident_workspace_projection_change_facts@1";
    readiness: "provisioning" | "ready" | "blocked";
    next_action: string;
    workspace_id: string;
    workspace_generation: number;
    provisioning_intent_id: string;
    provisioning_intent_state_version: number;
    transcript_digest: Sha256Digest;
    pending_signal_count: number;
    runtime_command_count: number;
    latest_runtime_command: null | {
      schema_version: "runtime_command_projection_fact@1";
      command_id: string;
      status: RuntimeCommandPublicV1["status"];
      state_version: number;
    };
    pending_approval_ids: string[];
    failure_ids: string[];
  };
}

export interface LayeredReleaseIdentityV2 {
  schema_version: "openzyme_layered_release_identity@1";
  kernel_contract_digest: Sha256Digest;
  core_schema_digest: Sha256Digest;
  adapter_bundle_digest: Sha256Digest;
  extension_bundle_digest: Sha256Digest;
  declared_tool_catalog_digest: Sha256Digest;
  route_catalog_digest: Sha256Digest;
  projection_catalog_digest: Sha256Digest;
  migration_catalog_digest: Sha256Digest;
  workspace_backend_digest: Sha256Digest;
  host_build_digest: Sha256Digest;
  client_build_digest: Sha256Digest;
  release_digest: Sha256Digest;
  public_contract_digest: Sha256Digest;
}

export interface FileWorkspaceV2Core {
  session: Record<string, unknown> & {
    resident_readiness: {
      schema_version: "resident_teammate_readiness@1";
      readiness: "provisioning" | "ready" | "blocked";
      workspace_id: string;
      workspace_generation: number;
      provisioning_intent_id: string;
      provisioning_intent_digest: Sha256Digest;
      failure_id: string | null;
      next_action: string;
    };
  };
  tasks: Record<string, unknown>[];
  lanes: Record<string, unknown>[];
  agents: Record<string, unknown>[];
  protocol: Record<string, unknown>;
  conversation: {
    memories: Record<string, unknown>[];
    messages: Record<string, unknown>[];
    transcript: {
      schema_version: "ordered_transcript@1";
      messages: Array<{
        schema_version: "resident_transcript_message@1";
        ordinal: number;
        message_id: string;
        role: "user" | "assistant" | "tool";
        content: string;
        correlation_id: string | null;
        tool_call_id: string | null;
        source_command_id: string | null;
        source_outcome_id: string | null;
        created_at: string;
      }>;
      transcript_digest: Sha256Digest;
    };
  };
  approvals: Record<string, unknown>[];
  authority_leases: Record<string, unknown>[];
  capability_binding: Record<string, unknown> & { binding_digest: Sha256Digest };
  runtime: Record<string, unknown> & {
    commands: RuntimeCommandPublicV1[];
    outcome_consumptions: RuntimeOutcomeConsumptionPublicV1[];
    turn_commands: RuntimeTurnCommandPublicV1[];
    outcomes: RuntimeTurnOutcomeReceiptPublicV1[];
    workflow_authority: {
      schema_version: "workflow_authority_projection@1";
      bindings: Record<string, unknown>[];
      signal_links: Record<string, unknown>[];
    };
  };
  workspace: Record<string, unknown> & {
    provisioning: {
      schema_version: "workspace_provisioning_public@2";
      intent_id: string;
      intent_digest: Sha256Digest;
      intent_state_version: number;
      status: "pending" | "claimed" | "ready" | "blocked" | "cancelled";
      workspace_id: string;
      workspace_generation: number;
      runtime_binding_id: string | null;
      failure_id: string | null;
      error_code: string | null;
      effect_certainty: string | null;
      mutation_applied: boolean | null;
      fallback_performed: false;
      retry_permitted: boolean;
      reconcile_required: boolean;
      diagnostic_id: string | null;
      next_action: string;
      reconciliation: null | {
        schema_version: "workspace_provisioning_reconciliation_public@1";
        reconciliation_id: string;
        reconciliation_digest: string;
        status: "pending" | "claimed" | "ready" | "blocked";
        attempt: number;
        parent_reconciliation_id: string | null;
        blocked_intent_state_version: number;
        blocked_intent_digest: string;
        source_receipt_id: string;
        source_receipt_digest: string;
        dispatch_receipt_digest: string;
        result_receipt_id: string | null;
        result_receipt_digest: string | null;
        effect_certainty: string | null;
        mutation_applied: boolean | null;
        fallback_performed: false;
        retry_permitted: false;
        reconcile_required: boolean;
        failure_id: string | null;
        diagnostic_id: string | null;
        requested_at: string;
        requested_claim_seconds: number;
        settled_at: string | null;
        next_action: string;
      };
    };
  };
  publications: Record<string, unknown>[];
  operations: Record<string, unknown>;
  failures: { observations: FailureObservationPublicV2[] };
  tool_reflection: {
    declared_tool_catalog_digest: Sha256Digest;
    affordance_snapshot_digest: Sha256Digest;
    capability_binding_digest: Sha256Digest;
    available_tool_names: string[];
    affordances: PublicToolAffordance[];
    tool_exposure: {
      schema_version: "tool_exposure_public@1";
      exposure_snapshot_id: string;
      exposure_snapshot_digest: Sha256Digest;
      direct_tool_names: string[];
      deferred_tool_names: string[];
      command_expansions: Array<{
        schema_version: "command_tool_expansion_public@1";
        expansion_id: string;
        command_id: string;
        expansion_revision: number;
        expanded_tool_names: string[];
        expansion_digest: Sha256Digest;
      }>;
    };
  };
}

export interface FileWorkspaceV2ExtensionSection {
  section_contract_digest: Sha256Digest;
  payload: Record<string, unknown>;
  next_cursor: string | null;
  projection_digest: Sha256Digest;
}

export interface FileWorkspacePublicV2 {
  schema_version: "file_workspace_public@2";
  release: LayeredReleaseIdentityV2;
  core: FileWorkspaceV2Core;
  extensions: Record<string, FileWorkspaceV2ExtensionSection>;
}
