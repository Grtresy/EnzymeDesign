from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


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


class ExecutionSdkError(RuntimeError):
    """Closed, safe error returned by the sandbox control protocol."""

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


# Temporary source-compatible name for openzyme-pipeline callers.  New callers
# import ExecutionSdkError from openzyme_execution_sdk.
PipelineSdkError = ExecutionSdkError


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
            raise ExecutionSdkError(
                "control socket request is not valid JSON",
                error_code="sandbox_transport_request_invalid",
                stage="control_socket_request",
                retryable=False,
            ) from exc
        if len(request_payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
            raise ExecutionSdkError(
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
                # A controlled operation can remain paused while Host waits for
                # approval or an external result.  The fixed timeout applies
                # again after the first response byte, bounding partial frames.
                client.settimeout(None)
                try:
                    response_payload = self._read_response_frame(client)
                except TimeoutError as exc:
                    raise ExecutionSdkError(
                        "control socket response timed out before its newline delimiter",
                        error_code="sandbox_transport_response_timeout",
                        stage="control_socket_response",
                        retryable=False,
                    ) from exc
        except OSError as exc:
            raise ExecutionSdkError(
                "control socket is unavailable",
                error_code="sandbox_transport_unavailable",
                stage="control_socket_transport",
                retryable=False,
            ) from exc
        response = self._decode_response_frame(response_payload, request_id=request["id"])
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                details = error.get("details")
                if not isinstance(details, dict):
                    details = {} if details is None else {"value": details}
                retryable = error.get("retryable")
                raise ExecutionSdkError(
                    str(error.get("message") or error),
                    error_code=(
                        None
                        if error.get("error_code") is None
                        else str(error.get("error_code"))
                    ),
                    stage=None if error.get("stage") is None else str(error.get("stage")),
                    retryable=retryable if isinstance(retryable, bool) else None,
                    hint=None if error.get("hint") is None else str(error.get("hint")),
                    details=details,
                )
            raise ExecutionSdkError(str(error))
        return response.get("result")

    @staticmethod
    def _read_response_frame(client: socket.socket) -> bytes:
        payload = bytearray()
        response_started = False
        while True:
            remaining = CONTROL_SOCKET_FRAME_MAX_BYTES - len(payload) + 1
            chunk = client.recv(min(_CONTROL_SOCKET_CHUNK_BYTES, remaining))
            if not chunk:
                raise ExecutionSdkError(
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
                    raise ExecutionSdkError(
                        "control socket response exceeds the bounded transport limit",
                        error_code="sandbox_transport_response_too_large",
                        stage="control_socket_response",
                        retryable=False,
                    )
                if chunk[newline_index + 1 :].strip():
                    raise ExecutionSdkError(
                        "control socket returned more than one response frame",
                        error_code="sandbox_transport_response_invalid",
                        stage="control_socket_response",
                        retryable=False,
                    )
                return bytes(payload)
            payload.extend(chunk)
            if len(payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
                raise ExecutionSdkError(
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
            raise ExecutionSdkError(
                "control socket response is not valid UTF-8 JSON",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            ) from exc
        if not isinstance(response, dict):
            raise ExecutionSdkError(
                "control socket response must contain a JSON object",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            )
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
            raise ExecutionSdkError(
                "control socket response identity is invalid",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            )
        has_result = "result" in response
        has_error = "error" in response
        if has_result == has_error:
            raise ExecutionSdkError(
                "control socket response must contain exactly one result or error",
                error_code="sandbox_transport_response_invalid",
                stage="control_socket_response",
                retryable=False,
            )
        return response


def call(method: str, params: dict[str, Any]) -> Any:
    return ControlClient().call(method, params)


def supervised_sandbox_mode() -> bool:
    return os.environ.get("OPENZYME_SANDBOX_MODE") == "file_workspace"


def canonical_digest(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise ExecutionSdkError(
            "canonical digest input is not valid JSON",
            error_code="sandbox_transport_request_invalid",
            stage="control_socket_request",
            retryable=False,
        ) from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = [
    "CONTROL_SOCKET_FRAME_MAX_BYTES",
    "CONTROL_SOCKET_IO_TIMEOUT_SECONDS",
    "ControlClient",
    "ExecutionSdkError",
    "PipelineSdkError",
    "call",
    "canonical_digest",
    "supervised_sandbox_mode",
]
