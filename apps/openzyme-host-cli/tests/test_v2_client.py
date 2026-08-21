from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import json
from pathlib import Path

import pytest

from openzyme_client import OpenZymeClientContractError
from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_host_cli import HostApiV2Client
from openzyme_host_cli.cli import run_cli
from openzyme_host_cli.v2_client import load_expected_release_identity


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _release() -> LayeredReleaseIdentity:
    return LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("schema"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        route_catalog_digest=_digest("routes"),
        projection_catalog_digest=_digest("projections"),
        migration_catalog_digest=_digest("migrations"),
        workspace_backend_digest=_digest("workspace"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )


def _projection(release: LayeredReleaseIdentity) -> FileWorkspacePublicV2:
    arrays = {
        "tasks",
        "lanes",
        "agents",
        "approvals",
        "authority_leases",
        "publications",
    }
    core: dict[str, object] = {
        key: [] if key in arrays else {} for key in FILE_WORKSPACE_CORE_SECTION_FIELDS
    }
    binding_digest = _digest("binding")
    core["session"] = {"session_id": "session-1"}
    core["protocol"] = {"records": [], "inbox": []}
    core["conversation"] = {"messages": [], "memories": []}
    core["capability_binding"] = {"binding_digest": binding_digest}
    core["runtime"] = {
        "signals": [],
        "session_leases": [],
        "turn_commands": [],
        "continuation_intents": [],
        "settlement_intents": [],
        "outcome_consumptions": [],
    }
    core["workspace"] = {
        "generations": [],
        "runtime_bindings": [],
        "repository_binding_pins": [],
        "checkpoints": [],
        "revision_path_verifications": [],
    }
    core["operations"] = {
        "controlled": [],
        "continuations": [],
        "publication_intents": [],
        "task_evidence": [],
        "command_receipts": [],
    }
    core["failures"] = {"observations": []}
    core["tool_reflection"] = {
        "declared_tool_catalog_digest": release.declared_tool_catalog_digest,
        "capability_binding_digest": binding_digest,
        "affordance_snapshot_digest": _digest("affordance"),
        "available_tool_names": [],
        "affordances": [],
    }
    return FileWorkspacePublicV2(
        release=release,
        core=FileWorkspaceCoreProjectionV2(core),
        extensions=(),
    )


@dataclass(frozen=True)
class _Response:
    status_code: int
    content: bytes
    headers: dict[str, str]


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None,
    ) -> _Response:
        self.calls.append((method, url, headers, content))
        return self.response

    def close(self) -> None:
        raise AssertionError("injected session must not be closed by the client")


class _SequencedSession(_Session):
    def __init__(self, responses: list[_Response]) -> None:
        super().__init__(responses[0])
        self._responses = list(responses)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None,
    ) -> _Response:
        self.calls.append((method, url, headers, content))
        return self._responses.pop(0)


def _session(
    release: LayeredReleaseIdentity,
    *,
    media_type: str = FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
) -> _Session:
    projection = _projection(release)
    body = json.dumps(
        projection.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    binding_digest = _digest("binding")
    affordance_digest = _digest("affordance")
    return _Session(
        _Response(
            status_code=200,
            content=body,
            headers={
                "content-type": media_type,
                "OpenZyme-Workspace-Contract": (
                    FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
                ),
                "OpenZyme-Release-Digest": release.release_digest,
                "OpenZyme-Public-Contract-Digest": (
                    FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                ),
                "OpenZyme-Projection-Digest": projection.projection_digest,
                "OpenZyme-Capability-Binding-Digest": binding_digest,
                "OpenZyme-Affordance-Snapshot-Digest": affordance_digest,
            },
        )
    )


def test_cli_v2_client_delegates_exact_guard_to_openzyme_client() -> None:
    release = _release()
    session = _session(release)
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        auth_token="secret",
        session=session,
    )

    projection, verified = client.inspect_workspace("session-1")

    assert projection.core.payload["session"] == {"session_id": "session-1"}
    assert verified.release_digest == release.release_digest
    method, path, headers, body = session.calls[0]
    assert (method, path, body) == (
        "GET",
        "/v3/sessions/session-1/workspace",
        None,
    )
    assert headers["Accept"] == FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
    assert headers["Authorization"] == "Bearer secret"


def test_cli_v2_client_rejects_media_drift_without_legacy_fallback() -> None:
    release = _release()
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=_session(
            release,
            media_type="application/vnd.openzyme.file-workspace+json;version=1",
        ),
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.inspect_workspace("session-1")
    assert rejected.value.code == "client_workspace_media_type_mismatch"
    assert rejected.value.mutation_applied is False
    assert rejected.value.fallback_performed is False


def test_cli_v2_message_is_bound_to_the_inspected_mutation_scope() -> None:
    release = _release()
    inspection = _session(release).response
    mutation = _Response(
        status_code=200,
        content=b'{"status":"accepted"}',
        headers={**inspection.headers, "content-type": "application/json"},
    )
    session = _SequencedSession([inspection, mutation])
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    result = client.post_message(
        "session-1",
        message="continue",
        task_id=None,
        lane_id=None,
        skill_keys=(),
        idempotency_key="message-1",
    )

    assert result == {"status": "accepted"}
    assert [call[0] for call in session.calls] == ["GET", "POST"]
    _, path, headers, body = session.calls[1]
    assert path == "/v3/sessions/session-1/messages"
    assert headers["OpenZyme-Projection-Digest"] == (
        inspection.headers["OpenZyme-Projection-Digest"]
    )
    assert headers["OpenZyme-Capability-Binding-Digest"] == _digest("binding")
    assert json.loads(body or b"{}") == {"message": "continue"}


def _write_release(path: Path, release: LayeredReleaseIdentity) -> None:
    path.write_text(
        json.dumps(release.to_dict(), sort_keys=True),
        encoding="utf-8",
    )


def test_cli_v2_loads_one_closed_operator_pinned_release(tmp_path: Path) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)

    assert load_expected_release_identity(release_path) == release

    release_path.write_text('{"unknown":true}', encoding="utf-8")
    with pytest.raises(OpenZymeClientContractError) as rejected:
        load_expected_release_identity(release_path)
    assert rejected.value.code == "cli_release_identity_invalid"
    assert rejected.value.fallback_performed is False


def test_cli_exact_v2_show_uses_closed_projection_renderer(tmp_path: Path) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    session = _session(release)
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            "sessions",
            "show",
        ],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert "Session session-1" in stdout.getvalue()
    assert "Extension sections: 0" in stdout.getvalue()
    assert [call[0] for call in session.calls] == ["GET"]


def test_cli_exact_v2_bootstraps_session_without_projection_preflight(
    tmp_path: Path,
) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    session = _session(release)
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "sessions",
            "create",
            "--project-id",
            "project-1",
            "--session-id",
            "session-2",
            "--objective",
            "prove plugin-free bootstrap",
            "--idempotency-key",
            "bootstrap-session-2",
        ],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert len(session.calls) == 1
    method, path, headers, body = session.calls[0]
    assert (method, path) == ("POST", "/v3/sessions")
    assert headers["OpenZyme-Release-Digest"] == release.release_digest
    assert "OpenZyme-Projection-Digest" not in headers
    assert json.loads(body or b"{}") == {
        "objective": "prove plugin-free bootstrap",
        "project_id": "project-1",
        "session_id": "session-2",
        "title": "prove plugin-free bootstrap",
    }


def test_cli_exact_v2_requires_explicit_mutation_identity_before_transport(
    tmp_path: Path,
) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    session = _session(release)
    stderr = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            "sessions",
            "message",
            "--message",
            "continue",
        ],
        session=session,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "explicit --idempotency-key" in stderr.getvalue()
    assert session.calls == []


def test_cli_has_no_legacy_mode_when_release_identity_is_absent() -> None:
    session = _session(_release())
    stderr = StringIO()

    exit_code = run_cli(
        ["--session-id", "session-1", "sessions", "show"],
        session=session,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "operator-pinned release identity" in stderr.getvalue()
    assert session.calls == []
