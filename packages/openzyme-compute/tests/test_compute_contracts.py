from __future__ import annotations

import importlib.metadata

from openzyme_compute import RunRecord
from openzyme_compute import RunStatus


def test_compute_contract_owner_has_only_declared_contract_dependencies() -> None:
    requirements = importlib.metadata.requires("openzyme-compute") or []
    runtime_requirements = sorted(
        requirement for requirement in requirements if "extra ==" not in requirement
    )

    assert runtime_requirements == [
        "openzyme-contracts",
        "openzyme-execution-contracts",
        "openzyme-extension-spi",
    ]
    assert RunStatus.SUCCEEDED.is_terminal is True


def test_run_record_preserves_existing_serialization_shape() -> None:
    record = RunRecord(
        run_id="run-1",
        session_id="session-1",
        task_id="task-1",
        lane_id=None,
        invocation_id="invocation-1",
        approval_id=None,
        engine_name="engine",
        runner_run_id="runner-1",
        status=RunStatus.RUNNING,
        execution_mode="remote",
        remote_run_dir="opaque-run-dir",
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )

    assert record.to_dict()["status"] == "running"
    assert record.to_dict()["runner_run_id"] == "runner-1"
