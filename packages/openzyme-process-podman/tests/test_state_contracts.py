from __future__ import annotations

import importlib.metadata

from openzyme_process_podman import SandboxImageCompatibility
from openzyme_process_podman import SandboxImageRecord
from openzyme_process_podman import SandboxRunRecord
from openzyme_process_podman import SandboxRunStatus
from openzyme_process_podman import SandboxWorkspaceStatus


def test_process_adapter_state_owner_has_no_runtime_implementation_dependency() -> None:
    requirements = importlib.metadata.requires("openzyme-process-podman") or []
    runtime_requirements = sorted(
        requirement for requirement in requirements if "extra ==" not in requirement
    )

    assert runtime_requirements == [
        "openzyme-contracts",
        "openzyme-extension-spi",
        "openzyme-runtime-spi",
    ]
    assert SandboxRunStatus.TIMEOUT.is_terminal is True
    assert SandboxWorkspaceStatus.READY.value == "ready"


def test_sandbox_state_records_preserve_existing_serialization_shape() -> None:
    image = SandboxImageRecord(
        image_ref="image:1",
        image_digest="sha256:" + "a" * 64,
        image_family="family",
        image_version="1",
        sandbox_protocol_version="1",
        manifest_schema_version="1",
        capabilities_declared=("process.exec",),
        compatibility=SandboxImageCompatibility.COMPATIBLE,
        is_default=True,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )
    run = SandboxRunRecord(
        sandbox_run_id="sandbox-run-1",
        session_id="session-1",
        sandbox_workspace_id="workspace-1",
        agent_id="agent-1",
        argv=("python", "script.py"),
        argv_digest="sha256:" + "b" * 64,
        cwd="work",
        env_digest="sha256:" + "c" * 64,
        status=SandboxRunStatus.RUNNING,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )

    assert image.to_dict()["capabilities_declared"] == ["process.exec"]
    assert image.to_dict()["compatibility"] == "compatible"
    assert run.to_dict()["argv"] == ["python", "script.py"]
    assert run.to_dict()["status"] == "running"
