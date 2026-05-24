from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
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
        super().__init__(message)
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


__all__ = ["ControlClient", "PipelineSdkError", "call"]
