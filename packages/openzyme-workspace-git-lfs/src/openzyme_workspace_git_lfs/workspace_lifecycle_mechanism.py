"""Mechanism-only Agent Git workspace provision and recovery probes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
from typing import Protocol

from openzyme_contracts import AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION
from openzyme_contracts import AgentWorkspaceVolumeBackendPort
from openzyme_contracts import AgentWorkspaceVolumeFact
from openzyme_contracts import AgentWorkspaceVolumeIdentityError

from .agent_workspaces import AgentGitDirectoryKind
from .agent_workspaces import AgentGitWorkspace
from .agent_workspaces import AgentGitWorkspaceBlockerCode
from .agent_workspaces import AgentGitWorkspaceObservation
from .clone import AgentGitWorkspaceProvisioningError
from .clone import AgentWorkspaceCloneRunner
from .observation import AgentGitWorkspaceBaseCommitDriftError
from .observation import AgentGitWorkspaceCorruptionError
from .observation import AgentGitWorkspaceInfrastructureError
from .observation import AgentGitWorkspaceObservationProvider
from .observation import AgentGitWorkspacePermissionError


class AgentWorkspaceVolumeAllocatorPort(Protocol):
    def allocate(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
    ) -> AgentWorkspaceVolumeFact: ...


class AgentGitWorkspaceProvisioningMechanismError(
    AgentGitWorkspaceProvisioningError
):
    error_code = "agent_git_workspace_provisioning_mechanism_failed"

    def __init__(self, message: str, *, blocker_detail: dict[str, object]) -> None:
        self.blocker_detail = blocker_detail
        super().__init__(message)


@dataclass(slots=True)
class AgentGitWorkspaceProvisioningMechanism:
    """Allocate a private volume and clone one exact canonical workspace."""

    volume_allocator: AgentWorkspaceVolumeAllocatorPort
    clone_runner: AgentWorkspaceCloneRunner

    def allocate_volume(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
    ) -> str:
        return self.volume_allocator.allocate(
            workspace_id=workspace_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        ).volume_id

    def clone_and_observe(
        self,
        *,
        workspace: AgentGitWorkspace,
        credential_token: str,
    ) -> AgentGitWorkspaceObservation:
        try:
            clone = self.clone_runner.clone_exact_base(
                workspace=workspace,
                credential_token=credential_token,
            )
        except BaseException as exc:
            raise AgentGitWorkspaceProvisioningMechanismError(
                "clone runner failed before identity observation",
                blocker_detail={
                    "exception_type": type(exc).__name__,
                    "reason": "clone_runner_failed_before_identity_observation",
                },
            ) from exc
        if clone.returncode != 0:
            raise AgentGitWorkspaceProvisioningMechanismError(
                f"full clone failed with native exit {clone.returncode}",
                blocker_detail={
                    "native_exit": clone.returncode,
                    "stderr_digest": _text_digest(clone.stderr),
                },
            )
        if (
            clone.head_commit is None
            or clone.head_tree is None
            or clone.object_format is None
            or clone.remote_endpoint is None
            or not clone.independent_git_directory
        ):
            raise AgentGitWorkspaceProvisioningMechanismError(
                "clone success did not return a complete independent Git identity",
                blocker_detail={
                    "reason": "clone_identity_receipt_incomplete",
                    "native_exit": clone.returncode,
                },
            )
        return AgentGitWorkspaceObservation(
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            volume_id=workspace.volume_id,
            clone_logical_root=workspace.clone_logical_root,
            git_directory_kind=AgentGitDirectoryKind.INDEPENDENT,
            internal_git_service_id=workspace.internal_git_service_id,
            internal_git_endpoint=clone.remote_endpoint,
            repository_id=workspace.repository_id,
            object_format=clone.object_format,
            base_commit=workspace.base_commit,
            head_commit=clone.head_commit,
            head_tree=clone.head_tree,
            head_readable=True,
            private_ref_namespace=workspace.private_ref_namespace,
            repository_policy_digest=workspace.repository_policy_digest,
            capability_policy_digest=workspace.capability_policy_digest,
            observed_at=datetime.now(tz=UTC).isoformat(),
        )


@dataclass(frozen=True, slots=True)
class AgentGitWorkspaceRecoveryProbe:
    observation: AgentGitWorkspaceObservation | None
    blocker_code: AgentGitWorkspaceBlockerCode | None
    blocker_detail: dict[str, object] | None
    private_error: Exception | None = None

    def __post_init__(self) -> None:
        ready = self.observation is not None
        blocked = self.blocker_code is not None and self.blocker_detail is not None
        if ready == blocked:
            raise ValueError("recovery probe must be exactly ready or blocked")
        if ready and self.private_error is not None:
            raise ValueError("ready recovery probe cannot contain a private error")


@dataclass(slots=True)
class AgentGitWorkspaceRecoveryMechanism:
    """Observe exact volume/Git identity without mutating Kernel state."""

    volume_backend: AgentWorkspaceVolumeBackendPort
    observation_provider: AgentGitWorkspaceObservationProvider

    def probe(self, workspace: AgentGitWorkspace) -> AgentGitWorkspaceRecoveryProbe:
        volume = self.volume_backend.inspect(workspace.volume_id)
        if volume is None:
            return _blocked_probe(
                AgentGitWorkspaceBlockerCode.MISSING_VOLUME,
                {"volume_id": workspace.volume_id},
            )
        try:
            require_exact_volume_owner(
                volume,
                expected_labels=expected_volume_labels(workspace),
            )
        except AgentWorkspaceVolumeIdentityError as exc:
            return _blocked_probe(
                AgentGitWorkspaceBlockerCode.CROSS_AGENT_VOLUME,
                {"diagnostic": str(exc)},
            )
        try:
            observation = self.observation_provider.observe(workspace)
        except AgentGitWorkspaceCorruptionError as exc:
            return _failed_probe(
                AgentGitWorkspaceBlockerCode.CORRUPT_GIT_DIRECTORY,
                exc,
            )
        except AgentGitWorkspaceBaseCommitDriftError as exc:
            return _failed_probe(
                AgentGitWorkspaceBlockerCode.BASE_COMMIT_DRIFT,
                exc,
            )
        except AgentGitWorkspaceInfrastructureError as exc:
            return _failed_probe(
                AgentGitWorkspaceBlockerCode.INFRASTRUCTURE_UNAVAILABLE,
                exc,
            )
        except AgentGitWorkspacePermissionError as exc:
            return _failed_probe(
                AgentGitWorkspaceBlockerCode.PERMISSION_OR_CONFIGURATION_FAILURE,
                exc,
            )
        except Exception as exc:
            return _failed_probe(
                AgentGitWorkspaceBlockerCode.INTERNAL_INVARIANT_FAILURE,
                exc,
            )
        return AgentGitWorkspaceRecoveryProbe(
            observation=observation,
            blocker_code=None,
            blocker_detail=None,
        )


def expected_volume_labels(
    workspace: AgentGitWorkspace,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                "io.openzyme.workspace_id": workspace.workspace_id,
                "io.openzyme.session_id": workspace.session_id,
                "io.openzyme.agent_member_id": workspace.agent_member_id,
                "io.openzyme.workspace_generation": str(
                    workspace.workspace_generation
                ),
                "io.openzyme.volume_schema": AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION,
            }.items()
        )
    )


def require_exact_volume_owner(
    fact: AgentWorkspaceVolumeFact,
    *,
    expected_labels: tuple[tuple[str, str], ...],
) -> None:
    owner_labels = tuple(key for key, _ in expected_labels)
    actual = dict(fact.labels)
    expected = dict(expected_labels)
    mismatched = tuple(
        key for key in owner_labels if actual.get(key) != expected.get(key)
    )
    if mismatched:
        raise AgentWorkspaceVolumeIdentityError(
            "workspace volume owner labels do not match: " + ", ".join(mismatched)
        )


def _blocked_probe(
    blocker_code: AgentGitWorkspaceBlockerCode,
    detail: dict[str, object],
) -> AgentGitWorkspaceRecoveryProbe:
    return AgentGitWorkspaceRecoveryProbe(
        observation=None,
        blocker_code=blocker_code,
        blocker_detail=detail,
    )


def _failed_probe(
    blocker_code: AgentGitWorkspaceBlockerCode,
    error: Exception,
) -> AgentGitWorkspaceRecoveryProbe:
    return AgentGitWorkspaceRecoveryProbe(
        observation=None,
        blocker_code=blocker_code,
        blocker_detail={"error_code": str(getattr(error, "error_code", "unknown"))},
        private_error=error,
    )


def _text_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


__all__ = [
    "AgentGitWorkspaceProvisioningMechanism",
    "AgentGitWorkspaceProvisioningMechanismError",
    "AgentGitWorkspaceRecoveryMechanism",
    "AgentGitWorkspaceRecoveryProbe",
    "AgentWorkspaceVolumeAllocatorPort",
    "expected_volume_labels",
    "require_exact_volume_owner",
]
