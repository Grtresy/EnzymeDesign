from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
import tempfile
from typing import Any
from typing import Callable
from typing import Iterator
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Header
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import ConfigDict

from openzyme_runtime import MissingLlmConfigurationError
from openzyme_runtime import LimiterRegistry
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import get_llm_debug_recorder
from openzyme_runtime import llm_debug_context

from .background_runtime import RuntimeSignalNotifier
from .background_runtime import V3BackgroundRuntimeService
from .tracing import host_request_trace_context
from .security import HostAuthenticationError
from .security import HostPrincipal
from .security import HostSecurityPolicy
from .v3_service import V3EventStore
from .v3_service import V3HostApiService

from openzyme_core import CoreRepositories
from openzyme_core import CommandIdempotencyConflictError
from openzyme_core import CommandReceiptRecord
from openzyme_core import EngineRegistry
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import SessionAccessRecord
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
from openzyme_domain import SessionRuntimeLease
from openzyme_domain.control_plane import utc_now_iso


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


class DrainV3RuntimeRequest(BaseModel):
    max_signals: int = 3
    max_steps_per_agent: int = 8
    auto_enqueue_ready_tasks: bool = False


class ResolveV3ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str


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
        for private_key in ("artifacts", "job_id", "remote_run_dir"):
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
    v3_background_runtime_enabled: bool | None = None
    v3_pipeline_sandbox_runner: Any | None = None
    v3_bio_adapter: Any | None = None
    v3_allow_bio_fixture_adapter: bool = False
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
            yield scope.repositories

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
        return V3HostApiService(
            repositories=repositories,
            event_store=V3EventStore(repositories),
            engine_registry=self.build_v3_engine_registry(repositories),
            model_factory=self.foundation.model_factory,
            bio_research_service=self.foundation.bio_research_service,
            research_adapter=self.foundation.research_adapter,
            signal_notifier=self.v3_signal_notifier,
            runtime_repository_scope_factory=self.v3_repository_scope,
            engine_registry_factory=self.build_v3_engine_registry,
            scheduler_limits={}
            if self.foundation.settings is None
            else dict(self.foundation.settings.limits.provider_limits),
        )

    def build_v3_engine_registry(
        self,
        repositories: CoreRepositories,
        runtime_lease: SessionRuntimeLease | None = None,
    ) -> EngineRegistry:
        @contextmanager
        def runtime_repository_scope() -> Iterator[CoreRepositories]:
            with self.v3_repository_scope(mode="connection") as scoped_repositories:
                if runtime_lease is None:
                    yield scoped_repositories
                    return
                with scoped_repositories.runtime_write_fence(runtime_lease):
                    yield scoped_repositories

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
                repository_scope_factory=runtime_repository_scope,
            ),
        )


def _as_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, CommandIdempotencyConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, MissingLlmConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


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
    request_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            digest_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
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
        raise HTTPException(status_code=401, detail="request is not authenticated")
    return principal


def _require_project_access(principal: HostPrincipal, project_id: str) -> None:
    if not principal.can_access_project(project_id):
        raise HTTPException(status_code=404, detail="project does not exist")


def _require_session_access(
    service: V3HostApiService,
    *,
    principal: HostPrincipal,
    security: HostSecurityPolicy,
    session_id: str,
) -> None:
    session = service.repositories.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session does not exist")
    if not security.shared:
        return
    if not principal.can_access_project(session.project_id):
        raise HTTPException(status_code=404, detail="session does not exist")
    if principal.has_role("admin"):
        return
    access = service.repositories.session_access.get(
        session_id,
        principal.principal_id,
    )
    if access is None:
        raise HTTPException(status_code=404, detail="session does not exist")


def _sse_encode(event: dict[str, Any]) -> str:
    payload = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return (
        f"id: {int(event['cursor'])}\n"
        f"event: {event['event_type']}\n"
        f"data: {payload}\n\n"
    )


def create_app(
    dependencies: HostApiDependencies,
    *,
    ui_dist_dir: Path | None = None,
) -> FastAPI:
    background_runtime = _build_background_runtime_service(dependencies)
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
        with dependencies.v3_service_scope(mode="write") as service:
            service.recover_abandoned_sdk_continuations()
        background_runtime.start()
        try:
            yield
        finally:
            await background_runtime.stop()
            dependencies.close_owned_v3_storage()

    app = FastAPI(title="OpenZyme Host API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def add_trace_context(request, call_next):  # type: ignore[no-untyped-def]
        with host_request_trace_context(method=request.method, path=request.url.path):
            path = request.url.path
            is_v3 = path == "/v3" or path.startswith("/v3/")
            is_debug = path == "/debug" or path.startswith("/debug/")
            if is_debug and not security.debug_enabled:
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            if is_v3 or is_debug:
                try:
                    principal = security.authenticate(request.headers.get("authorization"))
                except HostAuthenticationError as exc:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": str(exc)},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                if is_debug and security.shared and not principal.has_role(
                    "operator", "admin"
                ):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "operator role is required"},
                    )
                if (
                    is_v3
                    and security.shared
                    and request.method in {"POST", "PUT", "PATCH", "DELETE"}
                    and not (request.headers.get("idempotency-key") or "").strip()
                ):
                    return JSONResponse(
                        status_code=428,
                        content={
                            "detail": "Idempotency-Key is required for shared-profile mutations"
                        },
                    )
                request.state.openzyme_principal = principal
            response = await call_next(request)
            response.headers["X-OpenZyme-Deployment-Profile"] = (
                security.deployment_profile
            )
            return response

    @app.post("/v3/sessions")
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

    @app.get("/v3/projects/{project_id}/sessions")
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

    @app.get("/v3/sessions/{session_id}")
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

    @app.post("/v3/sessions/{session_id}/messages")
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

    @app.post("/v3/sessions/{session_id}/runtime/drain")
    def drain_v3_runtime(
        session_id: str,
        request: DrainV3RuntimeRequest,
        http_request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(http_request)
            if security.shared and not principal.has_role("operator", "admin"):
                raise HTTPException(status_code=403, detail="operator role is required")
            # Runtime drain may call LLM/provider/runner boundaries. It owns a
            # connection, but intentionally does not hold a SQLite transaction.
            with dependencies.v3_service_scope(mode="connection") as service:
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
                    return _execute_idempotent_command(
                        service,
                        command_type="runtime.drain",
                        scope_ref=f"session:{session_id}",
                        session_id=session_id,
                        idempotency_key=idempotency_key,
                        request_payload=request.model_dump(mode="json"),
                        operation=lambda: service.drain_runtime(
                            session_id=session_id,
                            max_signals=request.max_signals,
                            max_steps_per_agent=request.max_steps_per_agent,
                            auto_enqueue_ready_tasks=request.auto_enqueue_ready_tasks,
                        ).to_dict(),
                    )
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

    @app.get("/v3/sessions/{session_id}/events")
    def stream_v3_events(
        session_id: str,
        request: Request,
        replay: bool = True,
        follow: bool = False,
        after_cursor: int | None = None,
    ) -> StreamingResponse:
        principal = _request_principal(request)
        with dependencies.v3_service_scope(mode="read") as service:
            _require_session_access(
                service,
                principal=principal,
                security=security,
                session_id=session_id,
            )

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
                return scoped_service.events(session_id, after_cursor=cursor)

        async def event_stream() -> Any:
            cursor = requested_cursor
            if replay:
                existing = read_events(cursor)
                for event in existing:
                    yield _sse_encode(event)
                    cursor = int(event["cursor"])
            else:
                existing = read_events(cursor)
                if existing:
                    cursor = int(existing[-1]["cursor"])

            if not follow:
                return

            while True:
                current = read_events(cursor)
                for event in current:
                    yield _sse_encode(event)
                    cursor = int(event["cursor"])
                await asyncio.sleep(0.5)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/v3/tasks")
    def create_v3_task(
        payload: dict[str, Any],
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                session_id = str(payload.get("session_id") or "")
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
                    request_payload=payload,
                    operation=lambda: service.create_task(payload),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.patch("/v3/tasks/{task_id}")
    def update_v3_task(
        task_id: str,
        payload: dict[str, Any],
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
                return _execute_idempotent_command(
                    service,
                    command_type="task.update",
                    scope_ref=f"task:{task_id}",
                    session_id=task.session_id,
                    idempotency_key=idempotency_key,
                    request_payload=payload,
                    operation=lambda: service.update_task(task_id, payload),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/lanes")
    def create_v3_lane(
        payload: dict[str, Any],
        request: Request,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        try:
            principal = _request_principal(request)
            with dependencies.v3_service_scope(mode="write") as service:
                session_id = str(payload.get("session_id") or "")
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
                    request_payload=payload,
                    operation=lambda: service.create_lane(payload),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/lanes/{lane_id}/claim")
    def claim_v3_lane(
        lane_id: str,
        payload: dict[str, Any],
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
                    request_payload=payload,
                    operation=lambda: service.claim_lane(
                        lane_id,
                        claimed_ref=principal.principal_id,
                    ),
                )
        except Exception as exc:  # pragma: no cover - normalized below
            raise _as_http_error(exc) from exc

    @app.post("/v3/lanes/{lane_id}/keep")
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

    @app.post("/v3/lanes/{lane_id}/remove")
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

    @app.post("/v3/approvals/{approval_id}/resolve")
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
