from __future__ import annotations

from dataclasses import dataclass


RELATIONAL_RECORDS: tuple[str, ...] = (
    "projects",
    "episodes",
    "decisions",
    "approvals",
    "runs",
    "artifact_records",
    "reports",
)

RELATIONAL_ENTITY_RELATIONSHIPS: dict[str, tuple[str, ...]] = {
    "episodes": ("projects",),
    "decisions": ("episodes",),
    "approvals": ("episodes", "runs"),
    "runs": ("episodes", "approvals"),
    "artifact_records": ("episodes", "runs"),
    "reports": ("episodes", "artifact_records"),
}

CHECKPOINT_STATE_FIELDS: tuple[str, ...] = (
    "current_phase",
    "node_state",
    "pending_interrupt",
    "checkpoint_lineage",
    "resume_position",
)

ARTIFACT_STORE_OBJECTS: tuple[str, ...] = (
    "logs",
    "structure_files",
    "report_files",
    "result_files",
    "download_cache",
)

STABLE_IDENTIFIER_LINKS: dict[str, tuple[str, ...]] = {
    "project_id": ("projects", "episodes"),
    "episode_id": ("episodes", "decisions", "approvals", "runs", "artifact_records", "reports", "graph_thread"),
    "run_id": ("runs", "approvals", "artifact_records"),
    "artifact_id": ("artifact_records", "reports"),
}

GRAPH_STATE_DEPENDENCY_EXPECTATIONS: tuple[str, ...] = (
    "episode_id remains the single business and graph anchor",
    "graph state may reference canonical records but does not own them",
    "checkpoint data stays limited to execution-local workflow state",
)

HOST_UI_DEPENDENCY_EXPECTATIONS: tuple[str, ...] = (
    "Host API queries canonical relational records for business truth",
    "frontend read models project from canonical records plus graph progress",
    "artifact retrieval uses artifact metadata records rather than filesystem inference",
)


@dataclass(frozen=True, slots=True)
class StorageContract:
    relational_records: tuple[str, ...]
    relational_entity_relationships: dict[str, tuple[str, ...]]
    checkpoint_state_fields: tuple[str, ...]
    artifact_store_objects: tuple[str, ...]
    stable_identifier_links: dict[str, tuple[str, ...]]


def build_default_storage_contract() -> StorageContract:
    return StorageContract(
        relational_records=RELATIONAL_RECORDS,
        relational_entity_relationships=RELATIONAL_ENTITY_RELATIONSHIPS,
        checkpoint_state_fields=CHECKPOINT_STATE_FIELDS,
        artifact_store_objects=ARTIFACT_STORE_OBJECTS,
        stable_identifier_links=STABLE_IDENTIFIER_LINKS,
    )
