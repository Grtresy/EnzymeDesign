from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import ArtifactRecord
from openzyme_domain import EvidenceRecord
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_graph.design import build_phase_c_design_graph
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import create_app
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus


class FakeExecutionAdapter:
    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> ExecutionOutcome:
        return ExecutionOutcome(
            run_id="run_001",
            status=RunStatus.SUCCEEDED,
            execution_mode="ssh",
            remote_run_dir=f"/remote/{episode_id}/run_001",
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri="/tmp/stdout.log",
                    relative_path="stdout.log",
                    kind=ArtifactKind.LOG,
                ),
                ExecutionArtifactRef(
                    storage_uri="/tmp/result.json",
                    relative_path="result.json",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            raw_result={"status": "completed"},
        )


class FakeResearchAdapter:
    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult:
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the brief.",
            findings=(
                ResearchFinding(
                    summary=f"Finding for {unit.query}",
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Source for {unit.unit_id}",
                            locator=f"https://example.org/{unit.unit_id}",
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need structural follow-up",),
        )


class FakeHarnessInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> dict[str, object]:
        del system_prompt, messages, tools
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_task_create",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_llm_001",
                            "subject": "Capture design goals",
                            "description": "Extract the user goal into a tracked task.",
                            "kind": "general",
                            "priority": "high",
                        },
                    }
                ],
            }
        return {"content": "Created task task_llm_001 and captured the goal.", "tool_calls": []}


class FakeHarnessModelFactory:
    def __init__(self) -> None:
        self.invoker = FakeHarnessInvoker()

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeHarnessInvoker:
        assert purpose == "v3_harness_loop"
        return self.invoker


class FakeEchoHarnessInvoker:
    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> dict[str, object]:
        del system_prompt, messages, tools
        return {"content": "Planning started.", "tool_calls": []}


class FakeEchoHarnessModelFactory:
    def create_tool_calling_invoker(self, *, purpose: str) -> FakeEchoHarnessInvoker:
        assert purpose == "v3_harness_loop"
        return FakeEchoHarnessInvoker()


def _message_role(message: object) -> str | None:
    if isinstance(message, dict):
        return None if message.get("role") is None else str(message["role"])
    message_type = type(message).__name__
    if message_type == "HumanMessage":
        return "user"
    if message_type == "AIMessage":
        return "assistant"
    if message_type == "ToolMessage":
        return "tool"
    return None


def _message_content(message: object) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _tool_message_name(message: object) -> str | None:
    if isinstance(message, dict):
        return None if message.get("name") is None else str(message["name"])
    return None if getattr(message, "name", None) is None else str(getattr(message, "name"))


class FakeEngineHarnessInvoker:
    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> dict[str, object]:
        del tools
        focused_task = next(
            (
                line.removeprefix("Focused task: ").strip()
                for line in system_prompt.splitlines()
                if line.startswith("Focused task: ")
            ),
            "none",
        )
        latest_tool_name = None
        latest_tool_content = ""
        seen_tool_names: list[str] = []
        for message in messages:
            if _message_role(message) != "tool":
                continue
            tool_name = _tool_message_name(message)
            if tool_name is None:
                continue
            latest_tool_name = tool_name
            latest_tool_content = _message_content(message)
            seen_tool_names.append(tool_name)
        latest_user_message = next(
            (_message_content(message) for message in reversed(messages) if _message_role(message) == "user"),
            "",
        )

        if focused_task == "task_research_v3":
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_update_research_running",
                            "name": "task.update",
                            "args": {"task_id": focused_task, "status": "in_progress"},
                        },
                        {
                            "id": "call_research_start",
                            "name": "deep_research.start",
                            "args": {
                                "task_id": focused_task,
                                "brief": "Collect papers for the scaffold family.",
                            },
                        },
                    ],
                }
            if latest_tool_name == "deep_research.start":
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_update_research_completed",
                            "name": "task.update",
                            "args": {"task_id": focused_task, "status": "completed"},
                        }
                    ],
                }
            return {"content": "deep_research.start completed.", "tool_calls": []}

        if focused_task == "task_execution_v3":
            active_invocations = next(
                (
                    line.removeprefix("Active invocations: ").strip()
                    for line in system_prompt.splitlines()
                    if line.startswith("Active invocations: ")
                ),
                "none",
            )
            if latest_tool_name is None and active_invocations == "none":
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_update_execution_running",
                            "name": "task.update",
                            "args": {"task_id": focused_task, "status": "in_progress"},
                        },
                        {
                            "id": "call_execution_start",
                            "name": "execution.start",
                            "args": {
                                "task_id": focused_task,
                                "handoff": {
                                    "execution_goal": "Run fpocket against the candidate structure.",
                                    "catalog_tool_id": "fpocket",
                                    "require_approval": True,
                                },
                            },
                        },
                    ],
                }
            if latest_tool_name is None and active_invocations != "none":
                invocation_id = active_invocations.split(",")[0].strip()
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_resume",
                            "name": "execution.resume",
                            "args": {
                                "invocation_id": invocation_id,
                                "resolution": "Approval approved by user.",
                            },
                        }
                    ],
                }
            if latest_tool_name == "execution.start":
                return {"content": "execution.start is waiting for approval.", "tool_calls": []}
            if latest_tool_name == "execution.resume":
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_update_execution_completed",
                            "name": "task.update",
                            "args": {"task_id": focused_task, "status": "completed"},
                        }
                    ],
                }
            return {"content": "execution.resume completed.", "tool_calls": []}

        if focused_task == "task_report_v3":
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_update_report_running",
                            "name": "task.update",
                            "args": {"task_id": focused_task, "status": "in_progress"},
                        },
                        {
                            "id": "call_reporting_start",
                            "name": "reporting.start",
                            "args": {
                                "task_id": focused_task,
                                "report_brief": "Produce a concise report for the completed V3 workspace.",
                            },
                        },
                    ],
                }
            if latest_tool_name == "reporting.start":
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_update_report_completed",
                            "name": "task.update",
                            "args": {"task_id": focused_task, "status": "completed"},
                        }
                    ],
                }
            return {"content": "reporting.start completed.", "tool_calls": []}

        if "Please track extracting the design goals as a task." in latest_user_message:
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_create",
                            "name": "task.create",
                            "args": {
                                "task_id": "task_llm_001",
                                "subject": "Capture design goals",
                                "description": "Extract the user goal into a tracked task.",
                                "kind": "general",
                                "priority": "high",
                            },
                        }
                    ],
                }
            return {"content": "Created task task_llm_001 and captured the goal.", "tool_calls": []}

        raise AssertionError(f"Unhandled fake harness request for focused task {focused_task!r}")


class FakeEngineHarnessModelFactory:
    def create_tool_calling_invoker(self, *, purpose: str) -> FakeEngineHarnessInvoker:
        assert purpose == "v3_harness_loop"
        return FakeEngineHarnessInvoker()


def _resolve_next_approval(client: TestClient, episode_id: str, decision: str = "approved") -> dict[str, object]:
    pending = client.get(f"/episodes/{episode_id}/pending-actions")
    assert pending.status_code == 200
    pending_actions = pending.json()
    assert pending_actions
    response = client.post(
        "/commands/resolve_approval",
        json={
            "episode_id": episode_id,
            "approval_id": pending_actions[0]["approval_id"],
            "decision": decision,
        },
    )
    assert response.status_code == 200
    return response.json()


def _build_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    saver = InMemorySaver()

    @contextmanager
    def _shared_open(self: PostgresCheckpointerFactory):
        yield saver

    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _shared_open,
    )

    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    repositories.projects.save(Project.create("proj_001", "Thermostability project"))
    foundation = RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-b/memory")
        ),
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider()),
        research_adapter=FakeResearchAdapter(),
    )
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=foundation,
                    graph_builder=build_v2_supervisor_graph,
                )
            )
        ),
        foundation,
    )


def _build_v3_llm_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    client, foundation = _build_client(monkeypatch)
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(foundation, model_factory=FakeHarnessModelFactory()),
                    graph_builder=build_v2_supervisor_graph,
                )
            )
        ),
        foundation,
    )


def _build_v3_engine_llm_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    client, foundation = _build_client(monkeypatch)
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(foundation, model_factory=FakeEngineHarnessModelFactory()),
                    graph_builder=build_v2_supervisor_graph,
                )
            )
        ),
        foundation,
    )


def _build_v3_echo_llm_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    client, foundation = _build_client(monkeypatch)
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(foundation, model_factory=FakeEchoHarnessModelFactory()),
                    graph_builder=build_v2_supervisor_graph,
                )
            )
        ),
        foundation,
    )


def _build_design_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    saver = InMemorySaver()

    @contextmanager
    def _shared_open(self: PostgresCheckpointerFactory):
        yield saver

    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _shared_open,
    )

    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    repositories.projects.save(Project.create("proj_001", "Thermostability project"))
    repositories.episodes.save(
        Episode.create("ep_design", "proj_001", "Design a thermostable variant")
    )
    repositories.research_summaries.save(
        ResearchSummaryRecord(
            episode_id="ep_design",
            summary="Literature supports two promising scaffold directions.",
            created_at="2026-04-11T12:00:00+00:00",
            updated_at="2026-04-11T12:00:00+00:00",
        )
    )
    repositories.evidence_records.save(
        EvidenceRecord(
            evidence_id="ev_001",
            episode_id="ep_design",
            summary="Scaffold A is supported by thermostability evidence.",
            query="scaffold A evidence",
            created_at="2026-04-11T12:01:00+00:00",
        )
    )
    repositories.evidence_records.save(
        EvidenceRecord(
            evidence_id="ev_002",
            episode_id="ep_design",
            summary="Scaffold B has structure-backed homolog support.",
            query="scaffold B evidence",
            created_at="2026-04-11T12:02:00+00:00",
        )
    )
    repositories.artifact_records.save(
        ArtifactRecord(
            artifact_id="art_design_structure",
            episode_id="ep_design",
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/design_input_structure.pdb",
            created_at="2026-04-11T12:03:00+00:00",
            title="Design input structure",
            tags=("input", "structure"),
            availability={"local_readable": True, "execution_input": True},
            provenance={"source_type": "imported"},
        )
    )
    foundation = RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-c/design")
        ),
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider()),
    )
    runtime = GraphRuntimeFacade(foundation)
    with runtime.compile_graph(build_phase_c_design_graph) as graph:
        graph.invoke(
            {
                "episode_id": "ep_design",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            runtime.build_episode_graph_config("ep_design"),
        )
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=foundation,
                    graph_builder=build_phase_c_design_graph,
                )
            )
        ),
        foundation,
    )


def test_create_episode_projects_workspace_and_pending_actions(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    response = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Improve thermostability"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"]["workflow"]["current_phase"] == "execution"
    assert payload["workspace"]["workflow"]["pending_interrupt"]["type"] == "approval"
    assert payload["workspace"]["pending_actions"][0]["status"] == "pending"
    assert payload["workspace"]["workflow"]["summary"]["evidence_count"] == 2
    assert len(payload["workspace"]["research"]["turns"]) >= 1
    assert payload["workspace"]["workflow"]["summary"]["artifact_count"] >= 1
    assert {event["event_type"] for event in payload["events"]} >= {
        "workflow.phase_changed",
        "workflow.progress_updated",
        "workflow.interrupt_pending",
        "workflow.approval_pending",
        "workflow.evidence_updated",
        "workflow.research_turn_recorded",
        "workflow.design_workspace_updated",
    }

    episode_id = payload["episode_id"]
    workspace = client.get(f"/episodes/{episode_id}/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["workflow"]["pending_approval"]["approval_id"].startswith(f"{episode_id}-execution-approval-")


def test_v3_session_message_events_task_and_lane(monkeypatch) -> None:
    client, _ = _build_v3_echo_llm_client(monkeypatch)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_001",
            "project_id": "proj_001",
            "objective": "Plan an enzyme design run",
        },
    )

    assert created.status_code == 200
    workspace = created.json()["workspace"]
    assert workspace["session"]["session_id"] == "sess_v3_001"
    assert workspace["task_board"]["items"] == []

    lane = client.post(
        "/v3/lanes",
        json={
            "session_id": "sess_v3_001",
            "lane_id": "lane_v3_001",
            "name": "analysis",
            "cwd": "/tmp/openzyme-v3-analysis",
        },
    )
    assert lane.status_code == 200
    assert lane.json()["lane"]["status"] == "idle"

    task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_v3_001",
            "task_id": "task_v3_001",
            "subject": "Extract design goals",
            "description": "Read the paper and extract enzyme design objectives.",
            "lane_id": "lane_v3_001",
            "priority": "high",
        },
    )
    assert task.status_code == 200
    assert task.json()["task"]["lane_id"] == "lane_v3_001"

    message = client.post(
        "/v3/sessions/sess_v3_001/messages",
        json={"message": "Start by planning the literature extraction.", "task_id": "task_v3_001"},
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["outputs"] == ["Planning started."]
    assert {event["event_type"] for event in payload["events"]} >= {
        "conversation.user_message",
        "message.received",
        "message.sent",
        "conversation.assistant_message",
    }
    assert payload["workspace"]["inbox"]

    events = client.get("/v3/sessions/sess_v3_001/events?replay=1")
    assert events.status_code == 200
    assert "event: conversation.user_message" in events.text
    assert "event: conversation.assistant_message" in events.text

    updated = client.patch("/v3/tasks/task_v3_001", json={"status": "in_progress"})
    assert updated.status_code == 200
    assert updated.json()["task"]["status"] == "in_progress"


def test_v3_engine_backed_research_execution_reporting_loop(monkeypatch) -> None:
    client, _ = _build_v3_engine_llm_client(monkeypatch)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_engines",
            "project_id": "proj_001",
            "objective": "Evaluate a thermostability candidate",
        },
    )
    assert created.status_code == 200
    lane = client.post(
        "/v3/lanes",
        json={
            "session_id": "sess_v3_engines",
            "lane_id": "lane_v3_engines",
            "name": "engine lane",
            "cwd": "/tmp/openzyme-v3-engines",
        },
    )
    assert lane.status_code == 200

    research_task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_v3_engines",
            "task_id": "task_research_v3",
            "subject": "Collect evidence",
            "description": "Collect papers for the scaffold family.",
            "kind": "research",
            "lane_id": "lane_v3_engines",
        },
    )
    assert research_task.status_code == 200
    research = client.post(
        "/v3/sessions/sess_v3_engines/messages",
        json={"message": "Run the research task.", "task_id": "task_research_v3"},
    )
    assert research.status_code == 200
    research_payload = research.json()
    assert research_payload["status"] == "completed"
    assert research_payload["workspace"]["task_board"]["items"][0]["task"]["status"] == "completed"
    assert research_payload["workspace"]["capabilities"]["deep_research"][0]["canonical_summary"]["status"] == "completed"

    execution_task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_v3_engines",
            "task_id": "task_execution_v3",
            "subject": "Run fpocket",
            "description": "Run fpocket against the candidate structure.",
            "kind": "execution",
            "lane_id": "lane_v3_engines",
        },
    )
    assert execution_task.status_code == 200
    execution = client.post(
        "/v3/sessions/sess_v3_engines/messages",
        json={"message": "Run the execution task.", "task_id": "task_execution_v3"},
    )
    assert execution.status_code == 200
    execution_payload = execution.json()
    assert execution_payload["status"] == "waiting_approval"
    pending = execution_payload["workspace"]["pending_approvals"]
    assert pending[0]["kind"] == "execution_launch"
    assert execution_payload["workspace"]["capabilities"]["execution"][0]["status"] == "waiting_approval"

    approval_id = pending[0]["approval_id"]
    resolved = client.post(
        f"/v3/approvals/{approval_id}/resolve",
        json={"decision": "approved", "actor_ref": "tester"},
    )
    assert resolved.status_code == 200
    resolved_payload = resolved.json()
    assert resolved_payload["status"] == "completed"
    assert resolved_payload["workspace"]["pending_approvals"] == []
    assert resolved_payload["workspace"]["capabilities"]["execution"][0]["status"] == "succeeded"
    assert resolved_payload["workspace"]["artifacts"]

    reporting_task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_v3_engines",
            "task_id": "task_report_v3",
            "subject": "Summarize workspace",
            "description": "Produce a concise report for the completed V3 workspace.",
            "kind": "reporting",
            "lane_id": "lane_v3_engines",
        },
    )
    assert reporting_task.status_code == 200
    report = client.post(
        "/v3/sessions/sess_v3_engines/messages",
        json={"message": "Create the report.", "task_id": "task_report_v3"},
    )
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["status"] == "completed"
    assert report_payload["workspace"]["reports"][0]["status"] == "ready"
    assert report_payload["workspace"]["capabilities"]["reporting"][0]["report"]["status"] == "ready"

    events = client.get("/v3/sessions/sess_v3_engines/events?replay=1")
    assert events.status_code == 200
    assert "event: engine.invocation.started" in events.text
    assert "event: report.generated" in events.text


def test_v3_message_ingress_uses_llm_driver_when_model_factory_is_available(monkeypatch) -> None:
    client, _ = _build_v3_llm_client(monkeypatch)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_llm",
            "project_id": "proj_001",
            "objective": "Capture the user's design goal",
        },
    )
    assert created.status_code == 200

    message = client.post(
        "/v3/sessions/sess_v3_llm/messages",
        json={"message": "Please track extracting the design goals as a task."},
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["outputs"] == ["Created task task_llm_001 and captured the goal."]
    assert payload["workspace"]["task_board"]["items"][0]["task"]["task_id"] == "task_llm_001"
    assert payload["workspace"]["conversation"][0]["content"] == "Please track extracting the design goals as a task."
    assert payload["workspace"]["conversation"][1]["content"] == "Created task task_llm_001 and captured the goal."
    assert any(event["event_type"] == "tool.completed" for event in payload["events"])


def test_v3_message_ingress_returns_service_unavailable_without_model_factory(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_missing_llm",
            "project_id": "proj_001",
            "objective": "Capture the user's design goal",
        },
    )
    assert created.status_code == 200

    message = client.post(
        "/v3/sessions/sess_v3_missing_llm/messages",
        json={"message": "Please track extracting the design goals as a task."},
    )
    assert message.status_code == 503
    assert "requires a configured model_factory" in message.json()["detail"]


def test_resolve_approval_advances_episode_and_exposes_runs_and_artifacts(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Improve thermostability"},
    ).json()
    episode_id = created["episode_id"]
    first_payload = _resolve_next_approval(client, episode_id)
    assert first_payload["workspace"]["workflow"]["episode_status"] == "completed"
    assert first_payload["workspace"]["workflow"]["current_phase"] == "report_review"
    assert first_payload["workspace"]["pending_actions"] == []
    assert len(first_payload["workspace"]["design"]["artifacts"]) >= 1
    assert {event["event_type"] for event in first_payload["events"]} >= {
        "workflow.phase_changed",
        "workflow.summary_updated",
        "workflow.run_status_changed",
        "workflow.report_available",
    }
    payload = first_payload
    assert payload["workspace"]["workflow"]["episode_status"] == "completed"
    assert payload["workspace"]["workflow"]["current_phase"] == "report_review"
    assert payload["workspace"]["pending_actions"] == []
    assert len(payload["workspace"]["runs"]) == 1
    assert len(payload["workspace"]["artifacts"]) >= 3
    assert payload["workspace"]["report"]["report_id"] == f"{episode_id}-report"
    assert {event["event_type"] for event in payload["events"]} >= {
        "workflow.progress_updated",
        "workflow.run_status_changed",
        "workflow.artifact_available",
        "workflow.report_available",
    }

    runs = client.get(f"/episodes/{episode_id}/runs")
    artifacts = client.get(f"/episodes/{episode_id}/artifacts")
    reports = client.get(f"/episodes/{episode_id}/reports")
    pending = client.get(f"/episodes/{episode_id}/pending-actions")
    assert runs.json()[0]["status"] == "succeeded"
    assert len(artifacts.json()) >= 3
    assert reports.json()[0]["artifact_id"] == f"{episode_id}-report-artifact"
    assert pending.json() == []


def test_resume_and_stream_endpoint_emit_projected_host_events(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Improve thermostability"},
    ).json()
    episode_id = created["episode_id"]

    resumed = client.post(
        "/commands/resume_episode",
        json={
            "episode_id": episode_id,
            "resume_payload": {"approved": True},
        },
    )
    assert resumed.status_code == 200

    stream_response = client.get(f"/episodes/{episode_id}/stream")
    assert stream_response.status_code == 200
    lines = [line for line in stream_response.text.splitlines() if line.startswith("data: ")]
    events = [json.loads(line[6:]) for line in lines]
    event_types = {event["event_type"] for event in events}

    assert "workflow.phase_changed" in event_types
    assert "workflow.progress_updated" in event_types
    assert "workflow.run_status_changed" in event_types
    assert "workflow.artifact_available" in event_types
    assert "workflow.report_available" in event_types


def test_workspace_queries_return_canonical_research_outputs(monkeypatch) -> None:
    client, foundation = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Research thermostability evidence"},
    ).json()
    episode_id = created["episode_id"]

    foundation.repositories.evidence_records.save(
        EvidenceRecord(
            evidence_id="ev_001",
            episode_id=episode_id,
            summary="A homolog family remains active above 60C.",
            query="thermostable homolog catalase",
            confidence_label="high",
            created_at="2026-04-11T12:00:00+00:00",
        )
    )
    foundation.repositories.source_refs.save(
        SourceRef(
            source_ref_id="src_001",
            evidence_id="ev_001",
            episode_id=episode_id,
            title="Thermostable catalase paper",
            locator="https://example.org/paper",
            kind=SourceRefKind.PAPER,
            created_at="2026-04-11T12:01:00+00:00",
        )
    )
    foundation.repositories.research_summaries.save(
        ResearchSummaryRecord(
            episode_id=episode_id,
            summary="Public literature indicates one promising stable scaffold family.",
            created_at="2026-04-11T12:02:00+00:00",
            updated_at="2026-04-11T12:02:00+00:00",
        )
    )
    foundation.repositories.unresolved_gaps.save(
        UnresolvedGapRecord(
            gap_id="gap_001",
            episode_id=episode_id,
            summary="Missing structure-backed comparison for top hits.",
            created_at="2026-04-11T12:03:00+00:00",
        )
    )

    workspace = client.get(f"/episodes/{episode_id}/workspace")

    assert workspace.status_code == 200
    research = workspace.json()["research"]
    assert research["summary"]["summary"].startswith("Public literature indicates")
    assert research["evidence"][0]["query"] == "thermostable homolog catalase"
    assert research["evidence"][0]["source_refs"][0]["kind"] == "paper"
    assert research["unresolved_gaps"][0]["summary"].startswith("Missing structure-backed")


def test_unified_supervisor_resumes_design_then_execution_on_one_episode_thread(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Research thermostability evidence"},
    ).json()
    episode_id = created["episode_id"]
    assert created["workspace"]["workflow"]["current_phase"] == "execution"

    design_payload = _resolve_next_approval(client, episode_id)
    assert design_payload["workspace"]["workflow"]["current_phase"] == "report_review"
    assert design_payload["workspace"]["pending_actions"] == []
    assert design_payload["workspace"]["runs"][0]["episode_id"] == episode_id
    assert design_payload["workspace"]["report"]["report_id"] == f"{episode_id}-report"


def test_design_review_resume_uses_existing_host_command_path(monkeypatch) -> None:
    client, _ = _build_design_client(monkeypatch)

    created = client.get("/episodes/ep_design/workspace")
    assert created.json()["workflow"]["summary"]["artifact_count"] >= 1
    assert created.json()["workflow"]["current_phase"] == "design"
    assert created.json()["pending_actions"] == []
    assert len(created.json()["design"]["artifacts"]) >= 1
    assert "artifact_workspace_summary" in created.json()["design"]


def test_report_query_and_projection_become_available_after_supervisor_completion(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Improve thermostability"},
    ).json()
    episode_id = created["episode_id"]
    design_resume = _resolve_next_approval(client, episode_id)

    workspace = design_resume["workspace"]
    report = workspace["report"]
    assert report["summary"].startswith("Objective")
    assert report["stage_summary"].startswith("Research summary:")

    query = client.get(f"/episodes/{episode_id}/reports")
    assert query.status_code == 200
    assert query.json()[0]["report_id"] == report["report_id"]


def test_project_and_episode_queries_support_browser_shell_bootstrap(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Bootstrap shell workspace"},
    ).json()

    projects = client.get("/projects")
    episodes = client.get("/projects/proj_001/episodes")

    assert projects.status_code == 200
    assert projects.json()[0]["project_id"] == "proj_001"
    assert episodes.status_code == 200
    assert {episode["episode_id"] for episode in episodes.json()} >= {created["episode_id"]}
