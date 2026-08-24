from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import ClassVar
from typing import Mapping

from .identity import canonical_sha256_digest
from .identity import canonical_string_tuple
from .identity import require_digest
from .identity import require_identifier


WORKFLOW_SELECTION_REQUEST_SCHEMA_VERSION = "workflow_selection_request@1"
RESOLVED_WORKFLOW_SELECTION_SCHEMA_VERSION = "resolved_workflow_selection@1"
WORKFLOW_AUTHORITY_BINDING_SCHEMA_VERSION = "workflow_authority_binding@1"
RUNTIME_SIGNAL_AUTHORITY_LINK_SCHEMA_VERSION = "runtime_signal_authority_link@1"
WORKFLOW_AUTHORITY_SUBSET_REQUEST_SCHEMA_VERSION = "workflow_authority_subset_request@1"
WORKFLOW_AUTHORITY_TRANSITION_REQUEST_SCHEMA_VERSION = "workflow_authority_transition_request@1"


class WorkflowAuthorityStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    CONSUMED = "consumed"

    @property
    def is_terminal(self) -> bool:
        return self is not self.ACTIVE


class WorkflowAuthorityDerivationKind(StrEnum):
    ROOT_MESSAGE = "root_message"
    DELEGATION = "delegation"
    PROTOCOL_DELIVERY = "protocol_delivery"
    APPROVAL_RESOLUTION = "approval_resolution"
    CONTINUATION_DELIVERY = "continuation_delivery"


class WorkflowAuthoritySignalSourceKind(StrEnum):
    ROOT_MESSAGE = "root_message"
    DELEGATION = "delegation"
    PROTOCOL_MESSAGE = "protocol_message"
    APPROVAL_RESOLUTION = "approval_resolution"
    CONTINUATION = "continuation"
    CONTINUATION_DELIVERY = "continuation_delivery"


class WorkflowAuthorityContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        require_identifier(code, field_name="code")
        self.code = code
        self.effect_certainty = "no_effect"
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; mutation_applied=false; fallback_performed=false"
        )


def _positive(value: int, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _optional_identifier(value: str | None, *, field_name: str) -> None:
    if value is not None:
        require_identifier(value, field_name=field_name)


def _closed(payload: Mapping[str, Any], fields: frozenset[str], schema: str) -> None:
    if set(payload) != fields or payload.get("schema_version") != schema:
        raise ValueError(f"{schema} payload has an invalid closed schema")


@dataclass(frozen=True, slots=True)
class WorkflowSelectionRequest:
    SCHEMA_VERSION: ClassVar[str] = WORKFLOW_SELECTION_REQUEST_SCHEMA_VERSION

    request_id: str
    distribution_id: str
    requested_workflow_refs: tuple[str, ...] = ()
    compatibility_skill_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.request_id, field_name="request_id")
        require_identifier(self.distribution_id, field_name="distribution_id")
        refs = canonical_string_tuple(
            self.requested_workflow_refs,
            field_name="requested_workflow_refs",
        )
        skill_keys = canonical_string_tuple(
            self.compatibility_skill_keys,
            field_name="compatibility_skill_keys",
        )
        if refs and skill_keys:
            raise WorkflowAuthorityContractError(
                "workflow_selection_request_ambiguous",
                "canonical workflow_refs and compatibility skill_keys cannot be combined",
            )
        object.__setattr__(self, "requested_workflow_refs", refs)
        object.__setattr__(self, "compatibility_skill_keys", skill_keys)

    @property
    def request_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "request_id": self.request_id,
            "distribution_id": self.distribution_id,
            "requested_workflow_refs": list(self.requested_workflow_refs),
            "compatibility_skill_keys": list(self.compatibility_skill_keys),
        }
        if include_digest:
            payload["request_digest"] = self.request_digest
        return payload


@dataclass(frozen=True, slots=True)
class ResolvedWorkflowSelection:
    SCHEMA_VERSION: ClassVar[str] = RESOLVED_WORKFLOW_SELECTION_SCHEMA_VERSION

    request_id: str
    request_digest: str
    distribution_id: str
    registry_id: str
    registry_snapshot_digest: str
    selected_workflow_refs: tuple[str, ...]
    resolved_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "request_id", "distribution_id", "registry_id", "resolved_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.request_digest, field_name="request_digest")
        require_digest(
            self.registry_snapshot_digest,
            field_name="registry_snapshot_digest",
        )
        object.__setattr__(
            self,
            "selected_workflow_refs",
            canonical_string_tuple(
                self.selected_workflow_refs,
                field_name="selected_workflow_refs",
            ),
        )

    @property
    def selection_digest(self) -> str:
        return canonical_sha256_digest({
            "schema_version": "workflow_selection_binding@1",
            "registry_snapshot_digest": self.registry_snapshot_digest,
            "selected_workflow_refs": list(self.selected_workflow_refs),
        })

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "distribution_id": self.distribution_id,
            "registry_id": self.registry_id,
            "registry_snapshot_digest": self.registry_snapshot_digest,
            "selected_workflow_refs": list(self.selected_workflow_refs),
            "resolved_at": self.resolved_at,
        }
        if include_digest:
            payload["selection_digest"] = self.selection_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResolvedWorkflowSelection":
        value = dict(payload)
        supplied_digest = value.pop("selection_digest", None)
        _closed(value, frozenset({
            "schema_version", "request_id", "request_digest", "distribution_id",
            "registry_id", "registry_snapshot_digest", "selected_workflow_refs",
            "resolved_at",
        }), cls.SCHEMA_VERSION)
        selection = cls(
            request_id=str(value["request_id"]),
            request_digest=str(value["request_digest"]),
            distribution_id=str(value["distribution_id"]),
            registry_id=str(value["registry_id"]),
            registry_snapshot_digest=str(value["registry_snapshot_digest"]),
            selected_workflow_refs=tuple(str(item) for item in value["selected_workflow_refs"]),
            resolved_at=str(value["resolved_at"]),
        )
        if supplied_digest is not None and supplied_digest != selection.selection_digest:
            raise ValueError("resolved workflow selection digest mismatch")
        return selection


@dataclass(frozen=True, slots=True)
class WorkflowAuthorityBinding:
    SCHEMA_VERSION: ClassVar[str] = WORKFLOW_AUTHORITY_BINDING_SCHEMA_VERSION

    authority_id: str
    session_id: str
    project_id: str
    request_lineage_id: str
    source_message_id: str
    source_principal_id: str
    authorized_actor_id: str
    selected_workflow_refs: tuple[str, ...]
    selection_digest: str
    registry_snapshot_digest: str
    derivation_kind: WorkflowAuthorityDerivationKind
    status: WorkflowAuthorityStatus
    epoch: int
    state_version: int
    created_at: str
    updated_at: str
    parent_authority_id: str | None = None
    parent_authority_digest: str | None = None
    task_id: str | None = None
    lane_id: str | None = None
    revoked_at: str | None = None
    expires_at: str | None = None
    consumed_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "authority_id", "session_id", "project_id", "request_lineage_id",
            "source_message_id", "source_principal_id", "authorized_actor_id",
            "created_at", "updated_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("selection_digest", "registry_snapshot_digest"):
            require_digest(getattr(self, field_name), field_name=field_name)
        _positive(self.epoch, field_name="epoch")
        _positive(self.state_version, field_name="state_version")
        selected = canonical_string_tuple(
            self.selected_workflow_refs,
            field_name="selected_workflow_refs",
        )
        object.__setattr__(self, "selected_workflow_refs", selected)
        expected_selection_digest = canonical_sha256_digest({
            "schema_version": "workflow_selection_binding@1",
            "registry_snapshot_digest": self.registry_snapshot_digest,
            "selected_workflow_refs": list(selected),
        })
        if self.selection_digest != expected_selection_digest:
            raise ValueError("workflow authority selection digest mismatch")
        for field_name in (
            "parent_authority_id", "task_id", "lane_id", "revoked_at",
            "expires_at", "consumed_at",
        ):
            _optional_identifier(getattr(self, field_name), field_name=field_name)
        if (self.parent_authority_id is None) != (self.parent_authority_digest is None):
            raise ValueError("parent workflow authority identity must be complete")
        if self.parent_authority_digest is not None:
            require_digest(self.parent_authority_digest, field_name="parent_authority_digest")
        if self.derivation_kind is WorkflowAuthorityDerivationKind.ROOT_MESSAGE:
            if self.parent_authority_id is not None:
                raise ValueError("root workflow authority cannot have a parent")
        elif self.parent_authority_id is None:
            raise ValueError("derived workflow authority requires an exact parent")

        terminal_times = {
            WorkflowAuthorityStatus.REVOKED: self.revoked_at,
            WorkflowAuthorityStatus.EXPIRED: self.expires_at,
            WorkflowAuthorityStatus.CONSUMED: self.consumed_at,
        }
        if self.status is WorkflowAuthorityStatus.ACTIVE:
            if any(value is not None for value in terminal_times.values()):
                raise ValueError("active workflow authority cannot carry terminal timestamps")
        else:
            expected = terminal_times[self.status]
            if expected is None:
                raise ValueError("terminal workflow authority requires its matching timestamp")
            if sum(value is not None for value in terminal_times.values()) != 1:
                raise ValueError("workflow authority terminal timestamps are mutually exclusive")

    @property
    def scope_digest(self) -> str:
        return canonical_sha256_digest({
            "schema_version": "workflow_authority_scope@1",
            "session_id": self.session_id,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
        })

    @property
    def binding_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "authority_id": self.authority_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "request_lineage_id": self.request_lineage_id,
            "source_message_id": self.source_message_id,
            "source_principal_id": self.source_principal_id,
            "authorized_actor_id": self.authorized_actor_id,
            "selected_workflow_refs": list(self.selected_workflow_refs),
            "selection_digest": self.selection_digest,
            "registry_snapshot_digest": self.registry_snapshot_digest,
            "parent_authority_id": self.parent_authority_id,
            "parent_authority_digest": self.parent_authority_digest,
            "derivation_kind": self.derivation_kind.value,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "status": self.status.value,
            "epoch": self.epoch,
            "state_version": self.state_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revoked_at": self.revoked_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
        }
        if include_digest:
            payload["scope_digest"] = self.scope_digest
            payload["binding_digest"] = self.binding_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowAuthorityBinding":
        value = dict(payload)
        scope_digest = value.pop("scope_digest", None)
        binding_digest = value.pop("binding_digest", None)
        _closed(value, frozenset({
            "schema_version", "authority_id", "session_id", "project_id",
            "request_lineage_id", "source_message_id", "source_principal_id",
            "authorized_actor_id", "selected_workflow_refs", "selection_digest",
            "registry_snapshot_digest", "parent_authority_id",
            "parent_authority_digest", "derivation_kind", "task_id", "lane_id",
            "status", "epoch", "state_version", "created_at", "updated_at",
            "revoked_at", "expires_at", "consumed_at",
        }), cls.SCHEMA_VERSION)
        binding = cls(
            authority_id=str(value["authority_id"]), session_id=str(value["session_id"]),
            project_id=str(value["project_id"]), request_lineage_id=str(value["request_lineage_id"]),
            source_message_id=str(value["source_message_id"]), source_principal_id=str(value["source_principal_id"]),
            authorized_actor_id=str(value["authorized_actor_id"]),
            selected_workflow_refs=tuple(str(item) for item in value["selected_workflow_refs"]),
            selection_digest=str(value["selection_digest"]),
            registry_snapshot_digest=str(value["registry_snapshot_digest"]),
            parent_authority_id=None if value["parent_authority_id"] is None else str(value["parent_authority_id"]),
            parent_authority_digest=None if value["parent_authority_digest"] is None else str(value["parent_authority_digest"]),
            derivation_kind=WorkflowAuthorityDerivationKind(str(value["derivation_kind"])),
            task_id=None if value["task_id"] is None else str(value["task_id"]),
            lane_id=None if value["lane_id"] is None else str(value["lane_id"]),
            status=WorkflowAuthorityStatus(str(value["status"])), epoch=int(value["epoch"]),
            state_version=int(value["state_version"]), created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            revoked_at=None if value["revoked_at"] is None else str(value["revoked_at"]),
            expires_at=None if value["expires_at"] is None else str(value["expires_at"]),
            consumed_at=None if value["consumed_at"] is None else str(value["consumed_at"]),
        )
        if scope_digest is not None and scope_digest != binding.scope_digest:
            raise ValueError("workflow authority scope digest mismatch")
        if binding_digest is not None and binding_digest != binding.binding_digest:
            raise ValueError("workflow authority binding digest mismatch")
        return binding


@dataclass(frozen=True, slots=True)
class RuntimeSignalAuthorityLink:
    SCHEMA_VERSION: ClassVar[str] = RUNTIME_SIGNAL_AUTHORITY_LINK_SCHEMA_VERSION

    signal_id: str
    session_id: str
    authority_id: str
    authority_epoch: int
    authority_binding_digest: str
    causation_ref: str
    source_kind: WorkflowAuthoritySignalSourceKind
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "signal_id", "session_id", "authority_id", "causation_ref", "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _positive(self.authority_epoch, field_name="authority_epoch")
        require_digest(self.authority_binding_digest, field_name="authority_binding_digest")

    @property
    def link_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "signal_id": self.signal_id,
            "session_id": self.session_id,
            "authority_id": self.authority_id,
            "authority_epoch": self.authority_epoch,
            "authority_binding_digest": self.authority_binding_digest,
            "causation_ref": self.causation_ref,
            "source_kind": self.source_kind.value,
            "created_at": self.created_at,
        }
        if include_digest:
            payload["link_digest"] = self.link_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeSignalAuthorityLink":
        value = dict(payload)
        supplied_digest = value.pop("link_digest", None)
        _closed(value, frozenset({
            "schema_version", "signal_id", "session_id", "authority_id",
            "authority_epoch", "authority_binding_digest", "causation_ref",
            "source_kind", "created_at",
        }), cls.SCHEMA_VERSION)
        link = cls(
            signal_id=str(value["signal_id"]), session_id=str(value["session_id"]),
            authority_id=str(value["authority_id"]), authority_epoch=int(value["authority_epoch"]),
            authority_binding_digest=str(value["authority_binding_digest"]),
            causation_ref=str(value["causation_ref"]),
            source_kind=WorkflowAuthoritySignalSourceKind(str(value["source_kind"])),
            created_at=str(value["created_at"]),
        )
        if supplied_digest is not None and supplied_digest != link.link_digest:
            raise ValueError("runtime signal authority link digest mismatch")
        return link


@dataclass(frozen=True, slots=True)
class WorkflowAuthoritySubsetRequest:
    SCHEMA_VERSION: ClassVar[str] = WORKFLOW_AUTHORITY_SUBSET_REQUEST_SCHEMA_VERSION

    request_id: str
    parent_authority_id: str
    parent_binding_digest: str
    parent_epoch: int
    authorized_actor_id: str
    selected_workflow_refs: tuple[str, ...]
    task_id: str | None
    lane_id: str | None
    derivation_kind: WorkflowAuthorityDerivationKind
    causation_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "request_id", "parent_authority_id", "authorized_actor_id", "causation_ref",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.parent_binding_digest, field_name="parent_binding_digest")
        _positive(self.parent_epoch, field_name="parent_epoch")
        object.__setattr__(self, "selected_workflow_refs", canonical_string_tuple(
            self.selected_workflow_refs,
            field_name="selected_workflow_refs",
        ))
        _optional_identifier(self.task_id, field_name="task_id")
        _optional_identifier(self.lane_id, field_name="lane_id")
        if self.derivation_kind is WorkflowAuthorityDerivationKind.ROOT_MESSAGE:
            raise ValueError("subset derivation cannot be a root message")

    @property
    def request_digest(self) -> str:
        return canonical_sha256_digest({
            "schema_version": self.SCHEMA_VERSION,
            "request_id": self.request_id,
            "parent_authority_id": self.parent_authority_id,
            "parent_binding_digest": self.parent_binding_digest,
            "parent_epoch": self.parent_epoch,
            "authorized_actor_id": self.authorized_actor_id,
            "selected_workflow_refs": list(self.selected_workflow_refs),
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "derivation_kind": self.derivation_kind.value,
            "causation_ref": self.causation_ref,
        })


@dataclass(frozen=True, slots=True)
class WorkflowAuthorityTransitionRequest:
    SCHEMA_VERSION: ClassVar[str] = WORKFLOW_AUTHORITY_TRANSITION_REQUEST_SCHEMA_VERSION

    request_id: str
    authority_id: str
    expected_binding_digest: str
    expected_epoch: int
    target_status: WorkflowAuthorityStatus
    actor_id: str
    reason_code: str
    transitioned_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "request_id", "authority_id", "actor_id", "reason_code", "transitioned_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.expected_binding_digest, field_name="expected_binding_digest")
        _positive(self.expected_epoch, field_name="expected_epoch")
        if self.target_status is WorkflowAuthorityStatus.ACTIVE:
            raise ValueError("workflow authority cannot transition back to active")

    @property
    def request_digest(self) -> str:
        return canonical_sha256_digest({
            "schema_version": self.SCHEMA_VERSION,
            "request_id": self.request_id,
            "authority_id": self.authority_id,
            "expected_binding_digest": self.expected_binding_digest,
            "expected_epoch": self.expected_epoch,
            "target_status": self.target_status.value,
            "actor_id": self.actor_id,
            "reason_code": self.reason_code,
            "transitioned_at": self.transitioned_at,
        })


def require_workflow_authority_subset(
    parent: WorkflowAuthorityBinding,
    child: WorkflowAuthorityBinding | WorkflowAuthoritySubsetRequest,
) -> None:
    if parent.status is not WorkflowAuthorityStatus.ACTIVE:
        raise WorkflowAuthorityContractError(
            "workflow_authority_not_active",
            "workflow authority subset derivation requires an active parent",
        )
    if isinstance(child, WorkflowAuthorityBinding):
        refs = child.selected_workflow_refs
        task_id = child.task_id
        lane_id = child.lane_id
        parent_id = child.parent_authority_id
        parent_digest = child.parent_authority_digest
    else:
        refs = child.selected_workflow_refs
        task_id = child.task_id
        lane_id = child.lane_id
        parent_id = child.parent_authority_id
        parent_digest = child.parent_binding_digest
        if child.parent_epoch != parent.epoch:
            raise WorkflowAuthorityContractError(
                "workflow_authority_epoch_stale",
                "workflow authority subset request carries a stale parent epoch",
            )
    if parent_id != parent.authority_id or parent_digest != parent.binding_digest:
        raise WorkflowAuthorityContractError(
            "workflow_authority_parent_mismatch",
            "workflow authority subset request does not bind the exact parent",
        )
    if not set(refs).issubset(parent.selected_workflow_refs):
        raise WorkflowAuthorityContractError(
            "workflow_authority_subset_violation",
            "derived workflow selection is wider than its parent",
        )
    if parent.task_id is not None and task_id != parent.task_id:
        raise WorkflowAuthorityContractError(
            "workflow_authority_subset_violation",
            "derived Task scope is not a subset of its parent",
        )
    if parent.lane_id is not None and lane_id != parent.lane_id:
        raise WorkflowAuthorityContractError(
            "workflow_authority_subset_violation",
            "derived lane scope is not a subset of its parent",
        )


__all__ = [
    "RESOLVED_WORKFLOW_SELECTION_SCHEMA_VERSION",
    "RUNTIME_SIGNAL_AUTHORITY_LINK_SCHEMA_VERSION",
    "WORKFLOW_AUTHORITY_BINDING_SCHEMA_VERSION",
    "WORKFLOW_AUTHORITY_SUBSET_REQUEST_SCHEMA_VERSION",
    "WORKFLOW_AUTHORITY_TRANSITION_REQUEST_SCHEMA_VERSION",
    "WORKFLOW_SELECTION_REQUEST_SCHEMA_VERSION",
    "ResolvedWorkflowSelection",
    "RuntimeSignalAuthorityLink",
    "WorkflowAuthorityBinding",
    "WorkflowAuthorityContractError",
    "WorkflowAuthorityDerivationKind",
    "WorkflowAuthoritySignalSourceKind",
    "WorkflowAuthorityStatus",
    "WorkflowAuthoritySubsetRequest",
    "WorkflowAuthorityTransitionRequest",
    "WorkflowSelectionRequest",
    "require_workflow_authority_subset",
]
