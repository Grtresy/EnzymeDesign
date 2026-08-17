from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import PublishedRevision
from openzyme_domain import RetryEligibility
from openzyme_domain import WorkspacePublicationIntent
from openzyme_domain import WorkspacePublicationIntentState
from openzyme_domain import WorkspacePublicationManifest
from openzyme_domain import WorkspacePublicationRemoteReceipt
from openzyme_domain import canonical_publication_digest

from .repositories import _commit
from .reliability_repositories import OptimisticStateConflictError


class WorkspacePublicationRepositoryError(RuntimeError):
    error_code = "workspace_publication_repository_error"


class WorkspacePublicationIdentityConflictError(WorkspacePublicationRepositoryError):
    error_code = "workspace_publication_identity_conflict"


@dataclass(slots=True)
class WorkspacePublicationIntentRepository:
    connection: sqlite3.Connection

    def add_or_get_exact(
        self,
        intent: WorkspacePublicationIntent,
    ) -> WorkspacePublicationIntent:
        existing = self.get_by_idempotency_key(
            session_id=intent.session_id,
            idempotency_key=intent.idempotency_key,
        )
        if existing is not None:
            if existing == intent:
                return existing
            raise WorkspacePublicationIdentityConflictError(
                "publication idempotency key identifies different frozen facts"
            )
        try:
            self.connection.execute(
                """
                INSERT INTO workspace_publication_intents (
                    intent_id, publication_id, idempotency_key, project_id,
                    session_id, agent_member_id, agent_id, workspace_id,
                    workspace_generation, capability_lease_id,
                    repository_binding_id, repository_binding_version,
                    repository_id, expected_head_commit, expected_tree,
                    git_parent_commits_json, declared_base_commit,
                    parent_publication_id, supersedes_publication_id,
                    publication_ref, manifest_json, manifest_digest,
                    repository_policy_version, repository_policy_digest,
                    checkpoint_id, state, created_at, canonical_digest,
                    schema_version
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._values(intent),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get(intent.intent_id) or self.get_by_publication_id(
                intent.publication_id
            )
            if existing == intent:
                _commit(self.connection)
                return existing
            raise WorkspacePublicationIdentityConflictError(
                "publication intent conflicts with canonical storage"
            ) from exc
        _commit(self.connection)
        return intent

    def get(self, intent_id: str) -> WorkspacePublicationIntent | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_publication_intents WHERE intent_id = ?",
            (intent_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_publication_id(
        self,
        publication_id: str,
    ) -> WorkspacePublicationIntent | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_publication_intents WHERE publication_id = ?",
            (publication_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_idempotency_key(
        self,
        *,
        session_id: str,
        idempotency_key: str,
    ) -> WorkspacePublicationIntent | None:
        row = self.connection.execute(
            """
            SELECT * FROM workspace_publication_intents
            WHERE session_id = ? AND idempotency_key = ?
            """,
            (session_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _values(intent: WorkspacePublicationIntent) -> tuple[object, ...]:
        return (
            intent.intent_id,
            intent.publication_id,
            intent.idempotency_key,
            intent.project_id,
            intent.session_id,
            intent.agent_member_id,
            intent.agent_id,
            intent.workspace_id,
            intent.workspace_generation,
            intent.capability_lease_id,
            intent.repository_binding_id,
            intent.repository_binding_version,
            intent.repository_id,
            intent.expected_head_commit,
            intent.expected_tree,
            json.dumps(list(intent.git_parent_commits), separators=(",", ":")),
            intent.declared_base_commit,
            intent.parent_publication_id,
            intent.supersedes_publication_id,
            intent.publication_ref,
            json.dumps(intent.manifest.to_dict(), sort_keys=True, separators=(",", ":")),
            intent.manifest.manifest_digest,
            intent.repository_policy_version,
            intent.repository_policy_digest,
            intent.checkpoint_id,
            intent.state.value,
            intent.created_at,
            intent.canonical_digest,
            intent.schema_version,
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> WorkspacePublicationIntent:
        return WorkspacePublicationIntent(
            intent_id=row["intent_id"],
            publication_id=row["publication_id"],
            idempotency_key=row["idempotency_key"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_id=row["workspace_id"],
            workspace_generation=int(row["workspace_generation"]),
            capability_lease_id=row["capability_lease_id"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_id=row["repository_id"],
            expected_head_commit=row["expected_head_commit"],
            expected_tree=row["expected_tree"],
            git_parent_commits=tuple(json.loads(row["git_parent_commits_json"])),
            declared_base_commit=row["declared_base_commit"],
            parent_publication_id=row["parent_publication_id"],
            supersedes_publication_id=row["supersedes_publication_id"],
            publication_ref=row["publication_ref"],
            manifest=_manifest_from_json(row["manifest_json"]),
            repository_policy_version=row["repository_policy_version"],
            repository_policy_digest=row["repository_policy_digest"],
            checkpoint_id=row["checkpoint_id"],
            state=WorkspacePublicationIntentState(row["state"]),
            created_at=row["created_at"],
            canonical_digest=row["canonical_digest"],
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class WorkspacePublicationExecutionRepository:
    connection: sqlite3.Connection

    def add(
        self,
        *,
        intent: WorkspacePublicationIntent,
        execution: ControlledOperationExecution,
    ) -> ControlledOperationExecution:
        existing = self.get_by_intent(intent.intent_id)
        if existing is not None:
            if existing == execution:
                return existing
            raise WorkspacePublicationIdentityConflictError(
                "publication intent already owns another controlled execution"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_publication_execution_records (
                execution_id, operation_id, intent_id, publication_id,
                session_id, task_id, lane_id, schema_version, owner_mode,
                operation_digest, approval_digest, route_policy_id,
                selected_backend, adapter_policy_id, input_identity_digest,
                expected_output_contract_digest, runtime_identity_digest,
                lifecycle_state, terminal_outcome, effect_certainty,
                retry_eligibility, dispatch_generation, state_version,
                lease_owner, lease_token, lease_expires_at, fencing_token,
                backend_handle_ref, result_handle_ref, result_digest,
                error_code, safe_error_summary,
                created_at, updated_at, terminal_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                execution.execution_id,
                execution.operation_id,
                intent.intent_id,
                intent.publication_id,
                execution.session_id,
                execution.task_id,
                execution.lane_id,
                execution.SCHEMA_VERSION,
                execution.owner_mode.value,
                execution.operation_digest,
                execution.approval_digest,
                execution.route_policy_id,
                execution.selected_backend,
                execution.adapter_policy_id,
                execution.input_identity_digest,
                execution.expected_output_contract_digest,
                execution.runtime_identity_digest,
                execution.lifecycle_state.value,
                _enum_value(execution.terminal_outcome),
                execution.effect_certainty.value,
                execution.retry_eligibility.value,
                execution.dispatch_generation,
                execution.state_version,
                execution.lease_owner,
                execution.lease_token,
                execution.lease_expires_at,
                execution.fencing_token,
                execution.backend_handle_ref,
                execution.result_handle_ref,
                execution.result_digest,
                execution.error_code,
                execution.safe_error_summary,
                execution.created_at,
                execution.updated_at,
                execution.terminal_at,
            ),
        )
        _commit(self.connection)
        return execution

    def get(self, execution_id: str) -> ControlledOperationExecution | None:
        row = self.connection.execute(
            """
            SELECT * FROM workspace_publication_execution_records
            WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_intent(
        self,
        intent_id: str,
    ) -> ControlledOperationExecution | None:
        row = self.connection.execute(
            """
            SELECT * FROM workspace_publication_execution_records
            WHERE intent_id = ?
            """,
            (intent_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def replace_if_version(
        self,
        execution: ControlledOperationExecution,
        *,
        expected_state_version: int,
        expected_lease_token: str | None = None,
        expected_fencing_token: int | None = None,
    ) -> ControlledOperationExecution:
        current = self.get(execution.execution_id)
        if current is None or current.state_version != expected_state_version:
            raise OptimisticStateConflictError(
                "publication execution state version is stale"
            )
        if _execution_identity(current) != _execution_identity(execution):
            raise WorkspacePublicationIdentityConflictError(
                "publication controlled execution identity cannot change"
            )
        where = "execution_id = ? AND state_version = ?"
        values: list[object] = [execution.execution_id, expected_state_version]
        if expected_lease_token is not None or expected_fencing_token is not None:
            if expected_lease_token is None or expected_fencing_token is None:
                raise ValueError("lease token and fencing token are required together")
            where += " AND lease_token = ? AND fencing_token = ?"
            values.extend((expected_lease_token, expected_fencing_token))
        cursor = self.connection.execute(
            f"""
            UPDATE workspace_publication_execution_records
            SET lifecycle_state = ?, terminal_outcome = ?, effect_certainty = ?,
                retry_eligibility = ?, dispatch_generation = ?, state_version = ?,
                lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                fencing_token = ?, backend_handle_ref = ?, result_handle_ref = ?,
                result_digest = ?, error_code = ?,
                safe_error_summary = ?, updated_at = ?, terminal_at = ?
            WHERE {where}
            """,
            (
                execution.lifecycle_state.value,
                _enum_value(execution.terminal_outcome),
                execution.effect_certainty.value,
                execution.retry_eligibility.value,
                execution.dispatch_generation,
                execution.state_version,
                execution.lease_owner,
                execution.lease_token,
                execution.lease_expires_at,
                execution.fencing_token,
                execution.backend_handle_ref,
                execution.result_handle_ref,
                execution.result_digest,
                execution.error_code,
                execution.safe_error_summary,
                execution.updated_at,
                execution.terminal_at,
                *values,
            ),
        )
        if cursor.rowcount != 1:
            raise OptimisticStateConflictError(
                "publication execution lease or fence is stale"
            )
        _commit(self.connection)
        return execution

    @staticmethod
    def _row(row: sqlite3.Row) -> ControlledOperationExecution:
        return ControlledOperationExecution(
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            approval_id=None,
            owner_mode=ControlledOperationOwnerMode(row["owner_mode"]),
            operation_digest=row["operation_digest"],
            approval_digest=row["approval_digest"],
            route_policy_id=row["route_policy_id"],
            selected_backend=row["selected_backend"],
            adapter_policy_id=row["adapter_policy_id"],
            input_identity_digest=row["input_identity_digest"],
            expected_output_contract_digest=row["expected_output_contract_digest"],
            runtime_identity_digest=row["runtime_identity_digest"],
            lifecycle_state=ControlledOperationExecutionLifecycle(
                row["lifecycle_state"]
            ),
            terminal_outcome=(
                None
                if row["terminal_outcome"] is None
                else ControlledOperationExecutionTerminalOutcome(
                    row["terminal_outcome"]
                )
            ),
            effect_certainty=ExternalEffectCertainty(row["effect_certainty"]),
            retry_eligibility=RetryEligibility(row["retry_eligibility"]),
            dispatch_generation=int(row["dispatch_generation"]),
            state_version=int(row["state_version"]),
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            fencing_token=int(row["fencing_token"]),
            backend_handle_ref=row["backend_handle_ref"],
            result_handle_ref=row["result_handle_ref"],
            result_digest=row["result_digest"],
            error_code=row["error_code"],
            safe_error_summary=row["safe_error_summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_at=row["terminal_at"],
        )


@dataclass(slots=True)
class WorkspacePublicationExecutionEventRepository:
    connection: sqlite3.Connection

    def append(
        self,
        event: ControlledOperationExecutionEvent,
    ) -> ControlledOperationExecutionEvent:
        existing = self.get(event.event_id)
        if existing is not None:
            if existing == event:
                return existing
            raise WorkspacePublicationIdentityConflictError(
                "publication execution event identity conflict"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_publication_execution_events (
                event_id, execution_id, operation_id, session_id,
                state_version, dispatch_generation, phase,
                previous_lifecycle_state, lifecycle_state, terminal_outcome,
                effect_certainty, retry_eligibility, fencing_token,
                safe_receipt_digest, safe_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.execution_id,
                event.operation_id,
                event.session_id,
                event.state_version,
                event.dispatch_generation,
                event.phase.value,
                _enum_value(event.previous_lifecycle_state),
                event.lifecycle_state.value,
                _enum_value(event.terminal_outcome),
                event.effect_certainty.value,
                event.retry_eligibility.value,
                event.fencing_token,
                event.safe_receipt_digest,
                event.safe_summary,
                event.created_at,
            ),
        )
        _commit(self.connection)
        return event

    def get(self, event_id: str) -> ControlledOperationExecutionEvent | None:
        row = self.connection.execute(
            """
            SELECT * FROM workspace_publication_execution_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> ControlledOperationExecutionEvent:
        return ControlledOperationExecutionEvent(
            event_id=row["event_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            state_version=int(row["state_version"]),
            dispatch_generation=int(row["dispatch_generation"]),
            phase=ControlledOperationExecutionPhase(row["phase"]),
            previous_lifecycle_state=(
                None
                if row["previous_lifecycle_state"] is None
                else ControlledOperationExecutionLifecycle(
                    row["previous_lifecycle_state"]
                )
            ),
            lifecycle_state=ControlledOperationExecutionLifecycle(
                row["lifecycle_state"]
            ),
            terminal_outcome=(
                None
                if row["terminal_outcome"] is None
                else ControlledOperationExecutionTerminalOutcome(
                    row["terminal_outcome"]
                )
            ),
            effect_certainty=ExternalEffectCertainty(row["effect_certainty"]),
            retry_eligibility=RetryEligibility(row["retry_eligibility"]),
            fencing_token=int(row["fencing_token"]),
            safe_receipt_digest=row["safe_receipt_digest"],
            safe_summary=row["safe_summary"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class WorkspacePublicationRemoteReceiptRepository:
    connection: sqlite3.Connection

    def add(
        self,
        receipt: WorkspacePublicationRemoteReceipt,
    ) -> WorkspacePublicationRemoteReceipt:
        existing = self.get_by_intent(receipt.intent_id)
        if existing is not None:
            if existing == receipt:
                return existing
            raise WorkspacePublicationIdentityConflictError(
                "publication intent already owns another remote receipt"
            )
        self.connection.execute(
            """
            INSERT INTO workspace_publication_remote_receipts (
                receipt_id, intent_id, publication_id, execution_id,
                execution_dispatch_generation, execution_fencing_token,
                internal_git_service_id, repository_binding_id,
                repository_binding_version, repository_id, publication_ref,
                expected_previous_commit, new_commit, new_tree,
                server_observed_commit, observed_at, receipt_digest,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.intent_id,
                receipt.publication_id,
                receipt.execution_id,
                receipt.execution_dispatch_generation,
                receipt.execution_fencing_token,
                receipt.internal_git_service_id,
                receipt.repository_binding_id,
                receipt.repository_binding_version,
                receipt.repository_id,
                receipt.publication_ref,
                receipt.expected_previous_commit,
                receipt.new_commit,
                receipt.new_tree,
                receipt.server_observed_commit,
                receipt.observed_at,
                receipt.receipt_digest,
                receipt.schema_version,
            ),
        )
        _commit(self.connection)
        return receipt

    def get(self, receipt_id: str) -> WorkspacePublicationRemoteReceipt | None:
        row = self.connection.execute(
            """
            SELECT * FROM workspace_publication_remote_receipts
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_intent(
        self,
        intent_id: str,
    ) -> WorkspacePublicationRemoteReceipt | None:
        row = self.connection.execute(
            """
            SELECT * FROM workspace_publication_remote_receipts
            WHERE intent_id = ?
            """,
            (intent_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> WorkspacePublicationRemoteReceipt:
        return WorkspacePublicationRemoteReceipt(
            receipt_id=row["receipt_id"],
            intent_id=row["intent_id"],
            publication_id=row["publication_id"],
            execution_id=row["execution_id"],
            execution_dispatch_generation=int(row["execution_dispatch_generation"]),
            execution_fencing_token=int(row["execution_fencing_token"]),
            internal_git_service_id=row["internal_git_service_id"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_id=row["repository_id"],
            publication_ref=row["publication_ref"],
            expected_previous_commit=None,
            new_commit=row["new_commit"],
            new_tree=row["new_tree"],
            server_observed_commit=row["server_observed_commit"],
            observed_at=row["observed_at"],
            receipt_digest=row["receipt_digest"],
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class PublishedRevisionRepository:
    connection: sqlite3.Connection

    def add(self, revision: PublishedRevision) -> PublishedRevision:
        existing = self.get(revision.publication_id)
        if existing is not None:
            if existing == revision:
                return existing
            raise WorkspacePublicationIdentityConflictError(
                "publication id identifies another immutable revision"
            )
        self.connection.execute(
            """
            INSERT INTO published_revisions (
                publication_id, intent_id, project_id, session_id,
                repository_binding_id, repository_binding_version,
                repository_id, commit_id, tree_id, git_parent_commits_json,
                declared_base_commit, parent_publication_id,
                publisher_agent_member_id, publisher_agent_id,
                publisher_workspace_id, publisher_workspace_generation,
                publication_ref, manifest_json, manifest_digest,
                repository_policy_version, repository_policy_digest,
                controlled_execution_id, remote_receipt_id,
                supersedes_publication_id, created_at, revision_digest,
                schema_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                revision.publication_id,
                revision.intent_id,
                revision.project_id,
                revision.session_id,
                revision.repository_binding_id,
                revision.repository_binding_version,
                revision.repository_id,
                revision.commit,
                revision.tree,
                json.dumps(list(revision.git_parent_commits), separators=(",", ":")),
                revision.declared_base_commit,
                revision.parent_publication_id,
                revision.publisher_agent_member_id,
                revision.publisher_agent_id,
                revision.publisher_workspace_id,
                revision.publisher_workspace_generation,
                revision.publication_ref,
                json.dumps(revision.manifest.to_dict(), sort_keys=True, separators=(",", ":")),
                revision.manifest.manifest_digest,
                revision.repository_policy_version,
                revision.repository_policy_digest,
                revision.controlled_execution_id,
                revision.remote_receipt_id,
                revision.supersedes_publication_id,
                revision.created_at,
                revision.revision_digest,
                revision.schema_version,
            ),
        )
        if revision.supersedes_publication_id is not None:
            self.connection.execute(
                """
                INSERT INTO workspace_publication_supersedes_links (
                    successor_publication_id, predecessor_publication_id, created_at
                ) VALUES (?, ?, ?)
                """,
                (
                    revision.publication_id,
                    revision.supersedes_publication_id,
                    revision.created_at,
                ),
            )
        outbox_digest = canonical_publication_digest(
            {
                "event_type": "workspace.publication.materialized",
                "publication_id": revision.publication_id,
                "revision_digest": revision.revision_digest,
            }
        )
        self.connection.execute(
            """
            INSERT INTO workspace_publication_outbox_records (
                outbox_id, publication_id, session_id, event_type,
                event_digest, status, created_at, delivered_at
            ) VALUES (?, ?, ?, 'workspace.publication.materialized', ?, 'pending', ?, NULL)
            """,
            (
                f"publication_outbox_{revision.publication_id}",
                revision.publication_id,
                revision.session_id,
                outbox_digest,
                revision.created_at,
            ),
        )
        _commit(self.connection)
        return revision

    def get(self, publication_id: str) -> PublishedRevision | None:
        row = self.connection.execute(
            "SELECT * FROM published_revisions WHERE publication_id = ?",
            (publication_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_session(self, session_id: str) -> list[PublishedRevision]:
        rows = self.connection.execute(
            """
            SELECT * FROM published_revisions
            WHERE session_id = ? ORDER BY created_at, publication_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def pending_event(self, publication_id: str) -> dict[str, str] | None:
        row = self.connection.execute(
            """
            SELECT outbox_id, publication_id, session_id, event_type,
                   event_digest, created_at
            FROM workspace_publication_outbox_records
            WHERE publication_id = ? AND status = 'pending'
            """,
            (publication_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def mark_event_delivered(
        self,
        *,
        outbox_id: str,
        delivered_at: str,
    ) -> bool:
        cursor = self.connection.execute(
            """
            UPDATE workspace_publication_outbox_records
            SET status = 'delivered', delivered_at = ?
            WHERE outbox_id = ? AND status = 'pending'
            """,
            (delivered_at, outbox_id),
        )
        _commit(self.connection)
        return cursor.rowcount == 1

    @staticmethod
    def _row(row: sqlite3.Row) -> PublishedRevision:
        return PublishedRevision(
            publication_id=row["publication_id"],
            intent_id=row["intent_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_id=row["repository_id"],
            commit=row["commit_id"],
            tree=row["tree_id"],
            git_parent_commits=tuple(json.loads(row["git_parent_commits_json"])),
            declared_base_commit=row["declared_base_commit"],
            parent_publication_id=row["parent_publication_id"],
            publisher_agent_member_id=row["publisher_agent_member_id"],
            publisher_agent_id=row["publisher_agent_id"],
            publisher_workspace_id=row["publisher_workspace_id"],
            publisher_workspace_generation=int(
                row["publisher_workspace_generation"]
            ),
            publication_ref=row["publication_ref"],
            manifest=_manifest_from_json(row["manifest_json"]),
            repository_policy_version=row["repository_policy_version"],
            repository_policy_digest=row["repository_policy_digest"],
            controlled_execution_id=row["controlled_execution_id"],
            remote_receipt_id=row["remote_receipt_id"],
            supersedes_publication_id=row["supersedes_publication_id"],
            created_at=row["created_at"],
            revision_digest=row["revision_digest"],
            schema_version=row["schema_version"],
        )


def _manifest_from_json(value: str) -> WorkspacePublicationManifest:
    payload = json.loads(value)
    entries = tuple(
        PublicationManifestEntry(
            path=item["path"],
            mode=item["mode"],
            object_kind=PublicationManifestObjectKind(item["object_kind"]),
            object_id=item["object_id"],
            size_bytes=item.get("size_bytes"),
            lfs_oid=item.get("lfs_oid"),
            lfs_size_bytes=item.get("lfs_size_bytes"),
        )
        for item in payload["entries"]
    )
    return WorkspacePublicationManifest(
        entries=entries,
        manifest_digest=payload["manifest_digest"],
        schema_version=payload["schema_version"],
    )


def _enum_value(value: object | None) -> str | None:
    return None if value is None else str(getattr(value, "value"))


def _execution_identity(execution: ControlledOperationExecution) -> tuple[object, ...]:
    return (
        execution.execution_id,
        execution.operation_id,
        execution.session_id,
        execution.task_id,
        execution.lane_id,
        execution.approval_id,
        execution.owner_mode,
        execution.operation_digest,
        execution.approval_digest,
        execution.route_policy_id,
        execution.selected_backend,
        execution.adapter_policy_id,
        execution.input_identity_digest,
        execution.expected_output_contract_digest,
        execution.runtime_identity_digest,
        execution.created_at,
    )


__all__ = [
    "PublishedRevisionRepository",
    "WorkspacePublicationExecutionEventRepository",
    "WorkspacePublicationExecutionRepository",
    "WorkspacePublicationIdentityConflictError",
    "WorkspacePublicationIntentRepository",
    "WorkspacePublicationRemoteReceiptRepository",
    "WorkspacePublicationRepositoryError",
]
