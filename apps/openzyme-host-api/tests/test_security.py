from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
import pytest

from openzyme_core import RuntimeWriteFencingError
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain.control_plane import utc_now_iso
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import HostPrincipal
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import build_local_eval_foundation
from openzyme_host_api import create_app
from openzyme_host_api.app import _api_error_payload
from openzyme_host_api.app import _as_http_error
from openzyme_runtime import get_llm_debug_recorder


ALICE_TOKEN = "alice-token-0123456789abcdef01234567"
BOB_TOKEN = "bob-token-0123456789abcdef0123456789"
OPERATOR_TOKEN = "operator-token-0123456789abcdef0123"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _shared_policy(*, debug_enabled: bool = False) -> HostSecurityPolicy:
    return HostSecurityPolicy(
        deployment_profile="shared",
        principals_by_digest={
            _digest(ALICE_TOKEN): HostPrincipal(
                principal_id="user:alice",
                roles=frozenset({"user"}),
                project_ids=frozenset({"proj_shared"}),
            ),
            _digest(BOB_TOKEN): HostPrincipal(
                principal_id="user:bob",
                roles=frozenset({"user"}),
                project_ids=frozenset({"proj_shared"}),
            ),
            _digest(OPERATOR_TOKEN): HostPrincipal(
                principal_id="user:operator",
                roles=frozenset({"operator"}),
                project_ids=frozenset({"proj_shared"}),
            ),
        },
        debug_enabled=debug_enabled,
    )


def _headers(token: str, *, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def test_shared_profile_authenticates_and_persists_session_ownership() -> None:
    dependencies = HostApiDependencies(
        foundation=build_local_eval_foundation(),
        security_policy=_shared_policy(),
    )
    with TestClient(create_app(dependencies)) as client:
        unauthenticated = client.get("/v3/projects/proj_shared/sessions")
        invalid = client.get(
            "/v3/projects/proj_shared/sessions",
            headers={"Authorization": "Bearer invalid-token"},
        )
        missing_idempotency = client.post(
            "/v3/sessions",
            headers=_headers(ALICE_TOKEN),
            json={"project_id": "proj_shared", "objective": "Secure session"},
        )
        wrong_project = client.post(
            "/v3/sessions",
            headers=_headers(ALICE_TOKEN, key="wrong-project"),
            json={"project_id": "proj_other", "objective": "Forbidden"},
        )
        created = client.post(
            "/v3/sessions",
            headers=_headers(ALICE_TOKEN, key="alice-create"),
            json={
                "session_id": "sess_alice",
                "project_id": "proj_shared",
                "objective": "Secure session",
            },
        )

        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["www-authenticate"] == "Bearer"
        assert invalid.status_code == 401
        assert missing_idempotency.status_code == 428
        assert wrong_project.status_code == 404
        assert created.status_code == 200
        assert created.headers["x-openzyme-deployment-profile"] == "shared"

        bob_list = client.get(
            "/v3/projects/proj_shared/sessions",
            headers=_headers(BOB_TOKEN),
        )
        bob_get = client.get(
            "/v3/sessions/sess_alice",
            headers=_headers(BOB_TOKEN),
        )
        alice_get = client.get(
            "/v3/sessions/sess_alice",
            headers=_headers(ALICE_TOKEN),
        )
        alice_drain = client.post(
            "/v3/sessions/sess_alice/runtime/drain",
            headers=_headers(ALICE_TOKEN, key="alice-drain"),
            json={},
        )
        operator_created = client.post(
            "/v3/sessions",
            headers=_headers(OPERATOR_TOKEN, key="operator-create"),
            json={
                "session_id": "sess_operator",
                "project_id": "proj_shared",
                "objective": "Operate runtime",
            },
        )
        operator_drain = client.post(
            "/v3/sessions/sess_operator/runtime/drain",
            headers=_headers(OPERATOR_TOKEN, key="operator-drain"),
            json={},
        )

        assert bob_list.json() == []
        assert bob_get.status_code == 404
        assert alice_get.status_code == 200
        assert alice_drain.status_code == 403
        assert operator_created.status_code == 200
        assert operator_drain.status_code == 200
        with dependencies.v3_repository_scope(mode="read") as repositories:
            owner = repositories.session_access.get("sess_alice", "user:alice")
            assert owner is not None
            assert owner.access_role == "owner"


def test_shared_profile_derives_approval_actor_and_rejects_forged_actor() -> None:
    dependencies = HostApiDependencies(
        foundation=build_local_eval_foundation(),
        security_policy=_shared_policy(),
    )
    with TestClient(create_app(dependencies)) as client:
        created = client.post(
            "/v3/sessions",
            headers=_headers(ALICE_TOKEN, key="approval-session"),
            json={
                "session_id": "sess_approval_actor",
                "project_id": "proj_shared",
                "objective": "Audit approval identity",
            },
        )
        assert created.status_code == 200
        now = utc_now_iso()
        with dependencies.v3_repository_scope(mode="write") as repositories:
            repositories.approvals.save(
                ApprovalRequest(
                    approval_id="appr_actor",
                    session_id="sess_approval_actor",
                    task_id=None,
                    lane_id=None,
                    kind="operator_review",
                    requested_action="continue",
                    status=ApprovalRequestStatus.PENDING,
                    request_ref=None,
                    resolution_ref=None,
                    created_at=now,
                    resolved_at=None,
                )
            )

        forged = client.post(
            "/v3/approvals/appr_actor/resolve",
            headers=_headers(ALICE_TOKEN, key="forged-actor"),
            json={"decision": "approved", "actor_ref": "user:admin"},
        )
        resolved = client.post(
            "/v3/approvals/appr_actor/resolve",
            headers=_headers(ALICE_TOKEN, key="valid-actor"),
            json={"decision": "approved"},
        )
        events = client.get(
            "/v3/sessions/sess_approval_actor/events?replay=1",
            headers=_headers(ALICE_TOKEN),
        )

        assert forged.status_code == 422
        assert resolved.status_code == 200
        assert '"actor_ref":"user:alice"' in events.text


def test_shared_debug_surface_is_disabled_or_operator_only_and_sanitized() -> None:
    disabled_dependencies = HostApiDependencies(
        foundation=build_local_eval_foundation(),
        security_policy=_shared_policy(debug_enabled=False),
    )
    with TestClient(create_app(disabled_dependencies)) as disabled_client:
        disabled = disabled_client.get(
            "/debug/llm-calls",
            headers=_headers(OPERATOR_TOKEN),
        )
        assert disabled.status_code == 404

    recorder = get_llm_debug_recorder()
    recorder.clear()
    span = recorder.begin(
        purpose="security_test",
        kind="chat",
        model="test",
        base_url="https://user:pass@example.test/v1?token=secret",
        request={
            "Authorization": f"Bearer {ALICE_TOKEN}",
            "api_key": "top-secret",
            "input_path": "/home/user/private/input.pdb",
        },
    )
    span.finish(response={"content": "result at /tmp/private/output.json"})

    enabled_dependencies = HostApiDependencies(
        foundation=build_local_eval_foundation(),
        security_policy=_shared_policy(debug_enabled=True),
    )
    with TestClient(create_app(enabled_dependencies)) as client:
        regular = client.get(
            "/debug/llm-calls",
            headers=_headers(ALICE_TOKEN),
        )
        operator = client.get(
            "/debug/llm-calls",
            headers=_headers(OPERATOR_TOKEN),
        )

        assert regular.status_code == 403
        assert operator.status_code == 200
        record = operator.json()[0]
        assert record["request"]["Authorization"] == "[REDACTED]"
        assert record["request"]["api_key"] == "[REDACTED]"
        assert record["base_url"] == "https://example.test/v1"
        assert record["request"]["input_path"] == "[HOST_PATH]"
        assert record["response"]["content"] == "result at [HOST_PATH]"


def test_public_api_error_payload_sanitizes_private_diagnostics() -> None:
    payload = _api_error_payload(
        code="internal_error",
        message="failed at /home/operator/private.toml",
        hint="inspect storage://private/error-log",
        details={
            "access_token": "raw-token",
            "reason": "socket at /tmp/openzyme/private.sock",
        },
    )
    serialized = str(payload)

    assert "/home/operator" not in serialized
    assert "/tmp/openzyme" not in serialized
    assert "storage://" not in serialized
    assert "raw-token" not in serialized
    assert "access_token" not in serialized


def test_public_api_runtime_write_fence_is_typed_and_fail_closed() -> None:
    error = _as_http_error(
        RuntimeWriteFencingError(
            "stale lease sk-abcdefghijklmnop rejected at /tmp/private-runtime.sock"
        )
    )
    serialized = str(error.detail)

    assert error.status_code == 500
    assert error.detail == {
        "code": "runtime_write_fenced",
        "message": (
            "session runtime write was rejected because its lease fence is no longer "
            "authoritative"
        ),
        "hint": (
            "Fail closed for the current runtime attempt; acquire a fresh session "
            "runtime lease before any further write."
        ),
        "details": {
            "boundary": "session_runtime_write_fence",
            "disposition": "fail_closed",
        },
    }
    assert "sk-abcdefghijklmnop" not in serialized
    assert "/tmp/private-runtime.sock" not in serialized


@pytest.mark.parametrize(
    "private_code",
    (
        "/home/operator/private-code",
        "sk-abcdefghijklmnop",
        "AKIAABCDEFGHIJKLMNOP",
    ),
)
def test_public_api_error_payload_rejects_private_machine_code(
    private_code: str,
) -> None:
    payload = _api_error_payload(
        code=private_code,
        message="request failed",
    )

    assert payload["error"]["code"] == "internal_error"
    assert private_code not in str(payload)
