"""File-backed Standard product composition lifecycle and bounded workers."""

from __future__ import annotations

from builtins import ExceptionGroup
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import Event
from threading import RLock
from threading import Thread
from types import MappingProxyType
from typing import Any
from typing import Protocol
from uuid import uuid4

from openzyme_contracts import ClockPort
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelSessionDiscoveryPort
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_host_api import HostSecurityPolicy
from openzyme_store_sqlite import SQLiteConnectionProvider
from openzyme_store_sqlite import SQLiteStoreAdapterError
from openzyme_store_sqlite import SQLiteStoreConfiguration

from .application_runtime import StandardKernelApplicationRuntime
from .application_runtime import StandardOperationalAdapterSelection
from .composition import StandardDeploymentStartup
from .composition import activate_standard_composition
from .host_gateway import StandardSessionBootstrapAuthorityPort
from .host_gateway import StandardWorkspaceBootstrapDefaults
from .host_surface import build_standard_v2_host_app
from .role_policies import STANDARD_RESIDENT_ROLES
from .role_policies import standard_subject_policy_decisions_by_role
from .role_policies import standard_tool_exposure_policies
from .workflow_registry import StandardExplicitEmptyWorkflowRegistry


class StandardProductLifecycleState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SystemUtcClock:
    def now_iso(self) -> str:
        return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class UuidIdGenerator:
    def new_id(self, *, namespace: str) -> str:
        require_identifier(namespace, field_name="namespace")
        return f"{namespace}-{uuid4()}"


@dataclass(frozen=True, slots=True)
class StandardProductWorkerBounds:
    poll_interval_seconds: float = 0.25
    maximum_sessions_per_tick: int = 64
    maximum_provisioning_per_session: int = 1
    maximum_runtime_commands_per_session: int = 1
    shutdown_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.poll_interval_seconds, int | float)
            or isinstance(self.poll_interval_seconds, bool)
            or not 0.01 <= float(self.poll_interval_seconds) <= 60
        ):
            raise ValueError("worker poll interval must be within [0.01, 60]")
        for field_name, maximum in (
            ("maximum_sessions_per_tick", 1_024),
            ("maximum_provisioning_per_session", 64),
            ("maximum_runtime_commands_per_session", 64),
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= maximum
            ):
                raise ValueError(f"{field_name} exceeds its closed bound")
        if (
            not isinstance(self.shutdown_timeout_seconds, int | float)
            or isinstance(self.shutdown_timeout_seconds, bool)
            or not 0.1 <= float(self.shutdown_timeout_seconds) <= 300
        ):
            raise ValueError("worker shutdown timeout must be within [0.1, 300]")


@dataclass(frozen=True, slots=True)
class StandardProductComposition:
    """All exact identities and Ports required before opening the Host."""

    startup: StandardDeploymentStartup
    clock: ClockPort
    ids: IdGeneratorPort
    bootstrap_authority: StandardSessionBootstrapAuthorityPort
    bootstrap_defaults_by_project: Mapping[
        str,
        StandardWorkspaceBootstrapDefaults,
    ]
    security_policy: HostSecurityPolicy
    operational_selection: StandardOperationalAdapterSelection
    durable_root_paths: tuple[Path, ...] = ()
    allow_non_live_adapters: bool = False
    retirement_hooks: tuple[Callable[[], None], ...] = ()

    def __post_init__(self) -> None:
        defaults = dict(self.bootstrap_defaults_by_project)
        if not defaults:
            raise ValueError("Standard product requires explicit bootstrap defaults")
        object.__setattr__(
            self,
            "bootstrap_defaults_by_project",
            MappingProxyType(defaults),
        )
        if any(not callable(hook) for hook in self.retirement_hooks):
            raise TypeError("Standard retirement hooks must be callable")
        roots = tuple(self.durable_root_paths)
        if any(not isinstance(root, Path) for root in roots):
            raise TypeError("Standard durable roots must be pathlib.Path values")
        object.__setattr__(self, "durable_root_paths", roots)


class StandardProductCompositionFactoryPort(Protocol):
    """Build deployment facts from the Store Adapter's read-only verifier."""

    factory_id: str
    factory_digest: str

    def build(
        self,
        *,
        connection: Any,
        component_configuration: Mapping[str, object],
    ) -> StandardProductComposition: ...


class StandardStoreWriterHandlePort(Protocol):
    """Opaque writer handle opened and verified by the selected Store Adapter."""

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StandardProductPreflightReceipt:
    database_path: str
    activation_digest: str
    release_digest: str
    workflow_registry_snapshot_digest: str
    role_policy_digest: str
    runtime_adapter_id: str
    runtime_adapter_contract_digest: str
    durable_root_paths: tuple[str, ...]
    workspace_adapter_binding_digests: tuple[str, ...]
    file_backed: bool = True
    fallback_performed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_standard_product_preflight@1",
            "database_path": self.database_path,
            "activation_digest": self.activation_digest,
            "release_digest": self.release_digest,
            "workflow_registry_snapshot_digest": (
                self.workflow_registry_snapshot_digest
            ),
            "role_policy_digest": self.role_policy_digest,
            "runtime_adapter_id": self.runtime_adapter_id,
            "runtime_adapter_contract_digest": (
                self.runtime_adapter_contract_digest
            ),
            "durable_root_paths": list(self.durable_root_paths),
            "workspace_adapter_binding_digests": list(
                self.workspace_adapter_binding_digests
            ),
            "file_backed": self.file_backed,
            "fallback_performed": self.fallback_performed,
            "receipt_digest": self.receipt_digest,
        }

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_standard_product_preflight@1",
                "database_path": self.database_path,
                "activation_digest": self.activation_digest,
                "release_digest": self.release_digest,
                "workflow_registry_snapshot_digest": (
                    self.workflow_registry_snapshot_digest
                ),
                "role_policy_digest": self.role_policy_digest,
                "runtime_adapter_id": self.runtime_adapter_id,
                "runtime_adapter_contract_digest": (
                    self.runtime_adapter_contract_digest
                ),
                "durable_root_paths": list(self.durable_root_paths),
                "workspace_adapter_binding_digests": list(
                    self.workspace_adapter_binding_digests
                ),
                "file_backed": self.file_backed,
                "fallback_performed": self.fallback_performed,
            }
        )


@dataclass(frozen=True, slots=True)
class StandardProductWorkerTick:
    session_ids: tuple[str, ...]
    provisioning_receipt_count: int
    runtime_receipt_count: int
    fallback_performed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_standard_product_worker_tick@1",
            "session_ids": list(self.session_ids),
            "provisioning_receipt_count": self.provisioning_receipt_count,
            "runtime_receipt_count": self.runtime_receipt_count,
            "fallback_performed": self.fallback_performed,
        }


class StandardProductLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        require_identifier(code, field_name="code")
        self.code = code
        self.component = "openzyme.standard"
        self.effect_certainty = "no_effect"
        self.mutation_applied = False
        self.fallback_performed = False
        seed = canonical_sha256_digest(
            {"component": self.component, "code": code, "message": message}
        ).removeprefix("sha256:")[:24]
        self.diagnostic_id = f"diagnostic-standard-{seed}"
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_standard_lifecycle_error@1",
            "code": self.code,
            "message": str(self),
            "component": self.component,
            "effect_certainty": self.effect_certainty,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "diagnostic_id": self.diagnostic_id,
        }


def preflight_standard_product_composition(
    *,
    database_path: Path,
    composition: StandardProductComposition,
) -> StandardProductPreflightReceipt:
    """Validate one exact file-backed graph before writer/HTTP reachability."""

    resolved = database_path.resolve(strict=False)
    if not resolved.is_absolute() or str(resolved) == ":memory:":
        raise StandardProductLifecycleError(
            "standard_file_store_required",
            "Standard product startup requires one absolute file-backed SQLite path",
        )
    active = composition.startup.gate.active_epoch
    if active is None or active.distribution_id != "openzyme.standard":
        raise StandardProductLifecycleError(
            "standard_activation_missing",
            "Standard deployment activation is absent or owned by another Distribution",
        )
    declared = activate_standard_composition()
    if (
        active.release_identity.declared_tool_catalog_digest
        != declared.declared_tool_catalog.catalog_digest
        or active.release_identity.extension_bundle_digest
        != declared.plugins.extension_bundle_digest
    ):
        raise StandardProductLifecycleError(
            "standard_activation_catalog_drift",
            "Standard activation differs from the current exact catalogs",
        )
    decisions = standard_subject_policy_decisions_by_role(
        declared.declared_tool_catalog
    )
    policies = standard_tool_exposure_policies(
        declared.declared_tool_catalog,
        release_digest=active.release_identity.release_digest,
    )
    if tuple(decisions) != STANDARD_RESIDENT_ROLES or tuple(
        policy.subject_role for policy in policies
    ) != STANDARD_RESIDENT_ROLES:
        raise StandardProductLifecycleError(
            "standard_role_policy_incomplete",
            "Standard role policy does not cover every resident role",
        )
    registry = StandardExplicitEmptyWorkflowRegistry(clock=composition.clock)
    try:
        durable_roots = tuple(
            sorted(
                (
                    root.resolve(strict=True)
                    for root in composition.durable_root_paths
                ),
                key=str,
            )
        )
    except OSError as exc:
        raise StandardProductLifecycleError(
            "standard_durable_root_missing",
            "A configured Standard durable root does not exist",
        ) from exc
    if (
        not durable_roots
        or len(set(durable_roots)) != len(durable_roots)
        or any(not root.is_absolute() or not root.is_dir() for root in durable_roots)
    ):
        raise StandardProductLifecycleError(
            "standard_durable_root_invalid",
            "Standard startup requires unique absolute durable root directories",
        )
    selection = composition.operational_selection
    runtime_adapter_id = selection.runtime_adapter.adapter_id
    runtime_contract_digest = selection.runtime_adapter.adapter_contract_digest
    require_identifier(runtime_adapter_id, field_name="runtime_adapter_id")
    require_digest(
        runtime_contract_digest,
        field_name="runtime_adapter_contract_digest",
    )
    if not composition.allow_non_live_adapters and runtime_adapter_id != (
        "openzyme.runtime.llm"
    ):
        raise StandardProductLifecycleError(
            "standard_runtime_adapter_identity_invalid",
            "Live-capable Standard startup requires the selected LLM runtime Adapter",
        )
    provisioner = selection.workspace_provisioner
    bindings: list[str] = []
    for project_id, defaults in composition.bootstrap_defaults_by_project.items():
        if (
            project_id != defaults.repository_binding.project_id
            or defaults.provider_id != selection.workspace_provider_id
            or defaults.provider_id != provisioner.provider_id
            or defaults.adapter_binding_digest
            != provisioner.adapter_binding_digest
        ):
            raise StandardProductLifecycleError(
                "standard_workspace_adapter_identity_invalid",
                "Bootstrap defaults differ from the exact workspace provisioner",
            )
        bindings.append(defaults.adapter_binding_digest)
    if len(set(bindings)) != len(bindings) and len(bindings) > 1:
        # Multiple projects may intentionally share an Adapter binding.  Record
        # the exact unique set without inventing a different binding per project.
        bindings = sorted(set(bindings))
    role_policy_digest = canonical_sha256_digest(
        {
            "subject_decisions": {
                role: [
                    {
                        "tool_name": item.tool_name,
                        "action": item.action.value,
                    }
                    for item in decisions[role]
                ]
                for role in STANDARD_RESIDENT_ROLES
            },
            "exposure_policies": [
                {
                    "policy_id": policy.policy_id,
                    "subject_role": policy.subject_role,
                    "policy_digest": policy.policy_digest,
                }
                for policy in policies
            ],
        }
    )
    return StandardProductPreflightReceipt(
        database_path=str(resolved),
        activation_digest=active.activation_digest,
        release_digest=active.release_identity.release_digest,
        workflow_registry_snapshot_digest=registry.registry_snapshot_digest,
        role_policy_digest=role_policy_digest,
        runtime_adapter_id=runtime_adapter_id,
        runtime_adapter_contract_digest=runtime_contract_digest,
        durable_root_paths=tuple(str(root) for root in durable_roots),
        workspace_adapter_binding_digests=tuple(sorted(set(bindings))),
    )


@dataclass(slots=True)
class StandardProductLifecycle:
    """Own HTTP admission, bounded workers and the selected Store writer handle."""

    database_path: Path
    store_writer: StandardStoreWriterHandlePort
    records: KernelSessionDiscoveryPort
    composition: StandardProductComposition
    runtime: StandardKernelApplicationRuntime
    app: Any
    preflight: StandardProductPreflightReceipt
    worker_bounds: StandardProductWorkerBounds = StandardProductWorkerBounds()
    state: StandardProductLifecycleState = StandardProductLifecycleState.CREATED
    _accepting: bool = field(default=False, init=False, repr=False)
    _stop_event: Event = field(default_factory=Event, init=False, repr=False)
    _thread: Thread | None = field(default=None, init=False, repr=False)
    _failure: BaseException | None = field(default=None, init=False, repr=False)
    _state_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _tick_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _session_cursor: str | None = field(default=None, init=False, repr=False)

    @classmethod
    def compose_file_backed(
        cls,
        *,
        database_path: Path,
        factory: StandardProductCompositionFactoryPort,
        component_configuration: Mapping[str, object],
        expected_factory_id: str,
        expected_factory_digest: str,
        worker_bounds: StandardProductWorkerBounds = StandardProductWorkerBounds(),
    ) -> StandardProductLifecycle:
        require_identifier(expected_factory_id, field_name="expected_factory_id")
        require_digest(expected_factory_digest, field_name="expected_factory_digest")
        if (
            factory.factory_id != expected_factory_id
            or factory.factory_digest != expected_factory_digest
        ):
            raise StandardProductLifecycleError(
                "standard_component_factory_identity_drift",
                "Configured component factory differs from its exact identity",
            )
        path = database_path.resolve(strict=False)
        if not path.is_absolute() or not path.parent.is_dir():
            raise StandardProductLifecycleError(
                "standard_database_parent_missing",
                "Configured SQLite parent directory is absent",
            )
        provider = SQLiteConnectionProvider(
            SQLiteStoreConfiguration(database_path=str(path))
        )
        observation = provider.preflight()
        if not observation.ready_for_existing_database:
            raise StandardProductLifecycleError(
                "standard_file_store_preflight_failed",
                "Configured Store Adapter did not observe one existing regular database",
            )
        verifier: Any | None = None
        writer: StandardStoreWriterHandlePort | None = None
        try:
            try:
                verifier = provider.open_verifier()
            except SQLiteStoreAdapterError as exc:
                raise StandardProductLifecycleError(
                    "standard_store_verifier_activation_failed",
                    "Selected Store Adapter rejected read-only verifier activation",
                ) from exc
            try:
                composition = factory.build(
                    connection=verifier,
                    component_configuration=MappingProxyType(
                        dict(component_configuration)
                    ),
                )
            except StandardProductLifecycleError:
                raise
            except Exception as exc:
                raise StandardProductLifecycleError(
                    "standard_component_factory_build_failed",
                    "Configured Standard component factory failed closed",
                ) from exc
            preflight = preflight_standard_product_composition(
                database_path=path,
                composition=composition,
            )
            verifier.close()
            verifier = None
            try:
                writer = provider.open_writer(
                    composition.startup.deployment_proof.schema
                )
            except SQLiteStoreAdapterError as exc:
                raise StandardProductLifecycleError(
                    "standard_store_writer_activation_failed",
                    "Selected Store Adapter rejected writer activation",
                ) from exc
            try:
                app = build_standard_v2_host_app(
                    writer,
                    startup=composition.startup,
                    clock=composition.clock,
                    ids=composition.ids,
                    bootstrap_authority=composition.bootstrap_authority,
                    bootstrap_defaults_by_project=(
                        composition.bootstrap_defaults_by_project
                    ),
                    security_policy=composition.security_policy,
                    operational_selection=composition.operational_selection,
                )
            except Exception as exc:
                raise StandardProductLifecycleError(
                    "standard_host_composition_failed",
                    "Standard Host composition failed after exact preflight",
                ) from exc
            lifecycle = cls(
                database_path=path,
                store_writer=writer,
                records=app.state.openzyme_standard_runtime.store,
                composition=composition,
                runtime=app.state.openzyme_standard_runtime,
                app=app,
                preflight=preflight,
                worker_bounds=worker_bounds,
            )
            lifecycle._install_admission_gate()
            app.state.openzyme_standard_lifecycle = lifecycle
            return lifecycle
        except Exception:
            if verifier is not None:
                verifier.close()
            if writer is not None:
                writer.close()
            raise

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    def start(self) -> None:
        with self._state_lock:
            if self.state is not StandardProductLifecycleState.CREATED:
                raise StandardProductLifecycleError(
                    "standard_lifecycle_start_invalid",
                    "Standard lifecycle may start exactly once",
                )
            self._stop_event = Event()
            self._accepting = True
            self.state = StandardProductLifecycleState.RUNNING
            self._thread = Thread(
                target=self._worker_loop,
                name="openzyme-standard-bounded-workers",
                daemon=False,
            )
            self._thread.start()

    def tick_once(self) -> StandardProductWorkerTick:
        with self._state_lock:
            if self.state is not StandardProductLifecycleState.RUNNING:
                raise StandardProductLifecycleError(
                    "standard_lifecycle_not_running",
                    "Standard bounded workers require a running lifecycle",
                )
        with self._tick_lock:
            with self._state_lock:
                if self.state is not StandardProductLifecycleState.RUNNING:
                    raise StandardProductLifecycleError(
                        "standard_lifecycle_not_running",
                        "Standard lifecycle stopped before the bounded tick began",
                    )
            try:
                session_ids = self._discover_session_ids()
                provisioning = 0
                runtime = 0
                for session_id in session_ids:
                    provisioning += len(
                        self.runtime.provisioning_worker.tick(
                            session_id=session_id,
                            maximum=(
                                self.worker_bounds.maximum_provisioning_per_session
                            ),
                        )
                    )
                    runtime += len(
                        self.runtime.runtime_worker.tick(
                            session_id=session_id,
                            maximum=(
                                self.worker_bounds.maximum_runtime_commands_per_session
                            ),
                        )
                    )
                return StandardProductWorkerTick(
                    session_ids=session_ids,
                    provisioning_receipt_count=provisioning,
                    runtime_receipt_count=runtime,
                )
            except BaseException as exc:
                with self._state_lock:
                    self._failure = exc
                    self._accepting = False
                    self.state = StandardProductLifecycleState.FAILED
                self._stop_event.set()
                raise

    def _discover_session_ids(self) -> tuple[str, ...]:
        maximum = self.worker_bounds.maximum_sessions_per_tick
        session_ids = self.records.list_session_ids(
            after_session_id=self._session_cursor,
            max_items=maximum,
        )
        if session_ids:
            self._session_cursor = session_ids[-1]
        elif self._session_cursor is not None:
            # A visible empty tick is the explicit end-of-catalog boundary.
            # The next bounded tick restarts from the beginning; no hidden SQL
            # wraparound or unbounded scan occurs inside one worker occurrence.
            self._session_cursor = None
        return session_ids

    def stop(self) -> None:
        with self._state_lock:
            if self.state is StandardProductLifecycleState.STOPPED:
                return
            if self.state not in {
                StandardProductLifecycleState.RUNNING,
                StandardProductLifecycleState.FAILED,
                StandardProductLifecycleState.CREATED,
            }:
                raise StandardProductLifecycleError(
                    "standard_lifecycle_stop_invalid",
                    "Standard lifecycle is already stopping",
                )
            self._accepting = False
            self.state = StandardProductLifecycleState.STOPPING
            self._stop_event.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=self.worker_bounds.shutdown_timeout_seconds)
            if thread.is_alive():
                raise StandardProductLifecycleError(
                    "standard_worker_shutdown_timeout",
                    "Standard bounded workers did not retire before the deadline",
                )
        errors: list[BaseException] = []
        with self._tick_lock:
            for hook in self.composition.retirement_hooks:
                try:
                    hook()
                except BaseException as exc:  # preserve every explicit owner failure
                    errors.append(exc)
            try:
                self.store_writer.close()
            except BaseException as exc:
                errors.append(exc)
        with self._state_lock:
            self.state = StandardProductLifecycleState.STOPPED
        if errors:
            failure = StandardProductLifecycleError(
                "standard_product_retirement_failed",
                "One or more Standard product owners failed during retirement",
            )
            failure.owner_failures = tuple(errors)
            raise failure from ExceptionGroup(
                "Standard product retirement failures",
                errors,
            )

    def _worker_loop(self) -> None:
        try:
            while not self._stop_event.wait(
                self.worker_bounds.poll_interval_seconds
            ):
                self.tick_once()
        except BaseException as exc:
            with self._state_lock:
                self._failure = exc
                self._accepting = False
                self.state = StandardProductLifecycleState.FAILED
            self._stop_event.set()

    def _install_admission_gate(self) -> None:
        from starlette.responses import JSONResponse

        def not_accepting_response() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "schema_version": "openzyme_host_error@2",
                    "error": {
                        "code": "standard_lifecycle_not_accepting",
                        "message": (
                            "Standard product lifecycle is not accepting HTTP "
                            "admission"
                        ),
                        "mutation_applied": False,
                        "effect_certainty": "no_effect",
                        "fallback_performed": False,
                        "details": {
                            "lifecycle_state": self.state.value,
                        },
                    },
                },
            )

        @self.app.middleware("http")
        async def lifecycle_admission(request, call_next):  # noqa: ANN001, ANN202
            if not self._accepting:
                return not_accepting_response()
            return await call_next(request)


__all__ = [
    "StandardProductComposition",
    "StandardProductCompositionFactoryPort",
    "StandardProductLifecycle",
    "StandardProductLifecycleError",
    "StandardProductLifecycleState",
    "StandardProductPreflightReceipt",
    "StandardProductWorkerBounds",
    "StandardProductWorkerTick",
    "SystemUtcClock",
    "UuidIdGenerator",
    "preflight_standard_product_composition",
]
