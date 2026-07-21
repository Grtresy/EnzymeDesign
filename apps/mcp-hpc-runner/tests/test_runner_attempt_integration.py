from __future__ import annotations

import json
from pathlib import Path
import tempfile

from mcp_hpc_runner.attempts import RunnerAttemptPhase
from mcp_hpc_runner.attempts import RunnerAttemptState
from mcp_hpc_runner.attempts import RunnerEffectCertainty
from mcp_hpc_runner.attempts import RunnerRetryEligibility
from mcp_hpc_runner.models import RunSpec
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.server import MCPHpcServer
from mcp_hpc_runner.verification import AuthorizedInput
from mcp_hpc_runner.verification import remote_verification_stdout


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


class IntegratedRunner:
    def __init__(
        self,
        authorized: AuthorizedInput,
        *,
        fail_dispatch: bool = False,
    ) -> None:
        self.authorized = authorized
        self.fail_dispatch = fail_dispatch
        self.commands: list[list[str]] = []
        self.stages: list[str | None] = []

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
        if stage == "input_verification":
            stdout = remote_verification_stdout(self.authorized)
        elif stage == "preflight":
            stdout = _successful_preflight_receipt(args)
        elif stage == "remote_execution":
            if self.fail_dispatch:
                raise OSError("private transport disappeared after transmission")
            stdout = "scientific output"
        else:
            stdout = ""
        return CommandResult(
            args=list(args),
            returncode=0,
            stdout=stdout,
            stderr="",
            stage=stage,
        )


def _config(tmp_path: Path, control_root: Path) -> Path:
    path = tmp_path / "runner.toml"
    path.write_text(
        "\n".join(
            [
                "[runner]",
                'deployment_id = "attempt-integration"',
                f'transport_control_root = "{control_root}"',
                "[cluster]",
                'ssh_host = "private-hpc"',
                'ssh_user = "private-user"',
                'remote_base_dir = "private-runs"',
                "[execution]",
                f'artifact_root = "{tmp_path / "artifacts"}"',
                "use_rsync = false",
                "[ssh_transport]",
                'mode = "controlmaster_v1"',
                "channel_acquire_timeout_seconds = 0.1",
                "shutdown_timeout_seconds = 0.1",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _runspec(local: Path) -> dict[str, object]:
    return {
        "name": "journal-integration",
        "stage": "execution",
        "command": ["private-payload", "--private-argument"],
        "execution_mode": "ssh",
        "inputs": [
            {
                "local_path": str(local),
                "remote_path": "input.txt",
                "artifact_id": "private-artifact",
            }
        ],
        "metadata": {
            "openzyme": {
                "session_id": "private-session",
                "controlled_operation_id": "private-operation",
                "approval_id": "private-approval",
            }
        },
    }


def test_enabled_ssh_run_journals_verified_single_dispatch(tmp_path: Path) -> None:
    local = tmp_path / "input.txt"
    local.write_text("authorized bytes", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="ozi-", dir="/tmp") as raw_control:
        server = MCPHpcServer(_config(tmp_path, Path(raw_control) / "c"))
        runner = IntegratedRunner(AuthorizedInput.from_path(local))
        server.ssh_runner.command_runner = runner  # type: ignore[assignment]
        try:
            result = server.call_tool("exec.run", {"runspec": _runspec(local)})
            run_id = str(result["run_id"])
            attempt = server.attempt_journal.load_bound(
                run_id,
                RunSpec.from_dict(server.store.read_json(run_id, "runspec.json")),
                selected_mode="ssh",
            )
            preflight = server.store.read_json(run_id, "preflight_manifest.json")
        finally:
            close_report = server.close()

    assert result["status"] == "completed"
    assert attempt.phase is RunnerAttemptPhase.TERMINAL
    assert attempt.state is RunnerAttemptState.TERMINAL
    assert attempt.effect_certainty is RunnerEffectCertainty.TERMINAL_KNOWN
    assert attempt.retry_eligibility is RunnerRetryEligibility.TERMINAL
    assert runner.stages.count("remote_execution") == 1
    assert runner.stages.count("input_verification") == 3
    assert preflight["runner_attempt"]["manifest_body_digest"] == (
        attempt.receipt_digests["preflight_manifest"]
    )
    assert close_report["ambiguous_direct_run_count"] == 0
    public = json.dumps(result, sort_keys=True)
    for private_value in (
        "private-hpc",
        "private-user",
        "private-runs",
        "private-payload",
        "private-argument",
        "private-operation",
        "private-approval",
        "ControlPath",
    ):
        assert private_value not in public


def test_dispatch_exception_is_recorded_unknown_and_never_replayed(
    tmp_path: Path,
) -> None:
    local = tmp_path / "input.txt"
    local.write_text("authorized bytes", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="ozi-", dir="/tmp") as raw_control:
        config_path = _config(tmp_path, Path(raw_control) / "c")
        server = MCPHpcServer(config_path)
        runner = IntegratedRunner(
            AuthorizedInput.from_path(local),
            fail_dispatch=True,
        )
        server.ssh_runner.command_runner = runner  # type: ignore[assignment]
        try:
            result = server.call_tool("exec.run", {"runspec": _runspec(local)})
            run_id = str(result["run_id"])
            attempt = server.attempt_journal.load(run_id)
            close_report = server.close()
        finally:
            if server.transport_manager.current_generation:
                server.close()

        restarted = MCPHpcServer(config_path)
        try:
            recovered = {
                item["run_id"]: item for item in restarted.attempt_recovery_report
            }
            assert recovered[run_id]["status"] == "reconciliation_required"
            assert restarted.attempt_journal.load(run_id).state_version == (
                attempt.state_version
            )
        finally:
            restarted.close()

    assert attempt.phase is RunnerAttemptPhase.DISPATCHING
    assert attempt.state is RunnerAttemptState.RECONCILIATION_REQUIRED
    assert attempt.effect_certainty is RunnerEffectCertainty.DISPATCH_IN_DOUBT
    assert attempt.retry_eligibility is RunnerRetryEligibility.RECONCILE_REQUIRED
    assert attempt.reconciliation_required is True
    assert result["status"] == "failed"
    assert result["error_code"] == "DISPATCH_IN_DOUBT"
    assert result["effect_certainty"] == "dispatch_in_doubt"
    assert result["retry_eligibility"] == "reconcile_required"
    assert result["reconciliation_required"] is True
    assert result["retryable"] is False
    assert runner.stages.count("remote_execution") == 1
    assert close_report["ambiguous_direct_run_count"] == 1
