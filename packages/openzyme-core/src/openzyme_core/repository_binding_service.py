from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
from typing import Literal
from uuid import uuid4

from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryBindingDriftKind
from openzyme_domain import RepositoryBindingLifecycleStatus
from openzyme_domain import RepositoryRefClass
from openzyme_domain import Session
from openzyme_domain import SessionRepositoryBindingPin

from .repositories import CoreRepositories
from .repositories import RepositoryBindingConflictError
from .repositories import RepositoryBindingRequiredError
from .repositories import RepositoryBindingRetiredError
from .repository_storage import DurableRepositoryRootManager


RepositoryPrerequisite = Literal[
    "session_restore",
    "agent_workspace",
    "publication",
    "hpc_workspace",
    "historical_migration",
]


class RepositoryBindingDriftError(RuntimeError):
    error_code = "repository_binding_drift"

    def __init__(self, drift: tuple[RepositoryBindingDriftKind, ...]) -> None:
        self.drift = drift
        super().__init__(
            "repository binding drift: " + ", ".join(item.value for item in drift)
        )


@dataclass(frozen=True, slots=True)
class ResolvedSessionRepositoryBinding:
    pin: SessionRepositoryBindingPin
    binding: ProjectRepositoryBinding
    lifecycle_status: RepositoryBindingLifecycleStatus

    def safe_projection(
        self,
        *,
        allowed_ref_classes: tuple[RepositoryRefClass, ...],
    ) -> dict[str, object]:
        projected = self.binding.safe_projection(
            lifecycle_status=self.lifecycle_status,
            allowed_ref_classes=allowed_ref_classes,
        )
        projected.update(
            {
                "session_id": self.pin.session_id,
                "resolved_base_commit": self.pin.resolved_base_commit,
                "binding_canonical_digest": self.pin.binding_canonical_digest,
            }
        )
        return projected


@dataclass(slots=True)
class ProjectRepositoryBindingService:
    repositories: CoreRepositories
    roots: DurableRepositoryRootManager

    def assert_endpoint_identity(self, binding: ProjectRepositoryBinding) -> None:
        origin = self.roots.settings.https_origin.rstrip("/")
        expected_git = f"{origin}/repositories/{binding.repository_id}.git"
        expected_lfs = f"{expected_git}/info/lfs"
        if binding.internal_git_endpoint != expected_git:
            raise RepositoryBindingConflictError(
                "binding Git endpoint does not match configured repository service"
            )
        if binding.lfs_endpoint != expected_lfs:
            raise RepositoryBindingConflictError(
                "binding LFS endpoint does not match configured repository service"
            )

    def register(
        self,
        binding: ProjectRepositoryBinding,
    ) -> ProjectRepositoryBinding:
        self.assert_endpoint_identity(binding)
        self.roots.preflight_roots()
        self.roots.verify_exact_base(binding)
        return self.repositories.project_repository_bindings.add(binding)

    def activate(
        self,
        binding_id: str,
        *,
        actor_ref: str,
        activated_at: str,
    ) -> ProjectRepositoryBinding:
        binding = self.repositories.project_repository_bindings.get(binding_id)
        if binding is None:
            raise RepositoryBindingRequiredError(
                f"repository binding {binding_id!r} does not exist"
            )
        self.assert_endpoint_identity(binding)
        self.roots.preflight_roots()
        self.roots.verify_exact_base(binding)
        self.roots.set_default_head(binding)
        self.roots.verify_default_head(binding)
        return self.repositories.project_repository_bindings.activate(
            binding_id,
            actor_ref=actor_ref,
            activated_at=activated_at,
        )

    def create_pinned_session(
        self, session: Session
    ) -> ResolvedSessionRepositoryBinding:
        binding = self.repositories.project_repository_bindings.get_active(
            session.project_id
        )
        if binding is None:
            raise RepositoryBindingRequiredError(
                f"project {session.project_id!r} has no active repository binding"
            )
        self.assert_endpoint_identity(binding)
        self.roots.verify_exact_base(binding)
        with self.repositories.atomic(prefix="create_pinned_session"):
            current = self.repositories.project_repository_bindings.get_active(
                session.project_id
            )
            if current is None or current.canonical_digest != binding.canonical_digest:
                raise RepositoryBindingConflictError(
                    "project active repository binding changed during session creation"
                )
            pin = SessionRepositoryBindingPin(
                session_id=session.session_id,
                project_id=session.project_id,
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
                repository_id=binding.repository_id,
                resolved_base_commit=binding.default_base_commit,
                binding_canonical_digest=binding.canonical_digest,
                pinned_at=session.created_at,
            )
            self.repositories.sessions.save(session)
            self.repositories.session_repository_binding_pins.add(pin)
        return ResolvedSessionRepositoryBinding(
            pin=pin,
            binding=binding,
            lifecycle_status=RepositoryBindingLifecycleStatus.ACTIVE,
        )

    def require_session_binding(
        self,
        session_id: str,
        *,
        prerequisite: RepositoryPrerequisite,
    ) -> ResolvedSessionRepositoryBinding:
        if prerequisite not in {
            "session_restore",
            "agent_workspace",
            "publication",
            "hpc_workspace",
            "historical_migration",
        }:
            raise ValueError(f"unsupported repository prerequisite {prerequisite!r}")
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise RepositoryBindingRequiredError(
                f"session {session_id!r} does not exist"
            )
        pin = self.repositories.session_repository_binding_pins.require(session_id)
        binding = self.repositories.project_repository_bindings.get(pin.binding_id)
        if binding is None:
            raise RepositoryBindingRequiredError(
                f"session {session_id!r} references a missing repository binding"
            )
        self.assert_endpoint_identity(binding)
        lifecycle_status = (
            self.repositories.project_repository_bindings.lifecycle_status(
                binding.binding_id
            )
        )
        if lifecycle_status is RepositoryBindingLifecycleStatus.RETIRED:
            raise RepositoryBindingRetiredError(
                f"session {session_id!r} references a retired repository binding"
            )
        if (
            binding.project_id != session.project_id
            or pin.project_id != session.project_id
            or pin.binding_version != binding.binding_version
            or pin.repository_id != binding.repository_id
            or pin.resolved_base_commit != binding.default_base_commit
            or pin.binding_canonical_digest != binding.canonical_digest
        ):
            raise RepositoryBindingConflictError(
                f"session {session_id!r} repository pin is inconsistent"
            )
        self.roots.verify_pinned_commit(binding)
        return ResolvedSessionRepositoryBinding(
            pin=pin,
            binding=binding,
            lifecycle_status=lifecycle_status,
        )

    def assert_restore_configuration(
        self,
        session_id: str,
        *,
        configured_binding: ProjectRepositoryBinding,
    ) -> ResolvedSessionRepositoryBinding:
        resolved = self.require_session_binding(
            session_id,
            prerequisite="session_restore",
        )
        drift = resolved.binding.drift_from(configured_binding)
        if drift:
            raise RepositoryBindingDriftError(drift)
        return resolved

    def map_legacy_session(
        self,
        *,
        session_id: str,
        binding_id: str,
        binding_version: int,
        exact_base_commit: str,
        operator_ref: str,
        mapping_reason: str,
        mapped_at: str,
        receipt_id: str,
    ) -> tuple[ResolvedSessionRepositoryBinding, dict[str, object]]:
        binding = self.repositories.project_repository_bindings.get(binding_id)
        if binding is None or binding.binding_version != binding_version:
            raise RepositoryBindingRequiredError(
                "legacy mapping requires an exact existing binding id and version"
            )
        if exact_base_commit != binding.default_base_commit:
            raise RepositoryBindingConflictError(
                "legacy mapping base commit does not match binding"
            )
        self.assert_endpoint_identity(binding)
        self.roots.verify_pinned_commit(binding)
        pin, receipt = (
            self.repositories.session_repository_binding_pins.map_legacy_session(
                session_id=session_id,
                binding=binding,
                operator_ref=operator_ref,
                mapping_reason=mapping_reason,
                mapped_at=mapped_at,
                receipt_id=receipt_id,
            )
        )
        return (
            ResolvedSessionRepositoryBinding(
                pin=pin,
                binding=binding,
                lifecycle_status=(
                    self.repositories.project_repository_bindings.lifecycle_status(
                        binding.binding_id
                    )
                ),
            ),
            receipt,
        )

    def audit_binding_references(self, binding_id: str) -> dict[str, Any]:
        binding = self.repositories.project_repository_bindings.get(binding_id)
        if binding is None:
            raise RepositoryBindingRequiredError(
                f"repository binding {binding_id!r} does not exist"
            )
        connection = self.repositories.sessions.connection
        queries = {
            "active_pointer": (
                "SELECT COUNT(*) FROM project_repository_active_bindings "
                "WHERE binding_id = ? AND binding_version = ?"
            ),
            "session_pins": (
                "SELECT COUNT(*) FROM session_repository_binding_pins "
                "WHERE binding_id = ? AND binding_version = ?"
            ),
            "mapping_receipts": (
                "SELECT COUNT(*) FROM repository_binding_mapping_receipts "
                "WHERE binding_id = ? AND binding_version = ?"
            ),
            "credential_records": (
                "SELECT COUNT(*) FROM repository_credential_issuance_records "
                "WHERE binding_id = ? AND binding_version = ?"
            ),
            "private_namespaces": (
                "SELECT COUNT(*) FROM repository_private_namespace_records "
                "WHERE binding_id = ? AND binding_version = ?"
            ),
        }
        counts = {
            name: int(
                connection.execute(
                    query,
                    (binding.binding_id, binding.binding_version),
                ).fetchone()[0]
            )
            for name, query in queries.items()
        }
        payload = {
            "schema_version": "repository_binding_reference_audit@1",
            "binding_id": binding.binding_id,
            "binding_version": binding.binding_version,
            "project_id": binding.project_id,
            "counts": counts,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return {
            **payload,
            "reference_audit_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        }

    def retire_binding(
        self,
        binding_id: str,
        *,
        retired_at: str,
        retired_by: str,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        binding = self.repositories.project_repository_bindings.get(binding_id)
        if binding is None:
            raise RepositoryBindingRequiredError(
                f"repository binding {binding_id!r} does not exist"
            )
        if (
            self.repositories.project_repository_bindings.lifecycle_status(binding_id)
            is RepositoryBindingLifecycleStatus.RETIRED
        ):
            row = self.repositories.sessions.connection.execute(
                """
                SELECT receipt_json, receipt_digest
                FROM project_repository_binding_retirement_receipts
                WHERE binding_id = ? AND binding_version = ?
                """,
                (binding.binding_id, binding.binding_version),
            ).fetchone()
            if row is None:
                raise RuntimeError("retired repository binding has no receipt")
            payload = json.loads(row["receipt_json"])
            return {**payload, "receipt_digest": row["receipt_digest"]}
        audit = self.audit_binding_references(binding_id)
        counts = dict(audit["counts"])
        if any(int(value) != 0 for value in counts.values()):
            raise RepositoryBindingConflictError(
                "referenced repository binding cannot be retired: "
                + ", ".join(
                    f"{name}={value}"
                    for name, value in sorted(counts.items())
                    if int(value) != 0
                )
            )
        payload = {
            "schema_version": "project_repository_binding_retirement@1",
            "receipt_id": receipt_id or f"repository_binding_retirement_{uuid4().hex}",
            "binding_id": binding.binding_id,
            "binding_version": binding.binding_version,
            "project_id": binding.project_id,
            "reference_audit_digest": audit["reference_audit_digest"],
            "created_at": retired_at,
            "created_by": retired_by,
        }
        receipt_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        receipt_digest = (
            f"sha256:{hashlib.sha256(receipt_json.encode('utf-8')).hexdigest()}"
        )
        connection = self.repositories.sessions.connection
        with self.repositories.atomic(prefix="retire_repository_binding"):
            connection.execute(
                """
                INSERT INTO project_repository_binding_retirement_receipts (
                    receipt_id, binding_id, binding_version, project_id,
                    reference_audit_digest, receipt_digest, receipt_json,
                    created_at, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["receipt_id"],
                    binding.binding_id,
                    binding.binding_version,
                    binding.project_id,
                    audit["reference_audit_digest"],
                    receipt_digest,
                    receipt_json,
                    retired_at,
                    retired_by,
                ),
            )
            connection.execute(
                """
                INSERT INTO project_repository_binding_lifecycle_events (
                    event_id, project_id, binding_id, binding_version,
                    status, actor_ref, reason, created_at
                )
                VALUES (?, ?, ?, ?, 'retired', ?, ?, ?)
                """,
                (
                    f"repository_binding_event_{uuid4().hex}",
                    binding.project_id,
                    binding.binding_id,
                    binding.binding_version,
                    retired_by,
                    "reference audit contains no retained owner",
                    retired_at,
                ),
            )
        return {**payload, "receipt_digest": receipt_digest}


__all__ = [
    "ProjectRepositoryBindingService",
    "RepositoryBindingDriftError",
    "RepositoryPrerequisite",
    "ResolvedSessionRepositoryBinding",
]
