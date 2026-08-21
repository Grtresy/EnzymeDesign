from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible
from openzyme_contracts.identity import require_identifier
from openzyme_extension_spi import HttpRouteInvocation
from openzyme_extension_spi import HttpRouteRuntimeContribution
from openzyme_extension_spi import KernelMutationReceipt

from .file_workspace_v2 import FileWorkspaceV2HostContractError
from .file_workspace_v2 import FileWorkspaceV2HostProjection
from .file_workspace_v2 import FileWorkspaceV2HostSurface
from .security import HostAuthenticationError
from .security import HostPrincipal
from .security import HostSecurityPolicy


@dataclass(frozen=True, slots=True)
class HostV2MutationInvocation:
    """One admitted HTTP command; the Distribution translates it to Kernel APIs."""

    route_id: str
    method: str
    path: str
    session_id: str
    actor_id: str
    idempotency_key: str
    correlation_id: str
    payload: Mapping[str, JsonValue]
    precondition: FileWorkspaceV2HostProjection

    def __post_init__(self) -> None:
        payload = freeze_json(self.payload, field_name="payload")
        if not isinstance(payload, Mapping):
            raise ValueError("Host mutation payload must be a JSON object")
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class HostV2SessionBootstrapInvocation:
    """Authenticated pre-Session command bound to one exact active release."""

    session_id: str
    actor_id: str
    idempotency_key: str
    correlation_id: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.session_id, field_name="session_id")
        payload = freeze_json(self.payload, field_name="payload")
        if not isinstance(payload, Mapping):
            raise ValueError("Session bootstrap payload must be a JSON object")
        object.__setattr__(self, "payload", payload)


class HostV2KernelCommandGateway(Protocol):
    """Narrow outbound Port; Host owns transport, not canonical mutation logic."""

    def bootstrap(
        self,
        invocation: HostV2SessionBootstrapInvocation,
    ) -> KernelMutationReceipt: ...

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt: ...


class HostV2CommandError(RuntimeError):
    """Public-safe command failure emitted by an injected Distribution gateway."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        mutation_applied: bool | None,
        effect_certainty: str,
        details: Mapping[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.mutation_applied = mutation_applied
        self.effect_certainty = effect_certainty
        self.fallback_performed = False
        frozen = freeze_json(details or {}, field_name="details")
        assert isinstance(frozen, Mapping)
        self.details = frozen


@dataclass(frozen=True, slots=True)
class HostV2KernelMutationRoute:
    route_id: str
    method: str
    path: str

    def __post_init__(self) -> None:
        require_identifier(self.route_id, field_name="route_id")
        if self.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Kernel mutation route requires a mutation HTTP method")
        if (
            not self.path.startswith("/v3/sessions/{session_id}/")
            or ".." in self.path
            or "\x00" in self.path
        ):
            raise ValueError("Kernel mutation route must have one bounded Session path")


KERNEL_V2_MUTATION_ROUTES = (
    HostV2KernelMutationRoute(
        "openzyme.kernel.message.send@2",
        "POST",
        "/v3/sessions/{session_id}/messages",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.task.create@2",
        "POST",
        "/v3/sessions/{session_id}/tasks",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.task.dependency.add@2",
        "POST",
        "/v3/sessions/{session_id}/tasks/{task_id}/dependencies",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.task.finish@2",
        "POST",
        "/v3/sessions/{session_id}/tasks/{task_id}/finish",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.lane.create@2",
        "POST",
        "/v3/sessions/{session_id}/lanes",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.agent.register@2",
        "POST",
        "/v3/sessions/{session_id}/agents",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.agent.retire@2",
        "POST",
        "/v3/sessions/{session_id}/agents/{agent_member_id}/retire",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.protocol.delegate@2",
        "POST",
        "/v3/sessions/{session_id}/protocol/delegations",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.protocol.send@2",
        "POST",
        "/v3/sessions/{session_id}/protocol/messages",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.approval.request@2",
        "POST",
        "/v3/sessions/{session_id}/approvals",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.approval.decide@2",
        "POST",
        "/v3/sessions/{session_id}/approvals/{approval_id}/decision",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.authority.issue@2",
        "POST",
        "/v3/sessions/{session_id}/authority-leases",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.authority.revoke@2",
        "POST",
        "/v3/sessions/{session_id}/authority-leases/{lease_id}/revoke",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.runtime.drain@2",
        "POST",
        "/v3/sessions/{session_id}/runtime/drain",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.workspace.fs.mutate@2",
        "POST",
        "/v3/sessions/{session_id}/workspace/filesystem",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.workspace.exec@2",
        "POST",
        "/v3/sessions/{session_id}/workspace/processes",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.workspace.checkpoint@2",
        "POST",
        "/v3/sessions/{session_id}/workspace/checkpoints",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.workspace.publish@2",
        "POST",
        "/v3/sessions/{session_id}/workspace/publications",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.workspace.handoff@2",
        "POST",
        "/v3/sessions/{session_id}/workspace/handoffs",
    ),
)


@dataclass(frozen=True, slots=True)
class HostV2Dependencies:
    security_policy: HostSecurityPolicy
    workspace_surface: FileWorkspaceV2HostSurface
    command_gateway: HostV2KernelCommandGateway
    kernel_mutation_routes: tuple[HostV2KernelMutationRoute, ...] = (
        KERNEL_V2_MUTATION_ROUTES
    )
    http_routes: tuple[HttpRouteRuntimeContribution, ...] = ()

    def __post_init__(self) -> None:
        route_keys = [(route.method, route.path) for route in self.http_routes]
        route_ids = [route.route_id for route in self.http_routes]
        if len(set(route_keys)) != len(route_keys) or len(set(route_ids)) != len(
            route_ids
        ):
            raise ValueError("Host @2 extension HTTP routes must be unique")
        if any(route.method != "GET" for route in self.http_routes):
            raise ValueError(
                "Host @2 query runtime only mounts GET extension routes; "
                "mutations require a Kernel command gateway"
            )
        kernel_route_keys = [
            (route.method, route.path) for route in self.kernel_mutation_routes
        ]
        kernel_route_ids = [route.route_id for route in self.kernel_mutation_routes]
        if len(set(kernel_route_keys)) != len(kernel_route_keys) or len(
            set(kernel_route_ids)
        ) != len(kernel_route_ids):
            raise ValueError("Host @2 Kernel mutation routes must be unique")
        overlap = set(kernel_route_keys).intersection(route_keys)
        if overlap:
            raise ValueError("Plugin HTTP route collides with a Kernel route")


def create_v2_app(dependencies: HostV2Dependencies) -> FastAPI:
    """Build the exact @2 delivery Adapter without legacy product imports."""

    app = FastAPI(title="OpenZyme Host API", version="2")

    @app.exception_handler(FileWorkspaceV2HostContractError)
    async def handle_contract_error(
        request: Request,
        exc: FileWorkspaceV2HostContractError,
    ) -> JSONResponse:
        del request
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            mutation_applied=False,
        )

    @app.exception_handler(HostAuthenticationError)
    async def handle_authentication_error(
        request: Request,
        exc: HostAuthenticationError,
    ) -> JSONResponse:
        del request
        return _error_response(
            status_code=401,
            code="authentication_required",
            message=str(exc),
            mutation_applied=False,
        )

    @app.exception_handler(HostV2CommandError)
    async def handle_command_error(
        request: Request,
        exc: HostV2CommandError,
    ) -> JSONResponse:
        del request
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            mutation_applied=exc.mutation_applied,
            effect_certainty=exc.effect_certainty,
            details=exc.details,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        del request
        return _error_response(
            status_code=exc.status_code,
            code="request_rejected",
            message=str(exc.detail),
            mutation_applied=False,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        return _error_response(
            status_code=422,
            code="request_validation_error",
            message="Request payload failed closed validation.",
            mutation_applied=False,
            details={"errors": exc.errors()},
        )

    @app.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "schema_version": "openzyme_host_v2_health@1",
            "status": "ready",
            "release_digest": dependencies.workspace_surface.release.release_digest,
        }

    @app.post("/v3/sessions", response_model=None)
    async def bootstrap_session(
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> JSONResponse:
        principal = _authenticate(dependencies.security_policy, request)
        correlation_id = _correlation_id(request)
        dependencies.workspace_surface.admit_session_bootstrap_request(
            headers=request.headers,
        )
        payload = await _json_object(request)
        session_id = payload.get("session_id")
        if not isinstance(session_id, str):
            raise HTTPException(
                status_code=422,
                detail="Session bootstrap requires session_id",
            )
        try:
            require_identifier(session_id, field_name="session_id")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Session bootstrap session_id is invalid",
            ) from exc
        receipt = dependencies.command_gateway.bootstrap(
            HostV2SessionBootstrapInvocation(
                session_id=session_id,
                actor_id=principal.principal_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload=payload,
            )
        )
        return JSONResponse(
            content=receipt.to_dict(),
            media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
            headers=dependencies.workspace_surface.release_response_headers,
        )

    @app.get("/v3/sessions/{session_id}/workspace", response_model=None)
    async def inspect_workspace(
        session_id: str,
        request: Request,
    ) -> JSONResponse:
        principal = _authenticate(dependencies.security_policy, request)
        correlation_id = _correlation_id(request)
        dependencies.workspace_surface.admit_request(
            method="GET",
            headers=request.headers,
            session_id=session_id,
            actor_id=principal.principal_id,
            correlation_id=correlation_id,
        )
        current = dependencies.workspace_surface.inspect(
            session_id=session_id,
            actor_id=principal.principal_id,
            correlation_id=correlation_id,
        )
        _require_project_access(principal, current)
        return _projection_response(current)

    def mutation_endpoint(route_id: str):  # type: ignore[no-untyped-def]
        async def endpoint(
            session_id: str,
            request: Request,
            idempotency_key: str = Header(alias="Idempotency-Key"),
        ) -> JSONResponse:
            principal = _authenticate(dependencies.security_policy, request)
            correlation_id = _correlation_id(request)
            current = dependencies.workspace_surface.admit_request(
                method=request.method,
                headers=request.headers,
                session_id=session_id,
                actor_id=principal.principal_id,
                correlation_id=correlation_id,
            )
            assert current is not None
            _require_project_access(principal, current)
            payload = await _json_object(request)
            receipt = dependencies.command_gateway.invoke(
                HostV2MutationInvocation(
                    route_id=route_id,
                    method=request.method,
                    path=request.url.path,
                    session_id=session_id,
                    actor_id=principal.principal_id,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    payload=payload,
                    precondition=current,
                )
            )
            return JSONResponse(
                content=receipt.to_dict(),
                media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
                headers=current.response_headers,
            )

        return endpoint

    for route in dependencies.kernel_mutation_routes:
        app.add_api_route(
            route.path,
            mutation_endpoint(route.route_id),
            methods=[route.method],
            name=route.route_id,
        )

    for runtime in dependencies.http_routes:
        app.add_api_route(
            runtime.path,
            _extension_query_endpoint(dependencies, runtime),
            methods=[runtime.method],
            name=runtime.route_id,
        )

    return app


def _extension_query_endpoint(
    dependencies: HostV2Dependencies,
    runtime: HttpRouteRuntimeContribution,
):  # type: ignore[no-untyped-def]
    async def endpoint(session_id: str, request: Request) -> JSONResponse:
        principal = _authenticate(dependencies.security_policy, request)
        correlation_id = _correlation_id(request)
        dependencies.workspace_surface.admit_request(
            method="GET",
            headers=request.headers,
            session_id=session_id,
            actor_id=principal.principal_id,
            correlation_id=correlation_id,
        )
        current = dependencies.workspace_surface.inspect(
            session_id=session_id,
            actor_id=principal.principal_id,
            correlation_id=correlation_id,
        )
        _require_project_access(principal, current)
        result = runtime.invoke(
            HttpRouteInvocation(
                context=current.query_context,
                route_id=runtime.route_id,
                method=runtime.method,
                path=request.url.path,
                payload={},
            )
        )
        status_code = 200 if result.ok else 409
        return JSONResponse(
            status_code=status_code,
            content=result.to_dict(),
            media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
            headers=current.response_headers,
        )

    return endpoint


def _authenticate(policy: HostSecurityPolicy, request: Request) -> HostPrincipal:
    return policy.authenticate(request.headers.get("authorization"))


def _correlation_id(request: Request) -> str:
    return request.headers.get("x-request-id") or f"request-{uuid4().hex}"


async def _json_object(request: Request) -> Mapping[str, JsonValue]:
    try:
        value = await request.json()
        value = freeze_json(value, field_name="request_body")
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="request body must be JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=422, detail="request body must be an object")
    return value


def _require_project_access(
    principal: HostPrincipal,
    current: FileWorkspaceV2HostProjection,
) -> None:
    if not principal.project_ids or "*" in principal.project_ids:
        return
    session = current.projection.core.payload.get("session")
    project_id = session.get("project_id") if isinstance(session, Mapping) else None
    if not isinstance(project_id, str) or not principal.can_access_project(project_id):
        raise HTTPException(status_code=403, detail="project access is forbidden")


def _projection_response(current: FileWorkspaceV2HostProjection) -> JSONResponse:
    return JSONResponse(
        content=current.projection.to_dict(),
        media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        headers=current.response_headers,
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    mutation_applied: bool | None,
    effect_certainty: str = "no_effect",
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "schema_version": "openzyme_host_error@2",
            "error": {
                "code": code,
                "message": message,
                "mutation_applied": mutation_applied,
                "effect_certainty": effect_certainty,
                "fallback_performed": False,
                "details": json_compatible(details or {}),
            },
        },
    )


__all__ = [
    "HostV2Dependencies",
    "HostV2CommandError",
    "HostV2KernelCommandGateway",
    "HostV2KernelMutationRoute",
    "HostV2MutationInvocation",
    "HostV2SessionBootstrapInvocation",
    "KERNEL_V2_MUTATION_ROUTES",
    "create_v2_app",
]
