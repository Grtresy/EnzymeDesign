from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mcp_hpc_runner.remote import CommandRunner, make_remote_shell_command_with_env


def test_command_runner_records_timeout_and_elapsed() -> None:
    result = CommandRunner().run(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        check=False,
        timeout=0.01,
        stage="staging",
    )

    assert result.returncode == 124
    assert result.timed_out is True
    assert result.elapsed_seconds > 0
    assert result.stage == "staging"


def test_remote_shell_normalizes_relative_layout_paths(tmp_path: Path) -> None:
    work_dir = tmp_path / "mcp_runs" / "run123" / "work"
    out_dir = tmp_path / "mcp_runs" / "run123" / "out"
    work_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)

    command = make_remote_shell_command_with_env(
        "mcp_runs/run123/work",
        [
            "python3",
            "-c",
            (
                "import json, os; "
                "print(json.dumps({"
                "'cwd': os.getcwd(), "
                "'work': os.environ['MCP_WORKDIR'], "
                "'out': os.environ['MCP_OUTDIR']"
                "}))"
            ),
        ],
        {
            "MCP_WORKDIR": "mcp_runs/run123/work",
            "MCP_OUTDIR": "mcp_runs/run123/out",
        },
    )

    result = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        check=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload == {
        "cwd": str(work_dir),
        "work": str(work_dir),
        "out": str(out_dir),
    }


def test_remote_shell_normalizes_home_relative_layout_paths(tmp_path: Path) -> None:
    command = make_remote_shell_command_with_env(
        "~/mcp_runs/run123/work",
        ["printf", "%s", "$MCP_OUTDIR"],
        {"MCP_OUTDIR": "~/mcp_runs/run123/out"},
    )

    script = command[-1]
    assert 'case "$1" in' in script
    assert '~/*) printf' in script
    assert "cd $(_oz_abspath '~/mcp_runs/run123/work')" in script
    assert 'MCP_OUTDIR="$(_oz_abspath "${MCP_OUTDIR}")"' in script
