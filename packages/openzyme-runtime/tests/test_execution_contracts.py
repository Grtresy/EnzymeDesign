import pytest

from openzyme_runtime import ExecutionRunSpecDraft


def test_execution_runspec_defaults_remain_backward_compatible() -> None:
    draft = ExecutionRunSpecDraft(
        name="legacy",
        stage="execution",
        command=["echo", "ok"],
    )

    payload = draft.model_dump()

    assert payload["inputs"] == []
    assert payload["expected_outputs"] == []
    assert payload["resources"]["cpus"] == 1


def test_execution_runspec_accepts_full_runner_shape() -> None:
    draft = ExecutionRunSpecDraft(
        name="vina",
        stage="execution",
        command=["bash", "-lc", "vina"],
        resources={"cpus": 8, "mem_mb": 8192},
        inputs=[{"artifact_id": "art_receptor", "local_path": "/tmp/receptor.pdbqt", "remote_path": "receptor.pdbqt"}],
        expected_outputs=[{"path": "vina.log", "kind": "file", "non_empty": True}],
        success_checks=[{"check_type": "exists", "path": "vina.log"}],
        failure_signatures=[{"pattern": "Parse error", "error_code": "INPUT_PARSE_ERROR"}],
    )

    assert draft.inputs[0].remote_path == "receptor.pdbqt"
    assert draft.inputs[0].artifact_id == "art_receptor"
    assert draft.expected_outputs[0].path == "vina.log"


def test_execution_runspec_rejects_unsafe_runner_paths() -> None:
    with pytest.raises(ValueError, match="relative"):
        ExecutionRunSpecDraft(
            name="bad",
            stage="execution",
            command=["echo", "bad"],
            expected_outputs=[{"path": "/tmp/result.txt"}],
        )
