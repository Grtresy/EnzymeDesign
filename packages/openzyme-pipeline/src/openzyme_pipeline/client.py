from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import uuid4


class PipelineSdkError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        stage: str | None = None,
        retryable: bool | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        context = []
        if error_code:
            context.append(f"error_code={error_code}")
        if stage:
            context.append(f"stage={stage}")
        if retryable is not None:
            context.append(f"retryable={retryable}")
        display_message = message if not context else f"{message} ({', '.join(context)})"
        super().__init__(display_message)
        self.message = message
        self.error_code = error_code
        self.stage = stage
        self.retryable = retryable
        self.hint = hint
        self.details = {} if details is None else dict(details)


@dataclass(frozen=True, slots=True)
class ControlClient:
    socket_path: str = os.environ.get("OPENZYME_CONTROL_SOCKET", "/openzyme/control.sock")

    def call(self, method: str, params: dict[str, Any]) -> Any:
        request = {
            "jsonrpc": "2.0",
            "id": f"rpc_{uuid4().hex[:12]}",
            "method": method,
            "params": params,
        }
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(self.socket_path)
            client.sendall(json.dumps(request, sort_keys=True).encode("utf-8") + b"\n")
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
        response = json.loads(b"".join(chunks).decode("utf-8").strip())
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                details = error.get("details")
                if not isinstance(details, dict):
                    details = {} if details is None else {"value": details}
                raise PipelineSdkError(
                    str(error.get("message") or error),
                    error_code=None if error.get("error_code") is None else str(error.get("error_code")),
                    stage=None if error.get("stage") is None else str(error.get("stage")),
                    retryable=None if error.get("retryable") is None else bool(error.get("retryable")),
                    hint=None if error.get("hint") is None else str(error.get("hint")),
                    details=details,
                )
            raise PipelineSdkError(str(error))
        return response.get("result")


def call(method: str, params: dict[str, Any]) -> Any:
    return ControlClient().call(method, params)


def supervised_sandbox_mode() -> bool:
    return os.environ.get("OPENZYME_SANDBOX_MODE") in {"s10", "s12"}


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def controlled_operation(
    *,
    sdk_module: str,
    function_name: str,
    route_policy_id: str,
    params: dict[str, Any],
    expected_outputs: Any,
    resource_estimate: dict[str, Any] | None = None,
    input_artifact_ids: list[str] | None = None,
    input_artifact_digests: list[str] | None = None,
    placement: str = "provider",
    hpc_workspace_id: str | None = None,
    stage_refs: list[dict[str, Any]] | None = None,
    planned_fetch_intent: dict[str, Any] | None = None,
) -> Any:
    params_digest = canonical_digest(params)
    envelope: dict[str, Any] = {
        "schema_version": "s12.adapter_envelope.v1",
        "sdk_module": sdk_module,
        "function_name": function_name,
        "route_policy_id": route_policy_id,
        "idempotency_key": f"{sdk_module}.{function_name}:{params_digest}",
        "params_digest": params_digest,
        "params": dict(params),
        "input_artifact_ids": list(input_artifact_ids or []),
        "input_artifact_digests": list(input_artifact_digests or []),
        "expected_outputs": expected_outputs,
        "resource_estimate": dict(resource_estimate or {}),
        "placement": placement,
        "stage_refs": [dict(item) for item in stage_refs or []],
        "planned_fetch_intent": dict(planned_fetch_intent or {}),
    }
    if hpc_workspace_id:
        envelope["hpc_workspace_id"] = hpc_workspace_id
    return call("s10.controlled_operation", envelope)


__all__ = [
    "ControlClient",
    "PipelineSdkError",
    "call",
    "canonical_digest",
    "controlled_operation",
    "supervised_sandbox_mode",
]
