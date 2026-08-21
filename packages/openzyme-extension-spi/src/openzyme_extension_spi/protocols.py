from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import EvidenceRef
from openzyme_contracts import ToolSpec
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible

from .application import KernelEntitySnapshot
from .application import KernelCommandContext
from .application import KernelQueryContext
from .application import TaskEvidenceValidation
from .contributions import CapabilityProvision
from .contributions import CapabilityRequirement
from .contributions import QualificationSpec
from .contributions import RouteContribution
from .manifests import ComponentManifest
from .transactions import ExtensionTransactionParticipant


class ExtensionManifestProvider(Protocol):
    """Pure manifest locator target; construction must perform no external I/O."""

    def manifest(self) -> ComponentManifest: ...


class ToolRuntimeContribution(Protocol):
    """Runtime for one declared tool; dependencies are injected as narrow services."""

    @property
    def owner_plugin_id(self) -> str: ...

    @property
    def runtime_id(self) -> str: ...

    @property
    def contract(self) -> ToolSpec: ...

    def invoke(self, invocation: ToolInvocation) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class ToolDispatchBinding:
    """Kernel-admitted facts passed to a route-bound Plugin runtime.

    This is deliberately an SPI value rather than a repository handle.  A Plugin
    receives the exact authority, workspace and capability-route proof that the
    Kernel revalidated immediately before dispatch, but it cannot inspect or
    mutate Kernel storage through this object.
    """

    tool_name: str
    tool_contract_digest: str
    affordance_snapshot_digest: str
    capability_binding_digest: str
    extension_bundle_digest: str
    authority_lease_id: str
    authority_lease_digest: str
    authority_generation: int
    authority_fence: int
    workspace_generation: int
    route_id: str | None
    route_digest: str | None
    provider_component_id: str | None
    driver_id: str | None
    target_id: str | None
    inventory_generation: int | None
    inventory_digest: str | None
    qualification_digest: str | None
    capability_proof_digest: str | None

    def __post_init__(self) -> None:
        require_identifier(self.tool_name, field_name="tool_name")
        for field_name in (
            "tool_contract_digest",
            "affordance_snapshot_digest",
            "capability_binding_digest",
            "extension_bundle_digest",
            "authority_lease_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        require_identifier(self.authority_lease_id, field_name="authority_lease_id")
        for field_name in (
            "authority_generation",
            "authority_fence",
            "workspace_generation",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        route_values = (
            self.route_id,
            self.route_digest,
            self.provider_component_id,
            self.driver_id,
            self.target_id,
            self.inventory_generation,
            self.inventory_digest,
            self.qualification_digest,
            self.capability_proof_digest,
        )
        if all(value is None for value in route_values):
            return
        if any(value is None for value in route_values):
            raise ValueError("route-bound dispatch facts must be supplied together")
        for field_name in (
            "route_id",
            "provider_component_id",
            "driver_id",
            "target_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "route_digest",
            "inventory_digest",
            "qualification_digest",
            "capability_proof_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if (
            not isinstance(self.inventory_generation, int)
            or isinstance(self.inventory_generation, bool)
            or self.inventory_generation < 1
        ):
            raise ValueError("inventory_generation must be a positive integer")


class AdmittedToolRuntimeContribution(ToolRuntimeContribution, Protocol):
    """Optional exact-admission surface for route-bound formal tools."""

    def invoke_admitted(
        self,
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
    ) -> ToolResult: ...


class CapabilityProvider(Protocol):
    def provided_capabilities(self) -> tuple[CapabilityProvision, ...]: ...


class CapabilityRequirementProvider(Protocol):
    def capability_requirements(self) -> tuple[CapabilityRequirement, ...]: ...


class QualificationSpecProvider(Protocol):
    def qualification_specs(self) -> tuple[QualificationSpec, ...]: ...


class RouteProvider(Protocol):
    def routes(self) -> tuple[RouteContribution, ...]: ...


@dataclass(frozen=True, slots=True)
class CapabilityRouteInvocation:
    context: KernelCommandContext
    route_id: str
    capability_id: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.route_id, field_name="route_id")
        require_identifier(self.capability_id, field_name="capability_id")
        payload = freeze_json(self.payload, field_name="payload")
        if not isinstance(payload, Mapping):
            raise ValueError("route payload must be a JSON object")
        object.__setattr__(self, "payload", payload)


class CapabilityRouteRuntimeContribution(Protocol):
    """One declared Plugin route; a Driver may only implement its bound route."""

    @property
    def route_id(self) -> str: ...

    @property
    def owner_plugin_id(self) -> str: ...

    @property
    def driver_id(self) -> str | None: ...

    def invoke(self, invocation: CapabilityRouteInvocation) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class HttpRouteInvocation:
    context: KernelQueryContext
    route_id: str
    method: str
    path: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.route_id, field_name="route_id")
        require_identifier(self.method, field_name="method")
        if not isinstance(self.path, str) or not self.path.startswith("/"):
            raise ValueError("path must be an absolute request path")
        payload = freeze_json(self.payload, field_name="payload")
        if not isinstance(payload, Mapping):
            raise ValueError("HTTP payload must be a JSON object")
        object.__setattr__(self, "payload", payload)


class HttpRouteRuntimeContribution(Protocol):
    @property
    def route_id(self) -> str: ...

    @property
    def owner_plugin_id(self) -> str: ...

    @property
    def method(self) -> str: ...

    @property
    def path(self) -> str: ...

    @property
    def contract_digest(self) -> str: ...

    def invoke(self, invocation: HttpRouteInvocation) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class ProjectionRequest:
    context: KernelQueryContext
    section_id: str
    max_items: int
    max_bytes: int
    cursor: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.section_id, field_name="section_id")
        if not 1 <= self.max_items <= 1_000:
            raise ValueError("max_items must be between 1 and 1000")
        if not 1 <= self.max_bytes <= 1_048_576:
            raise ValueError("max_bytes must be between 1 and 1048576")
        if self.cursor is not None:
            require_identifier(self.cursor, field_name="cursor")


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    section_id: str
    section_contract_digest: str
    payload: Mapping[str, JsonValue]
    next_cursor: str | None
    projection_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.section_id, field_name="section_id")
        require_digest(
            self.section_contract_digest,
            field_name="section_contract_digest",
        )
        if self.next_cursor is not None:
            require_identifier(self.next_cursor, field_name="next_cursor")
        payload = freeze_json(self.payload, field_name="payload")
        if not isinstance(payload, Mapping):
            raise ValueError("projection payload must be a JSON object")
        object.__setattr__(self, "payload", payload)
        require_digest(self.projection_digest, field_name="projection_digest")
        if self.projection_digest != self.observed_digest:
            raise ValueError("projection digest does not match the bounded payload")

    @property
    def observed_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "section_id": self.section_id,
                "section_contract_digest": self.section_contract_digest,
                "payload": json_compatible(self.payload),
                "next_cursor": self.next_cursor,
            }
        )


class ProjectionContributor(Protocol):
    @property
    def section_id(self) -> str: ...

    @property
    def section_contract_digest(self) -> str: ...

    def project(self, request: ProjectionRequest) -> ProjectionResult: ...


@dataclass(frozen=True, slots=True)
class WorkerClaimRequest:
    worker_id: str
    owner_plugin_id: str
    activation_epoch: int
    max_items: int
    lease_seconds: int

    def __post_init__(self) -> None:
        require_identifier(self.worker_id, field_name="worker_id")
        require_identifier(self.owner_plugin_id, field_name="owner_plugin_id")
        if self.activation_epoch < 1:
            raise ValueError("activation_epoch must be positive")
        if not 1 <= self.max_items <= 100:
            raise ValueError("max_items must be between 1 and 100")
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")


@dataclass(frozen=True, slots=True)
class WorkerClaim:
    claim_id: str
    work_item_id: str
    source_version: int
    fence: int
    bounded_payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.claim_id, field_name="claim_id")
        require_identifier(self.work_item_id, field_name="work_item_id")
        if self.source_version < 1 or self.fence < 1:
            raise ValueError("worker source_version and fence must be positive")
        payload = freeze_json(self.bounded_payload, field_name="bounded_payload")
        if not isinstance(payload, Mapping):
            raise ValueError("bounded_payload must be a JSON object")
        object.__setattr__(self, "bounded_payload", payload)


class WorkerContributor(Protocol):
    @property
    def worker_id(self) -> str: ...

    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]: ...

    def run(self, claim: WorkerClaim) -> ToolResult: ...


class TaskEvidenceValidator(Protocol):
    @property
    def validator_id(self) -> str: ...

    def validate(
        self,
        context: KernelQueryContext,
        task: KernelEntitySnapshot,
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> TaskEvidenceValidation: ...


@dataclass(frozen=True, slots=True)
class ExtensionSchemaDescriptor:
    schema_id: str
    owner_plugin_id: str
    state_namespace: str
    schema_digest: str

    def __post_init__(self) -> None:
        for field_name in ("schema_id", "owner_plugin_id", "state_namespace"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.schema_digest, field_name="schema_digest")


@dataclass(frozen=True, slots=True)
class ExtensionMigrationDescriptor:
    migration_id: str
    owner_plugin_id: str
    state_namespace: str
    predecessor_digest: str | None
    migration_digest: str

    def __post_init__(self) -> None:
        for field_name in ("migration_id", "owner_plugin_id", "state_namespace"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.predecessor_digest is not None:
            require_digest(
                self.predecessor_digest,
                field_name="predecessor_digest",
            )
        require_digest(self.migration_digest, field_name="migration_digest")


class ExtensionSchemaContributor(Protocol):
    def schemas(self) -> tuple[ExtensionSchemaDescriptor, ...]: ...


class ExtensionMigrationContributor(Protocol):
    def migrations(self) -> tuple[ExtensionMigrationDescriptor, ...]: ...


class ExtensionTransactionParticipantProvider(Protocol):
    def transaction_participants(
        self,
    ) -> tuple[ExtensionTransactionParticipant, ...]: ...


__all__ = [
    "AdmittedToolRuntimeContribution",
    "CapabilityRouteInvocation",
    "CapabilityRouteRuntimeContribution",
    "CapabilityProvider",
    "CapabilityRequirementProvider",
    "ExtensionManifestProvider",
    "ExtensionMigrationContributor",
    "ExtensionMigrationDescriptor",
    "ExtensionSchemaContributor",
    "ExtensionSchemaDescriptor",
    "ExtensionTransactionParticipantProvider",
    "HttpRouteInvocation",
    "HttpRouteRuntimeContribution",
    "ProjectionContributor",
    "ProjectionRequest",
    "ProjectionResult",
    "QualificationSpecProvider",
    "RouteProvider",
    "TaskEvidenceValidator",
    "ToolRuntimeContribution",
    "ToolDispatchBinding",
    "WorkerClaim",
    "WorkerClaimRequest",
    "WorkerContributor",
]
