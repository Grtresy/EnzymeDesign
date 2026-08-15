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
    ("agent_members", MutationResourceCategory.CANONICAL_SQLITE),
    ("agent_runtime_signals", MutationResourceCategory.CANONICAL_SQLITE),
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
        "failure_recovery_disposition_records",
        MutationResourceCategory.CANONICAL_SQLITE,
    ),
    ("inbox_messages", MutationResourceCategory.CANONICAL_SQLITE),
    ("lane_lifecycle_events", MutationResourceCategory.EVENT_OUTBOX),
    ("lanes", MutationResourceCategory.CANONICAL_SQLITE),
    ("memory_entries", MutationResourceCategory.CANONICAL_SQLITE),
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
    ("tasks", MutationResourceCategory.CANONICAL_SQLITE),
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

# These records are deliberately Host-global rather than session-scoped.  They are
# named in the manifest so adding an unclassified canonical table changes coverage
# validation instead of silently weakening a receipt.
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
