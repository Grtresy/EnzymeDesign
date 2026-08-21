from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from typing import Protocol

import httpx
from openzyme_client import ClientHttpRequest
from openzyme_client import ClientHttpResponse
from openzyme_client import OpenZymeV2Client
from openzyme_client import OpenZymeClientContractError
from openzyme_client import VerifiedServerContract
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import LayeredReleaseIdentity


class HttpResponseProtocol(Protocol):
    status_code: int
    content: bytes
    headers: Any


class HttpSessionProtocol(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None,
    ) -> HttpResponseProtocol: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SessionClientTransport:
    session: HttpSessionProtocol

    def send(self, request: ClientHttpRequest) -> ClientHttpResponse:
        response = self.session.request(
            request.method,
            request.path,
            headers=dict(request.headers),
            content=request.body,
        )
        return ClientHttpResponse(
            status_code=response.status_code,
            media_type=str(response.headers.get("content-type") or ""),
            body=bytes(response.content),
            headers={str(name): str(value) for name, value in response.headers.items()},
        )


class HostApiV2Client:
    """Thin CLI delivery wrapper around the shared exact @2 client guard."""

    def __init__(
        self,
        base_url: str,
        *,
        expected_release: LayeredReleaseIdentity,
        auth_token: str | None = None,
        session: HttpSessionProtocol | None = None,
    ) -> None:
        self._owns_session = session is None
        self._session: HttpSessionProtocol = session or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=30.0,
        )
        self._authorization = (
            f"Bearer {auth_token}" if auth_token else "Bearer local-dev"
        )
        self._client = OpenZymeV2Client(
            transport=SessionClientTransport(self._session),
            expected_release=expected_release,
        )

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def inspect_workspace(
        self,
        session_id: str,
    ) -> tuple[FileWorkspacePublicV2, VerifiedServerContract]:
        return self._client.inspect_workspace(
            session_id=session_id,
            authorization=self._authorization,
        )

    def create_session(
        self,
        *,
        project_id: str,
        session_id: str,
        objective: str,
        title: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "session_id": session_id,
            "objective": objective,
            "title": title or objective,
        }
        response = self._client.bootstrap_session(
            authorization=self._authorization,
            idempotency_key=idempotency_key,
            body=json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        return _decode_mutation_body(response.body)

    def send_json_mutation(
        self,
        *,
        session_id: str,
        path: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Inspect exact @2 state, then send one mutation bound to that scope."""

        _, verified = self.inspect_workspace(session_id)
        response = self._client.send_mutation(
            method="POST",
            path=path,
            authorization=self._authorization,
            idempotency_key=idempotency_key,
            body=json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            verified_contract=verified,
            capability_binding_digest=verified.capability_binding_digest,
            affordance_snapshot_digest=verified.affordance_snapshot_digest,
        )
        return _decode_mutation_body(response.body)

    def post_message(
        self,
        session_id: str,
        *,
        message: str,
        task_id: str | None,
        lane_id: str | None,
        skill_keys: tuple[str, ...],
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": message}
        if task_id is not None:
            payload["task_id"] = task_id
        if lane_id is not None:
            payload["lane_id"] = lane_id
        if skill_keys:
            payload["skill_keys"] = list(skill_keys)
        return self.send_json_mutation(
            session_id=session_id,
            path=f"/v3/sessions/{session_id}/messages",
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def drain_runtime(
        self,
        session_id: str,
        *,
        max_signals: int,
        max_steps_per_agent: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self.send_json_mutation(
            session_id=session_id,
            path=f"/v3/sessions/{session_id}/runtime/drain",
            idempotency_key=idempotency_key,
            payload={
                "max_signals": max_signals,
                "max_steps_per_agent": max_steps_per_agent,
                "auto_enqueue_ready_tasks": False,
            },
        )


def load_expected_release_identity(path: Path) -> LayeredReleaseIdentity:
    """Load one operator-pinned, closed @2 release identity without fallback."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return LayeredReleaseIdentity.from_dict(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OpenZymeClientContractError(
            "cli_release_identity_invalid",
            "configured release identity file is missing or violates the closed contract",
        ) from exc


def _decode_mutation_body(body: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenZymeClientContractError(
            "cli_mutation_response_payload_invalid",
            "Host mutation response is not valid UTF-8 JSON",
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
        ) from exc
    if not isinstance(decoded, dict):
        raise OpenZymeClientContractError(
            "cli_mutation_response_payload_invalid",
            "Host mutation response is not one JSON object",
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
        )
    return decoded

__all__ = [
    "HostApiV2Client",
    "HttpSessionProtocol",
    "SessionClientTransport",
    "load_expected_release_identity",
]
