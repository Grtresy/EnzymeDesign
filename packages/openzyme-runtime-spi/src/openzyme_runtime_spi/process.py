from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
import hashlib
import re
from types import MappingProxyType
from typing import Any
from typing import Mapping
from typing import Protocol

from openzyme_contracts import FailureObservation
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts import require_workspace_relative_path


PROCESS_ISOLATION_REQUEST_SCHEMA_VERSION = "process_isolation_request@1"
PROCESS_ISOLATION_RECEIPT_SCHEMA_VERSION = "process_isolation_receipt@1"
PROCESS_ISOLATION_PORT_CONTRACT = "openzyme.process-isolation-port@1"
PROCESS_ISOLATION_PORT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": PROCESS_ISOLATION_PORT_CONTRACT,
        "methods": ["execute", "reconcile", "retire"],
        "request_schema": PROCESS_ISOLATION_REQUEST_SCHEMA_VERSION,
        "receipt_schema": PROCESS_ISOLATION_RECEIPT_SCHEMA_VERSION,
        "redispatch_on_reconcile": False,
    }
)
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")


class IsolatedProcessState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    FAILED = "failed"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class ProcessIsolationRequest:
    request_id: str
    command_id: str
    session_id: str
    agent_member_id: str
    workspace: WorkspaceRuntimeBinding
    process_epoch: int
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    argv: tuple[str, ...]
    cwd_relative: str
    environment: Mapping[str, str] = field(repr=False)
    image_identity: str
    mount_manifest_digest: str
    timeout_seconds: int
    max_output_bytes: int = 262_144
    stdin: bytes = field(default=b"", repr=False)
    secret_environment_keys: tuple[str, ...] = ()
    interactive: bool = False
    background: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "command_id",
            "session_id",
            "agent_member_id",
            "authority_lease_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if (
            not isinstance(self.image_identity, str)
            or not self.image_identity
            or self.image_identity != self.image_identity.strip()
            or len(self.image_identity) > 2_048
            or "\x00" in self.image_identity
            or any(character.isspace() for character in self.image_identity)
        ):
            raise ValueError("image_identity must be one bounded exact image reference")
        if self.workspace.session_id != self.session_id:
            raise ValueError("process request workspace belongs to another Session")
        if self.workspace.owner_member_id != self.agent_member_id:
            raise ValueError("process request workspace belongs to another Agent member")
        for field_name in (
            "process_epoch",
            "authority_generation",
            "authority_fence",
            "timeout_seconds",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if not self.argv or len(self.argv) > 256:
            raise ValueError("argv must be a non-empty bounded tuple")
        if any(not isinstance(item, str) or not item or len(item) > 16_384 for item in self.argv):
            raise ValueError("argv items must be non-empty bounded strings")
        object.__setattr__(
            self,
            "cwd_relative",
            require_workspace_relative_path(
                self.cwd_relative,
                field_name="cwd_relative",
                allow_root=True,
            ),
        )
        if self.timeout_seconds > 3_600:
            raise ValueError("timeout_seconds exceeds the bounded process limit")
        if not 256 <= self.max_output_bytes <= 4_194_304:
            raise ValueError("max_output_bytes must be between 256 and 4194304")
        if not isinstance(self.stdin, bytes) or len(self.stdin) > 1_048_576:
            raise ValueError("stdin must be bytes within the bounded request limit")
        if self.interactive:
            raise ValueError("interactive isolated processes are not supported")
        if self.background:
            raise ValueError("background isolated processes are not supported")
        if len(self.environment) > 128:
            raise ValueError("environment exceeds the bounded entry limit")
        normalized_environment: dict[str, str] = {}
        for key, value in self.environment.items():
            if not isinstance(key, str) or _ENVIRONMENT_NAME.fullmatch(key) is None:
                raise ValueError("environment keys must be portable variable names")
            if (
                not isinstance(value, str)
                or len(value) > 16_384
                or "\x00" in value
            ):
                raise ValueError("environment values must be bounded strings")
            normalized_environment[key] = value
        object.__setattr__(self, "environment", MappingProxyType(normalized_environment))
        secret_keys = tuple(self.secret_environment_keys)
        if secret_keys != tuple(sorted(set(secret_keys))) or any(
            key not in normalized_environment for key in secret_keys
        ):
            raise ValueError(
                "secret_environment_keys must be sorted unique environment keys"
            )
        object.__setattr__(self, "secret_environment_keys", secret_keys)
        require_digest(self.mount_manifest_digest, field_name="mount_manifest_digest")

    @property
    def request_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        data = {
            "schema_version": PROCESS_ISOLATION_REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "workspace": self.workspace.to_dict(),
            "process_epoch": self.process_epoch,
            "authority_lease_id": self.authority_lease_id,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
            "argv": list(self.argv),
            "cwd_relative": self.cwd_relative,
            "environment_keys": sorted(self.environment),
            "environment_digest": canonical_sha256_digest(
                {"environment": sorted(self.environment.items())}
            ),
            "secret_environment_keys": list(self.secret_environment_keys),
            "image_identity": self.image_identity,
            "mount_manifest_digest": self.mount_manifest_digest,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "stdin_digest": f"sha256:{hashlib.sha256(self.stdin).hexdigest()}",
            "stdin_size": len(self.stdin),
            "interactive": self.interactive,
            "background": self.background,
        }
        if include_digest:
            data["request_digest"] = self.request_digest
        return data


@dataclass(frozen=True, slots=True)
class ProcessIsolationReceipt:
    receipt_id: str
    request_id: str
    request_digest: str
    process_identity: str
    process_epoch: int
    workspace_generation: int
    authority_generation: int
    authority_fence: int
    state: IsolatedProcessState
    exit_code: int | None
    stdout_summary: str
    stderr_summary: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    effect_certainty: ExternalEffectCertainty
    fallback_performed: bool
    started_at: str
    ended_at: str | None
    failure: FailureObservation | None = None

    def __post_init__(self) -> None:
        for field_name in ("receipt_id", "request_id", "process_identity"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.request_digest, field_name="request_digest")
        for field_name in (
            "process_epoch",
            "workspace_generation",
            "authority_generation",
            "authority_fence",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            len(self.stdout_summary.encode("utf-8")) > 4_194_304
            or len(self.stderr_summary.encode("utf-8")) > 4_194_304
        ):
            raise ValueError("process output summaries exceed the absolute byte bound")
        if not isinstance(self.stdout_truncated, bool) or not isinstance(
            self.stderr_truncated,
            bool,
        ):
            raise ValueError("process truncation facts must be boolean")
        if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool):
            raise ValueError("duration_ms must be an integer")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")
        if self.fallback_performed:
            raise ValueError("process Adapter receipts cannot hide fallback")
        if self.state is IsolatedProcessState.FAILED and self.failure is None:
            raise ValueError("failed process receipt requires structured failure")
        if self.state is not IsolatedProcessState.FAILED and self.failure is not None:
            raise ValueError("failure is permitted only for failed process receipt")
        if self.state is IsolatedProcessState.EXITED and self.exit_code is None:
            raise ValueError("exited process receipt requires exit_code")
        if (
            self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            and self.state is not IsolatedProcessState.FAILED
        ):
            raise ValueError("dispatch_in_doubt process receipt must be failed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROCESS_ISOLATION_RECEIPT_SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "process_identity": self.process_identity,
            "process_epoch": self.process_epoch,
            "workspace_generation": self.workspace_generation,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
            "state": self.state.value,
            "exit_code": self.exit_code,
            "stdout_summary": self.stdout_summary,
            "stderr_summary": self.stderr_summary,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "duration_ms": self.duration_ms,
            "effect_certainty": self.effect_certainty.value,
            "fallback_performed": self.fallback_performed,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "failure": None if self.failure is None else self.failure.to_dict(),
        }


class ProcessIsolationPort(Protocol):
    provider_id: str
    provider_contract_digest: str

    def execute(self, request: ProcessIsolationRequest) -> ProcessIsolationReceipt: ...

    def reconcile(self, request: ProcessIsolationRequest) -> ProcessIsolationReceipt: ...

    def retire(
        self,
        *,
        process_identity: str,
        process_epoch: int,
        authority_fence: int,
    ) -> ProcessIsolationReceipt: ...


__all__ = [
    "IsolatedProcessState",
    "PROCESS_ISOLATION_RECEIPT_SCHEMA_VERSION",
    "PROCESS_ISOLATION_REQUEST_SCHEMA_VERSION",
    "PROCESS_ISOLATION_PORT_CONTRACT",
    "PROCESS_ISOLATION_PORT_CONTRACT_DIGEST",
    "ProcessIsolationPort",
    "ProcessIsolationReceipt",
    "ProcessIsolationRequest",
]
