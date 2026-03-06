from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _run(repo_root: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": ":".join(
            [
                str(repo_root / "apps" / "enzyme-host-cli" / "src"),
                str(repo_root / "apps" / "mcp-project-memory" / "src"),
                str(repo_root / "apps" / "mcp-hpc-tool-contracts" / "src"),
                str(repo_root / "apps" / "mcp-hpc-runner" / "src"),
            ]
        )
    }
    return subprocess.run(
        [sys.executable, "-m", "enzyme_host_cli.cli", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_flow_from_init_to_run_and_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = _run(repo_root, tmp_path, "init", "demo-project")
    assert result.returncode == 0, result.stderr

    project_root = tmp_path / "demo-project"
    (project_root / "data" / "inputs" / "target.pdb").write_text("ATOM\n", encoding="utf-8")
    plan_path = project_root / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "id": "pocket_1",
                        "tool": "fpocket",
                        "inputs": {"pdb": "data/inputs/target.pdb"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _run(repo_root, project_root, "new-episode", "improve binding")
    assert result.returncode == 0, result.stderr

    result = _run(repo_root, project_root, "plan", "import", str(plan_path))
    assert result.returncode == 0, result.stderr

    runner_shim = project_root / "mcp-hpc-runner"
    runner_shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "name = args[args.index('--name') + 1]\n"
        "payload = json.loads(args[args.index('--arguments') + 1])\n"
        "if name == 'job.submit':\n"
        "    print(json.dumps({'run_id': 'run-123', 'job_id': 'job-1', 'remote_run_dir': '/remote/run-123', 'status': 'submitted'}))\n"
        "elif name == 'job.status':\n"
        "    print(json.dumps({'run_id': 'run-123', 'job_id': 'job-1', 'state': 'completed'}))\n"
        "elif name == 'job.fetch_artifacts':\n"
        "    print(json.dumps({'run_id': 'run-123', 'status': 'completed', 'artifacts': {'/remote/out/report.txt': '/tmp/report.txt'}}))\n"
        "else:\n"
        "    raise SystemExit(f'unsupported tool: {name} {payload}')\n",
        encoding="utf-8",
    )
    runner_shim.chmod(0o755)

    env = {
        **os.environ,
        "PYTHONPATH": ":".join(
            [
                str(repo_root / "apps" / "enzyme-host-cli" / "src"),
                str(repo_root / "apps" / "mcp-project-memory" / "src"),
                str(repo_root / "apps" / "mcp-hpc-tool-contracts" / "src"),
                str(repo_root / "apps" / "mcp-hpc-runner" / "src"),
            ]
        ),
        "PATH": f"{project_root}:{os.environ.get('PATH', '')}",
    }
    result = subprocess.run(
        [sys.executable, "-m", "enzyme_host_cli.cli", "run"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "run-123" in result.stdout

    result = _run(repo_root, project_root, "status")
    assert result.returncode == 0, result.stderr
    assert "pocket_1: completed (run-123)" in result.stdout

    result = _run(repo_root, project_root, "report")
    assert result.returncode == 0, result.stderr
    assert (project_root / "episodes" / "0001" / "report.md").exists()

    result = _run(repo_root, project_root, "logs", "run-123")
    assert result.returncode == 0, result.stderr
    assert "job_status:" in result.stdout


def test_report_without_confirmed_plan_is_friendly(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = _run(repo_root, tmp_path, "init", "demo-project")
    assert result.returncode == 0, result.stderr

    project_root = tmp_path / "demo-project"

    result = _run(repo_root, project_root, "new-episode", "improve binding")
    assert result.returncode == 0, result.stderr

    result = _run(repo_root, project_root, "report")
    assert result.returncode == 0, result.stderr
    report = (project_root / "episodes" / "0001" / "report.md").read_text(encoding="utf-8")
    assert "No confirmed plan" in report


def test_logs_for_missing_run_is_friendly(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = _run(repo_root, tmp_path, "init", "demo-project")
    assert result.returncode == 0, result.stderr

    project_root = tmp_path / "demo-project"

    result = _run(repo_root, project_root, "logs", "missing-run")
    assert result.returncode == 1
    assert "Run missing-run not found." in result.stderr
