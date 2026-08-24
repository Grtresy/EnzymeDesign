from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from typing import Mapping
from typing import Sequence

from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationSafeReceipt
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import QualifiedExternalCapabilityFact
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_store_sqlite import SQLiteProtectedQualificationLedger

from .external_qualification import EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS
from .external_qualification import OPTIONAL_PROFILES
from .external_qualification import build_enzymedesign_external_qualification_plan
from .qualification_admission import EnzymeDesignExternalQualificationAdmission
from .qualification_live_runtime import LiveQualificationReceiptSetReport
from .qualification_live_runtime import verify_live_qualification_receipt_set
from .qualification_planning import ExternalQualificationBatch
from .qualification_planning import SafeIdentitySnapshot
from .qualification_planning import build_external_identity_gaps
from .qualification_planning import build_external_qualification_dry_plan
from .qualification_planning import discover_external_subject_identities
from .qualification_workspace_runtime import validate_hpc_live_bridge_snapshot


QUALIFIED_RUNTIME_ROOT = Path(
    "/home/grtresy/.local/state/openzyme/deployments/"
    "enzymedesign-qualified-runtime"
)
EXACT_BACKUP_SCOPES = (
    "adoption-ledger",
    "configuration",
    "qualification-receipts",
    "sqlite",
    "target-inventory",
    "wheel-lock",
)


def _timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} requires timezone")
    return parsed


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


class QualifiedRuntimeCutoverError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        require_identifier(code, field_name="code")
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class QualificationSourceCompatibilityProof:
    qualification_commit: str
    qualification_source_identity_digest: str
    deployment_commit: str
    deployment_source_identity_digest: str
    qualification_owner_closure_digest: str
    deployment_owner_closure_digest: str
    allowed_cutover_path_set_digest: str
    diff_digest: str
    proof_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "QualificationSourceCompatibilityProof":
        item = cls(**values, proof_digest="sha256:" + "0" * 64)
        if item.qualification_owner_closure_digest != item.deployment_owner_closure_digest:
            raise QualifiedRuntimeCutoverError(
                "cutover_qualified_owner_closure_drift",
                "deployment changed a qualified owner closure",
            )
        return replace(item, proof_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in ("qualification_commit", "deployment_commit"):
            value = getattr(self, name)
            if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a full lowercase git commit")
        for name in (
            "qualification_source_identity_digest",
            "deployment_source_identity_digest",
            "qualification_owner_closure_digest",
            "deployment_owner_closure_digest",
            "allowed_cutover_path_set_digest",
            "diff_digest",
            "proof_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        if self.proof_digest != "sha256:" + "0" * 64 and self.proof_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise QualifiedRuntimeCutoverError(
                "cutover_source_compatibility_digest_mismatch",
                "source compatibility proof digest drifted",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_cutover_source_compatibility@1",
            "qualification_commit": self.qualification_commit,
            "qualification_source_identity_digest": (
                self.qualification_source_identity_digest
            ),
            "deployment_commit": self.deployment_commit,
            "deployment_source_identity_digest": self.deployment_source_identity_digest,
            "qualification_owner_closure_digest": (
                self.qualification_owner_closure_digest
            ),
            "deployment_owner_closure_digest": self.deployment_owner_closure_digest,
            "allowed_cutover_path_set_digest": self.allowed_cutover_path_set_digest,
            "diff_digest": self.diff_digest,
            "qualified_owner_closure_unchanged": True,
            "deployment_source_claimed_qualified": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "proof_digest": self.proof_digest}


@dataclass(frozen=True, slots=True)
class CutoverQuiescenceSeal:
    observations: tuple[tuple[str, str], ...]
    unsettled_effect_count: int
    unknown_effect_count: int
    sealed_at: str
    seal_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "CutoverQuiescenceSeal":
        item = cls(**values, seal_digest="sha256:" + "0" * 64)
        return replace(item, seal_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.observations))
        if not ordered or len(set(ordered)) != len(ordered):
            raise ValueError("quiescence observations must be non-empty and unique")
        for owner, state in ordered:
            require_identifier(owner, field_name="owner")
            if state not in {"stopped", "isolated", "not_installed"}:
                raise ValueError("writer must be stopped, isolated or not installed")
        object.__setattr__(self, "observations", ordered)
        if self.unsettled_effect_count or self.unknown_effect_count:
            raise QualifiedRuntimeCutoverError(
                "cutover_quiescence_unsettled_effect",
                "cutover requires zero unsettled and unknown external effects",
            )
        _timestamp(self.sealed_at, field_name="sealed_at")
        require_digest(self.seal_digest, field_name="seal_digest")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_cutover_quiescence_seal@1",
            "observations": [
                {"owner_id": owner, "state": state}
                for owner, state in self.observations
            ],
            "unsettled_effect_count": self.unsettled_effect_count,
            "unknown_effect_count": self.unknown_effect_count,
            "sealed_at": self.sealed_at,
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "seal_digest": self.seal_digest}


@dataclass(frozen=True, slots=True)
class QualifiedRuntimeCutoverPlan:
    plan_id: str
    operator_id: str
    source_compatibility: QualificationSourceCompatibilityProof
    dry_plan_digest: str
    qualification_report_digest: str
    receipt_set_report_digest: str
    receipt_digests: tuple[str, ...]
    deployment_inventory: tuple[tuple[str, str], ...]
    backup_sources: tuple[tuple[str, str], ...]
    quiescence: CutoverQuiescenceSeal
    runtime_root: str
    created_at: str
    plan_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "QualifiedRuntimeCutoverPlan":
        item = cls(**values, plan_digest="sha256:" + "0" * 64)
        return replace(item, plan_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        require_identifier(self.plan_id, field_name="plan_id")
        require_identifier(self.operator_id, field_name="operator_id")
        for name in (
            "dry_plan_digest",
            "qualification_report_digest",
            "receipt_set_report_digest",
            "plan_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        receipts = tuple(sorted(self.receipt_digests))
        if len(receipts) != 44 or len(set(receipts)) != 44:
            raise QualifiedRuntimeCutoverError(
                "cutover_receipt_set_cardinality_invalid",
                "cutover requires exactly 44 unique Batch 1 receipts",
            )
        object.__setattr__(self, "receipt_digests", receipts)
        inventory = tuple(sorted(self.deployment_inventory))
        if len({name for name, _ in inventory}) != len(inventory):
            raise ValueError("deployment inventory keys must be unique")
        for _, digest in inventory:
            require_digest(digest, field_name="deployment_inventory_digest")
        object.__setattr__(self, "deployment_inventory", inventory)
        backups = tuple(sorted(self.backup_sources))
        if tuple(name for name, _ in backups) != EXACT_BACKUP_SCOPES:
            raise QualifiedRuntimeCutoverError(
                "cutover_backup_scope_incomplete",
                "cutover backup sources must close the exact six scopes",
            )
        object.__setattr__(self, "backup_sources", backups)
        if Path(self.runtime_root) != QUALIFIED_RUNTIME_ROOT:
            raise QualifiedRuntimeCutoverError(
                "cutover_runtime_root_drift",
                "cutover runtime root differs from the operator-approved path",
            )
        _timestamp(self.created_at, field_name="created_at")
        if self.plan_digest != "sha256:" + "0" * 64 and self.plan_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise QualifiedRuntimeCutoverError(
                "cutover_plan_digest_mismatch", "cutover plan digest drifted"
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_qualified_runtime_cutover_plan@1",
            "plan_id": self.plan_id,
            "operator_id": self.operator_id,
            "source_compatibility": self.source_compatibility.to_dict(),
            "dry_plan_digest": self.dry_plan_digest,
            "qualification_report_digest": self.qualification_report_digest,
            "receipt_set_report_digest": self.receipt_set_report_digest,
            "receipt_digests": list(self.receipt_digests),
            "deployment_inventory": dict(self.deployment_inventory),
            "backup_sources": dict(self.backup_sources),
            "quiescence": self.quiescence.to_dict(),
            "runtime_root": self.runtime_root,
            "created_at": self.created_at,
            "profiles": [
                "base",
                "research-provider",
                "hpc-primary",
                "hmmer",
                "docking",
            ],
            "alphafold": {
                "state": "deferred_optional_profile_capacity_unavailable",
                "qualified": False,
                "adopted": False,
                "cutover": False,
                "advertised": False,
            },
            "max_retries": 0,
            "dual_write": False,
            "fallback_performed": False,
            "mutation_applied": False,
            "live_occurrence_authorized": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "plan_digest": self.plan_digest}


@dataclass(frozen=True, slots=True)
class QualifiedRuntimeCutoverAuthority:
    authority_id: str
    plan_digest: str
    deployment_source_identity_digest: str
    operator_id: str
    occurrence_id: str
    authorized_at: str
    authority_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "QualifiedRuntimeCutoverAuthority":
        item = cls(**values, authority_digest="sha256:" + "0" * 64)
        return replace(item, authority_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in ("authority_id", "operator_id", "occurrence_id"):
            require_identifier(getattr(self, name), field_name=name)
        for name in (
            "plan_digest",
            "deployment_source_identity_digest",
            "authority_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        _timestamp(self.authorized_at, field_name="authorized_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_qualified_runtime_cutover_authority@1",
            "authority_id": self.authority_id,
            "plan_digest": self.plan_digest,
            "deployment_source_identity_digest": self.deployment_source_identity_digest,
            "operator_id": self.operator_id,
            "occurrence_id": self.occurrence_id,
            "authorized_at": self.authorized_at,
            "max_retries": 0,
            "fallback_allowed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "authority_digest": self.authority_digest}


@dataclass(frozen=True, slots=True)
class QualifiedRuntimeAdoptionLedger:
    plan_digest: str
    authority_digest: str
    source_compatibility_digest: str
    facts: tuple[QualifiedExternalCapabilityFact, ...]
    adopted_at: str
    ledger_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "QualifiedRuntimeAdoptionLedger":
        item = cls(**values, ledger_digest="sha256:" + "0" * 64)
        return replace(item, ledger_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in (
            "plan_digest",
            "authority_digest",
            "source_compatibility_digest",
            "ledger_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        facts = tuple(sorted(self.facts, key=lambda item: item.unit_digest))
        if len(facts) != 44 or len({item.unit_digest for item in facts}) != 44:
            raise QualifiedRuntimeCutoverError(
                "cutover_adoption_cardinality_invalid",
                "adoption ledger requires exactly 44 unique unit facts",
            )
        if any("alphafold" in item.capability_id.lower() for item in facts):
            raise QualifiedRuntimeCutoverError(
                "cutover_alphafold_adoption_forbidden",
                "deferred AlphaFold cannot enter this adoption ledger",
            )
        object.__setattr__(self, "facts", facts)
        _timestamp(self.adopted_at, field_name="adopted_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_qualified_runtime_adoption_ledger@1",
            "plan_digest": self.plan_digest,
            "authority_digest": self.authority_digest,
            "source_compatibility_digest": self.source_compatibility_digest,
            "facts": [item.to_dict() for item in self.facts],
            "adopted_at": self.adopted_at,
            "alphafold_adopted": False,
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "ledger_digest": self.ledger_digest}

    def admission(self, *, readiness_plan, as_of: str):
        return EnzymeDesignExternalQualificationAdmission.create(
            plan=readiness_plan,
            facts=self.facts,
            as_of=as_of,
        )


@dataclass(frozen=True, slots=True)
class CutoverStartupProof:
    plan_digest: str
    authority_digest: str
    adoption_ledger_digest: str
    distribution_digest: str
    mounted_component_count: int
    admitted_fact_count: int
    verified_at: str
    proof_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "CutoverStartupProof":
        item = cls(**values, proof_digest="sha256:" + "0" * 64)
        if item.admitted_fact_count != 44:
            raise QualifiedRuntimeCutoverError(
                "cutover_startup_adoption_incomplete",
                "startup readback requires exactly 44 admitted facts",
            )
        return replace(item, proof_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in (
            "plan_digest",
            "authority_digest",
            "adoption_ledger_digest",
            "distribution_digest",
            "proof_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        if self.mounted_component_count <= 0:
            raise ValueError("startup proof requires mounted components")
        _timestamp(self.verified_at, field_name="verified_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_qualified_runtime_startup_proof@1",
            "plan_digest": self.plan_digest,
            "authority_digest": self.authority_digest,
            "adoption_ledger_digest": self.adoption_ledger_digest,
            "distribution_digest": self.distribution_digest,
            "mounted_component_count": self.mounted_component_count,
            "admitted_fact_count": self.admitted_fact_count,
            "alphafold_advertised": False,
            "monitoring_wired": True,
            "verified_at": self.verified_at,
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "proof_digest": self.proof_digest}


@dataclass(frozen=True, slots=True)
class QualifiedRuntimeCutoverReceipt:
    plan_digest: str
    authority_digest: str
    adoption_ledger_digest: str
    startup_proof_digest: str
    backup_manifest_digest: str
    activated_at: str
    receipt_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "QualifiedRuntimeCutoverReceipt":
        item = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(item, receipt_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in (
            "plan_digest",
            "authority_digest",
            "adoption_ledger_digest",
            "startup_proof_digest",
            "backup_manifest_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        _timestamp(self.activated_at, field_name="activated_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_qualified_runtime_cutover_receipt@1",
            "plan_digest": self.plan_digest,
            "authority_digest": self.authority_digest,
            "adoption_ledger_digest": self.adoption_ledger_digest,
            "startup_proof_digest": self.startup_proof_digest,
            "backup_manifest_digest": self.backup_manifest_digest,
            "activated_at": self.activated_at,
            "cutover": True,
            "live_occurrence": False,
            "alphafold_cutover": False,
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class FirstLiveBoundaryReceipt:
    cutover_receipt_digest: str
    occurrence_id: str
    occurrence_authority_digest: str
    effect_certainty: str
    accepted_at: str
    receipt_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "FirstLiveBoundaryReceipt":
        item = cls(**values, receipt_digest="sha256:" + "0" * 64)
        if item.effect_certainty not in {"terminal_known", "dispatch_in_doubt"}:
            raise QualifiedRuntimeCutoverError(
                "cutover_first_live_no_effect_invalid",
                "first-live boundary records only accepted or unknown effects",
            )
        return replace(item, receipt_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in ("cutover_receipt_digest", "occurrence_authority_digest", "receipt_digest"):
            require_digest(getattr(self, name), field_name=name)
        require_identifier(self.occurrence_id, field_name="occurrence_id")
        _timestamp(self.accepted_at, field_name="accepted_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_cutover_first_live_boundary@1",
            "cutover_receipt_digest": self.cutover_receipt_digest,
            "occurrence_id": self.occurrence_id,
            "occurrence_authority_digest": self.occurrence_authority_digest,
            "effect_certainty": self.effect_certainty,
            "accepted_at": self.accepted_at,
            "recovery_boundary": "forward_only_preserve_evidence",
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class CutoverMonitoringSnapshot:
    cutover_receipt_digest: str
    activation_digest: str
    adoption_ledger_digest: str
    admitted_fact_count: int
    status: str
    diagnostic_ids: tuple[str, ...]
    observed_at: str
    snapshot_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "CutoverMonitoringSnapshot":
        item = cls(**values, snapshot_digest="sha256:" + "0" * 64)
        if item.status != "healthy" or item.admitted_fact_count != 44:
            raise QualifiedRuntimeCutoverError(
                "cutover_monitoring_unhealthy",
                "cutover monitoring requires one healthy 44-fact adoption",
            )
        return replace(
            item,
            snapshot_digest=canonical_sha256_digest(item.identity_payload),
        )

    def __post_init__(self) -> None:
        for name in (
            "cutover_receipt_digest",
            "activation_digest",
            "adoption_ledger_digest",
            "snapshot_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        for diagnostic_id in self.diagnostic_ids:
            require_identifier(diagnostic_id, field_name="diagnostic_id")
        _timestamp(self.observed_at, field_name="observed_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_cutover_monitoring_snapshot@1",
            "cutover_receipt_digest": self.cutover_receipt_digest,
            "activation_digest": self.activation_digest,
            "adoption_ledger_digest": self.adoption_ledger_digest,
            "admitted_fact_count": self.admitted_fact_count,
            "status": self.status,
            "diagnostic_ids": list(self.diagnostic_ids),
            "observed_at": self.observed_at,
            "secret_material_present": False,
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "snapshot_digest": self.snapshot_digest}


@dataclass(frozen=True, slots=True)
class CutoverRollbackReceipt:
    plan_digest: str
    authority_digest: str
    restored_backup_manifest_digest: str
    prior_activation_digest: str
    reason_code: str
    rolled_back_at: str
    receipt_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "CutoverRollbackReceipt":
        item = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(item, receipt_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in (
            "plan_digest",
            "authority_digest",
            "restored_backup_manifest_digest",
            "prior_activation_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        require_identifier(self.reason_code, field_name="reason_code")
        _timestamp(self.rolled_back_at, field_name="rolled_back_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_cutover_rollback_receipt@1",
            "plan_digest": self.plan_digest,
            "authority_digest": self.authority_digest,
            "restored_backup_manifest_digest": self.restored_backup_manifest_digest,
            "prior_activation_digest": self.prior_activation_digest,
            "reason_code": self.reason_code,
            "rolled_back_at": self.rolled_back_at,
            "before_first_live_only": True,
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class PostCutoverSmokePlan:
    plan_id: str
    cutover_receipt_digest: str
    adoption_ledger_digest: str
    unit_digest: str
    route_id: str
    subject_id: str
    created_at: str
    plan_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "PostCutoverSmokePlan":
        item = cls(**values, plan_digest="sha256:" + "0" * 64)
        return replace(item, plan_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        require_identifier(self.plan_id, field_name="plan_id")
        for name in (
            "cutover_receipt_digest",
            "adoption_ledger_digest",
            "unit_digest",
            "plan_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        require_identifier(self.route_id, field_name="route_id")
        require_identifier(self.subject_id, field_name="subject_id")
        _timestamp(self.created_at, field_name="created_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_post_cutover_smoke_plan@1",
            "plan_id": self.plan_id,
            "cutover_receipt_digest": self.cutover_receipt_digest,
            "adoption_ledger_digest": self.adoption_ledger_digest,
            "unit_digest": self.unit_digest,
            "route_id": self.route_id,
            "subject_id": self.subject_id,
            "created_at": self.created_at,
            "max_retries": 0,
            "fallback_allowed": False,
            "mutation_applied": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "plan_digest": self.plan_digest}


@dataclass(frozen=True, slots=True)
class PostCutoverSmokeAuthority:
    authority_id: str
    plan_digest: str
    operator_id: str
    occurrence_id: str
    authorized_at: str
    authority_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "PostCutoverSmokeAuthority":
        item = cls(**values, authority_digest="sha256:" + "0" * 64)
        return replace(item, authority_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in ("authority_id", "operator_id", "occurrence_id"):
            require_identifier(getattr(self, name), field_name=name)
        for name in ("plan_digest", "authority_digest"):
            require_digest(getattr(self, name), field_name=name)
        _timestamp(self.authorized_at, field_name="authorized_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_post_cutover_smoke_authority@1",
            "authority_id": self.authority_id,
            "plan_digest": self.plan_digest,
            "operator_id": self.operator_id,
            "occurrence_id": self.occurrence_id,
            "authorized_at": self.authorized_at,
            "max_retries": 0,
            "fallback_allowed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "authority_digest": self.authority_digest}


@dataclass(frozen=True, slots=True)
class PostCutoverSmokeReceipt:
    plan_digest: str
    authority_digest: str
    occurrence_id: str
    unit_digest: str
    backend_receipt_digest: str
    effect_certainty: str
    completed_at: str
    receipt_digest: str = ""

    @classmethod
    def create(cls, **values: object) -> "PostCutoverSmokeReceipt":
        item = cls(**values, receipt_digest="sha256:" + "0" * 64)
        if item.effect_certainty not in {"terminal_known", "dispatch_in_doubt"}:
            raise QualifiedRuntimeCutoverError(
                "cutover_smoke_effect_certainty_invalid",
                "post-cutover smoke must preserve its external effect certainty",
            )
        return replace(item, receipt_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        for name in (
            "plan_digest",
            "authority_digest",
            "unit_digest",
            "backend_receipt_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, name), field_name=name)
        require_identifier(self.occurrence_id, field_name="occurrence_id")
        _timestamp(self.completed_at, field_name="completed_at")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_post_cutover_smoke_receipt@1",
            "plan_digest": self.plan_digest,
            "authority_digest": self.authority_digest,
            "occurrence_id": self.occurrence_id,
            "unit_digest": self.unit_digest,
            "backend_receipt_digest": self.backend_receipt_digest,
            "effect_certainty": self.effect_certainty,
            "completed_at": self.completed_at,
            "retry_count": 0,
            "fallback_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


class ProtectedQualifiedRuntimeState:
    def __init__(self, root: Path = QUALIFIED_RUNTIME_ROOT) -> None:
        self.root = root

    def bootstrap(self) -> None:
        if self.root.exists() or self.root.is_symlink():
            self._require_directory(self.root)
            return
        parent = self.root.parent
        if not parent.exists() and not parent.is_symlink():
            self._require_directory(parent.parent)
            parent.mkdir(mode=0o700, parents=False)
        self._require_directory(parent)
        self.root.mkdir(mode=0o700, parents=False)
        self._require_directory(self.root)

    def _require_directory(self, path: Path) -> None:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise QualifiedRuntimeCutoverError(
                "cutover_protected_root_unsafe",
                "protected deployment directory ownership or mode is unsafe",
            )

    def _path(self, name: str) -> Path:
        require_identifier(name, field_name="protected_state_name")
        return self.root / f"{name}.json"

    def write_once(self, name: str, payload: Mapping[str, object]) -> Path:
        self.bootstrap()
        path = self._path(name)
        encoded = _canonical_bytes(payload)
        if path.exists() or path.is_symlink():
            current = self.read(name)
            if _canonical_bytes(current) != encoded:
                raise QualifiedRuntimeCutoverError(
                    "cutover_protected_state_conflict",
                    "existing protected deployment evidence differs",
                )
            return path
        temporary = self.root / f".{name}.{os.getpid()}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        self._require_file(path)
        return path

    def replace_exact(
        self,
        name: str,
        payload: Mapping[str, object],
        *,
        expected_prior_digest: str | None,
    ) -> Path:
        self.bootstrap()
        path = self._path(name)
        if expected_prior_digest is None:
            if path.exists() or path.is_symlink():
                raise QualifiedRuntimeCutoverError(
                    "cutover_activation_prior_state_drift",
                    "activation expected no prior deployment state",
                )
        else:
            prior = self.read(name)
            if canonical_sha256_digest(prior) != expected_prior_digest:
                raise QualifiedRuntimeCutoverError(
                    "cutover_activation_prior_state_drift",
                    "activation prior deployment state digest differs",
                )
        encoded = _canonical_bytes(payload)
        temporary = self.root / f".{name}.{os.getpid()}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path

    def read(self, name: str) -> dict[str, object]:
        path = self._path(name)
        self._require_file(path)
        return _load_object(path)

    def _require_file(self, path: Path) -> None:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise QualifiedRuntimeCutoverError(
                "cutover_protected_file_unsafe",
                "protected deployment file ownership or mode is unsafe",
            )


def reconstruct_batch_1_plans(packet: Mapping[str, object]):
    if (
        packet.get("schema_version")
        != "enzymedesign_post_preparation_operator_packet@1"
        or packet.get("claim") != "prepared_not_qualified"
        or packet.get("qualified") is not False
        or packet.get("cutover") is not False
        or packet.get("fallback_performed") is not False
    ):
        raise QualifiedRuntimeCutoverError(
            "cutover_qualification_packet_invalid",
            "qualification packet is not safe prepared evidence",
        )
    snapshot_payload = packet.get("prepared_snapshot")
    if not isinstance(snapshot_payload, Mapping):
        raise ValueError("qualification packet lacks prepared_snapshot")
    snapshot = SafeIdentitySnapshot.from_dict(snapshot_payload)
    validate_hpc_live_bridge_snapshot(snapshot)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.batch-1.exact-readiness",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
        credential_locator_ids=EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    dry_plan = build_external_qualification_dry_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=build_external_identity_gaps(discovery),
        batch=ExternalQualificationBatch.BATCH_1,
    )
    if dry_plan.dry_plan_digest != packet.get("batch_1_qualification_dry_plan_digest"):
        raise QualifiedRuntimeCutoverError(
            "cutover_qualification_dry_plan_drift",
            "reconstructed Batch 1 dry plan differs from protected packet",
        )
    return readiness, dry_plan


def verify_batch_1_adoption_evidence(
    *,
    packet_path: Path,
    authorization_path: Path,
    ledger_path: Path,
    receipt_set_path: Path,
    operator_id: str,
    verified_at: str,
) -> tuple[object, object, LiveQualificationReceiptSetReport]:
    packet = _load_object(packet_path)
    readiness, dry_plan = reconstruct_batch_1_plans(packet)
    authorization = ExternalQualificationOccurrenceAuthorization.from_dict(
        _load_object(authorization_path)
    )
    verified = verify_live_qualification_receipt_set(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        source_identity_digest=str(packet["source_identity_digest"]),
        operator_id=operator_id,
        authorizations=(authorization,),
        ledger=SQLiteProtectedQualificationLedger(ledger_path),
        verified_at=verified_at,
    )
    stored = _load_object(receipt_set_path)
    stored_receipts = stored.get("selected_receipts")
    stored_missing = stored.get("missing_unit_digests")
    stored_rejected = stored.get("rejected_receipts")
    stored_authorizations = stored.get("authorization_digests")
    if not (
        isinstance(stored_receipts, list)
        and isinstance(stored_missing, list)
        and isinstance(stored_rejected, list)
        and isinstance(stored_authorizations, list)
    ):
        raise ValueError("stored receipt-set payload shape is unsupported")
    reconstructed_stored = LiveQualificationReceiptSetReport.create(
        source_identity_digest=str(stored.get("source_identity_digest")),
        dry_plan_digest=str(stored.get("dry_plan_digest")),
        verified_at=str(stored.get("verified_at")),
        selected_receipts=tuple(
            ExternalQualificationSafeReceipt.from_dict(item)
            for item in stored_receipts
            if isinstance(item, Mapping)
        ),
        missing_unit_digests=tuple(str(item) for item in stored_missing),
        rejected_receipts=tuple(
            (str(item["receipt_digest"]), str(item["error_code"]))
            for item in stored_rejected
            if isinstance(item, Mapping)
        ),
        authorization_digests=tuple(str(item) for item in stored_authorizations),
    )
    if (
        reconstructed_stored.to_dict() != stored
        or tuple(item.receipt_digest for item in verified.selected_receipts)
        != tuple(item.receipt_digest for item in reconstructed_stored.selected_receipts)
        or verified.source_identity_digest
        != reconstructed_stored.source_identity_digest
        or verified.dry_plan_digest != reconstructed_stored.dry_plan_digest
        or not verified.qualified
        or len(verified.selected_receipts) != 44
    ):
        raise QualifiedRuntimeCutoverError(
            "cutover_qualification_receipt_set_drift",
            "stored Batch 1 receipt set differs from independent verification",
        )
    return readiness, dry_plan, verified


def build_adoption_ledger(
    *,
    readiness_plan,
    receipt_set: LiveQualificationReceiptSetReport,
    plan: QualifiedRuntimeCutoverPlan,
    authority: QualifiedRuntimeCutoverAuthority,
    adopted_at: str,
) -> QualifiedRuntimeAdoptionLedger:
    if authority.plan_digest != plan.plan_digest or (
        authority.deployment_source_identity_digest
        != plan.source_compatibility.deployment_source_identity_digest
    ):
        raise QualifiedRuntimeCutoverError(
            "cutover_authority_plan_drift", "cutover authority differs from plan"
        )
    now = _timestamp(adopted_at, field_name="adopted_at")
    units = {item.unit_digest: item for item in readiness_plan.units}
    facts = []
    for receipt in receipt_set.selected_receipts:
        unit = units.get(receipt.unit_digest)
        if unit is None:
            raise QualifiedRuntimeCutoverError(
                "cutover_adoption_unknown_unit", "receipt unit is absent from plan"
            )
        if _timestamp(receipt.valid_until, field_name="valid_until") <= now:
            raise QualifiedRuntimeCutoverError(
                "cutover_adoption_receipt_expired", "qualification receipt expired"
            )
        facts.append(
            QualifiedExternalCapabilityFact.create(
                capability_id=unit.capability_id,
                operation=unit.operation,
                route_id=unit.route_id,
                subject_kind=unit.subject_kind,
                subject_id=unit.subject_id,
                source_digest=unit.source_digest,
                build_digest=unit.build_digest,
                configuration_digest=unit.configuration_digest,
                validator_id=unit.validator_id,
                qualification_receipt_digest=receipt.receipt_digest,
                valid_until=receipt.valid_until,
                unit_digest=unit.unit_digest,
            )
        )
    return QualifiedRuntimeAdoptionLedger.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        source_compatibility_digest=plan.source_compatibility.proof_digest,
        facts=tuple(facts),
        adopted_at=adopted_at,
    )


def load_adoption_ledger(
    *,
    payload: Mapping[str, object],
    plan: QualifiedRuntimeCutoverPlan,
    authority: QualifiedRuntimeCutoverAuthority,
) -> QualifiedRuntimeAdoptionLedger:
    facts_payload = payload.get("facts")
    if not isinstance(facts_payload, list):
        raise ValueError("adoption ledger facts must be one list")
    facts = []
    for value in facts_payload:
        if not isinstance(value, Mapping):
            raise ValueError("adoption ledger fact must be one object")
        fact = QualifiedExternalCapabilityFact.create(
            capability_id=str(value["capability_id"]),
            operation=str(value["operation"]),
            route_id=str(value["route_id"]),
            subject_kind=ExternalQualificationSubjectKind(str(value["subject_kind"])),
            subject_id=str(value["subject_id"]),
            source_digest=str(value["source_digest"]),
            build_digest=str(value["build_digest"]),
            configuration_digest=str(value["configuration_digest"]),
            validator_id=str(value["validator_id"]),
            qualification_receipt_digest=str(
                value["qualification_receipt_digest"]
            ),
            valid_until=str(value["valid_until"]),
            unit_digest=str(value["unit_digest"]),
        )
        if fact.to_dict() != dict(value):
            raise QualifiedRuntimeCutoverError(
                "cutover_adoption_fact_persistence_drift",
                "one persisted adoption fact is not canonical",
            )
        facts.append(fact)
    ledger = QualifiedRuntimeAdoptionLedger.create(
        plan_digest=str(payload["plan_digest"]),
        authority_digest=str(payload["authority_digest"]),
        source_compatibility_digest=str(payload["source_compatibility_digest"]),
        facts=tuple(facts),
        adopted_at=str(payload["adopted_at"]),
    )
    if ledger.to_dict() != dict(payload):
        raise QualifiedRuntimeCutoverError(
            "cutover_adoption_ledger_persistence_drift",
            "persisted adoption ledger is not canonical",
        )
    if (
        ledger.plan_digest != plan.plan_digest
        or ledger.authority_digest != authority.authority_digest
        or ledger.source_compatibility_digest
        != plan.source_compatibility.proof_digest
    ):
        raise QualifiedRuntimeCutoverError(
            "cutover_adoption_ledger_binding_drift",
            "persisted adoption ledger differs from plan or authority",
        )
    return ledger


def backup_manifest_payload(
    sources: Sequence[tuple[str, Path]],
) -> dict[str, object]:
    ordered = tuple(sorted(sources, key=lambda item: item[0]))
    if tuple(name for name, _ in ordered) != EXACT_BACKUP_SCOPES:
        raise QualifiedRuntimeCutoverError(
            "cutover_backup_scope_incomplete", "backup source set is incomplete"
        )
    entries = []
    for name, path in ordered:
        if path.exists():
            data = path.read_bytes()
            state = "present"
        else:
            data = b""
            state = "absent"
        entries.append(
            {
                "scope": name,
                "pre_state": state,
                "byte_count": len(data),
                "content_digest": canonical_sha256_digest(
                    {"state": state, "bytes_hex": data.hex()}
                ),
            }
        )
    payload: dict[str, object] = {
        "schema_version": "enzymedesign_cutover_backup_manifest@1",
        "entries": entries,
        "independently_recoverable": True,
        "fallback_performed": False,
    }
    return {**payload, "manifest_digest": canonical_sha256_digest(payload)}


__all__ = [
    "EXACT_BACKUP_SCOPES",
    "QUALIFIED_RUNTIME_ROOT",
    "CutoverQuiescenceSeal",
    "CutoverMonitoringSnapshot",
    "CutoverRollbackReceipt",
    "CutoverStartupProof",
    "FirstLiveBoundaryReceipt",
    "PostCutoverSmokeAuthority",
    "PostCutoverSmokePlan",
    "PostCutoverSmokeReceipt",
    "ProtectedQualifiedRuntimeState",
    "QualificationSourceCompatibilityProof",
    "QualifiedRuntimeAdoptionLedger",
    "QualifiedRuntimeCutoverAuthority",
    "QualifiedRuntimeCutoverError",
    "QualifiedRuntimeCutoverPlan",
    "QualifiedRuntimeCutoverReceipt",
    "backup_manifest_payload",
    "build_adoption_ledger",
    "load_adoption_ledger",
    "reconstruct_batch_1_plans",
    "verify_batch_1_adoption_evidence",
]
