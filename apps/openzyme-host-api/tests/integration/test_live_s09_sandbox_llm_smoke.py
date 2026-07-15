from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import HarnessInput
from openzyme_core import RestoreFocus
from openzyme_core import TeammateConversationDriver
from openzyme_core import apply_sqlite_migrations
from openzyme_core import build_teammate_registry
from openzyme_core import connect_sqlite
from openzyme_core import derive_sandbox_workspace_id
from openzyme_core import run_agent_harness_loop
from openzyme_core import sandbox_image_record
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_model_factory_from_settings
from openzyme_runtime import get_settings
from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import derive_live_graph_timeout_seconds
from openzyme_runtime.live_testing import log_live_phase


pytestmark = [pytest.mark.integration, pytest.mark.live_llm]

DEFAULT_SANDBOX_IMAGE_REF = "localhost/openzyme-pipeline-sandbox:dev"


class LiveS09SandboxLlmSmokeTimeoutError(TimeoutError):
    """Raised when the live S09 sandbox LLM smoke exceeds its timeout budget."""


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _require_local_sandbox_runtime() -> None:
    if shutil.which("podman") is None:
        pytest.skip("S09 sandbox live smoke requires podman.")
    rootless = subprocess.run(
        ["podman", "info", "--format", "{{.Host.Security.Rootless}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if rootless.returncode != 0 or rootless.stdout.strip() != "true":
        pytest.skip("S09 sandbox live smoke requires rootless podman.")
    image = subprocess.run(
        ["podman", "image", "exists", DEFAULT_SANDBOX_IMAGE_REF],
        check=False,
        capture_output=True,
        text=True,
    )
    if image.returncode != 0:
        pytest.skip(
            "S09 sandbox live smoke requires the default sandbox image "
            f"{DEFAULT_SANDBOX_IMAGE_REF!r}."
        )


def _seed_executor_session(repositories: CoreRepositories) -> tuple[str, str, str]:
    session_id = "sess_live_s09_sandbox_llm"
    task_id = "task_live_s09_sandbox"
    agent_id = "agent:executor"
    member_id = "member_live_s09_executor"
    repositories.sessions.save(
        Session(
            session_id=session_id,
            project_id="proj_live_s09",
            title="Live S09 sandbox LLM smoke",
            objective="Verify a real executor LLM can write and run sandbox code.",
            status=SessionStatus.ACTIVE,
            created_at="2026-05-28T00:00:00+00:00",
            updated_at="2026-05-28T00:00:00+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id=task_id,
            session_id=session_id,
            subject="Write and execute a S09 sandbox smoke script",
            description=(
                "Use sandbox.file.write to create a Python script under "
                "/workspace/src, then run it with sandbox.exec."
            ),
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="execution",
            assigned_ref=agent_id,
            created_at="2026-05-28T00:01:00+00:00",
            updated_at="2026-05-28T00:01:00+00:00",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id=agent_id,
            session_id=session_id,
            lane_id=None,
            task_id=task_id,
            name="executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-28T00:02:00+00:00",
            updated_at="2026-05-28T00:02:00+00:00",
            member_id=member_id,
        )
    )
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref=DEFAULT_SANDBOX_IMAGE_REF,
            image_digest="sha256:live-s09-smoke",
        )
    )
    return session_id, task_id, agent_id


def _tool_payload(result: Any) -> dict[str, Any]:
    content = result.content
    if isinstance(content, str):
        return dict(json.loads(content))
    return dict(content)


def test_live_executor_llm_writes_and_executes_sandbox_code() -> None:
    _require_local_sandbox_runtime()
    settings = apply_live_llm_test_budget(get_settings())
    tuned_settings = replace(
        settings,
        llm=replace(
            settings.llm,
            max_tokens=max(settings.llm.max_tokens or 0, 900),
            max_retries=max(settings.llm.max_retries or 0, 1),
        ),
    )
    timeout_seconds = derive_live_graph_timeout_seconds(
        llm_timeout_seconds=tuned_settings.llm.timeout,
        structured_attempts=tuned_settings.llm.max_retries + 1,
        tavily_timeout_seconds=None,
        expected_llm_call_budget=8,
        expected_tavily_budget=0,
        buffer_seconds=120,
        minimum_seconds=180,
    )
    repositories = _build_repositories()
    session_id, task_id, agent_id = _seed_executor_session(repositories)
    workspace_id = derive_sandbox_workspace_id(session_id, "member_live_s09_executor")
    model_factory = build_model_factory_from_settings(tuned_settings)
    assert model_factory is not None
    driver = TeammateConversationDriver(
        model_factory=model_factory,
        role="executor",
        agent_id=agent_id,
        correlation_id="corr_live_s09_sandbox",
        task_id=task_id,
        instructions=(
            "This is a minimal live S09 sandbox smoke. Do not ask questions. "
            "Use tools to inspect the sandbox workspace, write exactly one Python "
            "file at /workspace/src/live_s09_smoke.py with code that prints "
            "S09_LIVE_SMOKE_OK, then run it with sandbox.exec using "
            "argv [\"python\", \"src/live_s09_smoke.py\"]. Do not call web, "
            "provider, research, HPC, execution.pipeline, or report tools. "
            "After sandbox.exec succeeds, reply with one short confirmation."
        ),
    )

    try:
        with LiveStageTimeout(
            "running live executor LLM S09 sandbox file/exec smoke",
            timeout_seconds,
            timeout_type=LiveS09SandboxLlmSmokeTimeoutError,
        ):
            log_live_phase("starting live S09 executor sandbox smoke")
            result = run_agent_harness_loop(
                repositories,
                HarnessInput(
                    session_id=session_id,
                    max_steps=10,
                    sender=agent_id,
                    sender_kind=InboxParticipantKind.AGENT,
                    restore_focus=RestoreFocus(task_id=task_id),
                    persist_conversation=False,
                ),
                driver=driver,
                tool_registry=build_teammate_registry(agent_id=agent_id),
                model_factory=model_factory,
            )
    finally:
        shutil.rmtree(
            Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces" / workspace_id,
            ignore_errors=True,
        )

    tool_names = [tool_result.tool_name for tool_result in result.tool_results]
    assert "sandbox.file.write" in tool_names, {
        "status": result.status.value,
        "tool_names": tool_names,
        "outputs": result.outputs,
    }
    exec_results = [
        tool_result
        for tool_result in result.tool_results
        if tool_result.tool_name == "sandbox.exec"
    ]
    assert exec_results, {
        "status": result.status.value,
        "tool_names": tool_names,
        "outputs": result.outputs,
    }
    assert any(
        tool_result.ok
        and _tool_payload(tool_result).get("status") == "completed"
        and "S09_LIVE_SMOKE_OK" in str(_tool_payload(tool_result).get("stdout_summary"))
        for tool_result in exec_results
    ), {
        "status": result.status.value,
        "exec_results": [_tool_payload(tool_result) for tool_result in exec_results],
        "outputs": result.outputs,
    }
