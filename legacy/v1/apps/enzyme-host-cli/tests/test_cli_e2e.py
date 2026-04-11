from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _run(repo_root: Path, cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": ":".join(
            [
                str(repo_root / "apps" / "enzyme-host-cli" / "src"),
                str(repo_root / "packages" / "enzyme-host-runtime" / "src"),
                str(repo_root / "packages" / "preprocess-backend" / "src"),
                str(repo_root / "apps" / "mcp-project-memory" / "src"),
                str(repo_root / "apps" / "mcp-hpc-tool-contracts" / "src"),
                str(repo_root / "apps" / "mcp-hpc-runner" / "src"),
            ]
        ),
        **(extra_env or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "enzyme_host_cli.cli", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_workflow_start_execute_status_and_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = _run(repo_root, tmp_path, "init", "demo-project")
    assert result.returncode == 0, result.stderr

    project_root = tmp_path / "demo-project"
    result = _run(repo_root, project_root, "new-episode", "improve binding")
    assert result.returncode == 0, result.stderr
    (project_root / "data" / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")

    result = _run(repo_root, project_root, "workflow", "start", extra_env={"ENZYME_HOST_CLI_FAKE_EXECUTOR": "prepare_receptor_success"})
    assert result.returncode == 0, result.stderr
    assert "Workflow Status:" in result.stdout
    assert "Next Step:" in result.stdout
    assert "Agent Backend:" in result.stdout

    result = _run(repo_root, project_root, "workflow", "execute", extra_env={"ENZYME_HOST_CLI_FAKE_EXECUTOR": "prepare_receptor_success"})
    assert result.returncode == 0, result.stderr
    assert "Runs: 1" in result.stdout

    result = _run(repo_root, project_root, "status")
    assert result.returncode == 0, result.stderr
    assert "Workflow Status:" in result.stdout
    assert "Summary:" in result.stdout
    assert "Agent Backend:" in result.stdout

    result = _run(repo_root, project_root, "report")
    assert result.returncode == 0, result.stderr
    assert (project_root / "episodes" / "0001" / "report.md").exists()


def test_cli_can_list_interrupts_and_submit_feedback(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = _run(repo_root, tmp_path, "init", "demo-project")
    assert result.returncode == 0, result.stderr
    project_root = tmp_path / "demo-project"

    result = _run(repo_root, project_root, "new-episode", "improve binding")
    assert result.returncode == 0, result.stderr

    shim_dir = project_root / "enzyme_host_runtime"
    shim_dir.mkdir(exist_ok=True)

    result = _run(repo_root, project_root, "workflow", "start")
    assert result.returncode == 0, result.stderr

    # Trigger a clarification interrupt by removing the expected input file and executing.
    result = _run(repo_root, project_root, "workflow", "execute")
    assert result.returncode == 1

    result = _run(repo_root, project_root, "workflow", "interrupts")
    assert result.returncode == 0, result.stderr
    assert "clarification_request" in result.stdout
    assert "Summary:" in result.stdout
    assert "Next:" in result.stdout
    interrupt_id = result.stdout.strip().split(":")[0]

    verbose = _run(repo_root, project_root, "--verbose", "status")
    assert verbose.returncode == 0, verbose.stderr
    assert "Technical Explanation:" in verbose.stdout

    result = _run(repo_root, project_root, "workflow", "feedback", interrupt_id, "retry the step")
    assert result.returncode == 0, result.stderr
    assert "Pending Interrupts: 0" in result.stdout


def test_cli_rejects_stale_resume_token(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    assert _run(repo_root, tmp_path, "init", "demo-project").returncode == 0
    project_root = tmp_path / "demo-project"
    assert _run(repo_root, project_root, "new-episode", "improve binding").returncode == 0

    result = _run(repo_root, project_root, "workflow", "start")
    assert result.returncode == 0, result.stderr

    result = _run(repo_root, project_root, "workflow", "execute")
    assert result.returncode == 1

    agent_state = json.loads((project_root / "episodes" / "0001" / "agent_state.json").read_text(encoding="utf-8"))
    interrupt = agent_state["pending_interrupts"][-1]
    interrupt_id = interrupt["interrupt_id"]
    state_version = str(interrupt["active_state_version"])
    resume_token = interrupt["resume_token"]

    result = _run(
        repo_root,
        project_root,
        "workflow",
        "feedback",
        interrupt_id,
        "retry the step",
        "--state-version",
        state_version,
        "--resume-token",
        resume_token,
    )
    assert result.returncode == 0, result.stderr

    stale = _run(
        repo_root,
        project_root,
        "workflow",
        "feedback",
        interrupt_id,
        "retry again",
        "--state-version",
        state_version,
        "--resume-token",
        resume_token,
    )
    assert stale.returncode == 1
    assert "Stale workflow state" in stale.stderr


def test_logs_for_missing_run_is_friendly(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = _run(repo_root, tmp_path, "init", "demo-project")
    assert result.returncode == 0, result.stderr

    project_root = tmp_path / "demo-project"
    result = _run(repo_root, project_root, "logs", "missing-run")
    assert result.returncode == 1
    assert "Run missing-run not found." in result.stderr
