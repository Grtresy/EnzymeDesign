from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelEntitySnapshot
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import TaskEvidenceValidation
from openzyme_kernel import FinishValidatorBinding
from openzyme_kernel import FinishValidatorRegistry
from openzyme_kernel import KernelContractError


def _digest(label: str) -> str:
    return canonical_sha256_digest({"label": label})


def _context() -> KernelQueryContext:
    return KernelQueryContext(
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        extension_bundle_digest=_digest("extension-bundle"),
        capability_binding_digest=_digest("binding"),
        correlation_id="correlation-1",
    )


def _task() -> KernelEntitySnapshot:
    return KernelEntitySnapshot(
        entity=KernelEntityRef(
            entity_kind="task",
            entity_id="task-1",
            state_version=3,
            entity_digest=_digest("task-1-v3"),
        ),
        payload={
            "session_id": "session-1",
            "owner_actor_id": "agent-1",
            "status": "in_progress",
        },
    )


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        evidence_id="evidence-1",
        evidence_kind=EvidenceKind.EXTENSION,
        contract_id="science-closure-1",
        owner_component_id="openzyme.science",
        project_id="project-1",
        session_id="session-1",
        task_id="task-1",
        subject_ref="closure-1",
        subject_digest=_digest("closure-1"),
        attributes={},
    )


@dataclass
class _Validator:
    validator_id: str
    accepted: bool
    calls: int = 0

    def validate(self, context, task, evidence_refs):  # noqa: ANN001
        self.calls += 1
        rejection_codes = () if self.accepted else ("formal_evidence_missing",)
        return TaskEvidenceValidation(
            accepted=self.accepted,
            validator_ids=(self.validator_id,),
            rejection_codes=rejection_codes,
            validation_digest=_digest(
                f"{self.validator_id}:{context.session_id}:"
                f"{task.entity.state_version}:{len(evidence_refs)}:{self.accepted}"
            ),
        )


def test_registry_runs_only_exact_required_validators_and_aggregates_rejection() -> None:
    science = _Validator("openzyme.science.finish", accepted=True)
    reporting = _Validator("openzyme.reporting.finish", accepted=False)
    unused = _Validator("example.unused.finish", accepted=True)
    registry = FinishValidatorRegistry(
        (
            FinishValidatorBinding("openzyme.science", science),
            FinishValidatorBinding("openzyme.reporting", reporting),
            FinishValidatorBinding("example.unused", unused),
        )
    )

    result = registry.validate(
        context=_context(),
        task=_task(),
        evidence_refs=(_evidence(),),
        required_validator_ids=(
            "openzyme.reporting.finish",
            "openzyme.science.finish",
        ),
    )

    assert result.accepted is False
    assert result.validator_ids == (
        "openzyme.reporting.finish",
        "openzyme.science.finish",
    )
    assert result.rejection_codes == ("formal_evidence_missing",)
    assert science.calls == 1
    assert reporting.calls == 1
    assert unused.calls == 0
    assert _task().payload["status"] == "in_progress"


def test_missing_required_validator_fails_closed_without_calling_an_alternative() -> None:
    available = _Validator("openzyme.science.finish", accepted=True)
    result = FinishValidatorRegistry(
        (FinishValidatorBinding("openzyme.science", available),)
    ).validate(
        context=_context(),
        task=_task(),
        evidence_refs=(_evidence(),),
        required_validator_ids=("openzyme.reporting.finish",),
    )

    assert result.accepted is False
    assert result.rejection_codes == ("required_finish_validator_unavailable",)
    assert available.calls == 0


def test_empty_validator_set_accepts_only_the_explicit_finish_validation_stage() -> None:
    result = FinishValidatorRegistry().validate(
        context=_context(),
        task=_task(),
        evidence_refs=(),
        required_validator_ids=(),
    )

    assert result.accepted is True
    assert result.validator_ids == ()
    assert result.rejection_codes == ()


def test_collisions_and_validator_identity_drift_are_rejected() -> None:
    one = _Validator("shared.finish", accepted=True)
    two = _Validator("shared.finish", accepted=True)
    with pytest.raises(KernelContractError, match="globally unique") as collision:
        FinishValidatorRegistry(
            (
                FinishValidatorBinding("plugin.one", one),
                FinishValidatorBinding("plugin.two", two),
            )
        )
    assert collision.value.code == "finish_validator_collision"

    class _DriftingValidator(_Validator):
        def validate(self, context, task, evidence_refs):  # noqa: ANN001
            return TaskEvidenceValidation(
                accepted=True,
                validator_ids=("another.finish",),
                rejection_codes=(),
                validation_digest=_digest("drift"),
            )

    registry = FinishValidatorRegistry(
        (
            FinishValidatorBinding(
                "plugin.one",
                _DriftingValidator("plugin.one.finish", accepted=True),
            ),
        )
    )
    with pytest.raises(KernelContractError, match="mounted id") as drift:
        registry.validate(
            context=_context(),
            task=_task(),
            evidence_refs=(),
            required_validator_ids=("plugin.one.finish",),
        )
    assert drift.value.code == "finish_validator_identity_drift"
