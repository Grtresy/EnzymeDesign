from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from typing import Protocol
from uuid import uuid4

import httpx

from .receipts import append_public_api_receipt
from .receipts import parse_sse_events


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
        receipt_chain: Path | None = None,
    ) -> None:
        self._owns_session = session is None
        self._session = session or httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._receipt_chain = receipt_chain
        self.last_receipt: dict[str, Any] | None = None

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
        event_stream: bool = False,
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
        self.last_receipt = None
        if self._receipt_chain is not None:
            self.last_receipt = append_public_api_receipt(
                self._receipt_chain,
                method=method,
                route=path,
                request_body=json_body,
                response=response,
            )
        if response.status_code >= 400:
            raise HostApiError(response.status_code, _normalize_error_text(response))
        return parse_sse_events(response.text) if event_stream else response.json()

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

    def get_v3_events(self, session_id: str, *, after_cursor: int) -> list[dict[str, Any]]:
        return self._request_json(
            "GET",
            f"/v3/sessions/{session_id}/events?replay=1&after_cursor={after_cursor}",
            event_stream=True,
        )

    def get_v3_pending_approvals(self, session_id: str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v3/sessions/{session_id}/pending-approvals",
        )

    def get_v3_runtime_health(self) -> dict[str, Any]:
        return self._request_json("GET", "/v3/runtime/health")

    def drain_v3_runtime(
        self,
        session_id: str,
        *,
        max_signals: int,
        max_steps_per_agent: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v3/sessions/{session_id}/runtime/drain",
            json_body={
                "max_signals": max_signals,
                "max_steps_per_agent": max_steps_per_agent,
                "auto_enqueue_ready_tasks": False,
            },
            idempotency_key=idempotency_key,
        )

    def get_v3_runtime_command(
        self,
        session_id: str,
        command_id: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v3/sessions/{session_id}/runtime/commands/{command_id}",
        )

    def get_v3_scientific_attempts(self, session_id: str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v3/sessions/{session_id}/scientific-attempts",
        )

    def export_v3_closed_scientific_attempt_evidence(
        self,
        session_id: str,
        *,
        attempt_id: str,
        selection_id: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v3/sessions/{session_id}/scientific-attempts/{attempt_id}/"
            f"selections/{selection_id}/evidence",
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

    def inject_v3_aox_reference_fault(
        self,
        session_id: str,
        *,
        attempt_id: str,
        artifact_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
            json_body={"attempt_id": attempt_id, "artifact_id": artifact_id},
            idempotency_key=idempotency_key,
        )

    def post_v3_message(
        self,
        session_id: str,
        *,
        message: str,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"message": message}
        if task_id:
            body["task_id"] = task_id
        if lane_id:
            body["lane_id"] = lane_id
        if skill_keys:
            body["skill_keys"] = list(skill_keys)
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
