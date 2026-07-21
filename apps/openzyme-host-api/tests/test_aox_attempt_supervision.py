from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest

from openzyme_host_api import aox_attempt_supervision as supervision
from openzyme_host_api.aox_attempt_supervision import AttemptRootAccessError
from openzyme_host_api.aox_attempt_supervision import AttemptRootAccessGate
from openzyme_host_api.aox_attempt_supervision import AttemptSupervisionFatalError
from openzyme_host_api.aox_attempt_supervision import LifecycleFrameValidator
from openzyme_host_api.aox_attempt_supervision import ProcessIsolatedAttemptRunner
from openzyme_host_api.aox_attempt_supervision import (
    validate_attempt_supervision_receipt,
)
from openzyme_host_api.aox_cutover_evidence import AoxCutoverCampaign
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
    TruncatedRunner as _TruncatedRunner,
)


class _FatalRunner:
    def __init__(self, code: str) -> None:
        self.code = code

    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        del context
        raise AttemptSupervisionFatalError(
            self.code,
            fatal_evidence_digest="sha256:" + "f" * 64,
        )


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
    )
    assert receipt["sqlite_checkpoint"] == "passed"
    assert receipt["sqlite_integrity"] == "passed"
    assert receipt["descendant_retirement_proven"] is True
    assert (context.roots.evidence_root / supervision.RESULT_BASENAME).is_file()
    assert not (context.roots.attempt_root.parent / "failures").exists()


@pytest.mark.parametrize(
    ("runner", "expected_codes"),
    [
        (_BlockingRunner(), {"attempt_child_timeout"}),
        (_FailingRunner(), {"attempt_child_runner_failed"}),
        (_TruncatedRunner(), {"attempt_quiescence_missing"}),
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
        )

    assert error.value.code == "attempt_supervision_receipt_invalid"


def test_campaign_propagates_supervision_fatal_without_attempt_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _attempt_context(tmp_path)
    monkeypatch.setattr(
        "openzyme_host_api.aox_cutover_evidence.create_blank_world_roots",
        lambda *args, **kwargs: context.roots,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_cutover_evidence.safe_micu_ledger_snapshot",
        lambda path: {},
    )
    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=_campaign_identity(),
        ledger_path=tmp_path / "ledger.sqlite3",
        positive_runner=_FatalRunner("attempt_child_timeout"),
        fault_runner=_FatalRunner("attempt_child_timeout"),
        allowed_prerequisites={},
    )

    records, decision = campaign.run()

    assert records == ()
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "attempt_child_timeout"
    assert decision["driver_failure_kind"] == "attempt_supervision_fatal"
    assert not list((tmp_path / "campaign").glob("*/evidence/attempt-bundle.json"))


def test_live_campaign_requires_supervision_before_ledger_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _attempt_context(tmp_path)
    snapshots = 0

    def snapshot(path: Path) -> dict[str, object]:
        nonlocal snapshots
        del path
        snapshots += 1
        return {}

    monkeypatch.setattr(
        "openzyme_host_api.aox_cutover_evidence.safe_micu_ledger_snapshot",
        snapshot,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_cutover_evidence.create_blank_world_roots",
        lambda *args, **kwargs: context.roots,
    )
    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=_campaign_identity(),
        ledger_path=tmp_path / "ledger.sqlite3",
        positive_runner=_ReturningRunner(create_sqlite=False),
        fault_runner=_ReturningRunner(create_sqlite=False),
        allowed_prerequisites={},
        require_process_supervision=True,
    )

    records, decision = campaign.run()

    assert records == ()
    assert snapshots == 1
    assert decision["blocker"]["code"] == "attempt_supervision_receipt_missing"
