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
from openzyme_contracts import ExternalQualificationOperationObservation
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


class LocalGitLfsQualificationCommandPort(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> tuple[int, str, str]: ...


@dataclass(frozen=True, slots=True)
class SubprocessLocalGitLfsQualificationCommandPort:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> tuple[int, str, str]:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        return completed.returncode, completed.stdout, completed.stderr


@dataclass(slots=True)
class LocalGitLfsQualificationState:
    repository: Path = field(repr=False)
    workspace: Path = field(repr=False)
    command_port: LocalGitLfsQualificationCommandPort = field(repr=False)
    response_loss_commit: str | None = None
    response_loss_ref: str | None = None

    def __post_init__(self) -> None:
        repository = self.repository.absolute()
        workspace = self.workspace.absolute()
        if (
            not repository.is_dir()
            or repository.is_symlink()
            or workspace.is_symlink()
            or repository == workspace
        ):
            raise ValueError("Git/LFS qualification paths must be direct and isolated")
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "workspace", workspace)

    def cleanup(self) -> dict[str, object]:
        removed = False
        if self.workspace.exists():
            if self.workspace.is_symlink():
                raise ExternalQualificationError(
                    "qualification_git_cleanup_target_invalid",
                    "Git/LFS qualification workspace cannot be a symlink",
                )
            shutil.rmtree(self.workspace)
            removed = True
        return {"workspace_removed": removed, "repository_preserved": True}


@dataclass(slots=True)
class LocalGitLfsQualificationOperation:
    component_id: str
    route_id: str
    subject_digest: str
    state: LocalGitLfsQualificationState = field(repr=False)
    local_only: bool = True
    hosted_sync_allowed: bool = False

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation:
        try:
            if request.operation == "clone":
                self._clone()
            elif request.operation == "checkpoint":
                self._checkpoint()
            elif request.operation == "publish":
                self._publish("refs/heads/qualification")
            elif request.operation == "lfs-fetch":
                self._lfs_fetch()
            elif request.operation == "response-loss-reconcile":
                self._prepare_response_loss(request)
                return self._observation(
                    request,
                    terminal=False,
                    succeeded=False,
                    effect_certainty="dispatch_in_doubt",
                    error_code="qualification_response_lost_after_git_acceptance",
                )
            else:
                raise ExternalQualificationError(
                    "qualification_git_operation_unsupported",
                    "Git/LFS qualification operation is unsupported",
                )
        except (OSError, subprocess.SubprocessError, ExternalQualificationError) as exc:
            return self._observation(
                request,
                terminal=True,
                succeeded=False,
                effect_certainty="terminal_known",
                error_code=getattr(exc, "error_code", "qualification_git_operation_failed"),
            )
        return self._observation(
            request,
            terminal=True,
            succeeded=True,
            effect_certainty="terminal_known",
        )

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation:
        if (
            request.operation != "response-loss-reconcile"
            or self.state.response_loss_commit is None
            or self.state.response_loss_ref is None
        ):
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "Git/LFS reconcile requires the exact response-loss dispatch",
            )
        returncode, stdout, _stderr = self.state.command_port.run(
            (
                "git",
                "--git-dir",
                str(self.state.repository),
                "rev-parse",
                self.state.response_loss_ref,
            )
        )
        succeeded = returncode == 0 and stdout.strip() == self.state.response_loss_commit
        return self._observation(
            request,
            terminal=True,
            succeeded=succeeded,
            effect_certainty="terminal_known",
            error_code=None if succeeded else "qualification_git_reconcile_failed",
        )

    def restore_dispatched_attempt(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> None:
        if request.operation != "response-loss-reconcile":
            raise ExternalQualificationError(
                "qualification_probe_restore_not_reconcilable",
                "only the Git response-loss operation can be restored",
            )
        ref = self._response_loss_ref(request)
        commit = self._run(
            "git",
            "--git-dir",
            str(self.state.repository),
            "rev-parse",
            ref,
        )
        self.state.response_loss_ref = ref
        self.state.response_loss_commit = commit

    def _run(self, *argv: str, cwd: Path | None = None) -> str:
        returncode, stdout, _stderr = self.state.command_port.run(tuple(argv), cwd=cwd)
        if returncode != 0:
            raise ExternalQualificationError(
                "qualification_git_command_failed",
                "local Git/LFS qualification command failed",
            )
        return stdout.strip()

    def _clone(self) -> None:
        if self.state.workspace.exists() or self.state.workspace.is_symlink():
            raise ExternalQualificationError(
                "qualification_git_workspace_collision",
                "Git/LFS qualification workspace already exists",
            )
        self.state.workspace.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._run("git", "clone", str(self.state.repository), str(self.state.workspace))
        self.state.workspace.chmod(0o700)
        self._run("git", "lfs", "install", "--local", cwd=self.state.workspace)

    def _checkpoint(self) -> None:
        self._run("git", "config", "user.name", "OpenZyme Qualification", cwd=self.state.workspace)
        self._run("git", "config", "user.email", "qualification@openzyme.invalid", cwd=self.state.workspace)
        self._run("git", "lfs", "track", "*.bin", cwd=self.state.workspace)
        payload = self.state.workspace / "qualification.bin"
        payload.write_bytes(b"openzyme-git-lfs-qualification-v1\n")
        self._run("git", "add", ".gitattributes", "qualification.bin", cwd=self.state.workspace)
        self._run("git", "commit", "-m", "qualification checkpoint", cwd=self.state.workspace)

    def _publish(self, ref: str) -> None:
        self._run("git", "push", "origin", f"HEAD:{ref}", cwd=self.state.workspace)

    def _lfs_fetch(self) -> None:
        self._run(
            "git",
            "lfs",
            "fetch",
            "origin",
            "refs/remotes/origin/qualification",
            cwd=self.state.workspace,
        )
        self._run("git", "lfs", "checkout", cwd=self.state.workspace)
        content = (self.state.workspace / "qualification.bin").read_bytes()
        if content != b"openzyme-git-lfs-qualification-v1\n":
            raise ExternalQualificationError(
                "qualification_git_lfs_content_mismatch",
                "Git LFS checkout returned unexpected content",
            )

    def _prepare_response_loss(self, request: ExternalQualificationProbeRequest) -> None:
        marker = self.state.workspace / "response-loss.txt"
        marker.write_text("same-attempt-response-loss\n", encoding="utf-8")
        self._run("git", "add", "response-loss.txt", cwd=self.state.workspace)
        self._run("git", "commit", "-m", "qualification response loss", cwd=self.state.workspace)
        commit = self._run("git", "rev-parse", "HEAD", cwd=self.state.workspace)
        ref = self._response_loss_ref(request)
        self._publish(ref)
        self.state.response_loss_ref = ref
        self.state.response_loss_commit = commit

    @staticmethod
    def _response_loss_ref(request: ExternalQualificationProbeRequest) -> str:
        suffix = canonical_sha256_digest(
            {"attempt_id": request.attempt_id}
        ).removeprefix("sha256:")[:16]
        return f"refs/heads/qualification-response-loss-{suffix}"

    @staticmethod
    def _observation(
        request: ExternalQualificationProbeRequest,
        *,
        terminal: bool,
        succeeded: bool,
        effect_certainty: str,
        error_code: str | None = None,
    ) -> ExternalQualificationOperationObservation:
        payload = {
            "attempt_id": request.attempt_id,
            "operation": request.operation,
            "terminal": terminal,
            "succeeded": succeeded,
        }
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty=effect_certainty,
            terminal=terminal,
            succeeded=succeeded,
            output_digest=canonical_sha256_digest(payload) if succeeded else None,
            receipt_digest=canonical_sha256_digest({**payload, "local_only": True}),
            error_code=error_code,
            external_effect_performed=True,
            credential_material_accessed=False,
            fallback_performed=False,
        )


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

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None:
        self._bridge.restore_dispatched_attempt(request)


__all__ = [
    "GIT_LFS_QUALIFICATION_OPERATIONS",
    "GitLfsQualificationOperationPort",
    "GitLfsQualificationProbeBridge",
    "LocalGitLfsQualificationCommandPort",
    "LocalGitLfsQualificationOperation",
    "LocalGitLfsQualificationState",
    "LocalGitLfsPreparationCommandPort",
    "LocalIsolatedGitLfsPreparationExecutor",
    "SubprocessLocalGitLfsPreparationCommandPort",
    "SubprocessLocalGitLfsQualificationCommandPort",
]
