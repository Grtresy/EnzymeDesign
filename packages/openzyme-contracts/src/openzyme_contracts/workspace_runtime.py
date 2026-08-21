from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any
from typing import Protocol

from .identity import canonical_sha256_digest
from .identity import require_digest
from .identity import require_identifier
from .reliability import ExternalEffectCertainty


WORKSPACE_STRUCTURED_OPERATION_MAX_BYTES = 1_048_576

WORKSPACE_RUNTIME_BINDING_SCHEMA_VERSION = "workspace_runtime_binding@1"
WORKSPACE_GENERATION_SCHEMA_VERSION = "workspace_generation@1"
WORKSPACE_OBSERVATION_REQUEST_SCHEMA_VERSION = "workspace_observation_request@1"
WORKSPACE_FILESYSTEM_MUTATION_SCHEMA_VERSION = "workspace_filesystem_mutation@1"
WORKSPACE_EXEC_REQUEST_SCHEMA_VERSION = "workspace_exec_request@1"
WORKSPACE_TRANSFER_REQUEST_SCHEMA_VERSION = "workspace_transfer_request@1"
WORKSPACE_OPERATION_RECEIPT_SCHEMA_VERSION = "workspace_operation_receipt@1"

WORKSPACE_OBSERVATION_PORT_CONTRACT = "openzyme.workspace-observation-port@1"
WORKSPACE_FILESYSTEM_PORT_CONTRACT = "openzyme.workspace-filesystem-port@1"
WORKSPACE_PROCESS_PORT_CONTRACT = "openzyme.workspace-process-port@1"
WORKSPACE_TRANSFER_PORT_CONTRACT = "openzyme.workspace-transfer-port@1"

WORKSPACE_OBSERVATION_PORT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": WORKSPACE_OBSERVATION_PORT_CONTRACT,
        "methods": ["observe"],
        "request_schema": WORKSPACE_OBSERVATION_REQUEST_SCHEMA_VERSION,
        "result": "workspace_observation@1",
        "mutating": False,
    }
)
WORKSPACE_FILESYSTEM_PORT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": WORKSPACE_FILESYSTEM_PORT_CONTRACT,
        "methods": ["mutate", "reconcile"],
        "request_schema": WORKSPACE_FILESYSTEM_MUTATION_SCHEMA_VERSION,
        "receipt_schema": WORKSPACE_OPERATION_RECEIPT_SCHEMA_VERSION,
        "redispatch_on_reconcile": False,
    }
)
WORKSPACE_PROCESS_PORT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": WORKSPACE_PROCESS_PORT_CONTRACT,
        "methods": ["execute", "reconcile"],
        "request_schema": WORKSPACE_EXEC_REQUEST_SCHEMA_VERSION,
        "receipt_schema": WORKSPACE_OPERATION_RECEIPT_SCHEMA_VERSION,
        "redispatch_on_reconcile": False,
    }
)
WORKSPACE_TRANSFER_PORT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": WORKSPACE_TRANSFER_PORT_CONTRACT,
        "methods": ["transfer", "reconcile"],
        "request_schema": WORKSPACE_TRANSFER_REQUEST_SCHEMA_VERSION,
        "receipt_schema": WORKSPACE_OPERATION_RECEIPT_SCHEMA_VERSION,
        "redispatch_on_reconcile": False,
    }
)


_OPAQUE_TRANSFER_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


def _bytes_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class WorkspaceKind(StrEnum):
    AGENT_LOCAL = "agent_local"
    EXECUTOR_REMOTE = "executor_remote"


class WorkspaceGenerationStatus(StrEnum):
    RESERVED = "reserved"
    PROVISIONING = "provisioning"
    READY = "ready"
    RETIRING = "retiring"
    RETIRED = "retired"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorkspaceGeneration:
    """Kernel-owned workspace generation identity, not provider mechanism state."""

    workspace_id: str
    workspace_kind: WorkspaceKind
    session_id: str
    owner_member_id: str
    generation: int
    state_version: int
    status: WorkspaceGenerationStatus
    provider_id: str
    target_id: str
    created_at: str
    updated_at: str
    root_identity_digest: str | None = None
    target_qualification_digest: str | None = None
    transition_receipt_digest: str | None = None
    controlled_operation_id: str | None = None
    retired_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "workspace_id",
            "session_id",
            "owner_member_id",
            "provider_id",
            "target_id",
            "created_at",
            "updated_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.generation < 1 or self.state_version < 1:
            raise ValueError("workspace generation and state_version must be positive")
        if self.root_identity_digest is not None:
            require_digest(self.root_identity_digest, field_name="root_identity_digest")
        if self.transition_receipt_digest is not None:
            require_digest(
                self.transition_receipt_digest,
                field_name="transition_receipt_digest",
            )
        if self.controlled_operation_id is not None:
            require_identifier(
                self.controlled_operation_id,
                field_name="controlled_operation_id",
            )
        if self.workspace_kind is WorkspaceKind.EXECUTOR_REMOTE:
            if self.target_qualification_digest is None:
                raise ValueError("remote workspace generation requires qualification")
            require_digest(
                self.target_qualification_digest,
                field_name="target_qualification_digest",
            )
        elif self.target_qualification_digest is not None:
            raise ValueError("local workspace generation cannot bind remote qualification")
        if self.status is WorkspaceGenerationStatus.READY and self.root_identity_digest is None:
            raise ValueError("ready workspace generation requires root identity")
        if self.status in {
            WorkspaceGenerationStatus.READY,
            WorkspaceGenerationStatus.RETIRED,
        } and (
            self.transition_receipt_digest is None
            or self.controlled_operation_id is None
        ):
            raise ValueError(
                "ready/retired workspace generation requires a controlled-operation receipt"
            )
        if self.status is WorkspaceGenerationStatus.RETIRED:
            if self.retired_at is None:
                raise ValueError("retired workspace generation requires retired_at")
            require_identifier(self.retired_at, field_name="retired_at")
        elif self.retired_at is not None:
            raise ValueError("only a retired workspace generation may have retired_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORKSPACE_GENERATION_SCHEMA_VERSION,
            "workspace_id": self.workspace_id,
            "workspace_kind": self.workspace_kind.value,
            "session_id": self.session_id,
            "owner_member_id": self.owner_member_id,
            "generation": self.generation,
            "state_version": self.state_version,
            "status": self.status.value,
            "provider_id": self.provider_id,
            "target_id": self.target_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "root_identity_digest": self.root_identity_digest,
            "target_qualification_digest": self.target_qualification_digest,
            "transition_receipt_digest": self.transition_receipt_digest,
            "controlled_operation_id": self.controlled_operation_id,
            "retired_at": self.retired_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkspaceGeneration":
        expected = {
            "schema_version",
            "workspace_id",
            "workspace_kind",
            "session_id",
            "owner_member_id",
            "generation",
            "state_version",
            "status",
            "provider_id",
            "target_id",
            "created_at",
            "updated_at",
            "root_identity_digest",
            "target_qualification_digest",
            "transition_receipt_digest",
            "controlled_operation_id",
            "retired_at",
        }
        if set(payload) != expected or payload.get("schema_version") != WORKSPACE_GENERATION_SCHEMA_VERSION:
            raise ValueError("workspace generation payload has an invalid closed schema")
        return cls(
            workspace_id=str(payload["workspace_id"]),
            workspace_kind=WorkspaceKind(str(payload["workspace_kind"])),
            session_id=str(payload["session_id"]),
            owner_member_id=str(payload["owner_member_id"]),
            generation=int(payload["generation"]),
            state_version=int(payload["state_version"]),
            status=WorkspaceGenerationStatus(str(payload["status"])),
            provider_id=str(payload["provider_id"]),
            target_id=str(payload["target_id"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            root_identity_digest=(
                None
                if payload["root_identity_digest"] is None
                else str(payload["root_identity_digest"])
            ),
            target_qualification_digest=(
                None
                if payload["target_qualification_digest"] is None
                else str(payload["target_qualification_digest"])
            ),
            transition_receipt_digest=(
                None
                if payload["transition_receipt_digest"] is None
                else str(payload["transition_receipt_digest"])
            ),
            controlled_operation_id=(
                None
                if payload["controlled_operation_id"] is None
                else str(payload["controlled_operation_id"])
            ),
            retired_at=(
                None if payload["retired_at"] is None else str(payload["retired_at"])
            ),
        )

    def runtime_binding(self) -> "WorkspaceRuntimeBinding":
        if self.status is not WorkspaceGenerationStatus.READY:
            raise ValueError("only a ready workspace generation has a runtime binding")
        assert self.root_identity_digest is not None
        return WorkspaceRuntimeBinding(
            workspace_id=self.workspace_id,
            workspace_kind=self.workspace_kind,
            session_id=self.session_id,
            owner_member_id=self.owner_member_id,
            generation=self.generation,
            state_version=self.state_version,
            root_identity_digest=self.root_identity_digest,
            provider_id=self.provider_id,
            target_id=self.target_id,
            target_qualification_digest=self.target_qualification_digest,
        )


class WorkspaceObservationKind(StrEnum):
    STATUS = "status"
    STAT = "stat"
    LIST = "list"
    READ = "read"
    HASH = "hash"


class WorkspaceFilesystemMutationKind(StrEnum):
    WRITE = "write"
    MKDIR = "mkdir"
    MOVE = "move"
    COPY = "copy"
    REMOVE = "remove"
    APPLY_PATCH = "apply_patch"


class WorkspaceTransferDirection(StrEnum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    SYNC_REVISION = "sync_revision"


class WorkspacePortError(RuntimeError):
    """Typed Adapter failure without permitting retry or provider fallback."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
        diagnostic_id: str | None = None,
    ) -> None:
        super().__init__(message)
        require_identifier(error_code, field_name="error_code")
        if diagnostic_id is not None:
            require_identifier(diagnostic_id, field_name="diagnostic_id")
        if effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if mutation_applied is not False:
                raise ValueError("no_effect WorkspacePortError requires mutation_applied=false")
        elif effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if mutation_applied is not None:
                raise ValueError(
                    "dispatch_in_doubt WorkspacePortError requires unknown mutation fact"
                )
        elif mutation_applied is None:
            raise ValueError("known WorkspacePortError requires a mutation fact")
        self.error_code = error_code
        self.effect_certainty = effect_certainty
        self.mutation_applied = mutation_applied
        self.diagnostic_id = diagnostic_id
        self.fallback_performed = False


def require_workspace_relative_path(
    value: str,
    *,
    field_name: str,
    allow_root: bool = False,
) -> str:
    if not isinstance(value, str) or "\x00" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a portable relative POSIX path")
    if any(character in value for character in ("*", "?", "[", "]")):
        raise ValueError(f"{field_name} must not contain implicit glob syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field_name} must remain inside the workspace root")
    normalized = path.as_posix()
    if normalized in ("", "."):
        if allow_root:
            return "."
        raise ValueError(f"{field_name} must name a path below the workspace root")
    return normalized


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeBinding:
    workspace_id: str
    workspace_kind: WorkspaceKind
    session_id: str
    owner_member_id: str
    generation: int
    state_version: int
    root_identity_digest: str
    provider_id: str
    target_id: str
    target_qualification_digest: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "workspace_id",
            "session_id",
            "owner_member_id",
            "provider_id",
            "target_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.generation < 1 or self.state_version < 1:
            raise ValueError("workspace generation and state_version must be positive")
        require_digest(
            self.root_identity_digest,
            field_name="root_identity_digest",
        )
        if self.workspace_kind is WorkspaceKind.EXECUTOR_REMOTE:
            if self.target_qualification_digest is None:
                raise ValueError("remote workspace requires target qualification")
            require_digest(
                self.target_qualification_digest,
                field_name="target_qualification_digest",
            )
        elif self.target_qualification_digest is not None:
            raise ValueError("local workspace must not bind remote qualification")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORKSPACE_RUNTIME_BINDING_SCHEMA_VERSION,
            "workspace_id": self.workspace_id,
            "workspace_kind": self.workspace_kind.value,
            "session_id": self.session_id,
            "owner_member_id": self.owner_member_id,
            "generation": self.generation,
            "state_version": self.state_version,
            "root_identity_digest": self.root_identity_digest,
            "provider_id": self.provider_id,
            "target_id": self.target_id,
            "target_qualification_digest": self.target_qualification_digest,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkspaceRuntimeBinding":
        expected = {
            "schema_version",
            "workspace_id",
            "workspace_kind",
            "session_id",
            "owner_member_id",
            "generation",
            "state_version",
            "root_identity_digest",
            "provider_id",
            "target_id",
            "target_qualification_digest",
        }
        if set(payload) != expected:
            raise ValueError("workspace runtime binding has an invalid closed schema")
        if payload["schema_version"] != WORKSPACE_RUNTIME_BINDING_SCHEMA_VERSION:
            raise ValueError("unsupported workspace runtime binding schema")
        for key in (
            "workspace_id",
            "workspace_kind",
            "session_id",
            "owner_member_id",
            "root_identity_digest",
            "provider_id",
            "target_id",
        ):
            if not isinstance(payload[key], str):
                raise TypeError(f"{key} must be a string")
        for key in ("generation", "state_version"):
            if not isinstance(payload[key], int) or isinstance(payload[key], bool):
                raise TypeError(f"{key} must be an integer")
        qualification = payload["target_qualification_digest"]
        if qualification is not None and not isinstance(qualification, str):
            raise TypeError("target_qualification_digest must be a string or null")
        return cls(
            workspace_id=payload["workspace_id"],
            workspace_kind=WorkspaceKind(payload["workspace_kind"]),
            session_id=payload["session_id"],
            owner_member_id=payload["owner_member_id"],
            generation=payload["generation"],
            state_version=payload["state_version"],
            root_identity_digest=payload["root_identity_digest"],
            provider_id=payload["provider_id"],
            target_id=payload["target_id"],
            target_qualification_digest=qualification,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceObservationRequest:
    binding: WorkspaceRuntimeBinding
    operation: WorkspaceObservationKind
    path: str = "."
    max_bytes: int = 65_536

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path",
            require_workspace_relative_path(
                self.path,
                field_name="path",
                allow_root=True,
            ),
        )
        if not 1 <= self.max_bytes <= WORKSPACE_STRUCTURED_OPERATION_MAX_BYTES:
            raise ValueError("max_bytes must be between 1 and 1048576")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORKSPACE_OBSERVATION_REQUEST_SCHEMA_VERSION,
            "binding": self.binding.to_dict(),
            "operation": self.operation.value,
            "path": self.path,
            "max_bytes": self.max_bytes,
        }

    @property
    def query_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class WorkspaceObservation:
    workspace_id: str
    generation: int
    state_version: int
    operation: WorkspaceObservationKind
    result_digest: str
    bounded_payload: bytes

    def __post_init__(self) -> None:
        require_identifier(self.workspace_id, field_name="workspace_id")
        require_digest(self.result_digest, field_name="result_digest")
        if self.generation < 1 or self.state_version < 1:
            raise ValueError("workspace generation and state_version must be positive")

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "generation": self.generation,
            "state_version": self.state_version,
            "operation": self.operation.value,
            "result_digest": self.result_digest,
            "bounded_payload_size": len(self.bounded_payload),
        }


@dataclass(frozen=True, slots=True)
class WorkspaceFilesystemMutation:
    operation_id: str
    binding: WorkspaceRuntimeBinding
    operation: WorkspaceFilesystemMutationKind
    path: str
    idempotency_key: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    destination_path: str | None = None
    content: bytes | None = None
    expected_content_digest: str | None = None
    recursive: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_identifier(self.idempotency_key, field_name="idempotency_key")
        require_identifier(self.authority_lease_id, field_name="authority_lease_id")
        for field_name in ("authority_generation", "authority_fence"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        object.__setattr__(
            self,
            "path",
            require_workspace_relative_path(self.path, field_name="path"),
        )
        if self.destination_path is not None:
            object.__setattr__(
                self,
                "destination_path",
                require_workspace_relative_path(
                    self.destination_path,
                    field_name="destination_path",
                ),
            )
        if self.expected_content_digest is not None:
            require_digest(
                self.expected_content_digest,
                field_name="expected_content_digest",
            )
        if (
            self.operation
            in {
                WorkspaceFilesystemMutationKind.MOVE,
                WorkspaceFilesystemMutationKind.COPY,
            }
            and self.destination_path is None
        ):
            raise ValueError("move/copy requires destination_path")
        if (
            self.operation
            in {
                WorkspaceFilesystemMutationKind.WRITE,
                WorkspaceFilesystemMutationKind.APPLY_PATCH,
            }
            and self.content is None
        ):
            raise ValueError("write/apply_patch requires content")
        if self.content is not None and len(self.content) > 1_048_576:
            raise ValueError("structured workspace mutation content exceeds 1 MiB")
        if (
            self.recursive
            and self.operation is not WorkspaceFilesystemMutationKind.REMOVE
        ):
            raise ValueError("recursive is only valid for remove")

    def intent_payload(self) -> dict[str, Any]:
        return {
            "schema_version": WORKSPACE_FILESYSTEM_MUTATION_SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "binding": self.binding.to_dict(),
            "operation": self.operation.value,
            "path": self.path,
            "destination_path": self.destination_path,
            "content_digest": (
                None
                if self.content is None
                else _bytes_digest(self.content)
            ),
            "content_size": None if self.content is None else len(self.content),
            "expected_content_digest": self.expected_content_digest,
            "recursive": self.recursive,
            "idempotency_key": self.idempotency_key,
            "authority_lease_id": self.authority_lease_id,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
        }

    @property
    def intent_digest(self) -> str:
        return canonical_sha256_digest(self.intent_payload())


@dataclass(frozen=True, slots=True)
class WorkspaceExecRequest:
    operation_id: str
    binding: WorkspaceRuntimeBinding
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    max_output_bytes: int
    idempotency_key: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    process_epoch: int
    stdin: bytes = field(default=b"", repr=False)
    interactive: bool = False
    background: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_identifier(self.idempotency_key, field_name="idempotency_key")
        require_identifier(self.authority_lease_id, field_name="authority_lease_id")
        for field_name in (
            "authority_generation",
            "authority_fence",
            "process_epoch",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if not self.argv or len(self.argv) > 256:
            raise ValueError("argv must contain between 1 and 256 entries")
        if any(not value or "\x00" in value for value in self.argv):
            raise ValueError("argv entries must be non-empty and contain no NUL")
        object.__setattr__(self, "argv", tuple(self.argv))
        object.__setattr__(
            self,
            "cwd",
            require_workspace_relative_path(
                self.cwd,
                field_name="cwd",
                allow_root=True,
            ),
        )
        if not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be between 1 and 3600")
        if not 256 <= self.max_output_bytes <= 4_194_304:
            raise ValueError("max_output_bytes must be between 256 and 4194304")
        if len(self.stdin) > 1_048_576:
            raise ValueError("stdin exceeds the bounded request limit")
        if self.interactive:
            raise ValueError("interactive workspace processes are not supported")
        if self.background:
            raise ValueError("background workspace processes are not supported")

    def intent_payload(self) -> dict[str, Any]:
        return {
            "schema_version": WORKSPACE_EXEC_REQUEST_SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "binding": self.binding.to_dict(),
            "argv": list(self.argv),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "idempotency_key": self.idempotency_key,
            "authority_lease_id": self.authority_lease_id,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
            "process_epoch": self.process_epoch,
            "stdin_digest": _bytes_digest(self.stdin),
            "stdin_size": len(self.stdin),
            "interactive": self.interactive,
            "background": self.background,
        }

    @property
    def intent_digest(self) -> str:
        return canonical_sha256_digest(self.intent_payload())


@dataclass(frozen=True, slots=True)
class WorkspaceTransferRequest:
    operation_id: str
    binding: WorkspaceRuntimeBinding
    direction: WorkspaceTransferDirection
    path: str
    transfer_ref: str
    transfer_manifest_digest: str
    max_bytes: int
    timeout_seconds: int
    idempotency_key: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        if (
            not isinstance(self.transfer_ref, str)
            or _OPAQUE_TRANSFER_REF.fullmatch(self.transfer_ref) is None
        ):
            raise ValueError(
                "transfer_ref must be an opaque identifier, not a path or URL"
            )
        require_digest(
            self.transfer_manifest_digest,
            field_name="transfer_manifest_digest",
        )
        if not 1 <= self.max_bytes <= 68_719_476_736:
            raise ValueError("max_bytes must be between 1 and 68719476736")
        if not 1 <= self.timeout_seconds <= 14_400:
            raise ValueError("timeout_seconds must be between 1 and 14400")
        require_identifier(self.idempotency_key, field_name="idempotency_key")
        require_identifier(self.authority_lease_id, field_name="authority_lease_id")
        for field_name in ("authority_generation", "authority_fence"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        object.__setattr__(
            self,
            "path",
            require_workspace_relative_path(self.path, field_name="path"),
        )

    def intent_payload(self) -> dict[str, Any]:
        return {
            "schema_version": WORKSPACE_TRANSFER_REQUEST_SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "binding": self.binding.to_dict(),
            "direction": self.direction.value,
            "path": self.path,
            "transfer_ref": self.transfer_ref,
            "transfer_manifest_digest": self.transfer_manifest_digest,
            "max_bytes": self.max_bytes,
            "timeout_seconds": self.timeout_seconds,
            "idempotency_key": self.idempotency_key,
            "authority_lease_id": self.authority_lease_id,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
        }

    @property
    def intent_digest(self) -> str:
        return canonical_sha256_digest(self.intent_payload())


@dataclass(frozen=True, slots=True)
class WorkspaceOperationReceipt:
    operation_id: str
    workspace_id: str
    generation: int
    state_version: int
    effect_certainty: ExternalEffectCertainty
    mutation_applied: bool | None
    fallback_performed: bool
    receipt_digest: str
    result_payload: bytes = field(default=b"", repr=False)
    result_media_type: str = "application/json"
    diagnostic_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_identifier(self.workspace_id, field_name="workspace_id")
        if self.diagnostic_id is not None:
            require_identifier(self.diagnostic_id, field_name="diagnostic_id")
        require_digest(self.receipt_digest, field_name="receipt_digest")
        if not isinstance(self.result_payload, bytes):
            raise TypeError("result_payload must be bytes")
        if len(self.result_payload) > 4_194_304:
            raise ValueError("workspace result payload exceeds the absolute byte limit")
        if (
            not isinstance(self.result_media_type, str)
            or not self.result_media_type
            or self.result_media_type != self.result_media_type.strip()
            or any(character.isspace() for character in self.result_media_type)
        ):
            raise ValueError("result_media_type must be one bounded media type")
        if self.fallback_performed:
            raise ValueError(
                "Workspace Runtime receipts must not report hidden fallback"
            )
        if self.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if self.mutation_applied is not False:
                raise ValueError("no_effect receipt cannot report a mutation")
        elif self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.mutation_applied is not None:
                raise ValueError(
                    "dispatch_in_doubt receipt cannot claim mutation certainty"
                )
            if self.result_payload:
                raise ValueError(
                    "dispatch_in_doubt receipt cannot expose an unverified result"
                )
        elif self.mutation_applied is None:
            raise ValueError("known effect receipt requires a mutation fact")
        if self.generation < 1 or self.state_version < 1:
            raise ValueError("workspace generation and state_version must be positive")
        if self.receipt_digest != canonical_sha256_digest(self.digest_payload()):
            raise ValueError("workspace operation receipt digest mismatch")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": WORKSPACE_OPERATION_RECEIPT_SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "generation": self.generation,
            "state_version": self.state_version,
            "effect_certainty": self.effect_certainty.value,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "result_payload_digest": _bytes_digest(self.result_payload),
            "result_payload_size": len(self.result_payload),
            "result_media_type": self.result_media_type,
            "diagnostic_id": self.diagnostic_id,
        }

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        workspace_id: str,
        generation: int,
        state_version: int,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
        result_payload: bytes = b"",
        result_media_type: str = "application/json",
        diagnostic_id: str | None = None,
    ) -> WorkspaceOperationReceipt:
        payload = {
            "schema_version": WORKSPACE_OPERATION_RECEIPT_SCHEMA_VERSION,
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "generation": generation,
            "state_version": state_version,
            "effect_certainty": effect_certainty.value,
            "mutation_applied": mutation_applied,
            "fallback_performed": False,
            "result_payload_digest": _bytes_digest(result_payload),
            "result_payload_size": len(result_payload),
            "result_media_type": result_media_type,
            "diagnostic_id": diagnostic_id,
        }
        return cls(
            operation_id=operation_id,
            workspace_id=workspace_id,
            generation=generation,
            state_version=state_version,
            effect_certainty=effect_certainty,
            mutation_applied=mutation_applied,
            fallback_performed=False,
            receipt_digest=canonical_sha256_digest(payload),
            result_payload=result_payload,
            result_media_type=result_media_type,
            diagnostic_id=diagnostic_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "receipt_digest": self.receipt_digest}


class WorkspaceObservationPort(Protocol):
    def observe(self, request: WorkspaceObservationRequest) -> WorkspaceObservation: ...


class WorkspaceFilesystemPort(Protocol):
    def mutate(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt: ...

    def reconcile(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt: ...


class WorkspaceProcessPort(Protocol):
    def execute(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt: ...

    def reconcile(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt: ...


class WorkspaceTransferPort(Protocol):
    def transfer(
        self, request: WorkspaceTransferRequest
    ) -> WorkspaceOperationReceipt: ...

    def reconcile(
        self, request: WorkspaceTransferRequest
    ) -> WorkspaceOperationReceipt: ...


__all__ = [
    "WORKSPACE_EXEC_REQUEST_SCHEMA_VERSION",
    "WORKSPACE_FILESYSTEM_MUTATION_SCHEMA_VERSION",
    "WORKSPACE_OBSERVATION_REQUEST_SCHEMA_VERSION",
    "WORKSPACE_OPERATION_RECEIPT_SCHEMA_VERSION",
    "WORKSPACE_RUNTIME_BINDING_SCHEMA_VERSION",
    "WORKSPACE_TRANSFER_REQUEST_SCHEMA_VERSION",
    "WORKSPACE_STRUCTURED_OPERATION_MAX_BYTES",
    "WORKSPACE_FILESYSTEM_PORT_CONTRACT",
    "WORKSPACE_FILESYSTEM_PORT_CONTRACT_DIGEST",
    "WORKSPACE_OBSERVATION_PORT_CONTRACT",
    "WORKSPACE_OBSERVATION_PORT_CONTRACT_DIGEST",
    "WORKSPACE_PROCESS_PORT_CONTRACT",
    "WORKSPACE_PROCESS_PORT_CONTRACT_DIGEST",
    "WORKSPACE_TRANSFER_PORT_CONTRACT",
    "WORKSPACE_TRANSFER_PORT_CONTRACT_DIGEST",
    "WorkspaceExecRequest",
    "WorkspaceFilesystemMutation",
    "WorkspaceFilesystemMutationKind",
    "WorkspaceFilesystemPort",
    "WorkspaceKind",
    "WorkspaceObservation",
    "WorkspaceObservationKind",
    "WorkspaceObservationPort",
    "WorkspaceObservationRequest",
    "WorkspaceOperationReceipt",
    "WorkspacePortError",
    "WorkspaceProcessPort",
    "WorkspaceRuntimeBinding",
    "WorkspaceTransferDirection",
    "WorkspaceTransferPort",
    "WorkspaceTransferRequest",
    "require_workspace_relative_path",
]
