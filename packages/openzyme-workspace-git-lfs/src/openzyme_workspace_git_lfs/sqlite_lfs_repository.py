from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
import sqlite3
from typing import Callable

from .credential_claims import RepositoryCredentialClaims
from .lfs import GitLfsBindingPolicy
from .lfs import GitLfsClosureEntry
from .lfs import GitLfsClosureManifest
from .lfs import GitLfsClosureVerification
from .lfs import GitLfsGcCandidateReceipt
from .lfs import GitLfsObjectReadReceipt
from .lfs import GitLfsPathRepresentation
from .lfs import GitLfsPathRule
from .lfs import GitLfsPrivateReachabilityReceipt
from .lfs import GitLfsRetentionClass
from .lfs import GitLfsUploadSession
from .lfs import GitLfsUploadStatus
from .lfs import canonical_lfs_digest


class GitLfsRepositoryError(RuntimeError):
    error_code = "git_lfs_repository_error"


class GitLfsPolicyError(GitLfsRepositoryError):
    error_code = "git_lfs_policy_mismatch"


class GitLfsQuotaExceededError(GitLfsRepositoryError):
    error_code = "git_lfs_quota_exceeded"

    def __init__(self, *, scope: str, limit_bytes: int, requested_bytes: int) -> None:
        self.scope = scope
        self.limit_bytes = limit_bytes
        self.requested_bytes = requested_bytes
        super().__init__(
            f"Git LFS {scope} quota {limit_bytes} bytes would be exceeded by "
            f"{requested_bytes} bytes"
        )


@dataclass(slots=True)
class GitLfsRepository:
    connection: sqlite3.Connection
    commit: Callable[[sqlite3.Connection], None]

    def add_policy(self, policy: GitLfsBindingPolicy) -> GitLfsBindingPolicy:
        existing = self.get_policy(
            binding_id=policy.binding_id,
            binding_version=policy.binding_version,
        )
        if existing is not None:
            if existing == policy:
                return existing
            raise GitLfsPolicyError("immutable binding already owns another LFS policy")
        self.connection.execute(
            """
            INSERT INTO git_lfs_binding_policies (
                binding_id, binding_version, repository_id, lfs_service_id,
                lfs_endpoint, object_format, path_rules_json,
                ordinary_blob_threshold_bytes, max_object_bytes,
                max_workspace_bytes, max_repository_bytes,
                published_retention_class, private_retention_class,
                private_retention_seconds, policy_version, policy_digest,
                schema_version, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.binding_id,
                policy.binding_version,
                policy.repository_id,
                policy.lfs_service_id,
                policy.lfs_endpoint,
                policy.object_format,
                json.dumps(
                    [rule.to_dict() for rule in policy.path_rules],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                policy.ordinary_blob_threshold_bytes,
                policy.max_object_bytes,
                policy.max_workspace_bytes,
                policy.max_repository_bytes,
                policy.published_retention_class.value,
                policy.private_retention_class.value,
                policy.private_retention_seconds,
                policy.policy_version,
                policy.policy_digest,
                policy.schema_version,
                policy.created_at,
                policy.created_by,
            ),
        )
        self.commit(self.connection)
        return policy

    def get_policy(
        self,
        *,
        binding_id: str,
        binding_version: int,
    ) -> GitLfsBindingPolicy | None:
        row = self.connection.execute(
            """
            SELECT * FROM git_lfs_binding_policies
            WHERE binding_id = ? AND binding_version = ?
            """,
            (binding_id, binding_version),
        ).fetchone()
        if row is None:
            return None
        rules = tuple(
            GitLfsPathRule(
                rule_id=item["rule_id"],
                pattern=item["pattern"],
                representation=GitLfsPathRepresentation(item["representation"]),
            )
            for item in json.loads(row["path_rules_json"])
        )
        return GitLfsBindingPolicy(
            binding_id=row["binding_id"],
            binding_version=int(row["binding_version"]),
            repository_id=row["repository_id"],
            lfs_service_id=row["lfs_service_id"],
            lfs_endpoint=row["lfs_endpoint"],
            object_format=row["object_format"],
            path_rules=rules,
            ordinary_blob_threshold_bytes=int(row["ordinary_blob_threshold_bytes"]),
            max_object_bytes=int(row["max_object_bytes"]),
            max_workspace_bytes=int(row["max_workspace_bytes"]),
            max_repository_bytes=int(row["max_repository_bytes"]),
            published_retention_class=GitLfsRetentionClass(
                row["published_retention_class"]
            ),
            private_retention_class=GitLfsRetentionClass(
                row["private_retention_class"]
            ),
            private_retention_seconds=int(row["private_retention_seconds"]),
            policy_version=row["policy_version"],
            policy_digest=row["policy_digest"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            schema_version=row["schema_version"],
        )

    def require_policy_for_claims(
        self,
        claims: RepositoryCredentialClaims,
    ) -> GitLfsBindingPolicy:
        policy = self.get_policy(
            binding_id=claims.binding_id,
            binding_version=claims.binding_version,
        )
        if (
            policy is None
            or policy.repository_id != claims.repository_id
        ):
            raise GitLfsPolicyError(
                "repository credential has no exact immutable Git LFS policy"
            )
        return policy

    def has_object_metadata(
        self,
        *,
        policy: GitLfsBindingPolicy,
        oid: str,
        size_bytes: int | None = None,
    ) -> bool:
        row = self.connection.execute(
            """
            SELECT size_bytes FROM git_lfs_object_records
            WHERE binding_id = ? AND binding_version = ? AND oid = ?
              AND deleted_at IS NULL
            """,
            (policy.binding_id, policy.binding_version, oid),
        ).fetchone()
        if row is None:
            return False
        if size_bytes is not None and int(row["size_bytes"]) != size_bytes:
            raise GitLfsRepositoryError(
                "Git LFS OID metadata disagrees with the declared object size"
            )
        return True

    def reserve_upload(
        self,
        *,
        policy: GitLfsBindingPolicy,
        claims: RepositoryCredentialClaims,
        oid: str,
        size_bytes: int,
        now: datetime,
    ) -> GitLfsUploadSession:
        if size_bytes > policy.max_object_bytes:
            raise GitLfsQuotaExceededError(
                scope="object",
                limit_bytes=policy.max_object_bytes,
                requested_bytes=size_bytes,
            )
        if self.has_object_metadata(policy=policy, oid=oid, size_bytes=size_bytes):
            raise GitLfsRepositoryError("identical Git LFS object is already committed")
        stable = canonical_lfs_digest(
            {
                "binding_id": policy.binding_id,
                "binding_version": policy.binding_version,
                "session_id": claims.session_id,
                "agent_member_id": claims.agent_member_id,
                "workspace_generation": claims.workspace_generation,
                "credential_id": claims.credential_id,
                "oid": oid,
                "size_bytes": size_bytes,
            }
        ).split(":", 1)[1]
        upload_session_id = f"lfs_upload_{stable[:32]}"
        existing = self.get_upload_session(upload_session_id)
        if existing is not None:
            if (
                existing.oid == oid
                and existing.declared_size == size_bytes
                and existing.status is GitLfsUploadStatus.RESERVED
            ):
                return existing
            raise GitLfsRepositoryError(
                "Git LFS upload-session identity is already terminal or drifted"
            )
        active_repository = int(
            self.connection.execute(
                """
                SELECT COALESCE(SUM(reserved_bytes), 0)
                FROM git_lfs_quota_reservations
                WHERE repository_id = ? AND state = 'reserved'
                  AND expires_at > ?
                """,
                (policy.repository_id, now.isoformat()),
            ).fetchone()[0]
        )
        retained_repository = int(
            self.connection.execute(
                """
                SELECT COALESCE(SUM(size_bytes), 0)
                FROM (
                    SELECT oid, MAX(size_bytes) AS size_bytes
                    FROM git_lfs_object_records
                    WHERE repository_id = ? AND deleted_at IS NULL
                    GROUP BY oid
                )
                """,
                (policy.repository_id,),
            ).fetchone()[0]
        )
        if retained_repository + active_repository + size_bytes > policy.max_repository_bytes:
            raise GitLfsQuotaExceededError(
                scope="repository",
                limit_bytes=policy.max_repository_bytes,
                requested_bytes=size_bytes,
            )
        active_workspace = int(
            self.connection.execute(
                """
                SELECT COALESCE(SUM(reserved_bytes), 0)
                FROM git_lfs_quota_reservations
                WHERE session_id = ? AND agent_member_id = ?
                  AND workspace_generation = ? AND state = 'reserved'
                  AND expires_at > ?
                """,
                (
                    claims.session_id,
                    claims.agent_member_id,
                    claims.workspace_generation,
                    now.isoformat(),
                ),
            ).fetchone()[0]
        )
        retained_workspace = int(
            self.connection.execute(
                """
                SELECT COALESCE(SUM(o.size_bytes), 0)
                FROM git_lfs_object_records o
                JOIN git_lfs_upload_sessions u
                  ON u.upload_session_id = o.first_upload_session_id
                WHERE u.session_id = ? AND u.agent_member_id = ?
                  AND u.workspace_generation = ?
                  AND o.deleted_at IS NULL
                """,
                (
                    claims.session_id,
                    claims.agent_member_id,
                    claims.workspace_generation,
                ),
            ).fetchone()[0]
        )
        if retained_workspace + active_workspace + size_bytes > policy.max_workspace_bytes:
            raise GitLfsQuotaExceededError(
                scope="workspace",
                limit_bytes=policy.max_workspace_bytes,
                requested_bytes=size_bytes,
            )
        created_at = now.astimezone(UTC).isoformat()
        expires_at = min(
            now + timedelta(minutes=15),
            datetime.fromisoformat(claims.expires_at),
        ).astimezone(UTC).isoformat()
        session = GitLfsUploadSession(
            upload_session_id=upload_session_id,
            binding_id=policy.binding_id,
            binding_version=policy.binding_version,
            repository_id=policy.repository_id,
            session_id=claims.session_id,
            agent_member_id=claims.agent_member_id,
            workspace_generation=claims.workspace_generation,
            credential_id=claims.credential_id,
            oid=oid,
            declared_size=size_bytes,
            reserved_bytes=size_bytes,
            status=GitLfsUploadStatus.RESERVED,
            created_at=created_at,
            expires_at=expires_at,
        )
        self.connection.execute(
            """
            INSERT INTO git_lfs_upload_sessions (
                upload_session_id, binding_id, binding_version, repository_id,
                session_id, agent_member_id, workspace_generation,
                credential_id, oid, declared_size, reserved_bytes, status,
                created_at, expires_at, completed_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, NULL, ?)
            """,
            (
                session.upload_session_id,
                session.binding_id,
                session.binding_version,
                session.repository_id,
                session.session_id,
                session.agent_member_id,
                session.workspace_generation,
                session.credential_id,
                session.oid,
                session.declared_size,
                session.reserved_bytes,
                session.created_at,
                session.expires_at,
                session.schema_version,
            ),
        )
        self.connection.execute(
            """
            INSERT INTO git_lfs_quota_reservations (
                reservation_id, upload_session_id, binding_id, binding_version,
                repository_id, session_id, agent_member_id,
                workspace_generation, oid, reserved_bytes, state,
                created_at, expires_at, settled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, NULL)
            """,
            (
                f"lfs_quota_{stable[:32]}",
                session.upload_session_id,
                session.binding_id,
                session.binding_version,
                session.repository_id,
                session.session_id,
                session.agent_member_id,
                session.workspace_generation,
                session.oid,
                session.reserved_bytes,
                session.created_at,
                session.expires_at,
            ),
        )
        self.commit(self.connection)
        return session

    def get_upload_session(self, upload_session_id: str) -> GitLfsUploadSession | None:
        row = self.connection.execute(
            "SELECT * FROM git_lfs_upload_sessions WHERE upload_session_id = ?",
            (upload_session_id,),
        ).fetchone()
        if row is None:
            return None
        return GitLfsUploadSession(
            upload_session_id=row["upload_session_id"],
            binding_id=row["binding_id"],
            binding_version=int(row["binding_version"]),
            repository_id=row["repository_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            workspace_generation=int(row["workspace_generation"]),
            credential_id=row["credential_id"],
            oid=row["oid"],
            declared_size=int(row["declared_size"]),
            reserved_bytes=int(row["reserved_bytes"]),
            status=GitLfsUploadStatus(row["status"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            completed_at=row["completed_at"],
            schema_version=row["schema_version"],
        )

    def commit_upload(
        self,
        *,
        upload_session: GitLfsUploadSession,
        completed_at: str,
    ) -> None:
        policy = self.get_policy(
            binding_id=upload_session.binding_id,
            binding_version=upload_session.binding_version,
        )
        if policy is None or policy.repository_id != upload_session.repository_id:
            raise GitLfsPolicyError("upload session has no exact LFS policy")
        retained_until = (
            datetime.fromisoformat(completed_at)
            + timedelta(seconds=policy.private_retention_seconds)
        ).astimezone(UTC).isoformat()
        receipt_digest = canonical_lfs_digest(
            {
                "upload_session_id": upload_session.upload_session_id,
                "binding_id": upload_session.binding_id,
                "binding_version": upload_session.binding_version,
                "repository_id": upload_session.repository_id,
                "oid": upload_session.oid,
                "size_bytes": upload_session.declared_size,
                "completed_at": completed_at,
            }
        )
        self.connection.execute(
            """
            INSERT INTO git_lfs_object_records (
                binding_id, binding_version, repository_id, oid, size_bytes,
                first_upload_session_id, retention_class, retained_until,
                object_receipt_digest, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'private', ?, ?, ?)
            ON CONFLICT(binding_id, binding_version, oid) DO NOTHING
            """,
            (
                upload_session.binding_id,
                upload_session.binding_version,
                upload_session.repository_id,
                upload_session.oid,
                upload_session.declared_size,
                upload_session.upload_session_id,
                retained_until,
                receipt_digest,
                completed_at,
            ),
        )
        row = self.connection.execute(
            """
            SELECT size_bytes FROM git_lfs_object_records
            WHERE binding_id = ? AND binding_version = ? AND oid = ?
              AND deleted_at IS NULL
            """,
            (
                upload_session.binding_id,
                upload_session.binding_version,
                upload_session.oid,
            ),
        ).fetchone()
        if row is None or int(row["size_bytes"]) != upload_session.declared_size:
            raise GitLfsRepositoryError("committed Git LFS object metadata drifted")
        self.connection.execute(
            """
            UPDATE git_lfs_upload_sessions
            SET status = 'committed', completed_at = ?
            WHERE upload_session_id = ? AND status = 'reserved'
            """,
            (completed_at, upload_session.upload_session_id),
        )
        self.connection.execute(
            """
            UPDATE git_lfs_quota_reservations
            SET state = 'committed', settled_at = ?
            WHERE upload_session_id = ? AND state = 'reserved'
            """,
            (completed_at, upload_session.upload_session_id),
        )
        self._link_workspace_object(
            binding_id=upload_session.binding_id,
            binding_version=upload_session.binding_version,
            repository_id=upload_session.repository_id,
            session_id=upload_session.session_id,
            agent_member_id=upload_session.agent_member_id,
            workspace_generation=upload_session.workspace_generation,
            credential_id=upload_session.credential_id,
            oid=upload_session.oid,
            observed_via="upload",
            created_at=completed_at,
        )
        self.commit(self.connection)

    def link_workspace_object(
        self,
        *,
        policy: GitLfsBindingPolicy,
        claims: RepositoryCredentialClaims,
        oid: str,
        observed_via: str,
        created_at: str,
    ) -> None:
        if (
            claims.binding_id != policy.binding_id
            or claims.binding_version != policy.binding_version
            or claims.repository_id != policy.repository_id
        ):
            raise GitLfsRepositoryError(
                "Git LFS workspace object link differs from credential scope"
            )
        self._link_workspace_object(
            binding_id=policy.binding_id,
            binding_version=policy.binding_version,
            repository_id=policy.repository_id,
            session_id=claims.session_id,
            agent_member_id=claims.agent_member_id,
            workspace_generation=claims.workspace_generation,
            credential_id=claims.credential_id,
            oid=oid,
            observed_via=observed_via,
            created_at=created_at,
        )
        self.commit(self.connection)

    def _link_workspace_object(
        self,
        *,
        binding_id: str,
        binding_version: int,
        repository_id: str,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
        credential_id: str,
        oid: str,
        observed_via: str,
        created_at: str,
    ) -> None:
        stable = canonical_lfs_digest(
            {
                "binding_id": binding_id,
                "binding_version": binding_version,
                "session_id": session_id,
                "agent_member_id": agent_member_id,
                "workspace_generation": workspace_generation,
                "oid": oid,
            }
        ).split(":", 1)[1]
        self.connection.execute(
            """
            INSERT INTO git_lfs_workspace_object_links (
                link_id, binding_id, binding_version, repository_id,
                session_id, agent_member_id, workspace_generation,
                credential_id, oid, observed_via, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                binding_id, binding_version, session_id, agent_member_id,
                workspace_generation, oid
            ) DO NOTHING
            """,
            (
                f"lfs_workspace_object_{stable[:32]}",
                binding_id,
                binding_version,
                repository_id,
                session_id,
                agent_member_id,
                workspace_generation,
                credential_id,
                oid,
                observed_via,
                created_at,
            ),
        )

    def abort_upload(
        self,
        *,
        upload_session_id: str,
        completed_at: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE git_lfs_upload_sessions
            SET status = 'aborted', completed_at = ?
            WHERE upload_session_id = ? AND status = 'reserved'
            """,
            (completed_at, upload_session_id),
        )
        self.connection.execute(
            """
            UPDATE git_lfs_quota_reservations
            SET state = 'released', settled_at = ?
            WHERE upload_session_id = ? AND state = 'reserved'
            """,
            (completed_at, upload_session_id),
        )
        self.commit(self.connection)

    def add_object_read_receipt(
        self,
        receipt: GitLfsObjectReadReceipt,
    ) -> GitLfsObjectReadReceipt:
        existing = self.get_object_read_receipt(receipt.receipt_id)
        if existing is not None:
            if existing == receipt:
                return existing
            raise GitLfsRepositoryError("object-read receipt identity conflict")
        self.connection.execute(
            """
            INSERT INTO git_lfs_object_read_receipts (
                receipt_id, binding_id, binding_version, repository_id,
                lfs_endpoint_identity, authorization_scope_digest, oid,
                declared_size, observed_size, observed_sha256, observed_at,
                receipt_digest, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.binding_id,
                receipt.binding_version,
                receipt.repository_id,
                receipt.lfs_endpoint_identity,
                receipt.authorization_scope_digest,
                receipt.oid,
                receipt.declared_size,
                receipt.observed_size,
                receipt.observed_sha256,
                receipt.observed_at,
                receipt.receipt_digest,
                receipt.schema_version,
            ),
        )
        self.commit(self.connection)
        return receipt

    def get_object_read_receipt(
        self,
        receipt_id: str,
    ) -> GitLfsObjectReadReceipt | None:
        row = self.connection.execute(
            "SELECT * FROM git_lfs_object_read_receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return GitLfsObjectReadReceipt(
            receipt_id=row["receipt_id"],
            binding_id=row["binding_id"],
            binding_version=int(row["binding_version"]),
            repository_id=row["repository_id"],
            lfs_endpoint_identity=row["lfs_endpoint_identity"],
            authorization_scope_digest=row["authorization_scope_digest"],
            oid=row["oid"],
            declared_size=int(row["declared_size"]),
            observed_size=int(row["observed_size"]),
            observed_sha256=row["observed_sha256"],
            observed_at=row["observed_at"],
            receipt_digest=row["receipt_digest"],
            schema_version=row["schema_version"],
        )

    def add_closure_manifest(
        self,
        manifest: GitLfsClosureManifest,
    ) -> GitLfsClosureManifest:
        existing = self.get_closure_manifest(manifest.manifest_digest)
        if existing is not None:
            if existing == manifest:
                return existing
            raise GitLfsRepositoryError("closure manifest digest identity conflict")
        self.connection.execute(
            """
            INSERT INTO git_lfs_closure_manifests (
                manifest_digest, binding_id, binding_version, repository_id,
                commit_id, tree_id, policy_digest, lfs_endpoint_identity,
                authorization_scope_digest, manifest_json, verified_at,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                manifest.manifest_digest,
                manifest.binding_id,
                manifest.binding_version,
                manifest.repository_id,
                manifest.commit,
                manifest.tree,
                manifest.policy_digest,
                manifest.lfs_endpoint_identity,
                manifest.authorization_scope_digest,
                json.dumps(manifest.payload, sort_keys=True, separators=(",", ":")),
                manifest.verified_at,
                manifest.schema_version,
            ),
        )
        for entry in manifest.entries:
            self.connection.execute(
                """
                INSERT INTO git_lfs_closure_entries (
                    manifest_digest, repository_path, file_mode,
                    pointer_blob_oid, lfs_oid, size_bytes,
                    object_read_receipt_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.manifest_digest,
                    entry.path,
                    entry.mode,
                    entry.pointer_blob_oid,
                    entry.lfs_oid,
                    entry.size_bytes,
                    entry.object_read_receipt_id,
                ),
            )
        self.commit(self.connection)
        return manifest

    def get_cached_closure(
        self,
        *,
        binding_id: str,
        binding_version: int,
        commit: str,
        tree: str,
        policy_digest: str,
        lfs_endpoint_identity: str,
        authorization_scope_digest: str,
    ) -> GitLfsClosureManifest | None:
        row = self.connection.execute(
            """
            SELECT manifest_digest FROM git_lfs_closure_manifests
            WHERE binding_id = ? AND binding_version = ? AND commit_id = ?
              AND tree_id = ? AND policy_digest = ?
              AND lfs_endpoint_identity = ? AND authorization_scope_digest = ?
            """,
            (
                binding_id,
                binding_version,
                commit,
                tree,
                policy_digest,
                lfs_endpoint_identity,
                authorization_scope_digest,
            ),
        ).fetchone()
        return None if row is None else self.get_closure_manifest(row["manifest_digest"])

    def get_closure_manifest(
        self,
        manifest_digest: str,
    ) -> GitLfsClosureManifest | None:
        row = self.connection.execute(
            "SELECT * FROM git_lfs_closure_manifests WHERE manifest_digest = ?",
            (manifest_digest,),
        ).fetchone()
        if row is None:
            return None
        entries = tuple(
            GitLfsClosureEntry(
                path=item["repository_path"],
                mode=item["file_mode"],
                pointer_blob_oid=item["pointer_blob_oid"],
                lfs_oid=item["lfs_oid"],
                size_bytes=int(item["size_bytes"]),
                object_read_receipt_id=item["object_read_receipt_id"],
            )
            for item in self.connection.execute(
                """
                SELECT * FROM git_lfs_closure_entries
                WHERE manifest_digest = ? ORDER BY repository_path
                """,
                (manifest_digest,),
            ).fetchall()
        )
        return GitLfsClosureManifest(
            binding_id=row["binding_id"],
            binding_version=int(row["binding_version"]),
            repository_id=row["repository_id"],
            commit=row["commit_id"],
            tree=row["tree_id"],
            policy_digest=row["policy_digest"],
            lfs_endpoint_identity=row["lfs_endpoint_identity"],
            authorization_scope_digest=row["authorization_scope_digest"],
            entries=entries,
            manifest_digest=row["manifest_digest"],
            verified_at=row["verified_at"],
            schema_version=row["schema_version"],
        )

    def add_closure_verification(
        self,
        verification: GitLfsClosureVerification,
        *,
        observed_closure: GitLfsClosureManifest,
    ) -> GitLfsClosureVerification:
        if (
            verification.manifest_digest != observed_closure.manifest_digest
            or verification.binding_id != observed_closure.binding_id
            or verification.binding_version != observed_closure.binding_version
            or verification.repository_id != observed_closure.repository_id
            or verification.authorization_scope_digest
            != observed_closure.authorization_scope_digest
            or set(verification.object_read_receipt_ids)
            != {entry.object_read_receipt_id for entry in observed_closure.entries}
        ):
            raise GitLfsRepositoryError(
                "closure verification differs from the fresh observed closure"
            )
        existing = self.get_closure_verification(verification.verification_id)
        if existing is not None:
            if existing == verification:
                return existing
            raise GitLfsRepositoryError("closure verification identity conflict")
        self.connection.execute(
            """
            INSERT INTO git_lfs_closure_verifications (
                verification_id, verification_digest, manifest_digest,
                binding_id, binding_version, repository_id,
                authorization_scope_digest, object_read_receipt_ids_json,
                observed_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                verification.verification_id,
                verification.verification_digest,
                verification.manifest_digest,
                verification.binding_id,
                verification.binding_version,
                verification.repository_id,
                verification.authorization_scope_digest,
                json.dumps(
                    list(verification.object_read_receipt_ids),
                    separators=(",", ":"),
                ),
                verification.observed_at,
                verification.schema_version,
            ),
        )
        for entry in observed_closure.entries:
            self.connection.execute(
                """
                INSERT INTO git_lfs_closure_verification_entries (
                    verification_id, manifest_digest, repository_path,
                    object_read_receipt_id
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    verification.verification_id,
                    verification.manifest_digest,
                    entry.path,
                    entry.object_read_receipt_id,
                ),
            )
        self.commit(self.connection)
        return verification

    def get_closure_verification(
        self,
        verification_id: str,
    ) -> GitLfsClosureVerification | None:
        row = self.connection.execute(
            """
            SELECT * FROM git_lfs_closure_verifications
            WHERE verification_id = ?
            """,
            (verification_id,),
        ).fetchone()
        if row is None:
            return None
        raw_ids = json.loads(row["object_read_receipt_ids_json"])
        if not isinstance(raw_ids, list):
            raise GitLfsRepositoryError(
                "closure verification receipt list is invalid"
            )
        return GitLfsClosureVerification(
            verification_id=row["verification_id"],
            verification_digest=row["verification_digest"],
            manifest_digest=row["manifest_digest"],
            binding_id=row["binding_id"],
            binding_version=int(row["binding_version"]),
            repository_id=row["repository_id"],
            authorization_scope_digest=row["authorization_scope_digest"],
            object_read_receipt_ids=tuple(str(value) for value in raw_ids),
            observed_at=row["observed_at"],
            schema_version=row["schema_version"],
        )

    def link_publication_intent_proof(
        self,
        *,
        intent_id: str,
        publication_id: str,
        closure: GitLfsClosureManifest,
        verification: GitLfsClosureVerification,
        created_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO git_lfs_publication_intent_proofs (
                intent_id, publication_id, manifest_digest,
                verification_id, verification_digest, binding_id,
                binding_version, repository_id, commit_id, tree_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(intent_id) DO NOTHING
            """,
            (
                intent_id,
                publication_id,
                closure.manifest_digest,
                verification.verification_id,
                verification.verification_digest,
                closure.binding_id,
                closure.binding_version,
                closure.repository_id,
                closure.commit,
                closure.tree,
                created_at,
            ),
        )
        proof = self.get_publication_intent_proof(intent_id)
        if (
            proof is None
            or proof["manifest_digest"] != closure.manifest_digest
            or proof["verification_id"] != verification.verification_id
            or proof["verification_digest"] != verification.verification_digest
        ):
            raise GitLfsRepositoryError(
                "publication intent already owns another Git LFS proof"
            )
        self.commit(self.connection)

    def get_publication_intent_proof(
        self,
        intent_id: str,
    ) -> dict[str, object] | None:
        row = self.connection.execute(
            """
            SELECT * FROM git_lfs_publication_intent_proofs
            WHERE intent_id = ?
            """,
            (intent_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def pin_publication(
        self,
        *,
        publication_id: str,
        closure: GitLfsClosureManifest,
        verification: GitLfsClosureVerification,
        pinned_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO git_lfs_publication_closures (
                publication_id, manifest_digest, verification_id,
                verification_digest, binding_id, binding_version,
                repository_id, pinned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(publication_id) DO NOTHING
            """,
            (
                publication_id,
                closure.manifest_digest,
                verification.verification_id,
                verification.verification_digest,
                closure.binding_id,
                closure.binding_version,
                closure.repository_id,
                pinned_at,
            ),
        )
        linked = self.connection.execute(
            """
            SELECT manifest_digest, verification_id, verification_digest
            FROM git_lfs_publication_closures
            WHERE publication_id = ?
            """,
            (publication_id,),
        ).fetchone()
        if (
            linked is None
            or linked["manifest_digest"] != closure.manifest_digest
            or linked["verification_id"] != verification.verification_id
            or linked["verification_digest"] != verification.verification_digest
        ):
            raise GitLfsRepositoryError(
                "published revision is already linked to another Git LFS closure"
            )
        for entry in closure.entries:
            self.connection.execute(
                """
                INSERT INTO git_lfs_publication_pins (
                    publication_id, manifest_digest, binding_id,
                    binding_version, repository_id, lfs_oid,
                    size_bytes, pinned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(publication_id, lfs_oid) DO NOTHING
                """,
                (
                    publication_id,
                    closure.manifest_digest,
                    closure.binding_id,
                    closure.binding_version,
                    closure.repository_id,
                    entry.lfs_oid,
                    entry.size_bytes,
                    pinned_at,
                ),
            )
            self.connection.execute(
                """
                UPDATE git_lfs_object_records
                SET retention_class = 'published', retained_until = NULL
                WHERE binding_id = ? AND binding_version = ? AND oid = ?
                  AND retention_class = 'private'
                """,
                (closure.binding_id, closure.binding_version, entry.lfs_oid),
            )
        self.commit(self.connection)

    def publication_closure_projection(
        self,
        publication_id: str,
    ) -> dict[str, object] | None:
        row = self.connection.execute(
            """
            SELECT c.manifest_digest, c.verification_id,
                   c.verification_digest, COUNT(p.lfs_oid) AS object_count,
                   COALESCE(SUM(p.size_bytes), 0) AS total_size_bytes
            FROM git_lfs_publication_closures c
            LEFT JOIN git_lfs_publication_pins p
              ON p.publication_id = c.publication_id
             AND p.manifest_digest = c.manifest_digest
            WHERE c.publication_id = ?
            GROUP BY c.manifest_digest
            """,
            (publication_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "manifest_digest": row["manifest_digest"],
            "verification_id": row["verification_id"],
            "verification_digest": row["verification_digest"],
            "object_count": int(row["object_count"]),
            "total_size_bytes": int(row["total_size_bytes"]),
            "retention_class": "published",
        }

    def private_namespace_retirement_scope(
        self,
        namespace_id: str,
    ) -> dict[str, object]:
        row = self.connection.execute(
            """
            SELECT n.namespace_id, n.binding_id, n.binding_version,
                   n.session_id, n.agent_member_id, n.workspace_generation,
                   n.status, r.receipt_id AS retirement_receipt_id,
                   r.terminal_refs_json, r.terminal_commits_json,
                   r.receipt_digest AS retirement_receipt_digest,
                   p.repository_id
            FROM repository_private_namespace_records n
            JOIN repository_private_namespace_retirement_receipts r
              ON r.namespace_id = n.namespace_id
            JOIN git_lfs_binding_policies p
              ON p.binding_id = n.binding_id
             AND p.binding_version = n.binding_version
            WHERE n.namespace_id = ?
            """,
            (namespace_id,),
        ).fetchone()
        if row is None or row["status"] not in {"closed", "retired"}:
            raise GitLfsRepositoryError(
                "private LFS reachability requires an exact retirement receipt"
            )
        terminal_refs = json.loads(row["terminal_refs_json"])
        terminal_commits = json.loads(row["terminal_commits_json"])
        if (
            not isinstance(terminal_refs, dict)
            or set(terminal_refs) != {"items"}
            or not isinstance(terminal_refs["items"], list)
            or not isinstance(terminal_commits, dict)
            or set(terminal_commits) != {"items"}
            or not isinstance(terminal_commits["items"], list)
        ):
            raise GitLfsRepositoryError(
                "private namespace retirement receipt has invalid terminal facts"
            )
        return {
            "namespace_id": row["namespace_id"],
            "binding_id": row["binding_id"],
            "binding_version": int(row["binding_version"]),
            "repository_id": row["repository_id"],
            "session_id": row["session_id"],
            "agent_member_id": row["agent_member_id"],
            "workspace_generation": int(row["workspace_generation"]),
            "retirement_receipt_id": row["retirement_receipt_id"],
            "retirement_receipt_digest": row["retirement_receipt_digest"],
            "terminal_refs": terminal_refs["items"],
            "terminal_commits": terminal_commits["items"],
        }

    def add_private_reachability_receipt(
        self,
        receipt: GitLfsPrivateReachabilityReceipt,
    ) -> GitLfsPrivateReachabilityReceipt:
        existing = self.get_private_reachability_receipt(receipt.namespace_id)
        if existing is not None:
            if existing == receipt:
                return existing
            raise GitLfsRepositoryError(
                "private namespace already owns another reachability receipt"
            )
        self.connection.execute(
            """
            INSERT INTO git_lfs_private_reachability_receipts (
                receipt_id, binding_id, binding_version, repository_id,
                namespace_id, workspace_generation, terminal_refs_digest,
                terminal_commits_digest, reachable_oids_json,
                reachability_digest, retirement_receipt_id, created_at,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.binding_id,
                receipt.binding_version,
                receipt.repository_id,
                receipt.namespace_id,
                receipt.workspace_generation,
                receipt.terminal_refs_digest,
                receipt.terminal_commits_digest,
                json.dumps(list(receipt.reachable_oids), separators=(",", ":")),
                receipt.reachability_digest,
                receipt.retirement_receipt_id,
                receipt.created_at,
                receipt.schema_version,
            ),
        )
        self.commit(self.connection)
        return receipt

    def get_private_reachability_receipt(
        self,
        namespace_id: str,
    ) -> GitLfsPrivateReachabilityReceipt | None:
        row = self.connection.execute(
            """
            SELECT * FROM git_lfs_private_reachability_receipts
            WHERE namespace_id = ?
            """,
            (namespace_id,),
        ).fetchone()
        if row is None:
            return None
        raw_oids = json.loads(row["reachable_oids_json"])
        if not isinstance(raw_oids, list):
            raise GitLfsRepositoryError("private reachable OID payload is invalid")
        return GitLfsPrivateReachabilityReceipt(
            receipt_id=row["receipt_id"],
            binding_id=row["binding_id"],
            binding_version=int(row["binding_version"]),
            repository_id=row["repository_id"],
            namespace_id=row["namespace_id"],
            workspace_generation=int(row["workspace_generation"]),
            terminal_refs_digest=row["terminal_refs_digest"],
            terminal_commits_digest=row["terminal_commits_digest"],
            reachable_oids=tuple(str(oid) for oid in raw_oids),
            retirement_receipt_id=row["retirement_receipt_id"],
            created_at=row["created_at"],
            reachability_digest=row["reachability_digest"],
            schema_version=row["schema_version"],
        )

    def compute_gc_candidate(
        self,
        *,
        policy: GitLfsBindingPolicy,
        receipt_id: str,
        created_at: str,
    ) -> GitLfsGcCandidateReceipt:
        namespace_rows = self.connection.execute(
            """
            SELECT n.namespace_id, n.status, n.workspace_generation,
                   r.receipt_id AS retirement_receipt_id,
                   r.receipt_digest AS retirement_receipt_digest,
                   lr.receipt_id AS lfs_reachability_receipt_id,
                   lr.reachability_digest AS lfs_reachability_digest
            FROM repository_private_namespace_records n
            JOIN git_lfs_binding_policies policy
              ON policy.binding_id = n.binding_id
             AND policy.binding_version = n.binding_version
            LEFT JOIN repository_private_namespace_retirement_receipts r
              ON r.namespace_id = n.namespace_id
            LEFT JOIN git_lfs_private_reachability_receipts lr
              ON lr.namespace_id = n.namespace_id
            WHERE policy.repository_id = ?
            ORDER BY n.namespace_id
            """,
            (policy.repository_id,),
        ).fetchall()
        reachability_rows = self.connection.execute(
            """
            SELECT publication_id, binding_id, binding_version, lfs_oid
            FROM git_lfs_publication_pins
            WHERE repository_id = ?
            ORDER BY publication_id, lfs_oid
            """,
            (policy.repository_id,),
        ).fetchall()
        upload_rows = self.connection.execute(
            """
            SELECT upload_session_id, binding_id, binding_version, oid,
                   status, expires_at
            FROM git_lfs_upload_sessions
            WHERE repository_id = ?
            ORDER BY upload_session_id
            """,
            (policy.repository_id,),
        ).fetchall()
        workspace_link_rows = self.connection.execute(
            """
            SELECT link_id, binding_id, binding_version, session_id,
                   agent_member_id, workspace_generation, oid
            FROM git_lfs_workspace_object_links
            WHERE repository_id = ?
            ORDER BY link_id
            """,
            (policy.repository_id,),
        ).fetchall()
        reachability_digest = canonical_lfs_digest(
            {
                "publication_pins": [dict(row) for row in reachability_rows],
                "upload_sessions": [dict(row) for row in upload_rows],
                "workspace_object_links": [
                    dict(row) for row in workspace_link_rows
                ],
                "private_namespaces": [
                    {
                        "namespace_id": row["namespace_id"],
                        "status": row["status"],
                        "workspace_generation": row["workspace_generation"],
                        "retirement_receipt_id": row["retirement_receipt_id"],
                        "lfs_reachability_receipt_id": row[
                            "lfs_reachability_receipt_id"
                        ],
                    }
                    for row in namespace_rows
                ],
            }
        )
        retirement_receipts_digest = canonical_lfs_digest(
            {
                "retirement_receipts": [
                    {
                        "namespace_id": row["namespace_id"],
                        "receipt_id": row["retirement_receipt_id"],
                        "receipt_digest": row["retirement_receipt_digest"],
                        "lfs_reachability_digest": row[
                            "lfs_reachability_digest"
                        ],
                    }
                    for row in namespace_rows
                    if row["retirement_receipt_id"] is not None
                ]
            }
        )
        candidates = tuple(
            row["oid"]
            for row in self.connection.execute(
                """
                SELECT o.oid
                FROM git_lfs_object_records o
                WHERE o.binding_id = ? AND o.binding_version = ?
                  AND o.repository_id = ?
                  AND o.retention_class = 'private'
                  AND o.deleted_at IS NULL
                  AND o.retained_until IS NOT NULL
                  AND o.retained_until <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM git_lfs_publication_pins p
                      WHERE p.repository_id = o.repository_id
                        AND p.lfs_oid = o.oid
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM git_lfs_upload_sessions active
                      WHERE active.repository_id = o.repository_id
                        AND active.oid = o.oid
                        AND active.status = 'reserved'
                        AND active.expires_at > ?
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM git_lfs_object_records other
                      WHERE other.repository_id = o.repository_id
                        AND other.oid = o.oid
                        AND other.deleted_at IS NULL
                        AND (
                            other.retention_class <> 'private'
                            OR other.retained_until IS NULL
                            OR other.retained_until > ?
                        )
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM git_lfs_workspace_object_links link
                      WHERE link.repository_id = o.repository_id
                        AND link.oid = o.oid
                        AND NOT EXISTS (
                            SELECT 1
                            FROM repository_private_namespace_records n
                            JOIN repository_private_namespace_retirement_receipts r
                              ON r.namespace_id = n.namespace_id
                            JOIN git_lfs_private_reachability_receipts lr
                              ON lr.namespace_id = n.namespace_id
                             AND lr.retirement_receipt_id = r.receipt_id
                            WHERE n.binding_id = link.binding_id
                              AND n.binding_version = link.binding_version
                              AND n.session_id = link.session_id
                              AND n.agent_member_id = link.agent_member_id
                              AND n.workspace_generation = link.workspace_generation
                              AND n.status = 'retired'
                        )
                  )
                ORDER BY o.oid
                """,
                (
                    policy.binding_id,
                    policy.binding_version,
                    policy.repository_id,
                    created_at,
                    created_at,
                    created_at,
                ),
            ).fetchall()
        )
        return GitLfsGcCandidateReceipt.create(
            receipt_id=receipt_id,
            binding_id=policy.binding_id,
            binding_version=policy.binding_version,
            repository_id=policy.repository_id,
            policy_digest=policy.policy_digest,
            reachability_digest=reachability_digest,
            retirement_receipts_digest=retirement_receipts_digest,
            candidate_oids=candidates,
            created_at=created_at,
        )

    def add_gc_candidate(
        self,
        receipt: GitLfsGcCandidateReceipt,
    ) -> GitLfsGcCandidateReceipt:
        existing = self.get_gc_candidate(receipt.receipt_id)
        if existing is not None:
            if existing == receipt:
                return existing
            raise GitLfsRepositoryError("GC candidate receipt identity conflict")
        self.connection.execute(
            """
            INSERT INTO git_lfs_gc_candidate_receipts (
                receipt_id, binding_id, binding_version, repository_id,
                policy_digest, reachability_digest,
                retirement_receipts_digest, dry_run, created_at,
                receipt_digest, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.binding_id,
                receipt.binding_version,
                receipt.repository_id,
                receipt.policy_digest,
                receipt.reachability_digest,
                receipt.retirement_receipts_digest,
                receipt.created_at,
                receipt.receipt_digest,
                receipt.schema_version,
            ),
        )
        for oid in receipt.candidate_oids:
            self.connection.execute(
                """
                INSERT INTO git_lfs_gc_candidate_items (receipt_id, oid)
                VALUES (?, ?)
                """,
                (receipt.receipt_id, oid),
            )
        self.commit(self.connection)
        return receipt

    def get_gc_candidate(
        self,
        receipt_id: str,
    ) -> GitLfsGcCandidateReceipt | None:
        row = self.connection.execute(
            "SELECT * FROM git_lfs_gc_candidate_receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        oids = tuple(
            item["oid"]
            for item in self.connection.execute(
                """
                SELECT oid FROM git_lfs_gc_candidate_items
                WHERE receipt_id = ? ORDER BY oid
                """,
                (receipt_id,),
            ).fetchall()
        )
        return GitLfsGcCandidateReceipt(
            receipt_id=row["receipt_id"],
            binding_id=row["binding_id"],
            binding_version=int(row["binding_version"]),
            repository_id=row["repository_id"],
            policy_digest=row["policy_digest"],
            reachability_digest=row["reachability_digest"],
            retirement_receipts_digest=row["retirement_receipts_digest"],
            candidate_oids=oids,
            dry_run=bool(row["dry_run"]),
            created_at=row["created_at"],
            receipt_digest=row["receipt_digest"],
            schema_version=row["schema_version"],
        )

    def object_size_for_gc(
        self,
        *,
        binding_id: str,
        binding_version: int,
        oid: str,
    ) -> int:
        row = self.connection.execute(
            """
            SELECT MIN(size_bytes) AS min_size, MAX(size_bytes) AS max_size
            FROM git_lfs_object_records
            WHERE binding_id = ? AND binding_version = ? AND oid = ?
              AND retention_class = 'private' AND deleted_at IS NULL
            """,
            (binding_id, binding_version, oid),
        ).fetchone()
        if row is None or row["min_size"] is None or row["min_size"] != row["max_size"]:
            raise GitLfsRepositoryError("GC candidate object is no longer deletable")
        return int(row["min_size"])

    def record_gc_deletion(
        self,
        *,
        candidate: GitLfsGcCandidateReceipt,
        deletion_receipt_id: str,
        exact_revalidation_digest: str,
        deleted_at: str,
        created_by: str,
    ) -> str:
        deleted_oids = list(candidate.candidate_oids)
        receipt_digest = canonical_lfs_digest(
            {
                "deletion_receipt_id": deletion_receipt_id,
                "candidate_receipt_id": candidate.receipt_id,
                "candidate_receipt_digest": candidate.receipt_digest,
                "exact_revalidation_digest": exact_revalidation_digest,
                "deleted_oids": deleted_oids,
                "created_at": deleted_at,
                "created_by": created_by,
            }
        )
        self.connection.execute(
            """
            INSERT INTO git_lfs_gc_deletion_receipts (
                deletion_receipt_id, candidate_receipt_id,
                exact_revalidation_digest, deleted_oids_json,
                created_at, created_by, receipt_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deletion_receipt_id,
                candidate.receipt_id,
                exact_revalidation_digest,
                json.dumps(deleted_oids, separators=(",", ":")),
                deleted_at,
                created_by,
                receipt_digest,
            ),
        )
        for oid in candidate.candidate_oids:
            cursor = self.connection.execute(
                """
                UPDATE git_lfs_object_records
                SET deleted_at = ?, deletion_receipt_id = ?
                WHERE repository_id = ? AND oid = ?
                  AND retention_class = 'private' AND deleted_at IS NULL
                """,
                (
                    deleted_at,
                    deletion_receipt_id,
                    candidate.repository_id,
                    oid,
                ),
            )
            if cursor.rowcount < 1:
                raise GitLfsRepositoryError(
                    "GC candidate object changed before deletion receipt"
                )
        self.commit(self.connection)
        return receipt_digest


__all__ = [
    "GitLfsPolicyError",
    "GitLfsQuotaExceededError",
    "GitLfsRepository",
    "GitLfsRepositoryError",
]
