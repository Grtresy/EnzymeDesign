from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import subprocess
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceObservation
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


SSH_WORKSPACE_PROVIDER_ID = "openzyme.hpc.ssh"
SSH_WORKSPACE_PROVIDER_CONTRACT = "openzyme.hpc.ssh.workspace@1"
SSH_WORKSPACE_PROVIDER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": SSH_WORKSPACE_PROVIDER_CONTRACT,
        "ports": [
            "openzyme.workspace-observation-port@1",
            "openzyme.workspace-filesystem-port@1",
            "openzyme.workspace-process-port@1",
            "openzyme.workspace-transfer-port@1",
        ],
        "path_policy": "workspace_relative_private_root_resolution",
        "process_policy": "bounded_foreground_argv",
        "reconcile_policy": "same_occurrence_no_redispatch",
        "scheduler_authority": False,
        "fallback": False,
    }
)


@dataclass(frozen=True, slots=True)
class PrivateRemoteWorkspaceLocator:
    workspace_id: str
    session_id: str
    owner_member_id: str
    generation: int
    state_version: int
    target_id: str
    target_qualification_digest: str
    root_identity_digest: str
    remote_root: str
    credential_claim_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "workspace_id",
            "session_id",
            "owner_member_id",
            "target_id",
            "credential_claim_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "target_qualification_digest",
            "root_identity_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.generation < 1 or self.state_version < 1:
            raise ValueError("remote locator generations must be positive")
        if (
            not isinstance(self.remote_root, str)
            or not self.remote_root.startswith("/")
            or self.remote_root == "/"
            or "\x00" in self.remote_root
            or self.remote_root.endswith("/")
            or any(part in {"", ".", ".."} for part in self.remote_root[1:].split("/"))
        ):
            raise ValueError("remote_root must be one protected absolute root")

    def matches(self, binding: WorkspaceRuntimeBinding) -> bool:
        return (
            self.workspace_id == binding.workspace_id
            and self.session_id == binding.session_id
            and self.owner_member_id == binding.owner_member_id
            and self.generation == binding.generation
            and self.state_version == binding.state_version
            and self.target_id == binding.target_id
            and self.target_qualification_digest
            == binding.target_qualification_digest
            and self.root_identity_digest == binding.root_identity_digest
            and binding.provider_id == SSH_WORKSPACE_PROVIDER_ID
        )


class PrivateRemoteWorkspaceLocatorResolver(Protocol):
    def resolve(
        self,
        binding: WorkspaceRuntimeBinding,
    ) -> PrivateRemoteWorkspaceLocator | None: ...


@dataclass(frozen=True, slots=True)
class RemoteWorkspaceTransportOutcome:
    operation_id: str
    request_digest: str
    effect_certainty: ExternalEffectCertainty
    mutation_applied: bool | None
    result_payload: bytes = b""
    diagnostic_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(self.request_digest, field_name="request_digest")
        if self.diagnostic_id is not None:
            require_identifier(self.diagnostic_id, field_name="diagnostic_id")
        if len(self.result_payload) > 4_194_304:
            raise ValueError("remote result payload exceeds the absolute bound")
        if self.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if self.mutation_applied is not False:
                raise ValueError("no_effect outcome requires mutation_applied=false")
        elif self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.mutation_applied is not None or self.result_payload:
                raise ValueError("uncertain outcome cannot claim mutation or result")
        elif self.mutation_applied is None:
            raise ValueError("settled outcome requires a mutation fact")


class RemoteWorkspaceTransport(Protocol):
    """Private SSH/SFTP/rsync transport; credentials never enter public DTOs."""

    def dispatch(
        self,
        *,
        locator: PrivateRemoteWorkspaceLocator,
        operation_id: str,
        request_digest: str,
        operation_kind: str,
        payload: Mapping[str, object],
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> RemoteWorkspaceTransportOutcome: ...

    def reconcile(
        self,
        *,
        locator: PrivateRemoteWorkspaceLocator,
        operation_id: str,
        request_digest: str,
    ) -> RemoteWorkspaceTransportOutcome: ...


@dataclass(frozen=True, slots=True)
class PrivateSshCredentialMaterial:
    credential_claim_id: str
    target_alias: str
    identity_file: str

    def __post_init__(self) -> None:
        require_identifier(
            self.credential_claim_id,
            field_name="credential_claim_id",
        )
        require_identifier(self.target_alias, field_name="target_alias")
        path = PurePosixPath(self.identity_file)
        if not path.is_absolute() or path.as_posix() != self.identity_file:
            raise ValueError("identity_file must be one exact private absolute path")


class PrivateSshCredentialResolver(Protocol):
    def resolve(
        self,
        credential_claim_id: str,
    ) -> PrivateSshCredentialMaterial | None: ...


@dataclass(frozen=True, slots=True)
class SshCommandResult:
    return_code: int
    stdout: bytes
    stderr: bytes


class SshCommandError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty,
        diagnostic_id: str | None = None,
    ) -> None:
        self.effect_certainty = effect_certainty
        self.diagnostic_id = diagnostic_id
        super().__init__(message)


class SshCommandExecutor(Protocol):
    def execute(
        self,
        *,
        argv: tuple[str, ...],
        stdin: bytes,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> SshCommandResult: ...


@dataclass(frozen=True, slots=True)
class SubprocessSshCommandExecutor:
    def execute(
        self,
        *,
        argv: tuple[str, ...],
        stdin: bytes,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> SshCommandResult:
        try:
            completed = subprocess.run(
                argv,
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SshCommandError(
                "SSH wrapper response deadline elapsed after dispatch",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            ) from exc
        except OSError as exc:
            raise SshCommandError(
                "SSH process could not be created",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            ) from exc
        if len(completed.stdout) + len(completed.stderr) > max_output_bytes:
            raise SshCommandError(
                "SSH wrapper response exceeded the output bound",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        return SshCommandResult(
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True, slots=True)
class SshJsonCommandTransport:
    credential_resolver: PrivateSshCredentialResolver
    executor: SshCommandExecutor
    wrapper_path: str = "/usr/local/libexec/openzyme-workspace-runtime"
    ssh_binary: str = "/usr/bin/ssh"

    def __post_init__(self) -> None:
        for field_name in ("wrapper_path", "ssh_binary"):
            value = PurePosixPath(getattr(self, field_name))
            if not value.is_absolute() or value.as_posix() != getattr(
                self,
                field_name,
            ):
                raise ValueError(f"{field_name} must be one exact absolute path")

    def dispatch(
        self,
        *,
        locator: PrivateRemoteWorkspaceLocator,
        operation_id: str,
        request_digest: str,
        operation_kind: str,
        payload: Mapping[str, object],
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> RemoteWorkspaceTransportOutcome:
        return self._invoke(
            locator=locator,
            action="dispatch",
            operation_id=operation_id,
            request_digest=request_digest,
            operation_kind=operation_kind,
            payload=payload,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    def reconcile(
        self,
        *,
        locator: PrivateRemoteWorkspaceLocator,
        operation_id: str,
        request_digest: str,
    ) -> RemoteWorkspaceTransportOutcome:
        return self._invoke(
            locator=locator,
            action="reconcile",
            operation_id=operation_id,
            request_digest=request_digest,
            operation_kind="reconcile",
            payload={},
            timeout_seconds=60,
            max_output_bytes=65_536,
        )

    def _invoke(
        self,
        *,
        locator: PrivateRemoteWorkspaceLocator,
        action: str,
        operation_id: str,
        request_digest: str,
        operation_kind: str,
        payload: Mapping[str, object],
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> RemoteWorkspaceTransportOutcome:
        credential = self.credential_resolver.resolve(locator.credential_claim_id)
        if (
            credential is None
            or credential.credential_claim_id != locator.credential_claim_id
        ):
            return RemoteWorkspaceTransportOutcome(
                operation_id=operation_id,
                request_digest=request_digest,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            )
        envelope = {
            "schema_version": "ssh_workspace_private_envelope@1",
            "action": action,
            "operation_id": operation_id,
            "request_digest": request_digest,
            "workspace_id": locator.workspace_id,
            "workspace_generation": locator.generation,
            "workspace_state_version": locator.state_version,
            "target_id": locator.target_id,
            "target_qualification_digest": locator.target_qualification_digest,
            "root_identity_digest": locator.root_identity_digest,
            "remote_root": locator.remote_root,
            "operation_kind": operation_kind,
            "payload": dict(payload),
        }
        try:
            result = self.executor.execute(
                argv=(
                    self.ssh_binary,
                    "-T",
                    "-oBatchMode=yes",
                    "-oIdentitiesOnly=yes",
                    "-i",
                    credential.identity_file,
                    credential.target_alias,
                    self.wrapper_path,
                    action,
                ),
                stdin=_json_bytes(envelope),
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
        except SshCommandError as exc:
            return RemoteWorkspaceTransportOutcome(
                operation_id=operation_id,
                request_digest=request_digest,
                effect_certainty=exc.effect_certainty,
                mutation_applied=(
                    False
                    if exc.effect_certainty is ExternalEffectCertainty.NO_EFFECT
                    else None
                ),
                diagnostic_id=exc.diagnostic_id,
            )
        if result.return_code != 0:
            return RemoteWorkspaceTransportOutcome(
                operation_id=operation_id,
                request_digest=request_digest,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            )
        try:
            response = json.loads(result.stdout)
            return self._parse_response(
                response,
                operation_id=operation_id,
                request_digest=request_digest,
            )
        except (
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ):
            return RemoteWorkspaceTransportOutcome(
                operation_id=operation_id,
                request_digest=request_digest,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            )

    @staticmethod
    def _parse_response(
        response: object,
        *,
        operation_id: str,
        request_digest: str,
    ) -> RemoteWorkspaceTransportOutcome:
        fields = {
            "schema_version",
            "operation_id",
            "request_digest",
            "effect_certainty",
            "mutation_applied",
            "result_base64",
            "diagnostic_id",
        }
        if not isinstance(response, dict) or set(response) != fields:
            raise ValueError("SSH workspace wrapper response fields are closed")
        if response["schema_version"] != "ssh_workspace_private_response@1":
            raise ValueError("SSH workspace wrapper response schema drifted")
        return RemoteWorkspaceTransportOutcome(
            operation_id=str(response["operation_id"]),
            request_digest=str(response["request_digest"]),
            effect_certainty=ExternalEffectCertainty(
                str(response["effect_certainty"])
            ),
            mutation_applied=response["mutation_applied"],
            result_payload=base64.b64decode(
                str(response["result_base64"]),
                validate=True,
            ),
            diagnostic_id=(
                None
                if response["diagnostic_id"] is None
                else str(response["diagnostic_id"])
            ),
        )

def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(slots=True)
class SshWorkspaceAdapter:
    locator_resolver: PrivateRemoteWorkspaceLocatorResolver
    transport: RemoteWorkspaceTransport

    def observe(self, request: WorkspaceObservationRequest) -> WorkspaceObservation:
        locator = self._locator(request.binding)
        query_digest = request.query_digest
        outcome = self.transport.dispatch(
            locator=locator,
            operation_id="observe-" + query_digest.removeprefix("sha256:")[:32],
            request_digest=query_digest,
            operation_kind="sftp.observe",
            payload={
                "operation": request.operation.value,
                "path": request.path,
            },
            timeout_seconds=30,
            max_output_bytes=request.max_bytes,
        )
        self._require_identity(
            outcome,
            operation_id="observe-" + query_digest.removeprefix("sha256:")[:32],
            request_digest=query_digest,
        )
        if outcome.effect_certainty is not ExternalEffectCertainty.TERMINAL_KNOWN:
            raise WorkspacePortError(
                "remote_workspace_observation_unsettled",
                "remote observation did not return a terminal-known result",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id=outcome.diagnostic_id,
            )
        if len(outcome.result_payload) > request.max_bytes:
            raise WorkspacePortError(
                "remote_workspace_observation_unbounded",
                "remote observation exceeded its requested byte budget",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id=outcome.diagnostic_id,
            )
        return WorkspaceObservation(
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            operation=request.operation,
            result_digest=canonical_sha256_digest(
                {
                    "query_digest": query_digest,
                    "result_base64": base64.b64encode(
                        outcome.result_payload
                    ).decode("ascii"),
                }
            ),
            bounded_payload=outcome.result_payload,
        )

    def mutate(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        return self._dispatch_mutation(
            request=request,
            operation_kind="sftp.mutate",
            payload={
                "operation": request.operation.value,
                "path": request.path,
                "destination_path": request.destination_path,
                "content_base64": (
                    None
                    if request.content is None
                    else base64.b64encode(request.content).decode("ascii")
                ),
                "expected_content_digest": request.expected_content_digest,
                "recursive": request.recursive,
            },
            timeout_seconds=60,
            max_output_bytes=65_536,
        )

    def execute(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt:
        return self._dispatch_mutation(
            request=request,
            operation_kind="ssh.exec",
            payload={
                "argv": list(request.argv),
                "cwd": request.cwd,
                "stdin_base64": base64.b64encode(request.stdin).decode("ascii"),
                "process_epoch": request.process_epoch,
            },
            timeout_seconds=request.timeout_seconds,
            max_output_bytes=request.max_output_bytes,
        )

    def transfer(
        self,
        request: WorkspaceTransferRequest,
    ) -> WorkspaceOperationReceipt:
        return self._dispatch_mutation(
            request=request,
            operation_kind="rsync.transfer",
            payload={
                "direction": request.direction.value,
                "path": request.path,
                "transfer_ref": request.transfer_ref,
                "transfer_manifest_digest": request.transfer_manifest_digest,
                "max_bytes": request.max_bytes,
            },
            timeout_seconds=request.timeout_seconds,
            max_output_bytes=65_536,
        )

    def reconcile(
        self,
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
    ) -> WorkspaceOperationReceipt:
        locator = self._locator(request.binding)
        outcome = self.transport.reconcile(
            locator=locator,
            operation_id=request.operation_id,
            request_digest=request.intent_digest,
        )
        self._require_identity(
            outcome,
            operation_id=request.operation_id,
            request_digest=request.intent_digest,
        )
        return self._receipt(request, outcome)

    def _dispatch_mutation(
        self,
        *,
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
        operation_kind: str,
        payload: Mapping[str, object],
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> WorkspaceOperationReceipt:
        locator = self._locator(request.binding)
        outcome = self.transport.dispatch(
            locator=locator,
            operation_id=request.operation_id,
            request_digest=request.intent_digest,
            operation_kind=operation_kind,
            payload=payload,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        self._require_identity(
            outcome,
            operation_id=request.operation_id,
            request_digest=request.intent_digest,
        )
        return self._receipt(request, outcome)

    def _locator(
        self,
        binding: WorkspaceRuntimeBinding,
    ) -> PrivateRemoteWorkspaceLocator:
        locator = self.locator_resolver.resolve(binding)
        if locator is None or not locator.matches(binding):
            raise WorkspacePortError(
                "remote_workspace_binding_stale",
                "remote workspace owner, generation, target or qualification drifted",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            )
        return locator

    @staticmethod
    def _require_identity(
        outcome: RemoteWorkspaceTransportOutcome,
        *,
        operation_id: str,
        request_digest: str,
    ) -> None:
        if (
            outcome.operation_id != operation_id
            or outcome.request_digest != request_digest
        ):
            certainty = (
                ExternalEffectCertainty.NO_EFFECT
                if outcome.effect_certainty is ExternalEffectCertainty.NO_EFFECT
                else ExternalEffectCertainty.DISPATCH_IN_DOUBT
            )
            raise WorkspacePortError(
                "remote_workspace_response_identity_mismatch",
                "remote response did not bind the exact occurrence",
                effect_certainty=certainty,
                mutation_applied=(
                    False
                    if certainty is ExternalEffectCertainty.NO_EFFECT
                    else None
                ),
                diagnostic_id=outcome.diagnostic_id,
            )

    @staticmethod
    def _receipt(
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
        outcome: RemoteWorkspaceTransportOutcome,
    ) -> WorkspaceOperationReceipt:
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=outcome.effect_certainty,
            mutation_applied=outcome.mutation_applied,
            result_payload=outcome.result_payload,
            diagnostic_id=outcome.diagnostic_id,
        )


__all__ = [
    "PrivateRemoteWorkspaceLocator",
    "PrivateRemoteWorkspaceLocatorResolver",
    "PrivateSshCredentialMaterial",
    "PrivateSshCredentialResolver",
    "RemoteWorkspaceTransport",
    "RemoteWorkspaceTransportOutcome",
    "SSH_WORKSPACE_PROVIDER_CONTRACT",
    "SSH_WORKSPACE_PROVIDER_CONTRACT_DIGEST",
    "SSH_WORKSPACE_PROVIDER_ID",
    "SshCommandError",
    "SshCommandExecutor",
    "SshCommandResult",
    "SshJsonCommandTransport",
    "SshWorkspaceAdapter",
    "SubprocessSshCommandExecutor",
]
