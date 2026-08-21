from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
import re
from typing import Any

from openzyme_execution_contracts.workspace_job_wire import (
    canonical_workspace_job_wire_digest,
)
from openzyme_execution_contracts.workspace_job_wire import parse_external_job_handle
from openzyme_execution_contracts.workspace_job_wire import (
    parse_external_job_observation,
)
from openzyme_execution_contracts.workspace_job_wire import (
    parse_workspace_job_cancellation_intent,
)
from openzyme_execution_contracts.workspace_job_wire import (
    parse_workspace_job_cancellation_receipt,
)


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def canonical_workspace_job_digest(value: object) -> str:
    return canonical_workspace_job_wire_digest(value)


def _serialize(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


def _creation_payload(
    schema_version: str,
    values: dict[str, Any],
) -> dict[str, object]:
    return {
        "schema_version": str(values.get("schema_version", schema_version)),
        **{
            key: _serialize(value)
            for key, value in values.items()
            if key != "schema_version"
        },
    }


def _record(record: object, schema_version: str) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        **{key: _serialize(value) for key, value in asdict(record).items()},
    }


def _require_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} is not a safe identifier")


def _require_digest(name: str, value: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} is not a sha256 digest")


def _require_oid(name: str, value: str) -> None:
    if not isinstance(value, str) or _OID.fullmatch(value) is None:
        raise ValueError(f"{name} is not an exact Git object id")


def _require_aware_timestamp(name: str, value: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include an explicit timezone")


def _require_relative_path(name: str, value: str, *, allow_dot: bool = True) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or (not allow_dot and value == ".")
    ):
        raise ValueError(f"{name} must be a canonical repository-relative path")


class WorkspaceRevisionSourceClass(StrEnum):
    PRIVATE = "private"
    PUBLISHED = "published"


class WorkspaceJobExecutionMode(StrEnum):
    SSH = "ssh"
    SBATCH = "sbatch"
    AUTO = "auto"


class WorkspaceExternalBackend(StrEnum):
    DIRECT = "direct"
    SLURM = "slurm"


class SchedulerCredentialOccurrenceState(StrEnum):
    RESERVED = "reserved"
    ISSUED = "issued"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class WorkspaceJobObservationState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True, slots=True)
class WorkspaceRevisionScientificBasis:
    attempt_id: str
    attempt_state_version: int
    admission_request_id: str
    admission_request_digest: str
    source_envelope_id: str
    workflow_contract_digest: str
    scope_digest: str
    effect_class_digest: str
    hpc_target_digest: str

    def __post_init__(self) -> None:
        for name in ("attempt_id", "admission_request_id", "source_envelope_id"):
            _require_identifier(name, getattr(self, name))
        if (
            not isinstance(self.attempt_state_version, int)
            or isinstance(self.attempt_state_version, bool)
            or self.attempt_state_version < 1
        ):
            raise ValueError("attempt_state_version must be a positive integer")
        for name in (
            "admission_request_digest",
            "workflow_contract_digest",
            "scope_digest",
            "effect_class_digest",
            "hpc_target_digest",
        ):
            _require_digest(name, getattr(self, name))

    def to_dict(self) -> dict[str, object]:
        return _record(self, "workspace_revision_scientific_basis@1")


@dataclass(frozen=True, slots=True)
class WorkspaceRevisionExecutionRequest:
    request_id: str
    execution_id: str
    operation_id: str
    operation_digest: str
    session_id: str
    executor_agent_member_id: str
    capability_lease_id: str
    capability_lease_version: int
    executor_hpc_workspace_id: str
    remote_workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    source_class: WorkspaceRevisionSourceClass
    source_revision_id: str
    source_ref: str
    source_commit: str
    source_tree: str
    lfs_closure_manifest_digest: str
    clean_observation_digest: str
    cwd: str
    command: tuple[str, ...]
    command_digest: str
    environment_policy_digest: str
    resources: dict[str, object]
    resource_digest: str
    requested_mode: WorkspaceJobExecutionMode
    target_profile_id: str
    target_profile_digest: str
    runner_policy_digest: str
    runtime_identity_digest: str
    absolute_deadline: str
    created_at: str
    scientific_basis: WorkspaceRevisionScientificBasis | None = None
    operation_approval_digest: str | None = None
    request_digest: str = ""
    schema_version: str = "workspace_revision_execution_request@1"

    def __post_init__(self) -> None:
        if self.schema_version != "workspace_revision_execution_request@1":
            raise ValueError("unsupported workspace revision execution request")
        for name in (
            "request_id",
            "execution_id",
            "operation_id",
            "session_id",
            "executor_agent_member_id",
            "capability_lease_id",
            "executor_hpc_workspace_id",
            "repository_binding_id",
            "target_profile_id",
            "source_revision_id",
        ):
            _require_identifier(name, getattr(self, name))
        for name in (
            "operation_digest",
            "lfs_closure_manifest_digest",
            "clean_observation_digest",
            "command_digest",
            "environment_policy_digest",
            "resource_digest",
            "target_profile_digest",
            "runner_policy_digest",
            "runtime_identity_digest",
        ):
            _require_digest(name, getattr(self, name))
        for name in (
            "capability_lease_version",
            "remote_workspace_generation",
            "repository_binding_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        _require_oid("source_commit", self.source_commit)
        _require_oid("source_tree", self.source_tree)
        if not isinstance(self.source_ref, str) or not self.source_ref.startswith(
            "refs/"
        ):
            raise ValueError("source_ref must be an exact Git ref")
        _require_relative_path("cwd", self.cwd)
        if (
            not isinstance(self.command, tuple)
            or not self.command
            or any(not isinstance(item, str) or not item for item in self.command)
        ):
            raise ValueError("command must be a non-empty tuple of strings")
        if self.command_digest != canonical_workspace_job_digest(list(self.command)):
            raise ValueError("command_digest does not match command")
        if not isinstance(self.resources, dict):
            raise ValueError("resources must be an object")
        expected_resource_fields = {
            "cpus",
            "mem_mb",
            "gpus",
            "time_minutes",
            "partition",
        }
        if set(self.resources) != expected_resource_fields:
            raise ValueError(
                "resources must use the closed cpus/mem_mb/gpus/time_minutes/partition schema"
            )
        for name, minimum in (
            ("cpus", 1),
            ("mem_mb", 1),
            ("gpus", 0),
            ("time_minutes", 1),
        ):
            resource_value = self.resources[name]
            if (
                not isinstance(resource_value, int)
                or isinstance(resource_value, bool)
                or resource_value < minimum
            ):
                raise ValueError(f"resources.{name} must be an integer >= {minimum}")
        partition = self.resources["partition"]
        if partition is not None and (
            not isinstance(partition, str) or not partition.strip()
        ):
            raise ValueError("resources.partition must be a non-empty string or null")
        if self.resource_digest != canonical_workspace_job_digest(self.resources):
            raise ValueError("resource_digest does not match resources")
        if self.scientific_basis is not None and self.operation_approval_digest:
            raise ValueError(
                "scientific basis and independent operation approval are exclusive"
            )
        if self.operation_approval_digest is not None:
            _require_digest("operation_approval_digest", self.operation_approval_digest)
        _require_aware_timestamp("absolute_deadline", self.absolute_deadline)
        _require_aware_timestamp("created_at", self.created_at)
        if self.request_digest != canonical_workspace_job_digest(self.identity_payload):
            raise ValueError("workspace revision execution request digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "operation_digest": self.operation_digest,
            "session_id": self.session_id,
            "executor_agent_member_id": self.executor_agent_member_id,
            "capability_lease_id": self.capability_lease_id,
            "capability_lease_version": self.capability_lease_version,
            "executor_hpc_workspace_id": self.executor_hpc_workspace_id,
            "remote_workspace_generation": self.remote_workspace_generation,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "source_class": self.source_class.value,
            "source_revision_id": self.source_revision_id,
            "source_ref": self.source_ref,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "lfs_closure_manifest_digest": self.lfs_closure_manifest_digest,
            "clean_observation_digest": self.clean_observation_digest,
            "cwd": self.cwd,
            "command": list(self.command),
            "command_digest": self.command_digest,
            "environment_policy_digest": self.environment_policy_digest,
            "resources": self.resources,
            "resource_digest": self.resource_digest,
            "requested_mode": self.requested_mode.value,
            "target_profile_id": self.target_profile_id,
            "target_profile_digest": self.target_profile_digest,
            "runner_policy_digest": self.runner_policy_digest,
            "runtime_identity_digest": self.runtime_identity_digest,
            "absolute_deadline": self.absolute_deadline,
            "created_at": self.created_at,
            "scientific_basis": (
                None
                if self.scientific_basis is None
                else self.scientific_basis.to_dict()
            ),
            "operation_approval_digest": self.operation_approval_digest,
        }

    def to_private_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "request_digest": self.request_digest}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkspaceRevisionExecutionRequest":
        expected = set(cls.__dataclass_fields__) - {"schema_version"}
        expected.add("schema_version")
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("workspace revision execution request fields are closed")
        if value["schema_version"] != "workspace_revision_execution_request@1":
            raise ValueError("workspace revision execution request schema is unsupported")
        basis_value = value["scientific_basis"]
        basis = None
        if basis_value is not None:
            if not isinstance(basis_value, dict):
                raise ValueError("scientific basis must be an object or null")
            basis_fields = {
                "schema_version",
                "attempt_id",
                "attempt_state_version",
                "admission_request_id",
                "admission_request_digest",
                "source_envelope_id",
                "workflow_contract_digest",
                "scope_digest",
                "effect_class_digest",
                "hpc_target_digest",
            }
            if set(basis_value) != basis_fields:
                raise ValueError("scientific basis fields are closed")
            basis = WorkspaceRevisionScientificBasis(
                **{
                    key: basis_value[key]
                    for key in basis_fields
                    if key != "schema_version"
                }
            )
        return cls(
            **{
                key: value[key]
                for key in expected
                if key
                not in {"schema_version", "scientific_basis", "source_class", "requested_mode", "command"}
            },
            source_class=WorkspaceRevisionSourceClass(value["source_class"]),
            requested_mode=WorkspaceJobExecutionMode(value["requested_mode"]),
            command=tuple(value["command"]),
            scientific_basis=basis,
            schema_version=value["schema_version"],
        )

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceRevisionExecutionRequest":
        return cls(
            **values,
            request_digest=canonical_workspace_job_digest(
                _creation_payload(
                    "workspace_revision_execution_request@1", values
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceRevisionCleanObservation:
    observation_id: str
    request_id: str
    workspace_id: str
    remote_workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    source_commit: str
    source_tree: str
    lfs_closure_manifest_digest: str
    head_matches: bool
    index_clean: bool
    tracked_tree_clean: bool
    untracked_policy_clean: bool
    attributes_digest: str
    cwd_present: bool
    observed_at: str
    observation_digest: str
    schema_version: str = "workspace_revision_clean_observation@1"

    def __post_init__(self) -> None:
        for name in ("observation_id", "request_id", "workspace_id", "repository_binding_id"):
            _require_identifier(name, getattr(self, name))
        for name in ("remote_workspace_generation", "repository_binding_version"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        _require_oid("source_commit", self.source_commit)
        _require_oid("source_tree", self.source_tree)
        for name in (
            "lfs_closure_manifest_digest",
            "attributes_digest",
        ):
            _require_digest(name, getattr(self, name))
        if not all(
            isinstance(getattr(self, name), bool)
            for name in (
                "head_matches",
                "index_clean",
                "tracked_tree_clean",
                "untracked_policy_clean",
                "cwd_present",
            )
        ):
            raise ValueError("clean observation flags must be booleans")
        _require_aware_timestamp("observed_at", self.observed_at)
        if self.observation_digest != canonical_workspace_job_digest(self.payload):
            raise ValueError("clean observation digest mismatch")

    @property
    def clean(self) -> bool:
        return all(
            (
                self.head_matches,
                self.index_clean,
                self.tracked_tree_clean,
                self.untracked_policy_clean,
                self.cwd_present,
            )
        )

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "observation_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceRevisionCleanObservation":
        return cls(
            **values,
            observation_digest=canonical_workspace_job_digest(
                _creation_payload(
                    "workspace_revision_clean_observation@1", values
                )
            ),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkspaceRevisionCleanObservation":
        expected = set(cls.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("workspace clean observation fields are closed")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class ComputeSourceManifestEntry:
    path: str
    object_id: str
    mode: str
    size_bytes: int
    content_digest: str
    lfs_oid: str | None = None

    def __post_init__(self) -> None:
        _require_relative_path("manifest path", self.path, allow_dot=False)
        _require_oid("manifest object_id", self.object_id)
        if self.mode not in {"100644", "100755", "120000"}:
            raise ValueError("manifest mode is unsupported")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
        ):
            raise ValueError("manifest size_bytes is invalid")
        _require_digest("content_digest", self.content_digest)
        if self.lfs_oid is not None:
            _require_digest("lfs_oid", self.lfs_oid)

    def to_dict(self) -> dict[str, object]:
        return _record(self, "compute_source_manifest_entry@1")


@dataclass(frozen=True, slots=True)
class ComputeSourceManifest:
    manifest_id: str
    request_id: str
    workspace_id: str
    source_commit: str
    source_tree: str
    lfs_closure_manifest_digest: str
    binding_digest: str
    repository_policy_digest: str
    target_inventory_generation: int
    target_inventory_digest: str
    owner_identity_digest: str
    entries: tuple[ComputeSourceManifestEntry, ...]
    created_at: str
    manifest_digest: str
    schema_version: str = "compute_source_manifest@2"

    def __post_init__(self) -> None:
        for name in ("manifest_id", "request_id", "workspace_id"):
            _require_identifier(name, getattr(self, name))
        _require_oid("source_commit", self.source_commit)
        _require_oid("source_tree", self.source_tree)
        for name in (
            "lfs_closure_manifest_digest",
            "binding_digest",
            "repository_policy_digest",
            "target_inventory_digest",
            "owner_identity_digest",
        ):
            _require_digest(name, getattr(self, name))
        if (
            not isinstance(self.target_inventory_generation, int)
            or isinstance(self.target_inventory_generation, bool)
            or self.target_inventory_generation < 1
        ):
            raise ValueError("target_inventory_generation must be positive")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("compute source manifest must contain entries")
        paths = tuple(item.path for item in self.entries)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("compute source manifest entries must be unique and sorted")
        if any(path == ".git" or path.startswith(".git/") for path in paths):
            raise ValueError("compute source manifest must exclude Git metadata")
        _require_aware_timestamp("created_at", self.created_at)
        if self.manifest_digest != canonical_workspace_job_digest(self.payload):
            raise ValueError("compute source manifest digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "request_id": self.request_id,
            "workspace_id": self.workspace_id,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "lfs_closure_manifest_digest": self.lfs_closure_manifest_digest,
            "binding_digest": self.binding_digest,
            "repository_policy_digest": self.repository_policy_digest,
            "target_inventory_generation": self.target_inventory_generation,
            "target_inventory_digest": self.target_inventory_digest,
            "owner_identity_digest": self.owner_identity_digest,
            "entries": [entry.to_dict() for entry in self.entries],
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> "ComputeSourceManifest":
        return cls(
            **values,
            manifest_digest=canonical_workspace_job_digest(
                _creation_payload("compute_source_manifest@2", values)
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceJobTargetQualification:
    target_profile_id: str
    target_profile_digest: str
    runner_policy_digest: str
    protected_submit_wrapper_digest: str
    dispatch_ledger_digest: str
    scheduler_credential_provider_id: str
    scheduler_credential_audience: str
    scheduler_marker_policy_digest: str
    scheduler_accounting_proof_digest: str
    ambient_submit_denial_proof_digest: str
    direct_process_ledger_proof_digest: str
    slurm_enabled: bool
    direct_enabled: bool
    qualified_at: str
    qualification_digest: str
    schema_version: str = "workspace_job_target_qualification@1"

    def __post_init__(self) -> None:
        for name in (
            "target_profile_id",
            "scheduler_credential_provider_id",
            "scheduler_credential_audience",
        ):
            _require_identifier(name, getattr(self, name))
        for name in (
            "target_profile_digest",
            "runner_policy_digest",
            "protected_submit_wrapper_digest",
            "dispatch_ledger_digest",
            "scheduler_marker_policy_digest",
            "scheduler_accounting_proof_digest",
            "ambient_submit_denial_proof_digest",
            "direct_process_ledger_proof_digest",
        ):
            _require_digest(name, getattr(self, name))
        if not isinstance(self.slurm_enabled, bool) or not isinstance(
            self.direct_enabled, bool
        ):
            raise ValueError("target mode qualification flags must be booleans")
        if not (self.slurm_enabled or self.direct_enabled):
            raise ValueError("at least one reliable job mode must be qualified")
        _require_aware_timestamp("qualified_at", self.qualified_at)
        if self.qualification_digest != canonical_workspace_job_digest(self.payload):
            raise ValueError("workspace job target qualification digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "qualification_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceJobTargetQualification":
        return cls(
            **values,
            qualification_digest=canonical_workspace_job_digest(
                _creation_payload(
                    "workspace_job_target_qualification@1", values
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceJobDispatchIntent:
    dispatch_id: str
    execution_id: str
    operation_id: str
    execution_state_version: int
    execution_fencing_token: int
    request_id: str
    request_digest: str
    runner_run_id: str
    workspace_id: str
    remote_workspace_generation: int
    source_manifest_digest: str
    selected_mode: WorkspaceJobExecutionMode
    command_digest: str
    resource_digest: str
    target_profile_digest: str
    scheduler_marker: str
    payload_digest: str
    absolute_deadline: str
    created_at: str
    intent_digest: str
    schema_version: str = "workspace_job_dispatch_intent@1"

    def __post_init__(self) -> None:
        for name in (
            "dispatch_id",
            "execution_id",
            "operation_id",
            "request_id",
            "runner_run_id",
            "workspace_id",
            "scheduler_marker",
        ):
            _require_identifier(name, getattr(self, name))
        for name in (
            "execution_state_version",
            "remote_workspace_generation",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if (
            not isinstance(self.execution_fencing_token, int)
            or isinstance(self.execution_fencing_token, bool)
            or self.execution_fencing_token < 0
        ):
            raise ValueError("execution_fencing_token is invalid")
        if self.selected_mode is WorkspaceJobExecutionMode.AUTO:
            raise ValueError("dispatch intent must freeze ssh or sbatch mode")
        for name in (
            "request_digest",
            "source_manifest_digest",
            "command_digest",
            "resource_digest",
            "target_profile_digest",
            "payload_digest",
        ):
            _require_digest(name, getattr(self, name))
        _require_aware_timestamp("absolute_deadline", self.absolute_deadline)
        _require_aware_timestamp("created_at", self.created_at)
        if self.intent_digest != canonical_workspace_job_digest(self.payload):
            raise ValueError("workspace job dispatch intent digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "intent_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceJobDispatchIntent":
        return cls(
            **values,
            intent_digest=canonical_workspace_job_digest(
                _creation_payload("workspace_job_dispatch_intent@1", values)
            ),
        )


@dataclass(frozen=True, slots=True)
class SchedulerCredentialOccurrence:
    occurrence_id: str
    dispatch_id: str
    execution_id: str
    execution_fencing_token: int
    target_profile_digest: str
    reservation_nonce_digest: str
    scheduler_marker: str
    payload_digest: str
    protected_wrapper_audience: str
    credential_fingerprint: str | None
    authentication_receipt_digest: str | None
    consumption_receipt_digest: str | None
    state: SchedulerCredentialOccurrenceState
    reserved_at: str
    expires_at: str
    issued_at: str | None = None
    consumed_at: str | None = None
    rejection_code: str | None = None
    schema_version: str = "scheduler_credential_occurrence@1"

    def __post_init__(self) -> None:
        for name in (
            "occurrence_id",
            "dispatch_id",
            "execution_id",
            "scheduler_marker",
            "protected_wrapper_audience",
        ):
            _require_identifier(name, getattr(self, name))
        if (
            not isinstance(self.execution_fencing_token, int)
            or isinstance(self.execution_fencing_token, bool)
            or self.execution_fencing_token < 0
        ):
            raise ValueError("execution_fencing_token is invalid")
        for name in (
            "target_profile_digest",
            "reservation_nonce_digest",
            "payload_digest",
        ):
            _require_digest(name, getattr(self, name))
        for name in (
            "credential_fingerprint",
            "authentication_receipt_digest",
            "consumption_receipt_digest",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_digest(name, value)
        for name in ("reserved_at", "expires_at"):
            _require_aware_timestamp(name, getattr(self, name))
        for name in ("issued_at", "consumed_at"):
            value = getattr(self, name)
            if value is not None:
                _require_aware_timestamp(name, value)
        if self.state is SchedulerCredentialOccurrenceState.RESERVED:
            if any(
                value is not None
                for value in (
                    self.credential_fingerprint,
                    self.authentication_receipt_digest,
                    self.consumption_receipt_digest,
                    self.issued_at,
                    self.consumed_at,
                    self.rejection_code,
                )
            ):
                raise ValueError("reserved occurrence cannot contain issue outcome")
        elif self.state is SchedulerCredentialOccurrenceState.ISSUED:
            if (
                self.credential_fingerprint is None
                or self.authentication_receipt_digest is None
                or self.issued_at is None
                or self.consumed_at is not None
                or self.consumption_receipt_digest is not None
            ):
                raise ValueError("issued occurrence is incomplete")
        elif self.state is SchedulerCredentialOccurrenceState.CONSUMED:
            if (
                self.credential_fingerprint is None
                or self.authentication_receipt_digest is None
                or self.issued_at is None
                or self.consumed_at is None
                or self.consumption_receipt_digest is None
            ):
                raise ValueError("consumed occurrence is incomplete")
        elif (
            not self.rejection_code
            or self.consumption_receipt_digest is not None
            or self.consumed_at is not None
        ):
            raise ValueError(
                "rejected or expired occurrence requires a code and no consumption"
            )

    def to_private_dict(self) -> dict[str, object]:
        return _record(self, self.schema_version)


@dataclass(frozen=True, slots=True)
class ExternalJobHandle:
    handle_id: str
    execution_id: str
    operation_id: str
    dispatch_id: str
    runner_run_id: str
    job_root_token: str
    target_profile_digest: str
    workspace_id: str
    remote_workspace_generation: int
    source_commit: str
    source_manifest_digest: str
    backend: WorkspaceExternalBackend
    raw_handle_ciphertext: str
    acceptance_receipt_digest: str
    accepted_at: str
    handle_digest: str
    schema_version: str = "external_job_handle@1"

    def __post_init__(self) -> None:
        parse_external_job_handle(_record(self, self.schema_version))

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "handle_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "ExternalJobHandle":
        return cls(
            **values,
            handle_digest=canonical_workspace_job_digest(
                _creation_payload("external_job_handle@1", values)
            ),
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "handle_id": self.handle_id,
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "runner_run_id": self.runner_run_id,
            "job_root_token": self.job_root_token,
            "workspace_id": self.workspace_id,
            "remote_workspace_generation": self.remote_workspace_generation,
            "source_commit": self.source_commit,
            "source_manifest_digest": self.source_manifest_digest,
            "backend": self.backend.value,
            "accepted_at": self.accepted_at,
            "handle_digest": self.handle_digest,
        }


@dataclass(frozen=True, slots=True)
class ExternalJobObservation:
    observation_id: str
    handle_id: str
    execution_id: str
    dispatch_id: str
    observation_index: int
    state: WorkspaceJobObservationState
    exit_code: int | None
    terminal_receipt_digest: str | None
    bounded_stdout: str | None
    bounded_stderr: str | None
    observed_at: str
    observation_digest: str
    schema_version: str = "external_job_observation@1"

    def __post_init__(self) -> None:
        parse_external_job_observation(_record(self, self.schema_version))

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "observation_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "ExternalJobObservation":
        return cls(
            **values,
            observation_digest=canonical_workspace_job_digest(
                _creation_payload("external_job_observation@1", values)
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceJobCancellationIntent:
    cancellation_id: str
    execution_id: str
    handle_id: str
    execution_state_version: int
    execution_fencing_token: int
    idempotency_key: str
    reason_digest: str
    created_at: str
    intent_digest: str
    schema_version: str = "workspace_job_cancellation_intent@1"

    def __post_init__(self) -> None:
        parse_workspace_job_cancellation_intent(self.payload)
        if self.intent_digest != canonical_workspace_job_digest(self.payload):
            raise ValueError("workspace job cancellation intent digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "intent_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceJobCancellationIntent":
        return cls(
            **values,
            intent_digest=canonical_workspace_job_digest(
                _creation_payload("workspace_job_cancellation_intent@1", values)
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceJobCancellationReceipt:
    receipt_id: str
    cancellation_id: str
    handle_id: str
    cancellation_requested: bool
    terminal_settlement_proven: bool
    backend_receipt_digest: str
    created_at: str
    receipt_digest: str
    schema_version: str = "workspace_job_cancellation_receipt@1"

    def __post_init__(self) -> None:
        parse_workspace_job_cancellation_receipt(_record(self, self.schema_version))

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "receipt_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceJobCancellationReceipt":
        return cls(
            **values,
            receipt_digest=canonical_workspace_job_digest(
                _creation_payload("workspace_job_cancellation_receipt@1", values)
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceJobResult:
    result_id: str
    execution_id: str
    operation_id: str
    handle_id: str
    runner_run_id: str
    terminal_observation_id: str
    terminal_observation_digest: str
    terminal_state: WorkspaceJobObservationState
    exit_code: int | None
    source_commit: str
    source_manifest_digest: str
    workspace_id: str
    remote_workspace_generation: int
    job_root_token: str
    cwd: str
    command_digest: str
    resource_digest: str
    target_profile_digest: str
    created_at: str
    result_digest: str
    schema_version: str = "workspace_job_result@1"

    def __post_init__(self) -> None:
        for name in (
            "result_id",
            "execution_id",
            "operation_id",
            "handle_id",
            "runner_run_id",
            "terminal_observation_id",
            "workspace_id",
            "job_root_token",
        ):
            _require_identifier(name, getattr(self, name))
        if not self.terminal_state.is_terminal:
            raise ValueError("workspace job result requires a terminal observation")
        if self.exit_code is not None and (
            not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)
        ):
            raise ValueError("exit_code must be an integer")
        _require_oid("source_commit", self.source_commit)
        _require_relative_path("cwd", self.cwd)
        if (
            not isinstance(self.remote_workspace_generation, int)
            or isinstance(self.remote_workspace_generation, bool)
            or self.remote_workspace_generation < 1
        ):
            raise ValueError("remote_workspace_generation must be positive")
        for name in (
            "terminal_observation_digest",
            "source_manifest_digest",
            "command_digest",
            "resource_digest",
            "target_profile_digest",
        ):
            _require_digest(name, getattr(self, name))
        _require_aware_timestamp("created_at", self.created_at)
        if self.result_digest != canonical_workspace_job_digest(self.payload):
            raise ValueError("workspace job result digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "result_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceJobResult":
        return cls(
            **values,
            result_digest=canonical_workspace_job_digest(
                _creation_payload("workspace_job_result@1", values)
            ),
        )

    def to_safe_dict(self) -> dict[str, object]:
        return _record(self, self.schema_version)


@dataclass(frozen=True, slots=True)
class WorkspaceJobResultRevisionLink:
    link_id: str
    result_id: str
    checkpoint_id: str
    workspace_id: str
    result_commit: str
    result_tree: str
    lfs_closure_manifest_digest: str
    linked_by_agent_member_id: str
    linked_at: str
    link_digest: str
    schema_version: str = "workspace_job_result_revision_link@1"

    def __post_init__(self) -> None:
        for name in (
            "link_id",
            "result_id",
            "checkpoint_id",
            "workspace_id",
            "linked_by_agent_member_id",
        ):
            _require_identifier(name, getattr(self, name))
        _require_oid("result_commit", self.result_commit)
        _require_oid("result_tree", self.result_tree)
        _require_digest(
            "lfs_closure_manifest_digest", self.lfs_closure_manifest_digest
        )
        _require_aware_timestamp("linked_at", self.linked_at)
        if self.link_digest != canonical_workspace_job_digest(self.payload):
            raise ValueError("workspace job result revision link digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "link_digest"
        }

    @classmethod
    def create(cls, **values: Any) -> "WorkspaceJobResultRevisionLink":
        return cls(
            **values,
            link_digest=canonical_workspace_job_digest(
                _creation_payload(
                    "workspace_job_result_revision_link@1", values
                )
            ),
        )


__all__ = [
    "ComputeSourceManifest",
    "ComputeSourceManifestEntry",
    "ExternalJobHandle",
    "ExternalJobObservation",
    "SchedulerCredentialOccurrence",
    "SchedulerCredentialOccurrenceState",
    "WorkspaceExternalBackend",
    "WorkspaceJobCancellationIntent",
    "WorkspaceJobCancellationReceipt",
    "WorkspaceJobDispatchIntent",
    "WorkspaceJobExecutionMode",
    "WorkspaceJobObservationState",
    "WorkspaceJobResult",
    "WorkspaceJobResultRevisionLink",
    "WorkspaceJobTargetQualification",
    "WorkspaceRevisionCleanObservation",
    "WorkspaceRevisionExecutionRequest",
    "WorkspaceRevisionScientificBasis",
    "WorkspaceRevisionSourceClass",
    "canonical_workspace_job_digest",
]
