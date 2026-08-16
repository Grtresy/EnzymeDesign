from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
from importlib.resources import as_file
from importlib.resources import files
import json
import os
import re
import subprocess
from typing import Protocol


AGENT_CAPSULE_IMAGE_MANIFEST_SCHEMA_VERSION = "agent_capsule_image_manifest@1"
AGENT_CAPSULE_IMAGE_QUALIFICATION_SCHEMA_VERSION = (
    "agent_capsule_image_qualification@1"
)
DEFAULT_AGENT_CAPSULE_IMAGE_FAMILY = "openzyme-agent-capsule"
_DIGEST_PINNED_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_VERSIONED_OUTPUT_IMAGE = re.compile(
    r"(?:localhost/)?openzyme-agent-capsule:[0-9]+\.[0-9]+\.[0-9]+"
)


class AgentCapsuleImageError(RuntimeError):
    error_code = "agent_capsule_image_error"


class AgentCapsuleImageQualificationError(AgentCapsuleImageError):
    error_code = "agent_capsule_image_qualification_failed"


@dataclass(frozen=True, slots=True)
class AgentCapsuleImageManifest:
    schema_version: str
    image_family: str
    image_version: str
    runtime_uid: int
    runtime_gid: int
    home: str
    workspace_mount: str
    clone_logical_root: str
    base_image_requirement: str
    debian_snapshot: str
    package_versions: tuple[tuple[str, str], ...]
    required_binaries: tuple[str, ...]
    qualification_entrypoint: str
    forbidden_mount_classes: tuple[str, ...]
    network_contract: str
    credential_persistence: str

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_CAPSULE_IMAGE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported agent capsule image manifest schema")
        if self.image_family != DEFAULT_AGENT_CAPSULE_IMAGE_FAMILY:
            raise ValueError("unexpected agent capsule image family")
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.image_version) is None:
            raise ValueError("agent capsule image_version must be semantic")
        if self.runtime_uid <= 0 or self.runtime_gid <= 0:
            raise ValueError("agent capsule runtime identity must be non-root")
        if self.base_image_requirement != "oci_digest_pinned":
            raise ValueError("agent capsule base image must be digest pinned")
        required_packages = {"git", "git-lfs", "openssh-client", "rsync", "curl"}
        if not required_packages.issubset(dict(self.package_versions)):
            raise ValueError("agent capsule manifest omits required package versions")
        required_binaries = {"git", "git-lfs", "ssh", "rsync", "scp", "curl"}
        if not required_binaries.issubset(self.required_binaries):
            raise ValueError("agent capsule manifest omits required binaries")
        if self.network_contract != "deployment_ordinary_network":
            raise ValueError("agent capsule network contract is not ordinary network")
        if self.credential_persistence != "forbidden":
            raise ValueError("agent capsule credential persistence must be forbidden")

    @property
    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "image_family": self.image_family,
            "image_version": self.image_version,
            "runtime_uid": self.runtime_uid,
            "runtime_gid": self.runtime_gid,
            "home": self.home,
            "workspace_mount": self.workspace_mount,
            "clone_logical_root": self.clone_logical_root,
            "base_image_requirement": self.base_image_requirement,
            "debian_snapshot": self.debian_snapshot,
            "package_versions": dict(self.package_versions),
            "required_binaries": list(self.required_binaries),
            "qualification_entrypoint": self.qualification_entrypoint,
            "forbidden_mount_classes": list(self.forbidden_mount_classes),
            "network_contract": self.network_contract,
            "credential_persistence": self.credential_persistence,
        }

    @property
    def manifest_digest(self) -> str:
        encoded = json.dumps(
            self.canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class AgentCapsuleImageQualification:
    image_ref: str
    image_manifest_digest: str
    qualification_output_digest: str
    qualified_at: str
    schema_version: str = AGENT_CAPSULE_IMAGE_QUALIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_CAPSULE_IMAGE_QUALIFICATION_SCHEMA_VERSION:
            raise ValueError("unsupported capsule qualification schema")
        _require_digest_pinned_image(self.image_ref, field_name="image_ref")
        for value, field_name in (
            (self.image_manifest_digest, "image_manifest_digest"),
            (self.qualification_output_digest, "qualification_output_digest"),
        ):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
                raise ValueError(f"{field_name} must be a sha256 digest")
        if not self.qualified_at:
            raise ValueError("qualified_at must not be empty")


@dataclass(frozen=True, slots=True)
class CapsuleCommandResult:
    returncode: int
    stdout: str
    stderr: str


class CapsuleCommandExecutor(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str] | None = None,
    ) -> CapsuleCommandResult: ...


@dataclass(frozen=True, slots=True)
class SubprocessCapsuleCommandExecutor:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str] | None = None,
    ) -> CapsuleCommandResult:
        process_environment = None
        if environment is not None:
            process_environment = {
                key: value
                for key, value in os.environ.items()
                if key
                in {
                    "CONTAINERS_CONF",
                    "DBUS_SESSION_BUS_ADDRESS",
                    "HOME",
                    "PATH",
                    "XDG_CONFIG_HOME",
                    "XDG_DATA_HOME",
                    "XDG_RUNTIME_DIR",
                }
            }
            process_environment.update(environment)
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            env=process_environment,
        )
        return CapsuleCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def load_agent_capsule_image_manifest() -> AgentCapsuleImageManifest:
    resource = files("openzyme_core.agent_capsule_assets").joinpath("manifest.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AgentCapsuleImageError("agent capsule manifest must be an object")
    package_versions = payload.get("package_versions")
    if not isinstance(package_versions, dict):
        raise AgentCapsuleImageError("package_versions must be an object")
    return AgentCapsuleImageManifest(
        schema_version=str(payload["schema_version"]),
        image_family=str(payload["image_family"]),
        image_version=str(payload["image_version"]),
        runtime_uid=int(payload["runtime_uid"]),
        runtime_gid=int(payload["runtime_gid"]),
        home=str(payload["home"]),
        workspace_mount=str(payload["workspace_mount"]),
        clone_logical_root=str(payload["clone_logical_root"]),
        base_image_requirement=str(payload["base_image_requirement"]),
        debian_snapshot=str(payload["debian_snapshot"]),
        package_versions=tuple(
            sorted((str(key), str(value)) for key, value in package_versions.items())
        ),
        required_binaries=tuple(str(item) for item in payload["required_binaries"]),
        qualification_entrypoint=str(payload["qualification_entrypoint"]),
        forbidden_mount_classes=tuple(
            str(item) for item in payload["forbidden_mount_classes"]
        ),
        network_contract=str(payload["network_contract"]),
        credential_persistence=str(payload["credential_persistence"]),
    )


def build_agent_capsule_image(
    *,
    base_image_ref: str,
    output_image_ref: str,
    executor: CapsuleCommandExecutor,
    podman_binary: str = "podman",
) -> None:
    _require_digest_pinned_image(base_image_ref, field_name="base_image_ref")
    if _VERSIONED_OUTPUT_IMAGE.fullmatch(output_image_ref) is None:
        raise AgentCapsuleImageError(
            "output image must use the versioned openzyme-agent-capsule family"
        )
    manifest = load_agent_capsule_image_manifest()
    asset_root = files("openzyme_core.agent_capsule_assets")
    containerfile = asset_root.joinpath("Containerfile")
    with as_file(asset_root) as context_path, as_file(containerfile) as file_path:
        result = executor.run(
            (
                podman_binary,
                "build",
                "--pull=never",
                "--build-arg",
                f"BASE_IMAGE={base_image_ref}",
                "--label",
                f"io.openzyme.agent_capsule_manifest={manifest.manifest_digest}",
                "--tag",
                output_image_ref,
                "--file",
                str(file_path),
                str(context_path),
            )
        )
    if result.returncode != 0:
        raise AgentCapsuleImageError(
            f"agent capsule image build failed: {result.stderr.strip()}"
        )


def qualify_agent_capsule_image(
    *,
    image_ref: str,
    executor: CapsuleCommandExecutor,
    podman_binary: str = "podman",
    qualified_at: str | None = None,
) -> AgentCapsuleImageQualification:
    _require_digest_pinned_image(image_ref, field_name="image_ref")
    manifest = load_agent_capsule_image_manifest()
    result = executor.run(
        (
            podman_binary,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--user",
            f"{manifest.runtime_uid}:{manifest.runtime_gid}",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,uid=10001,gid=10001,mode=0700",
            "--tmpfs",
            "/workspace/repository:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700",
            "--workdir",
            manifest.clone_logical_root,
            image_ref,
            manifest.qualification_entrypoint,
        )
    )
    if result.returncode != 0:
        raise AgentCapsuleImageQualificationError(
            "agent capsule image qualification failed with native exit "
            f"{result.returncode}: {result.stderr.strip()}"
        )
    output = f"{result.stdout}\n{result.stderr}".encode("utf-8")
    return AgentCapsuleImageQualification(
        image_ref=image_ref,
        image_manifest_digest=manifest.manifest_digest,
        qualification_output_digest=f"sha256:{hashlib.sha256(output).hexdigest()}",
        qualified_at=qualified_at or datetime.now(tz=UTC).isoformat(),
    )


def _require_digest_pinned_image(value: str, *, field_name: str) -> None:
    if _DIGEST_PINNED_IMAGE.fullmatch(value) is None:
        raise AgentCapsuleImageError(f"{field_name} must be an OCI digest-pinned ref")


__all__ = [
    "AGENT_CAPSULE_IMAGE_MANIFEST_SCHEMA_VERSION",
    "AGENT_CAPSULE_IMAGE_QUALIFICATION_SCHEMA_VERSION",
    "AgentCapsuleImageError",
    "AgentCapsuleImageManifest",
    "AgentCapsuleImageQualification",
    "AgentCapsuleImageQualificationError",
    "CapsuleCommandExecutor",
    "CapsuleCommandResult",
    "DEFAULT_AGENT_CAPSULE_IMAGE_FAMILY",
    "SubprocessCapsuleCommandExecutor",
    "build_agent_capsule_image",
    "load_agent_capsule_image_manifest",
    "qualify_agent_capsule_image",
]
