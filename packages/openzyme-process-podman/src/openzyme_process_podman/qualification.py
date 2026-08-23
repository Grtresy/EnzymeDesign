from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Protocol

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalBoundQualificationOperationPort
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOperationObservation
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationRouteOutcome
from openzyme_contracts import ExternalScientificQualificationWorkload
from openzyme_contracts import canonical_sha256_digest


PODMAN_QUALIFICATION_OPERATIONS = (
    "container-start",
    "create",
    "delete",
    "exec",
    "mount",
    "read",
    "retire",
    "timeout",
    "update",
)


class PodmanQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    qualification_isolated: bool
    image_digest_pinned: bool


class PodmanQualificationCommandPort(Protocol):
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]: ...


class ScientificQualificationInputResolver(Protocol):
    def resolve(self, content_digest: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SubprocessPodmanQualificationCommandPort:
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        return completed.returncode, completed.stdout, completed.stderr


@dataclass(slots=True)
class PodmanQualificationState:
    image_digest: str
    container_name: str
    workspace: Path = field(repr=False)
    command_port: PodmanQualificationCommandPort = field(repr=False)

    def __post_init__(self) -> None:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_digest) is None:
            raise ValueError("Podman qualification image must be digest-pinned")
        if re.fullmatch(r"openzyme-qualification-[a-z0-9-]{1,80}", self.container_name) is None:
            raise ValueError("Podman qualification container name is invalid")
        workspace = self.workspace.absolute()
        if workspace.is_symlink():
            raise ValueError("Podman qualification workspace cannot be a symlink")
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        workspace.chmod(0o700)
        object.__setattr__(self, "workspace", workspace)

    def cleanup(self) -> dict[str, object]:
        returncode, _stdout, _stderr = self.command_port.run(
            ("podman", "rm", "-f", self.container_name)
        )
        return {
            "container_absent": returncode in {0, 1, 125},
            "container_name_digest": canonical_sha256_digest(
                {"container_name": self.container_name}
            ),
        }


@dataclass(slots=True)
class SubprocessPodmanQualificationOperation:
    component_id: str
    route_id: str
    subject_digest: str
    state: PodmanQualificationState = field(repr=False)
    qualification_isolated: bool = True
    image_digest_pinned: bool = True

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation:
        try:
            self._execute(request.operation)
        except (OSError, subprocess.SubprocessError, ExternalQualificationError) as exc:
            return self._observation(
                request,
                succeeded=False,
                error_code=getattr(exc, "error_code", "qualification_podman_operation_failed"),
            )
        return self._observation(request, succeeded=True)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation:
        raise ExternalQualificationError(
            "qualification_probe_reconcile_without_dispatch",
            "terminal Podman qualification operation does not require reconcile",
        )

    def _run(self, *argv: str, expected: frozenset[int] = frozenset({0})) -> str:
        returncode, stdout, _stderr = self.state.command_port.run(tuple(argv))
        if returncode not in expected:
            raise ExternalQualificationError(
                "qualification_podman_command_failed",
                "isolated Podman qualification command failed",
            )
        return stdout.strip()

    def _execute(self, operation: str) -> None:
        name = self.state.container_name
        workspace = str(self.state.workspace)
        if operation == "container-start":
            self._run(
                "podman",
                "run",
                "-d",
                "--name",
                name,
                "--label",
                "openzyme.qualification=batch-1",
                "--memory",
                "2g",
                "--network",
                "none",
                "-v",
                f"{workspace}:/qualification:Z",
                self.state.image_digest,
                "sleep",
                "600",
            )
        elif operation == "mount":
            output = self._run("podman", "inspect", name)
            if "/qualification" not in output:
                raise ExternalQualificationError(
                    "qualification_podman_mount_missing",
                    "Podman qualification mount was not observed",
                )
        elif operation == "create":
            self._run("podman", "exec", name, "sh", "-lc", "printf create > /qualification/item")
        elif operation == "read":
            if self._run("podman", "exec", name, "cat", "/qualification/item") != "create":
                raise ExternalQualificationError(
                    "qualification_podman_read_mismatch",
                    "Podman qualification read returned unexpected content",
                )
        elif operation == "update":
            self._run("podman", "exec", name, "sh", "-lc", "printf update > /qualification/item")
        elif operation == "delete":
            self._run("podman", "exec", name, "rm", "/qualification/item")
        elif operation == "exec":
            if self._run("podman", "exec", name, "printf", "OPENZYME_PODMAN_OK") != "OPENZYME_PODMAN_OK":
                raise ExternalQualificationError(
                    "qualification_podman_exec_mismatch",
                    "Podman qualification exec returned unexpected output",
                )
        elif operation == "timeout":
            self._run(
                "podman",
                "exec",
                name,
                "timeout",
                "1",
                "sleep",
                "5",
                expected=frozenset({124}),
            )
        elif operation == "retire":
            self._run("podman", "rm", "-f", name)
        else:
            raise ExternalQualificationError(
                "qualification_podman_operation_unsupported",
                "Podman qualification operation is unsupported",
            )

    @staticmethod
    def _observation(
        request: ExternalQualificationProbeRequest,
        *,
        succeeded: bool,
        error_code: str | None = None,
    ) -> ExternalQualificationOperationObservation:
        payload = {
            "attempt_id": request.attempt_id,
            "operation": request.operation,
            "succeeded": succeeded,
            "qualification_isolated": True,
        }
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty="terminal_known",
            terminal=True,
            succeeded=succeeded,
            output_digest=canonical_sha256_digest(payload) if succeeded else None,
            receipt_digest=canonical_sha256_digest(payload),
            error_code=error_code,
            external_effect_performed=True,
            credential_material_accessed=False,
            fallback_performed=False,
        )


@dataclass(slots=True)
class PodmanScientificQualificationRoute:
    image_digest: str
    workspace_root: Path = field(repr=False)
    command_port: PodmanQualificationCommandPort = field(repr=False)
    input_resolver: ScientificQualificationInputResolver = field(repr=False)
    route_kind: str = "local"

    def __post_init__(self) -> None:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_digest) is None:
            raise ValueError("scientific Podman route requires a pinned image digest")
        root = self.workspace_root.absolute()
        if root.is_symlink():
            raise ValueError("scientific Podman workspace cannot be a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        object.__setattr__(self, "workspace_root", root)

    def dispatch(
        self,
        workload: ExternalScientificQualificationWorkload,
    ) -> ExternalScientificQualificationRouteOutcome:
        run_root = self.workspace_root / workload.workload_id
        if run_root.exists() or run_root.is_symlink():
            return self._failure(
                workload,
                "qualification_compute_workspace_collision",
                effect_certainty="no_effect",
                external_effect_performed=False,
            )
        run_root.mkdir(mode=0o700)
        try:
            for item in workload.inputs:
                content = self.input_resolver.resolve(item.content_digest)
                if len(content) != item.size_bytes or canonical_sha256_digest(
                    {"content_hex": content.hex()}
                ) != item.content_digest:
                    raise ExternalQualificationError(
                        "qualification_compute_input_digest_mismatch",
                        "scientific qualification input bytes drifted",
                    )
                path = run_root / workload.cwd / item.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            for output_path in workload.expected_output_paths:
                (run_root / workload.cwd / output_path).parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
            workdir = f"/work/{workload.cwd}"
            if workload.operation == "hmmsearch":
                setup = self._run_container(
                    workload,
                    run_root,
                    (
                        "hmmbuild",
                        "inputs/model.hmm",
                        "inputs/alignment.fasta",
                    ),
                    workdir,
                    suffix="setup",
                )
                if setup != 0:
                    return self._failure(workload, "qualification_compute_setup_failed")
            returncode = self._run_container(
                workload,
                run_root,
                workload.argv,
                workdir,
                suffix="run",
            )
            if returncode != 0:
                return self._failure(workload, "qualification_compute_process_failed")
            outputs: list[dict[str, object]] = []
            for output_path in workload.expected_output_paths:
                path = run_root / workload.cwd / output_path
                if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
                    return self._failure(
                        workload,
                        "qualification_compute_expected_output_missing",
                    )
                outputs.append(
                    {
                        "path": output_path,
                        "size_bytes": path.stat().st_size,
                        "content_digest": canonical_sha256_digest(
                            {"content_hex": path.read_bytes().hex()}
                        ),
                    }
                )
            payload = {
                "workload_digest": workload.workload_digest,
                "image_digest": self.image_digest,
                "outputs": outputs,
                "route_kind": self.route_kind,
            }
            return ExternalScientificQualificationRouteOutcome(
                workload_digest=workload.workload_digest,
                effect_certainty="terminal_known",
                terminal=True,
                succeeded=True,
                output_digest=canonical_sha256_digest(payload),
                receipt_digest=canonical_sha256_digest(
                    {**payload, "container_retired": True}
                ),
                error_code=None,
                external_effect_performed=True,
                credential_material_accessed=False,
            )
        except (OSError, subprocess.SubprocessError, ExternalQualificationError) as exc:
            return self._failure(
                workload,
                getattr(exc, "error_code", "qualification_compute_route_failed"),
            )
        finally:
            if run_root.exists() and not run_root.is_symlink():
                shutil.rmtree(run_root)

    def reconcile(
        self,
        workload: ExternalScientificQualificationWorkload,
    ) -> ExternalScientificQualificationRouteOutcome:
        return self._failure(
            workload,
            "qualification_compute_reconcile_without_dispatch",
            effect_certainty="no_effect",
            external_effect_performed=False,
        )

    def _run_container(
        self,
        workload: ExternalScientificQualificationWorkload,
        run_root: Path,
        argv: tuple[str, ...],
        workdir: str,
        *,
        suffix: str,
    ) -> int:
        name_suffix = workload.workload_digest.removeprefix("sha256:")[:20]
        returncode, _stdout, _stderr = self.command_port.run(
            (
                "podman",
                "run",
                "--rm",
                "--name",
                f"openzyme-qualification-{name_suffix}-{suffix}",
                "--label",
                "openzyme.qualification=batch-1-scientific",
                "--memory",
                "2g",
                "--network",
                "none",
                "-v",
                f"{run_root}:/work:Z",
                "--workdir",
                workdir,
                self.image_digest,
                *argv,
            )
        )
        return returncode

    @staticmethod
    def _failure(
        workload: ExternalScientificQualificationWorkload,
        error_code: str,
        *,
        effect_certainty: str = "terminal_known",
        external_effect_performed: bool = True,
    ) -> ExternalScientificQualificationRouteOutcome:
        return ExternalScientificQualificationRouteOutcome(
            workload_digest=workload.workload_digest,
            effect_certainty=effect_certainty,
            terminal=True,
            succeeded=False,
            output_digest=None,
            receipt_digest=None,
            error_code=error_code,
            external_effect_performed=external_effect_performed,
            credential_material_accessed=False,
        )


@dataclass(slots=True)
class PodmanQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: PodmanQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.process.podman":
            raise ValueError("Podman bridge requires the selected Adapter binding")
        if (
            self.operation_port.component_id != self.binding.component_id
            or self.operation_port.route_id != self.binding.route_id
            or self.operation_port.subject_digest != self.binding.subject_digest
            or not self.operation_port.qualification_isolated
            or not self.operation_port.image_digest_pinned
        ):
            raise ValueError(
                "Podman qualification port must bind one isolated digest-pinned subject"
            )
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=PODMAN_QUALIFICATION_OPERATIONS,
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
    "PODMAN_QUALIFICATION_OPERATIONS",
    "PodmanQualificationOperationPort",
    "PodmanQualificationProbeBridge",
    "PodmanQualificationCommandPort",
    "PodmanQualificationState",
    "PodmanScientificQualificationRoute",
    "ScientificQualificationInputResolver",
    "SubprocessPodmanQualificationCommandPort",
    "SubprocessPodmanQualificationOperation",
]
