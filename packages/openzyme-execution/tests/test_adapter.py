from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from openzyme_domain import RunStatus
from openzyme_execution import HpcRunnerExecutionAdapter
from openzyme_execution import map_runner_status_to_run_status
from openzyme_runtime import LimiterRegistry


_TOOLCHAIN_RUNTIME_IDENTITY = {
    "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
    "attestation_scope": "same_ssh_login_shell_pre_exec",
    "execution_mode": "ssh",
    "tool_id": "bio_tools.mafft",
    "adapter_id": "bio_tools.mafft",
    "command_template_id": "bio_tools_mafft_sif_v1",
    "runner_contract_digest": "sha256:" + "a" * 64,
    "image_digest": "sha256:" + "b" * 64,
}


class FakeRunnerServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.resolved_artifact_refs: list[str] = []

    def resolve_artifact_ref(self, artifact_ref: str) -> str:
        self.resolved_artifact_refs.append(artifact_ref)
        return "/tmp/" + artifact_ref.rsplit("/", maxsplit=1)[-1]

    def reserve_execution(self, identity):  # type: ignore[no-untyped-def]
        self.calls.append(("reserve_execution", dict(identity)))
        return {
            "run_id": "reserved_run_001",
            "identity_digest": "sha256:" + "1" * 64,
        }

    def submit_reserved_execution(
        self,
        *,
        run_id,
        runspec,
        mode_override=None,
    ):  # type: ignore[no-untyped-def]
        self.calls.append(
            (
                "submit_reserved_execution",
                {
                    "run_id": run_id,
                    "runspec": runspec,
                    "mode_override": mode_override,
                },
            )
        )
        return {
            "run_id": run_id,
            "selected_mode": "ssh",
            "status": "completed",
            "artifacts": {},
        }

    def inspect_reserved_execution(self, run_id):  # type: ignore[no-untyped-def]
        self.calls.append(("inspect_reserved_execution", {"run_id": run_id}))
        return {
            "run_id": run_id,
            "status": "reserved",
            "selected_mode": "ssh",
            "phase": "allocated",
            "effect_certainty": "no_effect",
            "retry_eligibility": "same_phase_safe",
            "reconciliation_required": False,
            "retryable": True,
            "runner_attempt_receipt_digest": "sha256:" + "2" * 64,
            "artifacts": {},
        }

    def recover_reserved_execution_outcome(
        self,
        run_id,
    ):  # type: ignore[no-untyped-def]
        self.calls.append(
            ("recover_reserved_execution_outcome", {"run_id": run_id})
        )
        return {
            "run_id": run_id,
            "status": "completed",
            "selected_mode": "ssh",
            "phase": "terminal",
            "effect_certainty": "terminal_known",
            "retry_eligibility": "terminal",
            "reconciliation_required": False,
            "retryable": False,
            "runner_attempt_receipt_digest": "sha256:" + "3" * 64,
            "exit_code": 0,
            "artifacts": {},
        }

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name == "job.status":
            return {
                "run_id": str(arguments["run_id"]),
                "state": "completed",
                "exit_code": 0,
            }
        if name == "job.fetch_artifacts":
            return {
                "run_id": str(arguments["run_id"]),
                "requested_mode": "sbatch",
                "selected_mode": "sbatch",
                "status": "completed",
                "artifacts": {
                    "a/result.json": (
                        f"runner-artifact://{arguments['run_id']}/a/result.json"
                    ),
                },
            }
        return {
            "run_id": "run_001",
            "requested_mode": "auto",
            "selected_mode": "ssh",
            "status": "completed",
            "artifacts": {
                "result.json": "runner-artifact://run_001/result.json",
            },
        }


def test_runner_status_mapping_covers_minimum_execution_lifecycle() -> None:
    assert map_runner_status_to_run_status("submitted") is RunStatus.QUEUED
    assert map_runner_status_to_run_status("running") is RunStatus.RUNNING
    assert map_runner_status_to_run_status("completed") is RunStatus.SUCCEEDED
    assert map_runner_status_to_run_status("cancelled") is RunStatus.CANCELLED
    assert map_runner_status_to_run_status("failed") is RunStatus.FAILED


def test_hpc_runner_adapter_requires_injected_runner_server() -> None:
    with pytest.raises(ValueError, match="requires an injected runner server"):
        HpcRunnerExecutionAdapter()


def test_hpc_runner_adapter_calls_real_boundary_shape_and_normalizes_output() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    outcome = adapter.submit_execution(
        "sess_001",
        {
            "tool_name": "exec.run",
            "runspec": {
                "name": "fpocket",
                "stage": "execution",
                "command": ["fpocket", "-f", "input.pdb"],
                "execution_mode": "auto",
                "metadata": {"tool_contract": {"adapter_id": "fpocket"}},
            },
        },
    )

    assert server.calls[0][0] == "exec.run"
    sent_runspec = server.calls[0][1]["runspec"]
    assert sent_runspec["metadata"]["openzyme"]["session_id"] == "sess_001"
    assert outcome.run_id == "run_001"
    assert outcome.status is RunStatus.SUCCEEDED
    assert outcome.execution_mode == "ssh"
    assert outcome.remote_run_dir == "opaque://run_001"
    assert outcome.job_id is None
    assert outcome.artifacts[0].storage_uri == "/tmp/result.json"
    assert outcome.artifacts[0].kind.value == "result"
    assert server.resolved_artifact_refs == [
        "runner-artifact://run_001/result.json"
    ]


def test_hpc_runner_adapter_projects_only_safe_ssh_toolchain_identity_fields() -> None:
    adapter = HpcRunnerExecutionAdapter(server=FakeRunnerServer())

    outcome = adapter._normalize_result(
        {
            "run_id": "run_001",
            "selected_mode": "ssh",
            "status": "completed",
            "artifacts": {},
            "toolchain_runtime_identity": {
                **_TOOLCHAIN_RUNTIME_IDENTITY,
                "sif_path": "/private/tool.sif",
                "command": ["apptainer", "exec", "/private/tool.sif"],
                "secret": "must-not-propagate",
            },
        }
    )

    assert outcome.toolchain_runtime_identity == _TOOLCHAIN_RUNTIME_IDENTITY
    assert (
        outcome.raw_result["toolchain_runtime_identity"]
        == _TOOLCHAIN_RUNTIME_IDENTITY
    )
    assert set(outcome.raw_result["toolchain_runtime_identity"]) == set(
        _TOOLCHAIN_RUNTIME_IDENTITY
    )


def test_hpc_runner_adapter_does_not_project_toolchain_identity_for_slurm() -> None:
    adapter = HpcRunnerExecutionAdapter(server=FakeRunnerServer())

    outcome = adapter._normalize_result(
        {
            "run_id": "run_001",
            "selected_mode": "sbatch",
            "status": "completed",
            "artifacts": {},
            "toolchain_runtime_identity": _TOOLCHAIN_RUNTIME_IDENTITY,
        }
    )

    assert outcome.toolchain_runtime_identity is None
    assert "toolchain_runtime_identity" not in outcome.raw_result


def test_hpc_runner_adapter_does_not_project_failed_partial_artifacts() -> None:
    adapter = HpcRunnerExecutionAdapter(server=FakeRunnerServer())

    outcome = adapter._normalize_result(
        {
            "run_id": "run_failed",
            "selected_mode": "ssh",
            "status": "failed",
            "artifacts": {
                "bio_tools/mafft/alignment.fasta": (
                    "/private/partial/alignment.fasta"
                )
            },
        }
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.artifacts == ()
    assert outcome.raw_result["artifacts"] == {}
    assert "/private/partial" not in str(outcome.raw_result)


def test_hpc_runner_adapter_preserves_transport_failure_taxonomy() -> None:
    adapter = HpcRunnerExecutionAdapter(server=FakeRunnerServer())

    outcome = adapter._normalize_result(
        {
            "run_id": "run_transport_failed",
            "selected_mode": "ssh",
            "status": "failed",
            "exit_code": 255,
            "error_code": "SSH_CONNECTION_TIMEOUT",
            "stage": "remote_execution",
            "stdout": "private stdout",
            "stderr": "private stderr",
            "logs": {"stderr": {"inline": "private inline diagnostic"}},
            "artifacts": {
                "bio_tools/cdhit/clustered.fasta": (
                    "/private/partial/clustered.fasta"
                )
            },
        }
    )

    assert outcome.status is RunStatus.FAILED
    assert outcome.exit_code == 255
    assert outcome.artifacts == ()
    assert outcome.raw_result["error_code"] == "SSH_CONNECTION_TIMEOUT"
    assert outcome.raw_result["stage"] == "remote_execution"
    assert outcome.raw_result["artifacts"] == {}
    assert "private" not in str(outcome.raw_result)


def test_hpc_runner_adapter_rejects_unknown_tool_names() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    with pytest.raises(ValueError, match="unsupported execution tool"):
        adapter.submit_execution(
            "sess_001",
            {
                "tool_name": "protein_engineering_pipeline",
                "runspec": {
                    "name": "pipeline-run",
                    "stage": "execution",
                    "command": ["echo", "ok"],
                    "execution_mode": "auto",
                    "metadata": {},
                },
            },
        )

    assert server.calls == []


def test_hpc_runner_adapter_rejects_caller_supplied_run_id() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    with pytest.raises(ValueError, match="run_id is server-generated"):
        adapter.submit_execution(
            "sess_001",
            {
                "tool_name": "exec.run",
                "runspec": {
                    "run_id": "caller-run",
                    "name": "pipeline-run",
                    "stage": "execution",
                    "command": ["echo", "ok"],
                },
            },
        )

    assert server.calls == []


def test_hpc_runner_adapter_queries_status_and_fetches_artifacts() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    status = adapter.get_execution_status(
        run_id="run_001",
    )
    fetched = adapter.fetch_execution_artifacts(
        run_id="run_001",
    )
    cancelled = adapter.cancel_execution(run_id="run_001")

    assert status.status is RunStatus.SUCCEEDED
    assert fetched.artifacts[0].relative_path == "a/result.json"
    assert cancelled.run_id == "run_001"
    assert [name for name, _ in server.calls[-3:]] == [
        "job.status",
        "job.fetch_artifacts",
        "job.cancel",
    ]
    for _, arguments in server.calls[-3:]:
        assert arguments == {"run_id": "run_001"}


def test_hpc_runner_adapter_reserves_dispatches_and_inspects_exact_run() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)
    identity = {
        "schema_version": "runner_execution_reservation_identity@1",
        "execution_id": "exec_001",
    }

    reserved = adapter.reserve_execution(identity)
    outcome = adapter.submit_reserved_execution(
        "sess_001",
        {
            "tool_name": "exec.run",
            "runspec": {
                "name": "durable-run",
                "stage": "execution",
                "command": ["true"],
                "execution_mode": "ssh",
            },
        },
        run_id=reserved["run_id"],
    )
    observation = adapter.inspect_reserved_execution(
        run_id=reserved["run_id"]
    )

    assert outcome.run_id == "reserved_run_001"
    assert observation.run_id == "reserved_run_001"
    assert observation.status == "reserved"
    assert observation.effect_certainty == "no_effect"
    sent = server.calls[1][1]
    assert sent["run_id"] == "reserved_run_001"
    assert sent["runspec"]["metadata"]["openzyme"]["session_id"] == "sess_001"


def test_hpc_runner_adapter_preserves_lowercase_sealed_error_code() -> None:
    class FailedRunnerServer(FakeRunnerServer):
        def inspect_reserved_execution(self, run_id):  # type: ignore[no-untyped-def]
            return {
                "run_id": run_id,
                "status": "failed",
                "selected_mode": "ssh",
                "phase": "terminal",
                "effect_certainty": "no_effect",
                "retry_eligibility": "terminal",
                "reconciliation_required": False,
                "retryable": False,
                "runner_attempt_receipt_digest": "sha256:" + "2" * 64,
                "error_code": "transport_connect_failed",
                "artifacts": {},
            }

    adapter = HpcRunnerExecutionAdapter(server=FailedRunnerServer())

    observation = adapter.inspect_reserved_execution(
        run_id="reserved_run_001"
    )

    assert observation.status == "failed"
    assert observation.error_code == "transport_connect_failed"
    assert observation.effect_certainty == "no_effect"
    assert observation.retry_eligibility == "terminal"


def test_hpc_runner_adapter_recovers_only_an_exact_terminal_reserved_run() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    outcome = adapter.recover_reserved_execution_outcome(
        run_id="reserved_run_001"
    )

    assert outcome.run_id == "reserved_run_001"
    assert outcome.status is RunStatus.SUCCEEDED
    assert [name for name, _ in server.calls] == [
        "recover_reserved_execution_outcome"
    ]


def test_hpc_runner_adapter_treats_pdbqt_as_structure() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    outcome = adapter._normalize_result(
        {
            "run_id": "run_001",
            "selected_mode": "ssh",
            "status": "completed",
            "artifacts": {
                "vina_out.pdbqt": "runner-artifact://run_001/vina_out.pdbqt",
            },
        }
    )

    assert outcome.artifacts[0].kind.value == "structure"


def test_hpc_runner_adapter_limits_runner_boundary_calls() -> None:
    class SlowRunnerServer(FakeRunnerServer):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.observed_max = 0
            self.lock = threading.Lock()

        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            with self.lock:
                self.active += 1
                self.observed_max = max(self.observed_max, self.active)
            try:
                time.sleep(0.01)
                return super().call_tool(name, arguments)
            finally:
                with self.lock:
                    self.active -= 1

    server = SlowRunnerServer()
    adapter = HpcRunnerExecutionAdapter(
        server=server,
        limiter_registry=LimiterRegistry({"execution_provider": 1}),
    )

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(
                adapter.submit_execution,
                "ep_001",
                {
                    "tool_name": "exec.run",
                    "runspec": {
                        "name": f"run-{index}",
                        "stage": "execution",
                        "command": ["echo", "ok"],
                        "execution_mode": "auto",
                        "metadata": {},
                    },
                },
            )
            for index in range(6)
        ]
        for future in futures:
            future.result(timeout=2)

    assert server.observed_max == 1
