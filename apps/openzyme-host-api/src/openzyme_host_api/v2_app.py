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
from openzyme_contracts import (
    WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS,
)
from openzyme_contracts import WORKSPACE_PROVISIONING_SUCCESSOR_ADMISSION_RESULT_FIELDS
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible
from openzyme_contracts.identity import require_digest
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


@dataclass(frozen=True, slots=True)
class HostV2WorkspaceProvisioningReconciliationInvocation:
    """One explicit operator admission for an exact blocked intent observation."""

    session_id: str
    actor_id: str
    idempotency_key: str
    correlation_id: str
    intent_id: str
    intent_digest: str
    expected_intent_version: int
    claim_seconds: int
    precondition: FileWorkspaceV2HostProjection

    def __post_init__(self) -> None:
        for field_name in (
            "session_id",
            "actor_id",
            "idempotency_key",
            "correlation_id",
            "intent_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.intent_digest, field_name="intent_digest")
        if (
            not isinstance(self.expected_intent_version, int)
            or isinstance(self.expected_intent_version, bool)
            or self.expected_intent_version < 1
        ):
            raise ValueError("expected_intent_version must be positive")
        if (
            not isinstance(self.claim_seconds, int)
            or isinstance(self.claim_seconds, bool)
            or not 1 <= self.claim_seconds <= 86_400
        ):
            raise ValueError("claim_seconds must be between 1 and 86400")


@dataclass(frozen=True, slots=True)
class HostV2WorkspaceProvisioningSuccessorInvocation:
    """One explicit operator request for a new generation after a known failure."""

    session_id: str
    actor_id: str
    idempotency_key: str
    correlation_id: str
    failed_intent_id: str
    failed_intent_digest: str
    expected_failed_intent_version: int
    resolved_reconciliation_id: str | None
    precondition: FileWorkspaceV2HostProjection

    def __post_init__(self) -> None:
        for field_name in (
            "session_id",
            "actor_id",
            "idempotency_key",
            "correlation_id",
            "failed_intent_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(
            self.failed_intent_digest,
            field_name="failed_intent_digest",
        )
        if (
            not isinstance(self.expected_failed_intent_version, int)
            or isinstance(self.expected_failed_intent_version, bool)
            or self.expected_failed_intent_version < 1
        ):
            raise ValueError("expected_failed_intent_version must be positive")
        if self.resolved_reconciliation_id is not None:
            require_identifier(
                self.resolved_reconciliation_id,
                field_name="resolved_reconciliation_id",
            )


class HostV2KernelCommandGateway(Protocol):
    """Narrow outbound Port; Host owns transport, not canonical mutation logic."""

    def bootstrap(
        self,
        invocation: HostV2SessionBootstrapInvocation,
    ) -> KernelMutationReceipt: ...

    def reconcile_workspace_provisioning(
        self,
        invocation: HostV2WorkspaceProvisioningReconciliationInvocation,
    ) -> KernelMutationReceipt:
        """Durably admit only; never claim, observe, or invoke an Adapter inline."""
        ...

    def create_workspace_provisioning_successor(
        self,
        invocation: HostV2WorkspaceProvisioningSuccessorInvocation,
    ) -> KernelMutationReceipt:
        """Create only the pending successor graph; never provision it inline."""
        ...

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
        "openzyme.kernel.workspace.provisioning.reconcile@2",
        "POST",
        "/v3/sessions/{session_id}/workspace/provisioning/reconcile",
    ),
    HostV2KernelMutationRoute(
        "openzyme.kernel.workspace.provisioning.successor@2",
        "POST",
        "/v3/sessions/{session_id}/workspace/provisioning/successor",
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

_ASYNC_ACCEPTED_ROUTE_IDS = frozenset(
    {
        "openzyme.kernel.message.send@2",
        "openzyme.kernel.approval.request@2",
        "openzyme.kernel.approval.decide@2",
        "openzyme.kernel.runtime.drain@2",
    }
)

_RESIDENT_READY_ROUTE_IDS = frozenset(
    {
        "openzyme.kernel.message.send@2",
        "openzyme.kernel.approval.request@2",
        "openzyme.kernel.approval.decide@2",
        "openzyme.kernel.runtime.drain@2",
    }
)

_MESSAGE_PAYLOAD_FIELDS = frozenset(
    {
        "lane_id",
        "message",
        "message_id",
        "skill_keys",
        "task_id",
        "workflow_refs",
    }
)

_WORKSPACE_PROVISIONING_RECONCILIATION_ROUTE_ID = (
    "openzyme.kernel.workspace.provisioning.reconcile@2"
)
_WORKSPACE_PROVISIONING_RECONCILIATION_PAYLOAD_FIELDS = frozenset(
    {
        "claim_seconds",
        "expected_intent_version",
        "intent_digest",
        "intent_id",
    }
)
_WORKSPACE_PROVISIONING_SUCCESSOR_ROUTE_ID = (
    "openzyme.kernel.workspace.provisioning.successor@2"
)
_WORKSPACE_PROVISIONING_SUCCESSOR_PAYLOAD_FIELDS = frozenset(
    {
        "expected_failed_intent_version",
        "failed_intent_digest",
        "failed_intent_id",
        "resolved_reconciliation_id",
    }
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
            status_code=202,
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
        _require_current_resident_state(current)
        _require_project_access(principal, current)
        return _projection_response(current)

    @app.get(
        "/v3/sessions/{session_id}/runtime/commands/{command_id}",
        response_model=None,
    )
    async def inspect_runtime_command(
        session_id: str,
        command_id: str,
        request: Request,
    ) -> JSONResponse:
        """Read one durable drain command from the exact public projection.

        This route is observation-only.  Polling never resubmits the drain or
        claims runtime authority, and the response remains bound to the same
        projection/release headers as workspace inspection.
        """

        try:
            require_identifier(command_id, field_name="command_id")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Runtime command identity is invalid",
            ) from exc
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
        _require_current_resident_state(current)
        _require_project_access(principal, current)
        runtime = current.projection.core.payload.get("runtime")
        commands = runtime.get("commands") if isinstance(runtime, Mapping) else None
        if not isinstance(commands, (list, tuple)):
            raise HostV2CommandError(
                "resident_teammate_state_incompatible",
                "Session runtime projection lacks durable command status facts",
                status_code=409,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={"session_id": session_id},
            )
        matches = tuple(
            item
            for item in commands
            if isinstance(item, Mapping) and item.get("command_id") == command_id
        )
        if len(matches) != 1:
            raise HostV2CommandError(
                "runtime_command_not_found",
                "Runtime command is absent from this Session projection",
                status_code=404,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={"session_id": session_id, "command_id": command_id},
            )
        return JSONResponse(
            content={
                "schema_version": "runtime_command_status@1",
                "session_id": session_id,
                "command": json_compatible(matches[0]),
                "projection_digest": current.projection.projection_digest,
                "mutation_applied": False,
                "fallback_performed": False,
            },
            media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
            headers=current.response_headers,
        )

    @app.post(
        "/v3/sessions/{session_id}/workspace/provisioning/reconcile",
        status_code=202,
        response_model=None,
        name=_WORKSPACE_PROVISIONING_RECONCILIATION_ROUTE_ID,
    )
    async def reconcile_workspace_provisioning(
        session_id: str,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> JSONResponse:
        """Admit one durable, bounded reconciliation without observing inline."""

        principal = _authenticate(dependencies.security_policy, request)
        _require_operator(principal)
        correlation_id = _correlation_id(request)
        current = dependencies.workspace_surface.admit_request(
            method=request.method,
            headers=request.headers,
            session_id=session_id,
            actor_id=principal.principal_id,
            correlation_id=correlation_id,
        )
        assert current is not None
        _require_current_resident_state(current)
        _require_project_access(principal, current)
        payload = _validate_workspace_provisioning_reconciliation_payload(
            await _json_object(request)
        )
        _require_workspace_provisioning_reconciliation_precondition(
            current=current,
            payload=payload,
        )
        reconcile = getattr(
            dependencies.command_gateway,
            "reconcile_workspace_provisioning",
            None,
        )
        if not callable(reconcile):
            raise HostV2CommandError(
                "workspace_provisioning_reconciliation_gateway_unconfigured",
                "The active Distribution has no explicit provisioning reconciliation gateway",
                status_code=503,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={
                    "session_id": session_id,
                    "intent_id": payload["intent_id"],
                    "fallback_performed": False,
                },
            )
        receipt = reconcile(
            HostV2WorkspaceProvisioningReconciliationInvocation(
                session_id=session_id,
                actor_id=principal.principal_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                intent_id=str(payload["intent_id"]),
                intent_digest=str(payload["intent_digest"]),
                expected_intent_version=int(payload["expected_intent_version"]),
                claim_seconds=int(payload["claim_seconds"]),
                precondition=current,
            )
        )
        _require_workspace_provisioning_reconciliation_admission_receipt(
            receipt=receipt,
            current=current,
            intent_id=str(payload["intent_id"]),
            intent_digest=str(payload["intent_digest"]),
            expected_intent_version=int(payload["expected_intent_version"]),
            requested_claim_seconds=int(payload["claim_seconds"]),
        )
        return JSONResponse(
            status_code=202,
            content=receipt.to_dict(),
            media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
            headers=current.response_headers,
        )

    @app.post(
        "/v3/sessions/{session_id}/workspace/provisioning/successor",
        status_code=202,
        response_model=None,
        name=_WORKSPACE_PROVISIONING_SUCCESSOR_ROUTE_ID,
    )
    async def create_workspace_provisioning_successor(
        session_id: str,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> JSONResponse:
        """Admit one pending successor generation without provisioning it."""

        principal = _authenticate(dependencies.security_policy, request)
        _require_operator(principal)
        correlation_id = _correlation_id(request)
        current = dependencies.workspace_surface.admit_request(
            method=request.method,
            headers=request.headers,
            session_id=session_id,
            actor_id=principal.principal_id,
            correlation_id=correlation_id,
        )
        assert current is not None
        _require_current_resident_state(current)
        _require_project_access(principal, current)
        payload = _validate_workspace_provisioning_successor_payload(
            await _json_object(request)
        )
        _require_workspace_provisioning_successor_precondition(
            current=current,
            payload=payload,
        )
        create_successor = getattr(
            dependencies.command_gateway,
            "create_workspace_provisioning_successor",
            None,
        )
        if not callable(create_successor):
            raise HostV2CommandError(
                "workspace_provisioning_successor_gateway_unconfigured",
                "The active Distribution has no explicit provisioning successor gateway",
                status_code=503,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={
                    "session_id": session_id,
                    "failed_intent_id": payload["failed_intent_id"],
                    "fallback_performed": False,
                },
            )
        resolved_reconciliation_id = payload["resolved_reconciliation_id"]
        receipt = create_successor(
            HostV2WorkspaceProvisioningSuccessorInvocation(
                session_id=session_id,
                actor_id=principal.principal_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                failed_intent_id=str(payload["failed_intent_id"]),
                failed_intent_digest=str(payload["failed_intent_digest"]),
                expected_failed_intent_version=int(
                    payload["expected_failed_intent_version"]
                ),
                resolved_reconciliation_id=(
                    None
                    if resolved_reconciliation_id is None
                    else str(resolved_reconciliation_id)
                ),
                precondition=current,
            )
        )
        _require_workspace_provisioning_successor_admission_receipt(
            receipt=receipt,
            current=current,
            payload=payload,
        )
        return JSONResponse(
            status_code=202,
            content=receipt.to_dict(),
            media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
            headers=current.response_headers,
        )

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
            _require_current_resident_state(current)
            _require_project_access(principal, current)
            _require_resident_ready(route_id=route_id, current=current)
            payload = _validate_mutation_payload(
                route_id=route_id,
                payload=await _json_object(request),
            )
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
                status_code=(202 if route_id in _ASYNC_ACCEPTED_ROUTE_IDS else 200),
                content=receipt.to_dict(),
                media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
                headers=current.response_headers,
            )

        return endpoint

    for route in dependencies.kernel_mutation_routes:
        if route.route_id in {
            _WORKSPACE_PROVISIONING_RECONCILIATION_ROUTE_ID,
            _WORKSPACE_PROVISIONING_SUCCESSOR_ROUTE_ID,
        }:
            continue
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
        _require_current_resident_state(current)
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


def _require_operator(principal: HostPrincipal) -> None:
    if principal.has_role("operator", "admin"):
        return
    raise HostV2CommandError(
        "workspace_provisioning_operator_required",
        "Workspace provisioning recovery requires an operator or admin principal",
        status_code=403,
        mutation_applied=False,
        effect_certainty="no_effect",
        details={"actor_id": principal.principal_id},
    )


def _validate_workspace_provisioning_reconciliation_payload(
    payload: Mapping[str, JsonValue],
) -> Mapping[str, JsonValue]:
    if set(payload) != _WORKSPACE_PROVISIONING_RECONCILIATION_PAYLOAD_FIELDS:
        raise HostV2CommandError(
            "workspace_provisioning_reconciliation_payload_invalid",
            "Provisioning reconciliation payload fields are closed",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={
                "missing_fields": sorted(
                    _WORKSPACE_PROVISIONING_RECONCILIATION_PAYLOAD_FIELDS.difference(
                        payload
                    )
                ),
                "unexpected_fields": sorted(
                    set(payload).difference(
                        _WORKSPACE_PROVISIONING_RECONCILIATION_PAYLOAD_FIELDS
                    )
                ),
            },
        )
    try:
        intent_id = payload["intent_id"]
        intent_digest = payload["intent_digest"]
        if not isinstance(intent_id, str) or not isinstance(intent_digest, str):
            raise ValueError("intent identity fields must be strings")
        require_identifier(intent_id, field_name="intent_id")
        require_digest(intent_digest, field_name="intent_digest")
        expected_version = payload["expected_intent_version"]
        claim_seconds = payload["claim_seconds"]
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 1
        ):
            raise ValueError("expected_intent_version must be positive")
        if (
            not isinstance(claim_seconds, int)
            or isinstance(claim_seconds, bool)
            or not 1 <= claim_seconds <= 86_400
        ):
            raise ValueError("claim_seconds must be between 1 and 86400")
    except (KeyError, TypeError, ValueError) as exc:
        raise HostV2CommandError(
            "workspace_provisioning_reconciliation_payload_invalid",
            "Provisioning reconciliation requires exact intent and bounded claim identities",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
        ) from exc
    return payload


def _validate_workspace_provisioning_successor_payload(
    payload: Mapping[str, JsonValue],
) -> Mapping[str, JsonValue]:
    if set(payload) != _WORKSPACE_PROVISIONING_SUCCESSOR_PAYLOAD_FIELDS:
        raise HostV2CommandError(
            "workspace_provisioning_successor_payload_invalid",
            "Provisioning successor payload fields are closed",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={
                "missing_fields": sorted(
                    _WORKSPACE_PROVISIONING_SUCCESSOR_PAYLOAD_FIELDS.difference(payload)
                ),
                "unexpected_fields": sorted(
                    set(payload).difference(
                        _WORKSPACE_PROVISIONING_SUCCESSOR_PAYLOAD_FIELDS
                    )
                ),
            },
        )
    try:
        failed_intent_id = payload["failed_intent_id"]
        failed_intent_digest = payload["failed_intent_digest"]
        if not isinstance(failed_intent_id, str) or not isinstance(
            failed_intent_digest, str
        ):
            raise ValueError("failed intent identity fields must be strings")
        require_identifier(failed_intent_id, field_name="failed_intent_id")
        require_digest(
            failed_intent_digest,
            field_name="failed_intent_digest",
        )
        expected_version = payload["expected_failed_intent_version"]
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 1
        ):
            raise ValueError("expected_failed_intent_version must be positive")
        resolved_reconciliation_id = payload["resolved_reconciliation_id"]
        if resolved_reconciliation_id is not None:
            if not isinstance(resolved_reconciliation_id, str):
                raise ValueError("resolved_reconciliation_id must be a string or null")
            require_identifier(
                resolved_reconciliation_id,
                field_name="resolved_reconciliation_id",
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise HostV2CommandError(
            "workspace_provisioning_successor_payload_invalid",
            "Provisioning successor requires one exact failed occurrence",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
        ) from exc
    return payload


def _workspace_provisioning_fact(
    current: FileWorkspaceV2HostProjection,
) -> tuple[Mapping[str, JsonValue], Mapping[str, JsonValue]]:
    core = current.projection.core.payload
    session = core.get("session")
    workspace = core.get("workspace")
    readiness = (
        session.get("resident_readiness") if isinstance(session, Mapping) else None
    )
    provisioning = (
        workspace.get("provisioning") if isinstance(workspace, Mapping) else None
    )
    if not isinstance(readiness, Mapping) or not isinstance(provisioning, Mapping):
        raise HostV2CommandError(
            "resident_teammate_state_incompatible",
            "Session lacks exact workspace provisioning recovery facts",
            status_code=409,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={"session_id": current.query_context.session_id},
        )
    return readiness, provisioning


def _require_workspace_provisioning_reconciliation_precondition(
    *,
    current: FileWorkspaceV2HostProjection,
    payload: Mapping[str, JsonValue],
) -> None:
    readiness, provisioning = _workspace_provisioning_fact(current)
    reconciliation = provisioning.get("reconciliation")
    source_matches = (
        provisioning.get("intent_id") == payload["intent_id"]
        and provisioning.get("intent_digest") == payload["intent_digest"]
        and provisioning.get("intent_state_version")
        == payload["expected_intent_version"]
    )
    result_is_unresolved = reconciliation is None or (
        isinstance(reconciliation, Mapping)
        and reconciliation.get("status") == "blocked"
        and reconciliation.get("reconcile_required") is True
        and reconciliation.get("blocked_intent_state_version")
        == payload["expected_intent_version"]
        and reconciliation.get("blocked_intent_digest") == payload["intent_digest"]
    )
    admissible = (
        readiness.get("readiness") == "blocked"
        and readiness.get("next_action") == "reconcile_workspace_provisioning"
        and provisioning.get("status") == "blocked"
        and provisioning.get("effect_certainty") == "dispatch_in_doubt"
        and provisioning.get("mutation_applied") is None
        and provisioning.get("fallback_performed") is False
        and provisioning.get("retry_permitted") is False
        and provisioning.get("reconcile_required") is True
        and provisioning.get("next_action") == "reconcile_workspace_provisioning"
        and source_matches
        and result_is_unresolved
    )
    if admissible:
        return
    raise HostV2CommandError(
        "workspace_provisioning_reconciliation_precondition_failed",
        "Only the exact unresolved dispatch-in-doubt occurrence may be reconciled",
        status_code=409,
        mutation_applied=False,
        effect_certainty="no_effect",
        details={
            "session_id": current.query_context.session_id,
            "requested_intent_id": payload["intent_id"],
            "current_intent_id": provisioning.get("intent_id"),
            "current_intent_state_version": provisioning.get("intent_state_version"),
            "readiness": readiness.get("readiness"),
            "next_action": readiness.get("next_action"),
            "fallback_performed": False,
        },
    )


def _require_workspace_provisioning_successor_precondition(
    *,
    current: FileWorkspaceV2HostProjection,
    payload: Mapping[str, JsonValue],
) -> None:
    readiness, provisioning = _workspace_provisioning_fact(current)
    reconciliation = provisioning.get("reconciliation")
    resolved_reconciliation_id = payload["resolved_reconciliation_id"]
    if resolved_reconciliation_id is None:
        reconciliation_resolved = (
            reconciliation is None and provisioning.get("reconcile_required") is False
        )
    else:
        reconciliation_resolved = (
            isinstance(reconciliation, Mapping)
            and reconciliation.get("reconciliation_id") == resolved_reconciliation_id
            and reconciliation.get("status") == "blocked"
            and reconciliation.get("reconcile_required") is False
            and reconciliation.get("settled_at") is not None
            and reconciliation.get("blocked_intent_state_version")
            == payload["expected_failed_intent_version"]
            and reconciliation.get("blocked_intent_digest")
            == payload["failed_intent_digest"]
        )
    admissible = (
        readiness.get("readiness") == "blocked"
        and readiness.get("next_action") == "create_successor_workspace_generation"
        and provisioning.get("status") == "blocked"
        and provisioning.get("intent_id") == payload["failed_intent_id"]
        and provisioning.get("intent_digest") == payload["failed_intent_digest"]
        and provisioning.get("intent_state_version")
        == payload["expected_failed_intent_version"]
        and provisioning.get("fallback_performed") is False
        and provisioning.get("retry_permitted") is False
        and provisioning.get("next_action") == "create_successor_workspace_generation"
        and reconciliation_resolved
    )
    if admissible:
        return
    raise HostV2CommandError(
        "workspace_provisioning_successor_precondition_failed",
        "Successor admission requires one exact diagnosed failed occurrence",
        status_code=409,
        mutation_applied=False,
        effect_certainty="no_effect",
        details={
            "session_id": current.query_context.session_id,
            "requested_failed_intent_id": payload["failed_intent_id"],
            "current_intent_id": provisioning.get("intent_id"),
            "current_intent_state_version": provisioning.get("intent_state_version"),
            "resolved_reconciliation_id": resolved_reconciliation_id,
            "readiness": readiness.get("readiness"),
            "next_action": readiness.get("next_action"),
            "fallback_performed": False,
        },
    )


def _require_workspace_provisioning_successor_admission_receipt(
    *,
    receipt: KernelMutationReceipt,
    current: FileWorkspaceV2HostProjection,
    payload: Mapping[str, JsonValue],
) -> None:
    _, provisioning = _workspace_provisioning_fact(current)
    result = receipt.result
    effect_certainty = receipt.effect_certainty.value
    source_workspace_id = provisioning.get("workspace_id")
    source_generation = provisioning.get("workspace_generation")
    successor_intent_id = result.get("successor_intent_id")
    identities_valid = False
    try:
        if not isinstance(source_workspace_id, str):
            raise TypeError("workspace_id must be a string")
        if not isinstance(successor_intent_id, str):
            raise TypeError("successor_intent_id must be a string")
        require_identifier(source_workspace_id, field_name="workspace_id")
        require_identifier(
            successor_intent_id,
            field_name="successor_intent_id",
        )
        if successor_intent_id == payload["failed_intent_id"]:
            raise ValueError("successor intent must have a fresh identity")
        if (
            not isinstance(source_generation, int)
            or isinstance(source_generation, bool)
            or source_generation < 1
        ):
            raise ValueError("workspace_generation must be positive")
        identities_valid = True
    except (KeyError, TypeError, ValueError):
        identities_valid = False
    admitted_only = (
        set(result) == WORKSPACE_PROVISIONING_SUCCESSOR_ADMISSION_RESULT_FIELDS
        and receipt.operation == "replace_failed_generation"
        and receipt.mutation_applied is True
        and effect_certainty == "no_effect"
        and receipt.fallback_performed is False
        and identities_valid
        and result.get("failed_intent_id") == payload["failed_intent_id"]
        and result.get("resolved_reconciliation_id")
        == payload["resolved_reconciliation_id"]
        and result.get("workspace_id") == source_workspace_id
        and result.get("generation") == source_generation + 1
        and result.get("readiness") == "provisioning"
        and result.get("successor_intent_created") is True
        and result.get("workspace_generation_reserved") is True
        and result.get("workspace_provisioning_enqueued") is True
        and result.get("adapter_invoked") is False
        and result.get("external_effect_performed") is False
        and result.get("runtime_executed") is False
        and result.get("task_transition_performed") is False
        and result.get("fallback_performed") is False
    )
    if admitted_only:
        return
    raise HostV2CommandError(
        "workspace_provisioning_successor_admission_receipt_invalid",
        "Provisioning successor gateway did not return an admission-only receipt",
        status_code=502,
        mutation_applied=receipt.mutation_applied,
        effect_certainty=effect_certainty,
        details={
            "operation": receipt.operation,
            "result_fields_closed": (
                set(result) == WORKSPACE_PROVISIONING_SUCCESSOR_ADMISSION_RESULT_FIELDS
            ),
            "failed_intent_id": result.get("failed_intent_id"),
            "resolved_reconciliation_id": result.get("resolved_reconciliation_id"),
            "workspace_id": result.get("workspace_id"),
            "generation": result.get("generation"),
            "readiness": result.get("readiness"),
            "successor_intent_created": result.get("successor_intent_created"),
            "workspace_generation_reserved": result.get(
                "workspace_generation_reserved"
            ),
            "workspace_provisioning_enqueued": result.get(
                "workspace_provisioning_enqueued"
            ),
            "adapter_invoked": result.get("adapter_invoked"),
            "external_effect_performed": result.get("external_effect_performed"),
            "runtime_executed": result.get("runtime_executed"),
            "task_transition_performed": result.get("task_transition_performed"),
            "fallback_performed": False,
        },
    )


def _require_workspace_provisioning_reconciliation_admission_receipt(
    *,
    receipt: KernelMutationReceipt,
    current: FileWorkspaceV2HostProjection,
    intent_id: str,
    intent_digest: str,
    expected_intent_version: int,
    requested_claim_seconds: int,
) -> None:
    result = receipt.result
    effect_certainty = receipt.effect_certainty.value
    _, provisioning = _workspace_provisioning_fact(current)
    previous = provisioning.get("reconciliation")
    expected_attempt: int | None = 1
    expected_parent_reconciliation_id: str | None = None
    if isinstance(previous, Mapping):
        previous_attempt = previous.get("attempt")
        previous_id = previous.get("reconciliation_id")
        if (
            isinstance(previous_attempt, int)
            and not isinstance(previous_attempt, bool)
            and previous_attempt >= 1
            and isinstance(previous_id, str)
        ):
            expected_attempt = previous_attempt + 1
            expected_parent_reconciliation_id = previous_id
        else:
            expected_attempt = None
    identities_valid = False
    attempt = result.get("attempt")
    parent_reconciliation_id = result.get("parent_reconciliation_id")
    try:
        for field_name in ("reconciliation_id", "source_receipt_id"):
            value = result.get(field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            require_identifier(value, field_name=field_name)
        for field_name in (
            "reconciliation_digest",
            "source_receipt_digest",
            "dispatch_receipt_digest",
        ):
            value = result.get(field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            require_digest(value, field_name=field_name)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError("attempt must be positive")
        if attempt == 1:
            if parent_reconciliation_id is not None:
                raise ValueError("first reconciliation cannot have a parent")
        else:
            if not isinstance(parent_reconciliation_id, str):
                raise TypeError("later reconciliation requires a parent")
            require_identifier(
                parent_reconciliation_id,
                field_name="parent_reconciliation_id",
            )
        reconciliation_id = result.get("reconciliation_id")
        if reconciliation_id in {intent_id, parent_reconciliation_id}:
            raise ValueError("reconciliation identity must be fresh")
        identities_valid = True
    except (TypeError, ValueError):
        identities_valid = False
    admitted_only = (
        set(result) == WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS
        and receipt.operation == "admit_reconciliation"
        and isinstance(receipt.mutation_applied, bool)
        and effect_certainty == "no_effect"
        and receipt.fallback_performed is False
        and identities_valid
        and result.get("intent_id") == intent_id
        and result.get("blocked_intent_digest") == intent_digest
        and result.get("blocked_intent_state_version") == expected_intent_version
        and result.get("attempt") == expected_attempt
        and result.get("parent_reconciliation_id") == expected_parent_reconciliation_id
        and result.get("requested_claim_seconds") == requested_claim_seconds
        and result.get("status") == "pending"
        and result.get("readiness") == "blocked"
        and result.get("historical_intent_preserved") is True
        and result.get("reconciliation_enqueued") is True
        and result.get("workspace_provisioning_reconciliation_enqueued") is True
        and result.get("adapter_invoked") is False
        and result.get("external_effect_performed") is False
        and result.get("runtime_executed") is False
        and result.get("task_transition_performed") is False
        and result.get("fallback_performed") is False
    )
    if admitted_only:
        return
    raise HostV2CommandError(
        "workspace_provisioning_reconciliation_admission_receipt_invalid",
        "Provisioning reconciliation gateway did not return an admission-only receipt",
        status_code=502,
        mutation_applied=receipt.mutation_applied,
        effect_certainty=effect_certainty,
        details={
            "operation": receipt.operation,
            "result_fields_closed": (
                set(result)
                == WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS
            ),
            "intent_id": result.get("intent_id"),
            "blocked_intent_state_version": result.get("blocked_intent_state_version"),
            "reconciliation_enqueued": result.get("reconciliation_enqueued"),
            "adapter_invoked": result.get("adapter_invoked"),
            "external_effect_performed": result.get("external_effect_performed"),
            "runtime_executed": result.get("runtime_executed"),
            "task_transition_performed": result.get("task_transition_performed"),
            "fallback_performed": False,
        },
    )


def _require_current_resident_state(
    current: FileWorkspaceV2HostProjection,
) -> None:
    core = current.projection.core.payload
    session = core.get("session")
    workspace = core.get("workspace")
    runtime = core.get("runtime")
    conversation = core.get("conversation")
    reflection = core.get("tool_reflection")
    failures = core.get("failures")
    readiness = (
        session.get("resident_readiness") if isinstance(session, Mapping) else None
    )
    provisioning = (
        workspace.get("provisioning") if isinstance(workspace, Mapping) else None
    )
    workflow_authority = (
        runtime.get("workflow_authority") if isinstance(runtime, Mapping) else None
    )
    transcript = (
        conversation.get("transcript") if isinstance(conversation, Mapping) else None
    )
    tool_exposure = (
        reflection.get("tool_exposure") if isinstance(reflection, Mapping) else None
    )
    compatible = (
        isinstance(readiness, Mapping)
        and readiness.get("schema_version") == "resident_teammate_readiness@1"
        and isinstance(provisioning, Mapping)
        and provisioning.get("schema_version") == "workspace_provisioning_public@2"
        and isinstance(workflow_authority, Mapping)
        and workflow_authority.get("schema_version")
        == "workflow_authority_projection@1"
        and isinstance(runtime, Mapping)
        and isinstance(runtime.get("commands"), (list, tuple))
        and isinstance(runtime.get("outcomes"), (list, tuple))
        and isinstance(transcript, Mapping)
        and transcript.get("schema_version") == "ordered_transcript@1"
        and isinstance(tool_exposure, Mapping)
        and tool_exposure.get("schema_version") == "tool_exposure_public@1"
        and isinstance(failures, Mapping)
        and isinstance(failures.get("observations"), (list, tuple))
    )
    if compatible:
        assert isinstance(readiness, Mapping)
        failure_id = readiness.get("failure_id")
        if failure_id is None:
            return
        assert isinstance(failures, Mapping)
        observations = failures.get("observations")
        assert isinstance(observations, (list, tuple))
        matches = tuple(
            item
            for item in observations
            if isinstance(item, Mapping) and item.get("failure_id") == failure_id
        )
        if len(matches) == 1:
            return
    raise HostV2CommandError(
        "resident_teammate_state_incompatible",
        "Session lacks one or more current resident teammate inner contracts",
        status_code=409,
        mutation_applied=False,
        effect_certainty="no_effect",
        details={
            "session_id": current.query_context.session_id,
            "next_action": "create_new_session_or_run_offline_migration",
        },
    )


def _require_resident_ready(
    *,
    route_id: str,
    current: FileWorkspaceV2HostProjection,
) -> None:
    if route_id not in _RESIDENT_READY_ROUTE_IDS:
        return
    session = current.projection.core.payload.get("session")
    readiness = (
        session.get("resident_readiness") if isinstance(session, Mapping) else None
    )
    state = readiness.get("readiness") if isinstance(readiness, Mapping) else None
    if not isinstance(readiness, Mapping) or state not in {
        "provisioning",
        "ready",
        "blocked",
    }:
        raise HostV2CommandError(
            "resident_teammate_state_incompatible",
            "Session lacks the current resident teammate readiness contract",
            status_code=409,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={"route_id": route_id},
        )
    if state == "ready":
        return
    details: dict[str, JsonValue] = {
        "route_id": route_id,
        "readiness": str(state or "incompatible"),
    }
    if isinstance(readiness, Mapping):
        for field_name in (
            "workspace_id",
            "workspace_generation",
            "provisioning_intent_id",
            "failure_id",
            "next_action",
        ):
            value = readiness.get(field_name)
            if value is not None:
                details[field_name] = value
    raise HostV2CommandError(
        "resident_teammate_not_ready",
        "Resident teammate mutations require an exact ready workspace",
        status_code=409,
        mutation_applied=False,
        effect_certainty="no_effect",
        details=details,
    )


def _validate_mutation_payload(
    *,
    route_id: str,
    payload: Mapping[str, JsonValue],
) -> Mapping[str, JsonValue]:
    if route_id != "openzyme.kernel.message.send@2":
        return payload
    unexpected = set(payload).difference(_MESSAGE_PAYLOAD_FIELDS)
    if unexpected:
        raise HostV2CommandError(
            "message_payload_fields_invalid",
            "Message admission payload fields are closed",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={"unexpected_fields": sorted(unexpected)},
        )
    message = payload.get("message")
    if (
        not isinstance(message, str)
        or not message
        or message != message.strip()
        or len(message) > 131_072
    ):
        raise HostV2CommandError(
            "message_payload_invalid",
            "Message admission requires bounded, trimmed message text",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
        )
    for field_name in ("message_id", "task_id", "lane_id"):
        value = payload.get(field_name)
        if value is None:
            continue
        try:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            require_identifier(value, field_name=field_name)
        except ValueError as exc:
            raise HostV2CommandError(
                "message_scope_identity_invalid",
                "Message admission scope identity is invalid",
                status_code=422,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={"field_name": field_name},
            ) from exc
    has_workflow_refs = "workflow_refs" in payload
    has_skill_keys = "skill_keys" in payload
    if has_workflow_refs and has_skill_keys:
        raise HostV2CommandError(
            "message_workflow_selection_ambiguous",
            "Canonical workflow_refs and compatibility skill_keys cannot be combined",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
        )
    if not has_workflow_refs and not has_skill_keys:
        raise HostV2CommandError(
            "message_workflow_selection_required",
            "Message admission requires an explicit workflow selection, including []",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
        )
    selection_field = "workflow_refs" if has_workflow_refs else "skill_keys"
    selection = payload[selection_field]
    if not isinstance(selection, (list, tuple)) or any(
        not isinstance(item, str) or not item or item != item.strip()
        for item in selection
    ):
        raise HostV2CommandError(
            "message_workflow_selection_invalid",
            "Workflow selection must be an ordered array of exact identifiers",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={"field_name": selection_field},
        )
    try:
        for item in selection:
            assert isinstance(item, str)
            require_identifier(item, field_name=selection_field)
    except ValueError as exc:
        raise HostV2CommandError(
            "message_workflow_selection_invalid",
            "Workflow selection contains an invalid exact identifier",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={"field_name": selection_field},
        ) from exc
    if tuple(selection) != tuple(sorted(set(selection))):
        raise HostV2CommandError(
            "message_workflow_selection_invalid",
            "Workflow selection must be sorted and unique",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={"field_name": selection_field},
        )
    return payload


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
    "HostV2WorkspaceProvisioningReconciliationInvocation",
    "HostV2WorkspaceProvisioningSuccessorInvocation",
    "KERNEL_V2_MUTATION_ROUTES",
    "create_v2_app",
]
