from __future__ import annotations

from types import SimpleNamespace
import sqlite3

import pytest

from openzyme_process_podman import PodmanAgentCapsuleProcessRunner
from openzyme_process_podman import PodmanAgentWorkspaceVolumeBackend
from openzyme_process_podman import MappingPodmanWorkspaceMountResolver
from openzyme_process_podman import PodmanWorkspaceFilesystemAdapter
from openzyme_process_podman import PodmanWorkspaceProcessAdapter
from openzyme_standard import StandardLocalWorkspaceAdapterFactory
from openzyme_standard import StandardLocalWorkspaceRuntimeFactory
from openzyme_standard import StandardLlmAdapterFactory
from openzyme_standard import StandardRepositoryAdapterFactory
from openzyme_runtime_llm import LangChainProviderBackend
from openzyme_runtime_llm import LlmAdapterConfiguration
from openzyme_runtime_llm import LlmRuntimeAdapter
from openzyme_workspace_git_lfs import DurableRepositoryRootManager
from openzyme_workspace_git_lfs import GitLfsRepositoryBindingMechanism
from openzyme_workspace_git_lfs import LocalGitRevisionBackend
from openzyme_workspace_git_lfs import PodmanAgentGitWorkspaceObservationProvider
from openzyme_workspace_git_lfs import AgentGitWorkspaceRecoveryMechanism
from openzyme_workspace_git_lfs import RepositoryCredentialIssuanceStore
from openzyme_workspace_git_lfs import RepositoryRootBoundary


def test_standard_factory_builds_exact_selected_local_adapters_without_effects() -> None:
    factory = StandardLocalWorkspaceAdapterFactory(
        podman_binary="/usr/bin/podman",
        deployment_network="openzyme-agent",
    )

    runner = factory.build_capsule_process_runner()
    volume = factory.build_workspace_volume_backend()
    observation = factory.build_workspace_observation_provider(
        process_runner=runner
    )

    assert isinstance(runner, PodmanAgentCapsuleProcessRunner)
    assert isinstance(volume, PodmanAgentWorkspaceVolumeBackend)
    assert isinstance(observation, PodmanAgentGitWorkspaceObservationProvider)
    assert runner.podman_binary == "/usr/bin/podman"
    assert runner.deployment_network == "openzyme-agent"
    assert observation.process_runner is runner


def test_standard_factory_rejects_implicit_or_unsafe_adapter_identity() -> None:
    with pytest.raises(ValueError, match="normalized absolute"):
        StandardLocalWorkspaceAdapterFactory(
            podman_binary="podman",
            deployment_network="openzyme-agent",
        )

    factory = StandardLocalWorkspaceAdapterFactory(
        podman_binary="/usr/bin/podman",
        deployment_network="network with spaces",
    )
    with pytest.raises(ValueError, match="safe Podman network"):
        factory.build_capsule_process_runner()


def test_standard_factory_composes_kernel_workspace_ports_without_dispatch() -> None:
    factory = StandardLocalWorkspaceRuntimeFactory(
        mount_resolver=MappingPodmanWorkspaceMountResolver(mounts={}),
        process_isolation=object(),  # type: ignore[arg-type]
        authority=object(),  # type: ignore[arg-type]
        controlled_operations=object(),  # type: ignore[arg-type]
        operation_ledger=object(),  # type: ignore[arg-type]
    )

    adapters = factory.build()

    assert isinstance(adapters.filesystem, PodmanWorkspaceFilesystemAdapter)
    assert isinstance(adapters.process, PodmanWorkspaceProcessAdapter)
    assert adapters.process.isolation is factory.process_isolation
    assert adapters.process.mount_resolver is factory.mount_resolver
    assert adapters.process.operation_ledger is factory.operation_ledger


def test_standard_llm_factory_constructs_selected_adapter_without_network() -> None:
    configuration = LlmAdapterConfiguration(
        provider_id="openai",
        model="gpt-test",
        base_url="https://provider.invalid/v1",
        credential_slot="llm.primary",
        timeout_seconds=30,
        max_retries=1,
        context_window_units=16_384,
        default_output_units=1_024,
        provider_options={},
    )

    adapter = StandardLlmAdapterFactory().build_runtime_adapter(
        configuration=configuration,
        credential="secret-material",
    )

    assert isinstance(adapter, LlmRuntimeAdapter)
    assert isinstance(adapter.provider, LangChainProviderBackend)
    assert adapter.configuration is configuration
    assert adapter.provider.provider_id == "openai"
    assert not hasattr(StandardLlmAdapterFactory, "build_legacy_chat_model_factory")


def test_standard_repository_factory_owns_git_lfs_adapter_construction(
    tmp_path,
) -> None:
    for name in ("git", "lfs", "backup", "checkout", "cwd"):
        (tmp_path / name).mkdir()
    settings = SimpleNamespace(
        bare_repository_root=(tmp_path / "git").resolve(),
        lfs_object_root=(tmp_path / "lfs").resolve(),
        backup_root=(tmp_path / "backup").resolve(),
        git_executable=(tmp_path / "git-bin").resolve(),
        credential_signing_key_file=(tmp_path / "credential.key").resolve(),
    )
    settings.credential_signing_key_file.write_bytes(b"k" * 32)
    boundary = RepositoryRootBoundary(
        host_checkout=(tmp_path / "checkout").resolve(),
        process_cwd=(tmp_path / "cwd").resolve(),
        temporary_roots=(),
    )
    factory = StandardRepositoryAdapterFactory(settings, boundary)

    roots = factory.build_root_manager()
    binding_mechanism = factory.build_binding_mechanism(roots=roots)
    revision_backend = factory.build_revision_backend(roots=roots, bindings=())
    recovery = factory.build_workspace_recovery_mechanism(
        volume_backend=object(),
        observation_provider=object(),
    )
    issuance = factory.build_credential_issuance_store(
        connection=sqlite3.connect(":memory:"),
    )

    assert factory.matches_settings(settings) is True
    assert isinstance(roots, DurableRepositoryRootManager)
    assert isinstance(binding_mechanism, GitLfsRepositoryBindingMechanism)
    assert isinstance(revision_backend, LocalGitRevisionBackend)
    assert isinstance(recovery, AgentGitWorkspaceRecoveryMechanism)
    assert isinstance(issuance, RepositoryCredentialIssuanceStore)
