from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from typing import Protocol
from uuid import uuid4

import httpx


class ResponseProtocol(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class SessionProtocol(Protocol):
    def get(self, url: str, **kwargs: Any) -> ResponseProtocol: ...
    def post(self, url: str, **kwargs: Any) -> ResponseProtocol: ...
    def patch(self, url: str, **kwargs: Any) -> ResponseProtocol: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class HostApiError(RuntimeError):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return f"Host API request failed ({self.status_code}): {self.detail}"


def _normalize_error_text(response: ResponseProtocol) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text or f"status {response.status_code}"
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        if isinstance(detail, str):
            return detail
        return json.dumps(detail, ensure_ascii=True, sort_keys=True)
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        error = payload["error"]
        code = str(error.get("code") or "host_api_error")
        message = str(error.get("message") or f"status {response.status_code}")
        return f"{code}: {message}"
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


class HostApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str | None = None,
        session: SessionProtocol | None = None,
    ) -> None:
        self._owns_session = session is None
        self._session = session or httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        if method != "GET":
            headers["Idempotency-Key"] = (
                idempotency_key or f"cli-{uuid4().hex}"
            )
        if method == "GET":
            response = self._session.get(path, headers=headers)
        elif method == "PATCH":
            response = self._session.patch(path, json=json_body, headers=headers)
        else:
            response = self._session.post(path, json=json_body, headers=headers)
        if response.status_code >= 400:
            raise HostApiError(response.status_code, _normalize_error_text(response))
        return response.json()

    def create_v3_session(
        self,
        *,
        project_id: str,
        objective: str,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"project_id": project_id, "objective": objective}
        if title:
            body["title"] = title
        if session_id:
            body["session_id"] = session_id
        return self._request_json("POST", "/v3/sessions", json_body=body)

    def get_v3_workspace(self, session_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v3/sessions/{session_id}/workspace")

    def get_v3_runtime_health(self) -> dict[str, Any]:
        return self._request_json("GET", "/v3/runtime/health")

    def get_v3_scientific_attempts(self, session_id: str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v3/sessions/{session_id}/scientific-attempts",
        )

    def grant_v3_scientific_attempt_authorization(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v3/sessions/{session_id}/scientific-attempt-authorizations",
            json_body=payload,
            idempotency_key=idempotency_key,
        )

    def execute_v3_scientific_attempt_command(
        self,
        session_id: str,
        *,
        command: str,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v3/sessions/{session_id}/scientific-attempt-commands",
            json_body={"command": command, "arguments": arguments},
            idempotency_key=idempotency_key,
        )

    def finalize_v3_scientific_attempt_closure(
        self,
        session_id: str,
        *,
        closure_request_id: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v3/sessions/{session_id}/scientific-attempt-closures/finalize",
            json_body={"closure_request_id": closure_request_id},
        )

    def finalize_v3_scientific_attempt_admission(
        self,
        session_id: str,
        *,
        admission_request_id: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v3/sessions/{session_id}/scientific-attempt-admissions/finalize",
            json_body={"admission_request_id": admission_request_id},
        )

    def post_v3_message(
        self,
        session_id: str,
        *,
        message: str,
        task_id: str | None = None,
        lane_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"message": message}
        if task_id:
            body["task_id"] = task_id
        if lane_id:
            body["lane_id"] = lane_id
        return self._request_json("POST", f"/v3/sessions/{session_id}/messages", json_body=body)

    def create_v3_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/v3/tasks", json_body=payload)

    def update_v3_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("PATCH", f"/v3/tasks/{task_id}", json_body=payload)

    def create_v3_lane(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/v3/lanes", json_body=payload)

    def claim_v3_lane(self, lane_id: str) -> dict[str, Any]:
        return self._request_json("POST", f"/v3/lanes/{lane_id}/claim", json_body={})

    def keep_v3_lane(self, lane_id: str) -> dict[str, Any]:
        return self._request_json("POST", f"/v3/lanes/{lane_id}/keep", json_body={})

    def remove_v3_lane(self, lane_id: str) -> dict[str, Any]:
        return self._request_json("POST", f"/v3/lanes/{lane_id}/remove", json_body={})

    def resolve_v3_approval(self, approval_id: str, decision: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v3/approvals/{approval_id}/resolve",
            json_body={"decision": decision},
        )
