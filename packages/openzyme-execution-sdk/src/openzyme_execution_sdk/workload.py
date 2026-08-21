from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_execution_contracts import ExecutionRouteIdentity
from openzyme_execution_contracts import ExecutionWorkloadSpec

from .client import ExecutionSdkError
from .client import call


@dataclass(frozen=True, slots=True)
class ExecutionWorkloadInvocation:
    invocation_id: str
    operation_id: str
    execution_id: str
    route_id: str
    workload_digest: str


def submit_workload(
    *,
    workload: ExecutionWorkloadSpec,
    route: ExecutionRouteIdentity,
    admission_identity: dict[str, Any],
) -> ExecutionWorkloadInvocation:
    if not isinstance(workload, ExecutionWorkloadSpec):
        raise TypeError("workload must be a parsed ExecutionWorkloadSpec")
    if not isinstance(route, ExecutionRouteIdentity):
        raise TypeError("route must be a parsed ExecutionRouteIdentity")
    if not isinstance(admission_identity, dict):
        raise TypeError("admission_identity must be a closed object")
    payload = call(
        "execution.workload.submit",
        {
            "schema_version": "execution_workload_admission@1",
            "workload": workload.to_dict(),
            "route_identity": route.to_dict(),
            "admission_identity": dict(admission_identity),
        },
    )
    if not isinstance(payload, dict) or set(payload) != {
        "invocation_id",
        "operation_id",
        "execution_id",
        "route_id",
        "workload_digest",
    }:
        raise ExecutionSdkError(
            "workload admission returned a non-closed result",
            error_code="execution_workload_response_invalid",
            stage="execution_workload_admission",
            retryable=False,
        )
    return ExecutionWorkloadInvocation(
        invocation_id=str(payload["invocation_id"]),
        operation_id=str(payload["operation_id"]),
        execution_id=str(payload["execution_id"]),
        route_id=str(payload["route_id"]),
        workload_digest=str(payload["workload_digest"]),
    )


__all__ = ["ExecutionWorkloadInvocation", "submit_workload"]
