from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Protocol

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalBoundQualificationOperationPort
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalIdentityPreparationAction
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
from openzyme_contracts import ExternalIdentityPreparationPlan
from openzyme_contracts import ExternalIdentityPreparationResult
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import create_external_identity_preparation_success


GIT_LFS_QUALIFICATION_OPERATIONS = (
    "checkpoint",
    "clone",
    "lfs-fetch",
    "publish",
    "response-loss-reconcile",
)


class LocalGitLfsPreparationCommandPort(Protocol):
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]: ...


@dataclass(frozen=True, slots=True)
class SubprocessLocalGitLfsPreparationCommandPort:
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
        return completed.returncode, completed.stdout, completed.stderr


@dataclass(frozen=True, slots=True)
class LocalIsolatedGitLfsPreparationExecutor:
    repository_root: Path = field(repr=False)
    command_port: LocalGitLfsPreparationCommandPort = field(repr=False)

    def __post_init__(self) -> None:
        root = self.repository_root.absolute()
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("local Git/LFS qualification root must be absolute and direct")
        if root.exists():
            metadata = root.stat()
            if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise ExternalQualificationError(
                    "qualification_git_root_permissions_unsafe",
                    "local Git/LFS qualification root must be owner-only",
                )
        object.__setattr__(self, "repository_root", root)

    def __call__(
        self,
        *,
        plan: ExternalIdentityPreparationPlan,
        authorization: ExternalIdentityPreparationOccurrenceAuthorization,
        action: ExternalIdentityPreparationAction,
        occurrence_id: str,
        request_digest: str,
        credential_material: object | None,
    ) -> ExternalIdentityPreparationResult:
        if (
            action.owner_component_id != "openzyme.workspace.git.lfs"
            or action.effect_id != "git-lfs.local-isolated-repository.create"
            or action.credential_locator_id is not None
            or credential_material is not None
        ):
            raise ExternalQualificationError(
                "qualification_git_preparation_binding_mismatch",
                "local Git/LFS preparation differs from the exact planned action",
            )
        self.repository_root.mkdir(mode=0o700, parents=False, exist_ok=True)
        repository = self.repository_root / occurrence_id
        if repository.exists() or repository.is_symlink():
            raise ExternalQualificationError(
                "qualification_git_occurrence_already_exists",
                "local Git/LFS preparation occurrence already has a repository",
            )
        repository.mkdir(mode=0o700)
        marker = repository / ".openzyme-qualification-owner"
        marker.write_text(occurrence_id, encoding="utf-8")
        marker.chmod(0o600)
        commands = (
            ("git", "init", "--bare", str(repository)),
            ("git", "--git-dir", str(repository), "lfs", "install", "--local"),
        )
        for argv in commands:
            returncode, _stdout, _stderr = self.command_port.run(argv)
            if returncode != 0:
                raise ExternalQualificationError(
                    "qualification_git_local_repository_create_failed",
                    "local Git/LFS qualification repository creation failed",
                )
        repository_identity = canonical_sha256_digest(
            {
                "occurrence_id": occurrence_id,
                "plan_digest": plan.preparation_plan_digest,
                "repository_kind": "local-bare",
                "hosted_sync_allowed": False,
            }
        )
        fields = tuple(
            sorted(
                (
                    SafeIdentityField(
                        "local_repository_endpoint",
                        f"local-git-lfs.qualification.{repository_identity[7:23]}",
                    ),
                    SafeIdentityField(
                        "local_lfs_endpoint_identity",
                        canonical_sha256_digest(
                            {"repository_identity": repository_identity, "lfs": "local"}
                        ),
                    ),
                    SafeIdentityField(
                        "repository_policy_digest",
                        canonical_sha256_digest(
                            {
                                "bare": True,
                                "local_only": True,
                                "hosted_sync_allowed": False,
                                "payload_hard_limit_mib": 10,
                            }
                        ),
                    ),
                    SafeIdentityField(
                        "local_process_scope_digest",
                        canonical_sha256_digest(
                            {
                                "owner_uid": os.getuid(),
                                "root_mode": "0700",
                                "repository_mode": "0700",
                            }
                        ),
                    ),
                ),
                key=lambda item: item.field_id,
            )
        )
        return create_external_identity_preparation_success(
            occurrence_id=occurrence_id,
            preparation_plan_digest=plan.preparation_plan_digest,
            authorization_digest=authorization.authorization_digest,
            action_id=action.action_id,
            owner_component_id=action.owner_component_id,
            effect_id=action.effect_id,
            input_binding_digest=action.input_binding_digest,
            request_digest=request_digest,
            safe_identity_fields=fields,
            receipt_payload={
                "schema_version": "local_git_lfs_preparation_receipt@1",
                "occurrence_id": occurrence_id,
                "repository_identity": repository_identity,
                "commands": ["git-init-bare", "git-lfs-install-local"],
                "hosted_sync_allowed": False,
            },
            external_effect_performed=True,
            credential_material_accessed=False,
        )

    def cleanup(self, occurrence_id: str) -> None:
        repository = self.repository_root / occurrence_id
        if repository.parent != self.repository_root or repository.is_symlink():
            raise ExternalQualificationError(
                "qualification_git_cleanup_target_invalid",
                "local Git/LFS cleanup target is outside the protected root",
            )
        marker = repository / ".openzyme-qualification-owner"
        if not marker.is_file() or marker.read_text(encoding="utf-8") != occurrence_id:
            raise ExternalQualificationError(
                "qualification_git_cleanup_ownership_unproven",
                "local Git/LFS cleanup requires the exact occurrence marker",
            )
        shutil.rmtree(repository)


class GitLfsQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    local_only: bool
    hosted_sync_allowed: bool


@dataclass(slots=True)
class GitLfsQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: GitLfsQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.workspace.git.lfs":
            raise ValueError("Git/LFS bridge requires the selected Adapter binding")
        if (
            self.operation_port.component_id != self.binding.component_id
            or self.operation_port.route_id != self.binding.route_id
            or self.operation_port.subject_digest != self.binding.subject_digest
            or not self.operation_port.local_only
            or self.operation_port.hosted_sync_allowed
        ):
            raise ValueError(
                "Git/LFS qualification port must bind the exact local-only subject"
            )
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=GIT_LFS_QUALIFICATION_OPERATIONS,
        )

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.dispatch(request)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.reconcile(request)


__all__ = [
    "GIT_LFS_QUALIFICATION_OPERATIONS",
    "GitLfsQualificationOperationPort",
    "GitLfsQualificationProbeBridge",
    "LocalGitLfsPreparationCommandPort",
    "LocalIsolatedGitLfsPreparationExecutor",
    "SubprocessLocalGitLfsPreparationCommandPort",
]
