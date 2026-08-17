from __future__ import annotations

import hashlib
import json

import pytest

from openzyme_host_api.executor_hpc_workspaces import (
    ExecutorHpcCredentialCommandResult,
)
from openzyme_host_api.workspace_revision_execution import (
    CommandRunnerSchedulerCredentialIssuer,
)


DIGEST = "sha256:" + "a" * 64


def _claims() -> dict[str, object]:
    return {
        "schema_version": "scheduler_occurrence_credential_claims@1",
        "occurrence_id": "occurrence_1",
        "dispatch_id": "dispatch_1",
        "execution_id": "execution_1",
        "execution_fencing_token": 3,
        "target_profile_digest": DIGEST,
        "reservation_nonce_digest": DIGEST,
        "scheduler_marker": "marker_1",
        "payload_digest": DIGEST,
        "protected_wrapper_audience": "wrapper_1",
        "expires_at": "2026-08-17T01:05:00+00:00",
    }


class _IssuerExecutor:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def run(
        self,
        argv: tuple[str, ...],
        *,
        stdin: str,
        timeout_seconds: int,
    ) -> ExecutorHpcCredentialCommandResult:
        assert argv == ("/usr/local/bin/issue-scheduler-occurrence",)
        assert timeout_seconds == 17
        self.request = json.loads(stdin)
        claims_digest = str(self.request["claims_digest"])
        return ExecutorHpcCredentialCommandResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "schema_version": (
                        "scheduler_occurrence_credential_issue_result@1"
                    ),
                    "claims_digest": claims_digest,
                    "occurrence_id": "occurrence_1",
                    "credential_fingerprint": DIGEST,
                    "authentication_receipt_digest": DIGEST,
                    "issued_at": "2026-08-17T01:00:01+00:00",
                    "opaque_token": "opaque-single-use-token",
                }
            ),
            stderr="",
        )


def test_scheduler_credential_command_is_exact_and_scheduler_only() -> None:
    executor = _IssuerExecutor()
    issuer = CommandRunnerSchedulerCredentialIssuer(
        issue_command=("/usr/local/bin/issue-scheduler-occurrence",),
        executor=executor,
        timeout_seconds=17,
    )

    issued = issuer.issue_occurrence(_claims())

    assert issued["occurrence_id"] == "occurrence_1"
    assert issued["opaque_token"] == "opaque-single-use-token"
    assert executor.request is not None
    assert executor.request["login_or_file_authority"] is False
    assert executor.request["interactive_authority"] is False
    encoded = json.dumps(
        _claims(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert executor.request["claims_digest"] == (
        "sha256:" + hashlib.sha256(encoded).hexdigest()
    )


def test_scheduler_credential_command_rejects_open_or_drifted_claims() -> None:
    issuer = CommandRunnerSchedulerCredentialIssuer(
        issue_command=("/usr/local/bin/issue-scheduler-occurrence",),
        executor=_IssuerExecutor(),
    )

    with pytest.raises(ValueError, match="claims are not closed"):
        issuer.issue_occurrence({**_claims(), "ssh_private_key": "forbidden"})
