from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import QualifiedExternalCapabilityFact
from openzyme_contracts import canonical_sha256_digest


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("qualification admission timestamp requires timezone")
    return parsed


@dataclass(frozen=True, slots=True)
class ExternalQualificationAdmissionBlocker:
    unit_digest: str
    error_code: str


@dataclass(frozen=True, slots=True)
class EnzymeDesignExternalQualificationAdmission:
    """Exact operational gate; it never chooses a replacement route."""

    plan_digest: str
    qualified_facts: tuple[QualifiedExternalCapabilityFact, ...]
    blockers: tuple[ExternalQualificationAdmissionBlocker, ...]
    admission_digest: str

    @classmethod
    def create(
        cls,
        *,
        plan: ExternalQualificationPlan,
        facts: tuple[QualifiedExternalCapabilityFact, ...],
        as_of: str,
    ) -> "EnzymeDesignExternalQualificationAdmission":
        now = _timestamp(as_of)
        fact_by_unit: dict[str, QualifiedExternalCapabilityFact] = {}
        for fact in facts:
            if fact.unit_digest in fact_by_unit:
                raise ExternalQualificationError(
                    "qualification_fact_duplicate",
                    "multiple qualification facts bind one exact unit",
                )
            if fact.fact_digest != canonical_sha256_digest(fact.identity_payload):
                raise ExternalQualificationError(
                    "qualified_external_fact_digest_mismatch",
                    "qualified external fact digest does not match its identity",
                )
            fact_by_unit[fact.unit_digest] = fact
        units = {item.unit_digest: item for item in plan.units}
        unexpected = sorted(set(fact_by_unit).difference(units))
        if unexpected:
            raise ExternalQualificationError(
                "qualification_fact_unplanned",
                "qualification facts contain units outside the exact plan",
            )
        qualified: list[QualifiedExternalCapabilityFact] = []
        blockers: list[ExternalQualificationAdmissionBlocker] = []
        for unit in plan.units:
            fact = fact_by_unit.get(unit.unit_digest)
            if fact is None:
                blockers.append(
                    ExternalQualificationAdmissionBlocker(
                        unit_digest=unit.unit_digest,
                        error_code="blocked_qualification_missing",
                    )
                )
                continue
            expected = (
                unit.capability_id,
                unit.operation,
                unit.route_id,
                unit.subject_kind,
                unit.subject_id,
                unit.source_digest,
                unit.build_digest,
                unit.configuration_digest,
                unit.validator_id,
            )
            observed = (
                fact.capability_id,
                fact.operation,
                fact.route_id,
                fact.subject_kind,
                fact.subject_id,
                fact.source_digest,
                fact.build_digest,
                fact.configuration_digest,
                fact.validator_id,
            )
            if observed != expected:
                blockers.append(
                    ExternalQualificationAdmissionBlocker(
                        unit_digest=unit.unit_digest,
                        error_code="blocked_qualification_identity_drift",
                    )
                )
                continue
            if _timestamp(fact.valid_until) <= now:
                blockers.append(
                    ExternalQualificationAdmissionBlocker(
                        unit_digest=unit.unit_digest,
                        error_code="blocked_qualification_expired",
                    )
                )
                continue
            qualified.append(fact)
        canonical_facts = tuple(sorted(qualified, key=lambda item: item.unit_digest))
        canonical_blockers = tuple(sorted(blockers, key=lambda item: item.unit_digest))
        payload = {
            "schema_version": "enzymedesign_external_qualification_admission@1",
            "plan_digest": plan.plan_digest,
            "qualified_fact_digests": [item.fact_digest for item in canonical_facts],
            "blockers": [
                {
                    "unit_digest": item.unit_digest,
                    "error_code": item.error_code,
                }
                for item in canonical_blockers
            ],
            "fallback_performed": False,
        }
        return cls(
            plan_digest=plan.plan_digest,
            qualified_facts=canonical_facts,
            blockers=canonical_blockers,
            admission_digest=canonical_sha256_digest(payload),
        )

    def available_routes(
        self,
        *,
        capability_id: str,
        operation: str,
    ) -> tuple[QualifiedExternalCapabilityFact, ...]:
        return tuple(
            item
            for item in self.qualified_facts
            if item.capability_id == capability_id and item.operation == operation
        )

    def admit_occurrence(
        self,
        *,
        unit_digest: str,
        route_id: str,
        subject_id: str,
    ) -> QualifiedExternalCapabilityFact:
        fact = next(
            (item for item in self.qualified_facts if item.unit_digest == unit_digest),
            None,
        )
        if fact is None:
            blocker = next(
                (item for item in self.blockers if item.unit_digest == unit_digest),
                None,
            )
            raise ExternalQualificationError(
                "blocked_qualification",
                "the exact external qualification unit is unavailable: "
                f"reason={blocker.error_code if blocker else 'unit_unknown'}",
            )
        if fact.route_id != route_id or fact.subject_id != subject_id:
            raise ExternalQualificationError(
                "blocked_qualification",
                "occurrence route or subject differs from the admitted unit",
            )
        return fact


__all__ = [
    "EnzymeDesignExternalQualificationAdmission",
    "ExternalQualificationAdmissionBlocker",
]
