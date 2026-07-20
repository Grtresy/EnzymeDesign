from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import uuid4


# Keep this wire-contract value identical to the Host-side control server.  The
# container SDK deliberately has no package dependencies, so the scalar is
# duplicated instead of importing the Host runtime.
CONTROL_SOCKET_FRAME_MAX_BYTES = 4 * 1024 * 1024
_CONTROL_SOCKET_CHUNK_BYTES = 64 * 1024
CONTROL_SOCKET_IO_TIMEOUT_SECONDS = 5.0


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r} is forbidden")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


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
        try:
            request_payload = json.dumps(
                request,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise PipelineSdkError(
                "control socket request is not valid JSON",
                error_code="sandbox_transport_request_invalid",
                stage="control_socket_request",
                retryable=False,
            ) from exc
        if len(request_payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
            raise PipelineSdkError(
                "control socket request exceeds the bounded transport limit",
                error_code="sandbox_transport_request_too_large",
                stage="control_socket_request",
                retryable=False,
                details={
                    "max_bytes": CONTROL_SOCKET_FRAME_MAX_BYTES,
                    "size_bytes": len(request_payload),
                },
            )
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(CONTROL_SOCKET_IO_TIMEOUT_SECONDS)
                client.connect(self.socket_path)
                client.sendall(request_payload + b"\n")
                # A controlled operation can legitimately remain paused in the
                # Host while it waits for approval or a provider/HPC result.  Its
                # outer sandbox/approval lifecycle owns that wait.  The fixed
                # socket timeout applies again only after the Host starts a
                # response, so a stalled partial frame still fails closed.
                client.settimeout(None)
                try:
                    response_payload = self._read_response_frame(client)
                except TimeoutError as exc:
                    raise PipelineSdkError(
                        "control socket response timed out before its newline delimiter",
                        error_code="sandbox_transport_response_timeout",
                        stage="control_socket_response",
                        retryable=False,
                    ) from exc
        except OSError as exc:
            raise PipelineSdkError(
                "control socket is unavailable",
                error_code="sandbox_transport_unavailable",
                stage="control_socket_transport",
                retryable=False,
            ) from exc
        response = self._decode_response_frame(
            response_payload,
            request_id=request["id"],
        )
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                details = error.get("details")
                if not isinstance(details, dict):
                    details = {} if details is None else {"value": details}
                retryable = error.get("retryable")
                raise PipelineSdkError(
                    str(error.get("message") or error),
                    error_code=None if error.get("error_code") is None else str(error.get("error_code")),
                    stage=None if error.get("stage") is None else str(error.get("stage")),
                    retryable=retryable if isinstance(retryable, bool) else None,
                    hint=None if error.get("hint") is None else str(error.get("hint")),
                    details=details,
                )
            raise PipelineSdkError(str(error))
        return response.get("result")

    @staticmethod
    def _read_response_frame(client: socket.socket) -> bytes:
        payload = bytearray()
        response_started = False
        while True:
            remaining = CONTROL_SOCKET_FRAME_MAX_BYTES - len(payload) + 1
            chunk = client.recv(min(_CONTROL_SOCKET_CHUNK_BYTES, remaining))
            if not chunk:
                raise PipelineSdkError(
                    "control socket response ended before its newline delimiter",
                    error_code="sandbox_transport_response_invalid",
                    stage="control_socket_response",
                    retryable=False,
                )
            if not response_started:
                client.settimeout(CONTROL_SOCKET_IO_TIMEOUT_SECONDS)
                response_started = True
            newline_index = chunk.find(b"\n")
            if newline_index >= 0:
                payload.extend(chunk[:newline_index])
                if len(payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
                    raise PipelineSdkError(
                        "control socket response exceeds the bounded transport limit",
                        error_code="sandbox_transport_response_too_large",
                        stage="control_socket_response",
                        retryable=False,
                    )
                if chunk[newline_index + 1 :].strip():
                    raise PipelineSdkError(
                        "control socket returned more than one response frame",
                        error_code="sandbox_transport_response_invalid",
                        stage="control_socket_response",
                        retryable=False,
                    )
                return bytes(payload)
            payload.extend(chunk)
            if len(payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
                raise PipelineSdkError(
                    "control socket response exceeds the bounded transport limit",
                    error_code="sandbox_transport_response_too_large",
                    stage="control_socket_response",
                    retryable=False,
                )

    @staticmethod
    def _decode_response_frame(payload: bytes, *, request_id: str) -> dict[str, Any]:
        try:
            response = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise PipelineSdkError(
                "control socket response is not valid UTF-8 JSON",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            ) from exc
        if not isinstance(response, dict):
            raise PipelineSdkError(
                "control socket response must contain a JSON object",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            )
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
            raise PipelineSdkError(
                "control socket response identity is invalid",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            )
        has_result = "result" in response
        has_error = "error" in response
        if has_result == has_error:
            raise PipelineSdkError(
                "control socket response must contain exactly one result or error",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            )
        return response


def call(method: str, params: dict[str, Any]) -> Any:
    return ControlClient().call(method, params)


def supervised_sandbox_mode() -> bool:
    return os.environ.get("OPENZYME_SANDBOX_MODE") in {"s10", "s12"}


def canonical_digest(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise PipelineSdkError(
            "canonical digest input is not valid JSON",
            error_code="sandbox_transport_request_invalid",
            stage="control_socket_request",
            retryable=False,
        ) from exc
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
    "CONTROL_SOCKET_FRAME_MAX_BYTES",
    "ControlClient",
    "PipelineSdkError",
    "call",
    "canonical_digest",
    "controlled_operation",
    "supervised_sandbox_mode",
]
