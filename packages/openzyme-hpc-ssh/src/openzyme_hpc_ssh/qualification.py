from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import os
from pathlib import Path
import re
import subprocess
from typing import Protocol

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalBoundQualificationOperationPort
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import canonical_sha256_digest


SSH_QUALIFICATION_OPERATIONS = (
    "create",
    "delete",
    "exec",
    "helper-identity",
    "read",
    "response-loss-reconcile",
    "update",
    "version",
)

_REMOTE_IDENTITY_SCRIPT = """set -eu
uname -srm | head -n 1
sinfo -h -p 3090 -o '%P' | head -n 1
hmmbuild -h 2>&1 | head -n 1
vina --version 2>&1 | head -n 1
fpocket -h 2>&1 | head -n 1
"""


class SshQualificationCredentialMaterial(Protocol):
    locator_id: str
    locator_version: str
    material_kind: str

    def field_value(self, field_name: str) -> str: ...


@dataclass(frozen=True, slots=True)
class SshHpcIdentityObservation:
    host_alias: str
    ssh_port: int
    partition: str
    environment_digest: str
    inventory_generation_digest: str
    software_versions: tuple[tuple[str, str], ...]

    def software_version(self, software_id: str) -> str:
        return dict(self.software_versions)[software_id]


class OpenSshQualificationCommandPort(Protocol):
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]: ...


@dataclass(frozen=True, slots=True)
class SubprocessOpenSshQualificationCommandPort:
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        return completed.returncode, completed.stdout, completed.stderr


@dataclass(frozen=True, slots=True)
class OpenSshHpcQualificationIdentityObservationPort:
    command_port: OpenSshQualificationCommandPort = field(repr=False)
    ssh_binary: str = "ssh"

    def observe(
        self,
        *,
        host_alias: str,
        partition: str,
        credential_material: SshQualificationCredentialMaterial,
    ) -> SshHpcIdentityObservation:
        if host_alias != "Diannan" or partition != "3090":
            raise ExternalQualificationError(
                "qualification_hpc_target_identity_mismatch",
                "SSH identity discovery is frozen to Diannan/3090",
            )
        host = credential_material.field_value("ssh_host")
        user = credential_material.field_value("ssh_user")
        raw_port = credential_material.field_value("ssh_port")
        identity_file = Path(
            credential_material.field_value("identity_file")
        ).absolute()
        known_hosts_file = Path(
            credential_material.field_value("known_hosts_file")
        ).absolute()
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,254}", host) is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", user) is None
            or re.fullmatch(r"[1-9][0-9]{0,4}", raw_port) is None
            or not identity_file.is_file()
            or identity_file.is_symlink()
            or not known_hosts_file.is_file()
            or known_hosts_file.is_symlink()
        ):
            raise ExternalQualificationError(
                "qualification_hpc_credential_identity_invalid",
                "SSH identity material is incomplete or unsafe",
            )
        ssh_port = int(raw_port)
        if ssh_port > 65535:
            raise ExternalQualificationError(
                "qualification_hpc_credential_identity_invalid",
                "SSH identity material is incomplete or unsafe",
            )
        if identity_file.stat().st_mode & 0o077:
            raise ExternalQualificationError(
                "qualification_hpc_identity_file_permissions_unsafe",
                "SSH qualification identity file must not be accessible by group or others",
            )
        argv = (
            self.ssh_binary,
            "-F",
            "/dev/null",
            "-p",
            str(ssh_port),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"IdentityFile={identity_file}",
            "-o",
            f"UserKnownHostsFile={known_hosts_file}",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=15",
            f"{user}@{host}",
            "sh",
            "-lc",
            _REMOTE_IDENTITY_SCRIPT,
        )
        returncode, stdout, _stderr = self.command_port.run(argv)
        lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
        if returncode != 0 or len(lines) != 5 or "3090" not in lines[1]:
            raise ExternalQualificationError(
                "qualification_hpc_identity_observation_failed",
                "SSH target identity observation failed or returned an unexpected shape",
            )
        environment_digest = canonical_sha256_digest(
            {
                "target_alias": host_alias,
                "ssh_port": ssh_port,
                "partition": partition,
                "system": lines[0],
            }
        )
        inventory_digest = canonical_sha256_digest(
            {
                "environment_digest": environment_digest,
                "partition_observation": lines[1],
                "hmmer_version_observation": lines[2],
                "vina_version_observation": lines[3],
                "fpocket_version_observation": lines[4],
            }
        )
        return SshHpcIdentityObservation(
            host_alias=host_alias,
            ssh_port=ssh_port,
            partition=partition,
            environment_digest=environment_digest,
            inventory_generation_digest=inventory_digest,
            software_versions=(
                ("software.fpocket", lines[4]),
                ("software.hmmer", lines[2]),
                ("software.vina", lines[3]),
            ),
        )


class SshQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    qualification_workspace_only: bool
    same_attempt_reconcile: bool


@dataclass(slots=True)
class SshQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: SshQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.hpc.ssh":
            raise ValueError("SSH bridge requires the selected Adapter binding")
        if (
            self.operation_port.component_id != self.binding.component_id
            or self.operation_port.route_id != self.binding.route_id
            or self.operation_port.subject_digest != self.binding.subject_digest
            or not self.operation_port.qualification_workspace_only
            or not self.operation_port.same_attempt_reconcile
        ):
            raise ValueError(
                "SSH qualification port must bind one exact qualification workspace"
            )
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=SSH_QUALIFICATION_OPERATIONS,
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
    "SSH_QUALIFICATION_OPERATIONS",
    "OpenSshHpcQualificationIdentityObservationPort",
    "OpenSshQualificationCommandPort",
    "SshQualificationOperationPort",
    "SshQualificationProbeBridge",
    "SshHpcIdentityObservation",
    "SshQualificationCredentialMaterial",
    "SubprocessOpenSshQualificationCommandPort",
]
