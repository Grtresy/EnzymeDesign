from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_engines.podman_sandbox import _ControlSocketServer


def test_podman_runner_can_bind_existing_sandbox_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        del kwargs
        calls.append(list(command))
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(
                returncode=0,
                stdout="sha256:" + "a" * 64 + "\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("openzyme_engines.podman_sandbox.subprocess.run", fake_run)
    monkeypatch.setattr("openzyme_engines.podman_sandbox.shutil.which", lambda binary: f"/usr/bin/{binary}")
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
    podman_run = next(command for command in calls if command[1] == "run")
    assert any(
        item == f"{workspace_root / workspace_id}:/workspace:Z"
        for item in podman_run
    )
    assert podman_run[-1] == "sha256:" + "a" * 64
    runtime_identity = outcome.raw_result["sandbox_runtime_identity"]
    assert runtime_identity["image_digest"] == "sha256:" + "a" * 64
    assert runtime_identity["pipeline_sdk_digest"].startswith("sha256:")


def test_control_socket_materialize_copies_input_to_requested_workspace_target(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "art_input.txt"
    source.write_text("authorized input\n", encoding="utf-8")
    server = _ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        input_dir=input_dir,
        output_dir=output_dir,
        artifacts={
            "art_input": {
                "artifact_id": "art_input",
                "path": "/openzyme/input/art_input.txt",
                "content_digest": "sha256:test",
            }
        },
    )

    result = server._materialize(
        {
            "artifact_id": "art_input",
            "target": "/workspace/input/nested/protein.txt",
            "mode": "copy",
        }
    )

    assert result["path"] == "/workspace/input/nested/protein.txt"
    assert (input_dir / "nested" / "protein.txt").read_text(encoding="utf-8") == "authorized input\n"
    with pytest.raises(ValueError, match="under /workspace/input"):
        server._materialize(
            {
                "artifact_id": "art_input",
                "target": "/workspace/output/protein.txt",
            }
        )
