from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import sqlite3
from typing import Any
from uuid import uuid4

from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import SessionRepositoryBindingPin

from .repositories import _commit
from .repositories import _managed_transaction_depth
from .repository_credentials import private_ref_prefix
from .repository_storage import DurableRepositoryRootManager


class RepositoryPrivateNamespaceStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    RETIRED = "retired"


class RepositoryPrivateNamespaceHoldKind(StrEnum):
    ACTIVE_CAPABILITY_LEASE = "active_capability_lease"
    PUBLICATION_PIN = "publication_pin"
    HISTORICAL_MIGRATION_PIN = "historical_migration_pin"
    LEGAL_HOLD = "legal_hold"
    AUDIT_HOLD = "audit_hold"
    RETAINED_REFERENCE = "retained_reference"


class RepositoryRetentionError(RuntimeError):
    error_code = "repository_retention_rejected"


def _parse_utc(value: str, *, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@dataclass(frozen=True, slots=True)
class RepositoryPrivateNamespace:
    namespace_id: str
    binding_id: str
    binding_version: int
    session_id: str
    agent_member_id: str
    workspace_generation: int
    namespace_prefix: str
    status: RepositoryPrivateNamespaceStatus
    retention_deadline: str
    opened_at: str
    closed_at: str | None
    retired_at: str | None


def _row_to_namespace(row: sqlite3.Row) -> RepositoryPrivateNamespace:
    return RepositoryPrivateNamespace(
        namespace_id=row["namespace_id"],
        binding_id=row["binding_id"],
        binding_version=int(row["binding_version"]),
        session_id=row["session_id"],
        agent_member_id=row["agent_member_id"],
        workspace_generation=int(row["workspace_generation"]),
        namespace_prefix=row["namespace_prefix"],
        status=RepositoryPrivateNamespaceStatus(row["status"]),
        retention_deadline=row["retention_deadline"],
        opened_at=row["opened_at"],
        closed_at=row["closed_at"],
        retired_at=row["retired_at"],
    )


@dataclass(slots=True)
class RepositoryPrivateNamespaceRetentionService:
    connection: sqlite3.Connection
    roots: DurableRepositoryRootManager

    def open_namespace(
        self,
        *,
        binding: ProjectRepositoryBinding,
        pin: SessionRepositoryBindingPin,
        agent_member_id: str,
        workspace_generation: int,
        retention_deadline: str,
        opened_at: str,
        namespace_id: str | None = None,
    ) -> RepositoryPrivateNamespace:
        if (
            pin.binding_id != binding.binding_id
            or pin.binding_version != binding.binding_version
            or pin.repository_id != binding.repository_id
        ):
            raise RepositoryRetentionError(
                "private namespace binding does not match session pin"
            )
        if _parse_utc(
            retention_deadline, field_name="retention_deadline"
        ) <= _parse_utc(
            opened_at,
            field_name="opened_at",
        ):
            raise RepositoryRetentionError(
                "private namespace retention deadline must follow opening"
            )
        resolved_id = namespace_id or f"repository_namespace_{uuid4().hex}"
        prefix = private_ref_prefix(
            binding,
            session_id=pin.session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        )
        self.connection.execute(
            """
            INSERT INTO repository_private_namespace_records (
                namespace_id, binding_id, binding_version, session_id,
                agent_member_id, workspace_generation, namespace_prefix,
                status, retention_deadline, opened_at, closed_at, retired_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, NULL, NULL)
            """,
            (
                resolved_id,
                binding.binding_id,
                binding.binding_version,
                pin.session_id,
                agent_member_id,
                workspace_generation,
                prefix,
                retention_deadline,
                opened_at,
            ),
        )
        _commit(self.connection)
        return self.require_namespace(resolved_id)

    def require_namespace(self, namespace_id: str) -> RepositoryPrivateNamespace:
        row = self.connection.execute(
            "SELECT * FROM repository_private_namespace_records WHERE namespace_id = ?",
            (namespace_id,),
        ).fetchone()
        if row is None:
            raise RepositoryRetentionError(
                f"private namespace {namespace_id!r} does not exist"
            )
        return _row_to_namespace(row)

    def close_namespace(self, namespace_id: str, *, closed_at: str) -> None:
        namespace = self.require_namespace(namespace_id)
        if namespace.status is not RepositoryPrivateNamespaceStatus.OPEN:
            raise RepositoryRetentionError("only an open private namespace can close")
        if _parse_utc(closed_at, field_name="closed_at") < _parse_utc(
            namespace.opened_at,
            field_name="opened_at",
        ):
            raise RepositoryRetentionError(
                "private namespace cannot close before opening"
            )
        cursor = self.connection.execute(
            """
            UPDATE repository_private_namespace_records
            SET status = 'closed', closed_at = ?
            WHERE namespace_id = ? AND status = 'open'
            """,
            (closed_at, namespace_id),
        )
        if cursor.rowcount != 1:
            raise RepositoryRetentionError(
                "private namespace changed before close could commit"
            )
        _commit(self.connection)

    def add_hold(
        self,
        namespace_id: str,
        *,
        hold_kind: RepositoryPrivateNamespaceHoldKind,
        owner_ref: str,
        created_at: str,
        hold_id: str | None = None,
    ) -> str:
        resolved_id = hold_id or f"repository_namespace_hold_{uuid4().hex}"
        self.connection.execute(
            """
            INSERT INTO repository_private_namespace_holds (
                hold_id, namespace_id, hold_kind, owner_ref, created_at, released_at
            )
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (resolved_id, namespace_id, hold_kind.value, owner_ref, created_at),
        )
        _commit(self.connection)
        return resolved_id

    def release_hold(self, hold_id: str, *, released_at: str) -> None:
        cursor = self.connection.execute(
            """
            UPDATE repository_private_namespace_holds
            SET released_at = ?
            WHERE hold_id = ? AND released_at IS NULL
            """,
            (released_at, hold_id),
        )
        if cursor.rowcount != 1:
            raise RepositoryRetentionError(f"active hold {hold_id!r} does not exist")
        _commit(self.connection)

    def retire_namespace(
        self,
        namespace_id: str,
        *,
        binding: ProjectRepositoryBinding,
        retired_at: str,
        retention_owner_ref: str,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        if _managed_transaction_depth(self.connection) != 0:
            raise RepositoryRetentionError(
                "namespace retirement must own its receipt-before-delete transaction"
            )
        namespace = self.require_namespace(namespace_id)
        if (
            namespace.binding_id != binding.binding_id
            or namespace.binding_version != binding.binding_version
        ):
            raise RepositoryRetentionError(
                "private namespace does not match repository binding"
            )
        if namespace.status is RepositoryPrivateNamespaceStatus.RETIRED:
            if self.roots.list_refs(
                binding,
                prefix=f"{namespace.namespace_prefix}/",
            ):
                raise RepositoryRetentionError(
                    "retired private namespace refs reappeared after deletion"
                )
            return self._require_receipt(namespace_id)
        if namespace.status is not RepositoryPrivateNamespaceStatus.CLOSED:
            raise RepositoryRetentionError(
                "private namespace must be closed before retirement"
            )
        if _parse_utc(retired_at, field_name="retired_at") < _parse_utc(
            namespace.retention_deadline,
            field_name="retention_deadline",
        ):
            raise RepositoryRetentionError(
                "private namespace retention deadline has not passed"
            )
        active_holds = self.connection.execute(
            """
            SELECT hold_kind, owner_ref
            FROM repository_private_namespace_holds
            WHERE namespace_id = ? AND released_at IS NULL
            ORDER BY hold_id
            """,
            (namespace_id,),
        ).fetchall()
        if active_holds:
            kinds = ", ".join(row["hold_kind"] for row in active_holds)
            raise RepositoryRetentionError(
                f"private namespace has active retention holds: {kinds}"
            )

        current_refs = self.roots.list_refs(
            binding,
            prefix=f"{namespace.namespace_prefix}/",
        )
        for _, commit in current_refs:
            self.roots.require_commit_object(binding, commit)
        existing = self.connection.execute(
            """
            SELECT receipt_json
            FROM repository_private_namespace_retirement_receipts
            WHERE namespace_id = ?
            """,
            (namespace_id,),
        ).fetchone()
        if existing is None:
            terminal_refs = [
                {"ref_name": ref_name, "commit": commit}
                for ref_name, commit in current_refs
            ]
            payload = {
                "schema_version": "repository_private_namespace_retirement@1",
                "receipt_id": (
                    receipt_id or f"repository_namespace_retirement_{uuid4().hex}"
                ),
                "namespace_id": namespace.namespace_id,
                "binding_id": namespace.binding_id,
                "binding_version": namespace.binding_version,
                "namespace_prefix": namespace.namespace_prefix,
                "terminal_refs": terminal_refs,
                "terminal_commits": sorted({commit for _, commit in current_refs}),
                "created_at": retired_at,
                "created_by": retention_owner_ref,
            }
            receipt_json = _canonical_json(payload)
            receipt_digest = (
                f"sha256:{hashlib.sha256(receipt_json.encode('utf-8')).hexdigest()}"
            )
            self.connection.execute(
                """
                INSERT INTO repository_private_namespace_retirement_receipts (
                    receipt_id, namespace_id, binding_id, binding_version,
                    namespace_prefix, terminal_refs_json, terminal_commits_json,
                    receipt_digest, receipt_json, created_at, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["receipt_id"],
                    namespace.namespace_id,
                    namespace.binding_id,
                    namespace.binding_version,
                    namespace.namespace_prefix,
                    _canonical_json({"items": terminal_refs}),
                    _canonical_json({"items": payload["terminal_commits"]}),
                    receipt_digest,
                    receipt_json,
                    retired_at,
                    retention_owner_ref,
                ),
            )
            _commit(self.connection)
            receipt = {**payload, "receipt_digest": receipt_digest}
        else:
            receipt = self._require_receipt(namespace_id)
            terminal_refs = list(receipt["terminal_refs"])

        expected_refs = tuple(
            (str(item["ref_name"]), str(item["commit"])) for item in terminal_refs
        )
        current_refs = self.roots.list_refs(
            binding,
            prefix=f"{namespace.namespace_prefix}/",
        )
        if current_refs and current_refs != expected_refs:
            raise RepositoryRetentionError(
                "private namespace refs changed after retirement receipt"
            )
        if current_refs:
            self.roots.delete_exact_refs(binding, expected_refs)
        cursor = self.connection.execute(
            """
            UPDATE repository_private_namespace_records
            SET status = 'retired', retired_at = ?
            WHERE namespace_id = ? AND status = 'closed'
            """,
            (retired_at, namespace_id),
        )
        if cursor.rowcount != 1:
            raise RepositoryRetentionError(
                "private namespace changed before retirement could commit"
            )
        _commit(self.connection)
        return receipt

    def _require_receipt(self, namespace_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT receipt_json, receipt_digest
            FROM repository_private_namespace_retirement_receipts
            WHERE namespace_id = ?
            """,
            (namespace_id,),
        ).fetchone()
        if row is None:
            raise RepositoryRetentionError(
                f"private namespace {namespace_id!r} has no retirement receipt"
            )
        payload = json.loads(row["receipt_json"])
        if not isinstance(payload, dict):
            raise RepositoryRetentionError("retirement receipt payload is invalid")
        return {**payload, "receipt_digest": row["receipt_digest"]}


__all__ = [
    "RepositoryPrivateNamespace",
    "RepositoryPrivateNamespaceHoldKind",
    "RepositoryPrivateNamespaceRetentionService",
    "RepositoryPrivateNamespaceStatus",
    "RepositoryRetentionError",
]
