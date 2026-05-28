from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openzyme_engines import PodmanPipelineSandboxRunner


def test_podman_runner_can_bind_existing_sandbox_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        del kwargs
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("openzyme_engines.podman_sandbox.subprocess.run", fake_run)
    monkeypatch.setattr("openzyme_engines.podman_sandbox._ControlSocketServer.start", lambda self: None)
    monkeypatch.setattr("openzyme_engines.podman_sandbox._ControlSocketServer.stop", lambda self: None)
    workspace_id = "sw_existing_workspace"
    workspace_root = tmp_path / "workspaces"
    sentinel = workspace_root / workspace_id / "work" / "keep.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep", encoding="utf-8")
    runner = PodmanPipelineSandboxRunner(
        workspace_root=workspace_root,
        timeout_seconds=30,
    )

    outcome = runner.run_pipeline(
        session_id="sess_001",
        invocation_id="inv_001",
        code="print('ok')\n",
        sandbox_workspace_id=workspace_id,
    )

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert outcome.remote_run_dir == f"podman://{workspace_id}"
    assert any(
        item == f"{workspace_root / workspace_id}:/workspace:Z"
        for item in calls[0]
    )
