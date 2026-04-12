from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import RuntimeFoundation

from .projections import HostProjectionLoader
from .projections import WorkflowEventProjector
from .service import HostApiService
from .tracing import host_request_trace_context


GraphBuilder = Callable[[Any], Any]


class CreateEpisodeRequest(BaseModel):
    project_id: str
    objective: str


class ResumeEpisodeRequest(BaseModel):
    episode_id: str
    resume_payload: Any


class ResolveApprovalRequest(BaseModel):
    episode_id: str
    approval_id: str
    decision: str


@dataclass(frozen=True, slots=True)
class HostApiDependencies:
    foundation: RuntimeFoundation
    graph_builder: GraphBuilder = build_v2_supervisor_graph

    def build_runtime(self) -> GraphRuntimeFacade:
        return GraphRuntimeFacade(self.foundation)

    def build_projection_loader(self) -> HostProjectionLoader:
        return HostProjectionLoader(
            runtime=self.build_runtime(),
            graph_builder=self.graph_builder,
        )

    def build_service(self) -> HostApiService:
        runtime = self.build_runtime()
        return HostApiService(
            runtime=runtime,
            projection_loader=HostProjectionLoader(runtime=runtime, graph_builder=self.graph_builder),
            event_projector=WorkflowEventProjector(),
            graph_builder=self.graph_builder,
        )


def _as_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _sse_encode(event: dict[str, Any]) -> str:
    payload = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return f"event: {event['event_type']}\ndata: {payload}\n\n"


def create_app(
    dependencies: HostApiDependencies,
    *,
    ui_dist_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenZyme Host API", version="0.1.0")

    @app.middleware("http")
    async def add_trace_context(request, call_next):  # type: ignore[no-untyped-def]
        with host_request_trace_context(method=request.method, path=request.url.path):
            return await call_next(request)

    @app.get("/episodes/{episode_id}/workspace")
    def get_episode_workspace(episode_id: str) -> dict[str, Any]:
        loader = dependencies.build_projection_loader()
        try:
            return loader.load_episode_workspace(episode_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/episodes/{episode_id}/workflow")
    def get_episode_workflow(episode_id: str) -> dict[str, Any]:
        loader = dependencies.build_projection_loader()
        try:
            return loader.load_workflow_projection(episode_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/episodes/{episode_id}/pending-actions")
    def get_pending_actions(episode_id: str) -> list[dict[str, Any]]:
        loader = dependencies.build_projection_loader()
        try:
            return loader.load_pending_actions(episode_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/episodes/{episode_id}/runs")
    def get_runs(episode_id: str) -> list[dict[str, Any]]:
        loader = dependencies.build_projection_loader()
        try:
            return loader.load_run_projection(episode_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/episodes/{episode_id}/artifacts")
    def get_artifacts(episode_id: str) -> list[dict[str, Any]]:
        loader = dependencies.build_projection_loader()
        try:
            return loader.load_artifact_projection(episode_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/episodes/{episode_id}/reports")
    def get_reports(episode_id: str) -> list[dict[str, Any]]:
        loader = dependencies.build_projection_loader()
        try:
            report = loader.load_report_projection(episode_id)
            return [] if report is None else [report]
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/projects")
    def get_projects() -> list[dict[str, Any]]:
        loader = dependencies.build_projection_loader()
        try:
            return loader.list_projects()
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.get("/projects/{project_id}/episodes")
    def get_project_episodes(project_id: str) -> list[dict[str, Any]]:
        loader = dependencies.build_projection_loader()
        try:
            return loader.list_project_episodes(project_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/commands/create_episode")
    def create_episode(request: CreateEpisodeRequest) -> dict[str, Any]:
        service = dependencies.build_service()
        try:
            result = service.create_episode(request.project_id, request.objective)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc
        return {
            "episode_id": result.workspace["episode_id"],
            "workspace": result.workspace,
            "events": result.events,
        }

    @app.post("/commands/resume_episode")
    def resume_episode(request: ResumeEpisodeRequest) -> dict[str, Any]:
        service = dependencies.build_service()
        try:
            result = service.resume_episode(request.episode_id, request.resume_payload)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc
        return {
            "episode_id": result.workspace["episode_id"],
            "workspace": result.workspace,
            "events": result.events,
        }

    @app.post("/commands/resolve_approval")
    def resolve_approval(request: ResolveApprovalRequest) -> dict[str, Any]:
        service = dependencies.build_service()
        try:
            result = service.resolve_approval(
                request.episode_id,
                request.approval_id,
                request.decision,
            )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc
        return {
            "episode_id": result.workspace["episode_id"],
            "workspace": result.workspace,
            "events": result.events,
        }

    @app.get("/episodes/{episode_id}/stream")
    def stream_episode_events(episode_id: str, replay: bool = True) -> StreamingResponse:
        loader = dependencies.build_projection_loader()
        projector = WorkflowEventProjector()
        try:
            workspace = loader.load_episode_workspace(episode_id)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

        def event_stream() -> Any:
            if replay:
                for event in projector.project_snapshot_events(workspace):
                    yield _sse_encode(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    if ui_dist_dir is not None and ui_dist_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_dist_dir), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

    return app
