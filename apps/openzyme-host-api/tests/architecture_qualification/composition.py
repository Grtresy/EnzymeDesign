from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from types import TracebackType
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import DurableRouteObservationKind
from openzyme_domain import ArtifactKind
from openzyme_domain import SessionArtifactRecord
from openzyme_host_api.app import HostApiDependencies
from openzyme_host_api.app import create_app
from openzyme_host_api.background_runtime import RuntimeSignalNotifier
from openzyme_host_api.background_runtime import V3DurableWorkSupervisor
from openzyme_host_api.durable_routes import HostProviderControlledOperationRouteAdapter
from openzyme_host_api.sandbox_host_gateway import ExecutionEngineSandboxHostGateway
from openzyme_engines.execution import BioArtifactDraft
from openzyme_engines.execution import BioSdkResult
from openzyme_runtime import ControlledOperationOwnerPolicy
from openzyme_runtime import ExecutionSettings
from openzyme_runtime import HostApiSettings
from openzyme_runtime import HostCliSettings
from openzyme_runtime import LiveLlmTestSettings
from openzyme_runtime import LimiterRegistry
from openzyme_runtime import LlmSettings
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import ReliabilityRefactorSettings
from openzyme_runtime import ReliabilityShadowObserver
from openzyme_runtime import ResearchSettings
from openzyme_runtime import RuntimeDrainContract
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import TestSettings
from openzyme_runtime import TracingSettings
from openzyme_runtime import V3BackgroundRuntimeSettings
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider

from .external_ports import ControlledExternalPort
from .external_ports import ExternalEffectLedger
from .external_ports import QUALIFICATION_FIXTURE_MARKER
from .external_ports import QualificationDurableRouteAdapter


@dataclass(frozen=True, slots=True)
class DeniedExecutionAdapter:
    port: ControlledExternalPort
    qualification_fixture_non_cutover: bool = True

    def submit_execution(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> object:
        return self.port.invoke(
            "submit_execution",
            {"payload": payload, "session_id": session_id},
        )


@dataclass(frozen=True, slots=True)
class DeniedBioAdapter:
    port: ControlledExternalPort
    api_version: str = QUALIFICATION_FIXTURE_MARKER
    qualification_fixture_non_cutover: bool = True

    def __getattr__(self, name: str) -> Any:
        def invoke(**kwargs: object) -> BioSdkResult:
            request = dict(kwargs)
            hmm_artifact = request.get("hmm_artifact")
            if hmm_artifact is not None:
                if not isinstance(hmm_artifact, SessionArtifactRecord):
                    raise ValueError("controlled HMM request artifact is invalid")
                metadata = dict(hmm_artifact.metadata or {})
                request["hmm_artifact"] = {
                    "artifact_digest": str(
                        metadata.get("sealed_digest")
                        or metadata.get("content_digest")
                        or metadata.get("tree_digest")
                        or metadata.get("source_tree_digest")
                        or ""
                    ),
                    "artifact_id": hmm_artifact.artifact_id,
                    "kind": hmm_artifact.kind.value,
                    "relative_path": hmm_artifact.relative_path,
                }
            raw = self.port.invoke(name, request)
            expected_fields = {
                "api_version",
                "artifacts",
                "operation",
                "provider",
                "provider_observation",
                "summary",
                "warnings",
            }
            if set(raw) != expected_fields:
                raise ValueError("controlled bio result is not a closed SDK result")
            artifacts = raw["artifacts"]
            warnings = raw["warnings"]
            if not isinstance(artifacts, list) or not isinstance(warnings, list):
                raise ValueError("controlled bio result arrays are invalid")
            drafts: list[BioArtifactDraft] = []
            artifact_fields = {
                "content",
                "format",
                "kind",
                "metadata",
                "relative_path",
                "title",
            }
            for item in artifacts:
                if not isinstance(item, dict) or set(item) != artifact_fields:
                    raise ValueError("controlled bio artifact is not closed")
                metadata = item["metadata"]
                if not isinstance(metadata, dict):
                    raise ValueError("controlled bio artifact metadata is invalid")
                drafts.append(
                    BioArtifactDraft(
                        relative_path=str(item["relative_path"]),
                        kind=ArtifactKind(str(item["kind"])),
                        title=str(item["title"]),
                        content=str(item["content"]),
                        format=str(item["format"]),
                        metadata=dict(metadata),
                    )
                )
            if any(not isinstance(item, dict) for item in warnings):
                raise ValueError("controlled bio warnings are invalid")
            summary = raw["summary"]
            provider_observation = raw["provider_observation"]
            if not isinstance(summary, dict) or (
                provider_observation is not None
                and not isinstance(provider_observation, dict)
            ):
                raise ValueError("controlled bio result objects are invalid")
            return BioSdkResult(
                provider=str(raw["provider"]),
                operation=str(raw["operation"]),
                summary=dict(summary),
                artifacts=tuple(drafts),
                warnings=tuple(dict(item) for item in warnings),
                provider_observation=(
                    None
                    if provider_observation is None
                    else dict(provider_observation)
                ),
                api_version=(
                    None
                    if raw["api_version"] is None
                    else str(raw["api_version"])
                ),
            )

        return invoke


@dataclass(slots=True)
class QualificationLostCallbackProviderRouteAdapter:
    """Delegate to the real provider route, then lose one opted-in callback."""

    inner: HostProviderControlledOperationRouteAdapter
    qualification_fixture_non_cutover: bool = True
    _lost_execution_ids: set[str] = field(default_factory=set, init=False)

    @property
    def route_policy_id(self) -> str:
        return self.inner.route_policy_id

    @property
    def selected_backend(self) -> str:
        return self.inner.selected_backend

    @property
    def adapter_policy_id(self) -> str:
        return self.inner.adapter_policy_id

    def prepare_dispatch(self, execution, request):  # type: ignore[no-untyped-def]
        return self.inner.prepare_dispatch(execution, request)

    def dispatch(self, execution, request):  # type: ignore[no-untyped-def]
        observation = self.inner.dispatch(execution, request)
        if (
            request.request_envelope.get("qualification_fault")
            == "lost_callback_after_materialization"
            and observation.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
            and execution.execution_id not in self._lost_execution_ids
        ):
            self._lost_execution_ids.add(execution.execution_id)
            raise RuntimeError("qualification lost callback after sealed materialization")
        return observation

    def poll(self, execution, request):  # type: ignore[no-untyped-def]
        return self.inner.poll(execution, request)

    def reconcile(self, execution, request):  # type: ignore[no-untyped-def]
        return self.inner.reconcile(execution, request)

    def materialize(self, execution, request):  # type: ignore[no-untyped-def]
        return self.inner.materialize(execution, request)


@dataclass(frozen=True, slots=True)
class DeniedPipelineSandboxRunner:
    port: ControlledExternalPort
    qualification_fixture_non_cutover: bool = True

    def preflight(self) -> object:
        return self.port.invoke("preflight", {})

    def run_pipeline(self, **kwargs: object) -> object:
        return self.port.invoke("run_pipeline", kwargs)


def _qualification_settings() -> OpenZymeSettings:
    return OpenZymeSettings(
        llm=LlmSettings(
            api_key=None,
            model="qualification-disabled",
            base_url="https://qualification.invalid/v1",
            extra_body=None,
            default_headers=None,
            use_responses_api=False,
            max_tokens=None,
            timeout=1.0,
            max_retries=0,
            temperature=0.0,
            structured_output_method="function_calling",
            structured_output_retry_backoff_seconds=0.0,
            purpose_policies={},
        ),
        research=ResearchSettings(
            max_units=1,
            allow_clarification=False,
            max_research_iterations=1,
            max_react_tool_calls=1,
            max_concurrent_research_units=1,
            tavily_api_key=None,
            tavily_max_results=1,
            tavily_topic="general",
            mcp_enabled=False,
            mcp_tool_allowlist=(),
            tavily_timeout_seconds=1.0,
            pubmed_email=None,
            pubmed_tool="openzyme-qualification",
            pubmed_api_key=None,
            semantic_scholar_api_key=None,
            provider_timeout_seconds=1.0,
            provider_max_attempts=1,
        ),
        tracing=TracingSettings(
            enabled=False,
            project_name="openzyme-architecture-qualification",
        ),
        host_cli=HostCliSettings(
            base_url="http://127.0.0.1:8000",
            project_id=None,
            output_format="json",
        ),
        host_api=HostApiSettings(
            bind_host="127.0.0.1",
            bind_port=8000,
            deployment_profile="local-dev",
            debug_enabled=False,
        ),
        v3_background_runtime=V3BackgroundRuntimeSettings(
            enabled=False,
            poll_interval_seconds=0.05,
            max_signals_per_tick=1,
            max_steps_per_agent=1,
            shutdown_timeout_seconds=1.0,
        ),
        execution=ExecutionSettings(
            backend="disabled",
            hpc_runner_config=None,
        ),
        test=TestSettings(
            enable_live_llm=False,
            enable_live_tavily=False,
            enable_live_hpc=False,
            enable_live_e2e=False,
            enable_quality_eval=False,
            upload_langsmith=False,
            live_llm=LiveLlmTestSettings(
                max_tokens=None,
                timeout=None,
                max_retries=None,
                structured_output_method=None,
                structured_output_retry_backoff_seconds=None,
            ),
        ),
        reliability=ReliabilityRefactorSettings(
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.DURABLE_ONLY_V1
            ),
            runtime_drain_contract=RuntimeDrainContract.COMMAND_V1,
        ),
    )


def _qualification_foundation(
    *,
    runner_port: ControlledExternalPort,
) -> RuntimeFoundation:
    settings = _qualification_settings()
    limiter_registry = LimiterRegistry(dict(settings.limits.provider_limits))
    catalog = RepoBackedHpcCatalogProvider()
    return RuntimeFoundation(
        execution_adapter=DeniedExecutionAdapter(runner_port),
        hpc_catalog_provider=catalog,
        hpc_execution_registry=DefaultHpcExecutionRegistry(catalog),
        research_adapter=None,
        research_tool_provider=None,
        bio_research_service=None,
        model_factory=None,
        limiter_registry=limiter_registry,
        settings=settings,
        reliability_shadow_observer=ReliabilityShadowObserver(settings.reliability),
    )


@dataclass(frozen=True, slots=True)
class QualificationRoots:
    scenario_root: Path
    database_path: Path
    artifact_root: Path
    blob_root: Path
    sandbox_root: Path
    workspace_root: Path

    @classmethod
    def create(cls, scenario_root: Path) -> "QualificationRoots":
        root = scenario_root.resolve()
        root.mkdir(parents=True, exist_ok=False)
        artifact_root = root / "artifacts"
        blob_root = root / "blobs"
        sandbox_root = root / "sandboxes"
        workspace_root = root / "workspace-projections"
        for directory in (
            artifact_root,
            blob_root,
            sandbox_root,
            workspace_root,
        ):
            directory.mkdir()
        return cls(
            scenario_root=root,
            database_path=root / "control-plane.sqlite3",
            artifact_root=artifact_root,
            blob_root=blob_root,
            sandbox_root=sandbox_root,
            workspace_root=workspace_root,
        )

    @classmethod
    def open_existing(cls, scenario_root: Path) -> "QualificationRoots":
        candidate = scenario_root.absolute()
        if candidate.is_symlink():
            raise RuntimeError("qualification scenario root must not be a symlink")
        root = candidate.resolve(strict=True)
        directories = {
            "artifact_root": root / "artifacts",
            "blob_root": root / "blobs",
            "sandbox_root": root / "sandboxes",
            "workspace_root": root / "workspace-projections",
        }
        for label, directory in directories.items():
            if directory.is_symlink() or not directory.is_dir():
                raise RuntimeError(
                    f"existing qualification {label} is absent or unsafe"
                )
        database_path = root / "control-plane.sqlite3"
        if database_path.is_symlink() or not database_path.is_file():
            raise RuntimeError("existing qualification SQLite database is absent")
        return cls(
            scenario_root=root,
            database_path=database_path,
            **directories,
        )


@dataclass(slots=True)
class ProductionComposition:
    roots: QualificationRoots
    generation: int
    repository_provider: SQLiteRepositoryProvider
    external_effect_ledger: ExternalEffectLedger
    external_ports: dict[str, ControlledExternalPort]
    dependencies: HostApiDependencies
    app: FastAPI
    _test_client_owner: TestClient | None = None
    client: TestClient | None = None
    retired: bool = False

    def __enter__(self) -> "ProductionComposition":
        if self.retired or self._test_client_owner is not None:
            raise RuntimeError("production composition generation is not enterable")
        owner = TestClient(self.app)
        self._test_client_owner = owner
        self.client = owner.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        owner = self._test_client_owner
        if owner is None:
            raise RuntimeError("production composition generation was not entered")
        try:
            return bool(owner.__exit__(exc_type, exc, traceback))
        finally:
            self.client = None
            self._test_client_owner = None
            self.retired = True

    def stop_durable_supervisor(self) -> None:
        owner = self._test_client_owner
        if owner is None or owner.portal is None:
            raise RuntimeError("production composition is not entered")
        owner.portal.call(self.durable_supervisor.stop)

    def run_durable_tick(self) -> tuple[dict[str, object], ...]:
        owner = self._test_client_owner
        if owner is None or owner.portal is None:
            raise RuntimeError("production composition is not entered")
        result = owner.portal.call(self.durable_supervisor.run_tick)
        return tuple(dict(item) for item in result)

    def build_manual_durable_supervisor(self) -> V3DurableWorkSupervisor:
        """Build the production supervisor class over the app-owned worker factory."""

        app_supervisor = self.durable_supervisor
        return V3DurableWorkSupervisor(
            worker_factory=app_supervisor.worker_factory,
            notifier=RuntimeSignalNotifier(wake_delay_seconds=0.01),
            enabled=True,
            poll_interval_seconds=app_supervisor.poll_interval_seconds,
            max_concurrency=app_supervisor.max_concurrency,
            shutdown_timeout_seconds=app_supervisor.shutdown_timeout_seconds,
            worker_id_prefix="architecture-qualification:manual-durable-work",
        )

    def run_manual_durable_tick(
        self,
        supervisor: V3DurableWorkSupervisor,
    ) -> tuple[dict[str, object], ...]:
        owner = self._test_client_owner
        if owner is None or owner.portal is None:
            raise RuntimeError("production composition is not entered")
        result = owner.portal.call(supervisor.run_tick)
        return tuple(dict(item) for item in result)

    def stop_manual_durable_supervisor(
        self,
        supervisor: V3DurableWorkSupervisor,
    ) -> None:
        owner = self._test_client_owner
        if owner is None or owner.portal is None:
            raise RuntimeError("production composition is not entered")
        owner.portal.call(supervisor.stop)

    @property
    def durable_supervisor(self) -> object:
        return self.app.state.v3_durable_work

    @property
    def background_runtime(self) -> object:
        return self.app.state.v3_background_runtime


@dataclass(slots=True)
class ProductionCompositionFactory:
    roots: QualificationRoots
    external_effect_ledger: ExternalEffectLedger
    external_ports: dict[str, ControlledExternalPort]
    _next_generation: int = 1

    @classmethod
    def create(cls, scenario_root: Path) -> "ProductionCompositionFactory":
        return cls._from_roots(QualificationRoots.create(scenario_root))

    @classmethod
    def open_existing(cls, scenario_root: Path) -> "ProductionCompositionFactory":
        return cls._from_roots(QualificationRoots.open_existing(scenario_root))

    @classmethod
    def _from_roots(
        cls,
        roots: QualificationRoots,
    ) -> "ProductionCompositionFactory":
        ledger = ExternalEffectLedger()
        return cls(
            roots=roots,
            external_effect_ledger=ledger,
            external_ports={
                port_id: ControlledExternalPort(port_id=port_id, ledger=ledger)
                for port_id in (
                    "bio.provider_http",
                    "runner.hpc",
                    "sandbox.container_process",
                )
            },
        )

    def build(self) -> ProductionComposition:
        provider = SQLiteRepositoryProvider(str(self.roots.database_path))
        runner_port = self.external_ports["runner.hpc"]
        bio_port = self.external_ports["bio.provider_http"]
        sandbox_port = self.external_ports["sandbox.container_process"]
        dependencies = HostApiDependencies(
            foundation=_qualification_foundation(runner_port=runner_port),
            v3_repository_provider=provider,
            v3_background_runtime_enabled=False,
            v3_durable_work_enabled=True,
            v3_durable_route_adapters={
                "qualification.provider:v1": QualificationDurableRouteAdapter(
                    port=bio_port,
                    route_policy_id="qualification.provider:v1",
                    selected_backend="qualification_provider",
                    adapter_policy_id="qualification_provider_adapter:v1",
                ),
                "qualification.runner:v1": QualificationDurableRouteAdapter(
                    port=runner_port,
                    route_policy_id="qualification.runner:v1",
                    selected_backend="qualification_runner",
                    adapter_policy_id="qualification_runner_adapter:v1",
                ),
            },
            v3_pipeline_sandbox_runner=DeniedPipelineSandboxRunner(sandbox_port),
            v3_bio_adapter=DeniedBioAdapter(bio_port),
            v3_allow_bio_fixture_adapter=False,
            v3_sandbox_workspace_root=self.roots.sandbox_root,
            v3_artifact_blob_root=self.roots.blob_root,
        )
        for provider_route_id in (
            "bio.hmmer_search.provider:v1",
            "bio.ncbi_fetch_proteins.provider:v1",
        ):
            dependencies.v3_durable_route_adapters[provider_route_id] = (
                QualificationLostCallbackProviderRouteAdapter(
                    HostProviderControlledOperationRouteAdapter(
                        route_policy_id=provider_route_id,
                        repository_scope_factory=dependencies.v3_repository_scope,
                        engine_registry_factory=(
                            lambda repositories: dependencies.build_v3_engine_registry(
                                repositories
                            )
                        ),
                    )
                )
            )
        generation = self._next_generation
        self._next_generation += 1
        return ProductionComposition(
            roots=self.roots,
            generation=generation,
            repository_provider=provider,
            external_effect_ledger=self.external_effect_ledger,
            external_ports=self.external_ports,
            dependencies=dependencies,
            app=create_app(dependencies),
        )

    def restart(self, retired: ProductionComposition) -> ProductionComposition:
        if not retired.retired:
            raise RuntimeError("previous production composition is still active")
        if retired.roots != self.roots:
            raise RuntimeError("restart attempted to change persistent roots")
        restarted = self.build()
        if restarted.dependencies is retired.dependencies:
            raise AssertionError("restart reused HostApiDependencies")
        if restarted.repository_provider is retired.repository_provider:
            raise AssertionError("restart reused SQLiteRepositoryProvider")
        return restarted


def assert_production_owner_shape(composition: ProductionComposition) -> None:
    dependencies = composition.dependencies
    if dependencies.v3_legacy_repositories_for_tests is not None:
        raise AssertionError("qualification used legacy repositories")
    if dependencies.v3_repository_provider is not composition.repository_provider:
        raise AssertionError("qualification lost the explicit repository provider")
    if dependencies.v3_sandbox_workspace_root != composition.roots.sandbox_root:
        raise AssertionError("qualification sandbox root drifted")
    if dependencies.v3_artifact_blob_root != composition.roots.blob_root:
        raise AssertionError("qualification blob root drifted")
    if Path(composition.repository_provider.database_path).resolve() != (
        composition.roots.database_path
    ):
        raise AssertionError("qualification database path drifted")
    if composition.repository_provider.uri:
        raise AssertionError("qualification used a URI/shared-memory repository")
    foundation = dependencies.foundation
    if foundation.model_factory is not None:
        raise AssertionError("qualification installed a model/eval factory")
    if foundation.research_adapter is not None:
        raise AssertionError("qualification installed a research/eval adapter")
    if foundation.research_tool_provider is not None:
        raise AssertionError("qualification installed fixture scientific tools")
    if foundation.bio_research_service is not None:
        raise AssertionError("qualification installed fixture scientific evidence")
    controlled_boundaries = (
        foundation.execution_adapter,
        dependencies.v3_bio_adapter,
        dependencies.v3_pipeline_sandbox_runner,
    )
    for boundary in controlled_boundaries:
        if not bool(getattr(boundary, "qualification_fixture_non_cutover", False)):
            raise AssertionError("qualification external boundary lost fixture marker")
        if "deterministic" in type(boundary).__name__.lower():
            raise AssertionError("qualification used an eval deterministic adapter")
    with dependencies.v3_service_scope(mode="read") as service:
        engine_registry = service.engine_registry
        if engine_registry is None:
            raise AssertionError("real engine registry is absent")
        if engine_registry.require("execution").descriptor.engine_name != "execution":
            raise AssertionError("real execution engine is absent")
        if engine_registry.require("deep_research").descriptor.engine_name != (
            "deep_research"
        ):
            raise AssertionError("real research engine is absent")
        binding_factory = service.sandbox_host_binding_factory
        if binding_factory is None:
            raise AssertionError("sandbox Host binding factory is absent")
        binding = binding_factory(engine_registry, None)
        if not isinstance(binding.gateway, ExecutionEngineSandboxHostGateway):
            raise AssertionError("real sandbox Host gateway is absent")
    coordinator = composition.durable_supervisor.worker_factory(
        "architecture-qualification:owner-inspection"
    )
    worker_types = {type(worker).__name__ for worker in coordinator.workers}
    if worker_types != {
        "ContinuationDeliveryWorker",
        "ControlledOperationExecutionWorker",
        "RuntimeCommandWorker",
    }:
        raise AssertionError(f"durable worker composition drifted: {worker_types}")
    if foundation.settings is None:
        raise AssertionError("qualification foundation lacks production settings")
    if (
        foundation.settings.reliability.controlled_operation_owner_policy
        is not ControlledOperationOwnerPolicy.DURABLE_ONLY_V1
    ):
        raise AssertionError("qualification did not enable durable owner composition")


__all__ = [
    "DeniedBioAdapter",
    "DeniedExecutionAdapter",
    "DeniedPipelineSandboxRunner",
    "ProductionComposition",
    "ProductionCompositionFactory",
    "QualificationRoots",
    "QualificationLostCallbackProviderRouteAdapter",
    "assert_production_owner_shape",
]
