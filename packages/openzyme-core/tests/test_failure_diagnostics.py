from __future__ import annotations

import sqlite3

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import LegacyFailureObservationV1
from openzyme_domain import RetryEligibility
from openzyme_domain import Session
from openzyme_domain import parse_failure_observation
from openzyme_runtime import record_failure_observation
from openzyme_runtime import DiagnosticBoundaryError
from openzyme_runtime import ToolResult


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create("session_diagnostics", "project_1", "Diagnostics", "Test")
    )
    return repositories


def _record(
    repositories: CoreRepositories,
    *,
    private_diagnostic: object | None,
) -> FailureObservation:
    return record_failure_observation(
        repositories,
        session_id="session_diagnostics",
        source_kind="workspace_publication",
        source_ref="publication_1",
        source_version="attempt:1",
        component="openzyme_core.workspace_publications",
        operation="dispatch_exact_ref",
        phase="remote_dispatch",
        failure_class=FailureClass.CONTROLLED_EFFECT,
        recoverability=FailureRecoverability.RECONCILIATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="publication_response_lost",
        safe_summary=(
            "push failed token=sk-secret-secret-secret at "
            "/home/operator/private/repository"
        ),
        facts={
            "return_code": 128,
            "remote_path": "/srv/private/repository",
            "credential_count": 1,
        },
        identities={
            "publication_id": "publication_1",
            "raw_handle": "ssh://private-host/opaque-token",
        },
        mutation_applied=True,
        fallback_performed=False,
        next_action="reconcile_exact_ref",
        private_diagnostic=private_diagnostic,
        correlation_id="correlation_1",
    )


def _chained_error() -> RuntimeError:
    try:
        raise OSError(13, "permission denied /srv/private/repository")
    except OSError as cause:
        try:
            raise RuntimeError("publication response lost token=sk-secret-secret") from cause
        except RuntimeError as error:
            return error


def test_public_v2_and_private_record_preserve_safe_and_complete_cause_chains() -> None:
    repositories = _repositories()
    error = _chained_error()

    observation = _record(repositories, private_diagnostic=error)
    public = observation.to_dict()
    private = repositories.private_diagnostics.get_for_operator(
        observation.diagnostic_id,
        operator_authorized=True,
    )

    assert public["schema_version"] == "failure_observation@2"
    assert public["component"] == "openzyme_core.workspace_publications"
    assert public["operation"] == "dispatch_exact_ref"
    assert public["mutation_applied"] is True
    assert public["fallback_performed"] is False
    assert public["next_action"] == "reconcile_exact_ref"
    assert public["identities"] == {"publication_id": "publication_1"}
    assert "private_diagnostic_digest" not in public
    assert "sk-secret" not in str(public)
    assert "/home/" not in str(public)
    assert "/srv/" not in str(public)
    assert [item["type"] for item in public["cause_chain"]] == [
        "RuntimeError",
        "PermissionError",
    ]
    assert private is not None
    assert private.record_digest == observation.private_diagnostic_digest
    assert "sk-secret-secret" in private.exception_message
    assert "/srv/private/repository" in private.traceback_text
    assert [item["type"] for item in private.cause_chain] == [
        "RuntimeError",
        "PermissionError",
    ]
    assert private.errno is None
    assert private.cause_chain[1]["message"] == (
        "[Errno 13] permission denied /srv/private/repository"
    )


def test_private_diagnostic_lookup_requires_explicit_operator_authority() -> None:
    repositories = _repositories()
    observation = _record(repositories, private_diagnostic=_chained_error())

    with pytest.raises(PermissionError, match="operator authority"):
        repositories.private_diagnostics.get_for_operator(
            observation.diagnostic_id,
            operator_authorized=False,
        )


def test_public_and_private_pair_roll_back_atomically(monkeypatch: pytest.MonkeyPatch) -> None:
    repositories = _repositories()

    def reject_private(*_args: object, **_kwargs: object) -> object:
        raise sqlite3.IntegrityError("forced private diagnostic rejection")

    monkeypatch.setattr(type(repositories.private_diagnostics), "add", reject_private)

    with pytest.raises(sqlite3.IntegrityError, match="forced private"):
        _record(repositories, private_diagnostic=_chained_error())

    assert repositories.failure_observations.list_by_session("session_diagnostics") == []


def test_v1_is_read_only_and_v2_public_payload_round_trips() -> None:
    legacy = parse_failure_observation(
        {"schema_version": "failure_observation@1", "failure_id": "legacy_1"}
    )
    assert isinstance(legacy, LegacyFailureObservationV1)
    assert legacy.to_dict()["failure_id"] == "legacy_1"

    observation = _record(_repositories(), private_diagnostic=None)
    parsed = parse_failure_observation(observation.to_dict())
    assert isinstance(parsed, FailureObservation)
    assert parsed == observation


def test_typed_boundary_error_keeps_same_diagnostic_and_python_cause() -> None:
    observation = _record(_repositories(), private_diagnostic=_chained_error())
    cause = _chained_error()

    try:
        raise DiagnosticBoundaryError(observation) from cause
    except DiagnosticBoundaryError as boundary:
        assert boundary.error_code == observation.error_code
        assert boundary.failure_id == observation.failure_id
        assert boundary.diagnostic_id == observation.diagnostic_id
        assert boundary.__cause__ is cause


def test_private_record_preserves_structured_exception_diagnostic_context() -> None:
    repositories = _repositories()
    error = RuntimeError("cleanup failed")
    error.diagnostic_context = {  # type: ignore[attr-defined]
        "temporary_path": "research/.openzyme-write-deadbeef",
        "ordered_failures": [
            {"order": 1, "role": "primary", "returncode": 73},
            {"order": 2, "role": "cleanup", "returncode": 74},
        ],
    }

    observation = _record(repositories, private_diagnostic=error)
    private = repositories.private_diagnostics.get_for_operator(
        observation.diagnostic_id,
        operator_authorized=True,
    )

    assert private is not None
    assert private.private_context == error.diagnostic_context  # type: ignore[attr-defined]


def test_tool_result_private_diagnostic_never_enters_public_envelope() -> None:
    secret_error = RuntimeError("private token=sk-secret-secret-secret")
    result = ToolResult(
        call_id="call_private",
        tool_name="workspace.write",
        ok=False,
        content="workspace write failed",
        private_diagnostic=secret_error,
    )

    envelope = result.envelope()

    assert "private_diagnostic" not in envelope
    assert "sk-secret" not in str(envelope)
