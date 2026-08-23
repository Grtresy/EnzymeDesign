from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import math
from pathlib import Path
from typing import Protocol

from packaging.specifiers import InvalidSpecifier
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion
from packaging.version import Version

from openzyme_contracts import ExternalIdentityGap
from openzyme_contracts import ExternalIdentityPreparationAction
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
from openzyme_contracts import ExternalIdentityPreparationPlan
from openzyme_contracts import ExternalIdentityPreparationResult
from openzyme_contracts import ExternalIdentityResolutionCandidate
from openzyme_contracts import ExternalIdentityResolutionDecision
from openzyme_contracts import ExternalQualificationBudgetPolicy
from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationEffectPolicy
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationFaultPolicy
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationAuthorizationRevocation
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import ExternalQualificationStoragePolicy
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import ExternalQualificationTtlPolicy
from openzyme_contracts import ExternalQualificationUnitSubjectBinding
from openzyme_contracts import ExternalRealSubjectIdentity
from openzyme_contracts import ExternalSubjectIdentityDiscoveryReport
from openzyme_contracts import ExternalSubjectIdentityObservation
from openzyme_contracts import ExternalSubjectIdentityStatus
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier
from openzyme_contracts import verify_external_qualification_dry_plan
from openzyme_contracts import verify_external_qualification_occurrence_authorization
from openzyme_contracts import verify_external_identity_decision
from openzyme_contracts import (
    verify_external_identity_preparation_occurrence_authorization,
)
from openzyme_contracts import verify_external_identity_preparation_plan


BATCH_1_PROFILES = (
    "base",
    "docking",
    "hmmer",
    "hpc-primary",
    "research-provider",
)
BATCH_2_PROFILES = ("alphafold",)

_SUBJECT_VERSION_FIELDS = {
    "software.alphafold3": "alphafold_version",
    "software.autodock-vina": "vina_version",
    "software.fpocket": "fpocket_version",
    "software.hmmer": "hmmer_version",
    "software.meeko": "meeko_version",
    "software.openbabel": "openbabel_version",
    "software.rdkit": "rdkit_version",
}


class ExternalQualificationBatch(StrEnum):
    BATCH_1 = "batch-1"
    BATCH_2_ALPHAFOLD = "batch-2-alphafold"


@dataclass(frozen=True, slots=True)
class OperatorIdentityResolutionSelection:
    projection_id: str
    candidate_id: str

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "OperatorIdentityResolutionSelection":
        allowed = {"projection_id", "candidate_id"}
        unexpected = set(payload).difference(allowed)
        if unexpected:
            raise ExternalQualificationError(
                "qualification_operator_selection_field_forbidden",
                f"operator selection contains unsupported fields: {sorted(unexpected)!r}",
            )
        return cls(
            projection_id=str(payload["projection_id"]),
            candidate_id=str(payload["candidate_id"]),
        )

    def __post_init__(self) -> None:
        require_identifier(self.projection_id, field_name="projection_id")
        require_identifier(self.candidate_id, field_name="candidate_id")

    def to_dict(self) -> dict[str, str]:
        return {
            "projection_id": self.projection_id,
            "candidate_id": self.candidate_id,
        }


@dataclass(frozen=True, slots=True)
class OperatorIdentityResolutionSelectionSet:
    selection_set_id: str
    operator_id: str
    decided_at: str
    snapshot_id: str
    constraints: tuple[str, ...]
    storage_selection_id: str
    selections: tuple[OperatorIdentityResolutionSelection, ...]

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "OperatorIdentityResolutionSelectionSet":
        allowed = {
            "schema_version",
            "selection_set_id",
            "operator_id",
            "decided_at",
            "snapshot_id",
            "constraints",
            "storage_selection_id",
            "selections",
        }
        unexpected = set(payload).difference(allowed)
        if unexpected:
            raise ExternalQualificationError(
                "qualification_operator_selection_field_forbidden",
                f"operator selection set contains unsupported fields: {sorted(unexpected)!r}",
            )
        if payload.get("schema_version") != (
            "enzymedesign_external_identity_resolution_selections@1"
        ):
            raise ValueError("operator identity selection schema is unsupported")
        return cls(
            selection_set_id=str(payload["selection_set_id"]),
            operator_id=str(payload["operator_id"]),
            decided_at=str(payload["decided_at"]),
            snapshot_id=str(payload["snapshot_id"]),
            constraints=tuple(str(item) for item in payload["constraints"]),  # type: ignore[union-attr]
            storage_selection_id=str(payload["storage_selection_id"]),
            selections=tuple(
                OperatorIdentityResolutionSelection.from_dict(item)
                for item in payload["selections"]  # type: ignore[union-attr]
            ),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "selection_set_id",
            "operator_id",
            "snapshot_id",
            "storage_selection_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        constraints = tuple(sorted(self.constraints))
        if not constraints or len(set(constraints)) != len(constraints):
            raise ValueError("operator constraints must be non-empty and unique")
        object.__setattr__(self, "constraints", constraints)
        for constraint in constraints:
            require_identifier(constraint, field_name="operator_constraint")
        selections = tuple(sorted(self.selections, key=lambda item: item.projection_id))
        if not selections or len({item.projection_id for item in selections}) != len(
            selections
        ):
            raise ValueError("operator selections must be non-empty and unique")
        object.__setattr__(self, "selections", selections)
        required_constraints = {
            "alphafold-batch-2-only",
            "first-effect-requires-new-authorization",
            "git-local-only-no-hosted-sync",
            "plan-only-current-authority",
        }
        if not required_constraints.issubset(constraints):
            raise ExternalQualificationError(
                "qualification_operator_selection_constraint_missing",
                "operator selections omit one or more hard phase constraints",
            )
        if self.storage_selection_id != "use-protected-operator-state-root":
            raise ExternalQualificationError(
                "qualification_storage_selection_unsupported",
                "current protected-storage implementation supports only the approved operator root",
            )

    @property
    def selection_set_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_external_identity_resolution_selections@1",
            "selection_set_id": self.selection_set_id,
            "operator_id": self.operator_id,
            "decided_at": self.decided_at,
            "snapshot_id": self.snapshot_id,
            "constraints": list(self.constraints),
            "storage_selection_id": self.storage_selection_id,
            "selections": [item.to_dict() for item in self.selections],
        }


@dataclass(frozen=True, slots=True)
class SafeSubjectProjection:
    projection_id: str
    logical_subject_id: str
    subject_kind: ExternalQualificationSubjectKind
    status: ExternalSubjectIdentityStatus
    component_ids: tuple[str, ...]
    safe_fields: tuple[SafeIdentityField, ...]
    missing_fields: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SafeSubjectProjection":
        return cls(
            projection_id=str(payload["projection_id"]),
            logical_subject_id=str(payload["logical_subject_id"]),
            subject_kind=ExternalQualificationSubjectKind(str(payload["subject_kind"])),
            status=ExternalSubjectIdentityStatus(str(payload["status"])),
            component_ids=tuple(str(item) for item in payload["component_ids"]),  # type: ignore[union-attr]
            safe_fields=tuple(
                SafeIdentityField(
                    field_id=str(item["field_id"]),
                    value=str(item["value"]),
                )
                for item in payload["safe_fields"]  # type: ignore[union-attr]
            ),
            missing_fields=tuple(
                str(item)
                for item in payload["missing_fields"]  # type: ignore[union-attr]
            ),
        )

    def __post_init__(self) -> None:
        if not self.projection_id or not self.logical_subject_id:
            raise ValueError("safe subject projection requires stable identities")
        if not self.component_ids:
            raise ValueError("safe subject projection requires affected components")
        if self.status is ExternalSubjectIdentityStatus.RESOLVED:
            required = {
                "endpoint_or_runtime_id",
                "account_or_deployment_digest",
                "api_or_route_variant",
                "environment_or_inventory_digest",
                "policy_digest",
            }
            present = {item.field_id for item in self.safe_fields}
            if required.difference(present):
                raise ValueError("resolved projection lacks real-subject closure")


@dataclass(frozen=True, slots=True)
class SafeIdentitySnapshot:
    snapshot_id: str
    source_digest: str
    observed_at: str
    projections: tuple[SafeSubjectProjection, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SafeIdentitySnapshot":
        allowed = {
            "schema_version",
            "snapshot_id",
            "source_digest",
            "observed_at",
            "projections",
        }
        unexpected = set(payload).difference(allowed)
        if unexpected:
            raise ExternalQualificationError(
                "qualification_safe_snapshot_field_forbidden",
                f"safe snapshot contains unsupported fields: {sorted(unexpected)!r}",
            )
        if payload.get("schema_version") != "enzymedesign_safe_identity_snapshot@1":
            raise ValueError("safe identity snapshot schema is unsupported")
        return cls(
            snapshot_id=str(payload["snapshot_id"]),
            source_digest=str(payload["source_digest"]),
            observed_at=str(payload["observed_at"]),
            projections=tuple(
                SafeSubjectProjection.from_dict(item)
                for item in payload["projections"]  # type: ignore[union-attr]
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_safe_identity_snapshot@1",
            "snapshot_id": self.snapshot_id,
            "source_digest": self.source_digest,
            "observed_at": self.observed_at,
            "projections": [
                {
                    "projection_id": item.projection_id,
                    "logical_subject_id": item.logical_subject_id,
                    "subject_kind": item.subject_kind.value,
                    "status": item.status.value,
                    "component_ids": list(item.component_ids),
                    "safe_fields": [field.to_dict() for field in item.safe_fields],
                    "missing_fields": list(item.missing_fields),
                }
                for item in self.projections
            ],
        }


def load_safe_identity_snapshot(path: Path) -> SafeIdentitySnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("safe identity snapshot must be an object")
    return SafeIdentitySnapshot.from_dict(payload)


def load_operator_identity_resolution_selections(
    path: Path,
) -> OperatorIdentityResolutionSelectionSet:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("operator identity selections must be an object")
    return OperatorIdentityResolutionSelectionSet.from_dict(payload)


def apply_external_identity_preparation_results(
    *,
    snapshot: SafeIdentitySnapshot,
    preparation_plan: ExternalIdentityPreparationPlan,
    results: tuple[ExternalIdentityPreparationResult, ...],
    observed_at: str,
) -> SafeIdentitySnapshot:
    """Project safe preparation outputs; this performs no credential or target access."""

    action_by_id = {item.action_id: item for item in preparation_plan.actions}
    result_by_action: dict[str, ExternalIdentityPreparationResult] = {}
    for result in results:
        if (
            result.preparation_plan_digest != preparation_plan.preparation_plan_digest
            or result.action_id not in action_by_id
            or result.action_id in result_by_action
        ):
            raise ExternalQualificationError(
                "qualification_preparation_result_set_mismatch",
                "preparation result set does not bind the exact plan actions",
            )
        action = action_by_id[result.action_id]
        if (
            result.owner_component_id != action.owner_component_id
            or result.input_binding_digest != action.input_binding_digest
            or tuple(item.field_id for item in result.safe_identity_fields)
            != action.expected_identity_fields
        ):
            raise ExternalQualificationError(
                "qualification_preparation_result_binding_mismatch",
                "preparation result differs from the exact action binding",
            )
        result_by_action[result.action_id] = result
    if set(result_by_action) != set(action_by_id):
        raise ExternalQualificationError(
            "qualification_preparation_result_coverage_mismatch",
            "effect-free rediscovery requires one successful result per batch action",
        )

    projections: list[SafeSubjectProjection] = []
    used_action_ids: set[str] = set()
    for projection in snapshot.projections:
        if not projection.missing_fields:
            projections.append(projection)
            continue
        matching = tuple(
            action
            for action in preparation_plan.actions
            if set(projection.missing_fields).issubset(action.expected_identity_fields)
        )
        if not matching:
            projections.append(projection)
            continue
        if len(matching) != 1:
            raise ExternalQualificationError(
                "qualification_preparation_projection_ambiguous",
                "prepared identity fields match multiple actions",
            )
        action = matching[0]
        result = result_by_action[action.action_id]
        prepared_fields = {
            item.field_id: item.value for item in result.safe_identity_fields
        }
        if set(projection.missing_fields).difference(prepared_fields):
            raise ExternalQualificationError(
                "qualification_preparation_projection_incomplete",
                "prepared result does not resolve the projection's exact missing fields",
            )
        used_action_ids.add(action.action_id)
        domain_fields = {
            item.field_id: item.value for item in projection.safe_fields
        }
        domain_fields.update(
            {
                field_id: prepared_fields[field_id]
                for field_id in projection.missing_fields
            }
        )
        if "credential_locator_id" in prepared_fields:
            domain_fields["credential_locator_id"] = prepared_fields[
                "credential_locator_id"
            ]
        closure_seed = {
            "projection_id": projection.projection_id,
            "logical_subject_id": projection.logical_subject_id,
            "component_ids": list(projection.component_ids),
            "domain_fields": dict(sorted(domain_fields.items())),
            "preparation_plan_digest": preparation_plan.preparation_plan_digest,
            "preparation_result_digest": result.result_digest,
        }
        generic_fields = {
            "endpoint_or_runtime_id": f"qualification.{projection.projection_id}",
            "account_or_deployment_digest": canonical_sha256_digest(
                {**closure_seed, "closure_kind": "account-or-deployment"}
            ),
            "api_or_route_variant": f"qualification.{projection.projection_id}.v1",
            "environment_or_inventory_digest": canonical_sha256_digest(
                {**closure_seed, "closure_kind": "environment-or-inventory"}
            ),
            "policy_digest": canonical_sha256_digest(
                {
                    "action_id": action.action_id,
                    "input_binding_digest": action.input_binding_digest,
                    "cleanup_action_id": action.cleanup_action_id,
                    "max_retries": preparation_plan.max_retries,
                    "fallback_allowed": False,
                }
            ),
        }
        domain_fields.update(generic_fields)
        projections.append(
            SafeSubjectProjection(
                projection_id=projection.projection_id,
                logical_subject_id=projection.logical_subject_id,
                subject_kind=projection.subject_kind,
                status=ExternalSubjectIdentityStatus.RESOLVED,
                component_ids=projection.component_ids,
                safe_fields=tuple(
                    SafeIdentityField(field_id, value)
                    for field_id, value in sorted(domain_fields.items())
                ),
                missing_fields=(),
            )
        )
    if used_action_ids != set(action_by_id):
        raise ExternalQualificationError(
            "qualification_preparation_result_unprojected",
            "one or more preparation results do not resolve a snapshot projection",
        )
    projection_payload = [
        {
            "projection_id": item.projection_id,
            "status": item.status.value,
            "safe_fields": [field.to_dict() for field in item.safe_fields],
            "missing_fields": list(item.missing_fields),
        }
        for item in sorted(projections, key=lambda value: value.projection_id)
    ]
    return SafeIdentitySnapshot(
        snapshot_id=(
            f"prepared.{preparation_plan.batch_id}."
            f"{canonical_sha256_digest(projection_payload)[7:23]}"
        ),
        source_digest=canonical_sha256_digest(
            {
                "source_snapshot_digest": snapshot.source_digest,
                "preparation_plan_digest": preparation_plan.preparation_plan_digest,
                "result_digests": sorted(item.result_digest for item in results),
            }
        ),
        observed_at=observed_at,
        projections=tuple(projections),
    )


def discover_external_subject_identities(
    *,
    readiness_plan: ExternalQualificationPlan,
    snapshot: SafeIdentitySnapshot,
) -> ExternalSubjectIdentityDiscoveryReport:
    observations: list[ExternalSubjectIdentityObservation] = []
    observed_units: set[str] = set()
    for projection in snapshot.projections:
        affected = tuple(
            unit.unit_digest
            for unit in readiness_plan.units
            if unit.component_id in projection.component_ids
            and unit.subject_id == projection.logical_subject_id
        )
        if not affected:
            continue
        safe_field_ids = {item.field_id for item in projection.safe_fields}
        affected_units = tuple(
            unit
            for unit in readiness_plan.units
            if unit.unit_digest in affected
        )
        if (
            projection.status is ExternalSubjectIdentityStatus.RESOLVED
            and any(
                unit.credential_locator is not None
                for unit in affected_units
            )
            and "credential_locator_id" not in safe_field_ids
        ):
            raise ExternalQualificationError(
                "qualification_resolved_credential_locator_missing",
                "resolved credential-bearing subject lacks a safe locator identity",
            )
        overlap = observed_units.intersection(affected)
        if overlap:
            raise ExternalQualificationError(
                "qualification_identity_observation_overlap",
                "one readiness unit is claimed by multiple safe projections",
            )
        observed_units.update(affected)
        effective_status = projection.status
        effective_missing_fields = projection.missing_fields
        version_requirements: dict[str, str] = {}
        for unit in affected_units:
            if unit.subject_version_spec is None:
                continue
            previous = version_requirements.setdefault(
                unit.capability_id,
                unit.subject_version_spec,
            )
            if previous != unit.subject_version_spec:
                raise ExternalQualificationError(
                    "qualification_subject_version_policy_collision",
                    "one subject capability has different version policies",
                )
        if (
            version_requirements
            and projection.status is ExternalSubjectIdentityStatus.RESOLVED
        ):
            safe_values = {
                item.field_id: item.value for item in projection.safe_fields
            }
            missing = set(projection.missing_fields)
            drifted = False
            for capability_id, version_spec in sorted(version_requirements.items()):
                version_field = _SUBJECT_VERSION_FIELDS.get(capability_id)
                if version_field is None:
                    raise ExternalQualificationError(
                        "qualification_subject_version_field_undeclared",
                        "versioned subject capability lacks a safe version field",
                    )
                observed_version = safe_values.get(version_field)
                if observed_version is None:
                    missing.add(version_field)
                    continue
                try:
                    satisfies = SpecifierSet(version_spec).contains(
                        Version(observed_version),
                        prereleases=True,
                    )
                except (InvalidSpecifier, InvalidVersion):
                    satisfies = False
                if not satisfies:
                    drifted = True
                    missing.add(f"{version_field}_satisfies_declared_spec")
            if drifted:
                effective_status = ExternalSubjectIdentityStatus.DRIFTED
            elif missing:
                effective_status = ExternalSubjectIdentityStatus.PARTIAL
            effective_missing_fields = tuple(sorted(missing))
        observation_source_digest = canonical_sha256_digest(
            {
                "snapshot_source_digest": snapshot.source_digest,
                "projection_id": projection.projection_id,
                "safe_fields": [item.to_dict() for item in projection.safe_fields],
                "subject_version_requirements": dict(
                    sorted(version_requirements.items())
                ),
            }
        )
        observations.append(
            ExternalSubjectIdentityObservation.create(
                observation_id=f"observation.{projection.projection_id}",
                logical_subject_id=projection.logical_subject_id,
                subject_kind=projection.subject_kind,
                status=effective_status,
                source_id=f"snapshot.{snapshot.snapshot_id}",
                source_digest=observation_source_digest,
                safe_fields=projection.safe_fields,
                missing_fields=effective_missing_fields,
                affected_unit_digests=affected,
            )
        )
    missing = {unit.unit_digest for unit in readiness_plan.units}.difference(
        observed_units
    )
    if missing:
        raise ExternalQualificationError(
            "qualification_identity_observation_coverage_gap",
            f"safe identity snapshot does not cover {len(missing)} readiness units",
        )
    return ExternalSubjectIdentityDiscoveryReport.create(
        report_id=f"discovery.{snapshot.snapshot_id}",
        readiness_plan_digest=readiness_plan.plan_digest,
        source_digest=snapshot.source_digest,
        observations=tuple(observations),
        observed_at=snapshot.observed_at,
        credential_material_accessed=False,
        external_effect_performed=False,
    )


_RECOMMENDED_ACTIONS: dict[str, tuple[str, str]] = {
    "provider.llm.primary": (
        "bind-current-provider-qualification-locator",
        "为当前 endpoint/model 的 intended account 绑定专用资格 locator 与最小 scope digest",
    ),
    "provider.tavily.primary": (
        "bind-official-tavily-account",
        "固定官方 Tavily service identity 与专用资格 account locator",
    ),
    "git.primary": (
        "create-local-isolated-git-lfs-repository",
        "只创建本地隔离 qualification repository 与 local LFS endpoint，禁止 hosted sync",
    ),
    "local.podman": (
        "adopt-digest-pinned-qualification-image",
        "采用或构建 digest-pinned qualification image，不修改 Host 全局软件",
    ),
    "local": (
        "adopt-local-scientific-image",
        "为该科学 Driver 采用 digest-pinned local Podman image closure",
    ),
    "hpc-primary": (
        "complete-executor-workspace-v2-inventory",
        "补齐 executor_workspace@2 inventory、native proofs 与 credential/policy identity",
    ),
}


def build_external_identity_gaps(
    report: ExternalSubjectIdentityDiscoveryReport,
) -> tuple[ExternalIdentityGap, ...]:
    gaps: list[ExternalIdentityGap] = []
    for observation in report.observations:
        if observation.status is ExternalSubjectIdentityStatus.RESOLVED:
            continue
        action_id, action = _RECOMMENDED_ACTIONS.get(
            observation.logical_subject_id,
            (
                "configure-intended-real-subject",
                "配置并冻结 intended real subject 的完整非 secret identity closure",
            ),
        )
        candidates = (
            ExternalIdentityResolutionCandidate(
                candidate_id=action_id,
                title="采用预期真实 subject",
                operator_action=action,
                effect_summary="当前只写配置决策；未来授权后执行隔离资格 effect",
                cost_summary="使用已批准的宽松 occurrence 与 batch 硬上限",
                security_summary="专用 locator、最小 scope、无 ambient fallback",
                prerequisite_ids=tuple(observation.missing_fields),
                recommended=True,
            ),
            ExternalIdentityResolutionCandidate(
                candidate_id="keep-profile-blocked",
                title="保持对应 profile 阻塞",
                operator_action="不提供该 subject，保留 blocked_identity 且不从声明中删除",
                effect_summary="无外部 effect",
                cost_summary="无资格执行费用",
                security_summary="不解析凭据且不启用替代 subject",
                recommended=False,
            ),
        )
        gaps.append(
            ExternalIdentityGap.create(
                gap_id=f"gap.{observation.observation_id}",
                logical_subject_id=observation.logical_subject_id,
                observation_digest=observation.observation_digest,
                missing_fields=observation.missing_fields
                or ("resolved_real_subject_closure",),
                affected_unit_digests=observation.affected_unit_digests,
                candidates=candidates,
            )
        )
    return tuple(sorted(gaps, key=lambda item: item.gap_id))


def build_external_identity_resolution_decisions(
    *,
    gaps: tuple[ExternalIdentityGap, ...],
    snapshot: SafeIdentitySnapshot,
    selection_set: OperatorIdentityResolutionSelectionSet,
) -> tuple[ExternalIdentityResolutionDecision, ...]:
    if selection_set.snapshot_id != snapshot.snapshot_id:
        raise ExternalQualificationError(
            "qualification_operator_selection_snapshot_drift",
            "operator identity selections do not bind the current safe snapshot",
        )
    gap_by_projection = {
        gap.gap_id.removeprefix("gap.observation."): gap for gap in gaps
    }
    selections = {item.projection_id: item for item in selection_set.selections}
    if set(selections) != set(gap_by_projection):
        raise ExternalQualificationError(
            "qualification_operator_selection_coverage_mismatch",
            "operator selections must cover every current identity gap exactly",
        )
    decisions: list[ExternalIdentityResolutionDecision] = []
    for projection_id, gap in sorted(gap_by_projection.items()):
        selection = selections[projection_id]
        decision = ExternalIdentityResolutionDecision.create(
            decision_id=f"decision.{selection_set.selection_set_id}.{projection_id}",
            gap_digest=gap.gap_digest,
            candidate_id=selection.candidate_id,
            operator_id=selection_set.operator_id,
            decided_at=selection_set.decided_at,
        )
        verify_external_identity_decision(gap, decision)
        decisions.append(decision)
    return tuple(decisions)


def _resolved_subjects(
    report: ExternalSubjectIdentityDiscoveryReport,
) -> tuple[ExternalRealSubjectIdentity, ...]:
    subjects: list[ExternalRealSubjectIdentity] = []
    for observation in report.observations:
        if observation.status is not ExternalSubjectIdentityStatus.RESOLVED:
            continue
        fields = {item.field_id: item.value for item in observation.safe_fields}
        subjects.append(
            ExternalRealSubjectIdentity.create(
                identity_id=f"identity.{observation.observation_id}",
                logical_subject_id=observation.logical_subject_id,
                subject_kind=observation.subject_kind,
                endpoint_or_runtime_id=fields["endpoint_or_runtime_id"],
                account_or_deployment_digest=fields["account_or_deployment_digest"],
                api_or_route_variant=fields["api_or_route_variant"],
                environment_or_inventory_digest=fields[
                    "environment_or_inventory_digest"
                ],
                policy_digest=fields["policy_digest"],
                source_observation_digest=observation.observation_digest,
            )
        )
    return tuple(subjects)


def _batch_budgets(
    batch: ExternalQualificationBatch,
) -> tuple[ExternalQualificationBudgetPolicy, ...]:
    if batch is ExternalQualificationBatch.BATCH_2_ALPHAFOLD:
        return (
            ExternalQualificationBudgetPolicy(
                "budget.batch-2.cash",
                "batch-2-alphafold",
                "cash",
                25.0,
                100.0,
                "usd",
            ),
            ExternalQualificationBudgetPolicy(
                "budget.alphafold.gpu-time",
                "enzymedesign.alphafold.hpc",
                "gpu-time",
                25.0,
                30.0,
                "minute",
            ),
        )
    return (
        ExternalQualificationBudgetPolicy(
            "budget.batch-1.cash", "batch-1", "cash", 100.0, 250.0, "usd"
        ),
        ExternalQualificationBudgetPolicy(
            "budget.llm.cash", "openzyme.runtime.llm", "cash", 50.0, 100.0, "usd"
        ),
        ExternalQualificationBudgetPolicy(
            "budget.llm.requests",
            "openzyme.runtime.llm",
            "request-count",
            10.0,
            20.0,
            "request",
        ),
        ExternalQualificationBudgetPolicy(
            "budget.tavily.cash",
            "openzyme.research.tavily",
            "cash",
            20.0,
            50.0,
            "usd",
        ),
        ExternalQualificationBudgetPolicy(
            "budget.git.payload",
            "openzyme.workspace.git.lfs",
            "payload-size",
            32.0,
            64.0,
            "mib",
        ),
        ExternalQualificationBudgetPolicy(
            "budget.podman.time",
            "openzyme.process.podman",
            "container-time",
            3000.0,
            3600.0,
            "second",
        ),
        ExternalQualificationBudgetPolicy(
            "budget.podman.memory",
            "openzyme.process.podman",
            "memory",
            2048.0,
            4096.0,
            "mib",
        ),
        ExternalQualificationBudgetPolicy(
            "budget.slurm.cpu-time",
            "openzyme.hpc.slurm",
            "cpu-time",
            120.0,
            180.0,
            "minute",
        ),
    )


_PREPARATION_EFFECTS: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "bind-current-provider-qualification-locator": (
        "provider.llm.qualification-locator.configure",
        "cleanup.provider.llm.qualification-locator",
        True,
        ("credential.llm.micuapi.qualification",),
    ),
    "bind-official-tavily-account": (
        "provider.tavily.dedicated-account.provision",
        "cleanup.provider.tavily.dedicated-account",
        True,
        ("credential.tavily.qualification",),
    ),
    "create-local-isolated-git-lfs-repository": (
        "git-lfs.local-isolated-repository.create",
        "cleanup.git-lfs.local-isolated-repository",
        False,
        (),
    ),
    "adopt-digest-pinned-qualification-image": (
        "podman.qualification-image.resolve",
        "cleanup.podman.qualification-image",
        False,
        (),
    ),
    "adopt-local-scientific-image": (
        "podman.scientific-image.resolve",
        "cleanup.podman.scientific-image",
        False,
        (),
    ),
    "complete-executor-workspace-v2-inventory": (
        "hpc.executor-workspace-v2.identity-resolve",
        "cleanup.hpc.identity-preparation",
        True,
        ("credential.hpc.diannan.qualification",),
    ),
}


@dataclass(slots=True)
class _ExternalIdentityPreparationActionGroup:
    owner_component_id: str
    logical_subject_id: str
    effect_id: str
    input_schema_id: str
    safe_input_fields: tuple[SafeIdentityField, ...]
    credential_locator_id: str | None
    cleanup_action_id: str
    requires_credential_material: bool
    gap_digests: set[str]
    decision_digests: set[str]
    expected_identity_fields: set[str]


_PREPARATION_INPUTS: dict[
    str,
    tuple[str, str, tuple[tuple[str, str], ...]],
] = {
    "bind-current-provider-qualification-locator": (
        "openzyme.runtime.llm",
        "provider-qualification-locator-preparation@1",
        (
            ("provider_id", "micuapi"),
            ("endpoint", "https://www.micuapi.ai/v1"),
            ("model", "gpt-5.5"),
            ("account_binding", "operator-bound-opaque-locator"),
        ),
    ),
    "bind-official-tavily-account": (
        "openzyme.research.tavily",
        "provider-qualification-locator-preparation@1",
        (
            ("provider_id", "tavily"),
            ("service_identity", "official-search-extract"),
            ("account_binding", "dedicated-qualification-account"),
        ),
    ),
    "create-local-isolated-git-lfs-repository": (
        "openzyme.workspace.git.lfs",
        "local-isolated-git-lfs-preparation@1",
        (
            ("repository_kind", "local-bare"),
            ("lfs_endpoint_kind", "local-only"),
            ("hosted_sync_allowed", "false"),
            ("payload_hard_limit_mib", "10"),
        ),
    ),
    "adopt-digest-pinned-qualification-image": (
        "openzyme.process.podman",
        "digest-pinned-image-preparation@1",
        (
            ("image_strategy", "repository-owned-digest-pinned"),
            ("platform", "linux-amd64"),
        ),
    ),
    "adopt-local-scientific-image": (
        "openzyme.process.podman",
        "digest-pinned-scientific-image-preparation@1",
        (
            ("image_strategy", "repository-owned-digest-pinned"),
            ("platform", "linux-amd64"),
        ),
    ),
    "complete-executor-workspace-v2-inventory": (
        "openzyme.hpc",
        "executor-workspace-v2-identity-preparation@1",
        (
            ("deployment_id", "aox-qualification-diannan"),
            ("target_alias", "Diannan-3090"),
            ("partition", "3090"),
            ("profile_schema", "executor_workspace@2"),
            ("configuration_mode", "qualification-only"),
        ),
    ),
}


def build_external_identity_preparation_plan(
    *,
    readiness_plan: ExternalQualificationPlan,
    discovery: ExternalSubjectIdentityDiscoveryReport,
    gaps: tuple[ExternalIdentityGap, ...],
    decisions: tuple[ExternalIdentityResolutionDecision, ...],
    selection_set: OperatorIdentityResolutionSelectionSet,
    batch: ExternalQualificationBatch,
) -> ExternalIdentityPreparationPlan:
    profiles = (
        BATCH_1_PROFILES
        if batch is ExternalQualificationBatch.BATCH_1
        else BATCH_2_PROFILES
    )
    unit_profile = {
        digest: profile.profile_id
        for profile in readiness_plan.profiles
        for digest in profile.unit_digests
    }
    batch_unit_digests = {
        unit.unit_digest
        for unit in readiness_plan.units
        if unit_profile[unit.unit_digest] in profiles
    }
    batch_gaps = tuple(
        gap
        for gap in gaps
        if batch_unit_digests.intersection(gap.affected_unit_digests)
    )
    decision_by_gap = {item.gap_digest: item for item in decisions}
    action_groups: dict[str, _ExternalIdentityPreparationActionGroup] = {}
    credential_locators: set[str] = set()
    batch_decisions: list[ExternalIdentityResolutionDecision] = []
    for gap in batch_gaps:
        try:
            decision = decision_by_gap[gap.gap_digest]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_preparation_decision_missing",
                "identity preparation lacks one selected batch gap decision",
            ) from exc
        candidate = verify_external_identity_decision(gap, decision)
        try:
            effect_id, cleanup_id, requires_credential, locators = _PREPARATION_EFFECTS[
                candidate.candidate_id
            ]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_preparation_candidate_not_executable",
                "selected identity candidate has no explicit preparation action",
            ) from exc
        owner_component_id, input_schema_id, safe_input_pairs = _PREPARATION_INPUTS[
            candidate.candidate_id
        ]
        if len(locators) > 1:
            raise ExternalQualificationError(
                "qualification_preparation_multiple_action_locators_forbidden",
                "one preparation action cannot bind multiple credential locators",
            )
        credential_locator_id = locators[0] if locators else None
        if (
            gap.logical_subject_id == "git.primary"
            and candidate.candidate_id != "create-local-isolated-git-lfs-repository"
        ):
            raise ExternalQualificationError(
                "qualification_git_hosted_sync_forbidden",
                "the approved Git subject is local-only and cannot target a hosted service",
            )
        projection_id = gap.gap_id.removeprefix("gap.observation.")
        expected_identity_fields = set(gap.missing_fields)
        if requires_credential:
            expected_identity_fields.add("credential_locator_id")
        if candidate.candidate_id == "complete-executor-workspace-v2-inventory":
            group_id = "hpc-primary"
        else:
            group_id = projection_id
            if candidate.candidate_id in {
                "adopt-digest-pinned-qualification-image",
                "adopt-local-scientific-image",
            }:
                effect_id = f"{effect_id}.{projection_id}"
                cleanup_id = f"{cleanup_id}.{projection_id}"
        image_group = {
            "podman-base": "base",
            "hmmer-local": "hmmer",
            "fpocket-local": "docking",
            "vina-local": "docking",
            "preprocess-podman": "docking",
        }.get(projection_id)
        group_logical_subject_id = gap.logical_subject_id
        action_safe_input_pairs = safe_input_pairs
        if image_group is not None:
            group_id = f"image-{image_group}"
            group_logical_subject_id = f"qualification.image.{image_group}"
            effect_id = f"podman.qualification-image.resolve.{image_group}"
            cleanup_id = f"cleanup.podman.qualification-image.{image_group}"
            input_schema_id = "qualification-image-group-preparation@1"
            action_safe_input_pairs = (
                ("image_strategy", "repository-owned-digest-pinned"),
                ("platform", "linux-amd64"),
                ("image_group", image_group),
            )
        group = action_groups.get(group_id)
        safe_input_fields = tuple(
            SafeIdentityField(field_id, value)
            for field_id, value in (
                *action_safe_input_pairs,
                ("projection_id", group_id),
            )
        )
        if group is None:
            action_groups[group_id] = _ExternalIdentityPreparationActionGroup(
                owner_component_id=owner_component_id,
                logical_subject_id=group_logical_subject_id,
                effect_id=effect_id,
                input_schema_id=input_schema_id,
                safe_input_fields=safe_input_fields,
                credential_locator_id=credential_locator_id,
                cleanup_action_id=cleanup_id,
                requires_credential_material=requires_credential,
                gap_digests={gap.gap_digest},
                decision_digests={decision.decision_digest},
                expected_identity_fields=expected_identity_fields,
            )
        else:
            if (
                group.owner_component_id != owner_component_id
                or group.logical_subject_id != group_logical_subject_id
                or group.effect_id != effect_id
                or group.input_schema_id != input_schema_id
                or group.safe_input_fields != safe_input_fields
                or group.credential_locator_id != credential_locator_id
                or group.cleanup_action_id != cleanup_id
                or group.requires_credential_material != requires_credential
            ):
                raise ExternalQualificationError(
                    "qualification_preparation_action_group_conflict",
                    "grouped identity gaps do not share one exact preparation effect",
                )
            group.gap_digests.add(gap.gap_digest)
            group.decision_digests.add(decision.decision_digest)
            group.expected_identity_fields.update(expected_identity_fields)
        credential_locators.update(locators)
        batch_decisions.append(decision)
    actions = tuple(
        ExternalIdentityPreparationAction.create(
            action_id=f"prepare.{batch.value}.{group_id}",
            owner_component_id=group.owner_component_id,
            logical_subject_id=group.logical_subject_id,
            gap_digests=tuple(sorted(group.gap_digests)),
            decision_digests=tuple(sorted(group.decision_digests)),
            effect_id=group.effect_id,
            input_schema_id=group.input_schema_id,
            safe_input_fields=group.safe_input_fields,
            credential_locator_id=group.credential_locator_id,
            mutating=True,
            requires_credential_material=group.requires_credential_material,
            expected_identity_fields=tuple(sorted(group.expected_identity_fields)),
            cleanup_action_id=group.cleanup_action_id,
            cleanup_deadline_seconds=24 * 60 * 60,
        )
        for group_id, group in action_groups.items()
    )
    storage = ExternalQualificationStoragePolicy(
        ledger_id="qualification.ledger.protected.operator-state-root.sqlite",
        private_evidence_root_id="qualification.evidence.protected.operator-state-root",
        public_export_secret_safe=True,
        credential_material_persisted=False,
    )
    plan = ExternalIdentityPreparationPlan.create(
        plan_id=f"enzymedesign.{batch.value}.identity-preparation-plan",
        batch_id=batch.value,
        source_digest=discovery.source_digest,
        discovery_report_digest=discovery.report_digest,
        decisions=tuple(batch_decisions),
        actions=actions,
        budgets=_batch_budgets(batch),
        credential_locator_ids=tuple(credential_locators),
        operator_constraints=selection_set.constraints,
        storage_policy=storage,
        max_retries=0,
        created_at=selection_set.decided_at,
        live_effect_authorized=False,
    )
    verify_external_identity_preparation_plan(
        plan,
        expected_source_digest=discovery.source_digest,
        expected_discovery_report_digest=discovery.report_digest,
        expected_gap_digests=tuple(gap.gap_digest for gap in batch_gaps),
    )
    return plan


def build_external_qualification_dry_plan(
    *,
    readiness_plan: ExternalQualificationPlan,
    discovery: ExternalSubjectIdentityDiscoveryReport,
    gaps: tuple[ExternalIdentityGap, ...],
    batch: ExternalQualificationBatch,
) -> ExternalQualificationDryPlan:
    profiles = (
        BATCH_1_PROFILES
        if batch is ExternalQualificationBatch.BATCH_1
        else BATCH_2_PROFILES
    )
    unit_profile = {
        digest: profile.profile_id
        for profile in readiness_plan.profiles
        for digest in profile.unit_digests
    }
    selected_units = tuple(
        unit
        for unit in readiness_plan.units
        if unit_profile[unit.unit_digest] in profiles
    )
    observation_by_unit = {
        digest: observation
        for observation in discovery.observations
        for digest in observation.affected_unit_digests
    }
    gap_by_unit: dict[str, list[str]] = {}
    for gap in gaps:
        for digest in gap.affected_unit_digests:
            gap_by_unit.setdefault(digest, []).append(gap.gap_id)
    subjects = _resolved_subjects(discovery)
    subject_by_observation = {
        item.source_observation_digest: item.subject_digest for item in subjects
    }
    safe_fields_by_observation = {
        observation.observation_digest: {
            item.field_id: item.value for item in observation.safe_fields
        }
        for observation in discovery.observations
    }
    bindings = []
    for unit in selected_units:
        observation = observation_by_unit[unit.unit_digest]
        subject_digest = subject_by_observation.get(observation.observation_digest)
        unit_gaps = tuple(gap_by_unit.get(unit.unit_digest, ()))
        credential_locator_id = (
            safe_fields_by_observation[observation.observation_digest].get(
                "credential_locator_id"
            )
            if subject_digest is not None and unit.credential_locator is not None
            else None
        )
        bindings.append(
            ExternalQualificationUnitSubjectBinding(
                unit_digest=unit.unit_digest,
                profile_id=unit_profile[unit.unit_digest],
                subject_digest=subject_digest,
                credential_locator_id=credential_locator_id,
                gap_ids=unit_gaps,
            )
        )
    storage = ExternalQualificationStoragePolicy(
        ledger_id="qualification.ledger.protected.sqlite",
        private_evidence_root_id="qualification.evidence.protected.root",
        public_export_secret_safe=True,
        credential_material_persisted=False,
    )
    ttl_policies = (
        ExternalQualificationTtlPolicy("ttl.provider", "provider", 24 * 60 * 60),
        ExternalQualificationTtlPolicy(
            "ttl.infrastructure", "git-podman-ssh-slurm", 7 * 24 * 60 * 60
        ),
        ExternalQualificationTtlPolicy(
            "ttl.scientific-software",
            "hmmer-vina-fpocket-preprocess",
            30 * 24 * 60 * 60,
        ),
        ExternalQualificationTtlPolicy("ttl.alphafold", "alphafold", 7 * 24 * 60 * 60),
    )
    effect_ids = (
        ("alphafold.fixed-monomer-predict",)
        if batch is ExternalQualificationBatch.BATCH_2_ALPHAFOLD
        else (
            "bio-http.read-smoke",
            "git-lfs.isolated-repository",
            "hpc.qualification-workspace",
            "llm.bounded-turn",
            "podman.qualification-container",
            "scientific.fixed-smoke",
            "slurm.test-jobs",
            "tavily.bounded-query",
        )
    )
    read_only_effects = {
        "bio-http.read-smoke",
        "llm.bounded-turn",
        "tavily.bounded-query",
    }
    effect_policies = tuple(
        ExternalQualificationEffectPolicy(
            effect_id=effect_id,
            scope_id=f"scope.{effect_id}",
            mutating=effect_id not in read_only_effects,
            cleanup_action_id=(
                None if effect_id in read_only_effects else f"cleanup.{effect_id}"
            ),
            cleanup_deadline_seconds=(
                None if effect_id in read_only_effects else 24 * 60 * 60
            ),
        )
        for effect_id in effect_ids
    )
    fault_policies = tuple(
        ExternalQualificationFaultPolicy(
            fault_id=fault_id,
            injection_point=f"adapter.{fault_id}",
            same_attempt_reconcile=fault_id == "response-loss-same-attempt",
            retry_allowed=False,
            fallback_allowed=False,
        )
        for fault_id in (
            "auth-or-config-no-effect",
            "operation-mismatch",
            "response-loss-same-attempt",
            "schema-mismatch",
            "timeout-before-effect",
        )
    )
    return ExternalQualificationDryPlan.create(
        plan_id=f"enzymedesign.{batch.value}.dry-plan",
        batch_id=batch.value,
        source_digest=discovery.source_digest,
        readiness_plan_digest=readiness_plan.plan_digest,
        discovery_report_digest=discovery.report_digest,
        unit_bindings=tuple(bindings),
        subjects=tuple(
            item
            for item in subjects
            if any(
                binding.subject_digest == item.subject_digest for binding in bindings
            )
        ),
        budgets=_batch_budgets(batch),
        credential_locator_ids=tuple(
            {
                binding.credential_locator_id
                for binding in bindings
                if binding.credential_locator_id is not None
            }
        ),
        effect_policies=effect_policies,
        fault_policies=fault_policies,
        ttl_policies=ttl_policies,
        storage_policy=storage,
        max_retries=0,
        created_at=discovery.observed_at,
        live_effect_authorized=False,
    )


@dataclass(frozen=True, slots=True)
class QualificationProbeBridgeMetadata:
    component_id: str
    selected_binding_digest: str
    unit_digest: str
    subject_digest: str | None
    plan_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "selected_binding_digest": self.selected_binding_digest,
            "unit_digest": self.unit_digest,
            "subject_digest": self.subject_digest,
            "plan_only": self.plan_only,
        }


def build_plan_only_probe_bridge_metadata(
    *,
    readiness_plan: ExternalQualificationPlan,
    dry_plan: ExternalQualificationDryPlan,
) -> tuple[QualificationProbeBridgeMetadata, ...]:
    units = {item.unit_digest: item for item in readiness_plan.units}
    metadata: list[QualificationProbeBridgeMetadata] = []
    for binding in dry_plan.unit_bindings:
        try:
            unit = units[binding.unit_digest]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_bridge_unit_not_selected",
                "dry-plan unit is absent from the selected readiness composition",
            ) from exc
        metadata.append(
            QualificationProbeBridgeMetadata(
                component_id=unit.component_id,
                selected_binding_digest=canonical_sha256_digest(
                    {
                        "component_id": unit.component_id,
                        "source_digest": unit.source_digest,
                        "build_digest": unit.build_digest,
                        "contract_digest": unit.contract_digest,
                    }
                ),
                unit_digest=unit.unit_digest,
                subject_digest=binding.subject_digest,
                plan_only=True,
            )
        )
    return tuple(sorted(metadata, key=lambda item: item.unit_digest))


class QualificationCredentialMaterialResolver(Protocol):
    def resolve(self, *, locator_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class QualificationBudgetReservation:
    reservation_id: str
    budget_id: str
    amount: float
    warning_crossed: bool


class QualificationBudgetLedger:
    """Plan-local reserve/settle ledger; it never shrinks or reroutes a probe."""

    def __init__(self, policies: tuple[ExternalQualificationBudgetPolicy, ...]) -> None:
        self._policies = {item.budget_id: item for item in policies}
        self._settled = {item.budget_id: 0.0 for item in policies}
        self._reservations: dict[str, QualificationBudgetReservation] = {}

    def reserve(
        self, *, reservation_id: str, budget_id: str, amount: float
    ) -> QualificationBudgetReservation:
        if reservation_id in self._reservations:
            prior = self._reservations[reservation_id]
            if prior.budget_id != budget_id or prior.amount != amount:
                raise ExternalQualificationError(
                    "qualification_budget_reservation_drift",
                    "budget reservation identity was reused with different values",
                )
            return prior
        try:
            policy = self._policies[budget_id]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_budget_policy_unknown",
                "budget reservation references an unknown policy",
            ) from exc
        if not math.isfinite(amount) or amount < 0:
            raise ValueError(
                "budget reservation amount must be finite and non-negative"
            )
        reserved = sum(
            item.amount
            for item in self._reservations.values()
            if item.budget_id == budget_id
        )
        if self._settled[budget_id] + reserved + amount > policy.hard_limit:
            raise ExternalQualificationError(
                "blocked_budget",
                "hard budget capacity is insufficient before dispatch",
            )
        item = QualificationBudgetReservation(
            reservation_id=reservation_id,
            budget_id=budget_id,
            amount=amount,
            warning_crossed=(
                self._settled[budget_id] + reserved + amount > policy.warning_limit
            ),
        )
        self._reservations[reservation_id] = item
        return item

    def settle(self, *, reservation_id: str, actual_amount: float) -> None:
        try:
            reservation = self._reservations.pop(reservation_id)
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_budget_reservation_unknown",
                "budget settlement references an unknown reservation",
            ) from exc
        if (
            not math.isfinite(actual_amount)
            or actual_amount < 0
            or actual_amount > reservation.amount
        ):
            raise ExternalQualificationError(
                "qualification_budget_settlement_invalid",
                "actual settlement must be within the reserved amount",
            )
        self._settled[reservation.budget_id] += actual_amount


class PlanOnlyIdentityPreparationBackendFactory:
    def __init__(
        self,
        *,
        credential_resolver: QualificationCredentialMaterialResolver,
        owner_builders: Mapping[str, Callable[..., object]] | None = None,
        result_recorder: Callable[[ExternalIdentityPreparationResult], None]
        | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver
        self._owner_builders = dict(owner_builders or {})
        self._result_recorder = result_recorder

    def build(
        self,
        *,
        plan: ExternalIdentityPreparationPlan,
        authorization: ExternalIdentityPreparationOccurrenceAuthorization | None,
        observed_at: str,
        occurrence_id: str,
        action_id: str,
        input_binding_digest: str,
        locator_id: str | None,
    ) -> object:
        verify_external_identity_preparation_occurrence_authorization(
            plan,
            authorization,
            observed_at=observed_at,
        )
        action = next(
            (item for item in plan.actions if item.action_id == action_id),
            None,
        )
        if action is None:
            raise ExternalQualificationError(
                "qualification_preparation_action_unknown",
                "identity preparation action is outside the exact plan",
            )
        if input_binding_digest != action.input_binding_digest:
            raise ExternalQualificationError(
                "qualification_preparation_input_binding_mismatch",
                "identity preparation request does not bind the action's exact input",
            )
        require_identifier(occurrence_id, field_name="occurrence_id")
        request_digest = canonical_sha256_digest(
            {
                "schema_version": "external_identity_preparation_request@1",
                "occurrence_id": occurrence_id,
                "preparation_plan_digest": plan.preparation_plan_digest,
                "authorization_digest": authorization.authorization_digest,
                "action_id": action.action_id,
                "owner_component_id": action.owner_component_id,
                "effect_id": action.effect_id,
                "input_binding_digest": action.input_binding_digest,
                "credential_locator_id": action.credential_locator_id,
            }
        )
        try:
            owner_builder = self._owner_builders[action.owner_component_id]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_preparation_backend_not_implemented",
                "no owner-scoped identity preparation bridge is installed",
            ) from exc
        material = None
        if action.requires_credential_material:
            if locator_id != action.credential_locator_id:
                raise ExternalQualificationError(
                    "qualification_preparation_credential_locator_mismatch",
                    "identity preparation requires the action's exact credential locator",
                )
            material = self._credential_resolver.resolve(locator_id=locator_id)
        elif locator_id is not None:
            raise ExternalQualificationError(
                "qualification_preparation_credential_locator_forbidden",
                "credential-free identity preparation cannot receive a locator",
            )
        result = owner_builder(
            plan=plan,
            authorization=authorization,
            action=action,
            occurrence_id=occurrence_id,
            request_digest=request_digest,
            credential_material=material,
        )
        if not isinstance(result, ExternalIdentityPreparationResult):
            raise ExternalQualificationError(
                "qualification_preparation_result_type_invalid",
                "owner preparation bridge returned an unsupported result",
            )
        observation = result.observation
        if (
            result.occurrence_id != occurrence_id
            or result.preparation_plan_digest != plan.preparation_plan_digest
            or result.authorization_digest != authorization.authorization_digest
            or result.action_id != action.action_id
            or result.owner_component_id != action.owner_component_id
            or result.input_binding_digest != action.input_binding_digest
            or observation.attempt_id != occurrence_id
            or observation.request_digest != request_digest
            or observation.operation != action.effect_id
        ):
            raise ExternalQualificationError(
                "qualification_preparation_result_binding_mismatch",
                "owner preparation result differs from the exact occurrence",
            )
        if tuple(
            item.field_id for item in result.safe_identity_fields
        ) != action.expected_identity_fields:
            raise ExternalQualificationError(
                "qualification_preparation_result_field_coverage_mismatch",
                "owner preparation result must cover the action's expected identity fields",
            )
        if self._result_recorder is not None:
            self._result_recorder(result)
        return result


class PlanOnlyQualificationBackendFactory:
    def __init__(
        self,
        *,
        credential_resolver: QualificationCredentialMaterialResolver,
        live_builder: Callable[..., object] | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver
        self._live_builder = live_builder

    def build(
        self,
        *,
        plan: ExternalQualificationDryPlan,
        authorization: ExternalQualificationOccurrenceAuthorization | None,
        observed_at: str,
        operator_id: str,
        locator_id: str,
        revocation: ExternalQualificationAuthorizationRevocation | None = None,
    ) -> object:
        verify_external_qualification_occurrence_authorization(
            plan,
            authorization,
            observed_at=observed_at,
            expected_operator_id=operator_id,
            revocation=revocation,
        )
        if self._live_builder is None:
            raise ExternalQualificationError(
                "qualification_live_backend_not_implemented",
                "no Adapter-owned live qualification bridge is installed",
            )
        if locator_id not in plan.credential_locator_ids:
            raise ExternalQualificationError(
                "qualification_credential_locator_mismatch",
                "live qualification factory requires one exact planned locator",
            )
        material = self._credential_resolver.resolve(locator_id=locator_id)
        return self._live_builder(
            plan=plan,
            authorization=authorization,
            locator_id=locator_id,
            credential_material=material,
        )


def qualification_plan_bundle(
    *,
    readiness_plan: ExternalQualificationPlan,
    snapshot: SafeIdentitySnapshot,
    selection_set: OperatorIdentityResolutionSelectionSet | None = None,
) -> dict[str, object]:
    discovery = discover_external_subject_identities(
        readiness_plan=readiness_plan,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    plans = tuple(
        build_external_qualification_dry_plan(
            readiness_plan=readiness_plan,
            discovery=discovery,
            gaps=gaps,
            batch=batch,
        )
        for batch in (
            ExternalQualificationBatch.BATCH_1,
            ExternalQualificationBatch.BATCH_2_ALPHAFOLD,
        )
    )
    for plan in plans:
        verify_external_qualification_dry_plan(
            plan,
            expected_source_digest=snapshot.source_digest,
            expected_readiness_plan_digest=readiness_plan.plan_digest,
        )
    decisions: tuple[ExternalIdentityResolutionDecision, ...] = ()
    preparation_plans: tuple[ExternalIdentityPreparationPlan, ...] = ()
    if selection_set is not None:
        decisions = build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selection_set,
        )
        preparation_plans = tuple(
            build_external_identity_preparation_plan(
                readiness_plan=readiness_plan,
                discovery=discovery,
                gaps=gaps,
                decisions=decisions,
                selection_set=selection_set,
                batch=batch,
            )
            for batch in (
                ExternalQualificationBatch.BATCH_1,
                ExternalQualificationBatch.BATCH_2_ALPHAFOLD,
            )
        )
    return {
        "schema_version": "enzymedesign_external_qualification_operator_packet@1",
        "claim": "plan_only",
        "credential_material_accessed": False,
        "external_effect_performed": False,
        "fallback_performed": False,
        "dry_plans_independently_verified": True,
        "discovery": discovery.to_dict(),
        "gaps": [item.to_dict() for item in gaps],
        "operator_selection_set": (
            None
            if selection_set is None
            else {
                **selection_set.to_dict(),
                "selection_set_digest": selection_set.selection_set_digest,
            }
        ),
        "identity_resolution_decisions": [item.to_dict() for item in decisions],
        "identity_preparation_plans": [item.to_dict() for item in preparation_plans],
        "dry_plans": [item.to_dict() for item in plans],
        "summary": {
            "observation_count": len(discovery.observations),
            "resolved_observation_count": sum(
                item.status is ExternalSubjectIdentityStatus.RESOLVED
                for item in discovery.observations
            ),
            "gap_count": len(gaps),
            "decision_count": len(decisions),
            "batch_1_preparation_authorizable": bool(preparation_plans),
            "batch_2_preparation_authorizable": bool(preparation_plans),
            "batch_1_authorizable": plans[0].authorizable,
            "batch_2_authorizable": plans[1].authorizable,
        },
    }


__all__ = [
    "BATCH_1_PROFILES",
    "BATCH_2_PROFILES",
    "ExternalQualificationBatch",
    "OperatorIdentityResolutionSelection",
    "OperatorIdentityResolutionSelectionSet",
    "PlanOnlyQualificationBackendFactory",
    "PlanOnlyIdentityPreparationBackendFactory",
    "QualificationBudgetLedger",
    "QualificationBudgetReservation",
    "QualificationCredentialMaterialResolver",
    "QualificationProbeBridgeMetadata",
    "SafeIdentitySnapshot",
    "SafeSubjectProjection",
    "build_external_identity_gaps",
    "build_external_identity_preparation_plan",
    "build_external_identity_resolution_decisions",
    "build_external_qualification_dry_plan",
    "build_plan_only_probe_bridge_metadata",
    "discover_external_subject_identities",
    "load_safe_identity_snapshot",
    "load_operator_identity_resolution_selections",
    "qualification_plan_bundle",
]
