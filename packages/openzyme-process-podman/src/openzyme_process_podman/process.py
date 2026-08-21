from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import PurePosixPath
import re
import signal
import subprocess
import threading
import time
from typing import BinaryIO
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureObservation
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import RetryEligibility
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceOperationIdentity
from openzyme_contracts import WorkspaceOperationLedgerError
from openzyme_contracts import WorkspaceOperationLedgerPort
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_runtime_spi import IsolatedProcessState
from openzyme_runtime_spi import ProcessIsolationPort
from openzyme_runtime_spi import ProcessIsolationReceipt
from openzyme_runtime_spi import ProcessIsolationRequest


PODMAN_PROCESS_PROVIDER_ID = "openzyme.process.podman"
PODMAN_PROCESS_PROVIDER_CONTRACT = "openzyme.process.podman@1"
PODMAN_PROCESS_PROVIDER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": PODMAN_PROCESS_PROVIDER_CONTRACT,
        "mechanism": "rootless_podman_named_volume",
        "process": "foreground_bounded_argv",
        "fallback": False,
    }
)

_SAFE_PODMAN_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}")
_INFRASTRUCTURE_ENVIRONMENT = {
    "CONTAINERS_CONF",
    "DBUS_SESSION_BUS_ADDRESS",
    "HOME",
    "PATH",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_RUNTIME_DIR",
}


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _require_clone_root(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("/workspace")
        or (value != "/workspace" and not value.startswith("/workspace/"))
        or value.endswith("/")
        or "\\" in value
        or ".." in PurePosixPath(value).parts
    ):
        raise ValueError("clone_logical_root must remain below /workspace")


def _require_image_identity(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 2_048
        or "\x00" in value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("image_identity must be one bounded exact OCI reference")


def build_podman_command(
    *,
    podman_binary: str,
    deployment_network: str,
    runtime_uid: int,
    runtime_gid: int,
    mount: PodmanWorkspaceMount,
    process_identity: str,
    cwd_relative: str,
    environment_keys: tuple[str, ...],
    timeout_seconds: int,
    argv: tuple[str, ...],
) -> tuple[str, ...]:
    workdir = mount.clone_logical_root
    if cwd_relative != ".":
        workdir = f"{workdir}/{cwd_relative}"
    command = [
        podman_binary,
        "run",
        "--rm",
        "--name",
        process_identity,
        "--network",
        deployment_network,
        "--read-only",
        "--user",
        f"{runtime_uid}:{runtime_gid}",
        "--cap-drop=all",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        (
            "/tmp:rw,nosuid,nodev,noexec,"
            f"uid={runtime_uid},gid={runtime_gid},mode=0700"
        ),
        "--mount",
        f"type=volume,src={mount.volume_id},dst=/workspace,rw",
        "--workdir",
        workdir,
    ]
    for key in environment_keys:
        command.extend(("--env", key))
    command.extend(
        (
            mount.image_identity,
            "/usr/bin/timeout",
            "--signal=TERM",
            "--kill-after=5",
            str(timeout_seconds),
            *argv,
        )
    )
    return tuple(command)


@dataclass(frozen=True, slots=True)
class PodmanWorkspaceMount:
    workspace_id: str
    session_id: str
    owner_member_id: str
    generation: int
    state_version: int
    root_identity_digest: str
    target_id: str
    volume_id: str
    clone_logical_root: str
    image_identity: str
    mount_manifest_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "workspace_id",
            "session_id",
            "owner_member_id",
            "target_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.generation < 1 or self.state_version < 1:
            raise ValueError("workspace mount generation and state_version must be positive")
        require_digest(self.root_identity_digest, field_name="root_identity_digest")
        if _SAFE_PODMAN_NAME.fullmatch(self.volume_id) is None:
            raise ValueError("volume_id is not one exact Podman named volume")
        _require_clone_root(self.clone_logical_root)
        _require_image_identity(self.image_identity)
        require_digest(self.mount_manifest_digest, field_name="mount_manifest_digest")
        if self.mount_manifest_digest != canonical_sha256_digest(
            self.identity_payload()
        ):
            raise ValueError("mount_manifest_digest does not match the mount identity")

    def identity_payload(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "owner_member_id": self.owner_member_id,
            "generation": self.generation,
            "state_version": self.state_version,
            "root_identity_digest": self.root_identity_digest,
            "target_id": self.target_id,
            "volume_id": self.volume_id,
            "clone_logical_root": self.clone_logical_root,
            "image_identity": self.image_identity,
        }

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        session_id: str,
        owner_member_id: str,
        generation: int,
        state_version: int,
        root_identity_digest: str,
        target_id: str,
        volume_id: str,
        clone_logical_root: str,
        image_identity: str,
    ) -> PodmanWorkspaceMount:
        payload: dict[str, object] = {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "owner_member_id": owner_member_id,
            "generation": generation,
            "state_version": state_version,
            "root_identity_digest": root_identity_digest,
            "target_id": target_id,
            "volume_id": volume_id,
            "clone_logical_root": clone_logical_root,
            "image_identity": image_identity,
        }
        return cls(
            **payload,
            mount_manifest_digest=canonical_sha256_digest(payload),
        )

    def matches(self, binding: WorkspaceRuntimeBinding) -> bool:
        return (
            self.workspace_id == binding.workspace_id
            and self.session_id == binding.session_id
            and self.owner_member_id == binding.owner_member_id
            and self.generation == binding.generation
            and self.state_version == binding.state_version
            and self.root_identity_digest == binding.root_identity_digest
            and self.target_id == binding.target_id
        )


class PodmanWorkspaceMountResolver(Protocol):
    def resolve(
        self,
        binding: WorkspaceRuntimeBinding,
    ) -> PodmanWorkspaceMount | None: ...


@dataclass(frozen=True, slots=True)
class MappingPodmanWorkspaceMountResolver:
    mounts: Mapping[str, PodmanWorkspaceMount]

    def resolve(
        self,
        binding: WorkspaceRuntimeBinding,
    ) -> PodmanWorkspaceMount | None:
        mount = self.mounts.get(binding.workspace_id)
        if mount is None or not mount.matches(binding):
            return None
        return mount


class PodmanDispatchError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty,
    ) -> None:
        super().__init__(message)
        require_identifier(error_code, field_name="error_code")
        self.error_code = error_code
        self.effect_certainty = effect_certainty
        self.fallback_performed = False


@dataclass(frozen=True, slots=True)
class SupervisedProcessRequest:
    process_identity: str
    process_epoch: int
    authority_fence: int
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    stdin: bytes
    timeout_seconds: int
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class SupervisedProcessResult:
    process_identity: str
    returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    retired: bool
    started_at: str
    ended_at: str
    duration_ms: int


class PodmanCommandExecutor(Protocol):
    def run(self, request: SupervisedProcessRequest) -> SupervisedProcessResult: ...

    def retire(
        self,
        *,
        process_identity: str,
        process_epoch: int,
        authority_fence: int,
    ) -> SupervisedProcessResult: ...


@dataclass(slots=True)
class _ActiveProcess:
    process: subprocess.Popen[bytes]
    request: SupervisedProcessRequest
    started_at: str
    started_monotonic: float
    retired: bool = False


@dataclass(slots=True)
class _BoundedOutput:
    limit: int
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, stream_name: str, value: bytes) -> None:
        with self._lock:
            remaining = self.limit - len(self.stdout) - len(self.stderr)
            target = self.stdout if stream_name == "stdout" else self.stderr
            accepted = value[: max(0, remaining)]
            target.extend(accepted)
            if len(accepted) != len(value):
                if stream_name == "stdout":
                    self.stdout_truncated = True
                else:
                    self.stderr_truncated = True


@dataclass(slots=True)
class SupervisedSubprocessExecutor:
    termination_grace_seconds: float = 5.0
    _active: dict[str, _ActiveProcess] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def run(self, request: SupervisedProcessRequest) -> SupervisedProcessResult:
        started_at = _utc_now()
        started_monotonic = time.monotonic()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in _INFRASTRUCTURE_ENVIRONMENT
        }
        environment.update(request.environment)
        try:
            process = subprocess.Popen(
                request.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise PodmanDispatchError(
                "podman_process_not_started",
                "Podman process could not be started",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            ) from exc

        active = _ActiveProcess(
            process=process,
            request=request,
            started_at=started_at,
            started_monotonic=started_monotonic,
        )
        with self._lock:
            if request.process_identity in self._active:
                self._terminate(process)
                raise PodmanDispatchError(
                    "podman_process_identity_active",
                    "process identity is already active",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                )
            self._active[request.process_identity] = active

        output = _BoundedOutput(request.max_output_bytes)
        stdout_thread = threading.Thread(
            target=_drain_pipe,
            args=(process.stdout, "stdout", output),
            daemon=False,
        )
        stderr_thread = threading.Thread(
            target=_drain_pipe,
            args=(process.stderr, "stderr", output),
            daemon=False,
        )
        stdin_thread = threading.Thread(
            target=_write_stdin,
            args=(process.stdin, request.stdin),
            daemon=False,
        )
        stdout_thread.start()
        stderr_thread.start()
        stdin_thread.start()

        timed_out = False
        try:
            try:
                process.wait(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate(process)
        except Exception as exc:
            try:
                self._terminate(process)
            except Exception:
                pass
            raise PodmanDispatchError(
                "podman_process_settlement_unknown",
                "Podman process outcome could not be settled",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            ) from exc
        finally:
            stdin_thread.join(timeout=self.termination_grace_seconds)
            stdout_thread.join(timeout=self.termination_grace_seconds)
            stderr_thread.join(timeout=self.termination_grace_seconds)
            with self._lock:
                current = self._active.get(request.process_identity)
                if current is active:
                    self._active.pop(request.process_identity, None)

        if stdin_thread.is_alive() or stdout_thread.is_alive() or stderr_thread.is_alive():
            raise PodmanDispatchError(
                "podman_process_stream_settlement_unknown",
                "Podman process streams did not settle after process termination",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        ended_at = _utc_now()
        return SupervisedProcessResult(
            process_identity=request.process_identity,
            returncode=process.returncode,
            stdout=bytes(output.stdout),
            stderr=bytes(output.stderr),
            stdout_truncated=output.stdout_truncated,
            stderr_truncated=output.stderr_truncated,
            timed_out=timed_out,
            retired=active.retired,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1_000)),
        )

    def retire(
        self,
        *,
        process_identity: str,
        process_epoch: int,
        authority_fence: int,
    ) -> SupervisedProcessResult:
        with self._lock:
            active = self._active.get(process_identity)
            if active is None:
                raise PodmanDispatchError(
                    "podman_process_not_active",
                    "process identity is not active in this Adapter epoch",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                )
            if (
                active.request.process_epoch != process_epoch
                or active.request.authority_fence != authority_fence
            ):
                raise PodmanDispatchError(
                    "podman_process_retirement_fence_stale",
                    "process retirement uses a stale epoch or authority fence",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                )
            active.retired = True
        self._terminate(active.process)
        return SupervisedProcessResult(
            process_identity=process_identity,
            returncode=active.process.returncode,
            stdout=b"",
            stderr=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            retired=True,
            started_at=active.started_at,
            ended_at=_utc_now(),
            duration_ms=max(
                0,
                int((time.monotonic() - active.started_monotonic) * 1_000),
            ),
        )

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=self.termination_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=self.termination_grace_seconds)
        except subprocess.TimeoutExpired as exc:
            raise PodmanDispatchError(
                "podman_process_group_not_reaped",
                "process group did not terminate within the bounded grace period",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            ) from exc


def _drain_pipe(
    pipe: BinaryIO | None,
    stream_name: str,
    output: _BoundedOutput,
) -> None:
    if pipe is None:
        return
    try:
        while True:
            chunk = pipe.read(65_536)
            if not chunk:
                return
            output.append(stream_name, chunk)
    finally:
        pipe.close()


def _write_stdin(pipe: BinaryIO | None, value: bytes) -> None:
    if pipe is None:
        return
    try:
        if value:
            pipe.write(value)
            pipe.flush()
    except BrokenPipeError:
        pass
    finally:
        pipe.close()


@dataclass(slots=True)
class PodmanProcessIsolationAdapter(ProcessIsolationPort):
    mount_resolver: PodmanWorkspaceMountResolver
    deployment_network: str
    executor: PodmanCommandExecutor = field(default_factory=SupervisedSubprocessExecutor)
    podman_binary: str = "/usr/bin/podman"
    runtime_uid: int = 10_001
    runtime_gid: int = 10_001
    provider_id: str = PODMAN_PROCESS_PROVIDER_ID
    provider_contract_digest: str = PODMAN_PROCESS_PROVIDER_CONTRACT_DIGEST
    _requests: dict[str, ProcessIsolationRequest] = field(default_factory=dict)
    _terminal_receipts: dict[str, ProcessIsolationReceipt] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if _SAFE_PODMAN_NAME.fullmatch(self.deployment_network) is None:
            raise ValueError("deployment_network is not a safe Podman network name")
        if not self.podman_binary.startswith("/") or "\x00" in self.podman_binary:
            raise ValueError("podman_binary must be one exact absolute executable path")
        if self.runtime_uid < 1 or self.runtime_gid < 1:
            raise ValueError("runtime uid/gid must be positive")
        if self.provider_id != PODMAN_PROCESS_PROVIDER_ID:
            raise ValueError("Podman Adapter provider identity is closed")
        if self.provider_contract_digest != PODMAN_PROCESS_PROVIDER_CONTRACT_DIGEST:
            raise ValueError("Podman Adapter contract digest is closed")

    def execute(self, request: ProcessIsolationRequest) -> ProcessIsolationReceipt:
        process_identity = _process_identity(request)
        with self._lock:
            existing = self._terminal_receipts.get(process_identity)
            if existing is not None:
                if existing.request_digest != request.request_digest:
                    raise PodmanDispatchError(
                        "podman_process_identity_collision",
                        "process identity resolved to another request digest",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    )
                return existing
            prior = self._requests.get(process_identity)
            if prior is not None and prior.request_digest != request.request_digest:
                raise PodmanDispatchError(
                    "podman_process_identity_collision",
                    "process identity resolved to another active request",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                )
            self._requests[process_identity] = request

        mount = self.mount_resolver.resolve(request.workspace)
        if mount is None:
            receipt = _failure_receipt(
                request,
                process_identity=process_identity,
                error_code="podman_workspace_mount_stale",
                safe_summary="The exact workspace mount is unavailable or stale.",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            )
            return self._remember(process_identity, receipt)
        if (
            request.image_identity != mount.image_identity
            or request.mount_manifest_digest != mount.mount_manifest_digest
        ):
            receipt = _failure_receipt(
                request,
                process_identity=process_identity,
                error_code="podman_workspace_mount_identity_mismatch",
                safe_summary="The process request does not match the exact mount manifest.",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            )
            return self._remember(process_identity, receipt)

        try:
            result = self.executor.run(
                SupervisedProcessRequest(
                    process_identity=process_identity,
                    process_epoch=request.process_epoch,
                    authority_fence=request.authority_fence,
                    argv=self._podman_argv(request, mount, process_identity),
                    environment=request.environment,
                    stdin=request.stdin,
                    timeout_seconds=request.timeout_seconds + 10,
                    max_output_bytes=request.max_output_bytes,
                )
            )
        except PodmanDispatchError as exc:
            receipt = _failure_receipt(
                request,
                process_identity=process_identity,
                error_code=exc.error_code,
                safe_summary="The selected Podman process Adapter failed.",
                effect_certainty=exc.effect_certainty,
                cause=exc.__cause__ or exc,
            )
            return self._remember(process_identity, receipt)
        except Exception as exc:
            receipt = _failure_receipt(
                request,
                process_identity=process_identity,
                error_code="podman_process_unclassified_failure",
                safe_summary="The selected Podman process outcome is uncertain.",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                cause=exc,
            )
            return self._remember(process_identity, receipt)

        if result.timed_out:
            receipt = _failure_receipt(
                request,
                process_identity=process_identity,
                error_code="podman_process_timeout",
                safe_summary="The bounded Podman process exceeded its deadline.",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                result=result,
            )
        else:
            receipt = _result_receipt(request, result)
        return self._remember(process_identity, receipt)

    def reconcile(self, request: ProcessIsolationRequest) -> ProcessIsolationReceipt:
        """Inspect this Adapter epoch without launching a replacement process."""

        process_identity = _process_identity(request)
        with self._lock:
            terminal = self._terminal_receipts.get(process_identity)
            prior = self._requests.get(process_identity)
        if prior is not None and prior.request_digest != request.request_digest:
            raise PodmanDispatchError(
                "podman_process_identity_collision",
                "process identity resolved to another request digest",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            )
        if terminal is not None:
            if terminal.request_digest != request.request_digest:
                raise PodmanDispatchError(
                    "podman_process_identity_collision",
                    "terminal process receipt belongs to another request digest",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                )
            return terminal
        return _failure_receipt(
            request,
            process_identity=process_identity,
            error_code="podman_process_reconciliation_pending",
            safe_summary=(
                "No terminal process receipt is available in this Adapter epoch; "
                "the original process was not redispatched."
            ),
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        )

    def retire(
        self,
        *,
        process_identity: str,
        process_epoch: int,
        authority_fence: int,
    ) -> ProcessIsolationReceipt:
        with self._lock:
            terminal = self._terminal_receipts.get(process_identity)
            request = self._requests.get(process_identity)
        if request is None:
            raise PodmanDispatchError(
                "podman_process_unknown",
                "process identity is unknown to this Adapter epoch",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            )
        if (
            request.process_epoch != process_epoch
            or request.authority_fence != authority_fence
        ):
            raise PodmanDispatchError(
                "podman_process_retirement_fence_stale",
                "process retirement uses a stale epoch or authority fence",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            )
        if terminal is not None:
            return terminal
        try:
            result = self.executor.retire(
                process_identity=process_identity,
                process_epoch=process_epoch,
                authority_fence=authority_fence,
            )
        except PodmanDispatchError:
            raise
        except Exception as exc:
            raise PodmanDispatchError(
                "podman_process_retirement_unknown",
                "process retirement outcome is uncertain",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            ) from exc
        return self._remember(process_identity, _result_receipt(request, result))

    def _remember(
        self,
        process_identity: str,
        receipt: ProcessIsolationReceipt,
    ) -> ProcessIsolationReceipt:
        with self._lock:
            self._terminal_receipts[process_identity] = receipt
        return receipt

    def _podman_argv(
        self,
        request: ProcessIsolationRequest,
        mount: PodmanWorkspaceMount,
        process_identity: str,
    ) -> tuple[str, ...]:
        return build_podman_command(
            podman_binary=self.podman_binary,
            deployment_network=self.deployment_network,
            runtime_uid=self.runtime_uid,
            runtime_gid=self.runtime_gid,
            mount=mount,
            process_identity=process_identity,
            cwd_relative=request.cwd_relative,
            environment_keys=tuple(sorted(request.environment)),
            timeout_seconds=request.timeout_seconds,
            argv=request.argv,
        )


@dataclass(slots=True)
class PodmanWorkspaceProcessAdapter:
    isolation: ProcessIsolationPort
    mount_resolver: PodmanWorkspaceMountResolver
    operation_ledger: WorkspaceOperationLedgerPort
    provider_id: str = PODMAN_PROCESS_PROVIDER_ID

    def execute(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt:
        identity = self._operation_identity(request)
        prior = self._read_ledger(identity)
        if prior is not None:
            return self._recorded_or_pending(identity, prior.receipt)
        isolation_request = self._isolation_request(request)
        if not self.operation_ledger.reserve(identity):
            concurrent = self._read_ledger(identity)
            if concurrent is None:
                raise RuntimeError("reserved process occurrence disappeared")
            return self._recorded_or_pending(identity, concurrent.receipt)
        receipt = self.isolation.execute(isolation_request)
        _validate_process_receipt(receipt, request, isolation_request)
        workspace_receipt = _workspace_process_receipt(request, receipt)
        self.operation_ledger.settle(identity, workspace_receipt)
        if receipt.state is IsolatedProcessState.FAILED:
            mutation_applied = (
                False
                if receipt.effect_certainty is ExternalEffectCertainty.NO_EFFECT
                else None
                if receipt.effect_certainty
                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else True
            )
            raise WorkspacePortError(
                (
                    "podman_process_failed"
                    if receipt.failure is None
                    else receipt.failure.error_code
                ),
                "the selected local process Adapter failed",
                effect_certainty=receipt.effect_certainty,
                mutation_applied=mutation_applied,
                diagnostic_id=(
                    None
                    if receipt.failure is None
                    else receipt.failure.diagnostic_id
                ),
            )
        return workspace_receipt

    def reconcile(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt:
        """Observe the original process identity without executing argv again."""

        identity = self._operation_identity(request)
        prior = self._read_ledger(identity)
        if prior is None:
            return WorkspaceOperationReceipt.create(
                operation_id=request.operation_id,
                workspace_id=request.binding.workspace_id,
                generation=request.binding.generation,
                state_version=request.binding.state_version,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id="diagnostic-process-occurrence-not-reserved",
            )
        if prior.receipt is not None and (
            prior.receipt.effect_certainty
            is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            return prior.receipt
        mount = self.mount_resolver.resolve(request.binding)
        if mount is None:
            pending = WorkspaceOperationReceipt.create(
                operation_id=request.operation_id,
                workspace_id=request.binding.workspace_id,
                generation=request.binding.generation,
                state_version=request.binding.state_version,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
                diagnostic_id="diagnostic-process-reconciliation-pending",
            )
            return self._settle_progress(identity, prior.receipt, pending)
        isolation_request = self._isolation_request(request)
        try:
            receipt = self.isolation.reconcile(isolation_request)
        except PodmanDispatchError as exc:
            raise WorkspacePortError(
                exc.error_code,
                "the selected local process Adapter could not reconcile the process",
                effect_certainty=exc.effect_certainty,
                mutation_applied=(
                    False
                    if exc.effect_certainty is ExternalEffectCertainty.NO_EFFECT
                    else None
                    if exc.effect_certainty
                    is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    else True
                ),
            ) from exc
        _validate_process_receipt(receipt, request, isolation_request)
        workspace_receipt = _workspace_process_receipt(request, receipt)
        return self._settle_progress(identity, prior.receipt, workspace_receipt)

    def _operation_identity(
        self,
        request: WorkspaceExecRequest,
    ) -> WorkspaceOperationIdentity:
        return WorkspaceOperationIdentity(
            provider_id=self.provider_id,
            operation_kind="process",
            operation_id=request.operation_id,
            intent_digest=request.intent_digest,
            session_id=request.binding.session_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
        )

    def _read_ledger(self, identity: WorkspaceOperationIdentity):  # noqa: ANN202
        try:
            return self.operation_ledger.read(identity)
        except WorkspaceOperationLedgerError as exc:
            collision = exc.phase == "identity"
            raise WorkspacePortError(
                (
                    "workspace_operation_identity_collision"
                    if collision
                    else "workspace_operation_ledger_rejected"
                ),
                "operation identity was already used for another process intent"
                if collision
                else "workspace occurrence ledger rejected the operation",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            ) from exc

    def _recorded_or_pending(
        self,
        identity: WorkspaceOperationIdentity,
        receipt: WorkspaceOperationReceipt | None,
    ) -> WorkspaceOperationReceipt:
        if receipt is not None:
            return receipt
        pending = WorkspaceOperationReceipt.create(
            operation_id=identity.operation_id,
            workspace_id=identity.workspace_id,
            generation=identity.generation,
            state_version=identity.state_version,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            mutation_applied=None,
            diagnostic_id="diagnostic-process-reconciliation-pending",
        )
        return self.operation_ledger.settle(identity, pending).receipt or pending

    def _settle_progress(
        self,
        identity: WorkspaceOperationIdentity,
        prior: WorkspaceOperationReceipt | None,
        observed: WorkspaceOperationReceipt,
    ) -> WorkspaceOperationReceipt:
        if (
            prior is not None
            and prior.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            and observed.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            return prior
        return self.operation_ledger.settle(identity, observed).receipt or observed

    def _isolation_request(
        self,
        request: WorkspaceExecRequest,
    ) -> ProcessIsolationRequest:
        mount = self.mount_resolver.resolve(request.binding)
        if mount is None:
            raise WorkspacePortError(
                "podman_workspace_mount_stale",
                "the exact local workspace mount is unavailable",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            )
        return ProcessIsolationRequest(
            request_id=f"{request.operation_id}.isolation",
            command_id=request.operation_id,
            session_id=request.binding.session_id,
            agent_member_id=request.binding.owner_member_id,
            workspace=request.binding,
            process_epoch=request.process_epoch,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
            argv=request.argv,
            cwd_relative=request.cwd,
            environment={},
            image_identity=mount.image_identity,
            mount_manifest_digest=mount.mount_manifest_digest,
            timeout_seconds=request.timeout_seconds,
            max_output_bytes=request.max_output_bytes,
            stdin=request.stdin,
        )


def _workspace_process_receipt(
    request: WorkspaceExecRequest,
    receipt: ProcessIsolationReceipt,
) -> WorkspaceOperationReceipt:
    mutation_applied = (
        False
        if receipt.effect_certainty is ExternalEffectCertainty.NO_EFFECT
        else None
        if receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        else True
    )
    payload = (
        b""
        if receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        else _bounded_workspace_result_payload(
            receipt,
            max_bytes=request.max_output_bytes,
        )
    )
    return WorkspaceOperationReceipt.create(
        operation_id=request.operation_id,
        workspace_id=request.binding.workspace_id,
        generation=request.binding.generation,
        state_version=request.binding.state_version,
        effect_certainty=receipt.effect_certainty,
        mutation_applied=mutation_applied,
        result_payload=payload,
        diagnostic_id=(
            None if receipt.failure is None else receipt.failure.diagnostic_id
        ),
    )


def _process_identity(request: ProcessIsolationRequest) -> str:
    digest = request.request_digest.removeprefix("sha256:")
    return f"ozp-{digest[:24]}"


def _result_receipt(
    request: ProcessIsolationRequest,
    result: SupervisedProcessResult,
) -> ProcessIsolationReceipt:
    return ProcessIsolationReceipt(
        receipt_id=f"receipt-{result.process_identity}",
        request_id=request.request_id,
        request_digest=request.request_digest,
        process_identity=result.process_identity,
        process_epoch=request.process_epoch,
        workspace_generation=request.workspace.generation,
        authority_generation=request.authority_generation,
        authority_fence=request.authority_fence,
        state=(
            IsolatedProcessState.RETIRED
            if result.retired
            else IsolatedProcessState.EXITED
        ),
        exit_code=result.returncode,
        stdout_summary=_redact_process_output(
            result.stdout.decode("utf-8", errors="replace"),
            request,
        ),
        stderr_summary=_redact_process_output(
            result.stderr.decode("utf-8", errors="replace"),
            request,
        ),
        stdout_truncated=result.stdout_truncated,
        stderr_truncated=result.stderr_truncated,
        duration_ms=result.duration_ms,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        fallback_performed=False,
        started_at=result.started_at,
        ended_at=result.ended_at,
    )


def _failure_receipt(
    request: ProcessIsolationRequest,
    *,
    process_identity: str,
    error_code: str,
    safe_summary: str,
    effect_certainty: ExternalEffectCertainty,
    result: SupervisedProcessResult | None = None,
    cause: BaseException | None = None,
) -> ProcessIsolationReceipt:
    suffix = canonical_sha256_digest(
        {
            "request_digest": request.request_digest,
            "error_code": error_code,
        }
    ).removeprefix("sha256:")[:20]
    diagnostic_id = f"diagnostic-{suffix}"
    cause_chain: tuple[dict[str, str], ...] = ()
    if cause is not None:
        cause_chain = (
            {
                "type": type(cause).__name__,
                "code": getattr(cause, "error_code", None) or "runtime_error",
                "message_digest": canonical_sha256_digest(
                    {"message": str(cause)}
                ),
            },
        )
    failure = FailureObservation(
        failure_id=f"failure-{suffix}",
        session_id=request.session_id,
        source_kind="process_adapter",
        source_ref=request.request_id,
        source_version=request.request_digest,
        phase="process_execute",
        failure_class=FailureClass.RUNTIME,
        recoverability=(
            FailureRecoverability.RECONCILIATION_REQUIRED
            if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else FailureRecoverability.AGENT_CAN_REPLAN
        ),
        effect_certainty=effect_certainty,
        retry_eligibility=(
            RetryEligibility.RECONCILE_REQUIRED
            if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else RetryEligibility.TERMINAL
        ),
        actor_kind=FailureActorKind.SYSTEM,
        error_code=error_code,
        safe_summary=safe_summary,
        facts={
            "process_epoch": request.process_epoch,
            "workspace_generation": request.workspace.generation,
            "fallback_performed": False,
        },
        likely_causes=("selected_process_adapter_failure",),
        evidence_refs=(request.request_digest,),
        created_at=_utc_now(),
        agent_id=request.agent_member_id,
        component=PODMAN_PROCESS_PROVIDER_ID,
        operation="process_execute",
        identities={
            "request_id": request.request_id,
            "process_identity": process_identity,
            "workspace_id": request.workspace.workspace_id,
        },
        mutation_applied=effect_certainty
        in {
            ExternalEffectCertainty.EFFECT_KNOWN,
            ExternalEffectCertainty.TERMINAL_KNOWN,
        },
        fallback_performed=False,
        cause_chain=cause_chain,
        diagnostic_id=diagnostic_id,
        next_action=(
            "reconcile_process"
            if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else "inspect_diagnostic"
        ),
    )
    return ProcessIsolationReceipt(
        receipt_id=f"receipt-{process_identity}",
        request_id=request.request_id,
        request_digest=request.request_digest,
        process_identity=process_identity,
        process_epoch=request.process_epoch,
        workspace_generation=request.workspace.generation,
        authority_generation=request.authority_generation,
        authority_fence=request.authority_fence,
        state=IsolatedProcessState.FAILED,
        exit_code=None if result is None else result.returncode,
        stdout_summary=(
            ""
            if result is None
            else _redact_process_output(
                result.stdout.decode("utf-8", errors="replace"),
                request,
            )
        ),
        stderr_summary=(
            ""
            if result is None
            else _redact_process_output(
                result.stderr.decode("utf-8", errors="replace"),
                request,
            )
        ),
        stdout_truncated=False if result is None else result.stdout_truncated,
        stderr_truncated=False if result is None else result.stderr_truncated,
        duration_ms=0 if result is None else result.duration_ms,
        effect_certainty=effect_certainty,
        fallback_performed=False,
        started_at=_utc_now() if result is None else result.started_at,
        ended_at=_utc_now() if result is None else result.ended_at,
        failure=failure,
    )


def _validate_process_receipt(
    receipt: ProcessIsolationReceipt,
    request: WorkspaceExecRequest,
    isolation_request: ProcessIsolationRequest,
) -> None:
    if (
        receipt.request_id != f"{request.operation_id}.isolation"
        or receipt.request_digest != isolation_request.request_digest
        or receipt.process_epoch != request.process_epoch
        or receipt.workspace_generation != request.binding.generation
        or receipt.authority_generation != request.authority_generation
        or receipt.authority_fence != request.authority_fence
        or receipt.fallback_performed
    ):
        raise WorkspacePortError(
            "podman_process_receipt_identity_mismatch",
            "process Adapter returned a receipt for another command identity",
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            mutation_applied=None,
        )


def _redact_process_output(
    value: str,
    request: ProcessIsolationRequest,
) -> str:
    redacted = value
    for key in request.secret_environment_keys:
        secret = request.environment[key]
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _bounded_workspace_result_payload(
    receipt: ProcessIsolationReceipt,
    *,
    max_bytes: int,
) -> bytes:
    def encode(stdout: str, stderr: str, truncated: bool) -> bytes:
        return json.dumps(
            {
                "process_identity": receipt.process_identity,
                "state": receipt.state.value,
                "returncode": receipt.exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": receipt.stdout_truncated or truncated,
                "stderr_truncated": receipt.stderr_truncated or truncated,
                "duration_ms": receipt.duration_ms,
                "retry_performed": False,
                "fallback_performed": False,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    stdout = receipt.stdout_summary
    stderr = receipt.stderr_summary
    payload = encode(stdout, stderr, False)
    if len(payload) <= max_bytes:
        return payload
    low = 0
    high = max(len(stdout), len(stderr))
    best = encode("", "", True)
    if len(best) > max_bytes:
        raise WorkspacePortError(
            "podman_process_result_budget_too_small",
            "process result metadata exceeds the declared output budget",
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
        )
    while low <= high:
        midpoint = (low + high) // 2
        candidate = encode(stdout[:midpoint], stderr[:midpoint], True)
        if len(candidate) <= max_bytes:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


__all__ = [
    "MappingPodmanWorkspaceMountResolver",
    "PODMAN_PROCESS_PROVIDER_CONTRACT",
    "PODMAN_PROCESS_PROVIDER_CONTRACT_DIGEST",
    "PODMAN_PROCESS_PROVIDER_ID",
    "PodmanCommandExecutor",
    "PodmanDispatchError",
    "PodmanProcessIsolationAdapter",
    "PodmanWorkspaceMount",
    "PodmanWorkspaceMountResolver",
    "PodmanWorkspaceProcessAdapter",
    "SupervisedProcessRequest",
    "SupervisedProcessResult",
    "SupervisedSubprocessExecutor",
    "build_podman_command",
]
