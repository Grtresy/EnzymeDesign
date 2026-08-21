"""Podman Adapter package with a locator-safe, side-effect-free import boundary."""

from __future__ import annotations

from importlib import import_module
from typing import Any


COMPONENT_ID = "openzyme.process.podman"
COMPONENT_KIND = "adapter"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"


_EXPORT_MODULES = {
    "AGENT_CAPSULE_IMAGE_MANIFEST_SCHEMA_VERSION": "capsule_image",
    "AGENT_CAPSULE_IMAGE_QUALIFICATION_SCHEMA_VERSION": "capsule_image",
    "AgentCapsuleImageError": "capsule_image",
    "AgentCapsuleImageManifest": "capsule_image",
    "AgentCapsuleImageQualification": "capsule_image",
    "AgentCapsuleImageQualificationError": "capsule_image",
    "CapsuleCommandExecutor": "capsule_image",
    "CapsuleCommandResult": "capsule_image",
    "DEFAULT_AGENT_CAPSULE_IMAGE_FAMILY": "capsule_image",
    "SubprocessCapsuleCommandExecutor": "capsule_image",
    "build_agent_capsule_image": "capsule_image",
    "load_agent_capsule_image_manifest": "capsule_image",
    "qualify_agent_capsule_image": "capsule_image",
    "AgentCapsuleControlHandler": "capsule_runner",
    "AgentCapsuleWorkspace": "capsule_runner",
    "PodmanAgentCapsuleProcessRunner": "capsule_runner",
    "PodmanContainerLease": "lifecycle",
    "PODMAN_ADAPTER_CONFIGURATION_SCHEMA": "preflight",
    "PODMAN_ADAPTER_CONFIGURATION_SCHEMA_DIGEST": "preflight",
    "PODMAN_ADAPTER_PREFLIGHT_CONTRACT": "preflight",
    "PODMAN_ADAPTER_PREFLIGHT_CONTRACT_DIGEST": "preflight",
    "PodmanAdapterConfiguration": "preflight",
    "PodmanAdapterPreflightReceipt": "preflight",
    "preflight_podman_adapter": "preflight",
    "PODMAN_FILESYSTEM_HELPER_DIGEST": "filesystem",
    "PODMAN_FILESYSTEM_HELPER_SCHEMA": "filesystem",
    "PODMAN_FILESYSTEM_PROVIDER_CONTRACT": "filesystem",
    "PODMAN_FILESYSTEM_PROVIDER_CONTRACT_DIGEST": "filesystem",
    "PODMAN_FILESYSTEM_PROVIDER_ID": "filesystem",
    "PodmanWorkspaceFilesystemAdapter": "filesystem",
    "MappingPodmanWorkspaceMountResolver": "process",
    "PODMAN_PROCESS_PROVIDER_CONTRACT": "process",
    "PODMAN_PROCESS_PROVIDER_CONTRACT_DIGEST": "process",
    "PODMAN_PROCESS_PROVIDER_ID": "process",
    "PodmanCommandExecutor": "process",
    "PodmanDispatchError": "process",
    "PodmanProcessIsolationAdapter": "process",
    "PodmanWorkspaceMount": "process",
    "PodmanWorkspaceMountResolver": "process",
    "PodmanWorkspaceProcessAdapter": "process",
    "SupervisedProcessRequest": "process",
    "SupervisedProcessResult": "process",
    "SupervisedSubprocessExecutor": "process",
    "build_podman_command": "process",
    "SandboxImageCompatibility": "state",
    "SandboxImageRecord": "state",
    "SandboxRunRecord": "state",
    "SandboxRunStatus": "state",
    "SandboxWorkspaceRecord": "state",
    "SandboxWorkspaceStatus": "state",
    "AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION": "volumes",
    "AgentWorkspaceVolumeAllocator": "volumes",
    "AgentWorkspaceVolumeBackend": "volumes",
    "AgentWorkspaceVolumeError": "volumes",
    "AgentWorkspaceVolumeFact": "volumes",
    "AgentWorkspaceVolumeIdentityError": "volumes",
    "PodmanAgentWorkspaceVolumeBackend": "volumes",
    "PodmanVolumeCommandExecutor": "volumes",
    "PodmanVolumeCommandResult": "volumes",
    "derive_agent_workspace_volume_id": "volumes",
    "MappingPodmanTransferMountResolver": "transfer",
    "PODMAN_TRANSFER_HELPER_DIGEST": "transfer",
    "PODMAN_TRANSFER_HELPER_SCHEMA": "transfer",
    "PODMAN_TRANSFER_PROVIDER_CONTRACT": "transfer",
    "PODMAN_TRANSFER_PROVIDER_CONTRACT_DIGEST": "transfer",
    "PODMAN_TRANSFER_PROVIDER_ID": "transfer",
    "PODMAN_TRANSFER_RESULT_SCHEMA": "transfer",
    "PodmanRevisionTransferIdentity": "transfer",
    "PodmanTransferMountResolver": "transfer",
    "PodmanTransferObjectKind": "transfer",
    "PodmanTransferObjectMount": "transfer",
    "PodmanWorkspaceTransferAdapter": "transfer",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORT_MODULES})


__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    *_EXPORT_MODULES,
]
