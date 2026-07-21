from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from typing import Callable
from typing import Iterator

import pytest

from mcp_hpc_runner.attempts import RunnerAttemptPhase
from mcp_hpc_runner.attempts import RunnerAttemptQuarantined
from mcp_hpc_runner.attempts import RunnerAttemptState
from mcp_hpc_runner.attempts import RunnerEffectCertainty
from mcp_hpc_runner.attempts import RunnerRetryEligibility
from mcp_hpc_runner.models import RunSpec
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.server import MCPHpcServer
from mcp_hpc_runner.verification import AuthorizedInput
from mcp_hpc_runner.verification import RemoteVerificationStatus
from mcp_hpc_runner.verification import remote_verification_stdout


def _command_result(
    returncode: int = 0,
    *,
    stdout: str = "",
    process_started: bool = True,
    timed_out: bool = False,
) -> CommandResult:
    return CommandResult(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr="",
        process_started=process_started,
        timed_out=timed_out,
    )


def _successful_preflight_receipt(args: list[str]) -> str:
    script = next(
        argument
        for argument in args
        if "descriptor_set_digest =" in argument and "checks =" in argument
    )
    checks = json.loads(
        script.split("checks = ", 1)[1].split("\ndescriptor_set_digest =", 1)[0]
    )
    descriptor_set_digest = json.loads(
        script.split("descriptor_set_digest = ", 1)[1].split("\nresults =", 1)[0]
    )
    return json.dumps(
        {
            "schema_version": "remote_preflight_receipt@1",
            "descriptor_set_digest": descriptor_set_digest,
            "checks": [
                {
                    "check_id": check["check_id"],
                    "kind": check["kind"],
                    "declared_path": check["path"],
                    "path": check["path"],
                    "status": "pass",
                }
                for check in checks
            ],
        }
    )


class FaultMatrixRunner:
    def __init__(
        self,
        *,
        authorized_input: AuthorizedInput | None = None,
        remote_output: AuthorizedInput | None = None,
    ) -> None:
        self.authorized_input = authorized_input
        self.remote_output = remote_output
        self.connect_results: deque[CommandResult] = deque()
        self.health_results: deque[CommandResult] = deque()
        self.layout_results: deque[CommandResult] = deque()
        self.input_parent_results: deque[CommandResult] = deque()
        self.upload_results: deque[CommandResult] = deque()
        self.input_verification_results: deque[CommandResult] = deque()
        self.preflight_results: deque[CommandResult] = deque()
        self.dispatch_results: deque[CommandResult] = deque()
        self.output_observation_results: deque[CommandResult] = deque()
        self.output_fetch_results: deque[CommandResult] = deque()
        self.commands: list[list[str]] = []
        self.stages: list[str | None] = []
        self.payload_invocations = 0
        self.accepted_payloads = 0
        self.upload_invocations = 0
        self.output_fetch_invocations = 0
        self.last_uploaded_input: AuthorizedInput | None = None
        self.last_attempted_input: AuthorizedInput | None = None
        self.write_wrong_output = False
        self.on_layout_failure: Callable[[], None] | None = None

    @staticmethod
    def _take(
        queue: deque[CommandResult],
        default: CommandResult,
    ) -> CommandResult:
        return queue.popleft() if queue else default

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:
        del check, timeout
        self.commands.append(list(args))
        self.stages.append(stage)
        default = _command_result()
        if stage == "transport_connect":
            result = self._take(self.connect_results, default)
        elif stage == "transport_health":
            result = self._take(self.health_results, default)
        elif stage == "staging" and self._is_layout(args):
            result = self._take(self.layout_results, default)
            if result.returncode != 0 and self.on_layout_failure is not None:
                self.on_layout_failure()
        elif stage == "staging" and self._is_input_parent(args):
            result = self._take(self.input_parent_results, default)
        elif stage == "staging" and args and args[0] in {"scp", "rsync"}:
            self.upload_invocations += 1
            result = self._take(self.upload_results, default)
            local_source = Path(args[-2].rstrip("/"))
            if local_source.exists():
                self.last_attempted_input = AuthorizedInput.from_path(local_source)
                if result.returncode == 0:
                    self.last_uploaded_input = AuthorizedInput.from_path(local_source)
        elif stage == "input_verification":
            authorized = (
                self.authorized_input
                or self.last_uploaded_input
                or self.last_attempted_input
            )
            if authorized is None:
                raise AssertionError("unexpected input verification")
            result = self._take(
                self.input_verification_results,
                _command_result(
                    stdout=remote_verification_stdout(authorized)
                ),
            )
        elif stage == "preflight":
            result = self._take(
                self.preflight_results,
                _command_result(stdout=_successful_preflight_receipt(args)),
            )
        elif stage == "remote_execution":
            self.payload_invocations += 1
            result = self._take(self.dispatch_results, default)
            if result.process_started:
                self.accepted_payloads += 1
        elif stage == "output_observation":
            if self.remote_output is None:
                raise AssertionError("unexpected output observation")
            result = self._take(
                self.output_observation_results,
                _command_result(stdout=remote_verification_stdout(self.remote_output)),
            )
        elif stage == "output_fetch":
            self.output_fetch_invocations += 1
            result = self._take(self.output_fetch_results, default)
            if result.returncode == 0:
                if self.remote_output is None:
                    raise AssertionError("output bytes are unavailable")
                local_target = Path(args[-1])
                local_target.parent.mkdir(parents=True, exist_ok=True)
                local_target.write_bytes(
                    b"wrong-output"
                    if self.write_wrong_output
                    else self._remote_output_bytes()
                )
        elif stage is None and args and args[0] == "ssh" and "sbatch" in args[-1]:
            result = _command_result(stdout="12345\n")
        else:
            result = default
        result.args = list(args)
        result.stage = stage
        return result

    @staticmethod
    def _is_layout(args: list[str]) -> bool:
        if not args or args[0] != "ssh":
            return False
        command = args[-1]
        return all(token in command for token in ("/work", "/out", "/tmp", "/logs"))

    @classmethod
    def _is_input_parent(cls, args: list[str]) -> bool:
        if not args or args[0] != "ssh" or cls._is_layout(args):
            return False
        command = args[-1]
        return "mkdir -p" in command and "/work" in command

    def _remote_output_bytes(self) -> bytes:
        assert self.remote_output is not None
        if self.remote_output.kind.value != "file":
            raise AssertionError("fault matrix currently uses file outputs")
        digest = self.remote_output.content_digest
        if digest == AuthorizedInput.from_path(self._output_source).content_digest:
            return self._output_source.read_bytes()
        raise AssertionError("remote output source drifted")

    @property
    def _output_source(self) -> Path:
        source = getattr(self, "output_source", None)
        if not isinstance(source, Path):
            raise AssertionError("output source was not configured")
        return source


@contextmanager
def _server(
    tmp_path: Path,
    runner: FaultMatrixRunner,
) -> Iterator[MCPHpcServer]:
    with tempfile.TemporaryDirectory(prefix="ozf-", dir="/tmp") as control:
        config_path = tmp_path / "fault-runner.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[runner]",
                    'deployment_id = "fault-matrix"',
                    f'transport_control_root = "{Path(control) / "c"}"',
                    "[cluster]",
                    'ssh_host = "private-hpc"',
                    'ssh_user = "private-user"',
                    'remote_base_dir = "private-runs"',
                    "[execution]",
                    f'artifact_root = "{tmp_path / "artifacts"}"',
                    "use_rsync = false",
                    "[ssh_transport]",
                    'mode = "controlmaster_v1"',
                    "backoff_initial_seconds = 0.0",
                    "backoff_max_seconds = 0.0",
                    "channel_acquire_timeout_seconds = 0.1",
                    "shutdown_timeout_seconds = 0.1",
                ]
            ),
            encoding="utf-8",
        )
        server = MCPHpcServer(config_path)
        server.ssh_runner.command_runner = runner  # type: ignore[assignment]
        try:
            yield server
        finally:
            server.close()


def _runspec(
    *,
    input_path: Path | None = None,
    expected_output: bool = False,
) -> dict[str, object]:
    raw: dict[str, object] = {
        "name": "fault-matrix",
        "stage": "execution",
        "command": ["private-payload", "--fixed"],
        "execution_mode": "ssh",
    }
    if input_path is not None:
        raw["inputs"] = [
            {
                "local_path": str(input_path),
                "remote_path": "input.txt",
                "artifact_id": "authorized-input",
            }
        ]
    if expected_output:
        raw["expected_outputs"] = [
            {
                "path": "result.txt",
                "kind": "file",
                "required": True,
                "non_empty": True,
            }
        ]
    return raw


def _attempt(server: MCPHpcServer, run_id: str):
    return server.attempt_journal.load(run_id)


def test_connect_failure_is_terminal_no_effect_before_remote_work(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.connect_results.append(_command_result(255))
    runner.health_results.append(_command_result(255))
    with _server(tmp_path, runner) as server:
        result = server.call_tool("exec.run", {"runspec": _runspec()})
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "failed"
    assert result["effect_certainty"] == "no_effect"
    assert result["retry_eligibility"] == "terminal"
    assert attempt.phase is RunnerAttemptPhase.TERMINAL
    assert runner.payload_invocations == 0


def test_layout_transport_failure_recovers_once_and_dispatches_once(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.layout_results.append(_command_result(255))
    with _server(tmp_path, runner) as server:
        result = server.call_tool("exec.run", {"runspec": _runspec()})
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "completed"
    assert attempt.pre_effect_recovery_attempts_used == 1
    assert attempt.transport_generation == 2
    assert runner.payload_invocations == 1
    assert runner.accepted_payloads == 1


def test_layout_recovery_budget_exhaustion_never_dispatches_payload(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.layout_results.extend([_command_result(255), _command_result(255)])
    with _server(tmp_path, runner) as server:
        result = server.call_tool("exec.run", {"runspec": _runspec()})
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "failed"
    assert result["error_code"] == "PRE_EFFECT_RECOVERY_EXHAUSTED"
    assert result["effect_certainty"] == "no_effect"
    assert result["retry_eligibility"] == "terminal"
    assert attempt.pre_effect_recovery_attempts_used == 1
    assert runner.payload_invocations == 0


def test_input_parent_transport_failure_recovers_exact_same_run_once(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("authorized-input", encoding="utf-8")
    authorized = AuthorizedInput.from_path(input_path)
    runner = FaultMatrixRunner(authorized_input=authorized)
    runner.input_parent_results.append(_command_result(255))
    runner.input_verification_results.extend(
        [
            _command_result(
                stdout=remote_verification_stdout(
                    authorized,
                    status=RemoteVerificationStatus.MISSING,
                )
            ),
            _command_result(
                stdout=remote_verification_stdout(
                    authorized,
                    status=RemoteVerificationStatus.MISSING,
                )
            )
        ]
    )

    with _server(tmp_path, runner) as server:
        result = server.call_tool(
            "exec.run",
            {"runspec": _runspec(input_path=input_path)},
        )
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "completed"
    assert attempt.pre_effect_recovery_attempts_used == 1
    assert attempt.transport_generation == 2
    assert runner.upload_invocations == 1
    assert runner.payload_invocations == 1


def test_partial_input_transfer_is_verified_then_published_without_reupload(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("authorized-input", encoding="utf-8")
    authorized = AuthorizedInput.from_path(input_path)
    runner = FaultMatrixRunner(authorized_input=authorized)
    runner.upload_results.append(_command_result(255))
    runner.input_verification_results.extend(
        [
            _command_result(
                stdout=remote_verification_stdout(
                    authorized,
                    status=RemoteVerificationStatus.MISSING,
                )
            ),
            _command_result(stdout=remote_verification_stdout(authorized)),
            _command_result(stdout=remote_verification_stdout(authorized)),
            _command_result(stdout=remote_verification_stdout(authorized)),
        ]
    )
    with _server(tmp_path, runner) as server:
        result = server.call_tool(
            "exec.run",
            {"runspec": _runspec(input_path=input_path)},
        )
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "completed"
    assert attempt.pre_effect_recovery_attempts_used == 1
    assert runner.upload_invocations == 1
    assert runner.payload_invocations == 1


def test_preflight_transport_failure_revalidates_input_before_retry(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("authorized-input", encoding="utf-8")
    authorized = AuthorizedInput.from_path(input_path)
    runner = FaultMatrixRunner(authorized_input=authorized)
    runner.preflight_results.extend(
        [
            _command_result(255),
        ]
    )
    with _server(tmp_path, runner) as server:
        result = server.call_tool(
            "exec.run",
            {"runspec": _runspec(input_path=input_path)},
        )
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "completed"
    assert attempt.pre_effect_recovery_attempts_used == 1
    assert runner.stages.count("input_verification") == 4
    assert runner.payload_invocations == 1


def test_deterministic_preflight_failure_does_not_replace_transport_or_dispatch(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.preflight_results.append(
        _command_result(
            stdout=json.dumps(
                [
                    {
                        "kind": "dir",
                        "path": "private-output",
                        "status": "error",
                        "reason": "missing",
                    }
                ]
            )
        )
    )
    with _server(tmp_path, runner) as server:
        result = server.call_tool("exec.run", {"runspec": _runspec()})
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "failed"
    assert result["error_code"] == "PREFLIGHT_FAILED"
    assert attempt.transport_generation == 1
    assert attempt.pre_effect_recovery_attempts_used == 0
    assert runner.payload_invocations == 0


def test_dispatch_not_accepted_retries_exact_run_but_only_one_payload_is_accepted(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.dispatch_results.extend(
        [
            _command_result(126, process_started=False),
            _command_result(0),
        ]
    )
    with _server(tmp_path, runner) as server:
        result = server.call_tool("exec.run", {"runspec": _runspec()})
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "completed"
    assert attempt.pre_effect_recovery_attempts_used == 1
    assert runner.payload_invocations == 2
    assert runner.accepted_payloads == 1


def test_dispatch_in_doubt_is_never_replayed_and_requires_reconciliation(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.dispatch_results.append(_command_result(255))
    with _server(tmp_path, runner) as server:
        result = server.call_tool("exec.run", {"runspec": _runspec()})
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "failed"
    assert result["effect_certainty"] == "dispatch_in_doubt"
    assert result["retry_eligibility"] == "reconcile_required"
    assert result["reconciliation_required"] is True
    assert result["retryable"] is False
    assert attempt.state is RunnerAttemptState.RECONCILIATION_REQUIRED
    assert runner.payload_invocations == 1
    assert runner.accepted_payloads == 1


def test_fetch_transport_recovery_never_reruns_known_terminal_payload(
    tmp_path: Path,
) -> None:
    output_source = tmp_path / "remote-result.txt"
    output_source.write_text("scientific-result", encoding="utf-8")
    remote_output = AuthorizedInput.from_path(output_source)
    runner = FaultMatrixRunner(remote_output=remote_output)
    runner.output_source = output_source
    runner.output_fetch_results.extend([_command_result(255), _command_result(0)])
    with _server(tmp_path, runner) as server:
        result = server.call_tool(
            "exec.run",
            {"runspec": _runspec(expected_output=True)},
        )
        run_id = str(result["run_id"])
        attempt = _attempt(server, run_id)
        resolved = server.resolve_artifact_ref(result["artifacts"]["result.txt"])

    assert result["status"] == "completed"
    assert Path(resolved).read_text(encoding="utf-8") == "scientific-result"
    assert attempt.phase_attempt_counts["outputs_fetching"] == 2
    assert attempt.transport_generation == 2
    assert runner.payload_invocations == 1
    assert runner.output_fetch_invocations == 2


def test_process_restart_resumes_only_output_fetch_for_known_terminal_payload(
    tmp_path: Path,
) -> None:
    output_source = tmp_path / "restart-remote-result.txt"
    output_source.write_text("scientific-result", encoding="utf-8")
    fake = FaultMatrixRunner(
        remote_output=AuthorizedInput.from_path(output_source)
    )
    fake.output_source = output_source
    control = tempfile.TemporaryDirectory(prefix="ozf-", dir="/tmp")
    config_path = tmp_path / "restart-output-fetch.toml"
    config_path.write_text(
        "\n".join(
            [
                "[runner]",
                'deployment_id = "restart-output-fetch"',
                f'transport_control_root = "{Path(control.name) / "c"}"',
                "[cluster]",
                'ssh_host = "private-hpc"',
                'ssh_user = "private-user"',
                'remote_base_dir = "private-runs"',
                "[execution]",
                f'artifact_root = "{tmp_path / "artifacts"}"',
                "use_rsync = false",
                "[ssh_transport]",
                'mode = "controlmaster_v1"',
                "backoff_initial_seconds = 0.0",
                "backoff_max_seconds = 0.0",
                "channel_acquire_timeout_seconds = 0.1",
                "shutdown_timeout_seconds = 0.1",
            ]
        ),
        encoding="utf-8",
    )
    first = MCPHpcServer(config_path)
    first.ssh_runner.command_runner = fake  # type: ignore[assignment]
    reserved = first.reserve_execution(
        {
            "schema_version": "runner_execution_reservation_identity@1",
            "execution_id": "execution_restart_output_fetch",
            "operation_id": "operation_restart_output_fetch",
            "operation_digest": "sha256:" + "1" * 64,
            "approval_digest": "sha256:" + "2" * 64,
            "route_policy_id": "bio_tools.mafft.hpc:v1",
            "adapter_policy_id": "runner_reserved_dispatch:v1",
            "request_digest": "sha256:" + "3" * 64,
            "execution_mode": "ssh",
        }
    )
    run_id = reserved["run_id"]

    def interrupt_fetch(*_args: object, **_kwargs: object) -> object:
        raise KeyboardInterrupt

    first.ssh_runner._fetch_outputs_with_recovery = interrupt_fetch  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        first.submit_reserved_execution(
            run_id=run_id,
            runspec=_runspec(expected_output=True),
        )
    interrupted = first.attempt_journal.load(run_id)
    assert interrupted.phase is RunnerAttemptPhase.OUTPUTS_FETCHING
    assert interrupted.effect_certainty is RunnerEffectCertainty.TERMINAL_KNOWN
    first.close()

    restarted = MCPHpcServer(config_path)
    restarted.ssh_runner.command_runner = fake  # type: ignore[assignment]
    recovery_report = {
        item["run_id"]: item for item in restarted.attempt_recovery_report
    }
    assert recovery_report[run_id]["disposition"] == (
        "resume_same_run_output_fetch"
    )

    recovered = restarted.recover_reserved_execution_outcome(run_id)
    replayed_recovery = restarted.recover_reserved_execution_outcome(run_id)
    attempt = restarted.attempt_journal.load(run_id)
    restarted.close()

    assert recovered["status"] == "completed"
    assert replayed_recovery["status"] == "completed"
    assert recovered["run_id"] == run_id
    assert attempt.state is RunnerAttemptState.TERMINAL
    assert attempt.phase_attempt_counts["outputs_fetching"] == 2
    assert fake.payload_invocations == 1
    assert fake.output_fetch_invocations == 1
    control.cleanup()


def test_output_digest_conflict_is_quarantined_without_payload_replay(
    tmp_path: Path,
) -> None:
    output_source = tmp_path / "remote-result.txt"
    output_source.write_text("scientific-result", encoding="utf-8")
    runner = FaultMatrixRunner(
        remote_output=AuthorizedInput.from_path(output_source)
    )
    runner.output_source = output_source
    runner.write_wrong_output = True
    with _server(tmp_path, runner) as server:
        result = server.call_tool(
            "exec.run",
            {"runspec": _runspec(expected_output=True)},
        )
        run_id = str(result["run_id"])
        quarantine = server.store.read_json(
            run_id,
            "runner_attempt_quarantine.json",
        )

    assert result["status"] == "failed"
    assert result["error_code"] == "OUTPUT_CONTRACT_CONFLICT"
    assert result["effect_certainty"] == "terminal_known"
    assert result["retry_eligibility"] == "terminal"
    assert result["artifacts"] == {}
    assert quarantine["reason_code"] == "output_contract_conflict"
    assert runner.payload_invocations == 1


def test_identity_drift_quarantines_before_recovery_remote_action(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.layout_results.append(_command_result(255))
    with _server(tmp_path, runner) as server:
        spec = RunSpec.from_dict(_runspec())
        spec.run_id = "identity-drift"
        runner.on_layout_failure = lambda: spec.command.append("changed")

        with pytest.raises(RunnerAttemptQuarantined):
            server.ssh_runner.exec_run(spec)

        assert server.store.read_json(
            spec.run_id,
            "runner_attempt_quarantine.json",
        )["reason_code"] == "attempt_identity_drift"
        assert server.transport_manager.current_generation == 1
        assert runner.payload_invocations == 0


def test_slurm_submission_persists_only_opaque_handle_and_verified_control_receipt(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    with _server(tmp_path, runner) as server:
        raw = _runspec()
        raw["execution_mode"] = "sbatch"
        result = server.call_tool("job.submit", {"runspec": raw})
        run_id = str(result["run_id"])
        attempt = _attempt(server, run_id)
        private_handle = server.store.read_json(run_id, "job_handle.json")

    assert result["status"] == "submitted"
    assert result["effect_certainty"] == "effect_known"
    assert result["retry_eligibility"] == "verify_then_retry"
    assert result["reconciliation_required"] is False
    assert "job_id" not in result
    assert "remote_run_dir" not in result
    assert private_handle["job_id"] == "12345"
    assert attempt.phase is RunnerAttemptPhase.REMOTE_PENDING
    assert "slurm_control_script" in attempt.receipt_digests
    assert sum(
        stage is None and "sbatch --parsable" in command[-1]
        for command, stage in zip(runner.commands, runner.stages, strict=True)
    ) == 1


def test_slurm_control_transfer_lost_ack_verifies_same_candidate_without_reupload(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.upload_results.append(_command_result(255))
    with _server(tmp_path, runner) as server:
        raw = _runspec()
        raw["execution_mode"] = "sbatch"
        result = server.call_tool("job.submit", {"runspec": raw})
        attempt = _attempt(server, str(result["run_id"]))

    assert result["status"] == "submitted"
    assert attempt.pre_effect_recovery_attempts_used == 1
    assert runner.upload_invocations == 1
    assert "slurm_control_script" in attempt.receipt_digests
    assert sum(
        stage is None and "sbatch --parsable" in command[-1]
        for command, stage in zip(runner.commands, runner.stages, strict=True)
    ) == 1


def test_slurm_cancel_acceptance_remains_nonterminal_until_exact_handle_poll(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    with _server(tmp_path, runner) as server:
        raw = _runspec()
        raw["execution_mode"] = "sbatch"
        submitted = server.call_tool("job.submit", {"runspec": raw})
        run_id = str(submitted["run_id"])

        cancelled = server.call_tool("job.cancel", {"run_id": run_id})
        status = server.call_tool("job.status", {"run_id": run_id})

    assert cancelled["status"] == "pending"
    assert cancelled["phase"] == "remote_pending"
    assert cancelled["effect_certainty"] == "effect_known"
    assert cancelled["retry_eligibility"] == "verify_then_retry"
    assert cancelled["reconciliation_required"] is False
    assert status["state"] == "unknown"
    assert status["phase"] == "remote_pending"
    assert status["effect_certainty"] == "effect_known"
    assert "job_id" not in cancelled
    assert "job_id" not in status


def test_shutdown_records_active_direct_dispatch_as_ambiguous_without_deleting_evidence(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    with _server(tmp_path, runner) as server:
        spec = RunSpec.from_dict(_runspec())
        spec.run_id = "shutdown-ambiguous"
        server.store.ensure_run_layout(spec.run_id)
        server.store.write_json(spec.run_id, "runspec.json", spec.to_dict())
        server.attempt_journal.create(spec, selected_mode="ssh")
        server.attempt_journal.transition(
            spec.run_id,
            phase=RunnerAttemptPhase.DISPATCHING,
            reason_code="payload_transmission_started",
        )

        report = server.close()
        attempt = server.attempt_journal.load(spec.run_id)

        assert report["ambiguous_direct_run_count"] == 1
        assert attempt.state is RunnerAttemptState.RECONCILIATION_REQUIRED
        assert attempt.phase is RunnerAttemptPhase.DISPATCHING
        assert (
            attempt.effect_certainty
            is RunnerEffectCertainty.DISPATCH_IN_DOUBT
        )
        assert (
            attempt.retry_eligibility
            is RunnerRetryEligibility.RECONCILE_REQUIRED
        )
        assert attempt.reconciliation_required is True
        assert server.store.read_json(spec.run_id, "runner_attempt.json")


def test_every_fault_case_keeps_private_transport_identity_out_of_public_result(
    tmp_path: Path,
) -> None:
    runner = FaultMatrixRunner()
    runner.dispatch_results.append(_command_result(255))
    with _server(tmp_path, runner) as server:
        result = server.call_tool("exec.run", {"runspec": _runspec()})

    public = json.dumps(result, sort_keys=True)
    for private_value in (
        "private-hpc",
        "private-user",
        "private-runs",
        "private-payload",
        "ControlPath",
        "generation",
    ):
        assert private_value not in public
