from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from openzyme_domain import ComputeSourceManifest
from openzyme_domain import ComputeSourceManifestEntry
from openzyme_domain import ExternalJobHandle
from openzyme_domain import ExternalJobObservation
from openzyme_domain import SchedulerCredentialOccurrence
from openzyme_domain import SchedulerCredentialOccurrenceState
from openzyme_domain import WorkspaceExternalBackend
from openzyme_domain import WorkspaceJobCancellationIntent
from openzyme_domain import WorkspaceJobCancellationReceipt
from openzyme_domain import WorkspaceJobDispatchIntent
from openzyme_domain import WorkspaceJobExecutionMode
from openzyme_domain import WorkspaceJobObservationState
from openzyme_domain import WorkspaceJobResult
from openzyme_domain import WorkspaceJobResultRevisionLink
from openzyme_domain import WorkspaceJobTargetQualification
from openzyme_domain import WorkspaceRevisionCleanObservation
from openzyme_domain import WorkspaceRevisionExecutionRequest
from openzyme_domain import WorkspaceRevisionScientificBasis
from openzyme_domain import WorkspaceRevisionSourceClass

from .repositories import _commit
from .repositories import _json_dumps


class WorkspaceRevisionExecutionRepositoryError(RuntimeError):
    error_code = "workspace_revision_execution_repository_error"


@dataclass(slots=True)
class WorkspaceRevisionExecutionRepository:
    connection: sqlite3.Connection

    def add_target_qualification(
        self,
        record: WorkspaceJobTargetQualification,
    ) -> WorkspaceJobTargetQualification:
        existing = self.get_target_qualification(record.target_profile_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace job target qualification identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_job_target_qualifications (
                target_profile_id, target_profile_digest, runner_policy_digest,
                protected_submit_wrapper_digest, dispatch_ledger_digest,
                scheduler_credential_provider_id,
                scheduler_credential_audience, scheduler_marker_policy_digest,
                scheduler_accounting_proof_digest,
                ambient_submit_denial_proof_digest,
                direct_process_ledger_proof_digest, slurm_enabled,
                direct_enabled, qualified_at, qualification_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.target_profile_id,
                record.target_profile_digest,
                record.runner_policy_digest,
                record.protected_submit_wrapper_digest,
                record.dispatch_ledger_digest,
                record.scheduler_credential_provider_id,
                record.scheduler_credential_audience,
                record.scheduler_marker_policy_digest,
                record.scheduler_accounting_proof_digest,
                record.ambient_submit_denial_proof_digest,
                record.direct_process_ledger_proof_digest,
                int(record.slurm_enabled),
                int(record.direct_enabled),
                record.qualified_at,
                record.qualification_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_target_qualification(
        self,
        target_profile_id: str,
    ) -> WorkspaceJobTargetQualification | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_target_qualifications WHERE target_profile_id = ?",
            (target_profile_id,),
        ).fetchone()
        if row is None:
            return None
        return WorkspaceJobTargetQualification(
            target_profile_id=row["target_profile_id"],
            target_profile_digest=row["target_profile_digest"],
            runner_policy_digest=row["runner_policy_digest"],
            protected_submit_wrapper_digest=row["protected_submit_wrapper_digest"],
            dispatch_ledger_digest=row["dispatch_ledger_digest"],
            scheduler_credential_provider_id=row[
                "scheduler_credential_provider_id"
            ],
            scheduler_credential_audience=row["scheduler_credential_audience"],
            scheduler_marker_policy_digest=row[
                "scheduler_marker_policy_digest"
            ],
            scheduler_accounting_proof_digest=row[
                "scheduler_accounting_proof_digest"
            ],
            ambient_submit_denial_proof_digest=row[
                "ambient_submit_denial_proof_digest"
            ],
            direct_process_ledger_proof_digest=row[
                "direct_process_ledger_proof_digest"
            ],
            slurm_enabled=bool(row["slurm_enabled"]),
            direct_enabled=bool(row["direct_enabled"]),
            qualified_at=row["qualified_at"],
            qualification_digest=row["qualification_digest"],
        )

    def add_request(
        self,
        record: WorkspaceRevisionExecutionRequest,
    ) -> WorkspaceRevisionExecutionRequest:
        existing = self.get_request(record.request_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace revision request identity conflicts"
            )
        basis = record.scientific_basis
        self.connection.execute(
            """
            INSERT INTO workspace_revision_execution_requests (
                request_id, execution_id, operation_id, operation_digest,
                session_id, executor_agent_member_id, capability_lease_id,
                capability_lease_version, executor_hpc_workspace_id,
                remote_workspace_generation, repository_binding_id,
                repository_binding_version, source_class, source_ref,
                source_revision_id, source_commit, source_tree,
                lfs_closure_manifest_digest,
                clean_observation_digest, cwd, command_json, command_digest,
                environment_policy_digest, resources_json, resource_digest,
                requested_mode, target_profile_id, target_profile_digest,
                runner_policy_digest, runtime_identity_digest,
                scientific_attempt_id, scientific_attempt_state_version,
                scientific_admission_request_id,
                scientific_admission_request_digest,
                scientific_source_envelope_id,
                scientific_workflow_contract_digest, scientific_scope_digest,
                scientific_effect_class_digest, scientific_hpc_target_digest,
                operation_approval_digest, absolute_deadline, created_at,
                request_digest
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                record.request_id,
                record.execution_id,
                record.operation_id,
                record.operation_digest,
                record.session_id,
                record.executor_agent_member_id,
                record.capability_lease_id,
                record.capability_lease_version,
                record.executor_hpc_workspace_id,
                record.remote_workspace_generation,
                record.repository_binding_id,
                record.repository_binding_version,
                record.source_class.value,
                record.source_ref,
                record.source_revision_id,
                record.source_commit,
                record.source_tree,
                record.lfs_closure_manifest_digest,
                record.clean_observation_digest,
                record.cwd,
                _json_dumps(list(record.command)),
                record.command_digest,
                record.environment_policy_digest,
                _json_dumps(record.resources),
                record.resource_digest,
                record.requested_mode.value,
                record.target_profile_id,
                record.target_profile_digest,
                record.runner_policy_digest,
                record.runtime_identity_digest,
                None if basis is None else basis.attempt_id,
                None if basis is None else basis.attempt_state_version,
                None if basis is None else basis.admission_request_id,
                None if basis is None else basis.admission_request_digest,
                None if basis is None else basis.source_envelope_id,
                None if basis is None else basis.workflow_contract_digest,
                None if basis is None else basis.scope_digest,
                None if basis is None else basis.effect_class_digest,
                None if basis is None else basis.hpc_target_digest,
                record.operation_approval_digest,
                record.absolute_deadline,
                record.created_at,
                record.request_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_request(
        self,
        request_id: str,
    ) -> WorkspaceRevisionExecutionRequest | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_revision_execution_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return None if row is None else self._request_from_row(row)

    def get_request_by_execution(
        self,
        execution_id: str,
    ) -> WorkspaceRevisionExecutionRequest | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_revision_execution_requests WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return None if row is None else self._request_from_row(row)

    def add_clean_observation(
        self,
        record: WorkspaceRevisionCleanObservation,
    ) -> WorkspaceRevisionCleanObservation:
        existing = self.get_clean_observation(record.observation_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace clean observation identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_revision_clean_observations (
                observation_id, request_id, workspace_id,
                remote_workspace_generation, repository_binding_id,
                repository_binding_version, source_commit, source_tree,
                lfs_closure_manifest_digest, head_matches, index_clean,
                tracked_tree_clean, untracked_policy_clean, attributes_digest,
                cwd_present, observed_at, observation_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.observation_id,
                record.request_id,
                record.workspace_id,
                record.remote_workspace_generation,
                record.repository_binding_id,
                record.repository_binding_version,
                record.source_commit,
                record.source_tree,
                record.lfs_closure_manifest_digest,
                int(record.head_matches),
                int(record.index_clean),
                int(record.tracked_tree_clean),
                int(record.untracked_policy_clean),
                record.attributes_digest,
                int(record.cwd_present),
                record.observed_at,
                record.observation_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_clean_observation(
        self,
        observation_id: str,
    ) -> WorkspaceRevisionCleanObservation | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_revision_clean_observations WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
        if row is None:
            return None
        return WorkspaceRevisionCleanObservation(
            observation_id=row["observation_id"],
            request_id=row["request_id"],
            workspace_id=row["workspace_id"],
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            source_commit=row["source_commit"],
            source_tree=row["source_tree"],
            lfs_closure_manifest_digest=row["lfs_closure_manifest_digest"],
            head_matches=bool(row["head_matches"]),
            index_clean=bool(row["index_clean"]),
            tracked_tree_clean=bool(row["tracked_tree_clean"]),
            untracked_policy_clean=bool(row["untracked_policy_clean"]),
            attributes_digest=row["attributes_digest"],
            cwd_present=bool(row["cwd_present"]),
            observed_at=row["observed_at"],
            observation_digest=row["observation_digest"],
        )

    def add_manifest(self, record: ComputeSourceManifest) -> ComputeSourceManifest:
        existing = self.get_manifest(record.manifest_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "compute source manifest identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO compute_source_manifests (
                manifest_id, request_id, workspace_id, source_commit,
                source_tree, lfs_closure_manifest_digest, binding_digest,
                repository_policy_digest, toolchain_digest,
                owner_identity_digest, entries_json, created_at, manifest_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.manifest_id,
                record.request_id,
                record.workspace_id,
                record.source_commit,
                record.source_tree,
                record.lfs_closure_manifest_digest,
                record.binding_digest,
                record.repository_policy_digest,
                record.toolchain_digest,
                record.owner_identity_digest,
                _json_dumps([entry.to_dict() for entry in record.entries]),
                record.created_at,
                record.manifest_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_manifest(self, manifest_id: str) -> ComputeSourceManifest | None:
        row = self.connection.execute(
            "SELECT * FROM compute_source_manifests WHERE manifest_id = ?",
            (manifest_id,),
        ).fetchone()
        if row is None:
            return None
        entries = tuple(
            ComputeSourceManifestEntry(
                path=item["path"],
                object_id=item["object_id"],
                mode=item["mode"],
                size_bytes=int(item["size_bytes"]),
                content_digest=item["content_digest"],
                lfs_oid=item.get("lfs_oid"),
            )
            for item in json.loads(row["entries_json"])
        )
        return ComputeSourceManifest(
            manifest_id=row["manifest_id"],
            request_id=row["request_id"],
            workspace_id=row["workspace_id"],
            source_commit=row["source_commit"],
            source_tree=row["source_tree"],
            lfs_closure_manifest_digest=row["lfs_closure_manifest_digest"],
            binding_digest=row["binding_digest"],
            repository_policy_digest=row["repository_policy_digest"],
            toolchain_digest=row["toolchain_digest"],
            owner_identity_digest=row["owner_identity_digest"],
            entries=entries,
            created_at=row["created_at"],
            manifest_digest=row["manifest_digest"],
        )

    def get_manifest_by_request(
        self,
        request_id: str,
    ) -> ComputeSourceManifest | None:
        row = self.connection.execute(
            "SELECT manifest_id FROM compute_source_manifests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return None if row is None else self.get_manifest(row["manifest_id"])

    def add_dispatch_intent(
        self,
        record: WorkspaceJobDispatchIntent,
    ) -> WorkspaceJobDispatchIntent:
        existing = self.get_dispatch_intent(record.dispatch_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace job dispatch intent identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_job_dispatch_intents (
                dispatch_id, execution_id, operation_id,
                execution_state_version, execution_fencing_token, request_id,
                request_digest, runner_run_id, workspace_id,
                remote_workspace_generation, source_manifest_digest,
                selected_mode, command_digest, resource_digest,
                target_profile_digest, scheduler_marker, payload_digest,
                absolute_deadline, created_at, intent_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.dispatch_id,
                record.execution_id,
                record.operation_id,
                record.execution_state_version,
                record.execution_fencing_token,
                record.request_id,
                record.request_digest,
                record.runner_run_id,
                record.workspace_id,
                record.remote_workspace_generation,
                record.source_manifest_digest,
                record.selected_mode.value,
                record.command_digest,
                record.resource_digest,
                record.target_profile_digest,
                record.scheduler_marker,
                record.payload_digest,
                record.absolute_deadline,
                record.created_at,
                record.intent_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_dispatch_intent(
        self,
        dispatch_id: str,
    ) -> WorkspaceJobDispatchIntent | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_dispatch_intents WHERE dispatch_id = ?",
            (dispatch_id,),
        ).fetchone()
        return None if row is None else self._dispatch_from_row(row)

    def get_dispatch_intent_by_execution(
        self,
        execution_id: str,
    ) -> WorkspaceJobDispatchIntent | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_dispatch_intents WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return None if row is None else self._dispatch_from_row(row)

    def add_scheduler_occurrence(
        self,
        record: SchedulerCredentialOccurrence,
    ) -> SchedulerCredentialOccurrence:
        existing = self.get_scheduler_occurrence(record.occurrence_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "scheduler credential occurrence identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO scheduler_credential_occurrences (
                occurrence_id, dispatch_id, execution_id,
                execution_fencing_token, target_profile_digest,
                reservation_nonce_digest, scheduler_marker, payload_digest,
                protected_wrapper_audience, credential_fingerprint,
                authentication_receipt_digest, consumption_receipt_digest,
                state, reserved_at, expires_at, issued_at, consumed_at,
                rejection_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._occurrence_values(record),
        )
        _commit(self.connection)
        return record

    def transition_scheduler_occurrence(
        self,
        record: SchedulerCredentialOccurrence,
        *,
        expected_state: SchedulerCredentialOccurrenceState,
    ) -> SchedulerCredentialOccurrence:
        cursor = self.connection.execute(
            """
            UPDATE scheduler_credential_occurrences SET
                credential_fingerprint = ?, authentication_receipt_digest = ?,
                consumption_receipt_digest = ?, state = ?, issued_at = ?,
                consumed_at = ?, rejection_code = ?
            WHERE occurrence_id = ? AND state = ?
            """,
            (
                record.credential_fingerprint,
                record.authentication_receipt_digest,
                record.consumption_receipt_digest,
                record.state.value,
                record.issued_at,
                record.consumed_at,
                record.rejection_code,
                record.occurrence_id,
                expected_state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise WorkspaceRevisionExecutionRepositoryError(
                "scheduler credential occurrence state conflict"
            )
        _commit(self.connection)
        return record

    def get_scheduler_occurrence(
        self,
        occurrence_id: str,
    ) -> SchedulerCredentialOccurrence | None:
        row = self.connection.execute(
            "SELECT * FROM scheduler_credential_occurrences WHERE occurrence_id = ?",
            (occurrence_id,),
        ).fetchone()
        if row is None:
            return None
        return SchedulerCredentialOccurrence(
            occurrence_id=row["occurrence_id"],
            dispatch_id=row["dispatch_id"],
            execution_id=row["execution_id"],
            execution_fencing_token=int(row["execution_fencing_token"]),
            target_profile_digest=row["target_profile_digest"],
            reservation_nonce_digest=row["reservation_nonce_digest"],
            scheduler_marker=row["scheduler_marker"],
            payload_digest=row["payload_digest"],
            protected_wrapper_audience=row["protected_wrapper_audience"],
            credential_fingerprint=row["credential_fingerprint"],
            authentication_receipt_digest=row[
                "authentication_receipt_digest"
            ],
            consumption_receipt_digest=row["consumption_receipt_digest"],
            state=SchedulerCredentialOccurrenceState(row["state"]),
            reserved_at=row["reserved_at"],
            expires_at=row["expires_at"],
            issued_at=row["issued_at"],
            consumed_at=row["consumed_at"],
            rejection_code=row["rejection_code"],
        )

    def add_handle(self, record: ExternalJobHandle) -> ExternalJobHandle:
        existing = self.get_handle(record.handle_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "external job handle identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_external_job_handles (
                handle_id, execution_id, operation_id, dispatch_id,
                runner_run_id, job_root_token, target_profile_digest, workspace_id,
                remote_workspace_generation, source_commit,
                source_manifest_digest, backend, raw_handle_ciphertext,
                acceptance_receipt_digest, accepted_at, handle_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.handle_id,
                record.execution_id,
                record.operation_id,
                record.dispatch_id,
                record.runner_run_id,
                record.job_root_token,
                record.target_profile_digest,
                record.workspace_id,
                record.remote_workspace_generation,
                record.source_commit,
                record.source_manifest_digest,
                record.backend.value,
                record.raw_handle_ciphertext,
                record.acceptance_receipt_digest,
                record.accepted_at,
                record.handle_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_handle(self, handle_id: str) -> ExternalJobHandle | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_external_job_handles WHERE handle_id = ?",
            (handle_id,),
        ).fetchone()
        if row is None:
            return None
        return ExternalJobHandle(
            handle_id=row["handle_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            dispatch_id=row["dispatch_id"],
            runner_run_id=row["runner_run_id"],
            job_root_token=row["job_root_token"],
            target_profile_digest=row["target_profile_digest"],
            workspace_id=row["workspace_id"],
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            source_commit=row["source_commit"],
            source_manifest_digest=row["source_manifest_digest"],
            backend=WorkspaceExternalBackend(row["backend"]),
            raw_handle_ciphertext=row["raw_handle_ciphertext"],
            acceptance_receipt_digest=row["acceptance_receipt_digest"],
            accepted_at=row["accepted_at"],
            handle_digest=row["handle_digest"],
        )

    def get_handle_by_execution(self, execution_id: str) -> ExternalJobHandle | None:
        row = self.connection.execute(
            "SELECT handle_id FROM workspace_external_job_handles WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return None if row is None else self.get_handle(row["handle_id"])

    def add_observation(
        self,
        record: ExternalJobObservation,
    ) -> ExternalJobObservation:
        existing = self.get_observation(record.observation_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "external job observation identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_external_job_observations (
                observation_id, handle_id, execution_id, dispatch_id,
                observation_index, state, exit_code, terminal_receipt_digest,
                bounded_stdout, bounded_stderr, observed_at, observation_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.observation_id,
                record.handle_id,
                record.execution_id,
                record.dispatch_id,
                record.observation_index,
                record.state.value,
                record.exit_code,
                record.terminal_receipt_digest,
                record.bounded_stdout,
                record.bounded_stderr,
                record.observed_at,
                record.observation_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_observation(self, observation_id: str) -> ExternalJobObservation | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_external_job_observations WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
        return None if row is None else self._observation_from_row(row)

    def latest_observation(self, handle_id: str) -> ExternalJobObservation | None:
        row = self.connection.execute(
            """
            SELECT * FROM workspace_external_job_observations
            WHERE handle_id = ? ORDER BY observation_index DESC LIMIT 1
            """,
            (handle_id,),
        ).fetchone()
        return None if row is None else self._observation_from_row(row)

    def add_cancellation_intent(
        self,
        record: WorkspaceJobCancellationIntent,
    ) -> WorkspaceJobCancellationIntent:
        existing = self.get_cancellation_intent(record.cancellation_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace job cancellation intent identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_job_cancellation_intents (
                cancellation_id, execution_id, handle_id,
                execution_state_version, execution_fencing_token,
                idempotency_key, reason_digest, created_at, intent_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.cancellation_id,
                record.execution_id,
                record.handle_id,
                record.execution_state_version,
                record.execution_fencing_token,
                record.idempotency_key,
                record.reason_digest,
                record.created_at,
                record.intent_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_cancellation_intent(
        self,
        cancellation_id: str,
    ) -> WorkspaceJobCancellationIntent | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_cancellation_intents WHERE cancellation_id = ?",
            (cancellation_id,),
        ).fetchone()
        if row is None:
            return None
        return WorkspaceJobCancellationIntent(
            cancellation_id=row["cancellation_id"],
            execution_id=row["execution_id"],
            handle_id=row["handle_id"],
            execution_state_version=int(row["execution_state_version"]),
            execution_fencing_token=int(row["execution_fencing_token"]),
            idempotency_key=row["idempotency_key"],
            reason_digest=row["reason_digest"],
            created_at=row["created_at"],
            intent_digest=row["intent_digest"],
        )

    def add_cancellation_receipt(
        self,
        record: WorkspaceJobCancellationReceipt,
    ) -> WorkspaceJobCancellationReceipt:
        existing = self.get_cancellation_receipt(record.cancellation_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace job cancellation receipt identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_job_cancellation_receipts (
                receipt_id, cancellation_id, handle_id,
                cancellation_requested, terminal_settlement_proven,
                backend_receipt_digest, created_at, receipt_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.receipt_id,
                record.cancellation_id,
                record.handle_id,
                int(record.cancellation_requested),
                int(record.terminal_settlement_proven),
                record.backend_receipt_digest,
                record.created_at,
                record.receipt_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_cancellation_receipt(
        self,
        cancellation_id: str,
    ) -> WorkspaceJobCancellationReceipt | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_cancellation_receipts WHERE cancellation_id = ?",
            (cancellation_id,),
        ).fetchone()
        if row is None:
            return None
        return WorkspaceJobCancellationReceipt(
            receipt_id=row["receipt_id"],
            cancellation_id=row["cancellation_id"],
            handle_id=row["handle_id"],
            cancellation_requested=bool(row["cancellation_requested"]),
            terminal_settlement_proven=bool(row["terminal_settlement_proven"]),
            backend_receipt_digest=row["backend_receipt_digest"],
            created_at=row["created_at"],
            receipt_digest=row["receipt_digest"],
        )

    def add_result(self, record: WorkspaceJobResult) -> WorkspaceJobResult:
        existing = self.get_result(record.result_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace job result identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_job_results (
                result_id, execution_id, operation_id, handle_id,
                runner_run_id, terminal_observation_id,
                terminal_observation_digest, terminal_state, exit_code,
                source_commit, source_manifest_digest, workspace_id,
                remote_workspace_generation, job_root_token, cwd,
                command_digest, resource_digest, target_profile_digest,
                created_at, result_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.result_id,
                record.execution_id,
                record.operation_id,
                record.handle_id,
                record.runner_run_id,
                record.terminal_observation_id,
                record.terminal_observation_digest,
                record.terminal_state.value,
                record.exit_code,
                record.source_commit,
                record.source_manifest_digest,
                record.workspace_id,
                record.remote_workspace_generation,
                record.job_root_token,
                record.cwd,
                record.command_digest,
                record.resource_digest,
                record.target_profile_digest,
                record.created_at,
                record.result_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_result(self, result_id: str) -> WorkspaceJobResult | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_results WHERE result_id = ?",
            (result_id,),
        ).fetchone()
        return None if row is None else self._result_from_row(row)

    def get_result_by_execution(self, execution_id: str) -> WorkspaceJobResult | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_results WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return None if row is None else self._result_from_row(row)

    def add_result_revision_link(
        self,
        record: WorkspaceJobResultRevisionLink,
    ) -> WorkspaceJobResultRevisionLink:
        existing = self.get_result_revision_link(record.result_id)
        if existing is not None:
            if existing == record:
                return existing
            raise WorkspaceRevisionExecutionRepositoryError(
                "workspace result revision link identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_job_result_revision_links (
                link_id, result_id, checkpoint_id, workspace_id,
                result_commit, result_tree,
                lfs_closure_manifest_digest, linked_by_agent_member_id,
                linked_at, link_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.link_id,
                record.result_id,
                record.checkpoint_id,
                record.workspace_id,
                record.result_commit,
                record.result_tree,
                record.lfs_closure_manifest_digest,
                record.linked_by_agent_member_id,
                record.linked_at,
                record.link_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_result_revision_link(
        self,
        result_id: str,
    ) -> WorkspaceJobResultRevisionLink | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_job_result_revision_links WHERE result_id = ?",
            (result_id,),
        ).fetchone()
        if row is None:
            return None
        return WorkspaceJobResultRevisionLink(
            link_id=row["link_id"],
            result_id=row["result_id"],
            checkpoint_id=row["checkpoint_id"],
            workspace_id=row["workspace_id"],
            result_commit=row["result_commit"],
            result_tree=row["result_tree"],
            lfs_closure_manifest_digest=row["lfs_closure_manifest_digest"],
            linked_by_agent_member_id=row["linked_by_agent_member_id"],
            linked_at=row["linked_at"],
            link_digest=row["link_digest"],
        )

    @staticmethod
    def _request_from_row(row: sqlite3.Row) -> WorkspaceRevisionExecutionRequest:
        basis = None
        if row["scientific_attempt_id"] is not None:
            basis = WorkspaceRevisionScientificBasis(
                attempt_id=row["scientific_attempt_id"],
                attempt_state_version=int(row["scientific_attempt_state_version"]),
                admission_request_id=row["scientific_admission_request_id"],
                admission_request_digest=row[
                    "scientific_admission_request_digest"
                ],
                source_envelope_id=row["scientific_source_envelope_id"],
                workflow_contract_digest=row[
                    "scientific_workflow_contract_digest"
                ],
                scope_digest=row["scientific_scope_digest"],
                effect_class_digest=row["scientific_effect_class_digest"],
                hpc_target_digest=row["scientific_hpc_target_digest"],
            )
        return WorkspaceRevisionExecutionRequest(
            request_id=row["request_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            operation_digest=row["operation_digest"],
            session_id=row["session_id"],
            executor_agent_member_id=row["executor_agent_member_id"],
            capability_lease_id=row["capability_lease_id"],
            capability_lease_version=int(row["capability_lease_version"]),
            executor_hpc_workspace_id=row["executor_hpc_workspace_id"],
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            source_class=WorkspaceRevisionSourceClass(row["source_class"]),
            source_revision_id=row["source_revision_id"],
            source_ref=row["source_ref"],
            source_commit=row["source_commit"],
            source_tree=row["source_tree"],
            lfs_closure_manifest_digest=row["lfs_closure_manifest_digest"],
            clean_observation_digest=row["clean_observation_digest"],
            cwd=row["cwd"],
            command=tuple(json.loads(row["command_json"])),
            command_digest=row["command_digest"],
            environment_policy_digest=row["environment_policy_digest"],
            resources=dict(json.loads(row["resources_json"])),
            resource_digest=row["resource_digest"],
            requested_mode=WorkspaceJobExecutionMode(row["requested_mode"]),
            target_profile_id=row["target_profile_id"],
            target_profile_digest=row["target_profile_digest"],
            runner_policy_digest=row["runner_policy_digest"],
            runtime_identity_digest=row["runtime_identity_digest"],
            scientific_basis=basis,
            operation_approval_digest=row["operation_approval_digest"],
            absolute_deadline=row["absolute_deadline"],
            created_at=row["created_at"],
            request_digest=row["request_digest"],
        )

    @staticmethod
    def _dispatch_from_row(row: sqlite3.Row) -> WorkspaceJobDispatchIntent:
        return WorkspaceJobDispatchIntent(
            dispatch_id=row["dispatch_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            execution_state_version=int(row["execution_state_version"]),
            execution_fencing_token=int(row["execution_fencing_token"]),
            request_id=row["request_id"],
            request_digest=row["request_digest"],
            runner_run_id=row["runner_run_id"],
            workspace_id=row["workspace_id"],
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            source_manifest_digest=row["source_manifest_digest"],
            selected_mode=WorkspaceJobExecutionMode(row["selected_mode"]),
            command_digest=row["command_digest"],
            resource_digest=row["resource_digest"],
            target_profile_digest=row["target_profile_digest"],
            scheduler_marker=row["scheduler_marker"],
            payload_digest=row["payload_digest"],
            absolute_deadline=row["absolute_deadline"],
            created_at=row["created_at"],
            intent_digest=row["intent_digest"],
        )

    @staticmethod
    def _occurrence_values(
        record: SchedulerCredentialOccurrence,
    ) -> tuple[object, ...]:
        return (
            record.occurrence_id,
            record.dispatch_id,
            record.execution_id,
            record.execution_fencing_token,
            record.target_profile_digest,
            record.reservation_nonce_digest,
            record.scheduler_marker,
            record.payload_digest,
            record.protected_wrapper_audience,
            record.credential_fingerprint,
            record.authentication_receipt_digest,
            record.consumption_receipt_digest,
            record.state.value,
            record.reserved_at,
            record.expires_at,
            record.issued_at,
            record.consumed_at,
            record.rejection_code,
        )

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> ExternalJobObservation:
        return ExternalJobObservation(
            observation_id=row["observation_id"],
            handle_id=row["handle_id"],
            execution_id=row["execution_id"],
            dispatch_id=row["dispatch_id"],
            observation_index=int(row["observation_index"]),
            state=WorkspaceJobObservationState(row["state"]),
            exit_code=row["exit_code"],
            terminal_receipt_digest=row["terminal_receipt_digest"],
            bounded_stdout=row["bounded_stdout"],
            bounded_stderr=row["bounded_stderr"],
            observed_at=row["observed_at"],
            observation_digest=row["observation_digest"],
        )

    @staticmethod
    def _result_from_row(row: sqlite3.Row) -> WorkspaceJobResult:
        return WorkspaceJobResult(
            result_id=row["result_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            handle_id=row["handle_id"],
            runner_run_id=row["runner_run_id"],
            terminal_observation_id=row["terminal_observation_id"],
            terminal_observation_digest=row["terminal_observation_digest"],
            terminal_state=WorkspaceJobObservationState(row["terminal_state"]),
            exit_code=row["exit_code"],
            source_commit=row["source_commit"],
            source_manifest_digest=row["source_manifest_digest"],
            workspace_id=row["workspace_id"],
            remote_workspace_generation=int(row["remote_workspace_generation"]),
            job_root_token=row["job_root_token"],
            cwd=row["cwd"],
            command_digest=row["command_digest"],
            resource_digest=row["resource_digest"],
            target_profile_digest=row["target_profile_digest"],
            created_at=row["created_at"],
            result_digest=row["result_digest"],
        )


__all__ = [
    "WorkspaceRevisionExecutionRepository",
    "WorkspaceRevisionExecutionRepositoryError",
]
