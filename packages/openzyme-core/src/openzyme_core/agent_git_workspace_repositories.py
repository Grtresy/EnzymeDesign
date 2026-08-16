from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceBlockerCode
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import GitObjectFormat

from .repositories import _commit


class AgentGitWorkspaceRepositoryError(RuntimeError):
    """Base error for canonical generation-owned Git workspace state."""


class AgentGitWorkspaceVersionConflictError(AgentGitWorkspaceRepositoryError):
    """A workspace compare-and-swap transition lost its state version."""


@dataclass(slots=True)
class AgentGitWorkspaceRepository:
    connection: sqlite3.Connection

    def add(self, workspace: AgentGitWorkspace) -> AgentGitWorkspace:
        existing = self.get(workspace.workspace_id)
        if existing is not None:
            if existing == workspace:
                return existing
            raise AgentGitWorkspaceRepositoryError(
                f"workspace_id {workspace.workspace_id!r} identifies other content"
            )
        self.connection.execute(
            """
            INSERT INTO agent_git_workspace_records (
                workspace_id,
                session_id,
                agent_member_id,
                agent_id,
                workspace_generation,
                reservation_id,
                reservation_fingerprint,
                capability_lease_id,
                capability_lease_intent_digest,
                repository_binding_id,
                repository_binding_version,
                repository_binding_digest,
                repository_id,
                internal_git_service_id,
                internal_git_endpoint,
                object_format,
                base_commit,
                volume_id,
                clone_logical_root,
                image_ref,
                image_manifest_digest,
                image_qualification_digest,
                private_ref_namespace,
                repository_policy_version,
                repository_policy_digest,
                capability_policy_version,
                capability_policy_digest,
                status,
                state_version,
                head_commit,
                head_tree,
                readiness_observation_digest,
                ready_at,
                blocker_code,
                blocker_detail_digest,
                blocked_at,
                frozen_reason,
                frozen_at,
                replaced_by_generation,
                replaced_at,
                created_at,
                updated_at,
                workspace_identity_digest,
                canonical_digest,
                schema_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            self._values(workspace),
        )
        _commit(self.connection)
        return workspace

    def update(
        self,
        workspace: AgentGitWorkspace,
        *,
        expected_state_version: int,
    ) -> AgentGitWorkspace:
        cursor = self.connection.execute(
            """
            UPDATE agent_git_workspace_records
            SET session_id = ?,
                agent_member_id = ?,
                agent_id = ?,
                workspace_generation = ?,
                reservation_id = ?,
                reservation_fingerprint = ?,
                capability_lease_id = ?,
                capability_lease_intent_digest = ?,
                repository_binding_id = ?,
                repository_binding_version = ?,
                repository_binding_digest = ?,
                repository_id = ?,
                internal_git_service_id = ?,
                internal_git_endpoint = ?,
                object_format = ?,
                base_commit = ?,
                volume_id = ?,
                clone_logical_root = ?,
                image_ref = ?,
                image_manifest_digest = ?,
                image_qualification_digest = ?,
                private_ref_namespace = ?,
                repository_policy_version = ?,
                repository_policy_digest = ?,
                capability_policy_version = ?,
                capability_policy_digest = ?,
                status = ?,
                state_version = ?,
                head_commit = ?,
                head_tree = ?,
                readiness_observation_digest = ?,
                ready_at = ?,
                blocker_code = ?,
                blocker_detail_digest = ?,
                blocked_at = ?,
                frozen_reason = ?,
                frozen_at = ?,
                replaced_by_generation = ?,
                replaced_at = ?,
                created_at = ?,
                updated_at = ?,
                workspace_identity_digest = ?,
                canonical_digest = ?,
                schema_version = ?
            WHERE workspace_id = ? AND state_version = ?
            """,
            (*self._values(workspace)[1:], workspace.workspace_id, expected_state_version),
        )
        _commit(self.connection)
        if cursor.rowcount != 1:
            raise AgentGitWorkspaceVersionConflictError(
                "agent Git workspace state version conflict"
            )
        return workspace

    def get(self, workspace_id: str) -> AgentGitWorkspace | None:
        row = self.connection.execute(
            """
            SELECT * FROM agent_git_workspace_records WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_generation(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
    ) -> AgentGitWorkspace | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_git_workspace_records
            WHERE session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (session_id, agent_member_id, workspace_generation),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_current(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> AgentGitWorkspace | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_git_workspace_records
            WHERE session_id = ?
              AND agent_member_id = ?
              AND status <> 'replaced'
            """,
            (session_id, agent_member_id),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_agent(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> list[AgentGitWorkspace]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_git_workspace_records
            WHERE session_id = ? AND agent_member_id = ?
            ORDER BY workspace_generation
            """,
            (session_id, agent_member_id),
        ).fetchall()
        return [self._row(row) for row in rows]

    def list_by_session(self, session_id: str) -> list[AgentGitWorkspace]:
        rows = self.connection.execute(
            """
            SELECT * FROM agent_git_workspace_records
            WHERE session_id = ?
            ORDER BY agent_member_id, workspace_generation, workspace_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _values(workspace: AgentGitWorkspace) -> tuple[object, ...]:
        return (
            workspace.workspace_id,
            workspace.session_id,
            workspace.agent_member_id,
            workspace.agent_id,
            workspace.workspace_generation,
            workspace.reservation_id,
            workspace.reservation_fingerprint,
            workspace.capability_lease_id,
            workspace.capability_lease_intent_digest,
            workspace.repository_binding_id,
            workspace.repository_binding_version,
            workspace.repository_binding_digest,
            workspace.repository_id,
            workspace.internal_git_service_id,
            workspace.internal_git_endpoint,
            workspace.object_format.value,
            workspace.base_commit,
            workspace.volume_id,
            workspace.clone_logical_root,
            workspace.image_ref,
            workspace.image_manifest_digest,
            workspace.image_qualification_digest,
            workspace.private_ref_namespace,
            workspace.repository_policy_version,
            workspace.repository_policy_digest,
            workspace.capability_policy_version,
            workspace.capability_policy_digest,
            workspace.status.value,
            workspace.state_version,
            workspace.head_commit,
            workspace.head_tree,
            workspace.readiness_observation_digest,
            workspace.ready_at,
            None if workspace.blocker_code is None else workspace.blocker_code.value,
            workspace.blocker_detail_digest,
            workspace.blocked_at,
            workspace.frozen_reason,
            workspace.frozen_at,
            workspace.replaced_by_generation,
            workspace.replaced_at,
            workspace.created_at,
            workspace.updated_at,
            workspace.workspace_identity_digest,
            workspace.canonical_digest,
            workspace.schema_version,
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> AgentGitWorkspace:
        blocker_code = row["blocker_code"]
        return AgentGitWorkspace(
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            reservation_id=row["reservation_id"],
            reservation_fingerprint=row["reservation_fingerprint"],
            capability_lease_id=row["capability_lease_id"],
            capability_lease_intent_digest=row["capability_lease_intent_digest"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_binding_digest=row["repository_binding_digest"],
            repository_id=row["repository_id"],
            internal_git_service_id=row["internal_git_service_id"],
            internal_git_endpoint=row["internal_git_endpoint"],
            object_format=GitObjectFormat(row["object_format"]),
            base_commit=row["base_commit"],
            volume_id=row["volume_id"],
            clone_logical_root=row["clone_logical_root"],
            image_ref=row["image_ref"],
            image_manifest_digest=row["image_manifest_digest"],
            image_qualification_digest=row["image_qualification_digest"],
            private_ref_namespace=row["private_ref_namespace"],
            repository_policy_version=row["repository_policy_version"],
            repository_policy_digest=row["repository_policy_digest"],
            capability_policy_version=row["capability_policy_version"],
            capability_policy_digest=row["capability_policy_digest"],
            status=AgentGitWorkspaceStatus(row["status"]),
            state_version=int(row["state_version"]),
            head_commit=row["head_commit"],
            head_tree=row["head_tree"],
            readiness_observation_digest=row["readiness_observation_digest"],
            ready_at=row["ready_at"],
            blocker_code=(
                None
                if blocker_code is None
                else AgentGitWorkspaceBlockerCode(blocker_code)
            ),
            blocker_detail_digest=row["blocker_detail_digest"],
            blocked_at=row["blocked_at"],
            frozen_reason=row["frozen_reason"],
            frozen_at=row["frozen_at"],
            replaced_by_generation=row["replaced_by_generation"],
            replaced_at=row["replaced_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            workspace_identity_digest=row["workspace_identity_digest"],
            canonical_digest=row["canonical_digest"],
            schema_version=row["schema_version"],
        )


__all__ = [
    "AgentGitWorkspaceRepository",
    "AgentGitWorkspaceRepositoryError",
    "AgentGitWorkspaceVersionConflictError",
]
