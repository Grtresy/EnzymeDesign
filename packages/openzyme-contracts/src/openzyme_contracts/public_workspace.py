from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .capabilities import ToolAffordanceSnapshot
from .diagnostics import sanitize_public_diagnostic_text
from .failures import FailureObservation
from .failures import LEGACY_FAILURE_OBSERVATION_SCHEMA_VERSION
from .failures import parse_failure_observation
from .identity import JsonValue
from .identity import canonical_sha256_digest
from .identity import freeze_json
from .identity import json_compatible
from .identity import require_digest
from .identity import require_identifier
from .release import LayeredReleaseIdentity
from .tool_exposure import CommandToolExpansion
from .tool_exposure import ToolExposure
from .tool_exposure import ToolExposureSnapshot
from .tool_exposure import validate_command_tool_expansion
from .workflow_authority import RuntimeSignalAuthorityLink
from .workflow_authority import WorkflowAuthorityBinding


FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION = "file_workspace_public@2"
FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE = (
    "application/vnd.openzyme.file-workspace+json;version=2"
)
RESIDENT_TEAMMATE_READINESS_SCHEMA_VERSION = "resident_teammate_readiness@1"
WORKSPACE_PROVISIONING_PUBLIC_SCHEMA_VERSION = "workspace_provisioning_public@2"
WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_SCHEMA_VERSION = (
    "workspace_provisioning_reconciliation_public@1"
)
WORKFLOW_AUTHORITY_PROJECTION_SCHEMA_VERSION = "workflow_authority_projection@1"
ORDERED_TRANSCRIPT_SCHEMA_VERSION = "ordered_transcript@1"
RESIDENT_TRANSCRIPT_MESSAGE_SCHEMA_VERSION = "resident_transcript_message@1"
TOOL_EXPOSURE_PUBLIC_SCHEMA_VERSION = "tool_exposure_public@1"
COMMAND_TOOL_EXPANSION_PUBLIC_SCHEMA_VERSION = "command_tool_expansion_public@1"
FILE_WORKSPACE_CORE_SECTION_FIELDS = frozenset(
    {
        "session",
        "tasks",
        "lanes",
        "agents",
        "protocol",
        "conversation",
        "approvals",
        "authority_leases",
        "capability_binding",
        "runtime",
        "workspace",
        "publications",
        "operations",
        "failures",
        "tool_reflection",
    }
)
FILE_WORKSPACE_CORE_SECTION_KINDS = {
    "session": "object",
    "tasks": "array",
    "lanes": "array",
    "agents": "array",
    "protocol": "object",
    "conversation": "object",
    "approvals": "array",
    "authority_leases": "array",
    "capability_binding": "object",
    "runtime": "object",
    "workspace": "object",
    "publications": "array",
    "operations": "object",
    "failures": "object",
    "tool_reflection": "object",
}
FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS = frozenset(
    {
        "agentcapabilitylease",
        "agentcapabilityleaseid",
        "agentcapabilityleases",
        "arti" + "fact",
        "arti" + "factcatalog",
        "arti" + "factindex",
        "arti" + "factkind",
        "arti" + "facts",
        "arti" + "factset",
        "alphafold",
        "aox",
        "compute",
        "docking",
        "fpocket",
        "hpc",
        "hpcstageref",
        "hpcworkspaces",
        "hmmer",
        "reports",
        "reportdrafts",
        "research",
        "researchfiles",
        "revisionexecutions",
        "scientificattempts",
        "scientificdeliverables",
        "scientificselections",
        "storageuri",
        "claimtoken",
        "deliveryleasetoken",
        "leasetoken",
        "runtimeleasetoken",
        "sessionleasetoken",
        "signalclaimtoken",
        "boundedstderr",
        "boundedstdout",
        "context",
        "privatecontext",
        "privatefailure",
        "stderr",
        "stdout",
        "toolrequests",
        "traceback",
        "tracebacktext",
        "vina",
    }
)
FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS = frozenset(
    {
        "accesstoken",
        "credential",
        "hostpath",
        "loginalias",
        "lfsobjectlocator",
        "lfsobjectroot",
        "lfslocator",
        "privatekey",
        "privateref",
        "refreshtoken",
        "remoteroot",
        "repositoryroot",
        "schedulerhandle",
    }
)
FILE_WORKSPACE_TOOL_REFLECTION_FIELDS = frozenset(
    {
        "declared_tool_catalog_digest",
        "affordance_snapshot_digest",
        "capability_binding_digest",
        "available_tool_names",
        "affordances",
    }
)
FILE_WORKSPACE_TOOL_REFLECTION_CURRENT_FIELDS = frozenset(
    {*FILE_WORKSPACE_TOOL_REFLECTION_FIELDS, "tool_exposure"}
)
FILE_WORKSPACE_RESIDENT_READINESS_FIELDS = frozenset(
    {
        "schema_version",
        "readiness",
        "workspace_id",
        "workspace_generation",
        "provisioning_intent_id",
        "provisioning_intent_digest",
        "failure_id",
        "next_action",
    }
)
FILE_WORKSPACE_PROVISIONING_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "intent_id",
        "intent_digest",
        "intent_state_version",
        "status",
        "workspace_id",
        "workspace_generation",
        "runtime_binding_id",
        "failure_id",
        "error_code",
        "effect_certainty",
        "mutation_applied",
        "fallback_performed",
        "retry_permitted",
        "reconcile_required",
        "diagnostic_id",
        "next_action",
        "reconciliation",
    }
)
FILE_WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "reconciliation_id",
        "reconciliation_digest",
        "status",
        "attempt",
        "parent_reconciliation_id",
        "blocked_intent_state_version",
        "blocked_intent_digest",
        "source_receipt_id",
        "source_receipt_digest",
        "dispatch_receipt_digest",
        "result_receipt_id",
        "result_receipt_digest",
        "effect_certainty",
        "mutation_applied",
        "fallback_performed",
        "retry_permitted",
        "reconcile_required",
        "failure_id",
        "diagnostic_id",
        "requested_at",
        "requested_claim_seconds",
        "settled_at",
        "next_action",
    }
)
FILE_WORKSPACE_FAILURE_OBSERVATION_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "failure_id",
        "session_id",
        "source_kind",
        "source_ref",
        "source_version",
        "phase",
        "failure_class",
        "recoverability",
        "effect_certainty",
        "retry_eligibility",
        "actor_kind",
        "error_code",
        "safe_summary",
        "facts",
        "likely_causes",
        "evidence_refs",
        "created_at",
        "task_id",
        "lane_id",
        "agent_id",
        "safe_hint",
        "component",
        "operation",
        "identities",
        "mutation_applied",
        "fallback_performed",
        "cause_chain",
        "diagnostic_id",
        "next_action",
    }
)
FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS = frozenset(
    {
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
    }
)
FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS = frozenset(
    {
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
    }
)
FILE_WORKSPACE_WORKFLOW_AUTHORITY_PROJECTION_FIELDS = frozenset(
    {"schema_version", "bindings", "signal_links"}
)
FILE_WORKSPACE_RUNTIME_COMMAND_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "command_id",
        "session_id",
        "command_type",
        "request_digest",
        "idempotency_key",
        "status",
        "max_signals",
        "max_steps_per_agent",
        "auto_enqueue_ready_tasks",
        "state_version",
        "fencing_token",
        "accepted_at",
        "claim_owner",
        "lease_expires_at",
        "bounded_outcome_summary",
        "failure_id",
        "diagnostic_id",
        "error_code",
        "safe_error_summary",
        "safe_retry_hint",
        "started_at",
        "completed_at",
    }
)
RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_SCHEMA_VERSION = (
    "runtime_command_outcome_summary_public@1"
)
FILE_WORKSPACE_RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "processed_signals",
        "turn_count",
        "turns_digest",
        "runtime_executed",
        "task_transition_performed",
        "fallback_performed",
    }
)
RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_SCHEMA_VERSION = (
    "runtime_outcome_consumption_public@1"
)
FILE_WORKSPACE_RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "consumption_id",
        "consumption_digest",
        "command_id",
        "command_digest",
        "outcome_id",
        "outcome_digest",
        "outcome_receipt_id",
        "outcome_receipt_digest",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "continuation_intent_id",
        "settlement_intent_id",
        "consumed_at",
    }
)
FILE_WORKSPACE_RUNTIME_TURN_COMMAND_FIELDS = frozenset(
    {
        "schema_version",
        "command_id",
        "turn_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "runtime_lease_generation",
        "runtime_fence",
        "process_epoch",
        "distribution_id",
        "distribution_manifest_digest",
        "release_digest",
        "adapter_bundle_digest",
        "extension_bundle_digest",
        "declared_tool_catalog_digest",
        "capability_binding_id",
        "capability_binding_revision",
        "capability_binding_digest",
        "affordance_snapshot_id",
        "affordance_snapshot_digest",
        "workflow_authority_id",
        "workflow_authority_epoch",
        "workflow_authority_digest",
        "signal_authority_link_digest",
        "tool_exposure_snapshot_id",
        "tool_exposure_snapshot_digest",
        "context_digest",
        "message_count",
        "runtime_adapter_id",
        "runtime_adapter_contract_digest",
        "max_steps",
        "max_duration_seconds",
        "max_input_units",
        "max_output_units",
        "task_id",
        "lane_id",
        "continuation_id",
        "source_command_digest",
    }
)
FILE_WORKSPACE_RUNTIME_OUTCOME_FIELDS = frozenset(
    {
        "schema_version",
        "outcome_id",
        "command_id",
        "source_command_digest",
        "turn_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "runtime_lease_generation",
        "runtime_fence",
        "process_epoch",
        "workflow_authority_id",
        "workflow_authority_epoch",
        "workflow_authority_digest",
        "tool_exposure_snapshot_id",
        "tool_exposure_snapshot_digest",
        "disposition",
        "summary",
        "message_count",
        "tool_request_count",
        "tool_request_digest",
        "usage",
        "continuation_id",
        "waiting_approval_id",
        "failure",
        "task_id",
        "lane_id",
        "correlation_id",
        "source_outcome_digest",
    }
)
FILE_WORKSPACE_RUNTIME_OUTCOME_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "outcome",
        "accepted_at",
        "source_receipt_digest",
    }
)
FILE_WORKSPACE_RUNTIME_FAILURE_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "failure_id",
        "error_code",
        "safe_summary",
        "diagnostic_id",
        "effect_certainty",
        "mutation_applied",
        "fallback_performed",
        "reconcile_required",
        "next_action",
    }
)
FILE_WORKSPACE_ORDERED_TRANSCRIPT_FIELDS = frozenset(
    {"schema_version", "messages", "transcript_digest"}
)
FILE_WORKSPACE_TRANSCRIPT_MESSAGE_FIELDS = frozenset(
    {
        "schema_version",
        "ordinal",
        "message_id",
        "role",
        "content",
        "correlation_id",
        "tool_call_id",
        "source_command_id",
        "source_outcome_id",
        "created_at",
    }
)
FILE_WORKSPACE_TOOL_EXPOSURE_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "exposure_snapshot_id",
        "exposure_snapshot_digest",
        "direct_tool_names",
        "deferred_tool_names",
        "command_expansions",
    }
)
FILE_WORKSPACE_COMMAND_EXPANSION_PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "expansion_id",
        "command_id",
        "expansion_revision",
        "expanded_tool_names",
        "expansion_digest",
    }
)
FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS = frozenset(
    {
        "tool_name",
        "tool_contract_digest",
        "state",
        "required_authorities",
        "route_ids",
        "route_refs",
        "blockers",
    }
)
FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES = frozenset(
    {
        "available",
        "available_with_approval",
        "blocked_dependency",
        "blocked_configuration",
        "blocked_qualification",
        "blocked_authority",
        "blocked_provisioning",
        "temporarily_unavailable",
    }
)
FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
        "media_type": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        "root_fields": ["schema_version", "release", "core", "extensions"],
        "core_sections": dict(sorted(FILE_WORKSPACE_CORE_SECTION_KINDS.items())),
        "core_forbidden_field_tokens": sorted(
            FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS
        ),
        "core_forbidden_field_fragments": sorted(
            FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS
        ),
        "tool_reflection_fields": sorted(FILE_WORKSPACE_TOOL_REFLECTION_FIELDS),
        "tool_reflection_current_fields": sorted(
            FILE_WORKSPACE_TOOL_REFLECTION_CURRENT_FIELDS
        ),
        "tool_affordance_fields": sorted(FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS),
        "public_tool_affordance_states": sorted(
            FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES
        ),
        "extension_fields": [
            "section_contract_digest",
            "payload",
            "next_cursor",
            "projection_digest",
        ],
        "resident_inner_contracts": {
            RESIDENT_TEAMMATE_READINESS_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_RESIDENT_READINESS_FIELDS
            ),
            WORKSPACE_PROVISIONING_PUBLIC_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_PROVISIONING_PUBLIC_FIELDS
            ),
            WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_FIELDS
            ),
            "failure_observation@2": sorted(
                FILE_WORKSPACE_FAILURE_OBSERVATION_PUBLIC_FIELDS
            ),
            WORKFLOW_AUTHORITY_PROJECTION_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_WORKFLOW_AUTHORITY_PROJECTION_FIELDS
            ),
            "runtime_command_public@1": sorted(
                FILE_WORKSPACE_RUNTIME_COMMAND_PUBLIC_FIELDS
            ),
            RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_FIELDS
            ),
            RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_FIELDS
            ),
            "runtime_turn_command_public@1": sorted(
                FILE_WORKSPACE_RUNTIME_TURN_COMMAND_FIELDS
            ),
            "runtime_turn_outcome_public@1": sorted(
                FILE_WORKSPACE_RUNTIME_OUTCOME_FIELDS
            ),
            "runtime_turn_outcome_receipt_public@1": sorted(
                FILE_WORKSPACE_RUNTIME_OUTCOME_RECEIPT_FIELDS
            ),
            ORDERED_TRANSCRIPT_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_ORDERED_TRANSCRIPT_FIELDS
            ),
            RESIDENT_TRANSCRIPT_MESSAGE_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_TRANSCRIPT_MESSAGE_FIELDS
            ),
            TOOL_EXPOSURE_PUBLIC_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_TOOL_EXPOSURE_PUBLIC_FIELDS
            ),
            COMMAND_TOOL_EXPANSION_PUBLIC_SCHEMA_VERSION: sorted(
                FILE_WORKSPACE_COMMAND_EXPANSION_PUBLIC_FIELDS
            ),
        },
    }
)


def _closed_json_mapping(
    value: Mapping[str, JsonValue],
    *,
    field_name: str,
) -> Mapping[str, JsonValue]:
    frozen = freeze_json(value, field_name=field_name)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return frozen


def _normalized_field_token(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _assert_core_public_value(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            token = _normalized_field_token(key)
            if token in FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS or any(
                fragment in token
                for fragment in FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS
            ):
                raise ValueError(
                    "file_workspace_public@2 core contains a forbidden public field; "
                    f"path={path}.{key}"
                )
            _assert_core_public_value(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_core_public_value(nested, path=f"{path}[{index}]")


def _closed_public_object(
    value: object,
    *,
    fields: frozenset[str],
    subject: str,
) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{subject} fields are closed")
    return value


def _require_optional_public_identifier(value: object, *, field_name: str) -> None:
    if value is not None:
        require_identifier(str(value), field_name=field_name)


def _assert_resident_readiness(value: object) -> Mapping[str, JsonValue]:
    readiness = _closed_public_object(
        value,
        fields=FILE_WORKSPACE_RESIDENT_READINESS_FIELDS,
        subject="resident readiness",
    )
    if readiness["schema_version"] != RESIDENT_TEAMMATE_READINESS_SCHEMA_VERSION:
        raise ValueError("resident readiness schema version is invalid")
    if readiness["readiness"] not in {"provisioning", "ready", "blocked"}:
        raise ValueError("resident readiness state is invalid")
    for field_name in ("workspace_id", "provisioning_intent_id"):
        require_identifier(str(readiness[field_name]), field_name=field_name)
    require_digest(
        str(readiness["provisioning_intent_digest"]),
        field_name="provisioning_intent_digest",
    )
    generation = readiness["workspace_generation"]
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
    ):
        raise ValueError("resident readiness workspace_generation must be positive")
    _require_optional_public_identifier(
        readiness["failure_id"], field_name="failure_id"
    )
    if readiness["next_action"] is not None and (
        not isinstance(readiness["next_action"], str)
        or not readiness["next_action"]
        or len(readiness["next_action"]) > 8_192
    ):
        raise ValueError("resident readiness next_action must be bounded")
    return readiness


def _assert_workspace_provisioning(value: object) -> Mapping[str, JsonValue]:
    provisioning = _closed_public_object(
        value,
        fields=FILE_WORKSPACE_PROVISIONING_PUBLIC_FIELDS,
        subject="workspace provisioning",
    )
    if provisioning["schema_version"] != WORKSPACE_PROVISIONING_PUBLIC_SCHEMA_VERSION:
        raise ValueError("workspace provisioning schema version is invalid")
    status = provisioning["status"]
    if status not in {"pending", "claimed", "ready", "blocked", "cancelled"}:
        raise ValueError("workspace provisioning status is invalid")
    for field_name in ("intent_id", "workspace_id"):
        require_identifier(str(provisioning[field_name]), field_name=field_name)
    require_digest(str(provisioning["intent_digest"]), field_name="intent_digest")
    intent_state_version = provisioning["intent_state_version"]
    if (
        not isinstance(intent_state_version, int)
        or isinstance(intent_state_version, bool)
        or intent_state_version < 1
    ):
        raise ValueError("workspace provisioning intent_state_version must be positive")
    generation = provisioning["workspace_generation"]
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
    ):
        raise ValueError("workspace provisioning generation must be positive")
    for field_name in (
        "runtime_binding_id",
        "failure_id",
        "error_code",
        "diagnostic_id",
    ):
        _require_optional_public_identifier(
            provisioning[field_name], field_name=field_name
        )
    for field_name in (
        "fallback_performed",
        "retry_permitted",
        "reconcile_required",
    ):
        if not isinstance(provisioning[field_name], bool):
            raise ValueError(f"workspace provisioning {field_name} must be boolean")
    if provisioning["fallback_performed"] or provisioning["retry_permitted"]:
        raise ValueError(
            "workspace provisioning cannot claim fallback or automatic retry"
        )
    mutation = provisioning["mutation_applied"]
    if mutation is not None and not isinstance(mutation, bool):
        raise ValueError(
            "workspace provisioning mutation_applied must be boolean or null"
        )
    certainty = provisioning["effect_certainty"]
    if certainty not in {
        None,
        "no_effect",
        "dispatch_in_doubt",
        "effect_known",
        "terminal_known",
    }:
        raise ValueError("workspace provisioning effect certainty is invalid")
    if certainty == "no_effect" and mutation is not False:
        raise ValueError("no_effect provisioning requires mutation_applied=false")
    if certainty == "dispatch_in_doubt" and (
        mutation is not None or provisioning["reconcile_required"] is not True
    ):
        raise ValueError("dispatch_in_doubt provisioning requires reconciliation")
    if certainty in {"effect_known", "terminal_known"} and not isinstance(
        mutation, bool
    ):
        raise ValueError("known provisioning effect requires a mutation fact")
    reconciliation_value = provisioning["reconciliation"]
    reconciliation_ready = (
        isinstance(reconciliation_value, Mapping)
        and reconciliation_value.get("status") == "ready"
    )
    if status == "ready":
        if provisioning["runtime_binding_id"] is None or any(
            provisioning[name] is not None
            for name in ("failure_id", "error_code", "diagnostic_id")
        ):
            raise ValueError("ready provisioning requires only a runtime binding")
    elif provisioning["runtime_binding_id"] is not None and not reconciliation_ready:
        raise ValueError("non-ready provisioning cannot expose a runtime binding")
    if status == "blocked" and any(
        provisioning[name] is None
        for name in ("failure_id", "error_code", "effect_certainty", "diagnostic_id")
    ):
        raise ValueError("blocked provisioning requires complete safe failure facts")
    if reconciliation_value is not None:
        reconciliation = _closed_public_object(
            reconciliation_value,
            fields=FILE_WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_FIELDS,
            subject="workspace provisioning reconciliation",
        )
        if (
            reconciliation["schema_version"]
            != WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_SCHEMA_VERSION
        ):
            raise ValueError("workspace provisioning reconciliation version is invalid")
        if (
            status != "blocked"
            or certainty != "dispatch_in_doubt"
            or (provisioning["reconcile_required"] is not True)
        ):
            raise ValueError(
                "reconciliation requires the preserved dispatch-in-doubt intent"
            )
        for field_name in ("reconciliation_id", "source_receipt_id", "requested_at"):
            require_identifier(str(reconciliation[field_name]), field_name=field_name)
        for field_name in (
            "reconciliation_digest",
            "blocked_intent_digest",
            "source_receipt_digest",
            "dispatch_receipt_digest",
        ):
            require_digest(str(reconciliation[field_name]), field_name=field_name)
        attempt = reconciliation["attempt"]
        blocked_version = reconciliation["blocked_intent_state_version"]
        requested_claim_seconds = reconciliation["requested_claim_seconds"]
        if (
            not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt < 1
            or not isinstance(blocked_version, int)
            or isinstance(blocked_version, bool)
            or blocked_version < 1
            or not isinstance(requested_claim_seconds, int)
            or isinstance(requested_claim_seconds, bool)
            or not 1 <= requested_claim_seconds <= 86_400
        ):
            raise ValueError("workspace provisioning reconciliation fence is invalid")
        _require_optional_public_identifier(
            reconciliation["parent_reconciliation_id"],
            field_name="parent_reconciliation_id",
        )
        for field_name in (
            "result_receipt_id",
            "failure_id",
            "diagnostic_id",
            "settled_at",
        ):
            _require_optional_public_identifier(
                reconciliation[field_name], field_name=field_name
            )
        if reconciliation["result_receipt_digest"] is not None:
            require_digest(
                str(reconciliation["result_receipt_digest"]),
                field_name="result_receipt_digest",
            )
        reconciliation_status = reconciliation["status"]
        if reconciliation_status not in {"pending", "claimed", "ready", "blocked"}:
            raise ValueError("workspace provisioning reconciliation status is invalid")
        for field_name in (
            "fallback_performed",
            "retry_permitted",
            "reconcile_required",
        ):
            if not isinstance(reconciliation[field_name], bool):
                raise ValueError(
                    f"workspace provisioning reconciliation {field_name} must be boolean"
                )
        if reconciliation["fallback_performed"] or reconciliation["retry_permitted"]:
            raise ValueError(
                "workspace provisioning reconciliation forbids fallback/retry"
            )
        reconciliation_certainty = reconciliation["effect_certainty"]
        reconciliation_mutation = reconciliation["mutation_applied"]
        if reconciliation_certainty not in {
            None,
            "no_effect",
            "dispatch_in_doubt",
            "effect_known",
            "terminal_known",
        }:
            raise ValueError("workspace reconciliation effect certainty is invalid")
        if reconciliation_mutation is not None and not isinstance(
            reconciliation_mutation, bool
        ):
            raise ValueError("workspace reconciliation mutation fact is invalid")
        terminal_fields = (
            reconciliation["result_receipt_id"],
            reconciliation["result_receipt_digest"],
            reconciliation["settled_at"],
            reconciliation_certainty,
        )
        if reconciliation_status in {"pending", "claimed"}:
            if (
                any(item is not None for item in terminal_fields)
                or any(
                    reconciliation[name] is not None
                    for name in ("failure_id", "diagnostic_id")
                )
                or reconciliation_mutation is not None
                or reconciliation["reconcile_required"]
            ):
                raise ValueError(
                    "pending reconciliation cannot expose settlement facts"
                )
        elif any(item is None for item in terminal_fields):
            raise ValueError("terminal reconciliation requires settlement facts")
        if reconciliation_status == "ready":
            if (
                reconciliation_certainty != "terminal_known"
                or reconciliation_mutation is not True
                or reconciliation["reconcile_required"]
                or reconciliation["failure_id"] is not None
                or reconciliation["diagnostic_id"] is not None
                or provisioning["runtime_binding_id"] is None
            ):
                raise ValueError("ready reconciliation requires exact activation facts")
        elif reconciliation_status == "blocked":
            if (
                reconciliation["failure_id"] is None
                or reconciliation["diagnostic_id"] is None
            ):
                raise ValueError("blocked reconciliation requires safe failure facts")
            if reconciliation_certainty == "no_effect":
                if (
                    reconciliation_mutation is not False
                    or reconciliation["reconcile_required"]
                ):
                    raise ValueError(
                        "no-effect reconciliation has invalid recovery facts"
                    )
            elif reconciliation_certainty == "dispatch_in_doubt":
                if (
                    reconciliation_mutation is not None
                    or not reconciliation["reconcile_required"]
                ):
                    raise ValueError(
                        "uncertain reconciliation requires explicit observation"
                    )
            elif reconciliation_certainty in {"effect_known", "terminal_known"}:
                if (
                    not isinstance(reconciliation_mutation, bool)
                    or reconciliation["reconcile_required"]
                ):
                    raise ValueError("known reconciliation has invalid recovery facts")
            else:
                raise ValueError("blocked reconciliation requires effect certainty")
        elif provisioning["runtime_binding_id"] is not None:
            raise ValueError(
                "nonterminal reconciliation cannot expose a runtime binding"
            )
    if provisioning["next_action"] is not None and (
        not isinstance(provisioning["next_action"], str)
        or not provisioning["next_action"]
        or len(provisioning["next_action"]) > 8_192
    ):
        raise ValueError("workspace provisioning next_action must be bounded")
    return provisioning


def _assert_workflow_authority_projection(value: object) -> None:
    projection = _closed_public_object(
        value,
        fields=FILE_WORKSPACE_WORKFLOW_AUTHORITY_PROJECTION_FIELDS,
        subject="workflow authority projection",
    )
    if projection["schema_version"] != WORKFLOW_AUTHORITY_PROJECTION_SCHEMA_VERSION:
        raise ValueError("workflow authority projection schema version is invalid")
    bindings_value = projection["bindings"]
    links_value = projection["signal_links"]
    if not isinstance(bindings_value, (list, tuple)) or not isinstance(
        links_value, (list, tuple)
    ):
        raise ValueError("workflow authority projection collections are invalid")
    try:
        bindings = tuple(
            WorkflowAuthorityBinding.from_dict(item)
            for item in bindings_value
            if isinstance(item, Mapping)
        )
        links = tuple(
            RuntimeSignalAuthorityLink.from_dict(item)
            for item in links_value
            if isinstance(item, Mapping)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "workflow authority projection contains an invalid fact"
        ) from exc
    if len(bindings) != len(bindings_value) or len(links) != len(links_value):
        raise ValueError("workflow authority projection facts must be objects")
    by_id = {binding.authority_id: binding for binding in bindings}
    if len(by_id) != len(bindings):
        raise ValueError("workflow authority projection contains duplicate bindings")
    for link in links:
        binding = by_id.get(link.authority_id)
        if binding is None or (
            link.authority_epoch != binding.epoch
            or link.authority_binding_digest != binding.binding_digest
        ):
            raise ValueError("runtime signal link differs from its workflow binding")


def _assert_runtime_commands(
    value: object,
    *,
    failures: Mapping[str, FailureObservation] | None = None,
) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 1_024:
        raise ValueError("runtime commands must be a bounded array")
    command_ids: list[str] = []
    for item in value:
        command = _closed_public_object(
            item,
            fields=FILE_WORKSPACE_RUNTIME_COMMAND_PUBLIC_FIELDS,
            subject="runtime command",
        )
        if command["schema_version"] != "runtime_command_public@1":
            raise ValueError("runtime command schema version is invalid")
        for field_name in ("command_id", "session_id", "idempotency_key"):
            require_identifier(str(command[field_name]), field_name=field_name)
        command_ids.append(str(command["command_id"]))
        require_digest(str(command["request_digest"]), field_name="request_digest")
        if command["command_type"] != "runtime.drain" or command["status"] not in {
            "accepted",
            "claimed",
            "completed",
            "failed",
            "locked",
            "cancelled",
        }:
            raise ValueError("runtime command type or status is invalid")
        for field_name in ("max_signals", "max_steps_per_agent", "state_version"):
            field_value = command[field_name]
            if (
                not isinstance(field_value, int)
                or isinstance(field_value, bool)
                or field_value < 1
            ):
                raise ValueError(f"runtime command {field_name} must be positive")
        fencing_token = command["fencing_token"]
        if (
            not isinstance(fencing_token, int)
            or isinstance(fencing_token, bool)
            or fencing_token < 0
        ):
            raise ValueError("runtime command fencing_token must be non-negative")
        if not isinstance(command["auto_enqueue_ready_tasks"], bool):
            raise ValueError("runtime command auto_enqueue_ready_tasks must be boolean")
        for field_name in (
            "accepted_at",
            "started_at",
            "completed_at",
            "lease_expires_at",
        ):
            _require_optional_public_identifier(
                command[field_name], field_name=field_name
            )
        require_identifier(str(command["accepted_at"]), field_name="accepted_at")
        for field_name in ("claim_owner", "error_code"):
            _require_optional_public_identifier(
                command[field_name], field_name=field_name
            )
        for field_name in ("failure_id", "diagnostic_id"):
            _require_optional_public_identifier(
                command[field_name], field_name=field_name
            )
        summary = command["bounded_outcome_summary"]
        if summary is not None:
            _assert_runtime_command_outcome_summary(summary)
        for field_name in ("safe_error_summary", "safe_retry_hint"):
            text = command[field_name]
            if text is not None and (not isinstance(text, str) or len(text) > 8_192):
                raise ValueError(f"runtime command {field_name} must be bounded")
        claim_fields = (
            command["claim_owner"],
            command["lease_expires_at"],
            command["started_at"],
        )
        if command["status"] == "claimed" and any(
            item is None for item in claim_fields
        ):
            raise ValueError("claimed runtime command lacks its claim identity")
        if (
            command["status"] in {"completed", "failed", "locked", "cancelled"}
            and command["completed_at"] is None
        ):
            raise ValueError("terminal runtime command lacks completed_at")
        failure_id = command["failure_id"]
        diagnostic_id = command["diagnostic_id"]
        if command["status"] == "failed":
            failure = None if failures is None else failures.get(str(failure_id))
            if (
                not isinstance(failure_id, str)
                or not isinstance(diagnostic_id, str)
                or failure is None
                or failure.session_id != command["session_id"]
                or failure.source_kind != "runtime_command"
                or failure.source_ref != command["command_id"]
                or failure.diagnostic_id != diagnostic_id
            ):
                raise ValueError(
                    "failed runtime command does not resolve its exact public failure"
                )
        elif failure_id is not None or diagnostic_id is not None:
            raise ValueError("non-failed runtime command carries failure identities")
    if len(command_ids) != len(set(command_ids)):
        raise ValueError("runtime command identities must be unique")


def _assert_runtime_command_outcome_summary(value: object) -> None:
    summary = _closed_public_object(
        value,
        fields=FILE_WORKSPACE_RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_FIELDS,
        subject="runtime command outcome summary",
    )
    if (
        summary["schema_version"]
        != RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_SCHEMA_VERSION
    ):
        raise ValueError("runtime command outcome summary schema version is invalid")
    for field_name in ("processed_signals", "turn_count"):
        field_value = summary[field_name]
        if (
            not isinstance(field_value, int)
            or isinstance(field_value, bool)
            or not 0 <= field_value <= 1_024
        ):
            raise ValueError(f"runtime command outcome summary {field_name} is invalid")
    if summary["turn_count"] != summary["processed_signals"]:
        raise ValueError("runtime command outcome summary turn count is inconsistent")
    require_digest(str(summary["turns_digest"]), field_name="turns_digest")
    for field_name in (
        "runtime_executed",
        "task_transition_performed",
        "fallback_performed",
    ):
        if not isinstance(summary[field_name], bool):
            raise ValueError(
                f"runtime command outcome summary {field_name} must be boolean"
            )
    if summary["fallback_performed"]:
        raise ValueError("runtime command outcome summary cannot report fallback")
    if summary["runtime_executed"] != (summary["processed_signals"] > 0):
        raise ValueError(
            "runtime command outcome summary execution fact is inconsistent"
        )


def _assert_runtime_outcome_consumptions(value: object) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 4_096:
        raise ValueError("runtime outcome consumptions must be a bounded array")
    consumption_ids: list[str] = []
    for item in value:
        consumption = _closed_public_object(
            item,
            fields=FILE_WORKSPACE_RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_FIELDS,
            subject="runtime outcome consumption",
        )
        if (
            consumption["schema_version"]
            != RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_SCHEMA_VERSION
        ):
            raise ValueError("runtime outcome consumption schema version is invalid")
        for field_name in (
            "consumption_id",
            "command_id",
            "outcome_id",
            "outcome_receipt_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "settlement_intent_id",
        ):
            require_identifier(str(consumption[field_name]), field_name=field_name)
        continuation_id = consumption["continuation_intent_id"]
        if continuation_id is not None:
            require_identifier(
                str(continuation_id), field_name="continuation_intent_id"
            )
        for field_name in (
            "consumption_digest",
            "command_digest",
            "outcome_digest",
            "outcome_receipt_digest",
        ):
            require_digest(str(consumption[field_name]), field_name=field_name)
        attempt = consumption["signal_attempt"]
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError(
                "runtime outcome consumption signal_attempt must be positive"
            )
        consumed_at = consumption["consumed_at"]
        if (
            not isinstance(consumed_at, str)
            or not consumed_at
            or len(consumed_at) > 256
        ):
            raise ValueError("runtime outcome consumption consumed_at is invalid")
        consumption_ids.append(str(consumption["consumption_id"]))
    if len(consumption_ids) != len(set(consumption_ids)):
        raise ValueError("runtime outcome consumption identities must be unique")


def _assert_public_failure_observations(
    value: object,
) -> dict[str, FailureObservation]:
    failures = _closed_public_object(
        value,
        fields=frozenset({"observations"}),
        subject="public failures",
    )
    observations = failures["observations"]
    if not isinstance(observations, (list, tuple)) or len(observations) > 4_096:
        raise ValueError("public failure observations must be a bounded array")
    failures_by_id: dict[str, FailureObservation] = {}
    for item in observations:
        if (
            isinstance(item, Mapping)
            and item.get("schema_version") == LEGACY_FAILURE_OBSERVATION_SCHEMA_VERSION
        ):
            raise ValueError("legacy failure observation is not public-compatible")
        failure_payload = _closed_public_object(
            item,
            fields=FILE_WORKSPACE_FAILURE_OBSERVATION_PUBLIC_FIELDS,
            subject="public failure observation",
        )
        try:
            failure = parse_failure_observation(failure_payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("public failure observation is invalid") from exc
        if not isinstance(failure, FailureObservation):
            raise ValueError("legacy failure observation is not public-compatible")
        for field_name in ("failure_id", "session_id"):
            require_identifier(str(failure_payload[field_name]), field_name=field_name)
        _assert_public_failure_mapping(
            failure_payload["facts"],
            allowed_fields=FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS,
            subject="public failure facts",
        )
        _assert_public_failure_mapping(
            failure_payload["identities"],
            allowed_fields=FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS,
            subject="public failure identities",
        )
        for field_name in (
            "source_ref",
            "source_version",
            "safe_summary",
            "created_at",
        ):
            _assert_public_failure_text(
                failure_payload[field_name],
                field_name=field_name,
            )
        if failure_payload["safe_hint"] is not None:
            _assert_public_failure_text(
                failure_payload["safe_hint"],
                field_name="safe_hint",
            )
        for field_name in ("likely_causes", "evidence_refs"):
            entries = failure_payload[field_name]
            if not isinstance(entries, (list, tuple)) or len(entries) > 64:
                raise ValueError(f"public failure {field_name} must be bounded")
            for entry in entries:
                _assert_public_failure_text(entry, field_name=field_name)
        if failure.failure_id in failures_by_id:
            raise ValueError("public failure observation identities must be unique")
        failures_by_id[failure.failure_id] = failure
    return failures_by_id


def _assert_public_failure_mapping(
    value: object,
    *,
    allowed_fields: frozenset[str],
    subject: str,
) -> None:
    if not isinstance(value, Mapping) or not set(value).issubset(allowed_fields):
        raise ValueError(f"{subject} fields are closed")
    for field_name, item in value.items():
        _assert_public_failure_value(item, field_name=field_name)


def _assert_public_failure_value(value: object, *, field_name: str) -> None:
    if isinstance(value, bool | int):
        return
    if isinstance(value, str):
        _assert_public_failure_text(value, field_name=field_name)
        return
    if isinstance(value, (list, tuple)) and len(value) <= 64:
        for item in value:
            _assert_public_failure_value(item, field_name=field_name)
        return
    raise ValueError(f"public failure {field_name} value is invalid")


def _assert_public_failure_text(value: object, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 16_384
        or sanitize_public_diagnostic_text(value) != value
    ):
        raise ValueError(f"public failure {field_name} text is not public-safe")


def _assert_runtime_turn_commands(value: object) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 4_096:
        raise ValueError("runtime turn commands must be a bounded array")
    for item in value:
        command = _closed_public_object(
            item,
            fields=FILE_WORKSPACE_RUNTIME_TURN_COMMAND_FIELDS,
            subject="runtime turn command",
        )
        if command["schema_version"] != "runtime_turn_command_public@1":
            raise ValueError("runtime turn command schema version is invalid")
        for field_name in (
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
        ):
            require_identifier(str(command[field_name]), field_name=field_name)
        for field_name in ("task_id", "lane_id", "continuation_id"):
            _require_optional_public_identifier(
                command[field_name], field_name=field_name
            )
        for field_name in (
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
        ):
            require_digest(str(command[field_name]), field_name=field_name)
        for field_name in (
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
        ):
            field_value = command[field_name]
            if (
                not isinstance(field_value, int)
                or isinstance(field_value, bool)
                or field_value < 1
            ):
                raise ValueError(f"runtime turn command {field_name} must be positive")
        if command["message_count"] > 512:
            raise ValueError("runtime turn command message_count exceeds the bound")


def _assert_runtime_outcome_receipt(value: object) -> None:
    receipt = _closed_public_object(
        value,
        fields=FILE_WORKSPACE_RUNTIME_OUTCOME_RECEIPT_FIELDS,
        subject="runtime turn outcome receipt",
    )
    if receipt["schema_version"] != "runtime_turn_outcome_receipt_public@1":
        raise ValueError("runtime turn outcome receipt schema version is invalid")
    require_identifier(str(receipt["receipt_id"]), field_name="receipt_id")
    require_identifier(str(receipt["accepted_at"]), field_name="accepted_at")
    require_digest(
        str(receipt["source_receipt_digest"]),
        field_name="source_receipt_digest",
    )
    outcome = _closed_public_object(
        receipt["outcome"],
        fields=FILE_WORKSPACE_RUNTIME_OUTCOME_FIELDS,
        subject="runtime turn outcome",
    )
    if outcome["schema_version"] != "runtime_turn_outcome_public@1":
        raise ValueError("runtime turn outcome schema version is invalid")
    for field_name in (
        "outcome_id",
        "command_id",
        "turn_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "workflow_authority_id",
        "tool_exposure_snapshot_id",
    ):
        require_identifier(str(outcome[field_name]), field_name=field_name)
    for field_name in (
        "source_command_digest",
        "workflow_authority_digest",
        "tool_exposure_snapshot_digest",
        "tool_request_digest",
        "source_outcome_digest",
    ):
        require_digest(str(outcome[field_name]), field_name=field_name)
    for field_name in (
        "continuation_id",
        "waiting_approval_id",
        "task_id",
        "lane_id",
        "correlation_id",
    ):
        _require_optional_public_identifier(outcome[field_name], field_name=field_name)
    for field_name in (
        "signal_attempt",
        "runtime_lease_generation",
        "runtime_fence",
        "process_epoch",
        "workflow_authority_epoch",
    ):
        field_value = outcome[field_name]
        if (
            not isinstance(field_value, int)
            or isinstance(field_value, bool)
            or field_value < 1
        ):
            raise ValueError(f"runtime outcome {field_name} must be positive")
    for field_name, maximum in (("message_count", 512), ("tool_request_count", 64)):
        field_value = outcome[field_name]
        if (
            not isinstance(field_value, int)
            or isinstance(field_value, bool)
            or not 0 <= field_value <= maximum
        ):
            raise ValueError(f"runtime outcome {field_name} is invalid")
    summary = outcome["summary"]
    if not isinstance(summary, str) or not summary or len(summary) > 16_384:
        raise ValueError("runtime turn outcome summary must be bounded")
    if outcome["disposition"] not in {
        "ready_for_next_step",
        "waiting_approval",
        "waiting_continuation",
        "idle",
        "step_limit_reached",
        "failed",
    }:
        raise ValueError("runtime turn outcome disposition is invalid")
    usage = outcome["usage"]
    if usage is not None:
        usage = _closed_public_object(
            usage,
            fields=frozenset(
                {
                    "schema_version",
                    "input_units",
                    "output_units",
                    "total_units",
                    "provider_reported",
                }
            ),
            subject="runtime usage",
        )
        if usage["schema_version"] != "runtime_usage@1":
            raise ValueError("runtime usage schema version is invalid")
        for field_name in ("input_units", "output_units", "total_units"):
            field_value = usage[field_name]
            if (
                not isinstance(field_value, int)
                or isinstance(field_value, bool)
                or field_value < 0
            ):
                raise ValueError(f"runtime usage {field_name} is invalid")
        if usage["total_units"] < usage["input_units"] + usage["output_units"]:
            raise ValueError("runtime usage total is smaller than its components")
        if not isinstance(usage["provider_reported"], bool):
            raise ValueError("runtime usage provider_reported must be boolean")
    failure = outcome["failure"]
    if failure is not None:
        failure = _closed_public_object(
            failure,
            fields=FILE_WORKSPACE_RUNTIME_FAILURE_PUBLIC_FIELDS,
            subject="runtime failure summary",
        )
        if failure["schema_version"] != "runtime_failure_public@1":
            raise ValueError("runtime failure summary schema version is invalid")
        for field_name in (
            "failure_id",
            "error_code",
            "diagnostic_id",
            "next_action",
        ):
            require_identifier(str(failure[field_name]), field_name=field_name)
        safe_summary = failure["safe_summary"]
        if (
            not isinstance(safe_summary, str)
            or not safe_summary
            or len(safe_summary) > 16_384
        ):
            raise ValueError("runtime failure safe_summary must be bounded")
        if not isinstance(failure["fallback_performed"], bool) or not isinstance(
            failure["reconcile_required"], bool
        ):
            raise ValueError("runtime failure recovery facts must be boolean")
        mutation_applied = failure["mutation_applied"]
        if mutation_applied is not None and not isinstance(mutation_applied, bool):
            raise ValueError("runtime failure mutation fact is invalid")
        certainty = failure["effect_certainty"]
        if certainty == "no_effect":
            if mutation_applied is not False or failure["reconcile_required"]:
                raise ValueError("no-effect runtime failure facts are inconsistent")
        elif certainty == "dispatch_in_doubt":
            if mutation_applied is not None or not failure["reconcile_required"]:
                raise ValueError("uncertain runtime failure facts are inconsistent")
        elif certainty in {"effect_known", "terminal_known"}:
            if not isinstance(mutation_applied, bool) or failure["reconcile_required"]:
                raise ValueError("known runtime failure facts are inconsistent")
        else:
            raise ValueError("runtime failure effect certainty is invalid")
    if (outcome["disposition"] == "failed") != (failure is not None):
        raise ValueError("runtime turn outcome failure and disposition differ")
    if (outcome["disposition"] == "waiting_approval") != (
        outcome["waiting_approval_id"] is not None
    ):
        raise ValueError("runtime outcome approval wait identity is inconsistent")
    if (outcome["disposition"] == "waiting_continuation") != (
        outcome["continuation_id"] is not None
    ):
        raise ValueError("runtime outcome continuation identity is inconsistent")


def _assert_runtime_outcomes(value: object) -> None:
    if not isinstance(value, (list, tuple)) or len(value) > 4_096:
        raise ValueError("runtime outcomes must be a bounded array")
    for item in value:
        _assert_runtime_outcome_receipt(item)


def _assert_ordered_transcript(value: object) -> None:
    transcript = _closed_public_object(
        value,
        fields=FILE_WORKSPACE_ORDERED_TRANSCRIPT_FIELDS,
        subject="ordered transcript",
    )
    if transcript["schema_version"] != ORDERED_TRANSCRIPT_SCHEMA_VERSION:
        raise ValueError("ordered transcript schema version is invalid")
    messages = transcript["messages"]
    if not isinstance(messages, (list, tuple)) or len(messages) > 16_384:
        raise ValueError("ordered transcript messages must be a bounded array")
    message_ids: list[str] = []
    for expected_ordinal, item in enumerate(messages, start=1):
        message = _closed_public_object(
            item,
            fields=FILE_WORKSPACE_TRANSCRIPT_MESSAGE_FIELDS,
            subject="resident transcript message",
        )
        if (
            message["schema_version"] != RESIDENT_TRANSCRIPT_MESSAGE_SCHEMA_VERSION
            or message["ordinal"] != expected_ordinal
            or message["role"] not in {"user", "assistant", "tool"}
        ):
            raise ValueError("resident transcript message order or role is invalid")
        require_identifier(str(message["message_id"]), field_name="message_id")
        message_ids.append(str(message["message_id"]))
        content = message["content"]
        if not isinstance(content, str) or not content or len(content) > 131_072:
            raise ValueError("resident transcript message content must be bounded")
        for field_name in (
            "correlation_id",
            "tool_call_id",
            "source_command_id",
            "source_outcome_id",
        ):
            _require_optional_public_identifier(
                message[field_name], field_name=field_name
            )
        require_identifier(str(message["created_at"]), field_name="created_at")
        if message["role"] == "tool" and message["tool_call_id"] is None:
            raise ValueError("tool transcript messages require tool_call_id")
    if len(message_ids) != len(set(message_ids)):
        raise ValueError("resident transcript message identities must be unique")
    require_digest(str(transcript["transcript_digest"]), field_name="transcript_digest")
    canonical = dict(transcript)
    supplied = canonical.pop("transcript_digest")
    if canonical_sha256_digest(canonical) != supplied:
        raise ValueError("ordered transcript digest is invalid")


def _assert_resident_inner_projection(payload: Mapping[str, JsonValue]) -> None:
    session = payload["session"]
    workspace = payload["workspace"]
    runtime = payload["runtime"]
    conversation = payload["conversation"]
    assert isinstance(session, Mapping)
    assert isinstance(workspace, Mapping)
    assert isinstance(runtime, Mapping)
    assert isinstance(conversation, Mapping)
    public_failures = _assert_public_failure_observations(payload["failures"])
    readiness = None
    provisioning = None
    if "resident_readiness" in session:
        readiness = _assert_resident_readiness(session["resident_readiness"])
    if "provisioning" in workspace:
        provisioning = _assert_workspace_provisioning(workspace["provisioning"])
    if readiness is not None and provisioning is not None:
        reconciliation = provisioning["reconciliation"]
        if isinstance(reconciliation, Mapping):
            expected_readiness = (
                "ready" if reconciliation["status"] == "ready" else "blocked"
            )
            expected_failure_id = (
                None
                if reconciliation["status"] == "ready"
                else (
                    reconciliation["failure_id"]
                    if reconciliation["status"] == "blocked"
                    else provisioning["failure_id"]
                )
            )
        else:
            expected_readiness = {
                "pending": "provisioning",
                "claimed": "provisioning",
                "ready": "ready",
                "blocked": "blocked",
                "cancelled": "blocked",
            }[str(provisioning["status"])]
            expected_failure_id = provisioning["failure_id"]
        exact_pairs = (
            (readiness["workspace_id"], provisioning["workspace_id"]),
            (readiness["workspace_generation"], provisioning["workspace_generation"]),
            (readiness["provisioning_intent_id"], provisioning["intent_id"]),
            (readiness["provisioning_intent_digest"], provisioning["intent_digest"]),
            (readiness["failure_id"], expected_failure_id),
        )
        if readiness["readiness"] != expected_readiness or any(
            left != right for left, right in exact_pairs
        ):
            raise ValueError("resident readiness differs from workspace provisioning")
    if "workflow_authority" in runtime:
        _assert_workflow_authority_projection(runtime["workflow_authority"])
    if "commands" in runtime:
        _assert_runtime_commands(runtime["commands"], failures=public_failures)
    if "turn_commands" in runtime:
        _assert_runtime_turn_commands(runtime["turn_commands"])
    if "outcomes" in runtime:
        _assert_runtime_outcomes(runtime["outcomes"])
    if "outcome_consumptions" in runtime:
        _assert_runtime_outcome_consumptions(runtime["outcome_consumptions"])
    if "transcript" in conversation:
        _assert_ordered_transcript(conversation["transcript"])


def _assert_public_tool_exposure(value: object) -> None:
    exposure = _closed_public_object(
        value,
        fields=FILE_WORKSPACE_TOOL_EXPOSURE_PUBLIC_FIELDS,
        subject="public tool exposure",
    )
    if exposure["schema_version"] != TOOL_EXPOSURE_PUBLIC_SCHEMA_VERSION:
        raise ValueError("public tool exposure schema version is invalid")
    require_identifier(
        str(exposure["exposure_snapshot_id"]), field_name="exposure_snapshot_id"
    )
    require_digest(
        str(exposure["exposure_snapshot_digest"]),
        field_name="exposure_snapshot_digest",
    )
    direct = exposure["direct_tool_names"]
    deferred = exposure["deferred_tool_names"]
    if not isinstance(direct, (list, tuple)) or not isinstance(deferred, (list, tuple)):
        raise ValueError("public tool exposure names must be arrays")
    direct_names = tuple(str(name) for name in direct)
    deferred_names = tuple(str(name) for name in deferred)
    for name in (*direct_names, *deferred_names):
        require_identifier(name, field_name="tool_name")
    if (
        len(set(direct_names)) != len(direct_names)
        or len(set(deferred_names)) != len(deferred_names)
        or set(direct_names).intersection(deferred_names)
    ):
        raise ValueError(
            "public Direct and Deferred tool names must be disjoint and unique"
        )
    expansions = exposure["command_expansions"]
    if not isinstance(expansions, (list, tuple)) or len(expansions) > 4_096:
        raise ValueError("public command expansions must be a bounded array")
    expansion_ids: list[str] = []
    for item in expansions:
        expansion = _closed_public_object(
            item,
            fields=FILE_WORKSPACE_COMMAND_EXPANSION_PUBLIC_FIELDS,
            subject="public command tool expansion",
        )
        if expansion["schema_version"] != COMMAND_TOOL_EXPANSION_PUBLIC_SCHEMA_VERSION:
            raise ValueError("public command tool expansion schema version is invalid")
        for field_name in ("expansion_id", "command_id"):
            require_identifier(str(expansion[field_name]), field_name=field_name)
        expansion_ids.append(str(expansion["expansion_id"]))
        revision = expansion["expansion_revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("public command expansion revision must be positive")
        names = expansion["expanded_tool_names"]
        if not isinstance(names, (list, tuple)) or not names:
            raise ValueError("public command expansion names must be non-empty")
        expanded_names = tuple(str(name) for name in names)
        if len(set(expanded_names)) != len(expanded_names) or not set(
            expanded_names
        ).issubset(deferred_names):
            raise ValueError(
                "public command expansion must be an exact Deferred subset"
            )
        require_digest(
            str(expansion["expansion_digest"]), field_name="expansion_digest"
        )
    if len(expansion_ids) != len(set(expansion_ids)):
        raise ValueError("public command expansion identities must be unique")


def _assert_tool_reflection(payload: Mapping[str, JsonValue]) -> None:
    reflection = payload["tool_reflection"]
    binding = payload["capability_binding"]
    if not isinstance(reflection, Mapping) or not isinstance(binding, Mapping):
        raise ValueError("file_workspace_public@2 tool reflection is not structured")
    if set(reflection) not in {
        FILE_WORKSPACE_TOOL_REFLECTION_FIELDS,
        FILE_WORKSPACE_TOOL_REFLECTION_CURRENT_FIELDS,
    }:
        raise ValueError("file_workspace_public@2 tool reflection fields are closed")
    for field_name in (
        "declared_tool_catalog_digest",
        "affordance_snapshot_digest",
        "capability_binding_digest",
    ):
        require_digest(str(reflection[field_name]), field_name=field_name)
    binding_digest = binding.get("binding_digest")
    require_digest(str(binding_digest), field_name="binding_digest")
    if reflection["capability_binding_digest"] != binding_digest:
        raise ValueError("tool reflection belongs to another capability binding")
    names = reflection["available_tool_names"]
    affordances = reflection["affordances"]
    if not isinstance(names, (list, tuple)) or not isinstance(
        affordances, (list, tuple)
    ):
        raise ValueError("tool reflection collections are invalid")
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("available tool names are invalid")
    observed_names: list[str] = []
    available_names: list[str] = []
    for affordance in affordances:
        if not isinstance(affordance, Mapping):
            raise ValueError("public tool affordance must be an object")
        if set(affordance) != FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS:
            raise ValueError("public tool affordance fields are closed")
        tool_name = affordance["tool_name"]
        state = affordance["state"]
        require_identifier(str(tool_name), field_name="tool_name")
        require_digest(
            str(affordance["tool_contract_digest"]),
            field_name="tool_contract_digest",
        )
        if state not in FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES:
            raise ValueError("public tool affordance state is invalid")
        for collection_name in (
            "required_authorities",
            "route_ids",
            "route_refs",
            "blockers",
        ):
            if not isinstance(affordance[collection_name], (list, tuple)):
                raise ValueError("public tool affordance collection is invalid")
        blockers = affordance["blockers"]
        if state in {"available", "available_with_approval"}:
            if blockers:
                raise ValueError("available public tool affordance has blockers")
            available_names.append(str(tool_name))
        observed_names.append(str(tool_name))
    if len(set(observed_names)) != len(observed_names):
        raise ValueError("public tool affordances contain duplicate tool names")
    if set(reflection) == FILE_WORKSPACE_TOOL_REFLECTION_CURRENT_FIELDS:
        tool_exposure = reflection["tool_exposure"]
        if tool_exposure is not None:
            _assert_public_tool_exposure(tool_exposure)
            assert isinstance(tool_exposure, Mapping)
            direct_names = set(tool_exposure["direct_tool_names"])
            expected_available_names = [
                name for name in available_names if name in direct_names
            ]
            if list(names) != expected_available_names:
                raise ValueError(
                    "available tool names differ from Direct callable affordances"
                )
            return
    if list(names) != available_names:
        raise ValueError("available tool names differ from public affordances")


@dataclass(frozen=True, slots=True)
class FileWorkspaceToolReflection:
    declared_tool_catalog_digest: str
    affordance_snapshot: ToolAffordanceSnapshot
    exposure_snapshot: ToolExposureSnapshot | None = None
    command_expansions: tuple[CommandToolExpansion, ...] = ()

    def __post_init__(self) -> None:
        require_digest(
            self.declared_tool_catalog_digest,
            field_name="declared_tool_catalog_digest",
        )
        if (
            self.affordance_snapshot.declared_tool_catalog_digest
            != self.declared_tool_catalog_digest
        ):
            raise ValueError("affordance snapshot belongs to another declared catalog")
        if not self.affordance_snapshot.has_valid_digest():
            raise ValueError("affordance snapshot digest is invalid")
        if self.exposure_snapshot is None:
            if self.command_expansions:
                raise ValueError(
                    "command expansions require an exact exposure snapshot"
                )
            return
        if (
            self.exposure_snapshot.declared_tool_catalog_digest
            != self.declared_tool_catalog_digest
            or self.exposure_snapshot.capability_binding_digest
            != self.affordance_snapshot.capability_binding_digest
            or self.exposure_snapshot.affordance_snapshot_id
            != self.affordance_snapshot.snapshot_id
            or self.exposure_snapshot.affordance_snapshot_digest
            != self.affordance_snapshot.snapshot_digest
        ):
            raise ValueError(
                "tool exposure belongs to another catalog or affordance snapshot"
            )
        for expansion in self.command_expansions:
            validate_command_tool_expansion(self.exposure_snapshot, expansion)
        expansion_ids = tuple(item.expansion_id for item in self.command_expansions)
        if len(set(expansion_ids)) != len(expansion_ids):
            raise ValueError("command expansion identities must be unique")

    def to_dict(self) -> dict[str, Any]:
        visible = [
            item.to_dict()
            for item in self.affordance_snapshot.affordances
            if item.state.value != "hidden"
        ]
        tool_exposure: dict[str, Any] | None = None
        if self.exposure_snapshot is not None:
            tool_exposure = {
                "schema_version": TOOL_EXPOSURE_PUBLIC_SCHEMA_VERSION,
                "exposure_snapshot_id": self.exposure_snapshot.exposure_snapshot_id,
                "exposure_snapshot_digest": (
                    self.exposure_snapshot.exposure_snapshot_digest
                ),
                "direct_tool_names": list(
                    self.exposure_snapshot.names(ToolExposure.DIRECT)
                ),
                "deferred_tool_names": list(
                    self.exposure_snapshot.names(ToolExposure.DEFERRED)
                ),
                "command_expansions": [
                    {
                        "schema_version": COMMAND_TOOL_EXPANSION_PUBLIC_SCHEMA_VERSION,
                        "expansion_id": expansion.expansion_id,
                        "command_id": expansion.command_id,
                        "expansion_revision": expansion.expansion_revision,
                        "expanded_tool_names": list(expansion.expanded_tool_names),
                        "expansion_digest": expansion.expansion_digest,
                    }
                    for expansion in self.command_expansions
                ],
            }
        return {
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "affordance_snapshot_digest": self.affordance_snapshot.snapshot_digest,
            "capability_binding_digest": (
                self.affordance_snapshot.capability_binding_digest
            ),
            "available_tool_names": list(
                self.affordance_snapshot.model_visible_tool_names
                if self.exposure_snapshot is None
                else tuple(
                    name
                    for name in self.affordance_snapshot.model_visible_tool_names
                    if name in self.exposure_snapshot.names(ToolExposure.DIRECT)
                )
            ),
            "affordances": visible,
            "tool_exposure": tool_exposure,
        }


@dataclass(frozen=True, slots=True)
class FileWorkspaceCoreProjectionV2:
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        observed = set(self.payload)
        if observed != FILE_WORKSPACE_CORE_SECTION_FIELDS:
            raise ValueError(
                "file_workspace_public@2 core section fields are closed; "
                f"missing={sorted(FILE_WORKSPACE_CORE_SECTION_FIELDS - observed)!r}, "
                f"unexpected={sorted(observed - FILE_WORKSPACE_CORE_SECTION_FIELDS)!r}"
            )
        for section_name, expected_kind in FILE_WORKSPACE_CORE_SECTION_KINDS.items():
            section = self.payload[section_name]
            if expected_kind == "object" and not isinstance(section, Mapping):
                raise ValueError(
                    "file_workspace_public@2 core section kind is invalid; "
                    f"section={section_name!r}, expected='object'"
                )
            if expected_kind == "array" and not isinstance(section, (list, tuple)):
                raise ValueError(
                    "file_workspace_public@2 core section kind is invalid; "
                    f"section={section_name!r}, expected='array'"
                )
        _assert_core_public_value(self.payload, path="core")
        _assert_tool_reflection(self.payload)
        _assert_resident_inner_projection(self.payload)
        object.__setattr__(
            self,
            "payload",
            _closed_json_mapping(self.payload, field_name="core"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return dict(json_compatible(self.payload))


@dataclass(frozen=True, slots=True)
class FileWorkspaceExtensionSectionV2:
    section_id: str
    section_contract_digest: str
    payload: Mapping[str, JsonValue]
    next_cursor: str | None
    projection_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.section_id, field_name="section_id")
        require_digest(
            self.section_contract_digest,
            field_name="section_contract_digest",
        )
        require_digest(self.projection_digest, field_name="projection_digest")
        if self.next_cursor is not None:
            require_identifier(self.next_cursor, field_name="next_cursor")
        object.__setattr__(
            self,
            "payload",
            _closed_json_mapping(
                self.payload,
                field_name=f"extensions.{self.section_id}.payload",
            ),
        )
        if self.projection_digest != self.observed_digest:
            raise ValueError("extension projection digest does not match its payload")

    @property
    def observed_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "section_id": self.section_id,
                "section_contract_digest": self.section_contract_digest,
                "payload": json_compatible(self.payload),
                "next_cursor": self.next_cursor,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_contract_digest": self.section_contract_digest,
            "payload": json_compatible(self.payload),
            "next_cursor": self.next_cursor,
            "projection_digest": self.projection_digest,
        }


@dataclass(frozen=True, slots=True)
class FileWorkspacePublicV2:
    release: LayeredReleaseIdentity
    core: FileWorkspaceCoreProjectionV2
    extensions: tuple[FileWorkspaceExtensionSectionV2, ...]

    def __post_init__(self) -> None:
        section_ids = [item.section_id for item in self.extensions]
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("extension projection section IDs must be unique")
        object.__setattr__(
            self,
            "extensions",
            tuple(sorted(self.extensions, key=lambda item: item.section_id)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
            "release": {
                **self.release.to_dict(),
                "release_digest": self.release.release_digest,
                "public_contract_digest": FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
            },
            "core": self.core.to_dict(),
            "extensions": {item.section_id: item.to_dict() for item in self.extensions},
        }

    @property
    def projection_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


__all__ = [
    "COMMAND_TOOL_EXPANSION_PUBLIC_SCHEMA_VERSION",
    "FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS",
    "FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS",
    "FILE_WORKSPACE_CORE_SECTION_FIELDS",
    "FILE_WORKSPACE_CORE_SECTION_KINDS",
    "FILE_WORKSPACE_COMMAND_EXPANSION_PUBLIC_FIELDS",
    "FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS",
    "FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS",
    "FILE_WORKSPACE_FAILURE_OBSERVATION_PUBLIC_FIELDS",
    "FILE_WORKSPACE_ORDERED_TRANSCRIPT_FIELDS",
    "FILE_WORKSPACE_PROVISIONING_PUBLIC_FIELDS",
    "FILE_WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_FIELDS",
    "FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST",
    "FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE",
    "FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION",
    "FILE_WORKSPACE_RESIDENT_READINESS_FIELDS",
    "FILE_WORKSPACE_RUNTIME_COMMAND_PUBLIC_FIELDS",
    "FILE_WORKSPACE_RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_FIELDS",
    "FILE_WORKSPACE_RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_FIELDS",
    "FILE_WORKSPACE_RUNTIME_OUTCOME_FIELDS",
    "FILE_WORKSPACE_RUNTIME_OUTCOME_RECEIPT_FIELDS",
    "FILE_WORKSPACE_RUNTIME_TURN_COMMAND_FIELDS",
    "FILE_WORKSPACE_TOOL_EXPOSURE_PUBLIC_FIELDS",
    "FILE_WORKSPACE_TOOL_REFLECTION_CURRENT_FIELDS",
    "FILE_WORKSPACE_TRANSCRIPT_MESSAGE_FIELDS",
    "FILE_WORKSPACE_WORKFLOW_AUTHORITY_PROJECTION_FIELDS",
    "FileWorkspaceCoreProjectionV2",
    "FileWorkspaceExtensionSectionV2",
    "FileWorkspacePublicV2",
    "FileWorkspaceToolReflection",
    "ORDERED_TRANSCRIPT_SCHEMA_VERSION",
    "RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_SCHEMA_VERSION",
    "RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_SCHEMA_VERSION",
    "RESIDENT_TEAMMATE_READINESS_SCHEMA_VERSION",
    "RESIDENT_TRANSCRIPT_MESSAGE_SCHEMA_VERSION",
    "TOOL_EXPOSURE_PUBLIC_SCHEMA_VERSION",
    "WORKFLOW_AUTHORITY_PROJECTION_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_PUBLIC_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_RECONCILIATION_PUBLIC_SCHEMA_VERSION",
]
