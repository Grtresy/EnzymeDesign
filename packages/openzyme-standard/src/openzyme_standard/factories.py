from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Iterable

from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import WorkspaceOperationLedgerPort
from openzyme_extension_spi import AuthorityApplicationService
from openzyme_extension_spi import ControlledOperationApplicationService
from openzyme_kernel import WorkspaceOperationCoordinator
from openzyme_process_podman import PodmanAgentCapsuleProcessRunner
from openzyme_process_podman import PodmanAgentWorkspaceVolumeBackend
from openzyme_process_podman import SubprocessCapsuleCommandExecutor
from openzyme_process_podman import PodmanWorkspaceFilesystemAdapter
from openzyme_process_podman import PodmanWorkspaceMountResolver
from openzyme_process_podman import PodmanWorkspaceProcessAdapter
from openzyme_runtime_spi import ProcessIsolationPort
from openzyme_workspace_git_lfs import PodmanAgentGitWorkspaceObservationProvider
from openzyme_workspace_git_lfs import DurableRepositoryRootManager
from openzyme_workspace_git_lfs import AgentGitWorkspaceRecoveryMechanism
from openzyme_workspace_git_lfs import GitLfsRepositoryBindingMechanism
from openzyme_workspace_git_lfs import HmacRepositoryCredentialMaterialAdapter
from openzyme_workspace_git_lfs import GitRepositoryLocation
from openzyme_workspace_git_lfs import GitRepositoryLocator
from openzyme_workspace_git_lfs import LocalGitRevisionBackend
from openzyme_workspace_git_lfs import RepositoryCredentialIssuanceStore
from openzyme_workspace_git_lfs import RepositoryRootBoundary
from openzyme_runtime_llm import LangChainProviderBackend
from openzyme_runtime_llm import LlmAdapterConfiguration
from openzyme_runtime_llm import LlmRuntimeAdapter


@dataclass(frozen=True, slots=True)
class StandardLocalWorkspaceAdapterFactory:
    """Construct the exact local Adapter set selected by Standard.

    Construction is side-effect free. It does not inspect Podman, allocate a
    volume, start a process, or create canonical workspace state.
    """

    podman_binary: str
    deployment_network: str

    def __post_init__(self) -> None:
        path = Path(self.podman_binary)
        if not path.is_absolute() or str(path) != self.podman_binary:
            raise ValueError("Standard Podman binary must be one normalized absolute path")

    def build_capsule_process_runner(self) -> PodmanAgentCapsuleProcessRunner:
        return PodmanAgentCapsuleProcessRunner(
            executor=SubprocessCapsuleCommandExecutor(),
            deployment_network=self.deployment_network,
            podman_binary=self.podman_binary,
        )

    def build_workspace_volume_backend(self) -> PodmanAgentWorkspaceVolumeBackend:
        return PodmanAgentWorkspaceVolumeBackend(
            executor=SubprocessCapsuleCommandExecutor(),
            podman_binary=self.podman_binary,
        )

    def build_workspace_observation_provider(
        self,
        *,
        process_runner: Any,
    ) -> PodmanAgentGitWorkspaceObservationProvider:
        return PodmanAgentGitWorkspaceObservationProvider(
            process_runner=process_runner
        )


@dataclass(frozen=True, slots=True)
class StandardLocalWorkspaceRuntimeAdapters:
    """Exact Port implementations behind Standard's Kernel workspace tools."""

    coordinator: WorkspaceOperationCoordinator
    filesystem: PodmanWorkspaceFilesystemAdapter
    process: PodmanWorkspaceProcessAdapter


@dataclass(frozen=True, slots=True)
class StandardLocalWorkspaceRuntimeFactory:
    """Compose local workspace Ports without performing an external effect."""

    mount_resolver: PodmanWorkspaceMountResolver
    process_isolation: ProcessIsolationPort
    authority: AuthorityApplicationService
    controlled_operations: ControlledOperationApplicationService
    operation_ledger: WorkspaceOperationLedgerPort
    workspace_provider_id: str = "openzyme.workspace.git-lfs"
    podman_binary: str = "/usr/bin/podman"

    def __post_init__(self) -> None:
        if not self.workspace_provider_id:
            raise ValueError("workspace_provider_id must be non-empty")
        path = Path(self.podman_binary)
        if not path.is_absolute() or str(path) != self.podman_binary:
            raise ValueError("Standard Podman binary must be one normalized absolute path")

    def build(self) -> StandardLocalWorkspaceRuntimeAdapters:
        filesystem = PodmanWorkspaceFilesystemAdapter(
            mount_resolver=self.mount_resolver,
            operation_ledger=self.operation_ledger,
            podman_binary=self.podman_binary,
        )
        process = PodmanWorkspaceProcessAdapter(
            isolation=self.process_isolation,
            mount_resolver=self.mount_resolver,
            operation_ledger=self.operation_ledger,
        )
        coordinator = WorkspaceOperationCoordinator(
            authority=self.authority,
            controlled_operations=self.controlled_operations,
            observation_ports={self.workspace_provider_id: filesystem},
            filesystem_ports={self.workspace_provider_id: filesystem},
            process_ports={self.workspace_provider_id: process},
        )
        return StandardLocalWorkspaceRuntimeAdapters(
            coordinator=coordinator,
            filesystem=filesystem,
            process=process,
        )


@dataclass(frozen=True, slots=True)
class StandardRepositoryAdapterFactory:
    """Side-effect-free composition factory for Standard's Git/LFS Adapter.

    Host supplies no filesystem locator or Git implementation.  The exact
    operator-selected settings and root boundary are frozen in this Distribution
    factory; individual build methods only construct Adapter objects.
    """

    repository_settings: Any
    root_boundary: RepositoryRootBoundary

    @classmethod
    def production(
        cls,
        repository_settings: Any,
        *,
        host_checkout: Path,
        process_cwd: Path,
    ) -> StandardRepositoryAdapterFactory:
        return cls(
            repository_settings=repository_settings,
            root_boundary=RepositoryRootBoundary.production(
                host_checkout=host_checkout,
                process_cwd=process_cwd,
            ),
        )

    def matches_settings(self, settings: Any) -> bool:
        return self.repository_settings == settings

    def build_root_manager(self) -> DurableRepositoryRootManager:
        return DurableRepositoryRootManager(
            self.repository_settings,
            self.root_boundary,
        )

    def build_binding_mechanism(
        self,
        *,
        roots: DurableRepositoryRootManager,
    ) -> GitLfsRepositoryBindingMechanism:
        if roots.settings != self.repository_settings or roots.boundary != self.root_boundary:
            raise ValueError(
                "repository root manager differs from the Standard factory identity"
            )
        return GitLfsRepositoryBindingMechanism(
            self.repository_settings,
            roots,
        )

    def build_revision_backend(
        self,
        *,
        roots: DurableRepositoryRootManager,
        bindings: Iterable[ProjectRepositoryBinding],
    ) -> LocalGitRevisionBackend:
        if roots.settings != self.repository_settings or roots.boundary != self.root_boundary:
            raise ValueError(
                "repository root manager differs from the Standard factory identity"
            )
        locations = tuple(
            GitRepositoryLocation(
                repository_id=binding.repository_id,
                bare_repository_root=roots.repository_path(binding.repository_id),
                lfs_object_root=(
                    roots.settings.lfs_object_root / binding.repository_id
                ),
            )
            for binding in bindings
        )
        return LocalGitRevisionBackend(
            locator=GitRepositoryLocator(locations),
        )

    def build_workspace_recovery_mechanism(
        self,
        *,
        volume_backend: Any,
        observation_provider: Any,
    ) -> AgentGitWorkspaceRecoveryMechanism:
        return AgentGitWorkspaceRecoveryMechanism(
            volume_backend=volume_backend,
            observation_provider=observation_provider,
        )

    def build_credential_issuance_store(
        self,
        *,
        connection: Any,
    ) -> RepositoryCredentialIssuanceStore:
        return RepositoryCredentialIssuanceStore(
            connection=connection,
            material=HmacRepositoryCredentialMaterialAdapter(
                self.repository_settings.credential_signing_key_file
            ),
        )


@dataclass(frozen=True, slots=True)
class StandardLlmAdapterFactory:
    """Construct only the LLM implementation explicitly selected by Standard.

    Host supplies resolved configuration but does not import LangChain, choose a
    provider, build provider credentials, or own token/provider diagnostics.
    """

    def build_runtime_adapter(
        self,
        *,
        configuration: LlmAdapterConfiguration,
        credential: str,
    ) -> LlmRuntimeAdapter:
        return LlmRuntimeAdapter(
            configuration=configuration,
            provider=LangChainProviderBackend(
                configuration=configuration,
                api_key=credential,
            ),
        )

__all__ = [
    "StandardLocalWorkspaceAdapterFactory",
    "StandardLlmAdapterFactory",
    "StandardRepositoryAdapterFactory",
]
