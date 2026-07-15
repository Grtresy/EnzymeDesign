from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import create_app
from openzyme_host_api.app import DrainV3RuntimeRequest
from openzyme_host_api.app import PostV3MessageRequest
from openzyme_host_api.background_runtime import RuntimeSignalNotifier
from openzyme_host_api.background_runtime import V3BackgroundRuntimeService
from openzyme_runtime import ConstraintItem
from openzyme_runtime import ConstraintSet
from openzyme_runtime import DesignBriefDraft
from openzyme_runtime import DesignNextAction
from openzyme_runtime import ExecutionPlanDraft
from openzyme_runtime import IntakeClarification
from openzyme_runtime import IntakePhaseOutput
from openzyme_runtime import LangChainToolCallingInvoker
from openzyme_runtime import ReportDraft
from openzyme_runtime import ResearchBriefDraft as RuntimeResearchBriefDraft
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import get_llm_debug_recorder
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_core import EngineDescriptor
from openzyme_core import EngineDocumentRecord
from openzyme_core import EngineRegistry
from openzyme_core import CoreRepositories
from openzyme_core import DurableEventRepository
from openzyme_core import SandboxWorkspaceService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_core import sandbox_image_record
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ExecutionParsedResult
from openzyme_engines import ResearchBriefDraft as EngineResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft as EngineResearchUnitDraft
from openzyme_engines import ResearchUnitPlan as EngineResearchUnitPlan
from openzyme_engines.execution import ExecutionStartResult
from openzyme_host_api.v3_service import V3EventStore
from openzyme_host_api.v3_service import V3HostApiService


def test_v3_durable_events_survive_host_restart_and_replay_from_cursor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "durable-events.sqlite3"))
    first_dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
    )
    with TestClient(create_app(first_dependencies)) as first_client:
        created = first_client.post(
            "/v3/sessions",
            headers={"Idempotency-Key": "create-restart-session"},
            json={
                "session_id": "sess_restart_events",
                "project_id": "proj_restart_events",
                "objective": "Prove event replay after restart",
            },
        )
        assert created.status_code == 200
        first_event = created.json()["events"][0]
        assert first_event["cursor"] > 0

    second_dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
    )
    with TestClient(create_app(second_dependencies)) as second_client:
        replay = second_client.get(
            "/v3/sessions/sess_restart_events/events?replay=1"
        )
        assert replay.status_code == 200
        assert f"id: {first_event['cursor']}" in replay.text
        assert first_event["event_id"] in replay.text

        after = second_client.get(
            "/v3/sessions/sess_restart_events/events?replay=1",
            headers={"Last-Event-ID": str(first_event["cursor"])},
        )
        assert after.status_code == 200
        assert first_event["event_id"] not in after.text


def test_v3_task_create_idempotency_replays_response_and_rejects_collision(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch)
    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_idempotency",
            "project_id": "proj_idempotency",
            "objective": "Prove command receipts",
        },
    )
    assert created.status_code == 200
    request = {
        "session_id": "sess_idempotency",
        "task_id": "task_idempotency",
        "subject": "Create exactly once",
        "description": "Retry-safe task creation",
    }
    headers = {"Idempotency-Key": "create-task-once"}

    first = client.post("/v3/tasks", headers=headers, json=request)
    second = client.post("/v3/tasks", headers=headers, json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    events = client.get("/v3/sessions/sess_idempotency/events?replay=1")
    assert events.text.count("event: task.created") == 1

    conflict = client.post(
        "/v3/tasks",
        headers=headers,
        json={**request, "subject": "Conflicting retry"},
    )
    assert conflict.status_code == 409
    assert "different request" in conflict.json()["detail"]


def test_v3_event_insert_failure_rolls_back_local_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "event-rollback.sqlite3"))
    def fail_event_append(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError("forced durable event failure")

    monkeypatch.setattr(DurableEventRepository, "append", fail_event_append)
    with pytest.raises(RuntimeError, match="forced durable event failure"):
        with provider.write() as owner:
            service = V3HostApiService(
                repositories=owner.repositories,
                event_store=V3EventStore(owner.repositories),
            )
            service.create_session(
                session_id="sess_rolled_back",
                project_id="proj_rolled_back",
                objective="This command must roll back",
            )

    with provider.read() as owner:
        assert owner.repositories.sessions.get("sess_rolled_back") is None
        assert owner.repositories.agents.list_by_session("sess_rolled_back") == []


class FakeExecutionAdapter:
    def submit_execution(
        self, session_id: str, payload: dict[str, object]
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            run_id="run_001",
            status=RunStatus.SUCCEEDED,
            execution_mode="ssh",
            remote_run_dir=f"/remote/{session_id}/run_001",
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
    def conduct(
        self, *, session_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult:
        del session_id, research_brief
        return self.normalize_search_response(
            unit=unit,
            response=self.web_search(
                query=unit.query,
                max_results=3,
                topic=unit.topic,
                include_raw_content=True,
            ),
        )

    def web_search(
        self,
        *,
        query: str,
        max_results: int = 3,
        topic: str = "general",
        include_raw_content: bool = True,
    ) -> dict[str, object]:
        del max_results, include_raw_content
        return {
            "results": [
                {
                    "title": f"Source for {topic}",
                    "url": f"https://example.org/{topic.replace(' ', '-')}",
                    "content": f"Finding for {query}",
                }
            ]
        }

    def fetch_url(
        self,
        *,
        url: str,
        query: str | None = None,
        extract_depth: str = "basic",
        format: str = "markdown",
        include_images: bool = False,
    ) -> dict[str, object]:
        del query, extract_depth, format, include_images
        return {
            "results": [
                {
                    "title": "Fetched source",
                    "url": url,
                    "raw_content": "Fetched content.",
                }
            ]
        }

    def normalize_search_response(
        self,
        *,
        unit: ResearchUnit,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        results = list(response.get("results", []))
        result = dict(results[0]) if results else {}
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the brief.",
            findings=(
                ResearchFinding(
                    summary=str(
                        result.get("content")
                        or result.get("raw_content")
                        or f"Finding for {unit.query}"
                    ),
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Source for {unit.unit_id}",
                            locator=str(
                                result.get("url")
                                or f"https://example.org/{unit.unit_id}"
                            ),
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need structural follow-up",),
        )

    def normalize_fetch_response(
        self,
        *,
        url: str,
        query: str | None,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        return self.normalize_search_response(
            unit=ResearchUnit(
                unit_id="web-fetch", topic="web fetch", query=query or url
            ),
            response=response,
        )


class FakeHarnessInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
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
        return {
            "content": "Created task task_llm_001 and captured the goal.",
            "tool_calls": [],
        }


class FakeHarnessModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, FakeHarnessInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeHarnessInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = FakeHarnessInvoker()
        return self.invokers[purpose]


class BlockingHarnessInvoker(FakeHarnessInvoker):
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.entered = entered
        self.release = release

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().invoke_with_tools(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
        )


class BlockingHarnessModelFactory:
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self.invoker = BlockingHarnessInvoker(entered, release)

    def create_tool_calling_invoker(self, *, purpose: str) -> BlockingHarnessInvoker:
        assert purpose == "v3_harness_loop"
        return self.invoker


class PressureHarnessInvoker:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "tools": list(tools),
            }
        )
        if not self.responses:
            return {"content": "pressure test complete", "tool_calls": []}
        return self.responses.pop(0)


class PressureHarnessModelFactory:
    def __init__(
        self,
        responses: list[dict[str, object]],
        *,
        model: str = "pressure-test-model",
        context_window_tokens: int | None = 100_000,
        default_output_tokens: int | None = 0,
    ) -> None:
        self.model = model
        self.context_window_tokens = context_window_tokens
        self.default_output_tokens = default_output_tokens
        self.invokers: dict[str, PressureHarnessInvoker] = {}
        self._responses = list(responses)

    def create_tool_calling_invoker(self, *, purpose: str) -> PressureHarnessInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = PressureHarnessInvoker(self._responses)
        return self.invokers[purpose]


class FakePhaseBStructuredInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict[str, object]):
        del system_prompt
        objective = str(user_payload.get("objective") or "Improve thermostability")
        if self.purpose == "intake_collect":
            return IntakePhaseOutput(
                clarification=IntakeClarification(),
                constraint_set=ConstraintSet(
                    objective_summary=objective,
                    constraints=[
                        ConstraintItem(
                            category="technical",
                            description="Prepare an execution-ready design workspace.",
                        )
                    ],
                ),
                design_brief=DesignBriefDraft(
                    design_brief=f"Design brief for {objective}",
                    success_criteria=["Prepare execution-ready artifacts."],
                ),
                research_brief=RuntimeResearchBriefDraft(
                    research_brief=f"Research brief for {objective}",
                    focus_areas=["evidence"],
                    expected_outputs=["research summary"],
                ),
            )
        if self.purpose == "design_next_action":
            evidence_refs = list(user_payload.get("evidence_refs") or [])
            run_summary = dict(user_payload.get("run_summary") or {})
            if not evidence_refs:
                return DesignNextAction(
                    action_kind="collect_research",
                    summary="Collect evidence for the design objective.",
                    rationale="No canonical evidence exists yet.",
                    arguments={},
                )
            if not run_summary:
                return DesignNextAction(
                    action_kind="request_execution",
                    summary="Route the curated workspace into execution.",
                    rationale="Evidence and execution-ready artifacts are available.",
                    arguments={},
                )
            return DesignNextAction(
                action_kind="stop",
                summary="Package the completed design dossier.",
                rationale="Research, workspace curation, and execution are complete.",
                stop_reason="design_loop_complete",
                arguments={},
            )
        if self.purpose == "deep_research_brief":
            return EngineResearchBriefDraft(research_brief=f"Research brief for {objective}")
        if self.purpose == "deep_research_supervisor":
            unit_results = list(user_payload.get("unit_results") or [])
            if any(result.get("findings") for result in unit_results):
                return ResearchSupervisorAction(
                    action_kind="complete",
                    rationale="A usable finding exists.",
                )
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one evidence unit.",
                unit_plan=EngineResearchUnitPlan(
                    units=[
                        EngineResearchUnitDraft(
                            unit_id="evidence",
                            topic="supporting evidence",
                            query=f"{objective} evidence",
                            rationale="Collect evidence for downstream design.",
                        )
                    ],
                    synthesis_goal="Support downstream design.",
                ),
            )
        if self.purpose == "deep_research_synthesis":
            return EvidenceSynthesis(
                summary="Research evidence supports the current objective.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Evidence supports the current scaffold direction.",
                        query=f"{objective} evidence",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Synthetic source",
                                locator="https://example.org/evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                    EvidenceSynthesisItem(
                        summary="Structure-backed evidence supports execution.",
                        query=f"{objective} structure evidence",
                        confidence_label="medium",
                        sources=[
                            ResearchSourceItem(
                                title="Synthetic structure source",
                                locator="https://example.org/structure-evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                ],
                unresolved_gaps=["Need wet-lab validation."],
            )
        if self.purpose == "execution_plan":
            return ExecutionPlanDraft(
                catalog_tool_id="fpocket",
                rationale="Use the curated execution-ready structure artifact.",
                tool_inputs={},
                expected_result_summary="Run fpocket on the selected structure artifact.",
            )
        if self.purpose == "report_review":
            return ReportDraft(
                title="OpenZyme design report",
                summary="Objective Improve thermostability completed with research, execution, and report outputs.",
                stage_summary="Research summary: evidence was collected and execution results were recorded.",
                key_decisions=["Proceed with the current scaffold direction."],
            )
        raise AssertionError(f"Unhandled structured purpose {self.purpose!r}")


class FakePhaseBToolCallingInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        self.calls += 1
        if self.purpose == "deep_research_researcher" and self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_web_search",
                        "name": "web.search",
                        "args": {
                            "query": "thermostability evidence",
                            "topic": "supporting evidence",
                            "max_results": 1,
                        },
                    }
                ],
            }
        return {"content": "", "tool_calls": []}


class FakePhaseBModelFactory:
    def __init__(self) -> None:
        self.tool_invokers: dict[str, FakePhaseBToolCallingInvoker] = {}

    def create_structured_invoker(self, *, purpose: str) -> FakePhaseBStructuredInvoker:
        return FakePhaseBStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str):
        if purpose.startswith("v3_"):
            return FakeHarnessInvoker()
        if purpose not in self.tool_invokers:
            self.tool_invokers[purpose] = FakePhaseBToolCallingInvoker(purpose)
        return self.tool_invokers[purpose]


class FakeEchoHarnessInvoker:
    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        return {"content": "Planning started.", "tool_calls": []}


class FakeEchoHarnessModelFactory:
    def create_tool_calling_invoker(self, *, purpose: str) -> FakeEchoHarnessInvoker:
        assert purpose.startswith("v3_")
        return FakeEchoHarnessInvoker()


class BlockingTraceInvoker:
    def __init__(
        self, entered_second_call: threading.Event, release_second_call: threading.Event
    ) -> None:
        self.calls = 0
        self.entered_second_call = entered_second_call
        self.release_second_call = release_second_call

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "I will create a task before answering.",
                "tool_calls": [
                    {
                        "id": "call_task_create",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_realtime_trace",
                            "subject": "Realtime trace task",
                            "description": "Exercise realtime trace streaming.",
                        },
                    }
                ],
            }
        self.entered_second_call.set()
        assert self.release_second_call.wait(timeout=5)
        return {"content": "Task created.", "tool_calls": []}


class BlockingTraceModelFactory:
    def __init__(self) -> None:
        self.entered_second_call = threading.Event()
        self.release_second_call = threading.Event()
        self.invoker = BlockingTraceInvoker(
            self.entered_second_call, self.release_second_call
        )

    def create_tool_calling_invoker(self, *, purpose: str) -> BlockingTraceInvoker:
        assert purpose == "v3_harness_loop"
        return self.invoker


class DebugRecordingModelFactory:
    def create_tool_calling_invoker(
        self, *, purpose: str
    ) -> LangChainToolCallingInvoker:
        class _Runnable:
            def invoke(self, messages):
                return {
                    "content": "Debug response.",
                    "tool_calls": [],
                    "message_count": len(messages),
                }

        class _Model:
            def bind_tools(self, tools):
                return _Runnable()

        return LangChainToolCallingInvoker(
            model=_Model(),
            purpose=purpose,
            model_name="debug-model",
            base_url="https://debug.example/v1",
        )


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
    return (
        None
        if getattr(message, "name", None) is None
        else str(getattr(message, "name"))
    )


def _tool_message_payload(message: object) -> dict[str, object]:
    try:
        envelope = json.loads(_message_content(message))
    except json.JSONDecodeError:
        return {}
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else {}


def _created_code_artifact_id(messages: list[object]) -> str | None:
    for message in reversed(messages):
        if _tool_message_name(message) != "artifact.create_text":
            continue
        payload = _tool_message_payload(message)
        artifact = payload.get("artifact")
        if isinstance(artifact, dict) and artifact.get("artifact_id"):
            return str(artifact["artifact_id"])
    return None


class FakeEngineHarnessInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.system_prompts: list[str] = []
        self.report_delegated = False

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        self.system_prompts.append(system_prompt)
        if self.purpose == "v3_teammate_loop:researcher":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_research_start",
                            "name": "deep_research.start",
                            "args": {
                                "task_id": "task_research_v3",
                                "brief": "Collect papers for the scaffold family.",
                            },
                        }
                    ],
                }
            if self.calls == 2:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_research_task_complete",
                            "name": "task.finish",
                            "args": {
                                "task_id": "task_research_v3",
                                "status": "completed",
                                "summary": "Research complete.",
                            },
                        }
                    ],
                }
            return {"content": "Research complete.", "tool_calls": []}
        if self.purpose == "v3_teammate_loop:executor":
            if any(_tool_message_name(message) == "task.finish" for message in messages):
                return {
                    "content": "fpocket found 1 pocket(s) for the selected artifact set. Output artifacts: run_inv_pipeline_task_execution_v3:target_out.",
                    "tool_calls": [],
                }
            if any(
                _tool_message_name(message) == "execution.pipeline.status"
                for message in messages
            ):
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_task_complete",
                            "name": "task.finish",
                            "args": {
                                "task_id": "task_execution_v3",
                                "status": "completed",
                                "summary": "fpocket found 1 pocket for the selected artifact set.",
                            },
                        }
                    ],
                }
            code_artifact_id = _created_code_artifact_id(messages)
            if code_artifact_id is not None and not any(
                _tool_message_name(message) == "execution.pipeline.start"
                for message in messages
            ):
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_start",
                            "name": "execution.pipeline.start",
                            "args": {
                                "task_id": "task_execution_v3",
                                "code_artifact_id": code_artifact_id,
                                "inputs": {
                                    "artifact_ids": ["art_v3_structure"],
                                },
                            },
                        }
                    ],
                }
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_source",
                            "name": "artifact.create_text",
                            "args": {
                                "filename": "fpocket_pipeline.py",
                                "content": (
                                    "from openzyme_pipeline import artifacts, hpc, structure_tools\n"
                                    "structure = artifacts.get('art_v3_structure')\n"
                                    "ws = hpc.workspace('fpocket')\n"
                                    "remote_structure = ws.stage_artifact(structure['artifact_id'], workspace_path='inputs/structure.pdb')\n"
                                    "run = structure_tools.fpocket(structure=remote_structure, placement=ws, expected_outputs=[{'path': 'target_out', 'kind': 'directory', 'format': 'fpocket'}])\n"
                                    "ws.fetch_outputs(run)\n"
                                ),
                            },
                        }
                    ],
                }
            if "Existing execution pipeline invocation:" in system_prompt:
                invocation_id = (
                    system_prompt.split("Existing execution pipeline invocation:", 1)[1]
                    .split(".", 1)[0]
                    .strip()
                )
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_status",
                            "name": "execution.pipeline.status",
                            "args": {"invocation_id": invocation_id},
                        }
                    ],
                }
            return {
                "content": "Execution started and is waiting for approval.",
                "tool_calls": [],
            }
        if self.purpose == "v3_teammate_loop:reporter":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_report_draft_update",
                            "name": "report_draft.update",
                            "args": {
                                "task_id": "task_report_v3",
                                "title": "Workspace report",
                                "summary": "Integrated workspace report",
                                "status": "ready",
                                "markdown": "# Workspace report\n\nIntegrated workspace report",
                            },
                        }
                    ],
                }
            if self.calls == 2:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_report_publish",
                            "name": "report.publish",
                            "args": {
                                "task_id": "task_report_v3",
                                "title": "Workspace report",
                                "summary": "Integrated workspace report",
                                "stage_summary": "Research and execution summarized.",
                            },
                        }
                    ],
                }
            if self.calls == 3:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_report_task_complete",
                            "name": "task.finish",
                            "args": {
                                "task_id": "task_report_v3",
                                "status": "completed",
                                "summary": "Reporting complete.",
                            },
                        }
                    ],
                }
            return {"content": "Reporting complete.", "tool_calls": []}
        focused_task = next(
            (
                line.removeprefix("Focused task: ").strip()
                for line in system_prompt.splitlines()
                if line.startswith("Focused task: ")
            ),
            "none",
        )
        latest_tool_name = None
        seen_tool_names: list[str] = []
        for message in messages:
            if _message_role(message) != "tool":
                continue
            tool_name = _tool_message_name(message)
            if tool_name is None:
                continue
            latest_tool_name = tool_name
            seen_tool_names.append(tool_name)
        latest_user_message = next(
            (
                _message_content(message)
                for message in reversed(messages)
                if _message_role(message) == "user"
            ),
            "",
        )
        if (
            focused_task == "task_research_v3"
            and "completed task_id=task_research_v3" in system_prompt
            and latest_tool_name is None
        ):
            return {"content": "Research complete.", "tool_calls": []}
        if (
            focused_task == "task_execution_v3"
            and "completed task_id=task_execution_v3" in system_prompt
            and latest_tool_name is None
        ):
            return {
                "content": "fpocket found 1 pocket(s) for the selected artifact set. Output artifacts: run_inv_pipeline_task_execution_v3:target_out.",
                "tool_calls": [],
            }
        if (
            focused_task == "task_report_v3"
            and "completed task_id=task_report_v3" in system_prompt
            and latest_tool_name is None
        ):
            return {"content": "Reporting complete.", "tool_calls": []}
        if focused_task == "task_research_v3":
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate_research",
                            "name": "task.delegate",
                            "args": {
                                "task_id": focused_task,
                                "agent_role": "researcher",
                                "instructions": "Collect papers for the scaffold family.",
                            },
                        },
                    ],
                }
            return {
                "content": "Delegated research task task_research_v3.",
                "tool_calls": [],
            }

        if focused_task == "task_execution_v3":
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate_execution",
                            "name": "task.delegate",
                            "args": {
                                "task_id": focused_task,
                                "agent_role": "executor",
                                "instructions": "Run fpocket against the candidate structure.",
                            },
                        },
                    ],
                }
            return {
                "content": "Delegated execution task task_execution_v3.",
                "tool_calls": [],
            }

        if focused_task == "task_report_v3":
            if not self.report_delegated:
                self.report_delegated = True
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate_report",
                            "name": "task.delegate",
                            "args": {
                                "task_id": focused_task,
                                "agent_role": "reporter",
                                "instructions": "Produce a concise report for the completed V3 workspace.",
                            },
                        },
                    ],
                }
            return {
                "content": "Delegated reporting task task_report_v3.",
                "tool_calls": [],
            }

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
            return {
                "content": "Created task task_llm_001 and captured the goal.",
                "tool_calls": [],
            }

        raise AssertionError(
            f"Unhandled fake harness request for focused task {focused_task!r}"
        )


class FakeEngineHarnessModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, FakeEngineHarnessInvoker] = {}
        self.fallback_factory = FakePhaseBModelFactory()

    def create_structured_invoker(self, *, purpose: str) -> FakePhaseBStructuredInvoker:
        return self.fallback_factory.create_structured_invoker(purpose=purpose)

    def create_tool_calling_invoker(self, *, purpose: str):
        if not purpose.startswith("v3_"):
            return self.fallback_factory.create_tool_calling_invoker(purpose=purpose)
        if purpose not in self.invokers:
            self.invokers[purpose] = FakeEngineHarnessInvoker(purpose)
        return self.invokers[purpose]


class DiagnosticExecutorInvoker:
    def __init__(self) -> None:
        self.calls = 0
        self.system_prompts: list[str] = []

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        self.system_prompts.append(system_prompt)
        assert "sanitized failure evidence" in system_prompt
        assert "INPUT_OR_ENTRYPOINT_MISSING" in system_prompt
        if any(_tool_message_name(message) == "task.finish" for message in messages):
            return {
                "content": (
                    "The approved fpocket task failed at the HPC runner boundary; "
                    "I marked the execution task failed with the runner evidence."
                ),
                "tool_calls": [],
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_mark_failed",
                    "name": "task.finish",
                    "args": {
                        "task_id": "task_hpc_diag",
                        "status": "failed",
                        "summary": "Approved fpocket failed at the HPC runner boundary.",
                        "failure_summary": (
                            "Approved fpocket reached the HPC runner, but the runner failed "
                            "with INPUT_OR_ENTRYPOINT_MISSING while creating the Apptainer container."
                        ),
                        "failure_ref": "engine:inv_hpc_diag",
                    },
                }
            ],
        }


class DiagnosticExecutorModelFactory:
    def __init__(self) -> None:
        self.invoker = DiagnosticExecutorInvoker()
        self.master_calls = 0

    def create_tool_calling_invoker(self, *, purpose: str):
        if purpose == "v3_harness_loop":
            factory = self

            class _MasterInvoker:
                def invoke_with_tools(
                    self,
                    *,
                    system_prompt: str,
                    messages: list[object],
                    tools: list[object],
                ) -> dict[str, object]:
                    del system_prompt, messages, tools
                    factory.master_calls += 1
                    return {
                        "content": (
                            "The approved fpocket task failed at the HPC runner boundary. "
                            "The execution task is marked failed with failure_ref engine:inv_hpc_diag."
                        ),
                        "tool_calls": [],
                    }

            return _MasterInvoker()
        assert purpose == "v3_teammate_loop:executor"
        return self.invoker


class FailedHpcExecutionEngine:
    def __init__(self, repositories: CoreRepositories) -> None:
        self.repositories = repositories

    @property
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            engine_name="execution",
            tool_names=("execution.pipeline.start", "execution.pipeline.status"),
            input_schema={},
            output_schema={},
            requires_approval=True,
            supports_background=False,
            idempotency_key_shape="test",
            produces_artifact_types=(),
            capability_key="execution",
        )

    def register_tools(self, registry: object) -> None:
        del registry

    def continue_after_approval(
        self, *, invocation_id: str, resolution: str
    ) -> ExecutionStartResult:
        del resolution
        invocation = self.repositories.invocations.get(invocation_id)
        assert invocation is not None
        output_ref = "eng_out_failed_hpc"
        error = {
            "type": "hpc_operation_failed",
            "message": "Pipeline failed: Traceback (most recent call last):",
            "hint": "Inspect the HPC run or runner configuration.",
            "stderr_excerpt": "PipelineSdkError: structure_tools.fpocket failed with status failed",
            "hpc_failure": {
                "run_id": "run_failed_hpc",
                "runner_run_id": "runner_failed_hpc",
                "status": "failed",
                "execution_mode": "ssh",
                "exit_code": 255,
                "error_code": "INPUT_OR_ENTRYPOINT_MISSING",
                "stderr_excerpt": "FATAL: container creation failed: mount source does not exist",
            },
        }
        now = "2026-05-03T16:00:00+00:00"
        self.repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=output_ref,
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="execution_result",
                payload={
                    "pipeline": {
                        "sandbox_status": "failed",
                        "terminal_summary": "Pipeline failed.",
                        "error": error,
                    }
                },
                created_at=now,
                updated_at=now,
            )
        )
        failed = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.FAILED,
            input_ref=invocation.input_ref,
            output_ref=output_ref,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(failed)
        return ExecutionStartResult(
            invocation=failed,
            run=None,
            approval=None,
            parsed_result=ExecutionParsedResult(
                result_summary="Pipeline failed.",
                structured_findings={"error": error},
            ),
        )


def _build_client(
    monkeypatch, *, with_model_factory: bool = True
) -> tuple[TestClient, RuntimeFoundation]:
    del monkeypatch
    foundation = RuntimeFoundation(
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(
            RepoBackedHpcCatalogProvider()
        ),
        research_adapter=FakeResearchAdapter(),
        model_factory=FakePhaseBModelFactory() if with_model_factory else None,
    )
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=foundation,
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
                    foundation=replace(
                        foundation, model_factory=FakeHarnessModelFactory()
                    ),
                )
            )
        ),
        foundation,
    )


def _build_v3_engine_llm_client(
    monkeypatch,
) -> tuple[TestClient, CoreRepositories, FakeEngineHarnessModelFactory]:
    client, foundation = _build_client(monkeypatch)
    v3_repositories = _build_v3_engine_repositories()
    model_factory = FakeEngineHarnessModelFactory()
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(foundation, model_factory=model_factory),
                    v3_legacy_repositories_for_tests=v3_repositories,
                )
            )
        ),
        v3_repositories,
        model_factory,
    )


def _build_v3_engine_repositories() -> CoreRepositories:
    # Explicit legacy fixture: a few pure unit tests inspect one in-memory
    # repository from both the TestClient and assertion threads. Production Host
    # composition always uses SQLiteRepositoryProvider with thread-affine scopes.
    connection = connect_v3_sqlite(":memory:", check_same_thread=False)
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _build_v3_pressure_client(
    monkeypatch,
    model_factory: PressureHarnessModelFactory,
) -> tuple[TestClient, CoreRepositories, PressureHarnessModelFactory]:
    client, foundation = _build_client(monkeypatch)
    del client
    v3_repositories = _build_v3_engine_repositories()
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(foundation, model_factory=model_factory),
                    v3_legacy_repositories_for_tests=v3_repositories,
                )
            )
        ),
        v3_repositories,
        model_factory,
    )


def _clear_context_budget_env(monkeypatch) -> None:
    for name in (
        "OPENZYME_LLM_CONTEXT_WINDOW_TOKENS",
        "OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS",
        "OPENZYME_LLM_CONTEXT_WARN_RATIO",
        "OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO",
        "OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO",
    ):
        monkeypatch.delenv(name, raising=False)


def _seed_large_text_artifact(
    repositories: CoreRepositories,
    session_id: str,
    tmp_path: Path,
) -> str:
    line = "stress-observation-" + ("x" * 720)
    content = "\n".join(f"{index:03d}:{line}" for index in range(500)) + "\n"
    path = tmp_path / "large_tool_source.txt"
    path.write_text(content, encoding="utf-8")
    artifact_id = "art_pressure_large_text"
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id=session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.LOG,
            storage_uri=str(path),
            relative_path="large_tool_source.txt",
            title="large_tool_source.txt",
            description="Large text artifact used by the pressure conversation.",
            metadata={
                "source": "pressure_test",
                "format": "txt",
                "content_digest": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
            },
            created_at="2026-06-04T10:00:00+00:00",
        )
    )
    return artifact_id


def _wait_for_background_runtime(
    client: TestClient,
    *,
    min_processed: int = 1,
    timeout_seconds: float = 3.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    status: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get("/debug/v3-runtime")
        assert response.status_code == 200
        status = response.json()
        if int(status.get("processed_signal_count") or 0) >= min_processed:
            return status
        time.sleep(0.05)
    return status


def _wait_for_v3_background_workspace(
    client: TestClient,
    *,
    session_id: str,
    is_ready,
    repositories: CoreRepositories | None = None,
    timeout_seconds: float = 30.0,
) -> tuple[dict[str, object], str, dict[str, object], list[str]]:
    deadline = time.monotonic() + timeout_seconds
    workspace: dict[str, object] = {}
    event_text = ""
    runtime_status: dict[str, object] = {}
    resolved_approvals: list[str] = []
    while time.monotonic() < deadline:
        workspace_response = client.get(f"/v3/sessions/{session_id}/workspace")
        if workspace_response.status_code != 200:
            runtime_response = client.get("/debug/v3-runtime")
            assert workspace_response.status_code == 200, {
                "step": "get_v3_workspace",
                "body": workspace_response.text,
                "workspace": workspace,
                "runtime_status": runtime_response.json()
                if runtime_response.status_code == 200
                else runtime_response.text,
                "events": event_text[-1000:],
                "signals": []
                if repositories is None
                else [
                    signal.to_dict()
                    for signal in repositories.runtime_signals.list_by_session(
                        session_id
                    )
                ],
            }
        workspace = workspace_response.json()
        runtime_response = client.get("/debug/v3-runtime")
        assert runtime_response.status_code == 200
        runtime_status = runtime_response.json()

        pending_approvals = workspace.get("pending_approvals") or []
        if pending_approvals:
            approval_id = pending_approvals[0]["approval_id"]
            resolved = client.post(
                f"/v3/approvals/{approval_id}/resolve",
                json={"decision": "approved", "actor_ref": "background_test"},
            )
            assert resolved.status_code == 200, resolved.text
            resolved_approvals.append(approval_id)
            time.sleep(0.2)
            continue

        if is_ready(workspace, event_text, runtime_status):
            while time.monotonic() < deadline:
                events_response = client.get(
                    f"/v3/sessions/{session_id}/events?replay=1"
                )
                if events_response.status_code == 200:
                    event_text = events_response.text
                    return workspace, event_text, runtime_status, resolved_approvals
                assert events_response.status_code == 200, {
                    "step": "get_v3_events",
                    "body": events_response.text,
                    "workspace": workspace,
                    "runtime_status": runtime_status,
                    "signals": []
                    if repositories is None
                    else [
                        signal.to_dict()
                        for signal in repositories.runtime_signals.list_by_session(
                            session_id
                        )
                    ],
                }
        time.sleep(0.2)
    raise AssertionError(
        {
            "tasks": [
                item["task"]
                for item in (workspace.get("task_board") or {}).get("items", [])
            ],
            "pending_approvals": workspace.get("pending_approvals"),
            "capabilities": {
                key: [item.get("status") for item in value]
                for key, value in (workspace.get("capabilities") or {}).items()
            },
            "runtime_status": runtime_status,
            "resolved_approvals": resolved_approvals,
            "signals": []
            if repositories is None
            else [
                signal.to_dict()
                for signal in repositories.runtime_signals.list_by_session(session_id)
            ],
        }
    )


def test_v3_task_crud_does_not_implicitly_drain_agent_runtime() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_task_crud_no_drain",
            "proj_001",
            "Task CRUD",
            "Keep task mutation separate from runtime scheduling.",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:researcher:crud",
            session_id="sess_task_crud_no_drain",
            lane_id=None,
            task_id=None,
            name="Ada",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="idle",
            current_correlation_id=None,
        )
    )
    model_factory = FakeEngineHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )

    created = service.create_task(
        {
            "session_id": "sess_task_crud_no_drain",
            "task_id": "task_no_drain",
            "subject": "Collect evidence",
            "description": "Ready research task.",
            "kind": "research",
        }
    )
    updated = service.update_task(
        "task_no_drain",
        {"description": "Still only a task mutation."},
    )

    assert created["task"]["status"] == "todo"
    assert updated["task"]["status"] == "todo"
    assert model_factory.invokers == {}
    assert repositories.runtime_signals.list_by_session("sess_task_crud_no_drain") == []


def test_v3_task_crud_rejects_business_exit_statuses(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch, with_model_factory=False)
    created_session = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_task_exit_guard",
            "project_id": "proj_001",
            "objective": "Guard task business exits",
        },
    )
    assert created_session.status_code == 200

    for status in ("blocked", "completed", "failed", "cancelled"):
        rejected_create = client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_task_exit_guard",
                "task_id": f"task_create_{status}",
                "subject": status,
                "status": status,
            },
        )
        assert rejected_create.status_code == 400
        assert "task.create cannot set business exit status" in rejected_create.text

    created_task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_task_exit_guard",
            "task_id": "task_edit_exit_guard",
            "subject": "Edit guard",
        },
    )
    assert created_task.status_code == 200
    for status in ("blocked", "completed", "failed", "cancelled"):
        rejected_update = client.patch(
            "/v3/tasks/task_edit_exit_guard",
            json={"status": status},
        )
        assert rejected_update.status_code == 400
        assert "task.edit cannot set business exit status" in rejected_update.text


def test_v3_drain_runtime_does_not_auto_claim_by_default() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_drain_no_auto_claim",
            "proj_001",
            "Drain",
            "Do not auto-claim ready tasks by default.",
        )
    )
    repositories.tasks.save(
        Task.create(
            "task_ready_no_auto_claim",
            "sess_drain_no_auto_claim",
            "Collect evidence",
            "Ready research task.",
            kind="research",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:researcher:no_auto_claim",
            session_id="sess_drain_no_auto_claim",
            lane_id=None,
            task_id=None,
            name="Ada",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="idle",
            current_correlation_id=None,
        )
    )
    service = V3HostApiService(repositories=repositories, event_store=V3EventStore())

    service.drain_runtime(session_id="sess_drain_no_auto_claim")

    assert repositories.runtime_signals.list_by_session("sess_drain_no_auto_claim") == []


def test_v3_drain_runtime_explicit_auto_claim_still_enqueues_ready_task() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_drain_auto_claim",
            "proj_001",
            "Drain",
            "Explicitly auto-claim ready tasks.",
        )
    )
    repositories.tasks.save(
        Task.create(
            "task_ready_auto_claim",
            "sess_drain_auto_claim",
            "Collect evidence",
            "Ready research task.",
            kind="research",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:researcher:auto_claim",
            session_id="sess_drain_auto_claim",
            lane_id=None,
            task_id=None,
            name="Curie",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="idle",
            current_correlation_id=None,
        )
    )
    service = V3HostApiService(repositories=repositories, event_store=V3EventStore())

    service.drain_runtime(
        session_id="sess_drain_auto_claim",
        auto_enqueue_ready_tasks=True,
    )

    signals = repositories.runtime_signals.list_by_session("sess_drain_auto_claim")
    assert len(signals) == 1
    assert signals[0].task_id == "task_ready_auto_claim"
    assert signals[0].reason.value == "task_available"


def test_v3_drain_runtime_uses_configured_scheduler_limits(monkeypatch) -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_drain_limits",
            "proj_001",
            "Drain limits",
            "Use configured scheduler limits.",
        )
    )
    captured: dict[str, object] = {}

    class FakeScheduler:
        def __init__(self, context, **kwargs):
            captured["context"] = context
            captured.update(kwargs)

        def run_once_sync(
            self,
            session_id: str,
            *,
            max_signals: int,
            max_steps_per_agent: int,
            signal_ids=None,
            auto_enqueue_ready_tasks: bool = False,
        ):
            captured["session_id"] = session_id
            captured["max_signals"] = max_signals
            captured["max_steps_per_agent"] = max_steps_per_agent
            captured["signal_ids"] = signal_ids
            captured["auto_enqueue_ready_tasks"] = auto_enqueue_ready_tasks
            return ()

    monkeypatch.setattr("openzyme_host_api.v3_service.AgentRuntimeScheduler", FakeScheduler)
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        scheduler_limits={"global": 7, "session": 5, "agent": 3},
    )

    service.drain_runtime(
        session_id="sess_drain_limits",
        max_signals=4,
        max_steps_per_agent=6,
    )

    assert captured["worker_id"] == "host-api:runtime-drain"
    assert captured["max_global_concurrency"] == 7
    assert captured["max_session_concurrency"] == 5
    assert captured["max_agent_concurrency"] == 3
    assert captured["runtime_mode"] == "manual_drain"
    assert captured["max_signals"] == 4
    assert captured["max_steps_per_agent"] == 6
    assert captured["auto_enqueue_ready_tasks"] is False


def test_v3_manual_drain_returns_locked_when_background_owns_session() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_manual_locked_by_background",
            "proj_001",
            "Runtime lock",
            "Manual drain must respect background ownership.",
        )
    )
    lease = repositories.session_runtime_leases.acquire(
        session_id="sess_manual_locked_by_background",
        owner_id="host-api:background-runtime",
        mode="background",
        lease_seconds=60,
    ).lease
    assert lease is not None
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    result = service.drain_runtime(session_id="sess_manual_locked_by_background")

    assert result.status == "locked"
    assert result.outputs == ()
    assert result.events[0]["event_type"] == "runtime.session_locked"
    assert result.events[0]["payload"]["owner_id"] == "host-api:background-runtime"
    assert result.events[0]["payload"]["mode"] == "background"
    assert repositories.session_runtime_leases.get_active(
        "sess_manual_locked_by_background"
    ).lease_token == lease.lease_token


def test_v3_background_runtime_skips_when_manual_drain_owns_session() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_background_locked_by_manual",
            "proj_001",
            "Runtime lock",
            "Background runtime must respect manual ownership.",
        )
    )
    repositories.session_runtime_leases.acquire(
        session_id="sess_background_locked_by_manual",
        owner_id="host-api:runtime-drain",
        mode="manual_drain",
        lease_seconds=60,
    )
    event_store = V3EventStore()
    service = V3HostApiService(
        repositories=repositories,
        event_store=event_store,
        model_factory=object(),
    )

    outcomes = asyncio.run(
        service.run_background_runtime_once(
            session_id="sess_background_locked_by_manual",
            worker_id="host-api:background-runtime",
        )
    )

    assert outcomes == []
    events = event_store.list("sess_background_locked_by_manual")
    assert [event["event_type"] for event in events] == ["runtime.session_locked"]
    assert events[0]["payload"]["owner_id"] == "host-api:runtime-drain"


def test_v3_session_runtime_lease_does_not_block_other_sessions() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create("sess_locked_a", "proj_001", "A", "A")
    )
    repositories.sessions.save(
        Session.create("sess_unlocked_b", "proj_001", "B", "B")
    )
    repositories.session_runtime_leases.acquire(
        session_id="sess_locked_a",
        owner_id="host-api:background-runtime",
        mode="background",
        lease_seconds=60,
    )
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    result = service.drain_runtime(session_id="sess_unlocked_b")

    assert result.status == "completed"
    assert repositories.session_runtime_leases.get_active("sess_locked_a") is not None
    assert repositories.session_runtime_leases.get_active("sess_unlocked_b") is None


def test_v3_drain_runtime_request_defaults_disable_auto_claim() -> None:
    assert DrainV3RuntimeRequest().auto_enqueue_ready_tasks is False


def test_v3_post_message_request_has_no_max_steps_field() -> None:
    assert "max_steps" not in PostV3MessageRequest.model_fields
    assert "max_steps" not in PostV3MessageRequest.model_json_schema()["properties"]


def test_v3_post_message_only_enqueues_master_signal() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Queue the master.",
        session_id="sess_msg_enqueue",
    )

    result = service.post_message(
        session_id="sess_msg_enqueue",
        message="Start planning.",
    )

    assert result.status == "completed"
    assert result.outputs == ()
    assert model_factory.invokers == {}
    assert repositories.agents.get("sess_msg_enqueue", "agent:master") is not None
    messages = repositories.inbox.list_by_session("sess_msg_enqueue")
    assert [message.message_type for message in messages] == ["user_message"]
    signals = repositories.runtime_signals.list_by_session("sess_msg_enqueue")
    assert len(signals) == 1
    assert signals[0].agent_id == "agent:master"
    assert signals[0].reason.value == "inbox_unread"
    assert signals[0].status.value == "pending"


def test_v3_background_runtime_processes_message_without_manual_drain(
    monkeypatch,
) -> None:
    client, foundation = _build_client(monkeypatch)
    del client
    dependencies = HostApiDependencies(
        foundation=replace(foundation, model_factory=FakeHarnessModelFactory()),
        v3_background_runtime_enabled=True,
    )
    app = create_app(dependencies)
    with TestClient(app) as background_client:
        created = background_client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_bg_runtime",
                "project_id": "proj_001",
                "objective": "Capture the user's design goal",
            },
        )
        assert created.status_code == 200

        message = background_client.post(
            "/v3/sessions/sess_bg_runtime/messages",
            json={"message": "Please track extracting the design goals as a task."},
        )
        assert message.status_code == 200
        assert message.json()["outputs"] == []

        status = _wait_for_background_runtime(background_client)

        assert status["running"] is True
        assert status["worker_id"] == "host-api:background-runtime"
        workspace = background_client.get(
            "/v3/sessions/sess_bg_runtime/workspace"
        ).json()
        assert (
            workspace["conversation"][1]["content"]
            == "Created task task_llm_001 and captured the goal."
        )
        with dependencies.v3_repository_scope(mode="read") as repositories:
            signals = [
                signal.to_dict()
                for signal in repositories.runtime_signals.list_by_session(
                    "sess_bg_runtime"
                )
            ]
        assert signals[0]["status"] == "completed"
        assert signals[0]["claimed_by"] == "host-api:background-runtime"


def test_v3_background_runtime_tick_does_not_block_event_loop() -> None:
    order: list[str] = []

    class FakeRuntimeSignals:
        def list_claimable_session_ids(self) -> list[str]:
            return ["sess_bg_runtime"]

    class FakeRepositories:
        runtime_signals = FakeRuntimeSignals()

    class BlockingService:
        repositories = FakeRepositories()
        model_factory = object()

        async def run_background_runtime_once(
            self,
            *,
            session_id: str,
            worker_id: str,
            max_signals: int,
            max_steps_per_agent: int,
        ) -> list[dict[str, object]]:
            assert session_id == "sess_bg_runtime"
            assert worker_id == "host-api:background-runtime"
            assert max_signals == 3
            assert max_steps_per_agent == 8
            time.sleep(0.2)
            order.append("runtime_done")
            return [{"status": "completed"}]

    async def run_check() -> None:
        service = V3BackgroundRuntimeService(
            build_service=BlockingService,
            notifier=RuntimeSignalNotifier(),
            enabled=True,
        )

        async def heartbeat() -> None:
            await asyncio.sleep(0.05)
            order.append("event_loop_alive")

        await asyncio.gather(service.run_tick(), heartbeat())

    asyncio.run(run_check())

    assert order == ["event_loop_alive", "runtime_done"]


def test_v3_background_runtime_once_releases_operation_lock_while_scheduler_runs() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session(
            session_id="sess_bg_lock",
            project_id="proj_001",
            title="Background lock",
            objective="Exercise runtime lock release.",
            status=SessionStatus.ACTIVE,
            created_at="2026-05-31T00:00:00+00:00",
            updated_at="2026-05-31T00:00:00+00:00",
        )
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    class Outcome:
        def to_dict(self) -> dict[str, object]:
            return {"status": "completed"}

    class BlockingScheduler:
        async def run_once(
            self,
            session_id: str,
            *,
            max_signals: int,
            max_steps_per_agent: int,
        ) -> list[Outcome]:
            assert session_id == "sess_bg_lock"
            assert max_signals == 1
            assert max_steps_per_agent == 1
            entered.set()
            await release.wait()
            return [Outcome()]

    class LockAwareService(V3HostApiService):
        def _build_scheduler(self, context, *, worker_id, runtime_mode="manual_drain"):
            del context, worker_id, runtime_mode
            return BlockingScheduler()

    service = LockAwareService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    async def run_check() -> None:
        task = asyncio.create_task(
            service.run_background_runtime_once(
                session_id="sess_bg_lock",
                max_signals=1,
                max_steps_per_agent=1,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        acquired = service.operation_lock.acquire(blocking=False)
        assert acquired is True
        service.operation_lock.release()
        release.set()
        assert await task == [{"status": "completed"}]

    asyncio.run(run_check())


def test_v3_drain_runtime_releases_operation_lock_while_scheduler_runs() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session(
            session_id="sess_drain_lock",
            project_id="proj_001",
            title="Drain lock",
            objective="Exercise drain lock release.",
            status=SessionStatus.ACTIVE,
            created_at="2026-05-31T00:00:00+00:00",
            updated_at="2026-05-31T00:00:00+00:00",
        )
    )
    entered = threading.Event()
    release = threading.Event()
    result_holder: dict[str, object] = {}

    class LockAwareService(V3HostApiService):
        def _drain_pending_agent_signals(self, *args, **kwargs):
            del args, kwargs
            entered.set()
            assert release.wait(timeout=2)
            return []

    service = LockAwareService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    def run_drain() -> None:
        result_holder["result"] = service.drain_runtime(
            session_id="sess_drain_lock",
            max_signals=1,
            max_steps_per_agent=1,
        )

    thread = threading.Thread(target=run_drain)
    thread.start()
    assert entered.wait(timeout=1)
    acquired = service.operation_lock.acquire(blocking=False)
    assert acquired is True
    service.operation_lock.release()
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    result = result_holder["result"]
    assert result.status == "completed"


def test_v3_blocking_provider_does_not_hold_sqlite_write_transaction(
    monkeypatch,
) -> None:
    client, foundation = _build_client(monkeypatch)
    del client
    entered = threading.Event()
    release = threading.Event()
    dependencies = HostApiDependencies(
        foundation=replace(
            foundation,
            model_factory=BlockingHarnessModelFactory(entered, release),
        )
    )
    drain_result: dict[str, object] = {}
    write_result: dict[str, object] = {}

    with TestClient(create_app(dependencies)) as scoped_client:
        assert scoped_client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_provider_blocked",
                "project_id": "proj_001",
                "objective": "Block inside the provider.",
            },
        ).status_code == 200
        assert scoped_client.post(
            "/v3/sessions/sess_provider_blocked/messages",
            json={"message": "Track this request."},
        ).status_code == 200

        drain_thread = threading.Thread(
            target=lambda: drain_result.setdefault(
                "response",
                scoped_client.post(
                    "/v3/sessions/sess_provider_blocked/runtime/drain",
                    json={},
                ),
            )
        )
        drain_thread.start()
        assert entered.wait(timeout=2)

        write_thread = threading.Thread(
            target=lambda: write_result.setdefault(
                "response",
                scoped_client.post(
                    "/v3/sessions",
                    json={
                        "session_id": "sess_concurrent_short_write",
                        "project_id": "proj_001",
                        "objective": "Must commit while the provider is blocked.",
                    },
                ),
            )
        )
        write_thread.start()
        write_thread.join(timeout=1)
        write_completed_before_provider_release = not write_thread.is_alive()
        release.set()
        write_thread.join(timeout=5)
        drain_thread.join(timeout=5)

    assert write_completed_before_provider_release is True
    assert not write_thread.is_alive()
    assert not drain_thread.is_alive()
    assert write_result["response"].status_code == 200
    assert drain_result["response"].status_code == 200


def test_v3_background_runtime_runs_teammate_and_master_followup_without_manual_drain(
    monkeypatch,
    tmp_path: Path,
    request,
) -> None:
    client, foundation = _build_client(monkeypatch)
    del client
    repository_provider = SQLiteRepositoryProvider(
        str(tmp_path / "background-runtime.sqlite3")
    )
    repository_scope = repository_provider.connection_scope()
    v3_repositories = repository_scope.__enter__().repositories
    request.addfinalizer(
        lambda: repository_scope.__exit__(None, None, None)
    )
    model_factory = FakeEngineHarnessModelFactory()
    dependencies = HostApiDependencies(
        foundation=replace(foundation, model_factory=model_factory),
        v3_repository_provider=repository_provider,
        v3_background_runtime_enabled=True,
    )
    app = create_app(dependencies)
    with TestClient(app) as background_client:
        created = background_client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_bg_v3_engines",
                "project_id": "proj_001",
                "objective": "Evaluate a thermostability candidate and publish the final report",
            },
        )
        assert created.status_code == 200
        _seed_v3_execution_artifact(v3_repositories, "sess_bg_v3_engines")
        lane = background_client.post(
            "/v3/lanes",
            json={
                "session_id": "sess_bg_v3_engines",
                "lane_id": "lane_bg_v3_engines",
                "name": "background engine lane",
                "cwd": "/tmp/openzyme-bg-v3-engines",
            },
        )
        assert lane.status_code == 200

        research_task = background_client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_bg_v3_engines",
                "task_id": "task_research_v3",
                "subject": "Collect evidence",
                "description": "Collect papers for the scaffold family.",
                "kind": "research",
                "lane_id": "lane_bg_v3_engines",
            },
        )
        assert research_task.status_code == 200
        research = background_client.post(
            "/v3/sessions/sess_bg_v3_engines/messages",
            json={"message": "Run the research task.", "task_id": "task_research_v3"},
        )
        assert research.status_code == 200
        assert research.json()["outputs"] == []
        assert "v3_teammate_loop:researcher" not in model_factory.invokers

        research_workspace, event_text, status, _ = _wait_for_v3_background_workspace(
            background_client,
            session_id="sess_bg_v3_engines",
            repositories=v3_repositories,
            is_ready=lambda workspace, _events, _status: (
                "deep_research" in workspace["capabilities"]
                and workspace["capabilities"]["deep_research"][0]["status"]
                == "succeeded"
                    and any(
                        item["task"]["task_id"] == "task_research_v3"
                        and item["task"]["status"] == "completed"
                        for item in workspace["task_board"]["items"]
                    )
                    and any(
                        message["role"] == "assistant"
                        and message["content"] == "Research complete."
                        for message in workspace["conversation"]
                    )
                ),
        )
        assert status["running"] is True
        assert status["worker_id"] == "host-api:background-runtime"
        assert "event: signal.claimed" in event_text
        assert "event: signal.completed" in event_text
        assert model_factory.invokers["v3_harness_loop"].calls >= 2
        assert model_factory.invokers["v3_teammate_loop:researcher"].calls >= 2
        assert any(
            message["role"] == "assistant" and message["content"] == "Research complete."
            for message in research_workspace["conversation"]
        )

        execution_task = background_client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_bg_v3_engines",
                "task_id": "task_execution_v3",
                "subject": "Run fpocket",
                "description": "Run fpocket against the candidate structure.",
                "kind": "execution",
                "lane_id": "lane_bg_v3_engines",
            },
        )
        assert execution_task.status_code == 200
        master_calls_before_execution = model_factory.invokers["v3_harness_loop"].calls
        execution = background_client.post(
            "/v3/sessions/sess_bg_v3_engines/messages",
            json={
                "message": "Run the execution task.",
                "task_id": "task_execution_v3",
            },
        )
        assert execution.status_code == 200
        assert execution.json()["outputs"] == []

        execution_workspace, event_text, status, resolved_approvals = (
            _wait_for_v3_background_workspace(
                background_client,
                session_id="sess_bg_v3_engines",
                repositories=v3_repositories,
                is_ready=lambda workspace, _events, _status: (
                    "execution" in workspace["capabilities"]
                    and workspace["capabilities"]["execution"][0]["status"]
                    == "succeeded"
                    and bool(workspace["artifacts"])
                    and any(
                        item["task"]["task_id"] == "task_execution_v3"
                        and item["task"]["status"] == "completed"
                        for item in workspace["task_board"]["items"]
                    )
                ),
            )
        )
        assert resolved_approvals
        assert all(
            v3_repositories.approvals.get(approval_id).status.value == "approved"
            for approval_id in resolved_approvals
        )
        assert sum(
            signal.status.value == "completed"
            and signal.claimed_by == "host-api:background-runtime"
            for signal in v3_repositories.runtime_signals.list_by_session(
                "sess_bg_v3_engines"
            )
        ) >= 3
        assert model_factory.invokers["v3_harness_loop"].calls > master_calls_before_execution
        assert model_factory.invokers["v3_teammate_loop:executor"].calls >= 3
        executor_projection = next(
            agent
            for agent in execution_workspace["delegation"]["agents"]
            if agent["agent"]["role"] == "executor"
        )
        assert executor_projection["latest_signal_reason"] is not None
        assert isinstance(executor_projection["pending_signal_count"], int)

        reporting_task = background_client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_bg_v3_engines",
                "task_id": "task_report_v3",
                "subject": "Publish report",
                "description": "Publish the integrated workspace report.",
                "kind": "reporting",
                "lane_id": "lane_bg_v3_engines",
            },
        )
        assert reporting_task.status_code == 200
        reporting = background_client.post(
            "/v3/sessions/sess_bg_v3_engines/messages",
            json={
                "message": "Publish the final report.",
                "task_id": "task_report_v3",
            },
        )
        assert reporting.status_code == 200, reporting.text
        assert reporting.json()["outputs"] == []

        final_workspace, event_text, status, _ = _wait_for_v3_background_workspace(
            background_client,
            session_id="sess_bg_v3_engines",
            is_ready=lambda workspace, _events, _status: (
                bool(workspace["reports"])
                and workspace["reports"][0]["status"] == "ready"
                and any(
                    item["task"]["task_id"] == "task_report_v3"
                    and item["task"]["status"] == "completed"
                    for item in workspace["task_board"]["items"]
                )
            ),
        )
        assert status["running"] is True
        assert "event: report.generated" in event_text
        assert model_factory.invokers["v3_teammate_loop:reporter"].calls >= 3
        assert {item["task"]["kind"] for item in final_workspace["task_board"]["items"]} >= {
            "research",
            "execution",
            "reporting",
        }
        assert {"researcher", "executor", "reporter"} <= {
            item["agent"]["role"] for item in final_workspace["delegation"]["agents"]
        }


def test_v3_background_runtime_debug_exposes_model_factory_disabled_reason(
    monkeypatch,
) -> None:
    client, foundation = _build_client(monkeypatch, with_model_factory=False)
    del client
    app = create_app(
        HostApiDependencies(
            foundation=foundation,
            v3_background_runtime_enabled=True,
        )
    )
    with TestClient(app) as background_client:
        status = background_client.get("/debug/v3-runtime")

    assert status.status_code == 200
    payload = status.json()
    assert payload["enabled"] is True
    assert payload["running"] is False
    assert payload["disabled_reason"] == "model_factory unavailable"


def test_v3_master_agents_and_signals_are_session_scoped() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeEchoHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(project_id="proj_001", objective="A", session_id="sess_a")
    service.create_session(project_id="proj_001", objective="B", session_id="sess_b")

    service.post_message(session_id="sess_a", message="Plan A.")
    service.post_message(session_id="sess_b", message="Plan B.")

    agent_a = repositories.agents.get("sess_a", "agent:master")
    agent_b = repositories.agents.get("sess_b", "agent:master")
    assert agent_a is not None
    assert agent_b is not None
    assert agent_a.member_id != agent_b.member_id
    assert [
        signal.agent_id
        for signal in repositories.runtime_signals.list_pending_by_session("sess_a")
    ] == ["agent:master"]
    assert [
        signal.agent_id
        for signal in repositories.runtime_signals.list_pending_by_session("sess_b")
    ] == ["agent:master"]

    drained_a = service.drain_runtime(session_id="sess_a")
    assert drained_a.status == "completed"
    assert [signal.status.value for signal in repositories.runtime_signals.list_by_session("sess_a")] == ["completed"]
    assert [signal.status.value for signal in repositories.runtime_signals.list_by_session("sess_b")] == ["pending"]
    assert repositories.agents.get("sess_a", "agent:master").member_id == agent_a.member_id
    assert repositories.agents.get("sess_b", "agent:master").member_id == agent_b.member_id

    drained_b = service.drain_runtime(session_id="sess_b")
    assert drained_b.status == "completed"
    assert [signal.status.value for signal in repositories.runtime_signals.list_by_session("sess_b")] == ["completed"]
    assert [message.payload_ref for message in repositories.inbox.list_by_session("sess_a")] != [
        message.payload_ref for message in repositories.inbox.list_by_session("sess_b")
    ]


def test_v3_runtime_drain_claims_master_signal_and_runs_master_loop() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeEchoHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Run the master via scheduler.",
        session_id="sess_master_claim",
    )
    posted = service.post_message(
        session_id="sess_master_claim",
        message="Start planning.",
    )
    assert posted.outputs == ()

    drained = service.drain_runtime(session_id="sess_master_claim")

    assert drained.status == "completed"
    assert drained.outputs == ("Planning started.",)
    signals = repositories.runtime_signals.list_by_session("sess_master_claim")
    assert len(signals) == 1
    assert signals[0].status.value == "completed"
    assert signals[0].claimed_by == "host-api:runtime-drain"


def test_v3_runtime_replay_extends_sanitized_trace_events_without_duplicates() -> None:
    repositories = _build_v3_engine_repositories()
    event_store = V3EventStore()
    service = V3HostApiService(
        repositories=repositories,
        event_store=event_store,
    )
    service.create_session(
        project_id="proj_001",
        objective="Replay persisted trace events.",
        session_id="sess_trace_replay",
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="llmtrace_replay_001",
            session_id="sess_trace_replay",
            invocation_id=None,
            document_kind="llm_trace_step",
            payload={
                "trace_id": "llmtrace_replay_001",
                "actor_ref": "harness",
                "actor_kind": "master",
                "display_name": "OpenZyme",
                "role": "master",
                "call_index": 1,
                "created_at": "2026-04-21T00:00:02+00:00",
                "response_text": "I will inspect the task.",
                "initial_prompt": {"instructions": "private prompt"},
                "restore_context": {"memory_summary": "private memory"},
                "tool_calls": [
                    {
                        "call_id": "call_001",
                        "tool_name": "task.get",
                        "task_id": "task_001",
                        "lane_id": "lane_001",
                        "args_public": {
                            "task_id": "task_001",
                            "secret_token": "abc123",
                            "host_path": "/home/user/private/input.pdb",
                            "storage_uri": "storage://private/input.pdb",
                        },
                        "content": "private tool result",
                    }
                ],
            },
            created_at="2026-04-21T00:00:02+00:00",
            updated_at="2026-04-21T00:00:02+00:00",
        )
    )

    first = service.drain_runtime(session_id="sess_trace_replay")
    second = service.drain_runtime(session_id="sess_trace_replay")

    first_trace_events = [
        event
        for event in first.events
        if event["event_type"] == "llm.response.created"
    ]
    second_trace_events = [
        event
        for event in second.events
        if event["event_type"] == "llm.response.created"
    ]
    stored_trace_events = [
        event
        for event in event_store.list("sess_trace_replay")
        if event["event_type"] == "llm.response.created"
    ]
    assert len(first_trace_events) == 1
    assert second_trace_events == []
    assert len(stored_trace_events) == 1
    payload = first_trace_events[0]["payload"]
    assert payload["projection_schema_version"] == "v1"
    assert payload["tool_calls"][0]["args_public"]["secret_token"] == "[redacted]"
    assert payload["tool_calls"][0]["args_public"]["host_path"] == "[redacted]"
    assert payload["tool_calls"][0]["args_public"]["storage_uri"] == "[redacted]"
    payload_text = json.dumps(payload, sort_keys=True)
    assert "initial_prompt" not in payload_text
    assert "private prompt" not in payload_text
    assert "private memory" not in payload_text
    assert "private tool result" not in payload_text
    assert "/home/user/private" not in payload_text
    assert "storage://private" not in payload_text


def test_v3_resolve_unassigned_approval_enqueues_master_wakeup() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Resolve generic approval.",
        session_id="sess_approval_master",
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_master",
            session_id="sess_approval_master",
            task_id=None,
            lane_id=None,
            kind="user_confirmation",
            requested_action="Confirm next step.",
            status=ApprovalRequestStatus.PENDING,
            request_ref=None,
            resolution_ref=None,
            created_at="2026-05-03T15:59:10+00:00",
        )
    )

    result = service.resolve_approval(
        "appr_master", decision="approved", actor_ref="tester"
    )

    assert result.status == "completed"
    assert result.outputs == ()
    assert model_factory.invokers == {}
    signals = repositories.runtime_signals.list_by_session("sess_approval_master")
    assert len(signals) == 1
    assert signals[0].agent_id == "agent:master"
    assert signals[0].reason.value == "approval_resolved"
    assert signals[0].source_ref == "appr_master"


def test_v3_resolve_sdk_controlled_operation_uses_continuation_not_agent_wakeup(tmp_path: Path) -> None:
    repositories = _build_v3_engine_repositories()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=FakeHarnessModelFactory(),
    )
    service.create_session(
        project_id="proj_001",
        objective="Resolve SDK controlled operation approval.",
        session_id="sess_sdk_approval",
    )
    agent = AgentMember(
        agent_id="agent:executor:sdk_approval",
        session_id="sess_sdk_approval",
        lane_id=None,
        task_id=None,
        name="Executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-03T15:59:00+00:00",
        updated_at="2026-05-03T15:59:00+00:00",
        member_id="member_executor",
    )
    repositories.agents.save(agent)
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:s10",
            image_digest="sha256:s10",
        )
    )
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=tmp_path / "workspaces",
    ).create_or_get(session_id="sess_sdk_approval", agent_member_id="member_executor")
    run = SandboxRunRecord(
        sandbox_run_id="srun_sdk_approval",
        session_id="sess_sdk_approval",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=("python", "src/s10.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        source_snapshot_artifact_id=None,
        source_tree_digest="sha256:source",
        changed_files_summary={},
        created_at="2026-05-03T15:59:01+00:00",
        updated_at="2026-05-03T15:59:01+00:00",
    )
    repositories.sandbox_runs.save(run)
    approval = ApprovalRequest(
        approval_id="appr_sdk_controlled",
        session_id="sess_sdk_approval",
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Approve fake SDK operation.",
        status=ApprovalRequestStatus.PENDING,
        request_ref="op_sdk_controlled",
        resolution_ref=None,
        created_at="2026-05-03T15:59:02+00:00",
    )
    repositories.approvals.save(approval)
    operation = ControlledOperation(
        operation_id="op_sdk_controlled",
        session_id="sess_sdk_approval",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=run.sandbox_run_id,
        logical_operation_key="fake.controlled",
        operation_digest="sha256:operation",
        params_digest="sha256:params",
        backend_category="provider_http",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.PENDING.value,
        route_reason="s10_generic_backend_category",
        expected_outputs_summary={},
        resource_estimate={},
        created_at="2026-05-03T15:59:03+00:00",
        updated_at="2026-05-03T15:59:03+00:00",
    )
    repositories.controlled_operations.save(operation)
    continuation = ContinuationState(
        continuation_id="srun_sdk_approval:op_sdk_controlled",
        session_id="sess_sdk_approval",
        operation_id=operation.operation_id,
        sandbox_run_id=run.sandbox_run_id,
        approval_id=approval.approval_id,
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at="2026-05-03T15:59:04+00:00",
        updated_at="2026-05-03T15:59:04+00:00",
    )
    repositories.continuation_states.save(continuation)

    pending_projection = service.workspace("sess_sdk_approval")["pending_approvals"][0]
    assert pending_projection["approval_id"] == approval.approval_id
    assert pending_projection["operation"]["operation_id"] == operation.operation_id
    assert pending_projection["operation"]["logical_operation_key"] == "fake.controlled"
    assert pending_projection["sandbox_run"]["sandbox_run_id"] == run.sandbox_run_id

    result = service.resolve_approval(
        approval.approval_id,
        decision="approved",
        actor_ref="tester",
    )

    assert result.status == "completed"
    assert repositories.runtime_signals.list_by_session("sess_sdk_approval") == []
    resolved = repositories.approvals.get(approval.approval_id)
    assert resolved is not None
    assert resolved.status is ApprovalRequestStatus.APPROVED
    updated_operation = repositories.controlled_operations.get(operation.operation_id)
    assert updated_operation is not None
    assert updated_operation.approval_state == "approved"
    assert updated_operation.status is ControlledOperationStatus.WAITING_APPROVAL
    updated_continuation = repositories.continuation_states.get(continuation.continuation_id)
    assert updated_continuation is not None
    assert updated_continuation.status is ContinuationStateStatus.APPROVED
    sdk_projection = result.workspace["capabilities"]["sdk_supervisor"][0]
    assert sdk_projection["operation_id"] == operation.operation_id
    assert sdk_projection["approval_state"] == "approved"
    assert sdk_projection["backend_category"] == "provider_http"
    assert any(
        item["event_type"] == "sdk_controlled_operation.updated"
        and item["payload"]["operation_id"] == operation.operation_id
        for item in result.workspace["activity_feed"]
    )
    assert any(
        event["event_type"] == "sdk_controlled_operation.approval_resolved"
        for event in result.events
    )

    duplicate = service.resolve_approval(
        approval.approval_id,
        decision="approved",
        actor_ref="tester",
    )
    assert duplicate.status == "completed"
    assert repositories.runtime_signals.list_by_session("sess_sdk_approval") == []
    duplicate_continuation = repositories.continuation_states.get(
        continuation.continuation_id
    )
    assert duplicate_continuation is not None
    assert duplicate_continuation.status is ContinuationStateStatus.APPROVED

    reject_approval = replace(
        approval,
        approval_id="appr_sdk_rejected",
        request_ref="op_sdk_rejected",
        status=ApprovalRequestStatus.PENDING,
        resolved_at=None,
        created_at="2026-05-03T16:00:02+00:00",
    )
    repositories.approvals.save(reject_approval)
    reject_operation = replace(
        operation,
        operation_id="op_sdk_rejected",
        approval_id=reject_approval.approval_id,
        approval_state=ApprovalRequestStatus.PENDING.value,
        status=ControlledOperationStatus.WAITING_APPROVAL,
        error_code=None,
        error_summary=None,
        created_at="2026-05-03T16:00:03+00:00",
        updated_at="2026-05-03T16:00:03+00:00",
    )
    repositories.controlled_operations.save(reject_operation)
    reject_continuation = replace(
        continuation,
        continuation_id="srun_sdk_approval:op_sdk_rejected",
        operation_id=reject_operation.operation_id,
        approval_id=reject_approval.approval_id,
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at="2026-05-03T16:00:04+00:00",
        updated_at="2026-05-03T16:00:04+00:00",
    )
    repositories.continuation_states.save(reject_continuation)

    rejected = service.resolve_approval(
        reject_approval.approval_id,
        decision="rejected",
        actor_ref="tester",
    )
    duplicate_reject = service.resolve_approval(
        reject_approval.approval_id,
        decision="rejected",
        actor_ref="tester",
    )
    assert rejected.status == "completed"
    assert duplicate_reject.status == "completed"
    updated_reject_operation = repositories.controlled_operations.get(
        reject_operation.operation_id
    )
    assert updated_reject_operation is not None
    assert updated_reject_operation.status is ControlledOperationStatus.FAILED
    assert updated_reject_operation.error_code == "approval_rejected"
    assert repositories.runtime_signals.list_by_session("sess_sdk_approval") == []
    try:
        service.resolve_approval(
            reject_approval.approval_id,
            decision="approved",
            actor_ref="tester",
        )
    except ValueError as exc:
        assert "approval_state_conflict" in str(exc)
    else:
        raise AssertionError("expected approval_state_conflict")


def test_v3_recover_abandoned_sdk_continuation_fails_closed(tmp_path: Path) -> None:
    repositories = _build_v3_engine_repositories()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=FakeHarnessModelFactory(),
    )
    service.create_session(
        project_id="proj_001",
        objective="Recover abandoned SDK continuation.",
        session_id="sess_sdk_recovery",
    )
    agent = AgentMember(
        agent_id="agent:executor:sdk_recovery",
        session_id="sess_sdk_recovery",
        lane_id=None,
        task_id=None,
        name="Executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-03T15:59:00+00:00",
        updated_at="2026-05-03T15:59:00+00:00",
        member_id="member_executor_recovery",
    )
    repositories.agents.save(agent)
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:s10",
            image_digest="sha256:s10",
        )
    )
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=tmp_path / "workspaces",
    ).create_or_get(
        session_id="sess_sdk_recovery",
        agent_member_id="member_executor_recovery",
    )
    run = SandboxRunRecord(
        sandbox_run_id="srun_sdk_recovery",
        session_id="sess_sdk_recovery",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=("python", "src/s10.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        source_snapshot_artifact_id=None,
        source_tree_digest="sha256:source",
        changed_files_summary={},
        created_at="2026-05-03T16:10:01+00:00",
        updated_at="2026-05-03T16:10:01+00:00",
    )
    repositories.sandbox_runs.save(run)
    approval = ApprovalRequest(
        approval_id="appr_sdk_recovery",
        session_id="sess_sdk_recovery",
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Approve fake SDK operation.",
        status=ApprovalRequestStatus.APPROVED,
        request_ref="op_sdk_recovery",
        resolution_ref=None,
        created_at="2026-05-03T16:10:02+00:00",
        resolved_at="2026-05-03T16:10:03+00:00",
    )
    repositories.approvals.save(approval)
    operation = ControlledOperation(
        operation_id="op_sdk_recovery",
        session_id="sess_sdk_recovery",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=run.sandbox_run_id,
        logical_operation_key="fake.recovery",
        operation_digest="sha256:operation",
        params_digest="sha256:params",
        backend_category="provider_http",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.APPROVED.value,
        route_reason="s10_generic_backend_category",
        expected_outputs_summary={},
        resource_estimate={},
        created_at="2026-05-03T16:10:04+00:00",
        updated_at="2026-05-03T16:10:04+00:00",
    )
    repositories.controlled_operations.save(operation)
    continuation = ContinuationState(
        continuation_id="srun_sdk_recovery:op_sdk_recovery",
        session_id="sess_sdk_recovery",
        operation_id=operation.operation_id,
        sandbox_run_id=run.sandbox_run_id,
        approval_id=approval.approval_id,
        status=ContinuationStateStatus.APPROVED,
        created_at="2026-05-03T16:10:05+00:00",
        updated_at="2026-05-03T16:10:05+00:00",
    )
    repositories.continuation_states.save(continuation)

    events = service.recover_abandoned_sdk_continuations(actor_ref="startup")

    recovered_operation = repositories.controlled_operations.get(operation.operation_id)
    recovered_continuation = repositories.continuation_states.get(
        continuation.continuation_id
    )
    recovered_run = repositories.sandbox_runs.get(run.sandbox_run_id)
    assert recovered_operation is not None
    assert recovered_operation.status is ControlledOperationStatus.RECOVERY_FAILED
    assert recovered_operation.error_code == "operation_recovery_failed"
    assert recovered_continuation is not None
    assert recovered_continuation.status is ContinuationStateStatus.RECOVERY_FAILED
    assert recovered_continuation.error_code == "operation_recovery_failed"
    assert recovered_run is not None
    assert recovered_run.status is SandboxRunStatus.FAILED
    assert recovered_run.error_code == "operation_recovery_failed"
    assert repositories.approvals.get(approval.approval_id) == approval
    assert repositories.runtime_signals.list_by_session("sess_sdk_recovery") == []
    assert any(
        event["event_type"] == "sdk_controlled_operation.recovery_failed"
        for event in events
    )


def test_hpc_operation_failed_after_approval_returns_to_executor_for_diagnostic() -> (
    None
):
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_hpc_diag",
            "proj_001",
            "HPC diagnostic",
            "Diagnose approved execution failure.",
        )
    )
    repositories.tasks.seed_fixture(
        Task.create(
            "task_hpc_diag",
            "sess_hpc_diag",
            "Run fpocket",
            "Run fpocket and report failures.",
            kind="execution",
            status=TaskStatus.BLOCKED,
            assigned_ref="agent:executor:hpc_diag",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:executor:hpc_diag",
            session_id="sess_hpc_diag",
            lane_id=None,
            task_id="task_hpc_diag",
            name="executor",
            role="executor",
            status=AgentMemberStatus.BLOCKED,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="blocked",
            current_correlation_id="corr_hpc_diag",
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_hpc_diag",
            session_id="sess_hpc_diag",
            task_id="task_hpc_diag",
            lane_id=None,
            kind="execution_pipeline_plan",
            requested_action="Approve fpocket.",
            status=ApprovalRequestStatus.PENDING,
            request_ref="artifact://approvals/appr_hpc_diag.json",
            resolution_ref=None,
            created_at="2026-05-03T15:59:10+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_hpc_diag",
            session_id="sess_hpc_diag",
            task_id="task_hpc_diag",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.WAITING_APPROVAL,
            input_ref="eng_in_hpc_diag",
            output_ref=None,
            approval_id="appr_hpc_diag",
            idempotency_key="hpc_diag",
            started_at="2026-05-03T15:59:10+00:00",
        )
    )
    registry = EngineRegistry()
    registry.register(FailedHpcExecutionEngine(repositories))
    model_factory = DiagnosticExecutorModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        engine_registry=registry,
        model_factory=model_factory,
        bio_research_service=None,
        research_adapter=None,
    )

    result = service.resolve_approval(
        "appr_hpc_diag", decision="approved", actor_ref="tester"
    )

    assert result.status == "completed"
    assert result.outputs == ()
    assert model_factory.invoker.calls == 0
    assert model_factory.master_calls == 0
    assert repositories.runtime_signals.list_pending_by_session("sess_hpc_diag")
    task = repositories.tasks.get("task_hpc_diag")
    assert task is not None
    assert task.status is TaskStatus.BLOCKED

    drained = service.drain_runtime(session_id="sess_hpc_diag")

    assert drained.status == "failed"
    assert model_factory.invoker.calls == 1
    assert model_factory.master_calls == 1
    assert drained.outputs == (
        "The approved fpocket task failed at the HPC runner boundary. "
        "The execution task is marked failed with failure_ref engine:inv_hpc_diag.",
    )
    assert "Execution failed in the approved pipeline" not in " ".join(drained.outputs)
    task = repositories.tasks.get("task_hpc_diag")
    assert task is not None
    assert task.status is TaskStatus.FAILED
    assert task.failure_ref == "engine:inv_hpc_diag"
    assert task.failure_summary is not None
    assert "INPUT_OR_ENTRYPOINT_MISSING" in task.failure_summary
    assistant_messages = [
        message
        for message in repositories.inbox.list_by_session("sess_hpc_diag")
        if message.message_type == "assistant_message" and message.recipient == "user"
    ]
    assert len(assistant_messages) == 1


def _seed_v3_execution_artifact(
    repositories: CoreRepositories, session_id: str
) -> None:
    lines = []
    serial = 1
    for residue_index in range(1, 11):
        for atom_index, atom_name in enumerate(("N", "CA", "C", "O", "CB")):
            lines.append(
                f"ATOM  {serial:5d} {atom_name:<4} ALA A{residue_index:4d}    "
                f"{float(residue_index):8.3f}{float(atom_index):8.3f}{0.0:8.3f}  1.00 20.00           C"
            )
            serial += 1
    content = "\n".join(lines) + "\nEND\n"
    Path("/tmp/v3_input_structure.pdb").write_text(content, encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_v3_structure",
            session_id=session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/v3_input_structure.pdb",
            relative_path="v3_input_structure.pdb",
            title="v3_input_structure.pdb",
            description=None,
            metadata={
                "source": "test_fixture",
                "format": "pdb",
                "content_digest": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
            },
            created_at="2026-04-20T12:00:03+00:00",
        )
    )


def _build_v3_echo_llm_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    client, foundation = _build_client(monkeypatch)
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(
                        foundation, model_factory=FakeEchoHarnessModelFactory()
                    ),
                )
            )
        ),
        foundation,
    )


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
        json={
            "message": "Start by planning the literature extraction.",
            "task_id": "task_v3_001",
        },
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["outputs"] == []
    assert {event["event_type"] for event in payload["events"]} >= {
        "conversation.user_message",
        "signal.queued",
    }

    drained = client.post("/v3/sessions/sess_v3_001/runtime/drain", json={})
    assert drained.status_code == 200
    payload = drained.json()
    assert payload["outputs"] == ["Planning started."]
    assert {event["event_type"] for event in payload["events"]} >= {
        "llm.response.created",
        "message.sent",
    }
    assert payload["workspace"]["inbox"]
    assert (
        payload["workspace"]["agent_traces"]["harness"][0]["response_text"]
        == "Planning started."
    )

    events = client.get("/v3/sessions/sess_v3_001/events?replay=1")
    assert events.status_code == 200
    assert "event: conversation.user_message" in events.text
    assert "event: llm.response.created" in events.text

    updated = client.patch("/v3/tasks/task_v3_001", json={"status": "in_progress"})
    assert updated.status_code == 200
    assert updated.json()["task"]["status"] == "in_progress"


def test_v3_pressure_user_message_triggers_budget_compaction_via_message_loop(
    monkeypatch,
) -> None:
    _clear_context_budget_env(monkeypatch)
    model_factory = PressureHarnessModelFactory(
        [{"content": "pressure message handled", "tool_calls": []}],
        context_window_tokens=105_000,
    )
    client, repositories, model_factory = _build_v3_pressure_client(
        monkeypatch, model_factory
    )

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_pressure_compact",
            "project_id": "proj_001",
            "objective": "Pressure test prompt compaction",
        },
    )
    assert created.status_code == 200

    message = client.post(
        "/v3/sessions/sess_pressure_compact/messages",
        json={"message": "正常用户消息：" + ("x" * 320_000)},
    )
    assert message.status_code == 200
    assert message.json()["outputs"] == []

    drained = client.post(
        "/v3/sessions/sess_pressure_compact/runtime/drain",
        json={"max_steps_per_agent": 1},
    )
    assert drained.status_code == 200
    payload = drained.json()
    event_types = [event["event_type"] for event in payload["events"]]

    assert payload["status"] == "completed"
    assert payload["outputs"] == ["pressure message handled"]
    assert len(model_factory.invokers["v3_harness_loop"].calls) == 1
    assert "llm.context_budget.warning" in event_types
    assert "llm.context_budget.after_compaction" in event_types
    assert "llm.context_budget.exceeded" not in event_types
    assert event_types.index("llm.context_budget.after_compaction") < event_types.index(
        "llm.response.created"
    )
    prompt_compactions = [
        memory
        for memory in repositories.memory.list_by_session("sess_pressure_compact")
        if memory.kind.value == "compaction"
        and memory.source_range == "auto:prompt_budget"
    ]
    assert prompt_compactions
    assert "auto_compact before model call" in prompt_compactions[-1].summary


def test_v3_prompt_budget_compaction_cuts_off_prior_conversation_for_later_drains(
    monkeypatch,
) -> None:
    _clear_context_budget_env(monkeypatch)
    large_marker = "large-round-one-marker"
    model_factory = PressureHarnessModelFactory(
        [
            {"content": f"round {round_index} handled", "tool_calls": []}
            for round_index in range(1, 6)
        ],
        context_window_tokens=105_000,
    )
    client, repositories, model_factory = _build_v3_pressure_client(
        monkeypatch, model_factory
    )
    session_id = "sess_pressure_multiround"

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": session_id,
            "project_id": "proj_001",
            "objective": "Pressure test prompt compaction reuse",
        },
    )
    assert created.status_code == 200

    message = client.post(
        f"/v3/sessions/{session_id}/messages",
        json={"message": large_marker + ":" + ("x" * 320_000)},
    )
    assert message.status_code == 200
    drained = client.post(
        f"/v3/sessions/{session_id}/runtime/drain",
        json={"max_steps_per_agent": 1},
    )
    assert drained.status_code == 200
    first_payload = drained.json()
    first_event_types = [event["event_type"] for event in first_payload["events"]]
    first_warning = [
        event["payload"]
        for event in first_payload["events"]
        if event["event_type"] == "llm.context_budget.warning"
    ][-1]
    first_after_compaction = [
        event["payload"]
        for event in first_payload["events"]
        if event["event_type"] == "llm.context_budget.after_compaction"
    ][-1]

    assert first_payload["outputs"] == ["round 1 handled"]
    assert "llm.response.created" in first_event_types
    assert first_warning["action"] == "auto_compact"
    assert first_after_compaction["ratio"] < first_warning["ratio"]

    invoker = model_factory.invokers["v3_harness_loop"]
    for round_index in range(2, 6):
        message = client.post(
            f"/v3/sessions/{session_id}/messages",
            json={"message": f"small round {round_index}"},
        )
        assert message.status_code == 200
        drained = client.post(
            f"/v3/sessions/{session_id}/runtime/drain",
            json={"max_steps_per_agent": 1},
        )
        assert drained.status_code == 200
        payload = drained.json()
        event_types = [event["event_type"] for event in payload["events"]]

        assert payload["outputs"] == [f"round {round_index} handled"]
        assert "llm.response.created" in event_types
        assert "llm.context_budget.after_compaction" not in event_types
        assert "llm.context_budget.exceeded" not in event_types
        provider_prompt = "\n".join(
            _message_content(message)
            for message in invoker.calls[-1]["messages"]
        )
        assert large_marker not in provider_prompt
        assert f"small round {round_index}" in provider_prompt
        prompt_compactions = [
            memory
            for memory in repositories.memory.list_by_session(session_id)
            if memory.kind.value == "compaction"
            and memory.source_range == "auto:prompt_budget"
        ]
        assert len(prompt_compactions) == 1

    assert len(invoker.calls) == 5


def test_v3_glm51_default_window_budget_boundaries_via_message_loop(
    monkeypatch,
) -> None:
    _clear_context_budget_env(monkeypatch)
    cases = [
        ("below_warn", 250_000, "ok"),
        ("warn", 360_000, "warn"),
        ("auto", 400_000, "auto_compact"),
    ]

    for suffix, message_size, expected_action in cases:
        model_factory = PressureHarnessModelFactory(
            [{"content": f"{suffix} handled", "tool_calls": []}],
            model="glm-5.1",
            context_window_tokens=None,
            default_output_tokens=None,
        )
        client, repositories, model_factory = _build_v3_pressure_client(
            monkeypatch, model_factory
        )
        session_id = f"sess_glm51_budget_{suffix}"

        created = client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "proj_001",
                "objective": f"Pressure test GLM-5.1 default boundary {suffix}",
            },
        )
        assert created.status_code == 200

        message = client.post(
            f"/v3/sessions/{session_id}/messages",
            json={"message": "正常窗口边界测试：" + ("x" * message_size)},
        )
        assert message.status_code == 200

        drained = client.post(
            f"/v3/sessions/{session_id}/runtime/drain",
            json={"max_steps_per_agent": 1},
        )
        assert drained.status_code == 200
        payload = drained.json()
        event_types = [event["event_type"] for event in payload["events"]]
        budget_payloads = [
            event["payload"]
            for event in payload["events"]
            if event["event_type"] == "llm.context_budget.warning"
        ]

        assert payload["status"] == "completed"
        assert payload["outputs"] == [f"{suffix} handled"]
        assert "llm.context_budget.exceeded" not in event_types
        assert len(model_factory.invokers["v3_harness_loop"].calls) == 1
        if expected_action == "ok":
            assert budget_payloads == []
            assert "llm.context_budget.after_compaction" not in event_types
            assert not [
                memory
                for memory in repositories.memory.list_by_session(session_id)
                if memory.kind.value == "compaction"
                and memory.source_range == "auto:prompt_budget"
            ]
            continue

        assert budget_payloads
        assert budget_payloads[-1]["model"] == "glm-5.1"
        assert budget_payloads[-1]["context_window_tokens"] == 200_000
        assert budget_payloads[-1]["reserved_output_tokens"] == 65_536
        assert budget_payloads[-1]["action"] == expected_action
        if expected_action == "warn":
            assert 0.80 <= budget_payloads[-1]["ratio"] < 0.85
            assert "llm.context_budget.after_compaction" not in event_types
        else:
            assert 0.85 <= budget_payloads[-1]["ratio"] < 0.90
            assert "llm.context_budget.after_compaction" in event_types
            assert event_types.index(
                "llm.context_budget.after_compaction"
            ) < event_types.index("llm.response.created")
            prompt_compactions = [
                memory
                for memory in repositories.memory.list_by_session(session_id)
                if memory.kind.value == "compaction"
                and memory.source_range == "auto:prompt_budget"
            ]
            assert prompt_compactions
            assert "auto_compact before model call" in prompt_compactions[-1].summary


def test_v3_pressure_large_tool_result_artifactized_via_message_loop(
    monkeypatch,
    tmp_path,
) -> None:
    _clear_context_budget_env(monkeypatch)
    model_factory = PressureHarnessModelFactory(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_large_range",
                        "name": "artifact.range",
                        "args": {
                            "artifact_id": "art_pressure_large_text",
                            "start_line": 1,
                            "end_line": 500,
                        },
                    }
                ],
            },
            {"content": "large observation handled", "tool_calls": []},
        ],
        context_window_tokens=100_000,
    )
    client, repositories, model_factory = _build_v3_pressure_client(
        monkeypatch, model_factory
    )

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_pressure_tool_result",
            "project_id": "proj_001",
            "objective": "Pressure test tool-result artifactization",
        },
    )
    assert created.status_code == 200
    _seed_large_text_artifact(repositories, "sess_pressure_tool_result", tmp_path)

    message = client.post(
        "/v3/sessions/sess_pressure_tool_result/messages",
        json={"message": "Read the large artifact and summarize what matters."},
    )
    assert message.status_code == 200

    drained = client.post(
        "/v3/sessions/sess_pressure_tool_result/runtime/drain",
        json={"max_steps_per_agent": 3},
    )
    assert drained.status_code == 200
    payload = drained.json()
    event_types = [event["event_type"] for event in payload["events"]]
    invoker = model_factory.invokers["v3_harness_loop"]

    assert payload["status"] == "completed"
    assert payload["outputs"] == ["large observation handled"]
    assert len(invoker.calls) == 2
    assert "tool_result.artifactized" in event_types
    assert "llm.context_budget.exceeded" not in event_types
    assert _tool_message_name(invoker.calls[1]["messages"][-1]) == "artifact.range"
    observation_envelope = json.loads(_message_content(invoker.calls[1]["messages"][-1]))
    observation = observation_envelope["payload"]
    assert observation_envelope["ok"] is False
    assert observation["status"] == "tool_result_context_over_budget"
    assert observation["original_tool_ok"] is True
    assert "artifact_id" in observation
    assert "stress-observation-" not in _message_content(invoker.calls[1]["messages"][-1])

    artifacts = [
        artifact
        for artifact in repositories.artifacts.list_by_session(
            "sess_pressure_tool_result"
        )
        if artifact.kind is ArtifactKind.RESULT
        and artifact.relative_path == "tool_results/call_large_range.json"
    ]
    assert len(artifacts) == 1
    assert artifacts[0].artifact_id == observation["artifact_id"]
    document = repositories.engine_documents.get(
        str(dict(artifacts[0].metadata or {})["output_ref"])
    )
    assert document is not None
    assert document.document_kind == "tool_result_full"
    persisted_result = document.payload["tool_result"]
    assert document.payload["original_tool_ok"] is True
    assert "stress-observation-" in persisted_result["content"]


def test_v3_llm_response_event_is_available_before_message_command_finishes() -> None:
    repositories = _build_v3_engine_repositories()
    event_store = V3EventStore()
    model_factory = BlockingTraceModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=event_store,
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        session_id="sess_realtime_trace",
        title="Realtime trace",
        objective="Exercise realtime trace streaming.",
    )
    result_holder: dict[str, object] = {}
    error_holder: dict[str, BaseException] = {}

    service.post_message(
        session_id="sess_realtime_trace",
        message="create a task",
    )

    def _drain_runtime() -> None:
        try:
            result_holder["result"] = service.drain_runtime(
                session_id="sess_realtime_trace",
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            error_holder["error"] = exc

    thread = threading.Thread(target=_drain_runtime)
    thread.start()
    try:
        assert model_factory.entered_second_call.wait(timeout=5)
        realtime_events = event_store.list("sess_realtime_trace")
        trace_events = [
            event
            for event in realtime_events
            if event["event_type"] == "llm.response.created"
        ]
        assert trace_events
        assert (
            trace_events[0]["payload"]["response_text"]
            == "I will create a task before answering."
        )
        assert trace_events[0]["payload"]["tool_calls"][0]["tool_name"] == "task.create"
        assert "result" not in result_holder
    finally:
        model_factory.release_second_call.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    if error_holder:
        raise error_holder["error"]
    completed_events = event_store.list("sess_realtime_trace")
    trace_ids = [
        event["payload"]["trace_id"]
        for event in completed_events
        if event["event_type"] == "llm.response.created"
    ]
    assert len(trace_ids) == len(set(trace_ids))
    assert "result" in result_holder


def test_v3_engine_backed_research_execution_report_draft_loop(monkeypatch) -> None:
    client, v3_repositories, model_factory = _build_v3_engine_llm_client(monkeypatch)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_engines",
            "project_id": "proj_001",
            "objective": "Evaluate a thermostability candidate and publish the final report",
        },
    )
    assert created.status_code == 200
    _seed_v3_execution_artifact(v3_repositories, "sess_v3_engines")
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
    assert research_payload["outputs"] == []
    assert (
        research_payload["workspace"]["task_board"]["items"][0]["task"]["status"]
        == "todo"
    )
    assert "v3_teammate_loop:researcher" not in model_factory.invokers

    research_drain = client.post(
        "/v3/sessions/sess_v3_engines/runtime/drain",
        json={},
    )
    assert research_drain.status_code == 200
    research_payload = research_drain.json()
    assert research_payload["status"] == "completed"
    assert (
        research_payload["workspace"]["task_board"]["items"][0]["task"]["status"]
        == "completed"
    )
    assert (
        research_payload["workspace"]["capabilities"]["deep_research"][0][
            "canonical_summary"
        ]["status"]
        == "completed"
    )
    assert any(
        agent["agent"]["role"] == "researcher"
        for agent in research_payload["workspace"]["delegation"]["agents"]
    )
    research_assistant_messages = [
        message["content"]
        for message in research_payload["workspace"]["conversation"]
        if message["role"] == "assistant"
    ]
    assert "Research complete." in research_payload["outputs"]
    assert "Research complete." in research_assistant_messages

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
    assert execution_payload["status"] == "completed"
    assert execution_payload["outputs"] == []
    execution_item = next(
        item
        for item in execution_payload["workspace"]["task_board"]["items"]
        if item["task"]["task_id"] == "task_execution_v3"
    )
    assert execution_item["task"]["status"] == "todo"

    execution_drain = client.post(
        "/v3/sessions/sess_v3_engines/runtime/drain",
        json={},
    )
    assert execution_drain.status_code == 200
    execution_payload = execution_drain.json()
    assert execution_payload["status"] == "waiting_approval"
    pending = execution_payload["workspace"]["pending_approvals"]
    assert pending[0]["kind"] == "execution_pipeline_plan"
    assert (
        execution_payload["workspace"]["capabilities"]["execution"][0]["status"]
        == "waiting_approval"
    )
    assert execution_payload["outputs"] == []
    assert not any(
        event["event_type"] == "conversation.assistant_message"
        for event in execution_payload["events"]
    )
    assert any(
        agent["agent"]["role"] == "executor"
        for agent in execution_payload["workspace"]["delegation"]["agents"]
    )
    master_calls_before_approval = model_factory.invokers["v3_harness_loop"].calls
    executor_calls_before_approval = model_factory.invokers[
        "v3_teammate_loop:executor"
    ].calls

    approval_id = pending[0]["approval_id"]
    resolved = client.post(
        f"/v3/approvals/{approval_id}/resolve",
        json={"decision": "approved", "actor_ref": "tester"},
    )
    assert resolved.status_code == 200
    resolved_payload = resolved.json()
    assert (
        model_factory.invokers["v3_harness_loop"].calls
        == master_calls_before_approval
    )
    assert (
        model_factory.invokers["v3_teammate_loop:executor"].calls
        == executor_calls_before_approval
    )
    assert resolved_payload["status"] == "completed"
    assert resolved_payload["workspace"]["pending_approvals"] == []
    assert resolved_payload["outputs"] == []

    execution_resume = client.post(
        "/v3/sessions/sess_v3_engines/runtime/drain",
        json={},
    )
    assert execution_resume.status_code == 200
    resolved_payload = execution_resume.json()
    assert (
        model_factory.invokers["v3_harness_loop"].calls
        == master_calls_before_approval + 1
    )
    assert (
        model_factory.invokers["v3_teammate_loop:executor"].calls
        == executor_calls_before_approval + 2
    )
    executor_agent = next(
        agent
        for agent in v3_repositories.agents.list_by_session("sess_v3_engines")
        if agent.role == "executor"
    )
    assert any(
        message.message_type == "delegation_result"
        and message.sender == executor_agent.agent_id
        for message in v3_repositories.inbox.list_by_session("sess_v3_engines")
    )
    assert resolved_payload["status"] == "completed"
    assert resolved_payload["workspace"]["pending_approvals"] == []
    assert (
        resolved_payload["workspace"]["capabilities"]["execution"][0]["status"]
        == "succeeded"
    )
    assert resolved_payload["workspace"]["artifacts"]
    assert any("fpocket found" in output for output in resolved_payload["outputs"])
    assert any("Output artifacts:" in output for output in resolved_payload["outputs"])
    assert not any("Pipeline sandbox completed." in output for output in resolved_payload["outputs"])
    assert (
        "Protocol threads available via protocol.thread"
        in model_factory.invokers["v3_harness_loop"].system_prompts[-1]
    )
    conversation = resolved_payload["workspace"]["conversation"]
    assistant_messages = [
        message["content"] for message in conversation if message["role"] == "assistant"
    ]
    assert not any(
        message == "Execution finished: Pipeline sandbox completed."
        for message in assistant_messages
    )
    assert sum("fpocket found" in message for message in assistant_messages) == 1
    assert not any(
        "Approval resolved. The delegated execution task resumed" in message
        for message in assistant_messages
    )
    assert any(
        agent["agent"]["status"] == "idle"
        for agent in resolved_payload["workspace"]["delegation"]["agents"]
    )

    events = client.get("/v3/sessions/sess_v3_engines/events?replay=1")
    assert events.status_code == 200
    assert "event: engine.invocation.started" in events.text


def test_v3_message_ingress_uses_llm_driver_when_model_factory_is_available(
    monkeypatch,
) -> None:
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
    assert payload["outputs"] == []
    drained = client.post("/v3/sessions/sess_v3_llm/runtime/drain", json={})
    assert drained.status_code == 200
    payload = drained.json()
    assert payload["outputs"] == ["Created task task_llm_001 and captured the goal."]
    assert (
        payload["workspace"]["task_board"]["items"][0]["task"]["task_id"]
        == "task_llm_001"
    )
    assert (
        payload["workspace"]["conversation"][0]["content"]
        == "Please track extracting the design goals as a task."
    )
    assert (
        payload["workspace"]["conversation"][1]["content"]
        == "Created task task_llm_001 and captured the goal."
    )
    assert any(event["event_type"] == "tool.completed" for event in payload["events"])
    assert not any(
        agent["agent"]["role"] != "master"
        for agent in payload["workspace"]["delegation"]["agents"]
    )


def test_debug_llm_calls_endpoint_lists_details_and_clears_records(monkeypatch) -> None:
    get_llm_debug_recorder().clear()
    client, foundation = _build_client(monkeypatch)
    debug_client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=replace(
                    foundation, model_factory=DebugRecordingModelFactory()
                ),
            )
        )
    )

    created = debug_client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_debug",
            "project_id": "proj_001",
            "objective": "Debug LLM calls",
        },
    )
    assert created.status_code == 200

    message = debug_client.post(
        "/v3/sessions/sess_v3_debug/messages",
        json={"message": "hello debug"},
    )
    assert message.status_code == 200
    drained = debug_client.post("/v3/sessions/sess_v3_debug/runtime/drain", json={})
    assert drained.status_code == 200

    records = debug_client.get("/debug/llm-calls?session_id=sess_v3_debug").json()
    assert len(records) == 1
    assert records[0]["purpose"] == "v3_harness_loop"
    assert records[0]["kind"] == "tool_calling"
    assert records[0]["request_context"]["session_id"] == "sess_v3_debug"
    assert records[0]["request"]["system_prompt"].startswith(
        "You are the top-level OpenZyme master agent."
    )
    assert records[0]["response"]["content"] == "Debug response."

    detail = debug_client.get(f"/debug/llm-calls/{records[0]['debug_id']}")
    assert detail.status_code == 200
    assert detail.json()["debug_id"] == records[0]["debug_id"]

    clear = debug_client.post("/debug/llm-calls/clear")
    assert clear.status_code == 200
    assert debug_client.get("/debug/llm-calls").json() == []


def test_v3_project_sessions_lists_recent_sessions_with_preview_and_pending_count(
    monkeypatch,
) -> None:
    client, _ = _build_v3_llm_client(monkeypatch)

    created_a = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_list_a",
            "project_id": "proj_001",
            "objective": "First session",
            "title": "Session A",
        },
    )
    created_b = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_list_b",
            "project_id": "proj_001",
            "objective": "Second session",
            "title": "Session B",
        },
    )
    assert created_a.status_code == 200
    assert created_b.status_code == 200

    message = client.post(
        "/v3/sessions/sess_v3_list_a/messages",
        json={"message": "Please track extracting the design goals as a task."},
    )
    assert message.status_code == 200
    drained = client.post("/v3/sessions/sess_v3_list_a/runtime/drain", json={})
    assert drained.status_code == 200

    listing = client.get("/v3/projects/proj_001/sessions")
    assert listing.status_code == 200
    payload = listing.json()
    assert [item["session_id"] for item in payload] == [
        "sess_v3_list_a",
        "sess_v3_list_b",
    ]
    assert payload[0]["title"] == "Session A"
    assert (
        payload[0]["latest_message_preview"]
        == "Created task task_llm_001 and captured the goal."
    )
    assert payload[0]["pending_approval_count"] == 0
    assert payload[0]["updated_at"] >= payload[1]["updated_at"]


def test_v3_message_ingress_returns_service_unavailable_without_model_factory(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch, with_model_factory=False)

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
    assert message.status_code == 200
    payload = message.json()
    assert payload["outputs"] == []
    assert any(
        event["event_type"] == "signal.queued"
        and event["payload"]["agent_id"] == "agent:master"
        for event in payload["events"]
    )
