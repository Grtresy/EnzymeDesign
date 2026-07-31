from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest

from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api import aox_attempt_supervision as supervision
from openzyme_host_api.aox_attempt_supervision import AttemptRootAccessError
from openzyme_host_api.aox_attempt_supervision import AttemptRootAccessGate
from openzyme_host_api.aox_attempt_supervision import AttemptSupervisionFatalError
from openzyme_host_api.aox_attempt_supervision import LifecycleFrameValidator
from openzyme_host_api.aox_attempt_supervision import ProcessIsolatedAttemptRunner
from openzyme_host_api.aox_attempt_supervision import (
    validate_attempt_supervision_receipt,
)
from openzyme_host_api.aox_cutover_evidence import AttemptRunContext
from openzyme_host_api.aox_cutover_evidence import BlankWorldRoots
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import canonical_json_bytes


_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from aox_attempt_supervision_spawn_fixtures import (  # noqa: E402
    BlockingRunner as _BlockingRunner,
)
from aox_attempt_supervision_spawn_fixtures import (  # noqa: E402
    DescendantRunner as _DescendantRunner,
)
from aox_attempt_supervision_spawn_fixtures import (  # noqa: E402
    FailingRunner as _FailingRunner,
)
from aox_attempt_supervision_spawn_fixtures import (  # noqa: E402
    IgnoringTermRunner as _IgnoringTermRunner,
)
from aox_attempt_supervision_spawn_fixtures import (  # noqa: E402
    ReturningRunner as _ReturningRunner,
)
from aox_attempt_supervision_spawn_fixtures import (  # noqa: E402
    TerminalRolloverRunner as _TerminalRolloverRunner,
)
from aox_attempt_supervision_spawn_fixtures import (  # noqa: E402
    TruncatedRunner as _TruncatedRunner,
)


def _attempt_authority(
    *,
    attempt_id: str,
    attempt_kind: str,
    ordinal: int = 1,
) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "attempt_kind": attempt_kind,
        "attempt_id": attempt_id,
        "envelope_id": f"attempt_authority_{ordinal}",
        "request_digest": canonical_digest(
            {
                "attempt_id": attempt_id,
                "attempt_kind": attempt_kind,
                "ordinal": ordinal,
            }
        ),
        "authority_request": {},
    }


def _attempt_context(
    tmp_path: Path,
    *,
    attempt_id: str = "positive-supervision-test",
    attempt_kind: str = "positive",
) -> AttemptRunContext:
    campaign_root = tmp_path / "campaign"
    attempt_root = campaign_root / attempt_id
    artifact_root = attempt_root / "artifacts"
    blob_root = attempt_root / "blobs"
    sandbox_root = attempt_root / "sandboxes"
    hpc_root = attempt_root / "hpc-workspace"
    evidence_root = attempt_root / "evidence"
    for path in (
        artifact_root,
        blob_root,
        sandbox_root,
        hpc_root,
        evidence_root,
    ):
        path.mkdir(parents=True, mode=0o700, exist_ok=False)
    proof = {
        "root_identity": canonical_digest(
            {"attempt_id": attempt_id, "attempt_kind": attempt_kind}
        ),
        "allowed_prerequisite_digest": canonical_digest({"allowed": True}),
    }
    roots = BlankWorldRoots(
        attempt_id=attempt_id,
        attempt_kind=attempt_kind,
        attempt_root=attempt_root,
        sqlite_path=attempt_root / "control-plane.sqlite3",
        artifact_root=artifact_root,
        blob_root=blob_root,
        sandbox_root=sandbox_root,
        hpc_root=hpc_root,
        evidence_root=evidence_root,
        hpc_workspace_label="aox-cutover-test",
        proof=proof,
    )
    return AttemptRunContext(
        roots=roots,
        identity={
            "git_commit": "a" * 40,
            "config_digest": "sha256:" + "b" * 64,
        },
        ledger_before={},
        attempt_number=1,
        attempt_authority=_attempt_authority(
            attempt_id=attempt_id,
            attempt_kind=attempt_kind,
        ),
    )


def _campaign_identity() -> dict[str, str]:
    return {
        "git_commit": "a" * 40,
        "config_digest": "sha256:" + "b" * 64,
        "workflow_ref": "workflow:aox-hmm-live@1.0.0#sha256:" + "c" * 64,
        "scoring_contract_digest": "sha256:" + "d" * 64,
        "scoring_implementation_digest": "sha256:" + "e" * 64,
        "image_digest": "sha256:" + "f" * 64,
        "sdk_digest": "sha256:" + "1" * 64,
    }


def _architecture_qualification() -> dict[str, str]:
    return build_architecture_qualification_receipt(
        report_payload_digest="sha256:" + "2" * 64,
        registry_digest="sha256:" + "3" * 64,
        test_manifest_digest="sha256:" + "4" * 64,
        profile_id="local_single_process_file_sqlite@1",
        source_commit=_campaign_identity()["git_commit"],
    )


def _supervisor(
    runner: object,
    context: AttemptRunContext,
    *,
    timeout_seconds: float = 5.0,
) -> ProcessIsolatedAttemptRunner:
    return ProcessIsolatedAttemptRunner(
        runner=runner,
        ledger_path=context.roots.attempt_root.parent / "ledger.sqlite3",
        timeout_seconds=timeout_seconds,
        term_grace_seconds=0.2,
        kill_grace_seconds=0.5,
        poll_interval_seconds=0.01,
    )


def _fatal_payload(context: AttemptRunContext) -> dict[str, object]:
    path = (
        context.roots.attempt_root.parent
        / "failures"
        / f"{context.roots.attempt_id}.fatal.json"
    )
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["fatal_digest"] == canonical_digest(envelope["payload"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    return dict(envelope["payload"])


def test_root_gate_rejects_reads_until_exact_retirement(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    root.mkdir()
    result = root / "result.json"
    result.write_text("{}", encoding="utf-8")
    gate = AttemptRootAccessGate(
        attempt_root=root,
        process_epoch="1" * 32,
        child_pid=123,
    )

    with pytest.raises(AttemptRootAccessError):
        gate.read_bytes(result)

    assert gate.attempted_access_count == 1
    with pytest.raises(AttemptRootAccessError):
        gate.retire(
            process_epoch="2" * 32,
            child_pid=123,
            descendant_retirement_proven=True,
        )
    gate.retire(
        process_epoch="1" * 32,
        child_pid=123,
        descendant_retirement_proven=True,
    )
    assert gate.read_bytes(result) == b"{}"


def test_lifecycle_validator_rejects_hash_and_canonical_drift() -> None:
    identity = supervision._ProtocolIdentity(
        campaign_id="sha256:" + "a" * 64,
        attempt_id="positive-1",
        attempt_kind="positive",
        attempt_authority_id="attempt_authority_1",
        attempt_authority_request_digest="sha256:" + "f" * 64,
        parent_process_nonce="b" * 64,
        process_epoch="c" * 32,
        root_identity="sha256:" + "d" * 64,
    )
    content, _ = supervision.build_lifecycle_frame(
        identity=identity,
        child_process_nonce="e" * 64,
        sequence=1,
        frame_type="child_started",
        payload={
            "child_pid": 11,
            "child_pgid": 11,
            "child_start_time_ticks": 12,
            "root_identity": identity.root_identity,
        },
        previous_frame_digest=None,
    )

    accepted = LifecycleFrameValidator(identity=identity).accept(content)
    assert accepted["sequence"] == 1
    with pytest.raises(supervision.AttemptSupervisionProtocolError):
        LifecycleFrameValidator(identity=identity).accept(b" " + content)
    forged = json.loads(content)
    forged["payload"]["child_pid"] = 99
    with pytest.raises(supervision.AttemptSupervisionProtocolError):
        LifecycleFrameValidator(identity=identity).accept(canonical_json_bytes(forged))


def test_normal_child_result_requires_sqlite_and_process_retirement(
    tmp_path: Path,
) -> None:
    context = _attempt_context(tmp_path)

    evidence = _supervisor(_ReturningRunner(), context)(context)

    product_path = dict(evidence["product_path"])
    assert product_path["runner_process_id"] != os.getpid()
    receipt = validate_attempt_supervision_receipt(
        product_path["attempt_supervision"],
        attempt_id=context.roots.attempt_id,
        attempt_kind=context.roots.attempt_kind,
        attempt_authority_id=str(context.attempt_authority["envelope_id"]),
        attempt_authority_request_digest=str(
            context.attempt_authority["request_digest"]
        ),
    )
    assert receipt["sqlite_checkpoint"] == "passed"
    assert receipt["sqlite_integrity"] == "passed"
    assert receipt["descendant_retirement_proven"] is True
    assert receipt["parent_snapshot_revalidated"] is True
    assert receipt["nonterminal_mutation_scope_count"] == 0
    assert (context.roots.evidence_root / supervision.RESULT_BASENAME).is_file()
    assert not (context.roots.attempt_root.parent / "failures").exists()


def test_writer_free_terminal_rollover_is_valid_local_settlement(
    tmp_path: Path,
) -> None:
    context = _attempt_context(tmp_path)

    evidence = _supervisor(_TerminalRolloverRunner(), context)(context)

    receipt = evidence["product_path"]["attempt_supervision"]
    assert receipt["local_state_settled"] is True
    assert receipt["parent_snapshot_revalidated"] is True
    assert receipt["nonterminal_mutation_scope_count"] == 1
    assert receipt["active_mutation_writer_count"] == 0


def test_active_writer_fails_local_settlement_with_stable_code(
    tmp_path: Path,
) -> None:
    context = _attempt_context(tmp_path)

    with pytest.raises(AttemptSupervisionFatalError) as error:
        _supervisor(_TerminalRolloverRunner(active_writer=True), context)(context)

    assert error.value.code == "mutation_writers_active"
    payload = _fatal_payload(context)
    assert payload["failure_code"] == "mutation_writers_active"
    assert payload["local_settlement_observed"] is False


def test_attempt_supervision_preserves_earliest_typed_causal_error() -> None:
    captured: RuntimeError | None = None
    try:
        try:
            raise CutoverEvidenceError(
                "canonical_lifecycle_drift",
                "canonical lifecycle evidence drifted",
            )
        except CutoverEvidenceError as cause:
            raise RuntimeError("outer runner wrapper") from cause
    except RuntimeError as exc:
        captured = exc

    assert captured is not None
    assert supervision._typed_causal_failure(captured) == (
        "canonical_lifecycle_drift",
        "CutoverEvidenceError",
    )


def test_parent_rejects_mutation_snapshot_drift_after_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _attempt_context(tmp_path)
    original = supervision._sqlite_local_settlement

    def drifted_parent_projection(
        path: Path,
        *,
        read_only: bool = False,
    ) -> dict[str, object]:
        projection = original(path, read_only=read_only)
        if read_only:
            projection = dict(projection)
            projection["snapshot_digest"] = "sha256:" + "f" * 64
        return projection

    monkeypatch.setattr(
        supervision,
        "_sqlite_local_settlement",
        drifted_parent_projection,
    )

    with pytest.raises(AttemptSupervisionFatalError) as error:
        _supervisor(_TerminalRolloverRunner(), context)(context)

    assert error.value.code == "attempt_mutation_snapshot_drift"
    payload = _fatal_payload(context)
    assert payload["failure_code"] == "attempt_mutation_snapshot_drift"
    assert payload["local_settlement_observed"] is True


@pytest.mark.parametrize(
    ("runner", "expected_codes"),
    [
        (_BlockingRunner(), {"attempt_child_timeout"}),
        (_FailingRunner(), {"attempt_child_runner_failed"}),
        (_TruncatedRunner(), {"attempt_local_settlement_missing"}),
        (_DescendantRunner(), {"attempt_child_descendant_leak"}),
    ],
)
def test_fatal_children_are_retired_without_partial_bundle(
    tmp_path: Path,
    runner: object,
    expected_codes: set[str],
) -> None:
    context = _attempt_context(tmp_path)
    timeout = 1.5 if isinstance(runner, _BlockingRunner) else 5.0

    with pytest.raises(AttemptSupervisionFatalError) as error:
        _supervisor(runner, context, timeout_seconds=timeout)(context)

    assert error.value.code in expected_codes
    payload = _fatal_payload(context)
    assert payload["failure_code"] == error.value.code
    assert payload["descendant_retirement_proven"] is True
    assert payload["external_outcome"] == "unknown"
    assert payload["next_attempt_blocked"] is True
    assert payload["cutover_eligible"] is False
    assert payload["ledger_after_claimed"] is False
    assert payload["sqlite_closure_claimed"] is False
    assert payload["artifact_completeness_claimed"] is False
    serialized = json.dumps(payload, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "provider-secret" not in serialized
    assert not (context.roots.evidence_root / "attempt-bundle.json").exists()


def test_sigkill_retires_child_that_ignores_sigterm(tmp_path: Path) -> None:
    context = _attempt_context(tmp_path)

    with pytest.raises(AttemptSupervisionFatalError) as error:
        _supervisor(_IgnoringTermRunner(), context, timeout_seconds=1.5)(context)

    assert error.value.code == "attempt_child_timeout"
    payload = _fatal_payload(context)
    phases = {item["phase"]: item for item in payload["termination_ladder"]}
    assert phases["sigterm"]["sent"] is True
    assert phases["sigkill"]["sent"] is True
    assert phases["retirement_check"]["group_member_count"] == 0


def test_supervision_receipt_rejects_unknown_fields(tmp_path: Path) -> None:
    context = _attempt_context(tmp_path)
    evidence = _supervisor(_ReturningRunner(create_sqlite=False), context)(context)
    receipt = dict(evidence["product_path"]["attempt_supervision"])
    receipt["untrusted_extra"] = True

    with pytest.raises(CutoverEvidenceError) as error:
        validate_attempt_supervision_receipt(
            receipt,
            attempt_id=context.roots.attempt_id,
            attempt_kind=context.roots.attempt_kind,
            attempt_authority_id=str(context.attempt_authority["envelope_id"]),
            attempt_authority_request_digest=str(
                context.attempt_authority["request_digest"]
            ),
        )

    assert error.value.code == "attempt_supervision_receipt_invalid"


@pytest.mark.parametrize(
    ("receipt_schema", "protocol_schema", "with_authority"),
    [
        (
            supervision.SUPERVISION_RECEIPT_SCHEMA_ID_V1,
            supervision.SUPERVISION_SCHEMA_ID_V1,
            False,
        ),
        (
            supervision.SUPERVISION_RECEIPT_SCHEMA_ID_V2,
            supervision.SUPERVISION_SCHEMA_ID_V2,
            True,
        ),
    ],
)
def test_legacy_receipts_are_explicit_offline_only(
    receipt_schema: str,
    protocol_schema: str,
    with_authority: bool,
) -> None:
    receipt = {
        "schema_id": receipt_schema,
        "mode": "process_isolated_spawn",
        "attempt_id": "positive-legacy",
        "attempt_kind": "positive",
        "campaign_id": canonical_digest({"campaign": "legacy"}),
        "process_epoch": "a" * 32,
        "protocol_final_sequence": 4,
        "protocol_final_digest": canonical_digest({"frame": "legacy"}),
        "child_exit_code": 0,
        "quiescent": True,
        "descendant_retirement_proven": True,
        "active_mutation_scope_count": 0,
        "active_mutation_writer_count": 0,
        "sqlite_checkpoint": "passed",
        "sqlite_integrity": "passed",
        "declared_root_sync": True,
        "result_digest": canonical_digest({"result": "legacy"}),
        "supervisor_contract_digest": supervision.supervision_contract_digest(
            timeout_seconds=30.0,
            term_grace_seconds=15.0,
            kill_grace_seconds=10.0,
            protocol_schema_id=protocol_schema,
        ),
        "timeout_seconds": 30.0,
        "term_grace_seconds": 15.0,
        "kill_grace_seconds": 10.0,
    }
    authority_id = "attempt_authority_legacy"
    authority_digest = canonical_digest({"authority": "legacy"})
    if with_authority:
        receipt.update(
            {
                "attempt_authority_id": authority_id,
                "attempt_authority_request_digest": authority_digest,
            }
        )

    with pytest.raises(CutoverEvidenceError):
        validate_attempt_supervision_receipt(
            receipt,
            attempt_id="positive-legacy",
            attempt_kind="positive",
            attempt_authority_id=authority_id if with_authority else None,
            attempt_authority_request_digest=(
                authority_digest if with_authority else None
            ),
        )

    assert (
        validate_attempt_supervision_receipt(
            receipt,
            attempt_id="positive-legacy",
            attempt_kind="positive",
            attempt_authority_id=authority_id if with_authority else None,
            attempt_authority_request_digest=(
                authority_digest if with_authority else None
            ),
            allow_legacy=True,
        )
        == receipt
    )
