from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

import pytest

from openzyme_host_cli.client import HostApiClient
from openzyme_host_cli.cli import _build_parser
from openzyme_host_cli.cli import run_cli
from openzyme_host_cli.receipts import PUBLIC_API_RECEIPT_V2_FIELDS
from openzyme_host_cli.receipts import PublicReceiptError
from openzyme_host_cli.receipts import append_public_api_receipt
from openzyme_host_cli.receipts import canonical_json_bytes
from openzyme_runtime import reset_settings_cache


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None]] = []
        self.last_headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
        self.calls.append(("GET", url, None))
        if url == "/v3/runtime/health":
            return FakeResponse(
                200,
                {
                    "schema_version": "v3.runtime_health.v1",
                    "status": "degraded",
                    "deployment_profile": "local-dev",
                    "storage_profile": "single_process_sqlite",
                    "observed_at": "2026-07-16T00:00:00+00:00",
                    "components": {
                        "control_plane": {"status": "ready", "details": {}},
                        "model": {"status": "unavailable", "details": {}},
                    },
                },
            )
        if url.startswith("/v3/mutation-operations/observe?"):
            return FakeResponse(
                200,
                {
                    "schema_id": "host_mutation_operation_observation@1",
                    "status": "unproven",
                    "query_read_only": True,
                    "resume_applicable": False,
                },
            )
        if url.startswith("/v3/sessions/") and url.endswith("/workspace"):
            return FakeResponse(200, build_v3_workspace())
        if url.startswith("/v3/sessions/") and url.endswith(
            "/scientific-attempts"
        ):
            return FakeResponse(
                200,
                {
                    "schema_id": "scientific_attempt_workspace@1",
                    "authorizations": [],
                    "attempts": [],
                },
            )
        if "/runtime/commands/" in url:
            return FakeResponse(
                200,
                {
                    "schema_version": "runtime_command_status@1",
                    "session_id": "sess_001",
                    "command_id": "runtime_command_001",
                    "command_type": "runtime.drain",
                    "status": "failed",
                    "status_url": url,
                    "accepted_at": "2026-07-24T00:00:00+00:00",
                    "started_at": "2026-07-24T00:00:01+00:00",
                    "completed_at": "2026-07-24T00:00:02+00:00",
                    "bounded_outcome_summary": {
                        "schema_version": "runtime_command_outcome@2",
                        "core_receipt_formed": True,
                        "scheduler_status": "completed",
                        "processed_signal_count": 1,
                        "suspended": False,
                        "projection_status": "failed",
                        "projection_error_code": "runtime_projection_failed",
                        "projection_failed_stage": "runtime_consistency",
                        "replay_safe": False,
                        "output_count": 0,
                        "output_ids": [],
                        "output_ids_truncated": False,
                        "event_count": 1,
                        "event_ids": ["evt_001"],
                        "event_ids_truncated": False,
                    },
                    "error_code": "runtime_projection_failed",
                    "safe_error_summary": "Consistency projection failed.",
                    "safe_retry_hint": "Inspect canonical state before retry.",
                },
            )
        return FakeResponse(200, [])

    def post(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
        self.calls.append(("POST", url, kwargs.get("json")))
        if url.endswith("/runtime/drain"):
            return FakeResponse(
                202,
                {
                    "schema_version": "runtime_command_status@1",
                    "session_id": "sess_001",
                    "command_id": "runtime_command_001",
                    "command_type": "runtime.drain",
                    "status": "accepted",
                    "status_url": (
                        "/v3/sessions/sess_001/runtime/commands/"
                        "runtime_command_001"
                    ),
                    "accepted_at": "2026-07-24T00:00:00+00:00",
                    "started_at": None,
                    "completed_at": None,
                    "bounded_outcome_summary": None,
                    "error_code": None,
                    "safe_error_summary": None,
                    "safe_retry_hint": None,
                },
            )
        return FakeResponse(
            200,
            {
                "session_id": "sess_001",
                "status": "completed",
                "outputs": ["Received: hello"],
                "workspace": build_v3_workspace(),
                "events": [{"event_type": "conversation.assistant_message"}],
            },
        )

    def patch(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
        self.calls.append(("PATCH", url, kwargs.get("json")))
        return FakeResponse(
            200,
            {
                "task": {
                    "task_id": "task_001",
                    "session_id": "sess_001",
                    "subject": "Task",
                    "description": "",
                    "status": "in_progress",
                    "priority": "normal",
                    "kind": "general",
                    "assigned_ref": None,
                    "lane_id": None,
                    "blocked_by": [],
                    "created_at": "2026-04-20T00:00:00+00:00",
                    "updated_at": "2026-04-20T00:00:00+00:00",
                },
                "workspace": build_v3_workspace(),
                "events": [{"event_type": "task.updated"}],
            },
        )

    def close(self) -> None:
        return None


class FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class FailingSession(FakeSession):
    def get(self, url: str, **kwargs):
        if url.endswith("/scientific-attempts"):
            self.last_headers = dict(kwargs.get("headers") or {})
            self.calls.append(("GET", url, None))
            return FakeResponse(
                403,
                {
                    "error": {
                        "code": "scientific_read_forbidden",
                        "message": "denied at /home/private/control.sqlite3",
                        "details": {"api_key": "sk-private"},
                    }
                },
            )
        return super().get(url, **kwargs)


def test_client_rejects_historical_chain_before_http(tmp_path: Path) -> None:
    chain = tmp_path / "historical.jsonl"
    current = append_public_api_receipt(
        chain,
        method="GET",
        route="/v3/runtime/health",
        request_body=None,
        response=FakeResponse(200, {"status": "ready"}),
    )
    historical = {
        key: value for key, value in current.items() if key in PUBLIC_API_RECEIPT_V2_FIELDS
    }
    historical["schema_id"] = "openzyme_public_api_receipt@2"
    chain.write_bytes(canonical_json_bytes(historical) + b"\n")
    session = FakeSession()
    client = HostApiClient(
        "http://127.0.0.1:8000",
        session=session,
        receipt_chain=chain,
    )

    with pytest.raises(PublicReceiptError, match="read-only"):
        client.get_v3_runtime_health()
    assert session.calls == []


def test_cli_encodes_exact_mutation_observation_identity() -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession()
    request_digest = "sha256:" + "a" * 64

    exit_code = run_cli(
        [
            "--session-id",
            "sess observe/1",
            "--format",
            "json",
            "operations",
            "observe",
            "--command-type",
            "task.update",
            "--scope-ref",
            "task:task observe/1",
            "--idempotency-key",
            "observe:key/1",
            "--request-digest",
            request_digest,
        ],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    assert session.calls == [
        (
            "GET",
            "/v3/mutation-operations/observe?"
            "session_id=sess+observe%2F1&command_type=task.update&"
            "scope_ref=task%3Atask+observe%2F1&"
            "idempotency_key=observe%3Akey%2F1&"
            f"request_digest=sha256%3A{'a' * 64}",
            None,
        )
    ]
    assert json.loads(stdout.getvalue())["query_read_only"] is True


def build_v3_workspace() -> dict[str, object]:
    return {
        "session": {
            "session_id": "sess_001",
            "project_id": "proj_001",
            "title": "V3",
            "objective": "Plan with V3",
            "status": "active",
            "created_at": "2026-04-20T00:00:00+00:00",
            "updated_at": "2026-04-20T00:00:00+00:00",
        },
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "task_001",
                        "subject": "Task",
                        "status": "todo",
                    },
                    "bucket": "ready",
                }
            ]
        },
        "lane_board": {"lanes": []},
        "pending_approvals": [],
        "reports": [],
    }


def test_cli_uses_env_defaults_and_wires_session_create(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_PROJECT_ID", "proj_001")
    monkeypatch.setenv("OPENZYME_HOST_AUTH_TOKEN", "cli-secret-token")
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["sessions", "create", "--objective", "Design an artifact workspace"],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/v3/sessions",
        {"project_id": "proj_001", "objective": "Design an artifact workspace"},
    )
    assert "Session sess_001" in stdout.getvalue()
    assert session.last_headers["Authorization"] == "Bearer cli-secret-token"
    assert session.last_headers["Idempotency-Key"].startswith("cli-")
    reset_settings_cache()


def test_cli_json_format_renders_raw_payload() -> None:
    stdout = StringIO()
    exit_code = run_cli(
        [
            "--format",
            "json",
            "sessions",
            "create",
            "--project-id",
            "proj_001",
            "--objective",
            "Plan with V3",
        ],
        session=FakeSession(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert '"session_id": "sess_001"' in stdout.getvalue()


def test_cli_v3_sessions_create_and_message() -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        [
            "sessions",
            "create",
            "--project-id",
            "proj_001",
            "--session-id",
            "sess_001",
            "--objective",
            "Plan with V3",
        ],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/v3/sessions",
        {"project_id": "proj_001", "objective": "Plan with V3", "session_id": "sess_001"},
    )
    assert "Session sess_001" in stdout.getvalue()

    stdout = StringIO()
    exit_code = run_cli(
        ["sessions", "message", "--session-id", "sess_001", "--message", "hello"],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == ("POST", "/v3/sessions/sess_001/messages", {"message": "hello"})
    assert "Received: hello" in stdout.getvalue()


def test_cli_v3_task_update_uses_patch() -> None:
    stdout = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["tasks", "update", "--task-id", "task_001", "--status", "in_progress"],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == ("PATCH", "/v3/tasks/task_001", {"status": "in_progress"})


def test_cli_runtime_drain_and_status_render_two_layer_receipt() -> None:
    session = FakeSession()
    stdout = StringIO()

    exit_code = run_cli(
        [
            "--session-id",
            "sess_001",
            "runtime",
            "drain",
            "--max-signals",
            "1",
            "--max-steps-per-agent",
            "2",
            "--idempotency-key",
            "drain:cli-test",
        ],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/v3/sessions/sess_001/runtime/drain",
        {
            "max_signals": 1,
            "max_steps_per_agent": 2,
            "auto_enqueue_ready_tasks": False,
        },
    )
    assert session.last_headers["Idempotency-Key"] == "drain:cli-test"
    assert "Command status: accepted" in stdout.getvalue()
    assert "Outcome schema: unavailable" in stdout.getvalue()

    stdout = StringIO()
    exit_code = run_cli(
        [
            "--session-id",
            "sess_001",
            "runtime",
            "status",
            "--command-id",
            "runtime_command_001",
        ],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    rendered = stdout.getvalue()
    assert exit_code == 0
    assert session.calls[-1] == (
        "GET",
        (
            "/v3/sessions/sess_001/runtime/commands/"
            "runtime_command_001"
        ),
        None,
    )
    assert "Command status: failed" in rendered
    assert "Scheduler: completed" in rendered
    assert "Processed signals: 1" in rendered
    assert "Projection: failed" in rendered
    assert "Projection stage: runtime_consistency" in rendered
    assert "Replay safe: False" in rendered
    assert "Projection: unavailable" not in rendered


def test_cli_runtime_status_preserves_historical_v1_uncertainty() -> None:
    session = FakeSession()
    original_get = session.get

    def historical_get(url: str, **kwargs):
        if "/runtime/commands/" not in url:
            return original_get(url, **kwargs)
        session.last_headers = dict(kwargs.get("headers") or {})
        session.calls.append(("GET", url, None))
        return FakeResponse(
            200,
            {
                "schema_version": "runtime_command_status@1",
                "session_id": "sess_001",
                "command_id": "runtime_command_historical",
                "command_type": "runtime.drain",
                "status": "failed",
                "status_url": url,
                "accepted_at": "2026-07-20T00:00:00+00:00",
                "started_at": "2026-07-20T00:00:01+00:00",
                "completed_at": "2026-07-20T00:00:02+00:00",
                "bounded_outcome_summary": {
                    "schema_version": "runtime_command_outcome@1",
                    "processed_signal_count": 0,
                    "suspended": False,
                },
                "error_code": "runtime_command_execution_failed",
                "safe_error_summary": "Historical command failed.",
                "safe_retry_hint": None,
            },
        )

    session.get = historical_get
    stdout = StringIO()

    exit_code = run_cli(
        [
            "--session-id",
            "sess_001",
            "runtime",
            "status",
            "--command-id",
            "runtime_command_historical",
        ],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    rendered = stdout.getvalue()
    assert exit_code == 0
    assert "Outcome schema: runtime_command_outcome@1" in rendered
    assert "Scheduler: unavailable in historical @1 receipt" in rendered
    assert "Projection: unavailable in historical @1 receipt" in rendered
    assert "Replay safe: unknown for historical @1 receipt" in rendered


def test_cli_scientific_inspect_remains_and_mutation_finalizers_are_retired() -> None:
    session = FakeSession()
    stdout = StringIO()
    assert (
        run_cli(
            [
                "--session-id",
                "sess_001",
                "scientific",
                "inspect",
            ],
            session=session,
            stdout=stdout,
            stderr=StringIO(),
        )
        == 0
    )
    assert session.calls[-1] == (
        "GET",
        "/v3/sessions/sess_001/scientific-attempts",
        None,
    )

    parser = _build_parser()
    resources = parser._subparsers._group_actions[0].choices
    scientific = resources["scientific"]._subparsers._group_actions[0].choices
    assert "inspect" in scientific
    assert "export-evidence" in scientific
    assert "command" not in scientific
    assert "finalize-admission" not in scientific
    assert "finalize" not in scientific


def test_cli_exports_and_seals_closed_attempt_evidence(
    tmp_path: Path,
) -> None:
    session = FakeSession()
    receipt_chain = tmp_path / "public-api-receipts.jsonl"
    sealed_response = tmp_path / "evidence-response.json"

    exit_code = run_cli(
        [
            "--session-id",
            "sess_001",
            "--receipt-chain",
            str(receipt_chain),
            "--seal-response",
            str(sealed_response),
            "scientific",
            "export-evidence",
            "--attempt-id",
            "attempt_001",
            "--selection-id",
            "selection_001",
        ],
        session=session,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "GET",
        "/v3/sessions/sess_001/scientific-attempts/attempt_001/"
        "selections/selection_001/evidence",
        None,
    )
    receipt = json.loads(receipt_chain.read_text(encoding="utf-8"))
    envelope = json.loads(sealed_response.read_text(encoding="utf-8"))
    assert receipt["request"] == {}
    assert envelope["receipt"] == receipt
    assert envelope["response"] == []


def test_cli_seals_sanitized_non_2xx_public_response(tmp_path: Path) -> None:
    session = FailingSession()
    receipt_chain = tmp_path / "failed-receipt.jsonl"
    sealed_response = tmp_path / "failed-response.json"
    stderr = StringIO()

    exit_code = run_cli(
        [
            "--session-id",
            "sess_001",
            "--receipt-chain",
            str(receipt_chain),
            "--seal-response",
            str(sealed_response),
            "scientific",
            "inspect",
        ],
        session=session,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    receipt = json.loads(receipt_chain.read_text(encoding="utf-8"))
    envelope = json.loads(sealed_response.read_text(encoding="utf-8"))
    assert receipt["status_code"] == 403
    assert envelope["receipt"] == receipt
    assert envelope["response"] == {
        "error": {
            "code": "scientific_read_forbidden",
            "message": "denied at [redacted-host-path]",
            "details": {},
        }
    }
    assert "/home/private" not in stderr.getvalue()
    assert "sk-private" not in stderr.getvalue()


def test_cli_reaches_exact_aox_reference_fault_capability() -> None:
    session = FakeSession()

    exit_code = run_cli(
        [
            "--session-id",
            "sess_001",
            "scientific",
            "inject-aox-reference-fault",
            "--attempt-id",
            "attempt_fault",
            "--artifact-id",
            "artifact_ref21",
            "--idempotency-key",
            "fault-once",
        ],
        session=session,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/v3/sessions/sess_001/aox-fault-injections/reference-byte-flip",
        {"attempt_id": "attempt_fault", "artifact_id": "artifact_ref21"},
    )


def test_cli_reaches_public_events_and_pending_approvals() -> None:
    session = FakeSession()

    assert (
        run_cli(
            ["--session-id", "sess_001", "sessions", "events"],
            session=session,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        == 0
    )
    assert session.calls[-1] == (
        "GET",
        "/v3/sessions/sess_001/events?replay=1&after_cursor=0",
        None,
    )
    assert (
        run_cli(
            ["--session-id", "sess_001", "approvals", "pending"],
            session=session,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        == 0
    )
    assert session.calls[-1] == (
        "GET",
        "/v3/sessions/sess_001/pending-approvals",
        None,
    )


def test_cli_lane_claim_uses_server_owned_actor() -> None:
    session = FakeSession()

    exit_code = run_cli(
        ["lanes", "claim", "--lane-id", "lane_001"],
        session=session,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == ("POST", "/v3/lanes/lane_001/claim", {})


def test_cli_runtime_health_renders_public_projection() -> None:
    stdout = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["runtime", "health"],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == ("GET", "/v3/runtime/health", None)
    rendered = stdout.getvalue()
    assert "Runtime: degraded" in rendered
    assert "control_plane: ready" in rendered
    assert "model: unavailable" in rendered


class ErrorSession(FakeSession):
    def post(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
        self.calls.append(("POST", url, kwargs.get("json")))
        return FakeResponse(
            422,
            {
                "error": {
                    "code": "request_validation_error",
                    "message": "Request payload failed validation.",
                }
            },
        )


def test_cli_renders_structured_host_error() -> None:
    stderr = StringIO()

    exit_code = run_cli(
        [
            "sessions",
            "create",
            "--project-id",
            "proj_001",
            "--objective",
            "Invalid request",
        ],
        session=ErrorSession(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "request_validation_error: Request payload failed validation." in stderr.getvalue()
