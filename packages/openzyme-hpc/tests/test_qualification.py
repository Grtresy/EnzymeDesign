from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_extension_spi import QualificationSpec
from openzyme_hpc import InventoryGeneration
from openzyme_hpc import QualificationProbeKind
from openzyme_hpc import QualificationProbeOutcome
from openzyme_hpc import QualificationProbeRequest
from openzyme_hpc import SoftwareQualificationReceipt
from openzyme_hpc import TargetInventoryRepository
from openzyme_hpc import TargetQualificationActorKind
from openzyme_hpc import TargetQualificationCommand
from openzyme_hpc import TargetQualificationError
from openzyme_hpc import TargetQualificationWorkflow
from openzyme_hpc import TargetToolchainInventory


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


def _spec() -> QualificationSpec:
    return QualificationSpec(
        qualification_spec_id="hmmer.qualification.v1",
        owner_plugin_id="enzymedesign.hmmer",
        capability_id="software.hmmer",
        contract_version="1",
        version_argv=("hmmbuild", "-h"),
        smoke_argv=("hmmbuild", "fixture.hmm", "fixture.fasta"),
        expected_result_schema={"type": "object", "required": ["model_digest"]},
        required_resource_capabilities=(),
    )


def _command(
    actor_kind: TargetQualificationActorKind = TargetQualificationActorKind.OPERATOR,
) -> TargetQualificationCommand:
    return TargetQualificationCommand(
        command_id="qualify_1",
        actor_id="operator_1",
        actor_kind=actor_kind,
        target_id="hpc:primary",
        target_profile_digest=DIGEST,
        environment_digest=OTHER_DIGEST,
        specs=(_spec(),),
        observed_at="2026-08-20T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )


@dataclass(slots=True)
class _MemoryRepository(TargetInventoryRepository):
    inventories: list[TargetToolchainInventory]
    generations: list[InventoryGeneration]
    receipts: list[tuple[SoftwareQualificationReceipt, ...]]

    def __init__(self) -> None:
        self.inventories = []
        self.generations = []
        self.receipts = []

    def latest(self, target_id: str) -> TargetToolchainInventory | None:
        matches = [item for item in self.inventories if item.target_id == target_id]
        return None if not matches else matches[-1]

    def publish(
        self,
        inventory: TargetToolchainInventory,
        generation: InventoryGeneration,
        receipts: tuple[SoftwareQualificationReceipt, ...],
        *,
        expected_previous_digest: str | None,
    ) -> None:
        prior = self.latest(inventory.target_id)
        observed = None if prior is None else prior.inventory_digest
        assert observed == expected_previous_digest
        self.inventories.append(inventory)
        self.generations.append(generation)
        self.receipts.append(receipts)


@dataclass(slots=True)
class _ProbePort:
    in_doubt_once: bool = False
    dispatches: list[QualificationProbeRequest] | None = None
    reconciliations: list[QualificationProbeRequest] | None = None

    def __post_init__(self) -> None:
        self.dispatches = []
        self.reconciliations = []

    def dispatch(self, request: QualificationProbeRequest) -> QualificationProbeOutcome:
        assert self.dispatches is not None
        self.dispatches.append(request)
        if self.in_doubt_once:
            self.in_doubt_once = False
            return self._outcome(
                request,
                certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        return self._outcome(
            request,
            certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        )

    def reconcile(self, request: QualificationProbeRequest) -> QualificationProbeOutcome:
        assert self.reconciliations is not None
        self.reconciliations.append(request)
        return self._outcome(
            request,
            certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        )

    @staticmethod
    def _outcome(
        request: QualificationProbeRequest,
        *,
        certainty: ExternalEffectCertainty,
    ) -> QualificationProbeOutcome:
        return QualificationProbeOutcome(
            operation_id=request.operation_id,
            request_digest=request.request_digest,
            effect_certainty=certainty,
            succeeded=certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            output_digest=DIGEST,
            backend_receipt_digest=OTHER_DIGEST,
            observed_version=(
                "3.4" if request.probe_kind is QualificationProbeKind.VERSION else None
            ),
            expected_schema_matched=(
                True if request.probe_kind is QualificationProbeKind.SMOKE else None
            ),
        )


def test_operator_qualification_publishes_explainable_inventory() -> None:
    repository = _MemoryRepository()
    probe = _ProbePort()
    inventory = TargetQualificationWorkflow(probe, repository).execute(_command())

    assert inventory.generation == 1
    assert inventory.facts[0].capability_id == "software.hmmer"
    assert inventory.facts[0].version == "3.4"
    assert len(repository.receipts[0]) == 1
    assert len(probe.dispatches or []) == 2
    assert probe.reconciliations == []


def test_agent_cannot_probe_or_publish_inventory() -> None:
    repository = _MemoryRepository()
    probe = _ProbePort()

    with pytest.raises(TargetQualificationError) as error:
        TargetQualificationWorkflow(probe, repository).execute(
            _command(TargetQualificationActorKind.AGENT)
        )

    assert error.value.error_code == "target_qualification_actor_forbidden"
    assert probe.dispatches == []
    assert repository.inventories == []


def test_uncertain_probe_reconciles_same_occurrence_without_replay_or_fallback() -> None:
    repository = _MemoryRepository()
    probe = _ProbePort(in_doubt_once=True)
    inventory = TargetQualificationWorkflow(probe, repository).execute(_command())

    assert inventory.generation == 1
    assert len(probe.dispatches or []) == 2
    assert len(probe.reconciliations or []) == 1
    assert probe.reconciliations[0] is probe.dispatches[0]  # type: ignore[index]


def test_probe_identity_drift_fails_before_inventory_mutation() -> None:
    repository = _MemoryRepository()

    class _DriftedPort(_ProbePort):
        def dispatch(
            self,
            request: QualificationProbeRequest,
        ) -> QualificationProbeOutcome:
            outcome = super().dispatch(request)
            return QualificationProbeOutcome(
                operation_id="other_operation",
                request_digest=outcome.request_digest,
                effect_certainty=outcome.effect_certainty,
                succeeded=outcome.succeeded,
                output_digest=outcome.output_digest,
                backend_receipt_digest=outcome.backend_receipt_digest,
                observed_version=outcome.observed_version,
                expected_schema_matched=outcome.expected_schema_matched,
            )

    with pytest.raises(TargetQualificationError) as error:
        TargetQualificationWorkflow(_DriftedPort(), repository).execute(_command())

    assert error.value.error_code == "target_qualification_probe_identity_mismatch"
    assert repository.inventories == []


def test_nonterminal_probe_never_publishes_inventory() -> None:
    repository = _MemoryRepository()

    class _NonterminalPort(_ProbePort):
        def dispatch(
            self,
            request: QualificationProbeRequest,
        ) -> QualificationProbeOutcome:
            return self._outcome(
                request,
                certainty=ExternalEffectCertainty.EFFECT_KNOWN,
            )

    with pytest.raises(TargetQualificationError) as error:
        TargetQualificationWorkflow(_NonterminalPort(), repository).execute(_command())

    assert error.value.error_code == "target_qualification_not_terminal"
    assert repository.inventories == []
