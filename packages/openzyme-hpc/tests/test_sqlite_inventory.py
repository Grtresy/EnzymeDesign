from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import ResourceCapabilityKind
from openzyme_hpc import InventoryGeneration
from openzyme_hpc import QualificationReceiptStatus
from openzyme_hpc import SQLiteTargetInventoryRepository
from openzyme_hpc import SoftwareQualificationReceipt
from openzyme_hpc import TargetCapabilityFact
from openzyme_hpc import TargetInventoryPersistenceError
from openzyme_hpc import TargetToolchainInventory
from openzyme_hpc import install_hpc_inventory_schema_for_offline_migration


DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def _receipt(receipt_id: str = "receipt_1") -> SoftwareQualificationReceipt:
    return SoftwareQualificationReceipt.create(
        receipt_id=receipt_id,
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
        operations=("hmmbuild", "hmmsearch"),
        status=QualificationReceiptStatus.PASSED,
        observed_at="2026-08-20T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )


def _inventory(
    receipt: SoftwareQualificationReceipt,
    *,
    generation: int = 1,
) -> TargetToolchainInventory:
    return TargetToolchainInventory.create(
        target_id="hpc:primary",
        generation=generation,
        target_profile_digest=DIGEST,
        facts=(
            TargetCapabilityFact(
                capability_id="software.hmmer",
                kind=ResourceCapabilityKind.SOFTWARE,
                contract_version="1",
                version="3.4",
                operations=("hmmbuild", "hmmsearch"),
                environment_digest=OTHER_DIGEST,
                qualification_digest=receipt.receipt_digest,
                implementation_digest=DIGEST,
            ),
        ),
        qualification_receipt_digests=(receipt.receipt_digest,),
        valid_until=receipt.valid_until,
        created_at=receipt.observed_at,
    )


def _generation(
    inventory: TargetToolchainInventory,
    *,
    previous: str | None = None,
) -> InventoryGeneration:
    return InventoryGeneration.create(
        target_id=inventory.target_id,
        generation=inventory.generation,
        previous_inventory_digest=previous,
        inventory_digest=inventory.inventory_digest,
        published_by_actor_id="operator_1",
        published_at=inventory.created_at,
    )


def test_repository_publishes_and_reads_exact_explainable_inventory() -> None:
    connection = sqlite3.connect(":memory:")
    install_hpc_inventory_schema_for_offline_migration(connection)
    repository = SQLiteTargetInventoryRepository(connection)
    receipt = _receipt()
    inventory = _inventory(receipt)

    repository.publish(
        inventory,
        _generation(inventory),
        (receipt,),
        expected_previous_digest=None,
    )

    assert repository.latest("hpc:primary") == inventory
    assert repository.get("hpc:primary", 1) == inventory
    row = connection.execute(
        "SELECT inventory_json FROM openzyme_hpc_target_toolchain_inventories"
    ).fetchone()
    assert "software.hmmer" in str(row[0])


def test_repository_rejects_stale_predecessor_without_partial_receipt_rows() -> None:
    connection = sqlite3.connect(":memory:")
    install_hpc_inventory_schema_for_offline_migration(connection)
    repository = SQLiteTargetInventoryRepository(connection)
    first_receipt = _receipt()
    first = _inventory(first_receipt)
    repository.publish(
        first,
        _generation(first),
        (first_receipt,),
        expected_previous_digest=None,
    )
    second_receipt = _receipt("receipt_2")
    second = _inventory(second_receipt, generation=2)

    with pytest.raises(TargetInventoryPersistenceError, match="predecessor"):
        repository.publish(
            second,
            _generation(second, previous=OTHER_DIGEST),
            (second_receipt,),
            expected_previous_digest=OTHER_DIGEST,
        )

    assert repository.latest("hpc:primary") == first
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_hpc_software_qualification_receipts"
    ).fetchone()[0] == 1


def test_repository_tables_are_append_only() -> None:
    connection = sqlite3.connect(":memory:")
    install_hpc_inventory_schema_for_offline_migration(connection)
    repository = SQLiteTargetInventoryRepository(connection)
    receipt = _receipt()
    inventory = _inventory(receipt)
    repository.publish(
        inventory,
        _generation(inventory),
        (receipt,),
        expected_previous_digest=None,
    )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE openzyme_hpc_target_toolchain_inventories "
            "SET valid_until = valid_until"
        )
