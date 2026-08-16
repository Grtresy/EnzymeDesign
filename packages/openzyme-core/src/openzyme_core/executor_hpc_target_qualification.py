from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Protocol

from openzyme_domain import ExecutorHpcTargetQualification

from .repositories import CoreRepositories


_POSITIVE_SCENARIOS = frozenset(
    {
        "ssh_login",
        "git",
        "git_lfs",
        "rsync",
        "scp",
        "file_create",
        "file_read",
        "file_update",
        "file_delete",
        "private_ref_push_fetch",
        "published_ref_fetch",
        "git_lfs_actual_bytes",
    }
)
_NEGATIVE_SCENARIOS = frozenset(
    {
        "cross_executor",
        "cross_generation",
        "cross_target_replay",
        "parent_traversal",
        "absolute_path_substitution",
        "symlink_escape",
        "hardlink_escape",
        "rsync_destination_escape",
        "scp_destination_escape",
        "runner_sidecar_access",
        "revoked_credential",
        "scheduler_submit_absent",
        "private_ref_cross_owner_denied",
        "published_ref_force_update_denied",
        "published_ref_delete_denied",
    }
)


class ExecutorHpcTargetQualificationError(RuntimeError):
    error_code = "executor_hpc_target_qualification_rejected"


class ExecutorHpcNativeQualificationEvidenceVerifier(Protocol):
    def verify(
        self,
        evidence: "ExecutorHpcNativeQualificationEvidence",
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ExecutorHpcNativeQualificationEvidence:
    target_profile_id: str
    target_profile_digest: str
    credential_provider_id: str
    authenticator_id: str
    os_principal_policy_id: str
    root_policy_digest: str
    login_alias: str
    workspace_root: str
    sidecar_root_digest: str
    toolchain_digest: str
    positive_receipt_digest: str
    negative_receipt_digest: str
    positive_scenarios: tuple[str, ...]
    negative_scenarios: tuple[str, ...]
    execution_mode: str
    mocked: bool
    verified_at: str
    evidence_digest: str
    schema_version: str = "executor_hpc_native_qualification_evidence@1"

    def __post_init__(self) -> None:
        if self.schema_version != "executor_hpc_native_qualification_evidence@1":
            raise ValueError("unsupported native qualification evidence schema")
        if self.execution_mode != "native_target_ssh" or self.mocked:
            raise ValueError("target qualification evidence must be real native SSH")
        for name in (
            "target_profile_id",
            "credential_provider_id",
            "authenticator_id",
            "os_principal_policy_id",
        ):
            if re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}",
                getattr(self, name),
            ) is None:
                raise ValueError(f"{name} is not a safe identity")
        for name in (
            "target_profile_digest",
            "root_policy_digest",
            "sidecar_root_digest",
            "toolchain_digest",
            "positive_receipt_digest",
            "negative_receipt_digest",
        ):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", getattr(self, name)) is None:
                raise ValueError(f"{name} is not a sha256 digest")
        if any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in (self.login_alias, self.workspace_root)
        ):
            raise ValueError("native login alias and workspace root must be exact")
        try:
            verified = datetime.fromisoformat(self.verified_at)
        except ValueError as exc:
            raise ValueError("verified_at is not ISO-8601") from exc
        if verified.tzinfo is None or verified.utcoffset() is None:
            raise ValueError("verified_at must include an explicit timezone")
        if (
            len(self.positive_scenarios) != len(set(self.positive_scenarios))
            or set(self.positive_scenarios) != _POSITIVE_SCENARIOS
        ):
            raise ValueError("native positive qualification scenarios are incomplete")
        if (
            len(self.negative_scenarios) != len(set(self.negative_scenarios))
            or set(self.negative_scenarios) != _NEGATIVE_SCENARIOS
        ):
            raise ValueError("native negative qualification scenarios are incomplete")
        if self.evidence_digest != _digest(self.payload):
            raise ValueError("native qualification evidence digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_profile_id": self.target_profile_id,
            "target_profile_digest": self.target_profile_digest,
            "credential_provider_id": self.credential_provider_id,
            "authenticator_id": self.authenticator_id,
            "os_principal_policy_id": self.os_principal_policy_id,
            "root_policy_digest": self.root_policy_digest,
            "login_alias": self.login_alias,
            "workspace_root": self.workspace_root,
            "sidecar_root_digest": self.sidecar_root_digest,
            "toolchain_digest": self.toolchain_digest,
            "positive_receipt_digest": self.positive_receipt_digest,
            "negative_receipt_digest": self.negative_receipt_digest,
            "positive_scenarios": list(self.positive_scenarios),
            "negative_scenarios": list(self.negative_scenarios),
            "execution_mode": self.execution_mode,
            "mocked": self.mocked,
            "verified_at": self.verified_at,
        }

    @classmethod
    def create(cls, **values: object) -> "ExecutorHpcNativeQualificationEvidence":
        payload = {
            "schema_version": "executor_hpc_native_qualification_evidence@1",
            **{
                key: list(value) if isinstance(value, tuple) else value
                for key, value in values.items()
            },
        }
        return cls(**values, evidence_digest=_digest(payload))


@dataclass(slots=True)
class ExecutorHpcTargetQualificationService:
    repositories: CoreRepositories
    evidence_verifier: ExecutorHpcNativeQualificationEvidenceVerifier | None = None

    def record_native_qualification(
        self,
        qualification: ExecutorHpcTargetQualification,
        *,
        evidence: ExecutorHpcNativeQualificationEvidence,
    ) -> ExecutorHpcTargetQualification:
        if self.evidence_verifier is None:
            raise ExecutorHpcTargetQualificationError(
                "native target evidence verifier is unavailable"
            )
        verified_evidence_digest = self.evidence_verifier.verify(evidence)
        if verified_evidence_digest != evidence.evidence_digest:
            raise ExecutorHpcTargetQualificationError(
                "native target verifier did not bind the exact evidence"
            )
        if (
            not qualification.activated
            or qualification.target_profile_id != evidence.target_profile_id
            or qualification.target_profile_digest
            != evidence.target_profile_digest
            or qualification.credential_provider_id
            != evidence.credential_provider_id
            or qualification.authenticator_id != evidence.authenticator_id
            or qualification.os_principal_policy_id
            != evidence.os_principal_policy_id
            or qualification.login_alias != evidence.login_alias
            or qualification.workspace_root != evidence.workspace_root
            or qualification.sidecar_root_digest
            != evidence.sidecar_root_digest
            or qualification.toolchain_digest != evidence.toolchain_digest
            or qualification.root_policy_digest != evidence.root_policy_digest
            or qualification.native_positive_proof_digest
            != evidence.positive_receipt_digest
            or qualification.native_negative_proof_digest
            != evidence.negative_receipt_digest
            or qualification.qualified_at != evidence.verified_at
        ):
            raise ExecutorHpcTargetQualificationError(
                "target qualification differs from native evidence"
            )
        return self.repositories.executor_hpc_workspaces.add_target_qualification(
            qualification
        )


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ExecutorHpcNativeQualificationEvidence",
    "ExecutorHpcNativeQualificationEvidenceVerifier",
    "ExecutorHpcTargetQualificationError",
    "ExecutorHpcTargetQualificationService",
]
