from __future__ import annotations

from pathlib import Path

from mcp_hpc_runner.models import ExpectedOutput, ResourceSpec, RunSpec, StagedInput
from mcp_hpc_runner.validation import validate_expected_outputs, validate_runspec


def test_runspec_validation_success(tmp_path: Path) -> None:
    infile = tmp_path / "input.txt"
    infile.write_text("hello", encoding="utf-8")

    spec = RunSpec(
        name="smoke",
        stage="evidence",
        command=["python3", "--version"],
        execution_mode="ssh",
        resources=ResourceSpec(cpus=1, mem_mb=256, gpus=0, time_minutes=5),
        inputs=[StagedInput(local_path=str(infile), remote_path="in/input.txt")],
    )
    assert validate_runspec(spec) == []


def test_runspec_validation_missing_input(tmp_path: Path) -> None:
    spec = RunSpec(
        name="bad",
        stage="evidence",
        command=["python3", "--version"],
        inputs=[StagedInput(local_path=str(tmp_path / "missing.txt"), remote_path="x")],
    )
    errors = validate_runspec(spec)
    assert any("required input is missing" in error for error in errors)


def test_validate_expected_outputs_non_empty(tmp_path: Path) -> None:
    out_root = tmp_path / "outputs"
    out_root.mkdir(parents=True)
    (out_root / "result.txt").write_text("", encoding="utf-8")

    missing, empty = validate_expected_outputs(
        out_root,
        [ExpectedOutput(path="result.txt", kind="file", required=True, non_empty=True)],
    )
    assert missing == []
    assert empty == ["result.txt"]
