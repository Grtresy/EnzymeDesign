from __future__ import annotations

import json
from pathlib import Path

from mcp_hpc_runner.sif import (
    BindPolicy,
    build_apptainer_command,
    map_input_path,
    map_output_path,
)


def test_bind_policy_command_construction(tmp_path: Path) -> None:
    policy = BindPolicy(
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        db_dir=tmp_path / "db",
        model_dir=tmp_path / "models",
        tmp_dir=tmp_path / "tmp",
    )
    cmd = build_apptainer_command(
        "~/containers/fpocket.sif",
        "fpocket",
        ["-f", "/work/target.pdb"],
        policy,
    )

    joined = " ".join(cmd)
    assert "--bind" in cmd
    assert ":/work" in joined
    assert ":/out" in joined
    assert ":/db" in joined
    assert ":/models" in joined
    assert ":/tmp" in joined


def test_bind_policy_path_mapping() -> None:
    assert map_input_path("foo/bar.txt") == "/work/foo/bar.txt"
    assert map_input_path("db.fa", source="db") == "/db/db.fa"
    assert map_output_path("result/out.txt") == "/out/result/out.txt"


def test_runspec_fixture_contains_bind_policy_and_failure_signatures() -> None:
    project_root = Path(__file__).resolve().parents[1]
    fixture_path = project_root / "fixtures" / "runspec_sif_fpocket.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    command = " ".join(payload["command"])
    assert "/work" in command
    assert "/out" in command
    assert payload["expected_outputs"]
    assert payload["failure_signatures"]
