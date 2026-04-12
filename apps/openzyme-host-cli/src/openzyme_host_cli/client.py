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
        response = (
            self._session.get(path)
            if method == "GET"
            else self._session.post(path, json=json_body)
        )
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
