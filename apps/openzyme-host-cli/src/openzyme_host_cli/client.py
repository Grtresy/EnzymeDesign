from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from typing import Protocol

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
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


class HostApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        session: SessionProtocol | None = None,
    ) -> None:
        self._owns_session = session is None
        self._session = session or httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self._base_url = base_url.rstrip("/")

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def _request_json(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        if method == "GET":
            response = self._session.get(path)
        elif method == "PATCH":
            response = self._session.patch(path, json=json_body)
        else:
            response = self._session.post(path, json=json_body)
        if response.status_code >= 400:
            raise HostApiError(response.status_code, _normalize_error_text(response))
        return response.json()

    def list_projects(self) -> list[dict[str, Any]]:
        return self._request_json("GET", "/projects")

    def list_project_episodes(self, project_id: str) -> list[dict[str, Any]]:
        return self._request_json("GET", f"/projects/{project_id}/episodes")

    def get_workspace(self, episode_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/episodes/{episode_id}/workspace")

    def get_pending_actions(self, episode_id: str) -> list[dict[str, Any]]:
        return self._request_json("GET", f"/episodes/{episode_id}/pending-actions")

    def get_runs(self, episode_id: str) -> list[dict[str, Any]]:
        return self._request_json("GET", f"/episodes/{episode_id}/runs")

    def get_artifacts(self, episode_id: str) -> list[dict[str, Any]]:
        return self._request_json("GET", f"/episodes/{episode_id}/artifacts")

    def get_reports(self, episode_id: str) -> list[dict[str, Any]]:
        return self._request_json("GET", f"/episodes/{episode_id}/reports")

    def create_episode(self, project_id: str, objective: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/commands/create_episode",
            json_body={"project_id": project_id, "objective": objective},
        )

    def resume_episode(self, episode_id: str, resume_payload: Any) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/commands/resume_episode",
            json_body={"episode_id": episode_id, "resume_payload": resume_payload},
        )

    def resolve_approval(self, episode_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/commands/resolve_approval",
            json_body={
                "episode_id": episode_id,
                "approval_id": approval_id,
                "decision": decision,
            },
        )

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

    def claim_v3_lane(self, lane_id: str, claimed_ref: str) -> dict[str, Any]:
        return self._request_json("POST", f"/v3/lanes/{lane_id}/claim", json_body={"claimed_ref": claimed_ref})

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
