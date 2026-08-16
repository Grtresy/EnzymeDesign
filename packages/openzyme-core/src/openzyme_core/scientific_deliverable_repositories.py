from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from openzyme_domain import ScientificDeliverableBundle
from openzyme_domain import ScientificDeliverableRef
from openzyme_domain import ScientificDeliverableValidationReceipt
from openzyme_domain import ScientificFileEffectAdoption
from openzyme_domain import ScientificFileStorage

from .repositories import _commit


class ScientificDeliverableRepositoryError(RuntimeError):
    error_code = "scientific_deliverable_repository_error"


@dataclass(slots=True)
class ScientificDeliverableRepository:
    connection: sqlite3.Connection

    def add_adoption(
        self,
        record: ScientificFileEffectAdoption,
    ) -> ScientificFileEffectAdoption:
        existing = self.get_adoption(record.adoption_id)
        if existing is not None:
            if existing == record:
                return existing
            raise ScientificDeliverableRepositoryError(
                "scientific file adoption identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO scientific_file_effect_adoption_records (
                adoption_id, selection_id, selection_revision, attempt_id,
                workflow_role, operation_id, execution_id, result_id,
                result_digest, effect_certainty, actor_ref,
                execution_fencing_token, idempotency_key, request_digest,
                created_at, adoption_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.adoption_id,
                record.selection_id,
                record.selection_revision,
                record.attempt_id,
                record.workflow_role,
                record.operation_id,
                record.execution_id,
                record.result_id,
                record.result_digest,
                record.effect_certainty,
                record.actor_ref,
                record.execution_fencing_token,
                record.idempotency_key,
                record.request_digest,
                record.created_at,
                record.adoption_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_adoption(self, adoption_id: str) -> ScientificFileEffectAdoption | None:
        row = self.connection.execute(
            "SELECT * FROM scientific_file_effect_adoption_records WHERE adoption_id = ?",
            (adoption_id,),
        ).fetchone()
        return None if row is None else self._adoption(row)

    def list_adoptions(self, selection_id: str) -> tuple[ScientificFileEffectAdoption, ...]:
        rows = self.connection.execute(
            """
            SELECT * FROM scientific_file_effect_adoption_records
            WHERE selection_id = ? ORDER BY workflow_role, adoption_id
            """,
            (selection_id,),
        ).fetchall()
        return tuple(self._adoption(row) for row in rows)

    def add_ref(self, record: ScientificDeliverableRef) -> ScientificDeliverableRef:
        existing = self.get_ref(record.ref_id)
        if existing is not None:
            if existing == record:
                return existing
            raise ScientificDeliverableRepositoryError(
                "scientific deliverable ref identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO scientific_deliverable_ref_records (
                ref_id, project_id, session_id, repository_binding_id,
                repository_binding_version, repository_policy_digest,
                publication_id, publication_digest, publication_ref,
                published_commit, published_tree, repository_path, storage,
                git_blob_oid, lfs_oid, lfs_declared_size, actual_size,
                content_digest, scientific_role, format_contract_id,
                format_contract_digest, deliverable_contract_id,
                deliverable_contract_digest, producer_operation_id,
                producer_execution_id, producer_result_id,
                producer_result_digest, attempt_id, attempt_state_version,
                selection_id, selection_revision, producer_adoption_id,
                selection_adoption_digest, publisher_workspace_id,
                publisher_workspace_generation, publisher_agent_member_id,
                created_at, supersedes_ref_id, ref_digest
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                record.ref_id,
                record.project_id,
                record.session_id,
                record.repository_binding_id,
                record.repository_binding_version,
                record.repository_policy_digest,
                record.publication_id,
                record.publication_digest,
                record.publication_ref,
                record.published_commit,
                record.published_tree,
                record.path,
                record.storage.value,
                record.git_blob_oid,
                record.lfs_oid,
                record.lfs_declared_size,
                record.actual_size,
                record.content_digest,
                record.scientific_role,
                record.format_contract_id,
                record.format_contract_digest,
                record.deliverable_contract_id,
                record.deliverable_contract_digest,
                record.producer_operation_id,
                record.producer_execution_id,
                record.producer_result_id,
                record.producer_result_digest,
                record.attempt_id,
                record.attempt_state_version,
                record.selection_id,
                record.selection_revision,
                record.producer_adoption_id,
                record.selection_adoption_digest,
                record.publisher_workspace_id,
                record.publisher_workspace_generation,
                record.publisher_agent_member_id,
                record.created_at,
                record.supersedes_ref_id,
                record.ref_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_ref(self, ref_id: str) -> ScientificDeliverableRef | None:
        row = self.connection.execute(
            "SELECT * FROM scientific_deliverable_ref_records WHERE ref_id = ?",
            (ref_id,),
        ).fetchone()
        return None if row is None else self._ref(row)

    def list_refs_by_session(
        self,
        session_id: str,
    ) -> tuple[ScientificDeliverableRef, ...]:
        rows = self.connection.execute(
            """
            SELECT * FROM scientific_deliverable_ref_records
            WHERE session_id = ? ORDER BY created_at, ref_id
            """,
            (session_id,),
        ).fetchall()
        return tuple(self._ref(row) for row in rows)

    def list_refs_by_bundle(self, bundle_id: str) -> tuple[ScientificDeliverableRef, ...]:
        rows = self.connection.execute(
            """
            SELECT ref.* FROM scientific_deliverable_bundle_entry_records AS entry
            JOIN scientific_deliverable_ref_records AS ref ON ref.ref_id = entry.ref_id
            WHERE entry.bundle_id = ? ORDER BY entry.ordinal
            """,
            (bundle_id,),
        ).fetchall()
        return tuple(self._ref(row) for row in rows)

    def add_bundle(
        self,
        record: ScientificDeliverableBundle,
        *,
        refs: tuple[ScientificDeliverableRef, ...],
    ) -> ScientificDeliverableBundle:
        existing = self.get_bundle(record.bundle_id)
        if existing is not None:
            canonical_refs = tuple(sorted(refs, key=lambda item: item.scientific_role))
            if (
                existing == record
                and self.list_refs_by_bundle(record.bundle_id) == canonical_refs
            ):
                return existing
            raise ScientificDeliverableRepositoryError(
                "scientific deliverable bundle identity conflicts"
            )
        if tuple(sorted(ref.ref_id for ref in refs)) != record.ref_ids:
            raise ScientificDeliverableRepositoryError(
                "scientific bundle refs differ from its closed identity"
            )
        self.connection.execute(
            """
            INSERT INTO scientific_deliverable_bundle_records (
                bundle_id, project_id, session_id, attempt_id, selection_id,
                publication_id, publication_digest, contract_id,
                contract_digest, ref_ids_json, role_manifest_digest,
                validation_preimage_digest, created_at, bundle_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.bundle_id,
                record.project_id,
                record.session_id,
                record.attempt_id,
                record.selection_id,
                record.publication_id,
                record.publication_digest,
                record.contract_id,
                record.contract_digest,
                json.dumps(list(record.ref_ids), separators=(",", ":")),
                record.role_manifest_digest,
                record.validation_preimage_digest,
                record.created_at,
                record.bundle_digest,
            ),
        )
        for ordinal, ref in enumerate(sorted(refs, key=lambda item: item.scientific_role), 1):
            self.connection.execute(
                """
                INSERT INTO scientific_deliverable_bundle_entry_records (
                    bundle_id, ref_id, scientific_role, repository_path, ordinal
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.bundle_id,
                    ref.ref_id,
                    ref.scientific_role,
                    ref.path,
                    ordinal,
                ),
            )
        _commit(self.connection)
        return record

    def get_bundle(self, bundle_id: str) -> ScientificDeliverableBundle | None:
        row = self.connection.execute(
            "SELECT * FROM scientific_deliverable_bundle_records WHERE bundle_id = ?",
            (bundle_id,),
        ).fetchone()
        if row is None:
            return None
        return ScientificDeliverableBundle(
            bundle_id=row["bundle_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            attempt_id=row["attempt_id"],
            selection_id=row["selection_id"],
            publication_id=row["publication_id"],
            publication_digest=row["publication_digest"],
            contract_id=row["contract_id"],
            contract_digest=row["contract_digest"],
            ref_ids=tuple(json.loads(row["ref_ids_json"])),
            role_manifest_digest=row["role_manifest_digest"],
            validation_preimage_digest=row["validation_preimage_digest"],
            created_at=row["created_at"],
            bundle_digest=row["bundle_digest"],
        )

    def add_receipt(
        self,
        record: ScientificDeliverableValidationReceipt,
    ) -> ScientificDeliverableValidationReceipt:
        existing = self.get_receipt(record.receipt_id)
        if existing is not None:
            if existing == record:
                return existing
            raise ScientificDeliverableRepositoryError(
                "scientific validation receipt identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO scientific_deliverable_validation_receipt_records (
                receipt_id, bundle_id, bundle_digest, publication_id,
                publication_digest, attempt_id, attempt_state_version,
                selection_id, selection_revision, actor_ref,
                execution_fencing_token, validation_preimage_digest,
                verified_ref_digests_json, created_at, receipt_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.receipt_id,
                record.bundle_id,
                record.bundle_digest,
                record.publication_id,
                record.publication_digest,
                record.attempt_id,
                record.attempt_state_version,
                record.selection_id,
                record.selection_revision,
                record.actor_ref,
                record.execution_fencing_token,
                record.validation_preimage_digest,
                json.dumps(list(record.verified_ref_digests), separators=(",", ":")),
                record.created_at,
                record.receipt_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_receipt(
        self,
        receipt_id: str,
    ) -> ScientificDeliverableValidationReceipt | None:
        row = self.connection.execute(
            """
            SELECT * FROM scientific_deliverable_validation_receipt_records
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return ScientificDeliverableValidationReceipt(
            receipt_id=row["receipt_id"],
            bundle_id=row["bundle_id"],
            bundle_digest=row["bundle_digest"],
            publication_id=row["publication_id"],
            publication_digest=row["publication_digest"],
            attempt_id=row["attempt_id"],
            attempt_state_version=int(row["attempt_state_version"]),
            selection_id=row["selection_id"],
            selection_revision=int(row["selection_revision"]),
            actor_ref=row["actor_ref"],
            execution_fencing_token=int(row["execution_fencing_token"]),
            validation_preimage_digest=row["validation_preimage_digest"],
            verified_ref_digests=tuple(json.loads(row["verified_ref_digests_json"])),
            created_at=row["created_at"],
            receipt_digest=row["receipt_digest"],
        )

    @staticmethod
    def _adoption(row: sqlite3.Row) -> ScientificFileEffectAdoption:
        return ScientificFileEffectAdoption(
            adoption_id=row["adoption_id"],
            selection_id=row["selection_id"],
            selection_revision=int(row["selection_revision"]),
            attempt_id=row["attempt_id"],
            workflow_role=row["workflow_role"],
            operation_id=row["operation_id"],
            execution_id=row["execution_id"],
            result_id=row["result_id"],
            result_digest=row["result_digest"],
            effect_certainty=row["effect_certainty"],
            actor_ref=row["actor_ref"],
            execution_fencing_token=int(row["execution_fencing_token"]),
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            created_at=row["created_at"],
            adoption_digest=row["adoption_digest"],
        )

    @staticmethod
    def _ref(row: sqlite3.Row) -> ScientificDeliverableRef:
        return ScientificDeliverableRef(
            ref_id=row["ref_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_policy_digest=row["repository_policy_digest"],
            publication_id=row["publication_id"],
            publication_digest=row["publication_digest"],
            publication_ref=row["publication_ref"],
            published_commit=row["published_commit"],
            published_tree=row["published_tree"],
            path=row["repository_path"],
            storage=ScientificFileStorage(row["storage"]),
            git_blob_oid=row["git_blob_oid"],
            lfs_oid=row["lfs_oid"],
            lfs_declared_size=row["lfs_declared_size"],
            actual_size=int(row["actual_size"]),
            content_digest=row["content_digest"],
            scientific_role=row["scientific_role"],
            format_contract_id=row["format_contract_id"],
            format_contract_digest=row["format_contract_digest"],
            deliverable_contract_id=row["deliverable_contract_id"],
            deliverable_contract_digest=row["deliverable_contract_digest"],
            producer_operation_id=row["producer_operation_id"],
            producer_execution_id=row["producer_execution_id"],
            producer_result_id=row["producer_result_id"],
            producer_result_digest=row["producer_result_digest"],
            attempt_id=row["attempt_id"],
            attempt_state_version=int(row["attempt_state_version"]),
            selection_id=row["selection_id"],
            selection_revision=int(row["selection_revision"]),
            producer_adoption_id=row["producer_adoption_id"],
            selection_adoption_digest=row["selection_adoption_digest"],
            publisher_workspace_id=row["publisher_workspace_id"],
            publisher_workspace_generation=int(row["publisher_workspace_generation"]),
            publisher_agent_member_id=row["publisher_agent_member_id"],
            created_at=row["created_at"],
            supersedes_ref_id=row["supersedes_ref_id"],
            ref_digest=row["ref_digest"],
        )


__all__ = ["ScientificDeliverableRepository", "ScientificDeliverableRepositoryError"]
