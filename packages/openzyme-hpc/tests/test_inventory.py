from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from openzyme_contracts import ResourceCapabilityKind
from openzyme_hpc import InventoryGeneration
from openzyme_hpc import QualificationReceiptStatus
from openzyme_hpc import SoftwareQualificationReceipt
from openzyme_hpc import TargetCapabilityFact
from openzyme_hpc import TargetHealthObservation
from openzyme_hpc import TargetHealthState
from openzyme_hpc import TargetToolchainInventory


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


def _fact(capability_id: str, *, version: str | None = "3.4") -> TargetCapabilityFact:
    return TargetCapabilityFact(
        capability_id=capability_id,
        kind=ResourceCapabilityKind.SOFTWARE,
        contract_version="1",
        version=version,
        operations=("hmmsearch", "hmmbuild"),
        environment_digest=DIGEST,
        qualification_digest=OTHER_DIGEST,
        implementation_digest=DIGEST,
    )


def _inventory(*facts: TargetCapabilityFact) -> TargetToolchainInventory:
    return TargetToolchainInventory.create(
        target_id="hpc:primary",
        generation=7,
        target_profile_digest=DIGEST,
        facts=facts,
        qualification_receipt_digests=(OTHER_DIGEST,),
        valid_until="2026-09-01T00:00:00Z",
        created_at="2026-08-20T00:00:00Z",
    )


def test_inventory_is_immutable_canonical_and_explainable() -> None:
    inventory = _inventory(
        _fact("software.hmmer"),
        _fact("software.mafft", version="7.526"),
    )

    assert tuple(fact.capability_id for fact in inventory.facts) == (
        "software.hmmer",
        "software.mafft",
    )
    assert inventory.inventory_digest.startswith("sha256:")
    facts = inventory.to_resource_facts()
    assert facts[0].inventory_generation == 7
    assert facts[0].inventory_digest == inventory.inventory_digest
    with pytest.raises(FrozenInstanceError):
        inventory.generation = 8  # type: ignore[misc]


def test_inventory_digest_is_order_independent_but_fact_sensitive() -> None:
    hmmer = _fact("software.hmmer")
    mafft = _fact("software.mafft", version="7.526")

    assert _inventory(hmmer, mafft).inventory_digest == _inventory(
        mafft, hmmer
    ).inventory_digest
    assert _inventory(hmmer).inventory_digest != _inventory(mafft).inventory_digest


def test_inventory_rejects_duplicate_capability_facts() -> None:
    with pytest.raises(ValueError, match="unique capability IDs"):
        _inventory(_fact("software.hmmer"), _fact("software.hmmer"))


def test_qualification_receipt_binds_spec_target_environment_smoke_and_validity() -> None:
    receipt = SoftwareQualificationReceipt.create(
        receipt_id="qualification_1",
        qualification_spec_id="hmmer.qualification.v1",
        qualification_spec_digest=DIGEST,
        target_id="hpc:primary",
        environment_digest=OTHER_DIGEST,
        capability_id="software.hmmer",
        observed_version="3.4",
        version_query_receipt_digest=DIGEST,
        smoke_input_digest=DIGEST,
        smoke_result_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        status=QualificationReceiptStatus.PASSED,
        observed_at="2026-08-20T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )

    assert receipt.status is QualificationReceiptStatus.PASSED
    assert receipt.receipt_digest.startswith("sha256:")


def test_inventory_generation_chains_without_mutating_prior_inventory() -> None:
    inventory = _inventory(_fact("software.hmmer"))
    generation = InventoryGeneration.create(
        target_id=inventory.target_id,
        generation=inventory.generation,
        previous_inventory_digest=None,
        inventory_digest=inventory.inventory_digest,
        published_by_actor_id="operator_1",
        published_at="2026-08-20T00:01:00Z",
    )

    assert generation.inventory_digest == inventory.inventory_digest
    assert generation.generation_digest.startswith("sha256:")


def test_transient_health_does_not_change_inventory_identity() -> None:
    inventory = _inventory(_fact("software.hmmer"))
    healthy = TargetHealthObservation.create(
        target_id=inventory.target_id,
        state=TargetHealthState.HEALTHY,
        observed_at="2026-08-20T00:00:00Z",
    )
    down = TargetHealthObservation.create(
        target_id=inventory.target_id,
        state=TargetHealthState.DOWN,
        observed_at="2026-08-20T00:05:00Z",
    )

    assert healthy.observation_digest != down.observation_digest
    assert inventory.inventory_digest == _inventory(
        _fact("software.hmmer")
    ).inventory_digest
