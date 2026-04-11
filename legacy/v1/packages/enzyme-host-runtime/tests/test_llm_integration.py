from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from enzyme_host_runtime.execution import ExecutionResult
from enzyme_host_runtime.execution import RoutedExecutionAdapter
from enzyme_host_runtime.execution import StepExecutor
from enzyme_host_runtime.services import HostRuntime
from enzyme_host_runtime.workspace import init_project


class _FakePreprocessExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool == "prepare_receptor"

    def run_step(self, project_root: Path, episode_id: str, step) -> ExecutionResult:
        del project_root, episode_id
        return ExecutionResult(
            run_id="llm-local-run",
            status="completed",
            manifest_payload={
                "backend": "local-preprocess",
                "tool": step.tool,
                "step_id": step.step_id,
                "status": "completed",
                "result": {"status": "completed", "output": {"output_path": "data/inputs/receptor.pdbqt"}},
            },
        )


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None
    or not (Path(__file__).resolve().parents[3] / "apps" / "pi-ai-sidecar" / "node_modules" / "@mariozechner" / "pi-ai").exists(),
    reason="Node sidecar dependencies are not installed.",
)


def test_runtime_can_use_llm_sidecar_backend_successfully(tmp_path: Path) -> None:
    context = init_project(tmp_path, "demo-project")
    runtime = HostRuntime(executor=RoutedExecutionAdapter([_FakePreprocessExecutor()]))
    snapshot = runtime.create_episode(context.root, "Improve binding")
    _write_backend_config(
        context.root,
        provider="fake",
        model="fake-structured-agent",
        allow_fallback=True,
        fake_mode="success",
    )
    (context.root / "data" / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")

    started = runtime.start_agent_workflow(context.root, episode_id=snapshot.episode_id)

    assert started.agent_backend["backend"] == "llm-sidecar"
    assert started.agent_backend["fallback_used"] is False
    assert started.agent_state["selected_action"] is not None

    executed = runtime.execute_selected_action(context.root, episode_id=snapshot.episode_id)

    assert executed.runs[-1]["run_id"] == "llm-local-run"
    assert executed.agent_backend["backend"] == "llm-sidecar"


def test_invalid_llm_output_blocks_workflow_without_tool_execution(tmp_path: Path) -> None:
    context = init_project(tmp_path, "demo-project")
    runtime = HostRuntime(executor=RoutedExecutionAdapter([_FakePreprocessExecutor()]))
    snapshot = runtime.create_episode(context.root, "Improve binding")
    _write_backend_config(
        context.root,
        provider="fake",
        model="fake-structured-agent",
        allow_fallback=False,
        fake_mode="invalid-structure",
    )

    started = runtime.start_agent_workflow(context.root, episode_id=snapshot.episode_id)

    assert started.agent_state["status"] == "blocked"
    assert started.agent_state["selected_action"] is None
    assert started.agent_backend["last_error_summary"]

    with pytest.raises(ValueError):
        runtime.execute_selected_action(context.root, episode_id=snapshot.episode_id)

    refreshed = runtime.get_status(context.root, episode_id=snapshot.episode_id)
    assert refreshed.runs == []


def _write_backend_config(
    project_root: Path,
    *,
    provider: str,
    model: str,
    allow_fallback: bool,
    fake_mode: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config_path = project_root / ".enzyme" / "agent_backend.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "backend": "llm-sidecar",
                "llm_sidecar": {
                    "provider": provider,
                    "model": model,
                    "timeout_seconds": 2,
                    "allow_fallback": allow_fallback,
                    "cwd": str((repo_root / "apps" / "pi-ai-sidecar").resolve()),
                    "command": [
                        "node",
                        str((repo_root / "apps" / "pi-ai-sidecar" / "src" / "index.mjs").resolve()),
                        "--config",
                        str(config_path.resolve()),
                    ],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["fakeMode"] = fake_mode
    payload["llm_sidecar"]["fakeMode"] = fake_mode
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
