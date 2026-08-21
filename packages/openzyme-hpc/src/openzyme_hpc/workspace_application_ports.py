from __future__ import annotations

from contextlib import AbstractContextManager
from enum import StrEnum
from typing import Protocol

from .contracts import ExecutorHpcTargetQualification
from .contracts import ExecutorHpcWorkspace
from .contracts import ExecutorHpcWorkspaceProvisionIntent
from .workspace_lifecycle import ExecutorHpcWorkspaceError
from .workspace_state_machine import ExecutorHpcProvisionContext
from .workspace_state_machine import ExecutorHpcRevisionSource


class ExecutorHpcWorkspaceAuthorityError(ExecutorHpcWorkspaceError):
    """Kernel authority or owner facts reject an HPC workspace operation."""

    error_code = "executor_hpc_workspace_authority_denied"


class ExecutorHpcAuthorityCapability(StrEnum):
    SSH = "ssh"
    RSYNC_SCP = "rsync_scp"
    HPC_LOGIN_WORKSPACE_CRUD = "hpc_login_workspace_crud"
    GIT = "git"
    GIT_LFS = "git_lfs"


class ExecutorHpcWorkspaceKernelFactsPort(Protocol):
    """Narrow Kernel-facing facts consumed by the HPC Plugin application."""

    def prepare_provision_context(
        self,
        *,
        session_id: str,
        executor_agent_id: str,
        target: ExecutorHpcTargetQualification,
    ) -> ExecutorHpcProvisionContext: ...

    def authorize_workspace(
        self,
        workspace: ExecutorHpcWorkspace,
        *,
        service_id: str,
        protocol: str,
        operation_class: str,
        required_capabilities: tuple[ExecutorHpcAuthorityCapability, ...],
    ) -> None: ...

    def agent_member_id(self, *, session_id: str, agent_id: str) -> str | None: ...

    def resolve_revision_source(
        self,
        *,
        workspace: ExecutorHpcWorkspace,
        checkpoint_id: str | None,
        publication_id: str | None,
    ) -> ExecutorHpcRevisionSource: ...

    def repository_binding_digest(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> str: ...


class ExecutorHpcWorkspaceUnitOfWork(Protocol):
    def __call__(self, *, prefix: str) -> AbstractContextManager[None]: ...


__all__ = [
    "ExecutorHpcAuthorityCapability",
    "ExecutorHpcWorkspaceAuthorityError",
    "ExecutorHpcWorkspaceKernelFactsPort",
    "ExecutorHpcWorkspaceUnitOfWork",
]
