from __future__ import annotations

import json
import subprocess
from pathlib import Path

from mcp_hpc_runner.remote import make_remote_shell_command_with_env


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
