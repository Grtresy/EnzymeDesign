"""Pure planning and proof gates for the one-way offline @2 cutover."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .offline_cutover import OfflineBackupKind
from .offline_cutover import OfflineBackupReceipt
from .offline_cutover import SessionCutoverDisposition
from .offline_cutover import SessionCutoverDispositionKind


class CutoverInventoryKind(StrEnum):
    SOURCE = "source"
    WHEEL = "wheel"
    DISTRIBUTION = "distribution"
    ADAPTER = "adapter"
    PLUGIN = "plugin"
    DRIVER = "driver"
    SCHEMA = "schema"
    TABLE = "table"
    IMPORT = "import"
    CATALOG = "catalog"
    TARGET_INVENTORY = "target_inventory"
    AUTHORITY = "authority"
    WORKSPACE = "workspace"
    SESSION = "session"
    CONTINUATION = "continuation"
    UNSETTLED_EFFECT = "unsettled_effect"


class QuiescenceSurfaceKind(StrEnum):
    HOST = "host"
    PLUGIN_WORKER = "plugin_worker"
    AGENT_RUNTIME = "agent_runtime"
    PROCESS_ADAPTER = "process_adapter"
    RUNNER = "runner"
    UI = "ui"
    SQLITE_WRITER = "sqlite_writer"
    GIT_WRITER = "git_writer"


class RecoveryBoundary(StrEnum):
    PRE_ACTIVATION_EXACT_ROLLBACK = "pre_activation_exact_rollback"
    POST_ACTIVATION_FORWARD_ONLY = "post_activation_forward_only"


class CutoverRecoveryAction(StrEnum):
    RESTORE_EXACT_PRE_ACTIVATION_BACKUPS = (
        "restore_exact_pre_activation_backups"
    )
    QUIESCE_AND_FORWARD_REPAIR = "quiesce_and_forward_repair"


@dataclass(frozen=True, slots=True)
class CutoverInventoryObservation:
    inventory_kind: CutoverInventoryKind
    identity_digest: str
    item_count: int
    expected_disposition_digest: str
    unresolved_item_count: int = 0

    def __post_init__(self) -> None:
        require_digest(self.identity_digest, field_name="identity_digest")
        require_digest(
            self.expected_disposition_digest,
            field_name="expected_disposition_digest",
        )
        for field_name in ("item_count", "unresolved_item_count"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.unresolved_item_count > self.item_count:
            raise ValueError("unresolved_item_count cannot exceed item_count")

    def to_dict(self) -> dict[str, object]:
        return {
            "inventory_kind": self.inventory_kind.value,
            "identity_digest": self.identity_digest,
            "item_count": self.item_count,
            "expected_disposition_digest": self.expected_disposition_digest,
            "unresolved_item_count": self.unresolved_item_count,
        }


@dataclass(frozen=True, slots=True)
class OfflineCutoverDryRunProof:
    source_release_digest: str
    target_release_digest: str
    observations: tuple[CutoverInventoryObservation, ...]
    blocker_codes: tuple[str, ...]
    mutation_applied: bool = False
    external_effect_performed: bool = False
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        require_digest(self.source_release_digest, field_name="source_release_digest")
        require_digest(self.target_release_digest, field_name="target_release_digest")
        ordered = tuple(sorted(self.observations, key=lambda item: item.inventory_kind))
        kinds = tuple(item.inventory_kind for item in ordered)
        if len(kinds) != len(set(kinds)) or set(kinds) != set(CutoverInventoryKind):
            raise ValueError("dry run requires the exact closed inventory-kind set")
        object.__setattr__(self, "observations", ordered)
        object.__setattr__(self, "blocker_codes", tuple(sorted(set(self.blocker_codes))))
        if self.mutation_applied or self.external_effect_performed or self.fallback_performed:
            raise ValueError("offline dry run must remain no-effect and no-fallback")

    @property
    def ready(self) -> bool:
        return not self.blocker_codes

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_offline_cutover_dry_run@1",
            "source_release_digest": self.source_release_digest,
            "target_release_digest": self.target_release_digest,
            "observations": [item.to_dict() for item in self.observations],
            "blocker_codes": list(self.blocker_codes),
            "ready": self.ready,
            "mutation_applied": self.mutation_applied,
            "external_effect_performed": self.external_effect_performed,
            "fallback_performed": self.fallback_performed,
        }


def build_offline_cutover_dry_run(
    *,
    source_release_digest: str,
    target_release_digest: str,
    observations: tuple[CutoverInventoryObservation, ...],
) -> OfflineCutoverDryRunProof:
    blockers = [
        f"unresolved_{item.inventory_kind.value}"
        for item in observations
        if item.unresolved_item_count
    ]
    effects = next(
        (
            item
            for item in observations
            if item.inventory_kind is CutoverInventoryKind.UNSETTLED_EFFECT
        ),
        None,
    )
    if effects is not None and effects.item_count:
        blockers.append("unsettled_effect_present")
    return OfflineCutoverDryRunProof(
        source_release_digest=source_release_digest,
        target_release_digest=target_release_digest,
        observations=observations,
        blocker_codes=tuple(blockers),
    )


@dataclass(frozen=True, slots=True)
class QuiescenceRequirement:
    owner_id: str
    surface_kind: QuiescenceSurfaceKind

    def __post_init__(self) -> None:
        require_identifier(self.owner_id, field_name="owner_id")

    @property
    def key(self) -> tuple[QuiescenceSurfaceKind, str]:
        return self.surface_kind, self.owner_id


@dataclass(frozen=True, slots=True)
class QuiescenceObservation:
    owner_id: str
    surface_kind: QuiescenceSurfaceKind
    stopped_or_isolated: bool
    observation_digest: str
    writer_generation: int | None = None
    writer_fence: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.owner_id, field_name="owner_id")
        require_digest(self.observation_digest, field_name="observation_digest")
        pair = (self.writer_generation, self.writer_fence)
        if any(value is not None for value in pair) and not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 1
            for value in pair
        ):
            raise ValueError("writer generation and fence must be supplied together")

    @property
    def key(self) -> tuple[QuiescenceSurfaceKind, str]:
        return self.surface_kind, self.owner_id

    def to_dict(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "surface_kind": self.surface_kind.value,
            "stopped_or_isolated": self.stopped_or_isolated,
            "observation_digest": self.observation_digest,
            "writer_generation": self.writer_generation,
            "writer_fence": self.writer_fence,
        }


@dataclass(frozen=True, slots=True)
class OfflineQuiescenceReceipt:
    deployment_inventory_digest: str
    observations: tuple[QuiescenceObservation, ...]
    unsettled_effect_set_digest: str
    unknown_effect_count: int
    verified_at: str
    mutation_applied: bool = False

    def __post_init__(self) -> None:
        require_digest(
            self.deployment_inventory_digest,
            field_name="deployment_inventory_digest",
        )
        require_digest(
            self.unsettled_effect_set_digest,
            field_name="unsettled_effect_set_digest",
        )
        require_identifier(self.verified_at, field_name="verified_at")
        if self.unknown_effect_count != 0:
            raise ValueError("quiescence cannot discard an unknown external effect")
        if any(not item.stopped_or_isolated for item in self.observations):
            raise ValueError("quiescence requires every selected surface to stop")
        ordered = tuple(sorted(self.observations, key=lambda item: item.key))
        if len({item.key for item in ordered}) != len(ordered):
            raise ValueError("quiescence observations must be unique")
        object.__setattr__(self, "observations", ordered)
        if self.mutation_applied:
            raise ValueError("quiescence verification cannot mutate deployment state")

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_offline_quiescence_receipt@1",
                "deployment_inventory_digest": self.deployment_inventory_digest,
                "observations": [item.to_dict() for item in self.observations],
                "unsettled_effect_set_digest": self.unsettled_effect_set_digest,
                "unknown_effect_count": self.unknown_effect_count,
                "verified_at": self.verified_at,
                "mutation_applied": self.mutation_applied,
            }
        )


def verify_offline_quiescence(
    *,
    required: tuple[QuiescenceRequirement, ...],
    observed: tuple[QuiescenceObservation, ...],
    deployment_inventory_digest: str,
    unsettled_effect_identities: tuple[str, ...],
    unknown_effect_count: int,
    verified_at: str,
) -> OfflineQuiescenceReceipt:
    required_keys = {item.key for item in required}
    observed_keys = {item.key for item in observed}
    if len(required_keys) != len(required) or len(observed_keys) != len(observed):
        raise ValueError("quiescence requirements and observations must be unique")
    if required_keys != observed_keys:
        raise ValueError(
            "quiescence observation set differs from the exact required surface set"
        )
    if unsettled_effect_identities:
        raise ValueError("quiescence requires an empty unsettled-effect set")
    return OfflineQuiescenceReceipt(
        deployment_inventory_digest=deployment_inventory_digest,
        observations=observed,
        unsettled_effect_set_digest=canonical_sha256_digest(
            tuple(sorted(unsettled_effect_identities))
        ),
        unknown_effect_count=unknown_effect_count,
        verified_at=verified_at,
    )


@dataclass(frozen=True, slots=True)
class OfflineBackupObservation:
    backup_id: str
    backup_kind: OfflineBackupKind
    source_identity_digest: str
    source_content_digest: str
    source_size_bytes: int
    backup_identity_digest: str
    backup_content_digest: str
    backup_size_bytes: int
    independent_readback_digest: str
    verifier_id: str
    recoverable: bool
    verified_at: str

    def __post_init__(self) -> None:
        require_identifier(self.backup_id, field_name="backup_id")
        require_identifier(self.verifier_id, field_name="verifier_id")
        require_identifier(self.verified_at, field_name="verified_at")
        for field_name in (
            "source_identity_digest",
            "source_content_digest",
            "backup_identity_digest",
            "backup_content_digest",
            "independent_readback_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        for field_name in ("source_size_bytes", "backup_size_bytes"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "backup_id": self.backup_id,
            "backup_kind": self.backup_kind.value,
            "source_identity_digest": self.source_identity_digest,
            "source_content_digest": self.source_content_digest,
            "source_size_bytes": self.source_size_bytes,
            "backup_identity_digest": self.backup_identity_digest,
            "backup_content_digest": self.backup_content_digest,
            "backup_size_bytes": self.backup_size_bytes,
            "independent_readback_digest": self.independent_readback_digest,
            "verifier_id": self.verifier_id,
            "recoverable": self.recoverable,
            "verified_at": self.verified_at,
        }


@dataclass(frozen=True, slots=True)
class OfflineBackupSetProof:
    receipts: tuple[OfflineBackupReceipt, ...]
    pre_activation_boundary: RecoveryBoundary = (
        RecoveryBoundary.PRE_ACTIVATION_EXACT_ROLLBACK
    )
    post_activation_boundary: RecoveryBoundary = (
        RecoveryBoundary.POST_ACTIVATION_FORWARD_ONLY
    )

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.receipts, key=lambda item: item.backup_kind))
        if len(ordered) != 3 or {item.backup_kind for item in ordered} != set(
            OfflineBackupKind
        ):
            raise ValueError("backup proof requires database/configuration/storage")
        object.__setattr__(self, "receipts", ordered)

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_offline_backup_set_proof@1",
                "receipt_digests": [item.receipt_digest for item in self.receipts],
                "pre_activation_boundary": self.pre_activation_boundary.value,
                "post_activation_boundary": self.post_activation_boundary.value,
            }
        )


def verify_offline_backup_set(
    observations: tuple[OfflineBackupObservation, ...],
) -> OfflineBackupSetProof:
    receipts = []
    for item in observations:
        if (
            not item.recoverable
            or item.source_size_bytes != item.backup_size_bytes
            or item.source_content_digest != item.backup_content_digest
            or item.backup_content_digest != item.independent_readback_digest
        ):
            raise ValueError(
                f"{item.backup_kind.value} backup failed exact independent verification"
            )
        receipts.append(
            OfflineBackupReceipt(
                backup_id=item.backup_id,
                backup_kind=item.backup_kind,
                source_identity_digest=item.source_identity_digest,
                backup_identity_digest=item.backup_identity_digest,
                verification_digest=canonical_sha256_digest(item.to_dict()),
                recoverable=True,
                verified_at=item.verified_at,
            )
        )
    return OfflineBackupSetProof(tuple(receipts))


@dataclass(frozen=True, slots=True)
class LegacySessionCutoverObservation:
    session_id: str
    terminal: bool
    source_contract_id: str
    core_rows_exact: bool
    extension_rows_exact: bool
    workspace_backend_exact: bool
    authority_mapping_exact: bool
    inventory_binding_exact: bool
    continuations_settled: bool
    controlled_operations_settled: bool
    target_composition_pin_digest: str | None
    target_capability_binding_digest: str | None
    evidence_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.session_id, field_name="session_id")
        require_identifier(self.source_contract_id, field_name="source_contract_id")
        require_digest(self.evidence_digest, field_name="evidence_digest")
        for field_name in (
            "target_composition_pin_digest",
            "target_capability_binding_digest",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_digest(value, field_name=field_name)


def classify_legacy_session(
    observation: LegacySessionCutoverObservation,
) -> SessionCutoverDisposition:
    if observation.terminal:
        return SessionCutoverDisposition(
            session_id=observation.session_id,
            disposition=SessionCutoverDispositionKind.CLOSED_HISTORICAL_AT1,
            composition_pin_digest=None,
            capability_binding_digest=None,
            evidence_digest=observation.evidence_digest,
        )
    exact = all(
        (
            observation.core_rows_exact,
            observation.extension_rows_exact,
            observation.workspace_backend_exact,
            observation.authority_mapping_exact,
            observation.inventory_binding_exact,
            observation.continuations_settled,
            observation.controlled_operations_settled,
            observation.target_composition_pin_digest is not None,
            observation.target_capability_binding_digest is not None,
        )
    )
    return SessionCutoverDisposition(
        session_id=observation.session_id,
        disposition=(
            SessionCutoverDispositionKind.MIGRATED_AT2
            if exact
            else SessionCutoverDispositionKind.BLOCKED
        ),
        composition_pin_digest=(
            observation.target_composition_pin_digest if exact else None
        ),
        capability_binding_digest=(
            observation.target_capability_binding_digest if exact else None
        ),
        evidence_digest=observation.evidence_digest,
    )


def select_cutover_recovery_action(
    *,
    activation_epoch_persisted: bool,
    post_freeze_canonical_mutation_count: int,
) -> CutoverRecoveryAction:
    if (
        not isinstance(post_freeze_canonical_mutation_count, int)
        or isinstance(post_freeze_canonical_mutation_count, bool)
        or post_freeze_canonical_mutation_count < 0
    ):
        raise ValueError("post-freeze canonical mutation count must be non-negative")
    if activation_epoch_persisted or post_freeze_canonical_mutation_count:
        return CutoverRecoveryAction.QUIESCE_AND_FORWARD_REPAIR
    return CutoverRecoveryAction.RESTORE_EXACT_PRE_ACTIVATION_BACKUPS


__all__ = [
    "CutoverInventoryKind",
    "CutoverInventoryObservation",
    "CutoverRecoveryAction",
    "LegacySessionCutoverObservation",
    "OfflineBackupObservation",
    "OfflineBackupSetProof",
    "OfflineCutoverDryRunProof",
    "OfflineQuiescenceReceipt",
    "QuiescenceObservation",
    "QuiescenceRequirement",
    "QuiescenceSurfaceKind",
    "RecoveryBoundary",
    "build_offline_cutover_dry_run",
    "classify_legacy_session",
    "select_cutover_recovery_action",
    "verify_offline_backup_set",
    "verify_offline_quiescence",
]
