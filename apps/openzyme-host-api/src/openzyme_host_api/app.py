from __future__ import annotations

import asyncio
from decimal import Decimal
from decimal import InvalidOperation
import hashlib
import json
from contextlib import asynccontextmanager
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from typing import AsyncIterator
from typing import Callable
from typing import Iterator
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Header
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from openzyme_runtime import MissingLlmConfigurationError
from openzyme_runtime import LimiterRegistry
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import RuntimeDrainContract
from openzyme_runtime import S12_ROUTE_POLICIES
from openzyme_runtime import get_llm_debug_recorder
from openzyme_runtime import llm_debug_context
from openzyme_runtime import safe_public_machine_identifier
from openzyme_runtime import sanitize_public_diagnostic_payload
from openzyme_runtime import sanitize_public_diagnostic_text

from .background_runtime import RuntimeSignalNotifier
from .background_runtime import V3BackgroundRuntimeService
from .background_runtime import V3DurableWorkCoordinator
from .background_runtime import V3DurableWorkSupervisor
from .aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)
from .aox_bundle_finalizer import finalize_aox_deliverable_bundle
from .durable_routes import build_host_hpc_route_adapters
from .durable_routes import build_host_provider_route_adapters
from .runtime_commands import HostRuntimeCommandExecutor
from .sandbox_host_gateway import ExecutionEngineSandboxHostGateway
from .sandbox_host_gateway import HostSandboxCallContextFactory
from .tracing import host_request_trace_context
from .security import HostAuthenticationError
from .security import HostPrincipal
from .security import HostSecurityPolicy
from .v3_service import V3EventStore
from .v3_service import V3HostApiService

from openzyme_core import CoreRepositories
from openzyme_core import ContinuationDeliveryWorker
from openzyme_core import ControlledOperationExecutionWorker
from openzyme_core import ControlledOperationRouteAdapter
from openzyme_core import CommandIdempotencyConflictError
from openzyme_core import CommandReceiptRecord
from openzyme_core import EngineRegistry
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import SessionAccessRecord
from openzyme_core import RuntimeCommandWorker
from openzyme_core import SandboxHostBinding
from openzyme_core import SandboxHostCallContext
from openzyme_core import SandboxProcessHostAuthority
from openzyme_core import SessionTurnHostAuthority
from openzyme_core import ScientificAttemptError
from openzyme_core import LiveProcessRegistry
from openzyme_core import MutationWriterTurnFactory
from openzyme_core import MutationScopeService
from openzyme_core import current_mutation_write_authority
from openzyme_core import project_runtime_command
from openzyme_core import recover_unattached_continuations
from openzyme_engines import DeepResearchEngine
from openzyme_engines import ExecutionEngine
from openzyme_engines import ExecutionOutcome as V3ExecutionOutcome
from openzyme_engines import ExecutionStatusSnapshot as V3ExecutionStatusSnapshot
from openzyme_engines import NativeDeepResearchRunner
from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_engines import ProviderHttpBioDatabaseAdapter
from openzyme_engines import build_engine_registry
from openzyme_engines.execution import ExecutionArtifactRef as V3ExecutionArtifactRef
from openzyme_domain import RunStatus
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import MutationWriterKind
from openzyme_domain import SessionRuntimeLease
from openzyme_domain.control_plane import utc_now_iso


class CreateV3SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=100_000)
    title: str | None = None
    session_id: str | None = None


class PostV3MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1_000_000)
    task_id: str | None = None
    lane_id: str | None = None
    skill_keys: list[str] = Field(default_factory=list, max_length=64)


class DrainV3RuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_signals: int = Field(default=3, ge=1, le=100)
    max_steps_per_agent: int = Field(default=8, ge=1, le=100)
    auto_enqueue_ready_tasks: bool = False


class ResolveV3ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


class CreateV3TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=10_000)
    description: str = Field(default="", max_length=100_000)
    task_id: str | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    kind: str = Field(default="general", min_length=1, max_length=100)
    status: Literal["todo", "in_progress"] = "todo"
    lane_id: str | None = None
    blocked_by: list[str] = Field(default_factory=list, max_length=1_000)


class UpdateV3TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, min_length=1, max_length=10_000)
    description: str | None = Field(default=None, max_length=100_000)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    kind: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["todo", "in_progress"] | None = None
    lane_id: str | None = None
    blocked_by: list[str] | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def require_mutation(self) -> "UpdateV3TaskRequest":
        if not self.model_fields_set:
            raise ValueError("task update must include at least one mutable field")
        return self


class CreateV3LaneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    cwd: str = Field(default=".", min_length=1, max_length=4_096)
    lane_id: str | None = None
    branch_name: str | None = Field(default=None, max_length=500)


class ClaimV3LaneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GrantScientificAttemptAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=200)
    campaign_id: str = Field(min_length=1, max_length=200)
    workflow_id: str = Field(min_length=1, max_length=200)
    root_ref: str = Field(min_length=1, max_length=500)
    grantor_kind: Literal["user", "operator"] = "user"
    allowed_scopes: list[Literal["formal", "probe", "fault"]] = Field(
        min_length=1,
        max_length=3,
    )
    allowed_effect_classes: list[str] = Field(min_length=1, max_length=64)
    allowed_providers: list[str] = Field(default_factory=list, max_length=64)
    allowed_hpc_targets: list[str] = Field(default_factory=list, max_length=64)
    max_attempts: int = Field(strict=True, ge=1, le=10_000)
    max_micu: int = Field(strict=True, ge=0)
    max_cost_microunits: int = Field(strict=True, ge=0)
    max_wall_time_seconds: int = Field(strict=True, ge=0)
    expires_at: str = Field(min_length=1, max_length=100)
    policy_digest: str | None = Field(default=None, max_length=200)


ScientificCommandName = Literal[
    "attempt.create",
    "scientific.selection.begin",
    "scientific.operation.disposition",
    "scientific.operation.adopt",
    "scientific.artifact.materialize",
    "scientific.selection.seal",
    "scientific.attempt.close",
]


class ScientificAttemptCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: ScientificCommandName
    arguments: dict[str, Any]


class FinalizeScientificAttemptAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admission_request_id: str = Field(min_length=1, max_length=300)


class FinalizeScientificAttemptClosureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closure_request_id: str = Field(min_length=1, max_length=300)


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    hint: str | None = None
    details: Any | None = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorDetail


class V3EventDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    session_id: str
    event_type: str
    schema_version: Literal["openzyme.v3.event.v1"]
    visibility: Literal["public"]
    created_at: str
    payload: dict[str, Any]
    cursor: int | None = None
    actor_ref: str | None = None
    command_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


class V3SessionCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    workspace: dict[str, Any]
    events: list[V3EventDto]


class V3SessionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    project_id: str
    title: str
    objective: str
    status: str
    created_at: str
    updated_at: str
    latest_message_preview: str
    pending_approval_count: int


class V3SessionWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: dict[str, Any]
    workspace: dict[str, Any]


class V3PendingApprovalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    pending_approvals: list[dict[str, Any]]


class V3CommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    status: str
    outputs: list[str]
    workspace: dict[str, Any]
    events: list[V3EventDto]


class V3RuntimeCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runtime_command_status@1"] = "runtime_command_status@1"
    session_id: str
    command_id: str
    command_type: Literal["runtime.drain"]
    status: Literal[
        "accepted",
        "claimed",
        "completed",
        "failed",
        "locked",
        "cancelled",
    ]
    status_url: str
    accepted_at: str
    started_at: str | None = None
    completed_at: str | None = None
    bounded_outcome_summary: dict[str, Any] | None = None
    error_code: str | None = None
    safe_error_summary: str | None = None
    safe_retry_hint: str | None = None


class V3TaskMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: dict[str, Any]
    workspace: dict[str, Any]
    events: list[V3EventDto]


class V3LaneMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane: dict[str, Any]
    workspace: dict[str, Any]
    events: list[V3EventDto]


RuntimeHealthStatus = Literal[
    "ready", "degraded", "disabled", "unavailable", "fixture_non_cutover"
]


class RuntimeComponentHealth(BaseModel):
    status: RuntimeHealthStatus
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeHealthResponse(BaseModel):
    schema_version: Literal["v3.runtime_health.v1"] = "v3.runtime_health.v1"
    status: Literal["ready", "degraded"]
    deployment_profile: Literal["local-dev", "shared"]
    storage_profile: Literal["single_process_sqlite"] = "single_process_sqlite"
    observed_at: str
    components: dict[str, RuntimeComponentHealth]


def _configured_component_status(
    component: Any,
    *,
    ready_type_names: frozenset[str],
    unavailable_type_names: frozenset[str] = frozenset(),
) -> RuntimeHealthStatus:
    if component is None:
        return "unavailable"
    type_name = type(component).__name__
    normalized = type_name.lower()
    if type_name in unavailable_type_names:
        return "unavailable"
    if any(
        marker in normalized for marker in ("deterministic", "fixture", "simulation")
    ):
        return "fixture_non_cutover"
    if type_name in ready_type_names:
        return "ready"
    return "degraded"


@dataclass(slots=True)
class V3ExecutionRunnerAdapter:
    execution_adapter: Any
    limiter_registry: LimiterRegistry | None = None
    _outcomes_by_run_id: dict[str, V3ExecutionOutcome] = field(default_factory=dict)

    def submit_execution(
        self, session_id: str, payload: dict[str, Any]
    ) -> V3ExecutionOutcome:
        outcome = self._convert_outcome(
            self._run_limited(
                lambda: self.execution_adapter.submit_execution(session_id, payload)
            )
        )
        self._outcomes_by_run_id[outcome.run_id] = outcome
        return outcome

    def reserve_execution(self, identity: dict[str, Any]) -> dict[str, str]:
        callback = getattr(self.execution_adapter, "reserve_execution", None)
        if not callable(callback):
            raise RuntimeError(
                "execution adapter does not support durable run reservation"
            )
        result = self._run_limited(lambda: callback(dict(identity)))
        if not isinstance(result, dict):
            raise ValueError("execution reservation returned a non-object result")
        return {str(key): str(value) for key, value in result.items()}

    def submit_reserved_execution(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        run_id: str,
    ) -> V3ExecutionOutcome:
        callback = getattr(self.execution_adapter, "submit_reserved_execution", None)
        if not callable(callback):
            raise RuntimeError(
                "execution adapter does not support durable reserved dispatch"
            )
        outcome = self._convert_outcome(
            self._run_limited(
                lambda: callback(
                    session_id,
                    payload,
                    run_id=run_id,
                )
            )
        )
        if outcome.run_id != run_id:
            raise ValueError("reserved execution outcome identity drift")
        self._outcomes_by_run_id[outcome.run_id] = outcome
        return outcome

    def inspect_reserved_execution(self, *, run_id: str) -> Any:
        callback = getattr(self.execution_adapter, "inspect_reserved_execution", None)
        if not callable(callback):
            raise RuntimeError(
                "execution adapter does not support durable run inspection"
            )
        observation = self._run_limited(lambda: callback(run_id=run_id))
        if str(getattr(observation, "run_id", "")) != run_id:
            raise ValueError("reserved execution observation identity drift")
        return observation

    def recover_reserved_execution_outcome(
        self,
        *,
        run_id: str,
    ) -> V3ExecutionOutcome:
        callback = getattr(
            self.execution_adapter,
            "recover_reserved_execution_outcome",
            None,
        )
        if not callable(callback):
            raise RuntimeError(
                "execution adapter does not support durable outcome recovery"
            )
        outcome = self._convert_outcome(
            self._run_limited(lambda: callback(run_id=run_id))
        )
        if outcome.run_id != run_id:
            raise ValueError("recovered execution outcome identity drift")
        self._outcomes_by_run_id[outcome.run_id] = outcome
        return outcome

    def get_execution_status(
        self,
        *,
        run_id: str,
    ) -> V3ExecutionStatusSnapshot:
        if hasattr(self.execution_adapter, "get_execution_status"):
            snapshot = self._run_limited(
                lambda: self.execution_adapter.get_execution_status(
                    run_id=run_id,
                )
            )
            return V3ExecutionStatusSnapshot(
                run_id=str(snapshot.run_id),
                status=snapshot.status,
                raw_result=dict(snapshot.raw_result),
                exit_code=snapshot.exit_code,
            )
        outcome = self._outcomes_by_run_id.get(run_id)
        if outcome is None:
            return V3ExecutionStatusSnapshot(
                run_id=run_id,
                status=RunStatus.FAILED,
                raw_result={
                    "error": "execution adapter does not expose status polling"
                },
            )
        return V3ExecutionStatusSnapshot(
            run_id=outcome.run_id,
            status=outcome.status,
            raw_result=outcome.raw_result,
            exit_code=outcome.exit_code,
        )

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
    ) -> V3ExecutionOutcome:
        if hasattr(self.execution_adapter, "fetch_execution_artifacts"):
            outcome = self._convert_outcome(
                self._run_limited(
                    lambda: self.execution_adapter.fetch_execution_artifacts(
                        run_id=run_id,
                    )
                )
            )
            self._outcomes_by_run_id[outcome.run_id] = outcome
            return outcome
        outcome = self._outcomes_by_run_id.get(run_id)
        if outcome is None:
            return V3ExecutionOutcome(
                run_id=run_id,
                status=RunStatus.FAILED,
                execution_mode="unknown",
                remote_run_dir=f"opaque://{run_id}",
                raw_result={
                    "error": "execution adapter does not expose artifact fetch"
                },
                artifacts=(),
            )
        return outcome

    def cancel_execution(
        self,
        *,
        run_id: str,
    ) -> V3ExecutionOutcome:
        if hasattr(self.execution_adapter, "cancel_execution"):
            return self._convert_outcome(
                self._run_limited(
                    lambda: self.execution_adapter.cancel_execution(
                        run_id=run_id,
                    )
                )
            )
        return V3ExecutionOutcome(
            run_id=run_id,
            status=RunStatus.FAILED,
            execution_mode="unknown",
            remote_run_dir=f"opaque://{run_id}",
            raw_result={
                "status": "unsupported",
                "error_code": "cancel_execution_unsupported",
                "error": "execution adapter does not expose cancel",
            },
            artifacts=(),
        )

    def _convert_outcome(self, outcome: Any) -> V3ExecutionOutcome:
        artifacts = tuple(
            V3ExecutionArtifactRef(
                storage_uri=str(artifact.storage_uri),
                relative_path=str(artifact.relative_path),
                kind=artifact.kind,
            )
            for artifact in getattr(outcome, "artifacts", ())
        )
        raw_result = dict(outcome.raw_result)
        # Runner artifact values are Host-local catalog/storage references.
        # They travel through the typed artifact channel below and must not be
        # duplicated into the agent-facing raw_result document.
        for private_key in (
            "artifacts",
            "job_id",
            "remote_run_dir",
            "stdout",
            "stderr",
            "logs",
        ):
            raw_result.pop(private_key, None)
        return V3ExecutionOutcome(
            run_id=str(outcome.run_id),
            status=outcome.status,
            execution_mode=str(outcome.execution_mode),
            remote_run_dir=f"opaque://{outcome.run_id}",
            raw_result=raw_result,
            artifacts=artifacts,
            exit_code=getattr(outcome, "exit_code", None),
        )

    def _run_limited(self, operation: Callable[[], Any]) -> Any:
        if self.limiter_registry is None:
            return operation()
        return self.limiter_registry.sync_limiter("execution_provider").run(operation)


@dataclass(slots=True)
class HostApiDependencies:
    foundation: RuntimeFoundation
    security_policy: HostSecurityPolicy | None = None
    v3_repository_provider: SQLiteRepositoryProvider | None = None
    # Explicit compatibility seam for thread-aware tests that still need one
    # process-local fixture connection. Production composition must use the provider.
    v3_legacy_repositories_for_tests: CoreRepositories | None = None
    v3_signal_notifier: RuntimeSignalNotifier = field(
        default_factory=RuntimeSignalNotifier
    )
    v3_durable_work_notifier: RuntimeSignalNotifier = field(
        default_factory=RuntimeSignalNotifier
    )
    v3_live_process_registry: LiveProcessRegistry = field(
        default_factory=LiveProcessRegistry
    )
    v3_background_runtime_enabled: bool | None = None
    v3_durable_work_enabled: bool | None = None
    v3_durable_route_adapters: dict[str, ControlledOperationRouteAdapter] = field(
        default_factory=dict
    )
    v3_pipeline_sandbox_runner: Any | None = None
    v3_bio_adapter: Any | None = None
    v3_allow_bio_fixture_adapter: bool = False
    v3_tool_dispatch_precondition: Callable[..., Any] | None = None
    v3_sandbox_workspace_root: Path | None = None
    v3_artifact_blob_root: Path | None = None
    _owned_v3_temp_directory: tempfile.TemporaryDirectory[str] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.security_policy is None:
            settings = getattr(self.foundation, "settings", None)
            self.security_policy = HostSecurityPolicy.from_settings(
                None if settings is None else settings.host_api
            )
        if (
            self.v3_repository_provider is not None
            and self.v3_legacy_repositories_for_tests is not None
        ):
            raise ValueError(
                "configure either v3_repository_provider or "
                "v3_legacy_repositories_for_tests, not both"
            )
        if self.v3_legacy_repositories_for_tests is None:
            self._ensure_v3_repository_provider()

    def _ensure_v3_repository_provider(self) -> SQLiteRepositoryProvider:
        provider = self.v3_repository_provider
        if provider is not None:
            return provider
        owner = tempfile.TemporaryDirectory(prefix="openzyme-host-v3-")
        provider = SQLiteRepositoryProvider(
            str(Path(owner.name) / "control-plane.sqlite3")
        )
        self._owned_v3_temp_directory = owner
        self.v3_repository_provider = provider
        return provider

    def close_owned_v3_storage(self) -> None:
        owner = self._owned_v3_temp_directory
        if owner is None:
            return
        owner.cleanup()
        self._owned_v3_temp_directory = None
        self.v3_repository_provider = None

    @contextmanager
    def v3_repository_scope(
        self,
        *,
        mode: Literal["read", "write", "connection"] = "connection",
    ) -> Iterator[CoreRepositories]:
        legacy = self.v3_legacy_repositories_for_tests
        if legacy is not None:
            authority = current_mutation_write_authority()
            if authority is None:
                yield legacy
            else:
                with legacy.mutation_write_authority(authority):
                    yield legacy
            return
        provider = self._ensure_v3_repository_provider()
        if mode == "read":
            owner = provider.read()
        elif mode == "write":
            owner = provider.write()
        elif mode == "connection":
            owner = provider.connection_scope()
        else:  # pragma: no cover - Literal protects production callers
            raise ValueError(f"unsupported V3 repository scope mode {mode!r}")
        with owner as scope:
            authority = current_mutation_write_authority()
            if authority is None:
                yield scope.repositories
            else:
                with scope.repositories.mutation_write_authority(authority):
                    yield scope.repositories

    def v3_mutation_writer_scope(
        self,
        *,
        session_id: str,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        process_epoch: int | None = None,
    ) -> Any:
        return MutationWriterTurnFactory(
            repository_scope_factory=lambda: self.v3_repository_scope(mode="connection")
        ).open(
            session_id=session_id,
            owner_kind=owner_kind,
            owner_ref=owner_ref,
            process_epoch=process_epoch,
        )

    def finalize_pending_v3_scientific_transitions(
        self,
        session_id: str,
    ) -> None:
        with self.v3_service_scope(mode="connection") as service:
            service.finalize_pending_scientific_transitions(session_id=session_id)

    @contextmanager
    def v3_service_scope(
        self,
        *,
        mode: Literal["read", "write", "connection"] = "connection",
    ) -> Iterator[V3HostApiService]:
        with self.v3_repository_scope(mode=mode) as repositories:
            yield self._build_v3_service(repositories)

    def _build_v3_service(
        self,
        repositories: CoreRepositories,
    ) -> V3HostApiService:
        durable_route_adapters = self.build_v3_durable_route_adapters()
        return V3HostApiService(
            repositories=repositories,
            event_store=V3EventStore(repositories),
            engine_registry=self.build_v3_engine_registry(repositories),
            model_factory=self.foundation.model_factory,
            bio_research_service=self.foundation.bio_research_service,
            research_adapter=self.foundation.research_adapter,
            sandbox_workspace_root=self.v3_sandbox_workspace_root,
            artifact_blob_root=self.v3_artifact_blob_root,
            artifact_bundle_finalizer=finalize_aox_deliverable_bundle,
            signal_notifier=self.v3_signal_notifier,
            durable_work_notifier=self.v3_durable_work_notifier,
            reliability_shadow_observer=(self.foundation.reliability_shadow_observer),
            reliability_settings=(
                None
                if self.foundation.settings is None
                else self.foundation.settings.reliability
            ),
            durable_route_adapter_policy_ids={
                route_policy_id: adapter.adapter_policy_id
                for route_policy_id, adapter in durable_route_adapters.items()
            },
            tool_dispatch_precondition=self.v3_tool_dispatch_precondition,
            runtime_repository_scope_factory=self.v3_repository_scope,
            engine_registry_factory=self.build_v3_engine_registry,
            mutation_writer_scope_factory=self.v3_mutation_writer_scope,
            sandbox_host_binding_factory=self.build_v3_sandbox_host_binding,
            scheduler_limits={}
            if self.foundation.settings is None
            else dict(self.foundation.settings.limits.provider_limits),
            scientific_workflow_contract_registry=(
                AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
            ),
        )

    def build_v3_durable_route_adapters(
        self,
    ) -> dict[str, ControlledOperationRouteAdapter]:
        settings = self.foundation.settings
        reliability = None if settings is None else settings.reliability
        owner_policy = (
            "legacy_only_v1"
            if reliability is None
            else reliability.controlled_operation_owner_policy.value
        )
        admission_route_ids: tuple[str, ...] = ()
        if reliability is not None:
            if owner_policy == "durable_only_v1":
                admission_route_ids = tuple(S12_ROUTE_POLICIES)
            else:
                admission_route_ids = tuple(
                    reliability.durable_execution_route_allowlist
                )
        durable_route_ids = tuple(
            sorted(set(admission_route_ids) | set(self.active_v3_durable_route_ids()))
        )
        adapters = dict(self.v3_durable_route_adapters)
        provider_adapters = build_host_provider_route_adapters(
            route_policy_ids=durable_route_ids,
            repository_scope_factory=self.v3_repository_scope,
            engine_registry_factory=lambda repositories: self.build_v3_engine_registry(
                repositories
            ),
        )
        for route_policy_id, adapter in provider_adapters.items():
            adapters.setdefault(route_policy_id, adapter)
        hpc_adapters = build_host_hpc_route_adapters(
            route_policy_ids=durable_route_ids,
            repository_scope_factory=self.v3_repository_scope,
            engine_registry_factory=lambda repositories: self.build_v3_engine_registry(
                repositories
            ),
        )
        for route_policy_id, adapter in hpc_adapters.items():
            adapters.setdefault(route_policy_id, adapter)
        return adapters

    def active_v3_durable_route_ids(self) -> tuple[str, ...]:
        """Return frozen routes needed to drain already-admitted durable rows."""

        with self.v3_repository_scope(mode="read") as repositories:
            active = repositories.controlled_operation_executions.list_nonterminal()
        return tuple(sorted({execution.route_policy_id for execution in active}))

    def active_v3_durable_execution_count(self) -> int:
        with self.v3_repository_scope(mode="read") as repositories:
            return repositories.controlled_operation_executions.count_nonterminal()

    def active_v3_runtime_command_count(self) -> int:
        with self.v3_repository_scope(mode="read") as repositories:
            return repositories.runtime_commands.count_active()

    def active_v3_continuation_count(self) -> int:
        with self.v3_repository_scope(mode="read") as repositories:
            return repositories.continuation_deliveries.count_active()

    def build_v3_engine_registry(
        self,
        repositories: CoreRepositories,
        runtime_lease: SessionRuntimeLease | None = None,
    ) -> EngineRegistry:
        host_context_factory = HostSandboxCallContextFactory(
            repository_scope_factory=lambda: self.v3_repository_scope(
                mode="connection"
            ),
            mutation_writer_scope_factory=self.v3_mutation_writer_scope,
            runtime_lease=runtime_lease,
        )

        @contextmanager
        def pipeline_host_call_context(
            *,
            session_id: str,
            invocation_id: str,
        ) -> Iterator[SandboxHostCallContext]:
            owner = (
                SessionTurnHostAuthority.from_lease(runtime_lease)
                if runtime_lease is not None
                else SandboxProcessHostAuthority(
                    session_id=session_id,
                    sandbox_workspace_id=f"pipeline_workspace:{invocation_id}",
                    sandbox_run_id=f"pipeline_run:{invocation_id}",
                    process_epoch=1,
                )
            )
            if owner.session_id != session_id:
                raise RuntimeError("pipeline Host context crossed its session")
            with host_context_factory(owner) as context:
                yield context

        return build_engine_registry(
            DeepResearchEngine(
                repositories,
                NativeDeepResearchRunner(
                    repositories=repositories,
                    research_adapter=self.foundation.research_adapter,
                    research_tool_provider=self.foundation.research_tool_provider,
                    model_factory=self.foundation.model_factory,
                    limiter_registry=self.foundation.limiter_registry,
                    settings=self.foundation.settings,
                ),
            ),
            ExecutionEngine(
                repositories,
                V3ExecutionRunnerAdapter(
                    self.foundation.execution_adapter,
                    self.foundation.limiter_registry,
                ),
                bio_adapter=self.v3_bio_adapter
                or ProviderHttpBioDatabaseAdapter.from_env(),
                allow_bio_fixture_adapter=self.v3_allow_bio_fixture_adapter,
                sandbox_runner=self.v3_pipeline_sandbox_runner
                or PodmanPipelineSandboxRunner(),
                sandbox_workspace_root=self.v3_sandbox_workspace_root,
                artifact_blob_root=self.v3_artifact_blob_root,
                sandbox_host_call_context_factory=pipeline_host_call_context,
                sandbox_process_registry=self.v3_live_process_registry,
                sandbox_process_signal_notifier=self.v3_signal_notifier,
            ),
        )

    def build_v3_sandbox_host_binding(
        self,
        engine_registry: EngineRegistry,
        runtime_lease: SessionRuntimeLease | None,
    ) -> SandboxHostBinding:
        execution_engine = engine_registry.require("execution")
        if not isinstance(execution_engine, ExecutionEngine):
            raise TypeError("execution engine does not support sandbox Host calls")
        return SandboxHostBinding(
            gateway=ExecutionEngineSandboxHostGateway(execution_engine),
            context_factory=HostSandboxCallContextFactory(
                repository_scope_factory=lambda: self.v3_repository_scope(
                    mode="connection"
                ),
                mutation_writer_scope_factory=self.v3_mutation_writer_scope,
                runtime_lease=runtime_lease,
            ),
        )


def _api_error_payload(
    *,
    code: str,
    message: str,
    hint: str | None = None,
    details: Any | None = None,
) -> dict[str, Any]:
    safe_details = sanitize_public_diagnostic_payload(details)
    safe_code = (
        safe_public_machine_identifier(
            code,
            fallback="internal_error",
        )
        or "internal_error"
    )
    return ApiErrorResponse(
        error=ApiErrorDetail(
            code=safe_code,
            message=sanitize_public_diagnostic_text(message),
            hint=None if hint is None else sanitize_public_diagnostic_text(hint),
            details=safe_details,
        )
    ).model_dump(mode="json", exclude_none=True)


def _http_exception(
    status_code: int,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    details: Any | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_api_error_payload(
            code=code,
            message=message,
            hint=hint,
            details=details,
        )["error"],
    )


def _as_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, KeyError):
        return _http_exception(404, code="resource_not_found", message=str(exc))
    if isinstance(exc, CommandIdempotencyConflictError):
        return _http_exception(409, code="idempotency_conflict", message=str(exc))
    if isinstance(exc, ScientificAttemptError):
        status_code = (
            403
            if exc.error_code.startswith("authorization_")
            else 409
        )
        return _http_exception(
            status_code,
            code=exc.error_code,
            message=str(exc),
            hint=exc.hint,
            details=exc.details,
        )
    if isinstance(exc, ValueError):
        return _http_exception(400, code="invalid_request", message=str(exc))
    if isinstance(exc, MissingLlmConfigurationError):
        return _http_exception(503, code="llm_not_configured", message=str(exc))
    error_code = getattr(exc, "error_code", None)
    hint = getattr(exc, "hint", None)
    details = getattr(exc, "details", None)
    return _http_exception(
        500,
        code=str(error_code or "internal_error"),
        message=str(getattr(exc, "public_message", None) or exc),
        hint=None if hint is None else str(hint),
        details=details,
    )


_PREFER_WAIT_PATTERN = re.compile(r"wait=([0-9]+(?:\.[0-9]+)?)")
_PREFER_WAIT_CAP_SECONDS = Decimal("2")


def _parse_prefer_wait(value: str | None) -> float:
    if value is None:
        return 0.0
    normalized = value.strip()
    match = _PREFER_WAIT_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("Prefer must use the exact form wait=<seconds>")
    try:
        seconds = Decimal(match.group(1))
    except InvalidOperation as exc:  # guarded by the regex
        raise ValueError("Prefer wait is invalid") from exc
    if seconds > _PREFER_WAIT_CAP_SECONDS:
        raise ValueError("Prefer wait must not exceed 2 seconds")
    return float(seconds)


def _project_runtime_command(record: RuntimeCommandRecord) -> dict[str, Any]:
    return project_runtime_command(record)


async def _observe_runtime_command(
    dependencies: HostApiDependencies,
    *,
    session_id: str,
    command_id: str,
    wait_seconds: float,
) -> RuntimeCommandRecord:
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        with dependencies.v3_repository_scope(mode="read") as repositories:
            record = repositories.runtime_commands.get_for_session(
                session_id=session_id,
                command_id=command_id,
            )
        if record is None:
            raise KeyError(f"runtime command {command_id!r} does not exist")
        if record.status.is_terminal:
            return record
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return record
        await asyncio.sleep(min(0.05, remaining))


def _runtime_drain_contract(
    dependencies: HostApiDependencies,
) -> RuntimeDrainContract:
    settings = getattr(getattr(dependencies, "foundation", None), "settings", None)
    reliability = None if settings is None else getattr(settings, "reliability", None)
    configured = (
        RuntimeDrainContract.COMMAND_V1
        if reliability is None
        else RuntimeDrainContract(str(reliability.runtime_drain_contract))
    )
    if configured is RuntimeDrainContract.SYNC_V1:
        active_commands = dependencies.active_v3_runtime_command_count()
        active_continuations = dependencies.active_v3_continuation_count()
        if active_commands > 0 or active_continuations > 0:
            raise RuntimeError(
                "runtime drain API cannot downgrade while active durable commands "
                "or continuations exist"
            )
        raise RuntimeError(
            "sync_v1 runtime drain contract is retired; synchronous fallback is "
            "not available"
        )
    return configured


def _execute_idempotent_command(
    service: V3HostApiService,
    *,
    command_type: str,
    scope_ref: str,
    session_id: str | None,
    idempotency_key: str | None,
    request_payload: object,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    with _host_command_write_scope(
        service,
        command_type=command_type,
        scope_ref=scope_ref,
        session_id=session_id,
    ):
        return _execute_idempotent_command_scoped(
            service,
            command_type=command_type,
            scope_ref=scope_ref,
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            operation=operation,
        )


@contextmanager
def _host_command_write_scope(
    service: V3HostApiService,
    *,
    command_type: str,
    scope_ref: str,
    session_id: str | None,
) -> Iterator[None]:
    writer_scope_factory = service.mutation_writer_scope_factory
    if writer_scope_factory is None or session_id is None:
        yield
        return
    with MutationScopeService(service.repositories).writer_turn(
        session_id=session_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref=f"host-command:{command_type}:{scope_ref}",
    ):
        yield


def _execute_idempotent_command_scoped(
    service: V3HostApiService,
    *,
    command_type: str,
    scope_ref: str,
    session_id: str | None,
    idempotency_key: str | None,
    request_payload: object,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if idempotency_key is None:
        return operation()
    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > 256:
        raise ValueError("Idempotency-Key must contain 1 to 256 characters")
    digest_payload = {
        "command_type": command_type,
        "scope_ref": scope_ref,
        "request": request_payload,
    }
    request_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                digest_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    existing = service.repositories.command_receipts.find(
        scope_ref=scope_ref,
        command_type=command_type,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise CommandIdempotencyConflictError(
                "Idempotency-Key was already used for a different request"
            )
        return existing.response
    response = operation()
    now = utc_now_iso()
    receipt = service.repositories.command_receipts.save(
        CommandReceiptRecord(
            command_receipt_id=f"receipt_{uuid4().hex[:16]}",
            scope_ref=scope_ref,
            session_id=session_id,
            command_type=command_type,
            idempotency_key=normalized_key,
            request_digest=request_digest,
            response=response,
            created_at=now,
            completed_at=now,
        )
    )
    if receipt.request_digest != request_digest:
        raise CommandIdempotencyConflictError(
            "Idempotency-Key was concurrently used for a different request"
        )
    return receipt.response


def _request_principal(request: Request) -> HostPrincipal:
    principal = getattr(request.state, "openzyme_principal", None)
    if not isinstance(principal, HostPrincipal):
        raise _http_exception(
            401,
            code="authentication_required",
            message="request is not authenticated",
        )
    return principal


def _require_project_access(principal: HostPrincipal, project_id: str) -> None:
    if not principal.can_access_project(project_id):
        raise _http_exception(
            404, code="project_not_found", message="project does not exist"
        )


def _require_session_access(
    service: V3HostApiService,
    *,
    principal: HostPrincipal,
    security: HostSecurityPolicy,
    session_id: str,
) -> None:
    session = service.repositories.sessions.get(session_id)
    if session is None:
        raise _http_exception(
            404, code="session_not_found", message="session does not exist"
        )
    if not security.shared:
        return
    if not principal.can_access_project(session.project_id):
        raise _http_exception(
            404, code="session_not_found", message="session does not exist"
        )
    if principal.has_role("admin"):
        return
    access = service.repositories.session_access.get(
        session_id,
        principal.principal_id,
    )
    if access is None:
        raise _http_exception(
            404, code="session_not_found", message="session does not exist"
        )


def _sse_encode(event: dict[str, Any], *, envelope: bool = False) -> str:
    payload = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return (
        f"id: {int(event['cursor'])}\n"
        f"event: {'openzyme.event' if envelope else event['event_type']}\n"
        f"data: {payload}\n\n"
    )


_V3_EVENT_PAGE_SIZE = 1_000


async def _iter_v3_event_stream(
    read_events: Callable[[int], list[dict[str, Any]]],
    *,
    requested_cursor: int,
    request_high_watermark: int,
    replay: bool,
    follow: bool,
    envelope: bool,
    poll_interval_seconds: float = 0.5,
) -> AsyncIterator[str]:
    cursor = requested_cursor
    if replay:
        while cursor < request_high_watermark:
            batch = read_events(cursor)
            snapshot_events = [
                event
                for event in batch
                if int(event["cursor"]) <= request_high_watermark
            ]
            if not snapshot_events:
                break
            for event in snapshot_events:
                yield _sse_encode(event, envelope=envelope)
                cursor = int(event["cursor"])
            if cursor >= request_high_watermark or len(batch) < _V3_EVENT_PAGE_SIZE:
                break

    # A private event may own the high-watermark cursor. Follow the global
    # durable cursor so private gaps are skipped without exposing their rows.
    cursor = max(cursor, request_high_watermark)
    if not follow:
        return

    while True:
        while True:
            current = read_events(cursor)
            if not current:
                break
            for event in current:
                yield _sse_encode(event, envelope=envelope)
                cursor = int(event["cursor"])
            if len(current) < _V3_EVENT_PAGE_SIZE:
                break
        await asyncio.sleep(poll_interval_seconds)


def create_app(
    dependencies: HostApiDependencies,
    *,
    ui_dist_dir: Path | None = None,
) -> FastAPI:
    _runtime_drain_contract(dependencies)
    background_runtime = _build_background_runtime_service(dependencies)
    durable_work = _build_durable_work_supervisor(dependencies)
    security = getattr(dependencies, "security_policy", None)
    if security is None:
        foundation = getattr(dependencies, "foundation", None)
        settings = getattr(foundation, "settings", None)
        security = HostSecurityPolicy.from_settings(
            None if settings is None else settings.host_api
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        app.state.v3_background_runtime = background_runtime
        app.state.v3_durable_work = durable_work
        with dependencies.v3_service_scope(mode="write") as service:
            service.recover_abandoned_sdk_continuations()
        recover_unattached_continuations(
            repository_scope_factory=dependencies.v3_repository_scope,
            live_process_registry=dependencies.v3_live_process_registry,
            signal_notifier=dependencies.v3_signal_notifier,
            mutation_writer_scope_factory=dependencies.v3_mutation_writer_scope,
        )
        durable_work.start()
        background_runtime.start()
        try:
            yield
        finally:
            dependencies.v3_live_process_registry.stop_all(
                reason="host_lifespan_stopping"
            )
            await background_runtime.stop()
            await durable_work.stop()
            dependencies.close_owned_v3_storage()

    app = FastAPI(title="OpenZyme Host API", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        del request
        detail = exc.detail
        if isinstance(detail, dict) and isinstance(detail.get("code"), str):
            content = _api_error_payload(
                code=detail["code"],
                message=str(detail.get("message") or "HTTP request failed."),
                hint=None if detail.get("hint") is None else str(detail.get("hint")),
                details=detail.get("details"),
            )
        else:
            status_code_map = {
                400: "invalid_request",
                401: "authentication_required",
                403: "forbidden",
                404: "resource_not_found",
                409: "conflict",
                428: "precondition_required",
                503: "service_unavailable",
            }
            content = _api_error_payload(
                code=status_code_map.get(exc.status_code, "http_error"),
                message=str(detail),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        details = [
            {
                "location": [str(item) for item in error.get("loc", ())],
                "message": str(error.get("msg") or "invalid value"),
                "type": str(error.get("type") or "validation_error"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_api_error_payload(
                code="request_validation_error",
                message="Request payload failed validation.",
                hint="Correct the fields listed in error.details and retry.",
                details=details,
            ),
        )

    @app.middleware("http")
    async def add_trace_context(request, call_next):  # type: ignore[no-untyped-def]
        with host_request_trace_context(method=request.method, path=request.url.path):
            path = request.url.path
            is_v3 = path == "/v3" or path.startswith("/v3/")
            is_debug = path == "/debug" or path.startswith("/debug/")
            if is_debug and not security.debug_enabled:
                return JSONResponse(
                    status_code=404,
                    content=_api_error_payload(
                        code="resource_not_found",
                        message="Not Found",
                    ),
                )
            if is_v3 or is_debug:
                try:
                    principal = security.authenticate(
                        request.headers.get("authorization")
                    )
                except HostAuthenticationError as exc:
                    return JSONResponse(
                        status_code=401,
                        content=_api_error_payload(
                            code="authentication_failed",
                            message=str(exc),
                        ),
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                if (
                    is_debug
                    and security.shared
                    and not principal.has_role("operator", "admin")
                ):
                    return JSONResponse(
                        status_code=403,
                        content=_api_error_payload(
                            code="operator_role_required",
                            message="operator role is required",
                        ),
                    )
                if (
                    is_v3
                    and security.shared
                    and request.method in {"POST", "PUT", "PATCH", "DELETE"}
                    and not (request.headers.get("idempotency-key") or "").strip()
                ):
                    return JSONResponse(
                        status_code=428,
                        content=_api_error_payload(
                            code="idempotency_key_required",
                            message="Idempotency-Key is required for shared-profile mutations",
                            hint="Retry with a stable Idempotency-Key header for this command.",
                        ),
                    )
                request.state.openzyme_principal = principal
            response = await call_next(request)
            response.headers["X-OpenZyme-Deployment-Profile"] = (
                security.deployment_profile
            )
            return response

    @app.get(
        "/v3/runtime/health",
        response_model=RuntimeHealthResponse,
        responses={401: {"model": ApiErrorResponse}},
    )
    def get_v3_runtime_health(request: Request) -> RuntimeHealthResponse:
        _request_principal(request)
        foundation = dependencies.foundation
        model_status = _configured_component_status(
            foundation.model_factory,
            ready_type_names=frozenset({"OpenAICompatibleChatModelFactory"}),
        )
        execution_status = _configured_component_status(
            foundation.execution_adapter,
            ready_type_names=frozenset({"HpcRunnerExecutionAdapter"}),
            unavailable_type_names=frozenset({"UnavailableExecutionAdapter"}),
        )
        research_status = _configured_component_status(
            foundation.research_adapter,
            ready_type_names=frozenset({"TavilyResearchAdapter"}),
        )
        bio_research_status = _configured_component_status(
            foundation.bio_research_service,
            ready_type_names=frozenset({"DefaultBioResearchService"}),
        )

        background_status = background_runtime.status()
        if background_status["running"]:
            worker_status = "degraded" if background_status["last_error"] else "ready"
        elif background_status["enabled"]:
            worker_status = "unavailable"
        else:
            worker_status = "disabled"

        sandbox_runner = (
            dependencies.v3_pipeline_sandbox_runner or PodmanPipelineSandboxRunner()
        )
        try:
            sandbox_preflight = sandbox_runner.preflight()
        except Exception:
            sandbox_preflight = None
        sandbox_identity = dict(
            getattr(sandbox_preflight, "runtime_identity", None) or {}
        )
        sandbox_status = (
            "ready"
            if sandbox_preflight is not None and bool(sandbox_preflight.ok)
            else "unavailable"
        )
        components = {
            "control_plane": RuntimeComponentHealth(
                status="ready",
                details={"storage": "single_process_sqlite"},
            ),
            "model": RuntimeComponentHealth(status=model_status),
            "background_runtime": RuntimeComponentHealth(
                status=worker_status,
                details={
                    "enabled": bool(background_status["enabled"]),
                    "running": bool(background_status["running"]),
                    "disabled": background_status["disabled_reason"] is not None,
                    "last_tick_at": background_status["last_tick_at"],
                    "tick_count": int(background_status["tick_count"]),
                    "processed_signal_count": int(
                        background_status["processed_signal_count"]
                    ),
                    "has_error": background_status["last_error"] is not None,
                },
            ),
            "execution": RuntimeComponentHealth(status=execution_status),
            "web_research": RuntimeComponentHealth(status=research_status),
            "bio_research": RuntimeComponentHealth(
                status=bio_research_status,
            ),
            "sandbox": RuntimeComponentHealth(
                status=sandbox_status,
                details={
                    key: sandbox_identity[key]
                    for key in (
                        "image_digest",
                        "pipeline_sdk_digest",
                        "runtime_identity_digest",
                        "sandbox_protocol_version",
                    )
                    if key in sandbox_identity
                },
            ),
        }
        overall_status = (
            "ready"
            if all(component.status == "ready" for component in components.values())
            else "degraded"
        )
        return RuntimeHealthResponse(
            status=overall_status,
            deployment_profile=security.deployment_profile,
            observed_at=utc_now_iso(),
            components=components,
        )

    @app.post(
        "/v3/sessions",
        response_model=V3SessionCreateResponse,
        responses={400: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def create_v3_session(
        request: CreateV3SessionRequest,
        http_request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(http_request)
            _require_project_access(principal, request.project_id)
            with dependencies.v3_service_scope(mode="write") as service:

                def create_owned_session() -> dict[str, Any]:
                    result = service.create_session(
                        project_id=request.project_id,
                        objective=request.objective,
                        title=request.title,
                        session_id=request.session_id,
                    )
                    service.repositories.session_access.save(
                        SessionAccessRecord(
                            session_id=str(result["session_id"]),
                            principal_id=principal.principal_id,
                            access_role="owner",
                            created_at=utc_now_iso(),
                        )
                    )
                    return result

                return _execute_idempotent_command(
                    service,
                    command_type="session.create",
                    scope_ref=(
                        f"principal:{principal.principal_id}:project:{request.project_id}"
                    ),
                    session_id=request.session_id,
                    idempotency_key=idempotency_key,
                    request_payload=request.model_dump(mode="json"),
                    operation=create_owned_session,
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get(
        "/v3/projects/{project_id}/sessions",
        response_model=list[V3SessionSummaryResponse],
    )
    def list_v3_project_sessions(
        project_id: str,
        request: Request,
    ) -> list[dict[str, Any]]:
        try:
            principal = _request_principal(request)
            _require_project_access(principal, project_id)
            with dependencies.v3_service_scope(mode="read") as service:
                sessions = service.list_sessions(project_id)
                if not security.shared or principal.has_role("admin"):
                    return sessions
                allowed = set(
                    service.repositories.session_access.list_session_ids(
                        principal.principal_id,
                        project_id=project_id,
                    )
                )
                return [item for item in sessions if item["session_id"] in allowed]
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get(
        "/v3/sessions/{session_id}",
        response_model=V3SessionWorkspaceResponse,
    )
    def get_v3_session(session_id: str, request: Request) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="read") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                workspace = service.workspace(session_id)
                return {"session": workspace["session"], "workspace": workspace}
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post(
        "/v3/sessions/{session_id}/messages",
        response_model=V3CommandResponse,
        responses={400: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def post_v3_message(
        session_id: str,
        request: PostV3MessageRequest,
        http_request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(http_request)
            # Message admission only persists conversation state and queues a
            # runtime signal; provider work belongs to the explicit drain command.
            with dependencies.v3_service_scope(mode="write") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                with llm_debug_context(
                    request_path=f"/v3/sessions/{session_id}/messages",
                    session_id=session_id,
                    task_id=request.task_id,
                    lane_id=request.lane_id,
                    actor=principal.principal_id,
                ):
                    return _execute_idempotent_command(
                        service,
                        command_type="conversation.message.post",
                        scope_ref=f"session:{session_id}",
                        session_id=session_id,
                        idempotency_key=idempotency_key,
                        request_payload=request.model_dump(mode="json"),
                        operation=lambda: service.post_message(
                            session_id=session_id,
                            message=request.message,
                            task_id=request.task_id,
                            lane_id=request.lane_id,
                            skill_keys=tuple(request.skill_keys),
                        ).to_dict(),
                    )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post(
        "/v3/sessions/{session_id}/runtime/drain",
        response_model=V3RuntimeCommandResponse,
        status_code=202,
        responses={
            400: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
        },
    )
    async def drain_v3_runtime(
        session_id: str,
        request: DrainV3RuntimeRequest,
        http_request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        prefer: str | None = Header(default=None, alias="Prefer"),
    ) -> dict[str, Any]:
        try:
            wait_seconds = _parse_prefer_wait(prefer)
            principal = _request_principal(http_request)
            if security.shared and not principal.has_role("operator", "admin"):
                raise HTTPException(
                    status_code=403,
                    detail="operator role is required",
                )
            with dependencies.v3_service_scope(mode="write") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                with llm_debug_context(
                    request_path=f"/v3/sessions/{session_id}/runtime/drain",
                    session_id=session_id,
                    actor=principal.principal_id,
                ):
                    with _host_command_write_scope(
                        service,
                        command_type="runtime.drain.admit",
                        scope_ref=f"session:{session_id}",
                        session_id=session_id,
                    ):
                        command, _created = service.admit_runtime_command(
                            session_id=session_id,
                            idempotency_key=idempotency_key,
                            max_signals=request.max_signals,
                            max_steps_per_agent=request.max_steps_per_agent,
                            auto_enqueue_ready_tasks=(
                                request.auto_enqueue_ready_tasks
                            ),
                        )
            dependencies.v3_durable_work_notifier.notify(session_id)
            observed = await _observe_runtime_command(
                dependencies,
                session_id=session_id,
                command_id=command.command_id,
                wait_seconds=wait_seconds,
            )
            return _project_runtime_command(observed)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get(
        "/v3/sessions/{session_id}/runtime/commands/{command_id}",
        response_model=V3RuntimeCommandResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def get_v3_runtime_command(
        session_id: str,
        command_id: str,
        http_request: Request,
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(http_request)
            with dependencies.v3_service_scope(mode="read") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                command = service.repositories.runtime_commands.get_for_session(
                    session_id=session_id,
                    command_id=command_id,
                )
                if command is None:
                    raise KeyError(f"runtime command {command_id!r} does not exist")
                return _project_runtime_command(command)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/v3/sessions/{session_id}/workspace")
    def get_v3_workspace(session_id: str, request: Request) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="read") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return service.workspace(session_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/v3/sessions/{session_id}/scientific-attempts")
    def get_v3_scientific_attempts(
        session_id: str,
        request: Request,
        attempt_id: str | None = None,
        selection_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="read") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                control = service.scientific_attempt_control()
                if (
                    attempt_id is None
                    and selection_id is None
                    and cursor is None
                ):
                    return control.project_session(
                        session_id,
                        limit=limit,
                    )
                if attempt_id is None or selection_id is None:
                    raise ScientificAttemptError(
                        "scientific_inspection_filter_incomplete",
                        "detailed scientific inspection requires exact attempt and selection ids",
                        details={"mutation_applied": False},
                    )
                return control.inspect_selection(
                    session_id=session_id,
                    attempt_id=attempt_id,
                    selection_id=selection_id,
                    limit=limit,
                    cursor=cursor,
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/sessions/{session_id}/scientific-attempt-authorizations")
    def grant_v3_scientific_attempt_authorization(
        session_id: str,
        payload: GrantScientificAttemptAuthorizationRequest,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            if security.shared and not principal.has_role("operator", "admin"):
                raise HTTPException(
                    status_code=403,
                    detail="operator role is required",
                )
            with dependencies.v3_service_scope(mode="write") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return service.grant_scientific_attempt_authorization(
                    payload.model_dump(mode="json"),
                    session_id=session_id,
                    grantor_ref=principal.principal_id,
                    idempotency_key=idempotency_key,
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/sessions/{session_id}/scientific-attempt-commands")
    def execute_v3_scientific_attempt_command(
        session_id: str,
        payload: ScientificAttemptCommandRequest,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return service.execute_scientific_attempt_command(
                    payload.command,
                    dict(payload.arguments),
                    session_id=session_id,
                    actor_ref=principal.principal_id,
                    idempotency_key=idempotency_key,
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/sessions/{session_id}/scientific-attempt-admissions/finalize")
    def finalize_v3_scientific_attempt_admission(
        session_id: str,
        payload: FinalizeScientificAttemptAdmissionRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            if security.shared and not principal.has_role("operator", "admin"):
                raise HTTPException(
                    status_code=403,
                    detail="operator role is required",
                )
            with dependencies.v3_service_scope(mode="write") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return service.finalize_scientific_attempt_admission(
                    session_id=session_id,
                    admission_request_id=payload.admission_request_id,
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/sessions/{session_id}/scientific-attempt-closures/finalize")
    def finalize_v3_scientific_attempt_closure(
        session_id: str,
        payload: FinalizeScientificAttemptClosureRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            if security.shared and not principal.has_role("operator", "admin"):
                raise HTTPException(
                    status_code=403,
                    detail="operator role is required",
                )
            with dependencies.v3_service_scope(mode="write") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return service.finalize_scientific_attempt_closure(
                    session_id=session_id,
                    closure_request_id=payload.closure_request_id,
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get(
        "/v3/sessions/{session_id}/pending-approvals",
        response_model=V3PendingApprovalsResponse,
    )
    def get_v3_pending_approvals(session_id: str, request: Request) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="read") as service:
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return {
                    "session_id": session_id,
                    "pending_approvals": service.pending_approvals(session_id),
                }
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/v3/sessions/{session_id}/events")
    def stream_v3_events(
        session_id: str,
        request: Request,
        replay: bool = True,
        follow: bool = False,
        after_cursor: int | None = None,
        envelope: bool = False,
    ) -> StreamingResponse:
        principal = _request_principal(request)
        with dependencies.v3_service_scope(mode="read") as service:
            _require_session_access(
                service,
                principal=principal,
                security=security,
                session_id=session_id,
            )
            request_high_watermark = service.event_store.latest_cursor(session_id)

        last_event_id = request.headers.get("last-event-id")
        if after_cursor is not None and last_event_id is not None:
            raise HTTPException(
                status_code=400,
                detail="after_cursor and Last-Event-ID cannot both be supplied",
            )
        try:
            requested_cursor = (
                after_cursor
                if after_cursor is not None
                else (int(last_event_id) if last_event_id is not None else 0)
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Last-Event-ID must be an integer",
            ) from exc
        if requested_cursor < 0:
            raise HTTPException(
                status_code=400,
                detail="after_cursor must be non-negative",
            )

        def read_events(cursor: int) -> list[dict[str, Any]]:
            # StreamingResponse starts consuming after the route returns. Never
            # capture a request-scoped service/connection in the generator.
            with dependencies.v3_service_scope(mode="read") as scoped_service:
                return scoped_service.events(
                    session_id,
                    after_cursor=cursor,
                    limit=_V3_EVENT_PAGE_SIZE,
                )

        return StreamingResponse(
            _iter_v3_event_stream(
                read_events,
                requested_cursor=requested_cursor,
                request_high_watermark=request_high_watermark,
                replay=replay,
                follow=follow,
                envelope=envelope,
            ),
            media_type="text/event-stream",
        )

    @app.post(
        "/v3/tasks",
        response_model=V3TaskMutationResponse,
        responses={400: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def create_v3_task(
        payload: CreateV3TaskRequest,
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                payload_dict = payload.model_dump(mode="json")
                session_id = payload.session_id
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return _execute_idempotent_command(
                    service,
                    command_type="task.create",
                    scope_ref=f"session:{session_id}",
                    session_id=session_id or None,
                    idempotency_key=idempotency_key,
                    request_payload=payload_dict,
                    operation=lambda: service.create_task(payload_dict),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.patch(
        "/v3/tasks/{task_id}",
        response_model=V3TaskMutationResponse,
        responses={400: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def update_v3_task(
        task_id: str,
        payload: UpdateV3TaskRequest,
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                task = service.repositories.tasks.get(task_id)
                if task is None:
                    raise KeyError(f"task {task_id!r} does not exist")
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=task.session_id,
                )
                payload_dict = payload.model_dump(mode="json", exclude_unset=True)
                return _execute_idempotent_command(
                    service,
                    command_type="task.update",
                    scope_ref=f"task:{task_id}",
                    session_id=task.session_id,
                    idempotency_key=idempotency_key,
                    request_payload=payload_dict,
                    operation=lambda: service.update_task(task_id, payload_dict),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post(
        "/v3/lanes",
        response_model=V3LaneMutationResponse,
        responses={400: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def create_v3_lane(
        payload: CreateV3LaneRequest,
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                payload_dict = payload.model_dump(mode="json")
                session_id = payload.session_id
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=session_id,
                )
                return _execute_idempotent_command(
                    service,
                    command_type="lane.create",
                    scope_ref=f"session:{session_id}",
                    session_id=session_id or None,
                    idempotency_key=idempotency_key,
                    request_payload=payload_dict,
                    operation=lambda: service.create_lane(payload_dict),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post(
        "/v3/lanes/{lane_id}/claim",
        response_model=V3LaneMutationResponse,
        responses={400: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def claim_v3_lane(
        lane_id: str,
        payload: ClaimV3LaneRequest,
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                lane = service.repositories.lanes.get(lane_id)
                if lane is None:
                    raise KeyError(f"lane {lane_id!r} does not exist")
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=lane.session_id,
                )
                return _execute_idempotent_command(
                    service,
                    command_type="lane.claim",
                    scope_ref=f"lane:{lane_id}",
                    session_id=lane.session_id,
                    idempotency_key=idempotency_key,
                    request_payload=payload.model_dump(mode="json"),
                    operation=lambda: service.claim_lane(
                        lane_id,
                        claimed_ref=principal.principal_id,
                    ),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post(
        "/v3/lanes/{lane_id}/keep",
        response_model=V3LaneMutationResponse,
    )
    def keep_v3_lane(
        lane_id: str,
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                lane = service.repositories.lanes.get(lane_id)
                if lane is None:
                    raise KeyError(f"lane {lane_id!r} does not exist")
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=lane.session_id,
                )
                return _execute_idempotent_command(
                    service,
                    command_type="lane.keep",
                    scope_ref=f"lane:{lane_id}",
                    session_id=lane.session_id,
                    idempotency_key=idempotency_key,
                    request_payload={},
                    operation=lambda: service.keep_lane(lane_id),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post(
        "/v3/lanes/{lane_id}/remove",
        response_model=V3LaneMutationResponse,
    )
    def remove_v3_lane(
        lane_id: str,
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                lane = service.repositories.lanes.get(lane_id)
                if lane is None:
                    raise KeyError(f"lane {lane_id!r} does not exist")
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=lane.session_id,
                )
                return _execute_idempotent_command(
                    service,
                    command_type="lane.remove",
                    scope_ref=f"lane:{lane_id}",
                    session_id=lane.session_id,
                    idempotency_key=idempotency_key,
                    request_payload={},
                    operation=lambda: service.remove_lane(lane_id),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post(
        "/v3/approvals/{approval_id}/resolve",
        response_model=V3CommandResponse,
        responses={400: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def resolve_v3_approval(
        approval_id: str,
        request: ResolveV3ApprovalRequest,
        http_request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(http_request)
            with dependencies.v3_service_scope(mode="write") as service:
                approval = service.repositories.approvals.get(approval_id)
                if approval is None:
                    raise KeyError(f"approval {approval_id!r} does not exist")
                _require_session_access(
                    service,
                    principal=principal,
                    security=security,
                    session_id=approval.session_id,
                )
                with llm_debug_context(
                    request_path=f"/v3/approvals/{approval_id}/resolve",
                    approval_id=approval_id,
                    actor=principal.principal_id,
                ):
                    return _execute_idempotent_command(
                        service,
                        command_type="approval.resolve",
                        scope_ref=f"approval:{approval_id}",
                        session_id=approval.session_id,
                        idempotency_key=idempotency_key,
                        request_payload={
                            **request.model_dump(mode="json"),
                            "actor_ref": principal.principal_id,
                        },
                        operation=lambda: service.resolve_approval(
                            approval_id,
                            decision=request.decision,
                            actor_ref=principal.principal_id,
                        ).to_dict(),
                    )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/debug/llm-calls")
    def list_llm_debug_calls(
        limit: int = 100,
        purpose: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return get_llm_debug_recorder().list_records(
            limit=limit,
            purpose=purpose,
            kind=kind,
            status=status,
            session_id=session_id,
        )

    @app.get("/debug/llm-calls/{debug_id}")
    def get_llm_debug_call(debug_id: str) -> dict[str, Any]:
        record = get_llm_debug_recorder().get_record(debug_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"debug call {debug_id!r} does not exist"
            )
        return record

    @app.post("/debug/llm-calls/clear")
    def clear_llm_debug_calls() -> dict[str, Any]:
        get_llm_debug_recorder().clear()
        return {"ok": True}

    @app.get("/debug/v3-runtime")
    def get_v3_runtime_debug() -> dict[str, Any]:
        return background_runtime.status()

    @app.get("/debug/v3-durable-work")
    def get_v3_durable_work_debug() -> dict[str, Any]:
        return durable_work.status()

    if ui_dist_dir is not None and ui_dist_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_dist_dir), html=True), name="ui")

        @app.get("/debug", include_in_schema=False)
        def debug_page() -> FileResponse:
            return FileResponse(str(ui_dist_dir / "debug.html"))

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

    return app


def _build_background_runtime_service(
    dependencies: HostApiDependencies,
) -> V3BackgroundRuntimeService:
    settings = getattr(getattr(dependencies, "foundation", None), "settings", None)
    runtime_settings = (
        None if settings is None else getattr(settings, "v3_background_runtime", None)
    )
    enabled_override = getattr(dependencies, "v3_background_runtime_enabled", None)
    notifier = getattr(dependencies, "v3_signal_notifier", RuntimeSignalNotifier())
    enabled = (
        enabled_override
        if enabled_override is not None
        else (False if runtime_settings is None else bool(runtime_settings.enabled))
    )
    service_scope = getattr(dependencies, "v3_service_scope", None)

    return V3BackgroundRuntimeService(
        build_service=None,
        service_scope=service_scope,
        notifier=notifier,
        enabled=enabled,
        poll_interval_seconds=2.0
        if runtime_settings is None
        else float(runtime_settings.poll_interval_seconds),
        max_signals_per_tick=3
        if runtime_settings is None
        else int(runtime_settings.max_signals_per_tick),
        max_steps_per_agent=8
        if runtime_settings is None
        else int(runtime_settings.max_steps_per_agent),
        shutdown_timeout_seconds=10.0
        if runtime_settings is None
        else float(runtime_settings.shutdown_timeout_seconds),
    )


def _build_durable_work_supervisor(
    dependencies: HostApiDependencies,
) -> V3DurableWorkSupervisor:
    settings = getattr(getattr(dependencies, "foundation", None), "settings", None)
    reliability = None if settings is None else getattr(settings, "reliability", None)
    owner_policy = (
        "legacy_only_v1"
        if reliability is None
        else str(reliability.controlled_operation_owner_policy.value)
    )
    enabled_override = dependencies.v3_durable_work_enabled
    active_execution_count = dependencies.active_v3_durable_execution_count()
    active_command_count = dependencies.active_v3_runtime_command_count()
    active_continuation_count = dependencies.active_v3_continuation_count()
    command_contract = (
        RuntimeDrainContract.COMMAND_V1
        if reliability is None
        else reliability.runtime_drain_contract
    )
    durable_worker_required = (
        owner_policy != "legacy_only_v1"
        or active_execution_count > 0
        or command_contract is RuntimeDrainContract.COMMAND_V1
        or active_command_count > 0
        or active_continuation_count > 0
    )
    if enabled_override is False and durable_worker_required:
        raise RuntimeError(
            "durable work cannot be disabled while durable admission or active rows exist"
        )
    enabled = (
        enabled_override if enabled_override is not None else durable_worker_required
    )
    adapters = dependencies.build_v3_durable_route_adapters()
    coordinators: dict[str, V3DurableWorkCoordinator] = {}
    coordinator_lock = threading.Lock()

    def worker_factory(worker_id: str) -> V3DurableWorkCoordinator:
        with coordinator_lock:
            existing = coordinators.get(worker_id)
            if existing is not None:
                return existing
            workers = []
            if owner_policy != "legacy_only_v1" or active_execution_count > 0:
                workers.append(
                    ControlledOperationExecutionWorker(
                        repository_scope_factory=dependencies.v3_repository_scope,
                        adapters=adapters,
                        worker_id=f"{worker_id}:execution",
                        mutation_writer_scope_factory=(
                            dependencies.v3_mutation_writer_scope
                        ),
                    )
                )
            if owner_policy != "legacy_only_v1" or active_continuation_count > 0:
                workers.append(
                    ContinuationDeliveryWorker(
                        repository_scope_factory=dependencies.v3_repository_scope,
                        live_process_registry=(dependencies.v3_live_process_registry),
                        signal_notifier=dependencies.v3_signal_notifier,
                        worker_id=f"{worker_id}:continuation-delivery",
                        mutation_writer_scope_factory=(
                            dependencies.v3_mutation_writer_scope
                        ),
                    )
                )
            if (
                command_contract is RuntimeDrainContract.COMMAND_V1
                or active_command_count > 0
            ):
                workers.append(
                    RuntimeCommandWorker(
                        repository_scope_factory=dependencies.v3_repository_scope,
                        executor=HostRuntimeCommandExecutor(
                            service_scope=lambda: dependencies.v3_service_scope(
                                mode="connection"
                            ),
                            worker_id=f"{worker_id}:runtime-command",
                        ),
                        worker_id=f"{worker_id}:runtime-command",
                        mutation_writer_scope_factory=(
                            dependencies.v3_mutation_writer_scope
                        ),
                        post_writer_finalizer=(
                            dependencies.finalize_pending_v3_scientific_transitions
                        ),
                    )
                )
            if not workers:
                raise RuntimeError("durable work has no configured worker kind")
            coordinator = V3DurableWorkCoordinator(tuple(workers))
            coordinators[worker_id] = coordinator
            return coordinator

    return V3DurableWorkSupervisor(
        worker_factory=worker_factory,
        notifier=dependencies.v3_durable_work_notifier,
        enabled=enabled,
        max_concurrency=(
            1 if dependencies.v3_legacy_repositories_for_tests is not None else 2
        ),
    )
