from __future__ import annotations

from pathlib import Path

import pytest

from mcp_hpc_runner.config import ResourceLimitsConfig
from mcp_hpc_runner.models import (
    ExpectedOutput,
    ResourceSpec,
    RunSpec,
    StagedInput,
    SuccessCheck,
)
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


def test_runspec_round_trip_preserves_staged_input_artifact_id(tmp_path: Path) -> None:
    infile = tmp_path / "input.txt"
    infile.write_text("hello", encoding="utf-8")

    spec = RunSpec(
        name="roundtrip",
        stage="execution",
        command=["cat", "input.txt"],
        inputs=[StagedInput(local_path=str(infile), remote_path="input.txt", artifact_id="art_input")],
    )
    restored = RunSpec.from_dict(spec.to_dict())

    assert restored.inputs[0].artifact_id == "art_input"
    assert restored.to_dict()["inputs"][0]["artifact_id"] == "art_input"


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


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../escape",
        "nested/../../escape",
        "./result.txt",
        "nested//result.txt",
        "nested\\result.txt",
        "nested/result;touch-pwned.txt",
        "nested/result $(touch-pwned).txt",
        "nested/result`touch-pwned`.txt",
        "nested/result:alternate.txt",
        "nested/line\nbreak.txt",
        "nested/nul\0byte.txt",
    ],
)
def test_runspec_validation_rejects_unsafe_workspace_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    infile = tmp_path / "input.txt"
    infile.write_text("hello", encoding="utf-8")

    input_spec = RunSpec(
        name="safe-name",
        stage="execution",
        command=["true"],
        inputs=[StagedInput(local_path=str(infile), remote_path=unsafe_path)],
    )
    output_spec = RunSpec(
        name="safe-name",
        stage="execution",
        command=["true"],
        expected_outputs=[ExpectedOutput(path=unsafe_path)],
    )
    check_spec = RunSpec(
        name="safe-name",
        stage="execution",
        command=["true"],
        success_checks=[SuccessCheck(check_type="exists", path=unsafe_path)],
    )

    assert any("inputs.remote_path" in error for error in validate_runspec(input_spec))
    assert any("expected_outputs.path" in error for error in validate_runspec(output_spec))
    assert any("success_checks.path" in error for error in validate_runspec(check_spec))


def test_runspec_validation_rejects_unsafe_stage_run_and_slurm_fields(
    tmp_path: Path,
) -> None:
    infile = tmp_path / "input.txt"
    infile.write_text("hello", encoding="utf-8")
    spec = RunSpec(
        name="safe\n#SBATCH --exclusive",
        stage="execution",
        command=["true"],
        resources=ResourceSpec(partition="cpu\n#SBATCH --exclusive"),
        inputs=[
            StagedInput(
                local_path=str(infile),
                remote_path="input.txt",
                stage_to="../../other",
            )
        ],
        run_id="../../escape",
    )

    errors = validate_runspec(spec)

    assert any("RunSpec.name" in error for error in errors)
    assert any("resources.partition" in error for error in errors)
    assert any("inputs.stage_to" in error for error in errors)
    assert any("RunSpec.run_id" in error for error in errors)


@pytest.mark.parametrize(
    ("resources", "expected_field"),
    [
        (ResourceSpec(cpus=65), "resources.cpus"),
        (ResourceSpec(mem_mb=524_289), "resources.mem_mb"),
        (ResourceSpec(gpus=9), "resources.gpus"),
        (ResourceSpec(time_minutes=10_081), "resources.time_minutes"),
    ],
)
def test_runspec_validation_rejects_resources_over_operator_limits(
    resources: ResourceSpec,
    expected_field: str,
) -> None:
    spec = RunSpec(
        name="bounded",
        stage="execution",
        command=["true"],
        resources=resources,
    )

    errors = validate_runspec(spec, limits=ResourceLimitsConfig())

    assert any(expected_field in error and "must be <=" in error for error in errors)


def test_runspec_validation_enforces_configured_partition_allowlist() -> None:
    spec = RunSpec(
        name="bounded",
        stage="execution",
        command=["true"],
        resources=ResourceSpec(partition="unapproved"),
    )

    errors = validate_runspec(spec, allowed_partitions=("cpu", "gpu"))

    assert any("resources.partition" in error and "allowed" in error for error in errors)


def test_runspec_validation_rejects_partition_override_without_allowlist() -> None:
    spec = RunSpec(
        name="bounded",
        stage="execution",
        command=["true"],
        resources=ResourceSpec(partition="cpu"),
    )

    errors = validate_runspec(spec, allowed_partitions=())

    assert any("resources.partition" in error and "allowed" in error for error in errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_cpus", 0),
        ("max_mem_mb", -1),
        ("max_gpus", -1),
        ("max_time_minutes", 0),
        ("max_tail_lines", 0),
    ],
)
def test_resource_limits_must_be_positive(field: str, value: int) -> None:
    values = {
        "max_cpus": 64,
        "max_mem_mb": 524_288,
        "max_gpus": 8,
        "max_time_minutes": 10_080,
        "max_tail_lines": 5_000,
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        ResourceLimitsConfig(**values)
