from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_hpc_runner.attempts import RunnerAttemptError
from mcp_hpc_runner.attempts import RunnerAttemptExistsError
from mcp_hpc_runner.attempts import RunnerAttemptJournal
from mcp_hpc_runner.attempts import RunnerAttemptPhase
from mcp_hpc_runner.attempts import RunnerAttemptQuarantined
from mcp_hpc_runner.attempts import RunnerAttemptState
from mcp_hpc_runner.attempts import RunnerEffectCertainty
from mcp_hpc_runner.attempts import RunnerRetryEligibility
from mcp_hpc_runner.attempts import receipt_digest
from mcp_hpc_runner.attempts import runner_attempt_snapshot_path
from mcp_hpc_runner.config import ClusterConfig
from mcp_hpc_runner.config import ExecutionConfig
from mcp_hpc_runner.config import RunnerConfig
from mcp_hpc_runner.config import SshTransportMode
from mcp_hpc_runner.config import SshTransportPolicy
from mcp_hpc_runner.models import ExpectedOutput
from mcp_hpc_runner.models import RunSpec
from mcp_hpc_runner.models import StagedInput
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.store import ArtifactStore
from mcp_hpc_runner.transport import SshTransportManager


class NoopRunner:
    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:
        del check, timeout
        return CommandResult(
            args=list(args),
            returncode=0,
            stdout="",
            stderr="",
            stage=stage,
        )


def _journal(tmp_path: Path) -> tuple[RunnerAttemptJournal, ArtifactStore]:
    config = RunnerConfig(
        cluster=ClusterConfig(ssh_host="private-hpc", ssh_user="secret-user"),
        execution=ExecutionConfig(artifact_root=str(tmp_path / "artifacts")),
        transport_control_root=str(tmp_path / "control"),
    )
    store = ArtifactStore(config.artifact_root)
    manager = SshTransportManager(config, NoopRunner())  # type: ignore[arg-type]
    return RunnerAttemptJournal(store, config, manager), store


def _restart_recovery_journal(
    tmp_path: Path,
) -> tuple[RunnerAttemptJournal, ArtifactStore, object]:
    config = RunnerConfig(
        cluster=ClusterConfig(ssh_host="private-hpc", ssh_user="secret-user"),
        execution=ExecutionConfig(artifact_root=str(tmp_path / "artifacts")),
        ssh_transport=SshTransportPolicy(
            mode=SshTransportMode.CONTROLMASTER_V1,
            backoff_initial_seconds=0.0,
            backoff_max_seconds=0.0,
        ),
        transport_control_root=str(tmp_path / "control"),
    )

    class RecoveryTransport:
        enabled = True
        identity = SimpleNamespace(identity_digest="sha256:" + "d" * 64)

        def __init__(self) -> None:
            self.after_generations: list[int] = []

        def recovery_backoff(self, recovery_index: int) -> None:
            assert recovery_index == 0

        def ensure_recovery_generation(self, *, after_generation: int) -> int:
            self.after_generations.append(after_generation)
            return after_generation + 1

    manager = RecoveryTransport()
    store = ArtifactStore(config.artifact_root)
    return RunnerAttemptJournal(store, config, manager), store, manager  # type: ignore[arg-type]


def _spec(tmp_path: Path, *, run_id: str = "opaque-run-1") -> RunSpec:
    local = tmp_path / "private-input.txt"
    local.write_text("scientific input", encoding="utf-8")
    return RunSpec(
        name="safe-tool",
        stage="execution",
        command=["private-payload", "--secret-argument"],
        execution_mode="ssh",
        inputs=[
            StagedInput(
                local_path=str(local),
                remote_path="input/private-input.txt",
                artifact_id="artifact-private-1",
            )
        ],
        expected_outputs=[ExpectedOutput(path="result/private-output.json")],
        metadata={
            "openzyme": {
                "session_id": "session-private",
                "controlled_operation_id": "operation-private",
                "controlled_operation_execution_id": "execution-private",
                "approval_id": "approval-private",
                "approval_digest": "sha256:" + "a" * 64,
            },
            "pipeline_invocation_id": "invocation-private",
            "pipeline_step_id": "step-private",
        },
        run_id=run_id,
    )


def test_attempt_create_is_atomic_digest_bound_and_private(tmp_path: Path) -> None:
    journal, store = _journal(tmp_path)
    spec = _spec(tmp_path)

    attempt = journal.create(spec, selected_mode="ssh")

    assert attempt.phase is RunnerAttemptPhase.ALLOCATED
    assert attempt.state is RunnerAttemptState.ACTIVE
    assert attempt.effect_certainty is RunnerEffectCertainty.NO_EFFECT
    assert attempt.retry_eligibility is RunnerRetryEligibility.SAME_PHASE_SAFE
    assert attempt.state_version == 1
    assert attempt.journal_head_digest is not None
    assert attempt.safe_receipt_digest.startswith("sha256:")
    assert len(store.list_metadata(spec.run_id or "", prefix="runner_attempt_event_")) == 1
    encoded = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (store.run_root(spec.run_id or "") / "metadata").iterdir()
        if path.is_file()
    )
    for private_value in (
        "private-hpc",
        "secret-user",
        "private-payload",
        "secret-argument",
        "operation-private",
        "execution-private",
        "approval-private",
        "private-input.txt",
        "private-output.json",
    ):
        assert private_value not in encoded

    with pytest.raises(RunnerAttemptExistsError, match="replay is refused"):
        journal.create(spec, selected_mode="ssh")


def test_attempt_transitions_are_monotonic_and_receipts_are_immutable(
    tmp_path: Path,
) -> None:
    journal, _ = _journal(tmp_path)
    spec = _spec(tmp_path)
    created = journal.create(spec, selected_mode="ssh")
    ready = journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.TRANSPORT_READY,
        transport_generation=1,
        reason_code="transport_ready",
        expected_state_version=created.state_version,
    )
    prepared = journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.DISPATCH_PREPARED,
        receipt_digests={"preflight": receipt_digest({"passed": True})},
        reason_code="dispatch_prepared",
    )

    assert prepared.state_version == 3
    assert prepared.transport_generation == 1
    assert prepared.phase_attempt_counts == {
        "allocated": 1,
        "transport_ready": 1,
        "dispatch_prepared": 1,
    }
    with pytest.raises(ValueError, match="phase regressed"):
        journal.transition(
            spec.run_id or "",
            phase=RunnerAttemptPhase.INPUT_STAGING,
            reason_code="illegal_regression",
        )
    with pytest.raises(RunnerAttemptError, match="state version changed"):
        journal.transition(
            spec.run_id or "",
            reason_code="stale_writer",
            expected_state_version=ready.state_version,
        )
    with pytest.raises(RunnerAttemptQuarantined, match="immutable"):
        journal.transition(
            spec.run_id or "",
            receipt_digests={"preflight": receipt_digest({"passed": False})},
            reason_code="receipt_conflict",
        )
    with pytest.raises(RunnerAttemptQuarantined):
        journal.load(spec.run_id or "")


def test_attempt_snapshot_recovers_from_append_only_event_head(tmp_path: Path) -> None:
    journal, store = _journal(tmp_path)
    spec = _spec(tmp_path)
    created = journal.create(spec, selected_mode="ssh")
    runner_attempt_snapshot_path(store, spec.run_id or "").unlink()

    recovered = journal.load(spec.run_id or "")

    assert recovered == created
    assert runner_attempt_snapshot_path(store, spec.run_id or "").is_file()


def test_snapshot_or_event_tampering_quarantines_before_more_work(
    tmp_path: Path,
) -> None:
    journal, store = _journal(tmp_path)
    spec = _spec(tmp_path)
    journal.create(spec, selected_mode="ssh")
    event_path = store.list_metadata(
        spec.run_id or "", prefix="runner_attempt_event_"
    )[0]
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["attempt_snapshot"]["runspec_digest"] = "sha256:" + "b" * 64
    event_path.write_text(json.dumps(event), encoding="utf-8")

    with pytest.raises(RunnerAttemptQuarantined, match="validation failed"):
        journal.load(spec.run_id or "")
    quarantine = store.read_json(spec.run_id or "", "runner_attempt_quarantine.json")
    assert quarantine["reason_code"] == "journal_validation_failed"


def test_bound_load_quarantines_runspec_config_or_route_drift(tmp_path: Path) -> None:
    journal, store = _journal(tmp_path)
    spec = _spec(tmp_path)
    journal.create(spec, selected_mode="ssh")
    changed = replace(spec, command=["different-payload"])

    with pytest.raises(RunnerAttemptQuarantined, match="identity drifted"):
        journal.load_bound(spec.run_id or "", changed, selected_mode="ssh")

    quarantine = store.read_json(spec.run_id or "", "runner_attempt_quarantine.json")
    assert quarantine["reason_code"] == "attempt_identity_drift"


def test_dispatch_ambiguity_is_closed_and_terminal_cannot_reopen(
    tmp_path: Path,
) -> None:
    journal, _ = _journal(tmp_path)
    spec = _spec(tmp_path)
    journal.create(spec, selected_mode="ssh")
    journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.DISPATCHING,
        effect_certainty=RunnerEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RunnerRetryEligibility.RECONCILE_REQUIRED,
        reconciliation_required=True,
        reason_code="payload_transmission_started",
    )
    ambiguous = journal.transition(
        spec.run_id or "",
        state=RunnerAttemptState.RECONCILIATION_REQUIRED,
        safe_failure_code="dispatch_in_doubt",
        reason_code="dispatch_outcome_unknown",
    )

    assert ambiguous.reconciliation_required is True
    assert ambiguous.retry_eligibility is RunnerRetryEligibility.RECONCILE_REQUIRED
    terminal = journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.TERMINAL,
        state=RunnerAttemptState.TERMINAL,
        effect_certainty=RunnerEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RunnerRetryEligibility.TERMINAL,
        reconciliation_required=False,
        reason_code="reconciled_terminal",
    )
    assert terminal.state is RunnerAttemptState.TERMINAL
    with pytest.raises(ValueError, match="state transition is illegal"):
        journal.transition(
            spec.run_id or "",
            phase=RunnerAttemptPhase.TERMINAL,
            reason_code="terminal_reopen_forbidden",
        )


def test_audit_existing_reports_valid_and_quarantined_attempts(tmp_path: Path) -> None:
    journal, store = _journal(tmp_path)
    valid = _spec(tmp_path, run_id="valid-run")
    invalid = _spec(tmp_path, run_id="invalid-run")
    journal.create(valid, selected_mode="ssh")
    journal.create(invalid, selected_mode="ssh")
    snapshot = runner_attempt_snapshot_path(store, invalid.run_id or "")
    raw = json.loads(snapshot.read_text(encoding="utf-8"))
    raw["state_version"] = 999
    snapshot.write_text(json.dumps(raw), encoding="utf-8")

    reports = {item["run_id"]: item for item in journal.audit_existing()}

    assert reports["valid-run"]["status"] == "active"
    assert reports["invalid-run"]["status"] == "quarantined"


def test_restart_classifies_verified_pre_effect_attempt_for_same_run_resume(
    tmp_path: Path,
) -> None:
    journal, store = _journal(tmp_path)
    spec = _spec(tmp_path, run_id="resume-safe-run")
    journal.create(spec, selected_mode="ssh")
    store.write_json(spec.run_id or "", "runspec.json", spec.to_dict())
    journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.INPUT_STAGING,
        reason_code="input_staging_started",
    )

    report = {
        item["run_id"]: item for item in journal.recover_interrupted_attempts()
    }

    assert report["resume-safe-run"] == {
        "run_id": "resume-safe-run",
        "status": "active",
        "phase": "input_staging",
        "effect_certainty": "no_effect",
        "disposition": "resume_same_run_pre_effect",
    }


def test_restart_pre_effect_recovery_is_same_run_fenced_and_bounded(
    tmp_path: Path,
) -> None:
    journal, _, transport = _restart_recovery_journal(tmp_path)
    spec = _spec(tmp_path, run_id="restart-recovery-run")
    journal.create(spec, selected_mode="ssh")
    journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.TRANSPORT_READY,
        transport_generation=3,
        reason_code="transport_ready",
    )
    journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.INPUT_STAGING,
        reason_code="input_staging_started",
    )

    recovered = journal.authorize_restart_pre_effect_recovery(
        spec.run_id or "",
        spec,
        selected_mode="ssh",
    )

    assert recovered is not None
    assert recovered.state is RunnerAttemptState.ACTIVE
    assert recovered.phase is RunnerAttemptPhase.INPUT_STAGING
    assert recovered.transport_generation == 4
    assert recovered.pre_effect_recovery_attempts_used == 1
    assert transport.after_generations == [3]  # type: ignore[attr-defined]

    exhausted = journal.authorize_restart_pre_effect_recovery(
        spec.run_id or "",
        spec,
        selected_mode="ssh",
    )
    assert exhausted is not None
    assert exhausted.state is RunnerAttemptState.TERMINAL
    assert exhausted.phase is RunnerAttemptPhase.TERMINAL
    assert exhausted.effect_certainty is RunnerEffectCertainty.NO_EFFECT
    assert exhausted.retry_eligibility is RunnerRetryEligibility.TERMINAL


def test_restart_output_fetch_recovery_never_reopens_payload_and_is_bounded(
    tmp_path: Path,
) -> None:
    journal, _, transport = _restart_recovery_journal(tmp_path)
    spec = _spec(tmp_path, run_id="restart-output-fetch-run")
    journal.create(spec, selected_mode="ssh")
    journal.transition(
        spec.run_id or "",
        phase=RunnerAttemptPhase.OUTPUTS_FETCHING,
        effect_certainty=RunnerEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RunnerRetryEligibility.VERIFY_THEN_RETRY,
        transport_generation=5,
        receipt_digests={"remote_terminal": receipt_digest({"exit_code": 0})},
        reason_code="outputs_fetching",
    )

    recovered = journal.authorize_restart_output_fetch_recovery(
        spec.run_id or "",
        spec,
        selected_mode="ssh",
    )

    assert recovered is not None
    assert recovered.state is RunnerAttemptState.ACTIVE
    assert recovered.phase is RunnerAttemptPhase.OUTPUTS_FETCHING
    assert recovered.effect_certainty is RunnerEffectCertainty.TERMINAL_KNOWN
    assert recovered.phase_attempt_counts["outputs_fetching"] == 2
    assert recovered.transport_generation == 6
    assert transport.after_generations == [5]  # type: ignore[attr-defined]

    exhausted = journal.authorize_restart_output_fetch_recovery(
        spec.run_id or "",
        spec,
        selected_mode="ssh",
    )
    assert exhausted is not None
    assert exhausted.state is RunnerAttemptState.TERMINAL
    assert exhausted.phase is RunnerAttemptPhase.TERMINAL
    assert exhausted.effect_certainty is RunnerEffectCertainty.TERMINAL_KNOWN
    assert exhausted.retry_eligibility is RunnerRetryEligibility.TERMINAL
    assert exhausted.safe_failure_code == "output_fetch_recovery_exhausted"


def test_restart_quarantines_persisted_runspec_drift_before_remote_work(
    tmp_path: Path,
) -> None:
    journal, store = _journal(tmp_path)
    spec = _spec(tmp_path, run_id="restart-drift-run")
    journal.create(spec, selected_mode="ssh")
    changed = replace(spec, command=["changed-payload"])
    store.write_json(spec.run_id or "", "runspec.json", changed.to_dict())

    report = {
        item["run_id"]: item for item in journal.recover_interrupted_attempts()
    }

    assert report["restart-drift-run"]["status"] == "quarantined"
    assert store.read_json(
        spec.run_id or "",
        "runner_attempt_quarantine.json",
    )["reason_code"] == "attempt_identity_drift"
