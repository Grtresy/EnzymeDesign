from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from openzyme_contracts import canonical_sha256_digest

from .process import PODMAN_PROCESS_PROVIDER_CONTRACT_DIGEST


PODMAN_ADAPTER_CONFIGURATION_SCHEMA = "openzyme_podman_adapter_configuration@1"
PODMAN_ADAPTER_CONFIGURATION_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "schema": PODMAN_ADAPTER_CONFIGURATION_SCHEMA,
        "fields": [
            "podman_binary",
            "deployment_network",
            "runtime_uid",
            "runtime_gid",
            "image_identity",
        ],
        "closed": True,
        "ambient_binary_selection": False,
    }
)
PODMAN_ADAPTER_PREFLIGHT_CONTRACT = "openzyme.podman-adapter-preflight@1"
PODMAN_ADAPTER_PREFLIGHT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": PODMAN_ADAPTER_PREFLIGHT_CONTRACT,
        "checks": [
            "exact_binary_regular_executable",
            "exact_network_identity",
            "exact_image_identity",
            "runtime_principal",
        ],
        "subprocess_probe": False,
        "network_probe": False,
    }
)


@dataclass(frozen=True, slots=True)
class PodmanAdapterConfiguration:
    podman_binary: str
    deployment_network: str
    runtime_uid: int
    runtime_gid: int
    image_identity: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.podman_binary, str)
            or not self.podman_binary.startswith("/")
            or "\x00" in self.podman_binary
        ):
            raise ValueError("podman_binary must be one exact absolute path")
        for field_name in ("deployment_network", "image_identity"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 2_048
                or "\x00" in value
            ):
                raise ValueError(f"{field_name} must be one bounded identity")
        for field_name in ("runtime_uid", "runtime_gid"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PodmanAdapterConfiguration":
        expected = {
            "schema_version",
            "podman_binary",
            "deployment_network",
            "runtime_uid",
            "runtime_gid",
            "image_identity",
        }
        if set(value) != expected:
            raise ValueError("Podman Adapter configuration fields are closed")
        if value["schema_version"] != PODMAN_ADAPTER_CONFIGURATION_SCHEMA:
            raise ValueError("unsupported Podman Adapter configuration schema")
        return cls(
            podman_binary=value["podman_binary"],
            deployment_network=value["deployment_network"],
            runtime_uid=value["runtime_uid"],
            runtime_gid=value["runtime_gid"],
            image_identity=value["image_identity"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PODMAN_ADAPTER_CONFIGURATION_SCHEMA,
            "podman_binary": self.podman_binary,
            "deployment_network": self.deployment_network,
            "runtime_uid": self.runtime_uid,
            "runtime_gid": self.runtime_gid,
            "image_identity": self.image_identity,
        }

    @property
    def configuration_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class PodmanAdapterPreflightReceipt:
    configuration_digest: str
    process_contract_digest: str
    binary_identity_digest: str
    ready: bool
    subprocess_probe_performed: bool = False
    network_probe_performed: bool = False

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "configuration_digest": self.configuration_digest,
                "process_contract_digest": self.process_contract_digest,
                "binary_identity_digest": self.binary_identity_digest,
                "ready": self.ready,
                "subprocess_probe_performed": self.subprocess_probe_performed,
                "network_probe_performed": self.network_probe_performed,
            }
        )


def preflight_podman_adapter(
    configuration: PodmanAdapterConfiguration,
) -> PodmanAdapterPreflightReceipt:
    path = Path(configuration.podman_binary)
    try:
        path_stat = path.stat()
    except OSError as exc:
        raise RuntimeError("selected Podman binary cannot be observed") from exc
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError("selected Podman binary is not a regular executable")
    binary_identity_digest = canonical_sha256_digest(
        {
            "path": configuration.podman_binary,
            "device": path_stat.st_dev,
            "inode": path_stat.st_ino,
            "size": path_stat.st_size,
            "mtime_ns": path_stat.st_mtime_ns,
        }
    )
    return PodmanAdapterPreflightReceipt(
        configuration_digest=configuration.configuration_digest,
        process_contract_digest=PODMAN_PROCESS_PROVIDER_CONTRACT_DIGEST,
        binary_identity_digest=binary_identity_digest,
        ready=True,
    )


__all__ = [
    "PODMAN_ADAPTER_CONFIGURATION_SCHEMA",
    "PODMAN_ADAPTER_CONFIGURATION_SCHEMA_DIGEST",
    "PODMAN_ADAPTER_PREFLIGHT_CONTRACT",
    "PODMAN_ADAPTER_PREFLIGHT_CONTRACT_DIGEST",
    "PodmanAdapterConfiguration",
    "PodmanAdapterPreflightReceipt",
    "preflight_podman_adapter",
]
