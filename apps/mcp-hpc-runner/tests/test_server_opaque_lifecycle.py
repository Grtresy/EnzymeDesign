from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest

from mcp_hpc_runner.errors import HpcStagingFailure
from mcp_hpc_runner.models import JobHandle, RunResult, RunSpec
from mcp_hpc_runner.preflight import PreflightResult
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.server import MCPHpcServer


def _config_path(tmp_path: Path) -> Path:
    config_path = tmp_path / "hpc_runner.toml"
    config_path.write_text(
        "\n".join(
            [
                "[cluster]",
                'ssh_host = "hpc"',
                'remote_base_dir = "mcp_runs"',
                "",
                "[execution]",
                f'artifact_root = "{tmp_path / "artifacts"}"',
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _runspec(**extra: Any) -> dict[str, Any]:
    return {
        "name": "opaque-run",
        "stage": "execution",
        "command": ["true"],
        "execution_mode": "ssh",
        **extra,
    }


def _mafft_runspec(**extra: Any) -> dict[str, Any]:
    return _runspec(
        command=["bash", "-lc", "printf tool-output"],
        metadata={
            "tool_contract": {
                "adapter_id": "bio_tools.mafft",
                "tool_id": "bio_tools.mafft",
                "command_template_id": "bio_tools_mafft_sif_v1",
                "preflight_hints": {
                    "entrypoint": {
                        "kind": "sif",
                        "path": "~/caller/injected.sif",
                    }
                },
            }
        },
        **extra,
    )


def _persist_async_run(
    server: MCPHpcServer,
    run_id: str,
    *,
    stored_handle_run_id: str | None = None,
    stored_runspec_run_id: str | None = None,
) -> None:
    handle_run_id = stored_handle_run_id or run_id
    server.store.write_json(
        run_id,
        "job_handle.json",
        JobHandle(
            run_id=handle_run_id,
            job_id="12345",
            remote_run_dir=f"mcp_runs/{handle_run_id}",
        ).to_dict(),
    )
    spec = RunSpec.from_dict(_runspec())
    spec.run_id = stored_runspec_run_id or run_id
    server.store.write_json(run_id, "runspec.json", spec.to_dict())


@pytest.mark.parametrize("tool_name", ["exec.run", "job.submit"])
def test_submit_tools_reject_caller_supplied_run_id(
    tmp_path: Path,
    tool_name: str,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    with pytest.raises(ValueError, match="run_id is server-generated"):
        server.call_tool(tool_name, {"runspec": _runspec(run_id="caller-run")})


def test_exec_run_staging_failure_keeps_server_issued_opaque_run_id(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fail_remote_layout(
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:  # noqa: ARG001
        return CommandResult(
            args=args,
            returncode=255,
            stdout="",
            stderr="private SSH target rejected the connection",
            stage=stage,
            elapsed_seconds=0.5,
        )

    server.command_runner.run = fail_remote_layout  # type: ignore[method-assign]

    with pytest.raises(HpcStagingFailure) as caught:
        server.call_tool("exec.run", {"runspec": _runspec()})

    run_id = caught.value.run_id
    assert re.fullmatch(r"[0-9a-f]{32}", run_id)
    assert server.store.read_json(run_id, "runner_failure.json") == (
        caught.value.to_safe_diagnostic()
    )


def test_exec_run_assigns_opaque_id_and_hides_internal_handle_fields(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))
    captured: dict[str, RunSpec] = {}

    def fake_exec(spec: RunSpec) -> RunResult:
        captured["spec"] = spec
        assert spec.run_id is not None
        return RunResult(
            run_id=spec.run_id,
            requested_mode="ssh",
            selected_mode="ssh",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="completed",
            exit_code=0,
            job_id="12345",
            stdout="unbounded-internal-stdout",
            stderr="",
            artifacts={
                f"mcp_runs/{spec.run_id}/out/a/result.json": (
                    f"/local/artifacts/{spec.run_id}/outputs/a/result.json"
                )
            },
            logs={"stdout": {"inline": "bounded"}},
            metadata={"remote_command": ["secret"]},
        )

    server.ssh_runner.exec_run = fake_exec  # type: ignore[method-assign]

    result = server.call_tool("exec.run", {"runspec": _runspec()})

    assert captured["spec"].run_id == result["run_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", result["run_id"])
    assert set(result) == {
        "run_id",
        "status",
        "selected_mode",
        "exit_code",
        "error_code",
        "artifacts",
        "logs",
    }
    assert result["artifacts"] == {
        "a/result.json": f"/local/artifacts/{result['run_id']}/outputs/a/result.json"
    }
    assert "job_id" not in result
    assert "remote_run_dir" not in result
    assert "stdout" not in result
    assert "metadata" not in result


@pytest.mark.parametrize(
    "field",
    ["toolchain_runtime_request", "toolchain_runtime_identity"],
)
def test_submit_rejects_caller_owned_toolchain_runtime_fields(
    tmp_path: Path,
    field: str,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))
    runspec = _mafft_runspec()
    runspec["metadata"][field] = {"sif_locator": "~/caller/injected.sif"}

    with pytest.raises(ValueError, match="runner-owned toolchain runtime fields"):
        server.call_tool("exec.run", {"runspec": runspec})


def test_exec_run_binds_runner_contract_and_projects_closed_toolchain_identity(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))
    captured: dict[str, RunSpec] = {}
    digest = "sha256:" + "a" * 64

    def fake_exec(spec: RunSpec) -> RunResult:
        captured["spec"] = spec
        runtime_request = dict(spec.metadata["toolchain_runtime_request"])
        return RunResult(
            run_id=str(spec.run_id),
            requested_mode="ssh",
            selected_mode="ssh",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="completed",
            metadata={
                "toolchain_runtime_identity": {
                    "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
                    "attestation_scope": "same_ssh_login_shell_pre_exec",
                    "execution_mode": "ssh",
                    "tool_id": "bio_tools.mafft",
                    "adapter_id": "bio_tools.mafft",
                    "command_template_id": "bio_tools_mafft_sif_v1",
                    "runner_contract_digest": runtime_request[
                        "runner_contract_digest"
                    ],
                    "image_digest": digest,
                    "sif_path": "/private/runner/mafft.sif",
                    "future_private_field": "must-not-cross-boundary",
                }
            },
        )

    server.ssh_runner.exec_run = fake_exec  # type: ignore[method-assign]

    result = server.call_tool("exec.run", {"runspec": _mafft_runspec()})

    bound = captured["spec"].metadata
    assert bound["tool_contract"]["preflight_hints"]["entrypoint"] == {
        "kind": "sif",
        "path": "~/containers/mafft_7.525.sif",
    }
    assert bound["toolchain_runtime_request"] == {
        "schema_id": "mcp_hpc_toolchain_runtime_request@1",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
        "entrypoint_kind": "sif",
        "sif_locator": "~/containers/mafft_7.525.sif",
        "runner_contract_digest": bound["tool_contract"]["runner_contract_digest"],
    }
    identity = result["toolchain_runtime_identity"]
    assert identity == {
        "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
        "attestation_scope": "same_ssh_login_shell_pre_exec",
        "execution_mode": "ssh",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
        "runner_contract_digest": bound["tool_contract"][
            "runner_contract_digest"
        ],
        "image_digest": digest,
    }
    assert "/private/runner" not in str(result)
    assert "future_private_field" not in str(result)


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("tool_id", "bio_tools.hmmbuild"),
        ("command_template_id", "bio_tools_hmmbuild_sif_v1"),
        ("runner_contract_digest", "sha256:" + "f" * 64),
    ],
)
def test_exec_run_fails_closed_when_identity_differs_from_bound_contract(
    tmp_path: Path,
    field: str,
    wrong_value: str,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fake_exec(spec: RunSpec) -> RunResult:
        runtime_request = dict(spec.metadata["toolchain_runtime_request"])
        identity = {
            "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
            "attestation_scope": "same_ssh_login_shell_pre_exec",
            "execution_mode": "ssh",
            "tool_id": runtime_request["tool_id"],
            "adapter_id": runtime_request["adapter_id"],
            "command_template_id": runtime_request["command_template_id"],
            "runner_contract_digest": runtime_request["runner_contract_digest"],
            "image_digest": "sha256:" + "a" * 64,
        }
        identity[field] = wrong_value
        return RunResult(
            run_id=str(spec.run_id),
            requested_mode="ssh",
            selected_mode="ssh",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="completed",
            artifacts={"out/alignment.fasta": "/private/partial/alignment.fasta"},
            metadata={"toolchain_runtime_identity": identity},
        )

    server.ssh_runner.exec_run = fake_exec  # type: ignore[method-assign]

    result = server.call_tool("exec.run", {"runspec": _mafft_runspec()})

    assert result["status"] == "failed"
    assert result["error_code"] == "TOOLCHAIN_IDENTITY_MISSING"
    assert result["artifacts"] == {}
    assert "toolchain_runtime_identity" not in result


def test_slurm_projection_never_claims_ssh_toolchain_attestation(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fake_submit(spec: RunSpec) -> RunResult:
        return RunResult(
            run_id=str(spec.run_id),
            requested_mode="sbatch",
            selected_mode="sbatch",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="submitted",
            metadata={
                "toolchain_runtime_identity": {
                    "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
                    "attestation_scope": "same_ssh_login_shell_pre_exec",
                    "execution_mode": "ssh",
                    "tool_id": "bio_tools.mafft",
                    "adapter_id": "bio_tools.mafft",
                    "command_template_id": "bio_tools_mafft_sif_v1",
                    "runner_contract_digest": "sha256:" + "b" * 64,
                    "image_digest": "sha256:" + "a" * 64,
                }
            },
        )

    server.slurm_runner.submit = fake_submit  # type: ignore[method-assign]

    result = server.call_tool("job.submit", {"runspec": _mafft_runspec()})

    assert result["selected_mode"] == "sbatch"
    assert "toolchain_runtime_identity" not in result


def test_job_submit_rejects_runner_mode_mismatch(tmp_path: Path) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fake_submit(spec: RunSpec) -> RunResult:
        return RunResult(
            run_id=str(spec.run_id),
            requested_mode="sbatch",
            selected_mode="ssh",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="submitted",
        )

    server.slurm_runner.submit = fake_submit  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="authoritative dispatch mode"):
        server.call_tool("job.submit", {"runspec": _mafft_runspec()})


def test_run_result_with_missing_status_fails_closed(tmp_path: Path) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fake_exec(spec: RunSpec) -> RunResult:
        assert spec.run_id is not None
        result = RunResult(
            run_id=spec.run_id,
            requested_mode="ssh",
            selected_mode="ssh",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="failed",
        )
        result.status = None  # type: ignore[assignment]
        return result

    server.ssh_runner.exec_run = fake_exec  # type: ignore[method-assign]

    result = server.call_tool("exec.run", {"runspec": _runspec()})

    assert result["status"] == "failed"
    assert result["error_code"] == "RUNNER_STATUS_INVALID"


def test_uppercase_success_cannot_bypass_required_toolchain_identity(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fake_exec(spec: RunSpec) -> RunResult:
        result = RunResult(
            run_id=str(spec.run_id),
            requested_mode="ssh",
            selected_mode="ssh",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="completed",
            artifacts={"out/alignment.fasta": "/private/partial/alignment.fasta"},
        )
        result.status = "COMPLETED"
        return result

    server.ssh_runner.exec_run = fake_exec  # type: ignore[method-assign]

    result = server.call_tool("exec.run", {"runspec": _mafft_runspec()})

    assert result["status"] == "failed"
    assert result["error_code"] == "TOOLCHAIN_IDENTITY_MISSING"
    assert result["artifacts"] == {}


def test_unknown_runner_status_is_closed_to_failed(tmp_path: Path) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fake_exec(spec: RunSpec) -> RunResult:
        result = RunResult(
            run_id=str(spec.run_id),
            requested_mode="ssh",
            selected_mode="ssh",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="failed",
            artifacts={"out/result.txt": "/private/partial/result.txt"},
        )
        result.status = "unexpected_future_success"
        return result

    server.ssh_runner.exec_run = fake_exec  # type: ignore[method-assign]

    result = server.call_tool("exec.run", {"runspec": _runspec()})

    assert result["status"] == "failed"
    assert result["error_code"] == "RUNNER_STATUS_INVALID"
    assert result["artifacts"] == {}


def test_job_submit_hides_raw_scheduler_output(tmp_path: Path) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    def fake_submit(spec: RunSpec) -> RunResult:
        assert spec.run_id is not None
        return RunResult(
            run_id=spec.run_id,
            requested_mode="sbatch",
            selected_mode="sbatch",
            remote_run_dir=f"mcp_runs/{spec.run_id}",
            status="submitted",
            job_id="secret-job-12345",
            stdout="secret-job-12345",
            logs={"submit": {"inline": "secret-job-12345"}},
        )

    server.slurm_runner.submit = fake_submit  # type: ignore[method-assign]

    result = server.call_tool("job.submit", {"runspec": _runspec()})

    assert result["status"] == "submitted"
    assert result["logs"] == {}
    assert "job_id" not in result
    assert "remote_run_dir" not in result
    assert "secret-job-12345" not in str(result)


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "job.status",
            {"run_id": "run-001", "job_id": "123", "remote_run_dir": "/etc"},
        ),
        ("job.logs", {"run_id": "run-001", "remote_run_dir": "/etc"}),
        ("job.cancel", {"run_id": "run-001", "job_id": "123"}),
        (
            "job.fetch_artifacts",
            {"run_id": "run-001", "runspec": _runspec()},
        ),
    ],
)
def test_lifecycle_tools_reject_raw_or_inline_fallback_arguments(
    tmp_path: Path,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    with pytest.raises(ValueError, match="unexpected arguments"):
        server.call_tool(tool_name, arguments)


def test_lifecycle_rejects_missing_or_foreign_persisted_handle(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))

    with pytest.raises(ValueError, match="persisted job handle"):
        server.call_tool("job.status", {"run_id": "missing-run"})
    assert not server.store.run_root("missing-run").exists()

    _persist_async_run(
        server,
        "run-a",
        stored_handle_run_id="run-b",
    )
    with pytest.raises(ValueError, match="does not belong to run_id"):
        server.call_tool("job.status", {"run_id": "run-a"})


def test_lifecycle_rejects_guessed_opaque_handle_without_mutating_store(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))
    guessed_run_id = "0" * 32

    with pytest.raises(ValueError, match="persisted job handle"):
        server.call_tool("job.status", {"run_id": guessed_run_id})

    assert not server.store.run_root(guessed_run_id).exists()


def test_fetch_rejects_mismatched_persisted_runspec(tmp_path: Path) -> None:
    server = MCPHpcServer(_config_path(tmp_path))
    _persist_async_run(
        server,
        "run-a",
        stored_runspec_run_id="run-b",
    )

    with pytest.raises(ValueError, match="Persisted RunSpec does not belong"):
        server.call_tool("job.fetch_artifacts", {"run_id": "run-a"})


def test_restart_loads_persisted_handle_by_opaque_run_id_only(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    first_server = MCPHpcServer(config_path)
    _persist_async_run(first_server, "persisted-run")

    restarted_server = MCPHpcServer(config_path)

    class FakeCommandRunner:
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
                args=args,
                returncode=0,
                stdout="RUNNING\n",
                stderr="",
                stage=stage,
            )

    restarted_server.slurm_runner.command_runner = FakeCommandRunner()  # type: ignore[assignment]

    result = restarted_server.call_tool(
        "job.status",
        {"run_id": "persisted-run"},
    )

    assert result["run_id"] == "persisted-run"
    assert result["state"] == "running"
    assert "job_id" not in result
    assert "remote_run_dir" not in result


def test_submit_persists_server_id_in_runspec_and_handle_for_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config_path(tmp_path)
    server = MCPHpcServer(config_path)

    class FakeCommandRunner:
        def run(
            self,
            args: list[str],
            check: bool = False,
            *,
            timeout: float | None = None,
            stage: str | None = None,
        ) -> CommandResult:
            del check, timeout
            output = "12345\n" if "sbatch" in " ".join(args) else ""
            return CommandResult(
                args=args,
                returncode=0,
                stdout=output,
                stderr="",
                stage=stage,
            )

    fake_runner = FakeCommandRunner()
    server.slurm_runner.command_runner = fake_runner  # type: ignore[assignment]
    server.slurm_runner._ensure_remote_layout = (  # type: ignore[method-assign]
        lambda run_id, remote_run_dir: None
    )
    server.slurm_runner.staging.upload_inputs = (  # type: ignore[method-assign]
        lambda run_id, inputs, remote_run_dir: []
    )
    server.slurm_runner.staging.build_upload_command = (  # type: ignore[method-assign]
        lambda local_path, remote_path, use_rsync: ["upload"]
    )
    monkeypatch.setattr(
        "mcp_hpc_runner.slurm.run_preflight",
        lambda spec, remote_run_dir, config, command_runner: PreflightResult(),
    )

    submitted = server.call_tool("job.submit", {"runspec": _runspec()})
    run_id = submitted["run_id"]
    stored_spec = RunSpec.from_dict(server.store.read_json(run_id, "runspec.json"))
    stored_handle = JobHandle.from_dict(
        server.store.read_json(run_id, "job_handle.json")
    )

    assert re.fullmatch(r"[0-9a-f]{32}", run_id)
    assert stored_spec.run_id == run_id
    assert stored_handle.run_id == run_id
    assert stored_handle.job_id == "12345"

    restarted = MCPHpcServer(config_path)
    restarted.slurm_runner.command_runner = FakeCommandRunner()  # type: ignore[assignment]
    restarted_status = restarted.call_tool("job.status", {"run_id": run_id})

    assert restarted_status["run_id"] == run_id


def test_lifecycle_responses_hide_raw_handles_and_fetch_uses_persisted_runspec(
    tmp_path: Path,
) -> None:
    server = MCPHpcServer(_config_path(tmp_path))
    _persist_async_run(server, "run-001")
    captured: dict[str, object] = {}

    def fake_logs(
        handle: JobHandle,
        tail_lines: int = 200,
    ) -> dict[str, object]:
        captured["logs_handle"] = handle
        captured["tail_lines"] = tail_lines
        return {
            "run_id": handle.run_id,
            "job_id": handle.job_id,
            "remote_stdout_path": f"{handle.remote_run_dir}/logs/stdout",
            "remote_stderr_path": f"{handle.remote_run_dir}/logs/stderr",
            "stdout": {"inline": "bounded stdout"},
            "stderr": {"inline": ""},
        }

    def fake_cancel(handle: JobHandle) -> RunResult:
        captured["cancel_handle"] = handle
        return RunResult(
            run_id=handle.run_id,
            requested_mode="sbatch",
            selected_mode="sbatch",
            remote_run_dir=handle.remote_run_dir,
            status="cancelled",
            job_id=handle.job_id,
        )

    def fake_fetch(spec: RunSpec, handle: JobHandle) -> RunResult:
        captured["fetch_spec"] = spec
        captured["fetch_handle"] = handle
        return RunResult(
            run_id=handle.run_id,
            requested_mode="sbatch",
            selected_mode="sbatch",
            remote_run_dir=handle.remote_run_dir,
            status="completed",
            job_id=handle.job_id,
            artifacts={
                f"{handle.remote_run_dir}/out/result.json": (
                    f"/local/{handle.run_id}/outputs/result.json"
                )
            },
        )

    server.slurm_runner.logs = fake_logs  # type: ignore[method-assign]
    server.slurm_runner.cancel = fake_cancel  # type: ignore[method-assign]
    server.slurm_runner.fetch_artifacts = fake_fetch  # type: ignore[method-assign]

    logs = server.call_tool("job.logs", {"run_id": "run-001", "tail_lines": 20})
    cancelled = server.call_tool("job.cancel", {"run_id": "run-001"})
    fetched = server.call_tool("job.fetch_artifacts", {"run_id": "run-001"})

    assert logs == {
        "run_id": "run-001",
        "stdout": {"inline": "bounded stdout"},
        "stderr": {"inline": ""},
    }
    for response in (cancelled, fetched):
        assert "job_id" not in response
        assert "remote_run_dir" not in response
    assert fetched["artifacts"] == {
        "result.json": "/local/run-001/outputs/result.json"
    }
    assert captured["tail_lines"] == 20
    assert isinstance(captured["fetch_spec"], RunSpec)
    assert captured["fetch_spec"].run_id == "run-001"


def test_lifecycle_tool_schemas_only_accept_opaque_run_id(tmp_path: Path) -> None:
    server = MCPHpcServer(_config_path(tmp_path))
    schemas = {
        tool["name"]: tool["inputSchema"]
        for tool in server._tools()  # noqa: SLF001 - schema is the unit under test.
    }

    assert schemas["job.status"] == {
        "type": "object",
        "required": ["run_id"],
        "additionalProperties": False,
        "properties": {"run_id": {"type": "string"}},
    }
    assert set(schemas["job.logs"]["properties"]) == {"run_id", "tail_lines"}
    assert schemas["job.logs"]["required"] == ["run_id"]
    assert schemas["job.logs"]["additionalProperties"] is False
    assert schemas["job.cancel"] == schemas["job.status"]
    assert schemas["job.fetch_artifacts"] == schemas["job.status"]
    assert schemas["exec.run"]["properties"]["runspec"]["not"] == {
        "required": ["run_id"]
    }
