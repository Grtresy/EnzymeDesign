from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Protocol

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalBoundQualificationOperationPort
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOperationObservation
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

DIANNAN_WORKSPACE_RUNTIME_PATH = (
    "/home/grtresy/.local/libexec/openzyme-workspace-runtime"
)
DIANNAN_WORKSPACE_RUNTIME_PARENT = (
    "/home/grtresy/.local/state/openzyme-executor-workspaces"
)
DIANNAN_WORKSPACE_RUNTIME_POLICY_ID = (
    "policy.openzyme.hpc.diannan.workspace-runtime"
)


def _safe_remote_absolute_path(value: str) -> bool:
    return (
        value.startswith("/")
        and value != "/"
        and not value.endswith("/")
        and re.fullmatch(r"/[A-Za-z0-9._/-]{1,254}", value) is not None
        and all(segment not in {"", ".", ".."} for segment in value[1:].split("/"))
    )

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
    software_image_digests: tuple[tuple[str, str], ...]
    apptainer_version: str

    def software_version(self, software_id: str) -> str:
        return dict(self.software_versions)[software_id]

    def software_image_digest(self, software_id: str) -> str:
        return dict(self.software_image_digests)[software_id]


@dataclass(frozen=True, slots=True)
class SshWorkspaceRuntimeQualificationIdentity:
    helper_path: str
    workspace_parent: str
    policy_id: str
    helper_version: str
    helper_build_digest: str
    root_policy_digest: str
    principal_identity_digest: str
    deployment_plan_digest: str
    deployment_receipt_digest: str
    native_qualification_digest: str
    file_owner: str
    file_group: str
    file_mode: str
    observation_digest: str

    def __post_init__(self) -> None:
        if (
            self.helper_path != DIANNAN_WORKSPACE_RUNTIME_PATH
            or self.workspace_parent != DIANNAN_WORKSPACE_RUNTIME_PARENT
            or self.policy_id != DIANNAN_WORKSPACE_RUNTIME_POLICY_ID
            or self.helper_version != "1.0.0"
            or self.file_owner != "grtresy"
            or self.file_group != "grtresy"
            or self.file_mode != "755"
        ):
            raise ValueError("workspace runtime qualification identity is not exact")
        for field_name in (
            "helper_build_digest",
            "root_policy_digest",
            "principal_identity_digest",
            "deployment_plan_digest",
            "deployment_receipt_digest",
            "native_qualification_digest",
            "observation_digest",
        ):
            value = getattr(self, field_name)
            if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
                raise ValueError(f"{field_name} is not a canonical digest")
        if self.observation_digest != canonical_sha256_digest(
            self.observation_payload
        ):
            raise ValueError("workspace runtime observation digest drifted")

    @property
    def observation_payload(self) -> dict[str, str]:
        return {
            "helper_path": self.helper_path,
            "workspace_parent": self.workspace_parent,
            "policy_id": self.policy_id,
            "helper_version": self.helper_version,
            "helper_build_digest": self.helper_build_digest,
            "root_policy_digest": self.root_policy_digest,
            "principal_identity_digest": self.principal_identity_digest,
            "deployment_plan_digest": self.deployment_plan_digest,
            "deployment_receipt_digest": self.deployment_receipt_digest,
            "native_qualification_digest": self.native_qualification_digest,
            "file_owner": self.file_owner,
            "file_group": self.file_group,
            "file_mode": self.file_mode,
        }

    @property
    def identity_payload(self) -> dict[str, str]:
        return {**self.observation_payload, "observation_digest": self.observation_digest}


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
            timeout=120,
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
        software_images = {
            "software.hmmer": credential_material.field_value("hmmer_sif"),
            "software.vina": credential_material.field_value("vina_sif"),
            "software.fpocket": credential_material.field_value("fpocket_sif"),
        }
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,254}", host) is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", user) is None
            or re.fullmatch(r"[1-9][0-9]{0,4}", raw_port) is None
            or not identity_file.is_file()
            or identity_file.is_symlink()
            or not known_hosts_file.is_file()
            or known_hosts_file.is_symlink()
            or any(not _safe_remote_absolute_path(path) for path in software_images.values())
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
        hmmer_image = shlex.quote(software_images["software.hmmer"])
        vina_image = shlex.quote(software_images["software.vina"])
        fpocket_image = shlex.quote(software_images["software.fpocket"])
        remote_identity_script = f"""set -eu
system=$(uname -srm | head -n 1)
partition=$(sinfo -h -p 3090 -o '%P' | head -n 1)
apptainer_version=$(apptainer --version | head -n 1)
hmmer_digest=$(sha256sum {hmmer_image} | cut -d' ' -f1)
hmmer_version=$(apptainer exec {hmmer_image} hmmbuild -h 2>&1 | grep -m1 '^# HMMER ')
vina_digest=$(sha256sum {vina_image} | cut -d' ' -f1)
vina_version=$(apptainer exec {vina_image} vina --version 2>&1 | head -n 1)
fpocket_digest=$(sha256sum {fpocket_image} | cut -d' ' -f1)
fpocket_version=$(apptainer exec {fpocket_image} fpocket -h 2>&1 | sed 's/\\x1B\\[[0-9;]*[mK]//g' | grep -m1 'fpocket [0-9]')
printf '%s\\n' "$system" "$partition" "$apptainer_version" "$hmmer_digest" "$hmmer_version" "$vina_digest" "$vina_version" "$fpocket_digest" "$fpocket_version"
"""
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
            "bash",
            "-lc",
            shlex.quote(remote_identity_script),
        )
        returncode, stdout, _stderr = self.command_port.run(argv)
        lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
        if (
            returncode != 0
            or len(lines) != 9
            or "3090" not in lines[1]
            or not lines[2].startswith(("apptainer version ", "apptainer version"))
            or any(re.fullmatch(r"[0-9a-f]{64}", lines[index]) is None for index in (3, 5, 7))
        ):
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
                "apptainer_version_observation": lines[2],
                "hmmer_image_digest": lines[3],
                "hmmer_version_observation": lines[4],
                "vina_image_digest": lines[5],
                "vina_version_observation": lines[6],
                "fpocket_image_digest": lines[7],
                "fpocket_version_observation": lines[8],
            }
        )
        return SshHpcIdentityObservation(
            host_alias=host_alias,
            ssh_port=ssh_port,
            partition=partition,
            environment_digest=environment_digest,
            inventory_generation_digest=inventory_digest,
            software_versions=(
                ("software.fpocket", lines[8]),
                ("software.hmmer", lines[4]),
                ("software.vina", lines[6]),
            ),
            software_image_digests=(
                ("software.fpocket", f"sha256:{lines[7]}"),
                ("software.hmmer", f"sha256:{lines[3]}"),
                ("software.vina", f"sha256:{lines[5]}"),
            ),
            apptainer_version=lines[2],
        )


class SshQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    qualification_workspace_only: bool
    same_attempt_reconcile: bool


@dataclass(slots=True)
class OpenSshQualificationState:
    credential_material: SshQualificationCredentialMaterial = field(repr=False)
    workspace_id: str
    command_port: OpenSshQualificationCommandPort = field(repr=False)
    workspace_runtime_identity: SshWorkspaceRuntimeQualificationIdentity | None = None
    response_loss_token: str | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", self.workspace_id) is None:
            raise ValueError("SSH qualification workspace identity is invalid")
        self._connection_argv()

    @property
    def remote_workspace(self) -> str:
        workspace_root = self.credential_material.field_value("workspace_root")
        if (
            not workspace_root.startswith("/")
            or workspace_root == "/"
            or workspace_root.endswith("/")
            or any(
                segment in {"", ".", ".."}
                for segment in workspace_root[1:].split("/")
            )
            or re.fullmatch(r"/[A-Za-z0-9._/-]{1,190}", workspace_root) is None
        ):
            raise ExternalQualificationError(
                "qualification_hpc_workspace_root_invalid",
                "SSH qualification workspace root is not one protected absolute path",
            )
        return f"{workspace_root}/{self.workspace_id}"

    def _connection_argv(self) -> tuple[str, ...]:
        host = self.credential_material.field_value("ssh_host")
        user = self.credential_material.field_value("ssh_user")
        port = self.credential_material.field_value("ssh_port")
        identity = Path(self.credential_material.field_value("identity_file")).absolute()
        known_hosts = Path(
            self.credential_material.field_value("known_hosts_file")
        ).absolute()
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,254}", host) is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", user) is None
            or re.fullmatch(r"[1-9][0-9]{0,4}", port) is None
            or int(port) > 65535
            or not identity.is_file()
            or identity.is_symlink()
            or identity.stat().st_mode & 0o077
            or not known_hosts.is_file()
            or known_hosts.is_symlink()
        ):
            raise ExternalQualificationError(
                "qualification_hpc_credential_identity_invalid",
                "SSH qualification identity material is incomplete or unsafe",
            )
        return (
            "ssh",
            "-F",
            "/dev/null",
            "-p",
            port,
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"IdentityFile={identity}",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=15",
            f"{user}@{host}",
        )

    def run_remote(self, script: str) -> tuple[int, str, str]:
        return self.command_port.run(
            (*self._connection_argv(), "bash", "-lc", shlex.quote(script))
        )

    def cleanup(self) -> dict[str, object]:
        workspace = self.remote_workspace
        script = (
            f"test -f {workspace}/.openzyme-qualification-owner && "
            f"test \"$(cat {workspace}/.openzyme-qualification-owner)\" = {self.workspace_id} && "
            f"rm -rf -- {workspace}"
        )
        returncode, _stdout, _stderr = self.run_remote(script)
        return {"workspace_removed": returncode == 0}


def observe_diannan_workspace_runtime_identity(
    *,
    state: OpenSshQualificationState,
    deployment_plan_digest: str,
    deployment_receipt_digest: str,
    native_qualification_digest: str,
) -> SshWorkspaceRuntimeQualificationIdentity:
    """Read the exact installed helper identity without mutating the target."""

    for value in (
        deployment_plan_digest,
        deployment_receipt_digest,
        native_qualification_digest,
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            raise ValueError("workspace runtime deployment evidence digest is invalid")
    helper = shlex.quote(DIANNAN_WORKSPACE_RUNTIME_PATH)
    parent = shlex.quote(DIANNAN_WORKSPACE_RUNTIME_PARENT)
    policy = shlex.quote(DIANNAN_WORKSPACE_RUNTIME_POLICY_ID)
    script = f"""set -eu
helper={helper}
test -f "$helper"
test ! -L "$helper"
owner=$(stat -c '%U' "$helper")
group=$(stat -c '%G' "$helper")
mode=$(stat -c '%a' "$helper")
version_output=$("$helper" version)
version=$(printf '%s\n' "$version_output" | sed -n 's/^OPENZYME_WORKSPACE_RUNTIME_VERSION=//p')
build=$(printf '%s\n' "$version_output" | sed -n 's/^OPENZYME_WORKSPACE_RUNTIME_BUILD_DIGEST=//p')
policy_output=$("$helper" policy-digest --policy-id {policy} --workspace-parent {parent})
root_policy=$(printf '%s\n' "$policy_output" | sed -n 's/^OPENZYME_ROOT_POLICY_DIGEST=//p')
principal=$(printf '%s\n' "$policy_output" | sed -n 's/^OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST=//p')
printf 'VERSION=%s\nBUILD=%s\nROOT_POLICY=%s\nPRINCIPAL=%s\nOWNER=%s\nGROUP=%s\nMODE=%s\n' "$version" "$build" "$root_policy" "$principal" "$owner" "$group" "$mode"
"""
    returncode, stdout, _stderr = state.run_remote(script)
    fields = dict(
        line.split("=", 1) for line in stdout.splitlines() if "=" in line
    )
    if (
        returncode != 0
        or set(fields)
        != {"VERSION", "BUILD", "ROOT_POLICY", "PRINCIPAL", "OWNER", "GROUP", "MODE"}
        or fields["VERSION"] != "1.0.0"
        or fields["OWNER"] != "grtresy"
        or fields["GROUP"] != "grtresy"
        or fields["MODE"] != "755"
        or any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", fields[field_name]) is None
            for field_name in ("BUILD", "ROOT_POLICY", "PRINCIPAL")
        )
    ):
        raise ExternalQualificationError(
            "qualification_workspace_runtime_identity_observation_failed",
            "workspace runtime identity observation failed or drifted",
        )
    identity = {
        "helper_path": DIANNAN_WORKSPACE_RUNTIME_PATH,
        "workspace_parent": DIANNAN_WORKSPACE_RUNTIME_PARENT,
        "policy_id": DIANNAN_WORKSPACE_RUNTIME_POLICY_ID,
        "helper_version": fields["VERSION"],
        "helper_build_digest": fields["BUILD"],
        "root_policy_digest": fields["ROOT_POLICY"],
        "principal_identity_digest": fields["PRINCIPAL"],
        "deployment_plan_digest": deployment_plan_digest,
        "deployment_receipt_digest": deployment_receipt_digest,
        "native_qualification_digest": native_qualification_digest,
        "file_owner": fields["OWNER"],
        "file_group": fields["GROUP"],
        "file_mode": fields["MODE"],
    }
    return SshWorkspaceRuntimeQualificationIdentity(
        **identity,
        observation_digest=canonical_sha256_digest(identity),
    )


@dataclass(slots=True)
class OpenSshQualificationOperation:
    component_id: str
    route_id: str
    subject_digest: str
    state: OpenSshQualificationState = field(repr=False)
    qualification_workspace_only: bool = True
    same_attempt_reconcile: bool = True

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation:
        try:
            if request.operation == "response-loss-reconcile":
                token = canonical_sha256_digest(
                    {"attempt_id": request.attempt_id}
                ).removeprefix("sha256:")
                self._run(
                    f"printf '%s' {token} > {self.state.remote_workspace}/response-loss"
                )
                self.state.response_loss_token = token
                return self._observation(
                    request,
                    terminal=False,
                    succeeded=False,
                    effect_certainty="dispatch_in_doubt",
                    error_code="qualification_response_lost_after_ssh_acceptance",
                )
            self._execute(request.operation)
        except (OSError, subprocess.SubprocessError, ExternalQualificationError) as exc:
            return self._observation(
                request,
                terminal=True,
                succeeded=False,
                effect_certainty="terminal_known",
                error_code=getattr(exc, "error_code", "qualification_ssh_operation_failed"),
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
        if request.operation != "response-loss-reconcile" or self.state.response_loss_token is None:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "SSH reconcile requires the exact response-loss dispatch",
            )
        output = self._run(f"cat {self.state.remote_workspace}/response-loss")
        succeeded = output == self.state.response_loss_token
        return self._observation(
            request,
            terminal=True,
            succeeded=succeeded,
            effect_certainty="terminal_known",
            error_code=None if succeeded else "qualification_ssh_reconcile_failed",
        )

    def restore_dispatched_attempt(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> None:
        if request.operation != "response-loss-reconcile":
            raise ExternalQualificationError(
                "qualification_probe_restore_not_reconcilable",
                "only the SSH response-loss operation can be restored",
            )
        self.state.response_loss_token = canonical_sha256_digest(
            {"attempt_id": request.attempt_id}
        ).removeprefix("sha256:")

    def _run(self, script: str) -> str:
        returncode, stdout, _stderr = self.state.run_remote(script)
        if returncode != 0:
            raise ExternalQualificationError(
                "qualification_ssh_command_failed",
                "SSH qualification command failed",
            )
        return stdout.strip()

    def _execute(self, operation: str) -> None:
        workspace = self.state.remote_workspace
        if operation == "helper-identity":
            expected = self.state.workspace_runtime_identity
            if expected is None:
                raise ExternalQualificationError(
                    "qualification_workspace_runtime_identity_missing",
                    "SSH helper qualification requires one exact deployed identity",
                )
            observed = observe_diannan_workspace_runtime_identity(
                state=self.state,
                deployment_plan_digest=expected.deployment_plan_digest,
                deployment_receipt_digest=expected.deployment_receipt_digest,
                native_qualification_digest=expected.native_qualification_digest,
            )
            if observed != expected:
                raise ExternalQualificationError(
                    "qualification_workspace_runtime_identity_drift",
                    "installed workspace runtime differs from the bound subject identity",
                )
        elif operation == "version":
            if not self._run("uname -srm"):
                raise ExternalQualificationError(
                    "qualification_ssh_version_failed",
                    "SSH target version observation is empty",
                )
        elif operation == "create":
            self._run(
                f"mkdir -p -m 700 {workspace}; printf '%s' {self.state.workspace_id} > {workspace}/.openzyme-qualification-owner; chmod 600 {workspace}/.openzyme-qualification-owner; printf create > {workspace}/item"
            )
        elif operation == "read":
            if self._run(f"cat {workspace}/item") != "create":
                raise ExternalQualificationError(
                    "qualification_ssh_read_mismatch",
                    "SSH qualification read returned unexpected content",
                )
        elif operation == "update":
            self._run(f"printf update > {workspace}/item")
        elif operation == "delete":
            self._run(f"rm -f {workspace}/item; test ! -e {workspace}/item")
        elif operation == "exec":
            if self._run("printf OPENZYME_SSH_OK") != "OPENZYME_SSH_OK":
                raise ExternalQualificationError(
                    "qualification_ssh_exec_mismatch",
                    "SSH qualification exec returned unexpected output",
                )
        else:
            raise ExternalQualificationError(
                "qualification_ssh_operation_unsupported",
                "SSH qualification operation is unsupported",
            )

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
            receipt_digest=canonical_sha256_digest({**payload, "target": "Diannan"}),
            error_code=error_code,
            external_effect_performed=True,
            credential_material_accessed=True,
            fallback_performed=False,
        )


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

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None:
        self._bridge.restore_dispatched_attempt(request)


__all__ = [
    "DIANNAN_WORKSPACE_RUNTIME_PARENT",
    "DIANNAN_WORKSPACE_RUNTIME_PATH",
    "DIANNAN_WORKSPACE_RUNTIME_POLICY_ID",
    "SSH_QUALIFICATION_OPERATIONS",
    "OpenSshHpcQualificationIdentityObservationPort",
    "OpenSshQualificationCommandPort",
    "OpenSshQualificationOperation",
    "OpenSshQualificationState",
    "SshQualificationOperationPort",
    "SshQualificationProbeBridge",
    "SshHpcIdentityObservation",
    "SshQualificationCredentialMaterial",
    "SshWorkspaceRuntimeQualificationIdentity",
    "SubprocessOpenSshQualificationCommandPort",
    "observe_diannan_workspace_runtime_identity",
]
