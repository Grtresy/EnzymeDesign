from __future__ import annotations

from importlib.resources import files
import json
import sqlite3

from openzyme_contracts import ResourceCapabilityKind

from .inventory import InventoryGeneration
from .inventory import SoftwareQualificationReceipt
from .inventory import TargetCapabilityFact
from .inventory import TargetToolchainInventory


class TargetInventoryPersistenceError(RuntimeError):
    error_code = "target_inventory_persistence_rejected"


def hpc_inventory_migration_sql() -> str:
    return (
        files("openzyme_hpc.migrations")
        .joinpath("001_target_toolchain_inventory.sql")
        .read_text()
    )


def install_hpc_inventory_schema_for_offline_migration(
    connection: sqlite3.Connection,
) -> None:
    """Install the Plugin schema only inside an explicit offline migration."""

    if connection.in_transaction:
        raise TargetInventoryPersistenceError(
            "HPC inventory migration cannot run inside an existing transaction"
        )
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + hpc_inventory_migration_sql() + "\nCOMMIT;")
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise TargetInventoryPersistenceError(
            "failed to install the exact HPC inventory migration"
        ) from exc


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class SQLiteTargetInventoryRepository:
    """Append-only Plugin repository; it never creates or migrates schema."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row

    def latest(self, target_id: str) -> TargetToolchainInventory | None:
        row = self.connection.execute(
            """
            SELECT inventory_json
            FROM openzyme_hpc_target_toolchain_inventories
            WHERE target_id = ?
            ORDER BY generation DESC
            LIMIT 1
            """,
            (target_id,),
        ).fetchone()
        return None if row is None else self._inventory(json.loads(row["inventory_json"]))

    def get(
        self,
        target_id: str,
        generation: int,
    ) -> TargetToolchainInventory | None:
        row = self.connection.execute(
            """
            SELECT inventory_json
            FROM openzyme_hpc_target_toolchain_inventories
            WHERE target_id = ? AND generation = ?
            """,
            (target_id, generation),
        ).fetchone()
        return None if row is None else self._inventory(json.loads(row["inventory_json"]))

    def publish(
        self,
        inventory: TargetToolchainInventory,
        generation: InventoryGeneration,
        receipts: tuple[SoftwareQualificationReceipt, ...],
        *,
        expected_previous_digest: str | None,
    ) -> None:
        if (
            generation.target_id != inventory.target_id
            or generation.generation != inventory.generation
            or generation.inventory_digest != inventory.inventory_digest
            or generation.previous_inventory_digest != expected_previous_digest
        ):
            raise TargetInventoryPersistenceError(
                "inventory generation does not bind the exact publication"
            )
        if tuple(sorted(item.receipt_digest for item in receipts)) != (
            inventory.qualification_receipt_digests
        ):
            raise TargetInventoryPersistenceError(
                "inventory receipt closure differs from published receipts"
            )
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.latest(inventory.target_id)
            observed_previous = None if previous is None else previous.inventory_digest
            expected_generation = 1 if previous is None else previous.generation + 1
            if (
                observed_previous != expected_previous_digest
                or inventory.generation != expected_generation
            ):
                raise TargetInventoryPersistenceError(
                    "inventory compare-and-swap predecessor drifted"
                )
            for receipt in receipts:
                self.connection.execute(
                    """
                    INSERT INTO openzyme_hpc_software_qualification_receipts (
                        receipt_id, target_id, capability_id, receipt_digest,
                        receipt_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        receipt.receipt_id,
                        receipt.target_id,
                        receipt.capability_id,
                        receipt.receipt_digest,
                        _json(receipt.to_dict()),
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO openzyme_hpc_target_toolchain_inventories (
                    target_id, generation, target_profile_digest,
                    previous_inventory_digest, inventory_digest, valid_until,
                    created_at, published_by_actor_id, published_at,
                    generation_digest, inventory_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inventory.target_id,
                    inventory.generation,
                    inventory.target_profile_digest,
                    generation.previous_inventory_digest,
                    inventory.inventory_digest,
                    inventory.valid_until,
                    inventory.created_at,
                    generation.published_by_actor_id,
                    generation.published_at,
                    generation.generation_digest,
                    _json(inventory.to_dict()),
                ),
            )
            self.connection.commit()
        except TargetInventoryPersistenceError:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
        except sqlite3.Error as exc:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise TargetInventoryPersistenceError(
                "inventory publication failed atomically"
            ) from exc

    @staticmethod
    def _inventory(payload: dict[str, object]) -> TargetToolchainInventory:
        expected = {
            "schema_version",
            "target_id",
            "generation",
            "target_profile_digest",
            "facts",
            "qualification_receipt_digests",
            "valid_until",
            "created_at",
            "inventory_digest",
        }
        if set(payload) != expected:
            raise TargetInventoryPersistenceError("stored inventory fields are closed")
        raw_facts = payload["facts"]
        if not isinstance(raw_facts, list):
            raise TargetInventoryPersistenceError("stored inventory facts are invalid")
        facts = tuple(
            TargetCapabilityFact(
                capability_id=str(item["capability_id"]),
                kind=ResourceCapabilityKind(str(item["kind"])),
                contract_version=str(item["contract_version"]),
                version=None if item["version"] is None else str(item["version"]),
                operations=tuple(str(value) for value in item["operations"]),
                environment_digest=str(item["environment_digest"]),
                qualification_digest=str(item["qualification_digest"]),
                implementation_digest=(
                    None
                    if item["implementation_digest"] is None
                    else str(item["implementation_digest"])
                ),
            )
            for item in raw_facts
            if isinstance(item, dict)
        )
        if len(facts) != len(raw_facts):
            raise TargetInventoryPersistenceError("stored inventory fact is invalid")
        return TargetToolchainInventory(
            target_id=str(payload["target_id"]),
            generation=int(payload["generation"]),
            target_profile_digest=str(payload["target_profile_digest"]),
            facts=facts,
            qualification_receipt_digests=tuple(
                str(value) for value in payload["qualification_receipt_digests"]
            ),
            valid_until=str(payload["valid_until"]),
            created_at=str(payload["created_at"]),
            inventory_digest=str(payload["inventory_digest"]),
        )


__all__ = [
    "SQLiteTargetInventoryRepository",
    "TargetInventoryPersistenceError",
    "hpc_inventory_migration_sql",
    "install_hpc_inventory_schema_for_offline_migration",
]
