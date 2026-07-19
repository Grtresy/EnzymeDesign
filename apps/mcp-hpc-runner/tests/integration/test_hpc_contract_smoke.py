from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import time
from typing import Any

import pytest

from mcp_hpc_runner.config import RunnerConfig, load_config
from mcp_hpc_runner.contract_manifest import (
    ToolContract,
    base_contract_record,
    build_discovery_runspec,
    build_smoke_runspec,
    load_contract_manifest,
    result_summary,
    sanitize_record,
    write_contract_record,
)
from mcp_hpc_runner.errors import FailureMapper
from mcp_hpc_runner.models import RunResult, RunSpec
from mcp_hpc_runner.preflight import PreflightError
from mcp_hpc_runner.remote import CommandRunner
from mcp_hpc_runner.slurm import SlurmRunner
from mcp_hpc_runner.ssh_runner import SSHRunner
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore


pytestmark = [pytest.mark.integration, pytest.mark.live_hpc]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _repo_root() -> Path:
    return _project_root().parents[1]


def _default_config_path() -> Path:
    return _project_root() / "config" / "hpc_runner.toml"


def _timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


@pytest.fixture(scope="session")
def contract_record_root() -> Path:
    configured = os.getenv("HPC_CONTRACT_RECORD_ROOT")
    if configured:
        root = Path(configured).expanduser()
    else:
        root = _repo_root() / ".mcp_hpc_runner" / "contract_runs" / _timestamp()
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="session")
def runner_config(contract_record_root: Path) -> RunnerConfig:
    configured_path = (
        os.getenv("OPENZYME_HPC_RUNNER_CONFIG")
        or os.getenv("HPC_RUNNER_CONFIG")
        or str(_default_config_path())
    )
    config_path = Path(configured_path).expanduser()
    if not config_path.exists():
        pytest.skip(f"Integration config not found: {config_path}")

    config = load_config(config_path)
    if os.getenv("HPC_SSH_HOST"):
        config.cluster.ssh_host = os.environ["HPC_SSH_HOST"]
    if os.getenv("HPC_SSH_USER") is not None:
        config.cluster.ssh_user = os.getenv("HPC_SSH_USER") or None
    if os.getenv("HPC_REMOTE_BASE_DIR"):
        config.cluster.remote_base_dir = os.environ["HPC_REMOTE_BASE_DIR"]
    if os.getenv("HPC_SLURM_PARTITION"):
        config.slurm.default_partition = os.environ["HPC_SLURM_PARTITION"]
    if os.getenv("HPC_SLURM_GPU_PARTITION"):
        config.slurm.gpu_partition = os.environ["HPC_SLURM_GPU_PARTITION"]
    if os.getenv("HPC_GPU_FLAG_STYLE"):
        config.slurm.gpu_flag_style = os.environ["HPC_GPU_FLAG_STYLE"]

    config.execution.artifact_root = str((contract_record_root / "artifacts").resolve())
    config.execution.use_rsync = True
    return config


@pytest.fixture(scope="session")
def runners(runner_config: RunnerConfig) -> tuple[SSHRunner, SlurmRunner]:
    store = ArtifactStore(runner_config.artifact_root)
    command_runner = CommandRunner()
    staging = StagingManager(runner_config, store, command_runner)
    mapper = FailureMapper()
    return (
        SSHRunner(runner_config, store, staging, command_runner, mapper),
        SlurmRunner(runner_config, store, staging, command_runner, mapper),
    )


def _contracts() -> list[ToolContract]:
    return load_contract_manifest()


@pytest.mark.parametrize("contract", _contracts(), ids=lambda contract: contract.tool_id)
def test_hpc_tool_contract_smoke_records_final_status(
    contract: ToolContract,
    runners: tuple[SSHRunner, SlurmRunner],
    runner_config: RunnerConfig,
    contract_record_root: Path,
) -> None:
    ssh, slurm = runners
    record = base_contract_record(contract)

    discovery_spec = build_discovery_runspec(contract)
    record["discovery"] = _run_discovery(ssh, discovery_spec)

    if contract.support_status == "smoke_runnable":
        smoke_spec = build_smoke_runspec(
            contract,
            _project_root() / "fixtures" / "hpc_tool_samples",
            partition=_adapter_partition(contract, runner_config),
        )
        record["smoke"] = _run_smoke(slurm, smoke_spec)
        record["final_status"] = _final_status(record["discovery"], record["smoke"])
    else:
        record["final_status"] = _blocked_or_entrypoint_status(contract, record)
        record["diagnostics"].append(
            f"support_status={contract.support_status}; smoke submission skipped"
        )

    output_path = write_contract_record(contract_record_root, contract.tool_id, record)
    persisted = output_path.read_text(encoding="utf-8")
    assert '"final_status"' in persisted
    assert sanitize_record(record)["final_status"] != "not_run"


def _adapter_partition(contract: ToolContract, config: RunnerConfig) -> str | None:
    adapter = config.adapters.get(contract.adapter_id)
    if adapter and adapter.partition:
        return adapter.partition
    return None


def _run_discovery(ssh: SSHRunner, spec: RunSpec) -> dict[str, Any]:
    try:
        result = ssh.exec_run(spec)
    except PreflightError as exc:
        return {
            "status": "blocked_preflight",
            "runspec": spec.to_dict(),
            "preflight": exc.manifest,
        }
    except Exception as exc:  # noqa: BLE001 - live contract records diagnostics.
        return {
            "status": "blocked_exception",
            "runspec": spec.to_dict(),
            "error": repr(exc),
        }
    return {
        "status": "completed" if result.status == "completed" else "entrypoint_failed",
        "runspec": spec.to_dict(),
        "result": result_summary(result),
    }


def _run_smoke(slurm: SlurmRunner, spec: RunSpec) -> dict[str, Any]:
    try:
        submitted = slurm.submit(spec)
    except PreflightError as exc:
        return {
            "status": "blocked_preflight",
            "runspec": spec.to_dict(),
            "preflight": exc.manifest,
        }
    except Exception as exc:  # noqa: BLE001 - live contract records diagnostics.
        return {
            "status": "blocked_exception",
            "runspec": spec.to_dict(),
            "error": repr(exc),
        }

    smoke: dict[str, Any] = {
        "status": "submitted" if submitted.status == "submitted" else "submit_failed",
        "runspec": spec.to_dict(),
        "submit_result": result_summary(submitted),
    }
    if submitted.status != "submitted" or not submitted.job_id:
        return smoke

    handle = slurm.load_handle(submitted.run_id)
    timeout_seconds = int(os.getenv("HPC_CONTRACT_TIMEOUT_SECONDS", "900"))
    poll_seconds = int(os.getenv("HPC_CONTRACT_POLL_SECONDS", "10"))
    deadline = time.monotonic() + timeout_seconds
    status = None
    while time.monotonic() < deadline:
        status = slurm.status(handle)
        smoke["job_status"] = sanitize_record(status.to_dict())
        if status.state in {"completed", "failed", "cancelled"}:
            break
        time.sleep(poll_seconds)
    else:
        smoke["status"] = "blocked_timeout"
        smoke["logs"] = sanitize_record(slurm.logs(handle))
        return smoke

    smoke["logs"] = sanitize_record(slurm.logs(handle))
    if status is None or status.state != "completed":
        smoke["status"] = "run_failed"
        return smoke

    fetched: RunResult = slurm.fetch_artifacts(spec, handle)
    smoke["fetch_result"] = result_summary(fetched)
    smoke["status"] = "completed" if fetched.status == "completed" else "artifact_failed"
    return smoke


def _blocked_or_entrypoint_status(
    contract: ToolContract, record: dict[str, Any]
) -> str:
    discovery = record.get("discovery") or {}
    if discovery.get("status") == "completed":
        return "entrypoint_only"
    if contract.support_status == "blocked_missing_db_or_sample":
        return "blocked_missing_db_or_sample"
    if contract.support_status == "documented_only":
        return "documented_only"
    return "entrypoint_blocked"


def _final_status(discovery: dict[str, Any], smoke: dict[str, Any] | None) -> str:
    if smoke and smoke.get("status") == "completed":
        return "smoke_completed"
    if smoke and str(smoke.get("status", "")).startswith("blocked"):
        return str(smoke["status"])
    if smoke:
        return f"smoke_{smoke.get('status', 'failed')}"
    if discovery.get("status") == "completed":
        return "entrypoint_only"
    return str(discovery.get("status", "blocked"))
