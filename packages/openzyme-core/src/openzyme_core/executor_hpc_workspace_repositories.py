from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import json
import sqlite3

from openzyme_domain import ExecutorHpcCredentialClaim
from openzyme_domain import ExecutorHpcCredentialOperation
from openzyme_domain import ExecutorHpcCleanupDisposition
from openzyme_domain import ExecutorHpcTargetQualification
from openzyme_domain import ExecutorHpcWorkspace
from openzyme_domain import ExecutorHpcWorkspaceCleanupIntent
from openzyme_domain import ExecutorHpcWorkspaceCleanupReceipt
from openzyme_domain import ExecutorHpcWorkspaceProvisionIntent
from openzyme_domain import ExecutorHpcWorkspaceProvisionReceipt
from openzyme_domain import ExecutorHpcWorkspaceState

from .repositories import _commit


class ExecutorHpcWorkspaceRepositoryError(RuntimeError):
    error_code = "executor_hpc_workspace_repository_error"


@dataclass(slots=True)
class ExecutorHpcWorkspaceRepository:
    connection: sqlite3.Connection

    def add_target_qualification(
        self,
        record: ExecutorHpcTargetQualification,
    ) -> ExecutorHpcTargetQualification:
        existing = self.get_target_qualification(record.target_profile_id)
        if existing is not None:
            if existing == record:
                return existing
            raise ExecutorHpcWorkspaceRepositoryError(
                "target qualification identity already describes different content"
            )
        self.connection.execute(
            """
            INSERT INTO executor_hpc_target_qualifications (
                target_profile_id, target_profile_digest, root_policy_digest,
                os_principal_policy_id, credential_provider_id,
                authenticator_id, login_alias,
                workspace_root, sidecar_root_digest, toolchain_digest,
                native_positive_proof_digest, native_negative_proof_digest,
                activated, qualified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.target_profile_id,
                record.target_profile_digest,
                record.root_policy_digest,
                record.os_principal_policy_id,
                record.credential_provider_id,
                record.authenticator_id,
                record.login_alias,
                record.workspace_root,
                record.sidecar_root_digest,
                record.toolchain_digest,
                record.native_positive_proof_digest,
                record.native_negative_proof_digest,
                int(record.activated),
                record.qualified_at,
            ),
        )
        _commit(self.connection)
        return record

    def get_target_qualification(
        self,
        target_profile_id: str,
    ) -> ExecutorHpcTargetQualification | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_target_qualifications
            WHERE target_profile_id = ?
            """,
            (target_profile_id,),
        ).fetchone()
        if row is None:
            return None
        return ExecutorHpcTargetQualification(
            target_profile_id=row["target_profile_id"],
            target_profile_digest=row["target_profile_digest"],
            root_policy_digest=row["root_policy_digest"],
            os_principal_policy_id=row["os_principal_policy_id"],
            credential_provider_id=row["credential_provider_id"],
            authenticator_id=row["authenticator_id"],
            login_alias=row["login_alias"],
            workspace_root=row["workspace_root"],
            sidecar_root_digest=row["sidecar_root_digest"],
            toolchain_digest=row["toolchain_digest"],
            native_positive_proof_digest=row["native_positive_proof_digest"],
            native_negative_proof_digest=row["native_negative_proof_digest"],
            activated=bool(row["activated"]),
            qualified_at=row["qualified_at"],
        )

    def list_target_qualifications(self) -> list[ExecutorHpcTargetQualification]:
        rows = self.connection.execute(
            """
            SELECT target_profile_id FROM executor_hpc_target_qualifications
            WHERE activated = 1 ORDER BY target_profile_id
            """
        ).fetchall()
        return [
            record
            for row in rows
            if (
                record := self.get_target_qualification(row["target_profile_id"])
            )
            is not None
        ]

    def add_intent(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        *,
        local_workspace_id: str,
    ) -> ExecutorHpcWorkspaceProvisionIntent:
        existing = self.get_intent(intent.intent_id)
        if existing is not None:
            if existing == intent:
                return existing
            raise ExecutorHpcWorkspaceRepositoryError(
                "provision intent id identifies different content"
            )
        self.connection.execute(
            """
            INSERT INTO executor_hpc_workspace_provision_intents (
                intent_id, workspace_id, project_id, session_id,
                executor_agent_member_id, local_workspace_id,
                local_workspace_generation, remote_workspace_generation,
                repository_binding_id, repository_binding_version,
                repository_id, base_commit, target_profile_id,
                target_profile_digest, root_policy_digest,
                capability_lease_id, capability_lease_version,
                idempotency_key, absolute_deadline, intent_digest,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.intent_id,
                intent.workspace_id,
                intent.project_id,
                intent.session_id,
                intent.executor_agent_member_id,
                local_workspace_id,
                intent.local_workspace_generation,
                intent.remote_workspace_generation,
                intent.repository_binding_id,
                intent.repository_binding_version,
                intent.repository_id,
                intent.base_commit,
                intent.target_profile_id,
                intent.target_profile_digest,
                intent.root_policy_digest,
                intent.capability_lease_id,
                intent.capability_lease_version,
                intent.idempotency_key,
                intent.absolute_deadline,
                intent.intent_digest,
                intent.created_at,
            ),
        )
        _commit(self.connection)
        return intent

    def get_intent(
        self,
        intent_id: str,
    ) -> ExecutorHpcWorkspaceProvisionIntent | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_provision_intents
            WHERE intent_id = ?
            """,
            (intent_id,),
        ).fetchone()
        return None if row is None else self._intent_from_row(row)

    def get_intent_by_idempotency(
        self,
        *,
        session_id: str,
        executor_agent_member_id: str,
        idempotency_key: str,
    ) -> ExecutorHpcWorkspaceProvisionIntent | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_provision_intents
            WHERE session_id = ?
              AND executor_agent_member_id = ?
              AND idempotency_key = ?
            """,
            (session_id, executor_agent_member_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._intent_from_row(row)

    def add_workspace(self, workspace: ExecutorHpcWorkspace) -> ExecutorHpcWorkspace:
        existing = self.get(workspace.workspace_id)
        if existing is not None:
            if existing == workspace:
                return existing
            raise ExecutorHpcWorkspaceRepositoryError(
                "executor HPC workspace id identifies different content"
            )
        self.connection.execute(
            """
            INSERT INTO executor_hpc_workspace_records (
                workspace_id, project_id, repository_binding_id,
                repository_binding_version, repository_id, session_id,
                executor_agent_member_id, executor_agent_id,
                local_workspace_id, local_workspace_generation,
                capability_lease_id, capability_lease_version,
                target_profile_id, target_profile_digest,
                remote_workspace_generation, provision_intent_id,
                runner_handle, provision_receipt_id, login_alias,
                remote_workspace_path, remote_root_digest,
                os_principal_identity_digest, isolation_receipt_digest,
                state, state_version, invalid_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._workspace_values(workspace),
        )
        _commit(self.connection)
        return workspace

    def get(self, workspace_id: str) -> ExecutorHpcWorkspace | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_records
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        return None if row is None else self._workspace_from_row(row)

    def list_by_session(self, session_id: str) -> list[ExecutorHpcWorkspace]:
        rows = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_records
            WHERE session_id = ? ORDER BY created_at, workspace_id
            """,
            (session_id,),
        ).fetchall()
        return [self._workspace_from_row(row) for row in rows]

    def list_by_agent_member(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> list[ExecutorHpcWorkspace]:
        rows = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_records
            WHERE session_id = ? AND executor_agent_member_id = ?
            ORDER BY remote_workspace_generation, created_at
            """,
            (session_id, agent_member_id),
        ).fetchall()
        return [self._workspace_from_row(row) for row in rows]

    def add_receipt(
        self,
        receipt: ExecutorHpcWorkspaceProvisionReceipt,
    ) -> ExecutorHpcWorkspaceProvisionReceipt:
        existing = self.get_receipt(receipt.receipt_id)
        if existing is not None:
            if existing == receipt:
                return existing
            raise ExecutorHpcWorkspaceRepositoryError(
                "provision receipt id identifies different content"
            )
        self.connection.execute(
            """
            INSERT INTO executor_hpc_workspace_provision_receipts (
                receipt_id, intent_id, intent_digest, workspace_id,
                runner_handle, target_profile_digest, login_alias,
                remote_workspace_path, remote_root_digest,
                repository_remote_digest, clone_head_commit,
                owner_identity_digest, os_principal_identity_digest,
                isolation_receipt_digest, receipt_digest, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.intent_id,
                receipt.intent_digest,
                receipt.workspace_id,
                receipt.runner_handle,
                receipt.target_profile_digest,
                receipt.login_alias,
                receipt.remote_workspace_path,
                receipt.remote_root_digest,
                receipt.repository_remote_digest,
                receipt.clone_head_commit,
                receipt.owner_identity_digest,
                receipt.os_principal_identity_digest,
                receipt.isolation_receipt_digest,
                receipt.receipt_digest,
                receipt.created_at,
            ),
        )
        _commit(self.connection)
        return receipt

    def get_receipt(
        self,
        receipt_id: str,
    ) -> ExecutorHpcWorkspaceProvisionReceipt | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_provision_receipts
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()
        return None if row is None else self._receipt_from_row(row)

    def transition(
        self,
        workspace: ExecutorHpcWorkspace,
        *,
        expected_state_version: int,
    ) -> ExecutorHpcWorkspace:
        cursor = self.connection.execute(
            """
            UPDATE executor_hpc_workspace_records SET
                runner_handle = ?, provision_receipt_id = ?, login_alias = ?,
                remote_workspace_path = ?, remote_root_digest = ?,
                os_principal_identity_digest = ?, isolation_receipt_digest = ?,
                state = ?,
                state_version = ?, invalid_reason = ?, updated_at = ?
            WHERE workspace_id = ? AND state_version = ?
            """,
            (
                workspace.runner_handle,
                workspace.provision_receipt_id,
                workspace.login_alias,
                workspace.remote_workspace_path,
                workspace.remote_root_digest,
                workspace.os_principal_identity_digest,
                workspace.isolation_receipt_digest,
                workspace.state.value,
                workspace.state_version,
                workspace.invalid_reason,
                workspace.updated_at,
                workspace.workspace_id,
                expected_state_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ExecutorHpcWorkspaceRepositoryError(
                "executor HPC workspace state version changed"
            )
        _commit(self.connection)
        return workspace

    def add_credential_claim(
        self,
        claim: ExecutorHpcCredentialClaim,
        *,
        credential_fingerprint: str,
        authentication_receipt_digest: str,
    ) -> ExecutorHpcCredentialClaim:
        self.connection.execute(
            """
            INSERT INTO executor_hpc_credential_claims (
                claim_id, workspace_id, session_id,
                executor_agent_member_id, local_workspace_generation,
                remote_workspace_generation, target_profile_id,
                target_profile_digest, capability_lease_id,
                capability_lease_version, credential_provider_id,
                authenticator_id, login_alias, remote_workspace_path,
                remote_root_digest,
                os_principal_identity_digest,
                operations_json, credential_fingerprint,
                authentication_receipt_digest, issued_at,
                expires_at, revoked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim_id,
                claim.workspace_id,
                claim.session_id,
                claim.executor_agent_member_id,
                claim.local_workspace_generation,
                claim.remote_workspace_generation,
                claim.target_profile_id,
                claim.target_profile_digest,
                claim.capability_lease_id,
                claim.capability_lease_version,
                claim.credential_provider_id,
                claim.authenticator_id,
                claim.login_alias,
                claim.remote_workspace_path,
                claim.remote_root_digest,
                claim.os_principal_identity_digest,
                json.dumps(
                    [item.value for item in claim.operations],
                    separators=(",", ":"),
                ),
                credential_fingerprint,
                authentication_receipt_digest,
                claim.issued_at,
                claim.expires_at,
                claim.revoked_at,
            ),
        )
        _commit(self.connection)
        return claim

    def get_credential_claim(
        self,
        claim_id: str,
    ) -> tuple[ExecutorHpcCredentialClaim, str] | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_credential_claims
            WHERE claim_id = ?
            """,
            (claim_id,),
        ).fetchone()
        if row is None:
            return None
        operations = tuple(
            ExecutorHpcCredentialOperation(item)
            for item in json.loads(row["operations_json"])
        )
        claim = ExecutorHpcCredentialClaim(
            claim_id=row["claim_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            executor_agent_member_id=row["executor_agent_member_id"],
            local_workspace_generation=int(row["local_workspace_generation"]),
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            target_profile_id=row["target_profile_id"],
            target_profile_digest=row["target_profile_digest"],
            capability_lease_id=row["capability_lease_id"],
            capability_lease_version=int(row["capability_lease_version"]),
            credential_provider_id=row["credential_provider_id"],
            authenticator_id=row["authenticator_id"],
            login_alias=row["login_alias"],
            remote_workspace_path=row["remote_workspace_path"],
            remote_root_digest=row["remote_root_digest"],
            os_principal_identity_digest=row["os_principal_identity_digest"],
            operations=operations,
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )
        return claim, str(row["credential_fingerprint"])

    def list_active_credential_claims(
        self,
        workspace_id: str,
    ) -> list[tuple[ExecutorHpcCredentialClaim, str]]:
        rows = self.connection.execute(
            """
            SELECT claim_id FROM executor_hpc_credential_claims
            WHERE workspace_id = ? AND revoked_at IS NULL
            ORDER BY issued_at, claim_id
            """,
            (workspace_id,),
        ).fetchall()
        return [
            result
            for row in rows
            if (result := self.get_credential_claim(row["claim_id"])) is not None
        ]

    def revoke_credential_claim(
        self,
        claim_id: str,
        *,
        revoked_at: str,
    ) -> ExecutorHpcCredentialClaim:
        current = self.get_credential_claim(claim_id)
        if current is None:
            raise ExecutorHpcWorkspaceRepositoryError(
                "executor HPC credential claim does not exist"
            )
        claim, _ = current
        if claim.revoked_at is not None:
            if claim.revoked_at != revoked_at:
                raise ExecutorHpcWorkspaceRepositoryError(
                    "executor HPC credential claim already has another revoke time"
                )
            return claim
        cursor = self.connection.execute(
            """
            UPDATE executor_hpc_credential_claims
            SET revoked_at = ?
            WHERE claim_id = ? AND revoked_at IS NULL
            """,
            (revoked_at, claim_id),
        )
        if cursor.rowcount != 1:
            raise ExecutorHpcWorkspaceRepositoryError(
                "executor HPC credential revoke raced"
            )
        _commit(self.connection)
        return replace(claim, revoked_at=revoked_at)

    def add_cleanup_receipt(
        self,
        receipt: ExecutorHpcWorkspaceCleanupReceipt,
    ) -> ExecutorHpcWorkspaceCleanupReceipt:
        existing = self.get_cleanup_receipt(receipt.cleanup_receipt_id)
        if existing is not None:
            if existing == receipt:
                return existing
            raise ExecutorHpcWorkspaceRepositoryError(
                "cleanup receipt id identifies different content"
            )
        self.connection.execute(
            """
            INSERT INTO executor_hpc_workspace_cleanup_receipts (
                cleanup_receipt_id, cleanup_intent_id,
                cleanup_intent_digest, workspace_id, runner_handle,
                remote_root_digest, disposition, unsettled_effect_count,
                settlement_proof_digest, isolation_cleanup_receipt_digest,
                receipt_digest, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.cleanup_receipt_id,
                receipt.cleanup_intent_id,
                receipt.cleanup_intent_digest,
                receipt.workspace_id,
                receipt.runner_handle,
                receipt.remote_root_digest,
                receipt.disposition.value,
                receipt.unsettled_effect_count,
                receipt.settlement_proof_digest,
                receipt.isolation_cleanup_receipt_digest,
                receipt.receipt_digest,
                receipt.created_at,
            ),
        )
        _commit(self.connection)
        return receipt

    def add_cleanup_intent(
        self,
        intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspaceCleanupIntent:
        existing = self.get_cleanup_intent(intent.cleanup_intent_id)
        if existing is not None:
            if existing == intent:
                return existing
            raise ExecutorHpcWorkspaceRepositoryError(
                "cleanup intent id identifies different content"
            )
        existing_for_workspace = self.get_cleanup_intent_by_workspace(
            intent.workspace_id
        )
        if existing_for_workspace is not None:
            if existing_for_workspace == intent:
                return existing_for_workspace
            raise ExecutorHpcWorkspaceRepositoryError(
                "workspace already has another cleanup intent"
            )
        self.connection.execute(
            """
            INSERT INTO executor_hpc_workspace_cleanup_intents (
                cleanup_intent_id, workspace_id, workspace_state_version,
                runner_handle, remote_root_digest, settlement_proof_digest,
                idempotency_key, intent_digest, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.cleanup_intent_id,
                intent.workspace_id,
                intent.workspace_state_version,
                intent.runner_handle,
                intent.remote_root_digest,
                intent.settlement_proof_digest,
                intent.idempotency_key,
                intent.intent_digest,
                intent.created_at,
            ),
        )
        _commit(self.connection)
        return intent

    def get_cleanup_intent(
        self,
        cleanup_intent_id: str,
    ) -> ExecutorHpcWorkspaceCleanupIntent | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_cleanup_intents
            WHERE cleanup_intent_id = ?
            """,
            (cleanup_intent_id,),
        ).fetchone()
        return None if row is None else self._cleanup_intent_from_row(row)

    def get_cleanup_intent_by_workspace(
        self,
        workspace_id: str,
    ) -> ExecutorHpcWorkspaceCleanupIntent | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_cleanup_intents
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        return None if row is None else self._cleanup_intent_from_row(row)

    def get_cleanup_receipt(
        self,
        cleanup_receipt_id: str,
    ) -> ExecutorHpcWorkspaceCleanupReceipt | None:
        row = self.connection.execute(
            """
            SELECT * FROM executor_hpc_workspace_cleanup_receipts
            WHERE cleanup_receipt_id = ?
            """,
            (cleanup_receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return ExecutorHpcWorkspaceCleanupReceipt(
            cleanup_receipt_id=row["cleanup_receipt_id"],
            cleanup_intent_id=row["cleanup_intent_id"],
            cleanup_intent_digest=row["cleanup_intent_digest"],
            workspace_id=row["workspace_id"],
            runner_handle=row["runner_handle"],
            remote_root_digest=row["remote_root_digest"],
            disposition=ExecutorHpcCleanupDisposition(row["disposition"]),
            unsettled_effect_count=int(row["unsettled_effect_count"]),
            settlement_proof_digest=row["settlement_proof_digest"],
            isolation_cleanup_receipt_digest=row[
                "isolation_cleanup_receipt_digest"
            ],
            created_at=row["created_at"],
            receipt_digest=row["receipt_digest"],
        )

    def get_cleanup_receipt_by_workspace(
        self,
        workspace_id: str,
    ) -> ExecutorHpcWorkspaceCleanupReceipt | None:
        row = self.connection.execute(
            """
            SELECT cleanup_receipt_id
            FROM executor_hpc_workspace_cleanup_receipts
            WHERE workspace_id = ?
            ORDER BY created_at DESC, cleanup_receipt_id DESC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        return (
            None
            if row is None
            else self.get_cleanup_receipt(row["cleanup_receipt_id"])
        )

    @staticmethod
    def _workspace_values(
        workspace: ExecutorHpcWorkspace,
    ) -> tuple[object, ...]:
        return (
            workspace.workspace_id,
            workspace.project_id,
            workspace.repository_binding_id,
            workspace.repository_binding_version,
            workspace.repository_id,
            workspace.session_id,
            workspace.executor_agent_member_id,
            workspace.executor_agent_id,
            workspace.local_workspace_id,
            workspace.local_workspace_generation,
            workspace.capability_lease_id,
            workspace.capability_lease_version,
            workspace.target_profile_id,
            workspace.target_profile_digest,
            workspace.remote_workspace_generation,
            workspace.provision_intent_id,
            workspace.runner_handle,
            workspace.provision_receipt_id,
            workspace.login_alias,
            workspace.remote_workspace_path,
            workspace.remote_root_digest,
            workspace.os_principal_identity_digest,
            workspace.isolation_receipt_digest,
            workspace.state.value,
            workspace.state_version,
            workspace.invalid_reason,
            workspace.created_at,
            workspace.updated_at,
        )

    @staticmethod
    def _workspace_from_row(row: sqlite3.Row) -> ExecutorHpcWorkspace:
        return ExecutorHpcWorkspace(
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_id=row["repository_id"],
            session_id=row["session_id"],
            executor_agent_member_id=row["executor_agent_member_id"],
            executor_agent_id=row["executor_agent_id"],
            local_workspace_id=row["local_workspace_id"],
            local_workspace_generation=int(row["local_workspace_generation"]),
            capability_lease_id=row["capability_lease_id"],
            capability_lease_version=int(row["capability_lease_version"]),
            target_profile_id=row["target_profile_id"],
            target_profile_digest=row["target_profile_digest"],
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            provision_intent_id=row["provision_intent_id"],
            runner_handle=row["runner_handle"],
            provision_receipt_id=row["provision_receipt_id"],
            login_alias=row["login_alias"],
            remote_workspace_path=row["remote_workspace_path"],
            remote_root_digest=row["remote_root_digest"],
            os_principal_identity_digest=row["os_principal_identity_digest"],
            isolation_receipt_digest=row["isolation_receipt_digest"],
            state=ExecutorHpcWorkspaceState(row["state"]),
            state_version=int(row["state_version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            invalid_reason=row["invalid_reason"],
        )

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> ExecutorHpcWorkspaceProvisionIntent:
        return ExecutorHpcWorkspaceProvisionIntent(
            intent_id=row["intent_id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            executor_agent_member_id=row["executor_agent_member_id"],
            local_workspace_generation=int(row["local_workspace_generation"]),
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_id=row["repository_id"],
            base_commit=row["base_commit"],
            target_profile_id=row["target_profile_id"],
            target_profile_digest=row["target_profile_digest"],
            root_policy_digest=row["root_policy_digest"],
            capability_lease_id=row["capability_lease_id"],
            capability_lease_version=int(row["capability_lease_version"]),
            idempotency_key=row["idempotency_key"],
            absolute_deadline=row["absolute_deadline"],
            created_at=row["created_at"],
            intent_digest=row["intent_digest"],
        )

    @staticmethod
    def _receipt_from_row(
        row: sqlite3.Row,
    ) -> ExecutorHpcWorkspaceProvisionReceipt:
        return ExecutorHpcWorkspaceProvisionReceipt(
            receipt_id=row["receipt_id"],
            intent_id=row["intent_id"],
            intent_digest=row["intent_digest"],
            workspace_id=row["workspace_id"],
            runner_handle=row["runner_handle"],
            target_profile_digest=row["target_profile_digest"],
            login_alias=row["login_alias"],
            remote_workspace_path=row["remote_workspace_path"],
            remote_root_digest=row["remote_root_digest"],
            repository_remote_digest=row["repository_remote_digest"],
            clone_head_commit=row["clone_head_commit"],
            owner_identity_digest=row["owner_identity_digest"],
            os_principal_identity_digest=row["os_principal_identity_digest"],
            isolation_receipt_digest=row["isolation_receipt_digest"],
            created_at=row["created_at"],
            receipt_digest=row["receipt_digest"],
        )

    @staticmethod
    def _cleanup_intent_from_row(
        row: sqlite3.Row,
    ) -> ExecutorHpcWorkspaceCleanupIntent:
        return ExecutorHpcWorkspaceCleanupIntent(
            cleanup_intent_id=row["cleanup_intent_id"],
            workspace_id=row["workspace_id"],
            workspace_state_version=int(row["workspace_state_version"]),
            runner_handle=row["runner_handle"],
            remote_root_digest=row["remote_root_digest"],
            settlement_proof_digest=row["settlement_proof_digest"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            intent_digest=row["intent_digest"],
        )


__all__ = [
    "ExecutorHpcWorkspaceRepository",
    "ExecutorHpcWorkspaceRepositoryError",
]
