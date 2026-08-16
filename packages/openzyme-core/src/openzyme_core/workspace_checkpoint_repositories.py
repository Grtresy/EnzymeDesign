from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from openzyme_domain import AgentWorkspaceStateObservation
from openzyme_domain import PrivateRefAdvanceKind
from openzyme_domain import VerifiedWorkspaceCheckpoint
from openzyme_domain import WorkspaceDirtyState
from openzyme_domain import WorkspaceFormalBoundary

from .repositories import _commit


class WorkspaceCheckpointRepositoryError(RuntimeError):
    error_code = "workspace_checkpoint_repository_error"


@dataclass(slots=True)
class AgentWorkspaceStateObservationRepository:
    connection: sqlite3.Connection

    def add(
        self,
        observation: AgentWorkspaceStateObservation,
    ) -> AgentWorkspaceStateObservation:
        existing = self.get(observation.observation_id)
        if existing is not None:
            if existing == observation:
                return existing
            raise WorkspaceCheckpointRepositoryError(
                "workspace observation id identifies different content"
            )
        self.connection.execute(
            """
            INSERT INTO agent_workspace_state_observations (
                observation_id, workspace_id, session_id, agent_member_id,
                agent_id, workspace_generation, head_commit, head_tree,
                dirty_state, staged, unstaged, untracked, observed_at,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation.observation_id,
                observation.workspace_id,
                observation.session_id,
                observation.agent_member_id,
                observation.agent_id,
                observation.workspace_generation,
                observation.head_commit,
                observation.head_tree,
                observation.dirty_state.value,
                int(observation.staged),
                int(observation.unstaged),
                int(observation.untracked),
                observation.observed_at,
                observation.schema_version,
            ),
        )
        _commit(self.connection)
        return observation

    def get(self, observation_id: str) -> AgentWorkspaceStateObservation | None:
        row = self.connection.execute(
            "SELECT * FROM agent_workspace_state_observations WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def latest_for_workspace(
        self,
        workspace_id: str,
    ) -> AgentWorkspaceStateObservation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_workspace_state_observations
            WHERE workspace_id = ?
            ORDER BY observed_at DESC, observation_id DESC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> AgentWorkspaceStateObservation:
        return AgentWorkspaceStateObservation(
            observation_id=row["observation_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            head_commit=row["head_commit"],
            head_tree=row["head_tree"],
            dirty_state=WorkspaceDirtyState(row["dirty_state"]),
            staged=bool(row["staged"]),
            unstaged=bool(row["unstaged"]),
            untracked=bool(row["untracked"]),
            observed_at=row["observed_at"],
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class VerifiedWorkspaceCheckpointRepository:
    connection: sqlite3.Connection

    def add(
        self,
        checkpoint: VerifiedWorkspaceCheckpoint,
    ) -> VerifiedWorkspaceCheckpoint:
        existing = self.get(checkpoint.checkpoint_id)
        if existing is not None:
            if existing == checkpoint:
                return existing
            raise WorkspaceCheckpointRepositoryError(
                "checkpoint id identifies different content"
            )
        self.connection.execute(
            """
            INSERT INTO verified_workspace_checkpoint_records (
                checkpoint_id, boundary, workspace_id, session_id,
                agent_member_id, agent_id, workspace_generation,
                repository_binding_id, repository_binding_version,
                repository_id, commit_oid, tree_oid, private_ref,
                prior_commit_oid, advance_kind, remote_observed_at,
                verified_at, checkpoint_digest, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.checkpoint_id,
                checkpoint.boundary.value,
                checkpoint.workspace_id,
                checkpoint.session_id,
                checkpoint.agent_member_id,
                checkpoint.agent_id,
                checkpoint.workspace_generation,
                checkpoint.repository_binding_id,
                checkpoint.repository_binding_version,
                checkpoint.repository_id,
                checkpoint.commit,
                checkpoint.tree,
                checkpoint.private_ref,
                checkpoint.prior_commit,
                checkpoint.advance_kind.value,
                checkpoint.remote_observed_at,
                checkpoint.verified_at,
                checkpoint.checkpoint_digest,
                checkpoint.schema_version,
            ),
        )
        _commit(self.connection)
        return checkpoint

    def get(self, checkpoint_id: str) -> VerifiedWorkspaceCheckpoint | None:
        row = self.connection.execute(
            """
            SELECT * FROM verified_workspace_checkpoint_records
            WHERE checkpoint_id = ?
            """,
            (checkpoint_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def latest_for_workspace(
        self,
        workspace_id: str,
    ) -> VerifiedWorkspaceCheckpoint | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM verified_workspace_checkpoint_records
            WHERE workspace_id = ?
            ORDER BY verified_at DESC, checkpoint_id DESC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def latest_for_ref(
        self,
        *,
        workspace_id: str,
        private_ref: str,
    ) -> VerifiedWorkspaceCheckpoint | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM verified_workspace_checkpoint_records
            WHERE workspace_id = ? AND private_ref = ?
            ORDER BY verified_at DESC, checkpoint_id DESC
            LIMIT 1
            """,
            (workspace_id, private_ref),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_workspace(
        self,
        workspace_id: str,
    ) -> list[VerifiedWorkspaceCheckpoint]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM verified_workspace_checkpoint_records
            WHERE workspace_id = ?
            ORDER BY verified_at, checkpoint_id
            """,
            (workspace_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> VerifiedWorkspaceCheckpoint:
        return VerifiedWorkspaceCheckpoint(
            checkpoint_id=row["checkpoint_id"],
            boundary=WorkspaceFormalBoundary(row["boundary"]),
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_id=row["repository_id"],
            commit=row["commit_oid"],
            tree=row["tree_oid"],
            private_ref=row["private_ref"],
            prior_commit=row["prior_commit_oid"],
            advance_kind=PrivateRefAdvanceKind(row["advance_kind"]),
            remote_observed_at=row["remote_observed_at"],
            verified_at=row["verified_at"],
            checkpoint_digest=row["checkpoint_digest"],
            schema_version=row["schema_version"],
        )


__all__ = [
    "AgentWorkspaceStateObservationRepository",
    "VerifiedWorkspaceCheckpointRepository",
    "WorkspaceCheckpointRepositoryError",
]
