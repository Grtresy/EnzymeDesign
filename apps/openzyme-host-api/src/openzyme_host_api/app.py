from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Callable

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openzyme_runtime import MissingLlmConfigurationError
from openzyme_runtime import LimiterRegistry
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import get_llm_debug_recorder
from openzyme_runtime import llm_debug_context

from .background_runtime import RuntimeSignalNotifier
from .background_runtime import V3BackgroundRuntimeService
from .tracing import host_request_trace_context
from .v3_service import V3EventStore
from .v3_service import V3HostApiService

from openzyme_core import CoreRepositories
from openzyme_core import EngineRegistry
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_engines import DeepResearchEngine
from openzyme_engines import ExecutionEngine
from openzyme_engines import ExecutionOutcome as V3ExecutionOutcome
from openzyme_engines import ExecutionStatusSnapshot as V3ExecutionStatusSnapshot
from openzyme_engines import NativeDeepResearchRunner
from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_engines import build_engine_registry
from openzyme_engines.execution import ExecutionArtifactRef as V3ExecutionArtifactRef
from openzyme_domain import RunStatus


class CreateV3SessionRequest(BaseModel):
    project_id: str
    objective: str
    title: str | None = None
    session_id: str | None = None


class PostV3MessageRequest(BaseModel):
    message: str | None = None
    task_id: str | None = None
    lane_id: str | None = None
    skill_keys: list[str] = []
    max_steps: int = 8


class DrainV3RuntimeRequest(BaseModel):
    max_signals: int = 3
    max_steps_per_agent: int = 8
    auto_enqueue_ready_tasks: bool = False


class ResolveV3ApprovalRequest(BaseModel):
    decision: str
    actor_ref: str = "user"


def _build_default_v3_repositories() -> CoreRepositories:
    connection = connect_v3_sqlite(":memory:")
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


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

    def get_execution_status(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> V3ExecutionStatusSnapshot:
        if hasattr(self.execution_adapter, "get_execution_status"):
            snapshot = self._run_limited(
                lambda: self.execution_adapter.get_execution_status(
                    run_id=run_id,
                    remote_run_dir=remote_run_dir,
                    job_id=job_id,
                )
            )
            return V3ExecutionStatusSnapshot(
                run_id=str(snapshot.run_id),
                status=snapshot.status,
                remote_run_dir=str(snapshot.remote_run_dir),
                raw_result=dict(snapshot.raw_result),
                job_id=None if snapshot.job_id is None else str(snapshot.job_id),
                exit_code=snapshot.exit_code,
            )
        outcome = self._outcomes_by_run_id.get(run_id)
        if outcome is None:
            return V3ExecutionStatusSnapshot(
                run_id=run_id,
                status=RunStatus.FAILED,
                remote_run_dir=remote_run_dir,
                raw_result={
                    "error": "execution adapter does not expose status polling"
                },
                job_id=job_id,
            )
        return V3ExecutionStatusSnapshot(
            run_id=outcome.run_id,
            status=outcome.status,
            remote_run_dir=outcome.remote_run_dir,
            raw_result=outcome.raw_result,
            job_id=outcome.job_id,
            exit_code=outcome.exit_code,
        )

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        runspec: dict[str, Any],
        job_id: str | None = None,
    ) -> V3ExecutionOutcome:
        if hasattr(self.execution_adapter, "fetch_execution_artifacts"):
            outcome = self._convert_outcome(
                self._run_limited(
                    lambda: self.execution_adapter.fetch_execution_artifacts(
                        run_id=run_id,
                        remote_run_dir=remote_run_dir,
                        runspec=runspec,
                        job_id=job_id,
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
                remote_run_dir=remote_run_dir,
                raw_result={
                    "error": "execution adapter does not expose artifact fetch"
                },
                artifacts=(),
                job_id=job_id,
            )
        return outcome

    def cancel_execution(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> V3ExecutionOutcome:
        if hasattr(self.execution_adapter, "cancel_execution"):
            return self._convert_outcome(
                self._run_limited(
                    lambda: self.execution_adapter.cancel_execution(
                        run_id=run_id,
                        remote_run_dir=remote_run_dir,
                        job_id=job_id,
                    )
                )
            )
        return V3ExecutionOutcome(
            run_id=run_id,
            status=RunStatus.FAILED,
            execution_mode="unknown",
            remote_run_dir=remote_run_dir,
            raw_result={
                "status": "unsupported",
                "error_code": "cancel_execution_unsupported",
                "error": "execution adapter does not expose cancel",
            },
            artifacts=(),
            job_id=job_id,
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
        return V3ExecutionOutcome(
            run_id=str(outcome.run_id),
            status=outcome.status,
            execution_mode=str(outcome.execution_mode),
            remote_run_dir=str(outcome.remote_run_dir),
            raw_result=dict(outcome.raw_result),
            artifacts=artifacts,
            job_id=None
            if getattr(outcome, "job_id", None) is None
            else str(outcome.job_id),
            exit_code=getattr(outcome, "exit_code", None),
        )

    def _run_limited(self, operation: Callable[[], Any]) -> Any:
        if self.limiter_registry is None:
            return operation()
        return self.limiter_registry.sync_limiter("execution_provider").run(operation)


@dataclass(frozen=True, slots=True)
class HostApiDependencies:
    foundation: RuntimeFoundation
    v3_repositories: CoreRepositories = field(
        default_factory=_build_default_v3_repositories
    )
    v3_event_store: V3EventStore = field(default_factory=V3EventStore)
    v3_signal_notifier: RuntimeSignalNotifier = field(
        default_factory=RuntimeSignalNotifier
    )
    v3_background_runtime_enabled: bool | None = None

    def build_v3_service(self) -> V3HostApiService:
        return V3HostApiService(
            repositories=self.v3_repositories,
            event_store=self.v3_event_store,
            engine_registry=self.build_v3_engine_registry(),
            model_factory=self.foundation.model_factory,
            bio_research_service=self.foundation.bio_research_service,
            research_adapter=self.foundation.research_adapter,
            signal_notifier=self.v3_signal_notifier,
            scheduler_limits={}
            if self.foundation.settings is None
            else dict(self.foundation.settings.limits.provider_limits),
        )

    def build_v3_engine_registry(self) -> EngineRegistry:
        return build_engine_registry(
            DeepResearchEngine(
                self.v3_repositories,
                NativeDeepResearchRunner(
                    repositories=self.v3_repositories,
                    research_adapter=self.foundation.research_adapter,
                    research_tool_provider=self.foundation.research_tool_provider,
                    model_factory=self.foundation.model_factory,
                    limiter_registry=self.foundation.limiter_registry,
                    settings=self.foundation.settings,
                ),
            ),
            ExecutionEngine(
                self.v3_repositories,
                V3ExecutionRunnerAdapter(
                    self.foundation.execution_adapter,
                    self.foundation.limiter_registry,
                ),
                sandbox_runner=PodmanPipelineSandboxRunner(),
            ),
        )


def _as_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, MissingLlmConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _sse_encode(event: dict[str, Any]) -> str:
    payload = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return f"event: {event['event_type']}\ndata: {payload}\n\n"


def create_app(
    dependencies: HostApiDependencies,
    *,
    ui_dist_dir: Path | None = None,
) -> FastAPI:
    background_runtime = _build_background_runtime_service(dependencies)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        app.state.v3_background_runtime = background_runtime
        background_runtime.start()
        try:
            yield
        finally:
            await background_runtime.stop()

    app = FastAPI(title="OpenZyme Host API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def add_trace_context(request, call_next):  # type: ignore[no-untyped-def]
        with host_request_trace_context(method=request.method, path=request.url.path):
            return await call_next(request)

    @app.post("/v3/sessions")
    def create_v3_session(request: CreateV3SessionRequest) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.create_session(
                project_id=request.project_id,
                objective=request.objective,
                title=request.title,
                session_id=request.session_id,
            )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/v3/projects/{project_id}/sessions")
    def list_v3_project_sessions(project_id: str) -> list[dict[str, Any]]:
        service = dependencies.build_v3_service()
        try:
            return service.list_sessions(project_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/v3/sessions/{session_id}")
    def get_v3_session(session_id: str) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            workspace = service.workspace(session_id)
            return {"session": workspace["session"], "workspace": workspace}
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/sessions/{session_id}/messages")
    def post_v3_message(
        session_id: str, request: PostV3MessageRequest
    ) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            with llm_debug_context(
                request_path=f"/v3/sessions/{session_id}/messages",
                session_id=session_id,
                task_id=request.task_id,
                lane_id=request.lane_id,
                actor="user",
            ):
                return service.post_message(
                    session_id=session_id,
                    message=request.message,
                    task_id=request.task_id,
                    lane_id=request.lane_id,
                    skill_keys=tuple(request.skill_keys),
                    max_steps=request.max_steps,
                ).to_dict()
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/sessions/{session_id}/runtime/drain")
    def drain_v3_runtime(
        session_id: str, request: DrainV3RuntimeRequest
    ) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            with llm_debug_context(
                request_path=f"/v3/sessions/{session_id}/runtime/drain",
                session_id=session_id,
                actor="scheduler",
            ):
                return service.drain_runtime(
                    session_id=session_id,
                    max_signals=request.max_signals,
                    max_steps_per_agent=request.max_steps_per_agent,
                    auto_enqueue_ready_tasks=request.auto_enqueue_ready_tasks,
                ).to_dict()
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/v3/sessions/{session_id}/workspace")
    def get_v3_workspace(session_id: str) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.workspace(session_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/v3/sessions/{session_id}/events")
    def stream_v3_events(
        session_id: str, replay: bool = True, follow: bool = False
    ) -> StreamingResponse:
        service = dependencies.build_v3_service()
        try:
            service.workspace(session_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

        async def event_stream() -> Any:
            next_index = 0
            if replay:
                existing = service.events(session_id)
                for event in existing:
                    yield _sse_encode(event)
                next_index = len(existing)
            else:
                next_index = len(service.events(session_id))

            if not follow:
                return

            while True:
                current = service.events(session_id)
                while next_index < len(current):
                    yield _sse_encode(current[next_index])
                    next_index += 1
                await asyncio.sleep(0.5)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/v3/tasks")
    def create_v3_task(payload: dict[str, Any]) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.create_task(payload)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.patch("/v3/tasks/{task_id}")
    def update_v3_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.update_task(task_id, payload)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/lanes")
    def create_v3_lane(payload: dict[str, Any]) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.create_lane(payload)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/lanes/{lane_id}/claim")
    def claim_v3_lane(lane_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.claim_lane(
                lane_id, claimed_ref=str(payload.get("claimed_ref") or "user")
            )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/lanes/{lane_id}/keep")
    def keep_v3_lane(lane_id: str) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.keep_lane(lane_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/lanes/{lane_id}/remove")
    def remove_v3_lane(lane_id: str) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            return service.remove_lane(lane_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/approvals/{approval_id}/resolve")
    def resolve_v3_approval(
        approval_id: str, request: ResolveV3ApprovalRequest
    ) -> dict[str, Any]:
        service = dependencies.build_v3_service()
        try:
            with llm_debug_context(
                request_path=f"/v3/approvals/{approval_id}/resolve",
                approval_id=approval_id,
                actor=request.actor_ref,
            ):
                return service.resolve_approval(
                    approval_id,
                    decision=request.decision,
                    actor_ref=request.actor_ref,
                ).to_dict()
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
    build_service = getattr(dependencies, "build_v3_service", None)
    if build_service is None:
        def build_service() -> V3HostApiService:
            raise RuntimeError("V3 service dependencies are not configured")

    return V3BackgroundRuntimeService(
        build_service=build_service,
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
