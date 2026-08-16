from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from collections.abc import Iterator
from typing import Final

from openzyme_domain import MutationWriterKind


HOST_MUTATION_POLICY_ID: Final = "host_mutation_policy_v1"
HOST_MUTATION_COVERAGE_MANIFEST_ID: Final = "host_mutation_coverage_v1"
HOST_MUTATION_SNAPSHOT_SCHEMA_ID: Final = "host_mutation_snapshot@1"
HOST_MUTATION_RECEIPT_EVIDENCE_SCHEMA_ID: Final = "host_mutation_receipt_evidence@1"
MAX_QUIESCENCE_SNAPSHOT_ROWS: Final = 50_000
MAX_QUIESCENCE_SNAPSHOT_BYTES: Final = 16 * 1024 * 1024


class MutationResourceCategory(StrEnum):
    CANONICAL_SQLITE = "canonical_sqlite"
    EVENT_OUTBOX = "event_outbox"
    ARTIFACT_PUBLICATION = "artifact_publication"
    REPORT_PUBLICATION = "report_publication"
    LEDGER = "ledger"


class AgentCapabilityReadinessActivationError(RuntimeError):
    """A readiness activation lost its exact transaction-local authority."""

    error_code = "agent_capability_readiness_activation_fenced"
    retryable = False


class AgentRetirementLifecycleAuthorityError(RuntimeError):
    """An agent retirement phase lost its exact service-only authority."""

    error_code = "agent_retirement_lifecycle_fenced"
    retryable = False


@dataclass(frozen=True, slots=True)
class AgentCapabilityReadinessActivationAuthority:
    """Exact one-transaction authority derived from a verified readiness proof.

    This authority is deliberately separate from ``MutationWriteAuthority``.  A
    generic mutation writer may persist ordinary canonical state, but it cannot
    promote a workspace generation or capability lease into runnable authority.
    """

    reservation_id: str
    lease_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    provider_id: str
    readiness_ref: str
    readiness_digest: str
    activated_at: str
    reservation_previous_state_version: int
    lease_previous_state_version: int
    reservation_canonical_digest: str
    lease_canonical_digest: str
    event_id: str
    event_digest: str
    actor_ref: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.reservation_id, "reservation_id"),
            (self.lease_id, "lease_id"),
            (self.session_id, "session_id"),
            (self.agent_member_id, "agent_member_id"),
            (self.agent_id, "agent_id"),
            (self.provider_id, "provider_id"),
            (self.readiness_ref, "readiness_ref"),
            (self.activated_at, "activated_at"),
            (self.event_id, "event_id"),
            (self.actor_ref, "actor_ref"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        if self.reservation_previous_state_version <= 0:
            raise ValueError("reservation_previous_state_version must be positive")
        if self.lease_previous_state_version <= 0:
            raise ValueError("lease_previous_state_version must be positive")
        for digest, field_name in (
            (self.readiness_digest, "readiness_digest"),
            (self.reservation_canonical_digest, "reservation_canonical_digest"),
            (self.lease_canonical_digest, "lease_canonical_digest"),
            (self.event_digest, "event_digest"),
        ):
            if len(digest) != 71 or not digest.startswith("sha256:"):
                raise ValueError(f"{field_name} must be a sha256 digest")
            if any(
                character not in "0123456789abcdef"
                for character in digest.removeprefix("sha256:")
            ):
                raise ValueError(f"{field_name} must use lowercase hexadecimal")


@dataclass(frozen=True, slots=True)
class AgentRetirementLifecycleAuthority:
    """Exact one-transaction authority for one retirement lifecycle insert."""

    phase: str
    record_id: str
    record_digest: str
    request_id: str
    request_digest: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    capability_lease_id: str

    def __post_init__(self) -> None:
        if self.phase not in {"request", "cleanup_proof", "final"}:
            raise ValueError("unsupported agent retirement lifecycle phase")
        for value, field_name in (
            (self.record_id, "record_id"),
            (self.request_id, "request_id"),
            (self.session_id, "session_id"),
            (self.agent_member_id, "agent_member_id"),
            (self.agent_id, "agent_id"),
            (self.capability_lease_id, "capability_lease_id"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        for digest, field_name in (
            (self.record_digest, "record_digest"),
            (self.request_digest, "request_digest"),
        ):
            if len(digest) != 71 or not digest.startswith("sha256:"):
                raise ValueError(f"{field_name} must be a sha256 digest")
            if any(
                character not in "0123456789abcdef"
                for character in digest.removeprefix("sha256:")
            ):
                raise ValueError(f"{field_name} must use lowercase hexadecimal")


@dataclass(frozen=True, slots=True)
class MutationCoverageEntry:
    table_name: str
    resource_category: MutationResourceCategory
    session_binding: str = "direct_session_id"


@dataclass(frozen=True, slots=True)
class MutationWriteAuthority:
    scope_id: str
    scope_generation: int
    scope_fencing_token: int
    writer_id: str
    writer_fencing_token: int
    owner_kind: MutationWriterKind


_CURRENT_MUTATION_WRITE_AUTHORITY: ContextVar[MutationWriteAuthority | None] = (
    ContextVar("openzyme_current_mutation_write_authority", default=None)
)


def current_mutation_write_authority() -> MutationWriteAuthority | None:
    return _CURRENT_MUTATION_WRITE_AUTHORITY.get()


@contextmanager
def bind_mutation_write_authority(
    authority: MutationWriteAuthority,
) -> Iterator[None]:
    token = _CURRENT_MUTATION_WRITE_AUTHORITY.set(authority)
    try:
        yield
    finally:
        _CURRENT_MUTATION_WRITE_AUTHORITY.reset(token)


@contextmanager
def suspend_mutation_write_authority() -> Iterator[None]:
    token = _CURRENT_MUTATION_WRITE_AUTHORITY.set(None)
    try:
        yield
    finally:
        _CURRENT_MUTATION_WRITE_AUTHORITY.reset(token)


class MutationWriteFencingError(RuntimeError):
    """A covered mutation did not carry current registered writer authority."""

    error_code = "mutation_write_fenced"
    retryable = False
    public_message = (
        "canonical mutation was rejected because its mutation-scope authority "
        "is missing, stale, frozen, or sealed"
    )

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.details = {
            "boundary": "host_mutation_authority",
            "disposition": "fail_closed",
        }


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


HOST_MUTATION_POLICY: Final[dict[str, object]] = {
    "schema_id": "host_mutation_policy@1",
    "policy_id": HOST_MUTATION_POLICY_ID,
    "active_scope_cardinality": "one_per_session",
    "writer_admission": "open_scope_only",
    "freeze_behavior": "close_admission_and_fence_canonical_writes",
    "retirement": "explicit_or_exact_process_epoch_proof",
    "quiescence": "no_active_writers_and_stable_bounded_snapshot",
    "sealing": "exact_receipt_monotonic",
    "max_snapshot_rows": MAX_QUIESCENCE_SNAPSHOT_ROWS,
    "max_snapshot_bytes": MAX_QUIESCENCE_SNAPSHOT_BYTES,
}
HOST_MUTATION_POLICY_DIGEST: Final = canonical_digest(HOST_MUTATION_POLICY)


_DIRECT_COVERAGE: tuple[tuple[str, MutationResourceCategory], ...] = (
    (
        "agent_capability_lease_lifecycle_events",
        MutationResourceCategory.EVENT_OUTBOX,
    ),
    ("agent_capability_lease_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("agent_git_workspace_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("agent_retirement_requests", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "agent_retirement_cleanup_proofs",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("agent_members", MutationResourceCategory.CANONICAL_SQLITE),
    ("agent_retirement_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("agent_runtime_signals", MutationResourceCategory.CANONICAL_SQLITE),
    ("agent_workspace_state_observations", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "agent_workspace_generation_reservations",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("approval_requests", MutationResourceCategory.CANONICAL_SQLITE),
    ("command_receipt_records", MutationResourceCategory.LEDGER),
    ("continuation_state_records", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "controlled_operation_dispatch_requests",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    (
        "controlled_operation_provider_dispatch_receipts",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    (
        "controlled_operation_provider_observation_receipts",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    (
        "controlled_operation_execution_events",
        MutationResourceCategory.EVENT_OUTBOX,
    ),
    (
        "controlled_operation_execution_records",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("controlled_operation_records", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "controlled_operation_result_artifacts",
        MutationResourceCategory.ARTIFACT_PUBLICATION,
    ),
    (
        "controlled_operation_result_handles",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("durable_event_records", MutationResourceCategory.EVENT_OUTBOX),
    ("engine_documents", MutationResourceCategory.CANONICAL_SQLITE),
    ("engine_invocations", MutationResourceCategory.CANONICAL_SQLITE),
    ("failure_observation_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("failure_hypothesis_records", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "executor_hpc_workspace_provision_intents",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    (
        "executor_hpc_workspace_records",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    (
        "executor_hpc_credential_claims",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("workspace_revision_execution_requests", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "failure_recovery_disposition_records",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("inbox_messages", MutationResourceCategory.CANONICAL_SQLITE),
    ("lane_lifecycle_events", MutationResourceCategory.EVENT_OUTBOX),
    ("lanes", MutationResourceCategory.CANONICAL_SQLITE),
    ("memory_entries", MutationResourceCategory.CANONICAL_SQLITE),
    ("protocol_file_handoff_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("research_file_index_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("repository_provision_credential_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("revision_path_refs", MutationResourceCategory.CANONICAL_SQLITE),
    ("runtime_command_records", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "sandbox_command_log_artifacts",
        MutationResourceCategory.ARTIFACT_PUBLICATION,
    ),
    ("sandbox_file_audit_entries", MutationResourceCategory.CANONICAL_SQLITE),
    ("sandbox_run_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("sandbox_workspace_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("session_access_records", MutationResourceCategory.LEDGER),
    (
        "session_artifact_records",
        MutationResourceCategory.ARTIFACT_PUBLICATION,
    ),
    (
        "session_report_draft_records",
        MutationResourceCategory.REPORT_PUBLICATION,
    ),
    ("session_report_records", MutationResourceCategory.REPORT_PUBLICATION),
    ("session_research_evidence", MutationResourceCategory.CANONICAL_SQLITE),
    ("session_research_gaps", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "session_research_source_refs",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("session_research_summaries", MutationResourceCategory.CANONICAL_SQLITE),
    ("session_run_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("session_runtime_leases", MutationResourceCategory.CANONICAL_SQLITE),
    (
        "scientific_attempt_authorization_records",
        MutationResourceCategory.LEDGER,
    ),
    (
        "scientific_attempt_admission_request_records",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    (
        "scientific_attempt_operation_bindings",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("scientific_attempt_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("scientific_attempt_run_bindings", MutationResourceCategory.CANONICAL_SQLITE),
    ("sessions", MutationResourceCategory.CANONICAL_SQLITE),
    ("task_finish_evidence_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("task_finish_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("tasks", MutationResourceCategory.CANONICAL_SQLITE),
    ("verified_workspace_checkpoint_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("workspace_publication_execution_events", MutationResourceCategory.CANONICAL_SQLITE),
    ("workspace_publication_execution_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("workspace_publication_intents", MutationResourceCategory.CANONICAL_SQLITE),
    ("workspace_publication_outbox_records", MutationResourceCategory.CANONICAL_SQLITE),
    ("published_revisions", MutationResourceCategory.CANONICAL_SQLITE),
    ("git_lfs_quota_reservations", MutationResourceCategory.ARTIFACT_PUBLICATION),
    ("git_lfs_upload_sessions", MutationResourceCategory.ARTIFACT_PUBLICATION),
    ("git_lfs_workspace_object_links", MutationResourceCategory.ARTIFACT_PUBLICATION),
)

HOST_MUTATION_COVERAGE_ENTRIES: Final[tuple[MutationCoverageEntry, ...]] = tuple(
    MutationCoverageEntry(table_name=table_name, resource_category=category)
    for table_name, category in _DIRECT_COVERAGE
) + (
    MutationCoverageEntry(
        table_name="task_dependencies",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="task_id_to_tasks",
    ),
    MutationCoverageEntry(
        table_name="executor_hpc_workspace_provision_receipts",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="workspace_id_to_executor_hpc_workspace",
    ),
    MutationCoverageEntry(
        table_name="executor_hpc_workspace_cleanup_intents",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="workspace_id_to_executor_hpc_workspace",
    ),
    MutationCoverageEntry(
        table_name="executor_hpc_workspace_cleanup_receipts",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="workspace_id_to_executor_hpc_workspace",
    ),
    MutationCoverageEntry(
        table_name="workspace_revision_clean_observations",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="request_id_to_workspace_revision_execution",
    ),
    MutationCoverageEntry(
        table_name="compute_source_manifests",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="request_id_to_workspace_revision_execution",
    ),
    MutationCoverageEntry(
        table_name="workspace_job_dispatch_intents",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="request_id_to_workspace_revision_execution",
    ),
    MutationCoverageEntry(
        table_name="scheduler_credential_occurrences",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="execution_id_to_controlled_operation_execution",
    ),
    MutationCoverageEntry(
        table_name="workspace_external_job_handles",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="dispatch_id_to_workspace_job_dispatch",
    ),
    MutationCoverageEntry(
        table_name="workspace_external_job_observations",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="execution_id_to_controlled_operation_execution",
    ),
    MutationCoverageEntry(
        table_name="workspace_job_cancellation_intents",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="execution_id_to_controlled_operation_execution",
    ),
    MutationCoverageEntry(
        table_name="workspace_job_cancellation_receipts",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="cancellation_id_to_workspace_job_cancellation",
    ),
    MutationCoverageEntry(
        table_name="workspace_job_results",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="execution_id_to_controlled_operation_execution",
    ),
    MutationCoverageEntry(
        table_name="workspace_job_result_revision_links",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="result_id_to_workspace_job_result",
    ),
    MutationCoverageEntry(
        table_name="protocol_file_handoff_entries",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="handoff_id_to_protocol_file_handoffs",
    ),
    MutationCoverageEntry(
        table_name="workspace_publication_remote_receipts",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="intent_id_to_workspace_publication_intents",
    ),
    MutationCoverageEntry(
        table_name="workspace_publication_supersedes_links",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="successor_publication_id_to_published_revisions",
    ),
    MutationCoverageEntry(
        table_name="git_lfs_publication_intent_proofs",
        resource_category=MutationResourceCategory.ARTIFACT_PUBLICATION,
        session_binding="intent_id_to_workspace_publication_intents",
    ),
    MutationCoverageEntry(
        table_name="git_lfs_publication_closures",
        resource_category=MutationResourceCategory.ARTIFACT_PUBLICATION,
        session_binding="publication_id_to_published_revisions",
    ),
    MutationCoverageEntry(
        table_name="git_lfs_publication_pins",
        resource_category=MutationResourceCategory.ARTIFACT_PUBLICATION,
        session_binding="publication_id_to_published_revisions",
    ),
    MutationCoverageEntry(
        table_name="artifact_materialization_records",
        resource_category=MutationResourceCategory.ARTIFACT_PUBLICATION,
        session_binding="sandbox_workspace_id_to_workspace",
    ),
    MutationCoverageEntry(
        table_name="scientific_chain_selection_records",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="attempt_id_to_scientific_attempts",
    ),
    MutationCoverageEntry(
        table_name="scientific_selection_head_records",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="attempt_id_to_scientific_attempts",
    ),
    MutationCoverageEntry(
        table_name="scientific_selection_occurrence_records",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="attempt_id_to_scientific_attempts",
    ),
    MutationCoverageEntry(
        table_name="scientific_operation_disposition_records",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="attempt_id_to_scientific_attempts",
    ),
    MutationCoverageEntry(
        table_name="scientific_effect_adoption_records",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="attempt_id_to_scientific_attempts",
    ),
    MutationCoverageEntry(
        table_name="scientific_artifact_materialization_records",
        resource_category=MutationResourceCategory.ARTIFACT_PUBLICATION,
        session_binding="attempt_id_to_scientific_attempts",
    ),
    MutationCoverageEntry(
        table_name="scientific_attempt_closure_request_records",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="attempt_id_to_scientific_attempts",
    ),
    MutationCoverageEntry(
        table_name="scientific_attempt_closure_response_records",
        resource_category=MutationResourceCategory.CANONICAL_SQLITE,
        session_binding="attempt_id_to_scientific_attempts",
    ),
)

# These records are either deliberately Host-global or inactive source-only
# candidate schemas.  They are named in the manifest so adding an unclassified
# canonical table changes coverage validation instead of silently weakening a
# receipt.  A candidate table must move into guarded coverage before activation.
HOST_MUTATION_GLOBAL_EXCLUSIONS: Final[tuple[dict[str, str], ...]] = (
    {
        "table_name": "artifact_blob_gc_queue",
        "reason": "host_global_blob_gc_without_session_identity",
    },
    {
        "table_name": "sandbox_image_records",
        "reason": "host_global_immutable_image_catalog",
    },
    {
        "table_name": "scientific_attempt_closure_records",
        "reason": "post_quiescence_immutable_seal_bound_to_exact_receipt",
    },
    {
        "table_name": "project_repository_binding_versions",
        "reason": "host_operator_immutable_repository_binding_versions",
    },
    {
        "table_name": "project_repository_active_bindings",
        "reason": "host_operator_repository_binding_activation_authority",
    },
    {
        "table_name": "project_repository_binding_lifecycle_events",
        "reason": "host_operator_append_only_repository_binding_lifecycle",
    },
    {
        "table_name": "project_repository_binding_retirement_receipts",
        "reason": "host_operator_immutable_repository_binding_retirement_receipts",
    },
    {
        "table_name": "repository_binding_mapping_receipts",
        "reason": "host_operator_immutable_legacy_repository_mapping_receipts",
    },
    {
        "table_name": "session_repository_binding_pins",
        "reason": "host_owned_immutable_session_repository_identity",
    },
    {
        "table_name": "repository_credential_issuance_records",
        "reason": "host_repository_security_credential_ledger",
    },
    {
        "table_name": "repository_private_namespace_records",
        "reason": "host_repository_retention_namespace_authority",
    },
    {
        "table_name": "repository_private_namespace_holds",
        "reason": "host_repository_retention_hold_authority",
    },
    {
        "table_name": "repository_private_namespace_retirement_receipts",
        "reason": "host_repository_retention_immutable_retirement_receipts",
    },
    {
        "table_name": "git_lfs_binding_policies",
        "reason": "host_operator_immutable_repository_lfs_policy",
    },
    {
        "table_name": "git_lfs_object_records",
        "reason": "host_global_repository_lfs_object_catalog",
    },
    {
        "table_name": "git_lfs_object_read_receipts",
        "reason": "host_global_immutable_lfs_object_attestations",
    },
    {
        "table_name": "git_lfs_closure_manifests",
        "reason": "host_global_immutable_lfs_closure_cache",
    },
    {
        "table_name": "git_lfs_closure_entries",
        "reason": "host_global_immutable_lfs_closure_cache_entries",
    },
    {
        "table_name": "git_lfs_closure_verifications",
        "reason": "host_global_immutable_lfs_verification_cache",
    },
    {
        "table_name": "git_lfs_closure_verification_entries",
        "reason": "host_global_immutable_lfs_verification_cache_entries",
    },
    {
        "table_name": "git_lfs_private_reachability_receipts",
        "reason": "host_repository_retention_lfs_reachability_authority",
    },
    {
        "table_name": "git_lfs_gc_candidate_receipts",
        "reason": "host_global_lfs_gc_candidate_ledger",
    },
    {
        "table_name": "git_lfs_gc_candidate_items",
        "reason": "host_global_lfs_gc_candidate_item_ledger",
    },
    {
        "table_name": "git_lfs_gc_deletion_receipts",
        "reason": "host_global_lfs_gc_deletion_ledger",
    },
    {
        "table_name": "executor_hpc_target_qualifications",
        "reason": "host_operator_immutable_executor_target_qualification",
    },
    {
        "table_name": "workspace_job_target_qualifications",
        "reason": "host_operator_immutable_job_target_qualification",
    },
    {
        "table_name": "scientific_file_effect_adoption_records",
        "reason": "inactive_source_only_scientific_file_candidate",
    },
    {
        "table_name": "scientific_deliverable_ref_records",
        "reason": "inactive_source_only_scientific_file_candidate",
    },
    {
        "table_name": "scientific_deliverable_bundle_records",
        "reason": "inactive_source_only_scientific_file_candidate",
    },
    {
        "table_name": "scientific_deliverable_bundle_entry_records",
        "reason": "inactive_source_only_scientific_file_candidate",
    },
    {
        "table_name": "scientific_deliverable_validation_receipt_records",
        "reason": "inactive_source_only_scientific_file_candidate",
    },
    {
        "table_name": "scientific_contract_epoch_records",
        "reason": "host_operator_inactive_scientific_contract_epoch",
    },
    {
        "table_name": "file_workspace_contract_epoch_records",
        "reason": "host_operator_inactive_file_workspace_contract_epoch",
    },
    {
        "table_name": "file_workspace_surface_freeze_records",
        "reason": "host_operator_inactive_file_workspace_freeze_receipt",
    },
    {
        "table_name": "file_workspace_public_epoch_records",
        "reason": "host_operator_inactive_file_workspace_public_epoch",
    },
    {
        "table_name": "file_workspace_session_contract_records",
        "reason": "inactive_source_only_session_contract_candidate",
    },
    {
        "table_name": "historical_artifact_inventory_records",
        "reason": "offline_operator_historical_migration_candidate",
    },
    {
        "table_name": "historical_artifact_migration_unit_records",
        "reason": "offline_operator_historical_migration_candidate",
    },
    {
        "table_name": "historical_artifact_ref_records",
        "reason": "offline_operator_historical_migration_candidate",
    },
    {
        "table_name": "historical_artifact_reference_rewrite_records",
        "reason": "offline_operator_historical_migration_candidate",
    },
    {
        "table_name": "historical_artifact_migration_unit_receipts",
        "reason": "offline_operator_historical_migration_candidate",
    },
    {
        "table_name": "historical_artifact_migration_global_receipts",
        "reason": "offline_operator_historical_migration_candidate",
    },
)

HOST_MUTATION_COVERAGE_MANIFEST: Final[dict[str, object]] = {
    "schema_id": "host_mutation_coverage_manifest@1",
    "manifest_id": HOST_MUTATION_COVERAGE_MANIFEST_ID,
    "covered_resources": [
        {
            "table_name": entry.table_name,
            "resource_category": entry.resource_category.value,
            "session_binding": entry.session_binding,
        }
        for entry in HOST_MUTATION_COVERAGE_ENTRIES
    ],
    "global_exclusions": list(HOST_MUTATION_GLOBAL_EXCLUSIONS),
    "writer_categories": sorted(kind.value for kind in MutationWriterKind),
}
HOST_MUTATION_COVERAGE_DIGEST: Final = canonical_digest(HOST_MUTATION_COVERAGE_MANIFEST)


_ALL_RESOURCES = frozenset(MutationResourceCategory)
WRITER_RESOURCE_CATEGORIES: Final[
    dict[MutationWriterKind, frozenset[MutationResourceCategory]]
] = {
    MutationWriterKind.AGENT_TURN: _ALL_RESOURCES,
    MutationWriterKind.RUNTIME_COMMAND: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.EVENT_OUTBOX,
            MutationResourceCategory.LEDGER,
        }
    ),
    MutationWriterKind.SANDBOX_PROCESS: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.EVENT_OUTBOX,
            MutationResourceCategory.ARTIFACT_PUBLICATION,
        }
    ),
    MutationWriterKind.CONTROLLED_OPERATION: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.EVENT_OUTBOX,
            MutationResourceCategory.ARTIFACT_PUBLICATION,
        }
    ),
    MutationWriterKind.CONTINUATION_DELIVERY: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.EVENT_OUTBOX,
        }
    ),
    MutationWriterKind.ENGINE_CALLBACK: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.EVENT_OUTBOX,
            MutationResourceCategory.ARTIFACT_PUBLICATION,
        }
    ),
    MutationWriterKind.ARTIFACT_PUBLISHER: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.ARTIFACT_PUBLICATION,
            MutationResourceCategory.EVENT_OUTBOX,
        }
    ),
    MutationWriterKind.REPORT_PUBLISHER: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.REPORT_PUBLICATION,
            MutationResourceCategory.ARTIFACT_PUBLICATION,
            MutationResourceCategory.EVENT_OUTBOX,
        }
    ),
    MutationWriterKind.EVENT_OUTBOX_PUBLISHER: frozenset(
        {MutationResourceCategory.EVENT_OUTBOX}
    ),
    MutationWriterKind.RUNNER_CALLBACK: frozenset(
        {
            MutationResourceCategory.CANONICAL_SQLITE,
            MutationResourceCategory.EVENT_OUTBOX,
            MutationResourceCategory.ARTIFACT_PUBLICATION,
        }
    ),
    MutationWriterKind.ATTEMPT_DRIVER: _ALL_RESOURCES,
    MutationWriterKind.SEAL_PUBLISHER: frozenset(),
    MutationWriterKind.LIVE_TOKEN_LEDGER: frozenset(
        {MutationResourceCategory.LEDGER, MutationResourceCategory.EVENT_OUTBOX}
    ),
}


def writer_allows_resource(
    owner_kind: MutationWriterKind,
    resource_category: MutationResourceCategory,
) -> bool:
    return resource_category in WRITER_RESOURCE_CATEGORIES.get(
        owner_kind,
        frozenset(),
    )


__all__ = [
    "AgentCapabilityReadinessActivationAuthority",
    "AgentCapabilityReadinessActivationError",
    "AgentRetirementLifecycleAuthority",
    "AgentRetirementLifecycleAuthorityError",
    "HOST_MUTATION_COVERAGE_DIGEST",
    "HOST_MUTATION_COVERAGE_ENTRIES",
    "HOST_MUTATION_COVERAGE_MANIFEST",
    "HOST_MUTATION_COVERAGE_MANIFEST_ID",
    "HOST_MUTATION_GLOBAL_EXCLUSIONS",
    "HOST_MUTATION_POLICY",
    "HOST_MUTATION_POLICY_DIGEST",
    "HOST_MUTATION_POLICY_ID",
    "HOST_MUTATION_RECEIPT_EVIDENCE_SCHEMA_ID",
    "HOST_MUTATION_SNAPSHOT_SCHEMA_ID",
    "MAX_QUIESCENCE_SNAPSHOT_BYTES",
    "MAX_QUIESCENCE_SNAPSHOT_ROWS",
    "MutationCoverageEntry",
    "MutationResourceCategory",
    "MutationWriteAuthority",
    "MutationWriteFencingError",
    "canonical_digest",
    "canonical_json_bytes",
    "bind_mutation_write_authority",
    "current_mutation_write_authority",
    "suspend_mutation_write_authority",
    "writer_allows_resource",
]
