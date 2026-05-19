from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

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
from openzyme_host_api.app import DrainV3RuntimeRequest
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import ConstraintItem
from openzyme_runtime import ConstraintSet
from openzyme_runtime import DesignBriefDraft
from openzyme_runtime import DesignNextAction
from openzyme_runtime import ExecutionPlanDraft
from openzyme_runtime import IntakeClarification
from openzyme_runtime import IntakePhaseOutput
from openzyme_runtime import LangChainToolCallingInvoker
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import ReportDraft
from openzyme_runtime import ResearchBriefDraft as RuntimeResearchBriefDraft
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
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
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_core import EngineDescriptor
from openzyme_core import EngineDocumentRecord
from openzyme_core import EngineRegistry
from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
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


class FakeExecutionAdapter:
    def submit_execution(
        self, episode_id: str, payload: dict[str, object]
    ) -> ExecutionOutcome:
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
    def conduct(
        self, *, episode_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult:
        del episode_id, research_brief
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


class FakeEngineHarnessInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.system_prompts: list[str] = []

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
                            "name": "task.update",
                            "args": {
                                "task_id": "task_research_v3",
                                "status": "completed",
                            },
                        }
                    ],
                }
            return {"content": "Research complete.", "tool_calls": []}
        if self.purpose == "v3_teammate_loop:executor":
            if any(_tool_message_name(message) == "task.update" for message in messages):
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
                            "name": "task.update",
                            "args": {
                                "task_id": "task_execution_v3",
                                "status": "completed",
                            },
                        }
                    ],
                }
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_start",
                            "name": "execution.pipeline.start",
                            "args": {
                                "task_id": "task_execution_v3",
                                "code": "from openzyme_pipeline import artifacts, hpc\nstructure = artifacts.get('art_v3_structure')\nhpc.fpocket(structure_artifact_id=structure['artifact_id'])\n",
                                "inputs": {
                                    "artifact_ids": ["art_v3_structure"],
                                },
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
                            "name": "task.update",
                            "args": {
                                "task_id": "task_report_v3",
                                "status": "completed",
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
            if latest_tool_name is None:
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
        self.phase_b = FakePhaseBModelFactory()

    def create_structured_invoker(self, *, purpose: str) -> FakePhaseBStructuredInvoker:
        return self.phase_b.create_structured_invoker(purpose=purpose)

    def create_tool_calling_invoker(self, *, purpose: str):
        if not purpose.startswith("v3_"):
            return self.phase_b.create_tool_calling_invoker(purpose=purpose)
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
        if any(_tool_message_name(message) == "task.update" for message in messages):
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
                    "name": "task.update",
                    "args": {
                        "task_id": "task_hpc_diag",
                        "status": "failed",
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
            "stderr_excerpt": "PipelineSdkError: hpc.fpocket failed with status failed",
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


def _resolve_next_approval(
    client: TestClient, episode_id: str, decision: str = "approved"
) -> dict[str, object]:
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


def _build_client(
    monkeypatch, *, with_model_factory: bool = True
) -> tuple[TestClient, RuntimeFoundation]:
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
                    foundation=replace(
                        foundation, model_factory=FakeHarnessModelFactory()
                    ),
                    graph_builder=build_v2_supervisor_graph,
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
                    graph_builder=build_v2_supervisor_graph,
                    v3_repositories=v3_repositories,
                )
            )
        ),
        v3_repositories,
        model_factory,
    )


def _build_v3_engine_repositories() -> CoreRepositories:
    connection = connect_v3_sqlite(":memory:")
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


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
            agent_id="agent:researcher",
            session_id="sess_task_crud_no_drain",
            lane_id=None,
            task_id=None,
            name="researcher",
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
            agent_id="agent:researcher",
            session_id="sess_drain_no_auto_claim",
            lane_id=None,
            task_id=None,
            name="researcher",
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

    service.drain_runtime(session_id="sess_drain_no_auto_claim", run_master_followup=False)

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
            agent_id="agent:researcher",
            session_id="sess_drain_auto_claim",
            lane_id=None,
            task_id=None,
            name="researcher",
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
        run_master_followup=False,
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

        def run_once_sync(self, session_id: str, *, max_signals: int, max_steps_per_agent: int, signal_ids=None):
            captured["session_id"] = session_id
            captured["max_signals"] = max_signals
            captured["max_steps_per_agent"] = max_steps_per_agent
            captured["signal_ids"] = signal_ids
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
        run_master_followup=False,
    )

    assert captured["worker_id"] == "host-api:runtime-drain"
    assert captured["max_global_concurrency"] == 7
    assert captured["max_session_concurrency"] == 5
    assert captured["max_agent_concurrency"] == 3
    assert captured["max_signals"] == 4
    assert captured["max_steps_per_agent"] == 6


def test_v3_drain_runtime_request_defaults_disable_auto_claim() -> None:
    assert DrainV3RuntimeRequest().auto_enqueue_ready_tasks is False


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
    repositories.tasks.save(
        Task.create(
            "task_hpc_diag",
            "sess_hpc_diag",
            "Run fpocket",
            "Run fpocket and report failures.",
            kind="execution",
            status=TaskStatus.BLOCKED,
            assigned_ref="agent:executor",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:executor",
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

    assert result.status == "failed"
    assert result.outputs == ()
    assert model_factory.invoker.calls == 0
    assert model_factory.master_calls == 0
    assert repositories.runtime_signals.list_pending_by_session("sess_hpc_diag")
    task = repositories.tasks.get("task_hpc_diag")
    assert task is not None
    assert task.status is TaskStatus.BLOCKED

    drained = service.drain_runtime(session_id="sess_hpc_diag")

    assert drained.status == "failed"
    assert model_factory.invoker.calls == 2
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
    Path("/tmp/v3_input_structure.pdb").write_text(
        "\n".join(lines) + "\nEND\n", encoding="utf-8"
    )
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
            metadata={"source": "test_fixture", "format": "pdb"},
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
        hpc_execution_registry=DefaultHpcExecutionRegistry(
            RepoBackedHpcCatalogProvider()
        ),
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
    assert workspace.json()["workflow"]["pending_approval"]["approval_id"].startswith(
        f"{episode_id}-execution-approval-"
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
    assert payload["outputs"] == ["Planning started."]
    assert {event["event_type"] for event in payload["events"]} >= {
        "conversation.user_message",
        "llm.response.created",
        "message.received",
        "message.sent",
        "conversation.assistant_message",
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
    assert "event: conversation.assistant_message" in events.text

    updated = client.patch("/v3/tasks/task_v3_001", json={"status": "in_progress"})
    assert updated.status_code == 200
    assert updated.json()["task"]["status"] == "in_progress"


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

    def _post_message() -> None:
        try:
            result_holder["result"] = service.post_message(
                session_id="sess_realtime_trace",
                message="create a task",
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            error_holder["error"] = exc

    thread = threading.Thread(target=_post_message)
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
            "objective": "Evaluate a thermostability candidate",
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
    assert research_payload["outputs"] == ["Delegated research task task_research_v3."]
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
    assert (
        research_payload["workspace"]["delegation"]["agents"][0]["agent"]["role"]
        == "researcher"
    )
    research_assistant_messages = [
        message["content"]
        for message in research_payload["workspace"]["conversation"]
        if message["role"] == "assistant"
    ]
    assert research_payload["outputs"] == ["Research complete."]
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
    assert execution_payload["outputs"] == ["Delegated execution task task_execution_v3."]
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
        == executor_calls_before_approval + 3
    )
    assert any(
        message.message_type == "delegation_result"
        and message.sender == "agent:executor"
        for message in v3_repositories.inbox.list_by_session("sess_v3_engines")
    )
    assert resolved_payload["status"] == "completed"
    assert resolved_payload["workspace"]["pending_approvals"] == []
    assert (
        resolved_payload["workspace"]["capabilities"]["execution"][0]["status"]
        == "succeeded"
    )
    assert resolved_payload["workspace"]["artifacts"]
    assert len(resolved_payload["outputs"]) == 1
    assert "fpocket found" in resolved_payload["outputs"][0]
    assert "Output artifacts:" in resolved_payload["outputs"][0]
    assert "Pipeline sandbox completed." not in resolved_payload["outputs"][0]
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
    assert report_payload["outputs"] == ["Delegated reporting task task_report_v3."]

    report_drain = client.post(
        "/v3/sessions/sess_v3_engines/runtime/drain",
        json={},
    )
    assert report_drain.status_code == 200
    report_payload = report_drain.json()
    assert report_payload["status"] == "completed"
    assert (
        report_payload["workspace"]["report_drafts"][0]["task_id"] == "task_report_v3"
    )
    assert report_payload["workspace"]["report_drafts"][0]["status"] == "published"
    assert report_payload["workspace"]["reports"][0]["status"] == "ready"
    assert "reporting" not in report_payload["workspace"]["capabilities"]

    events = client.get("/v3/sessions/sess_v3_engines/events?replay=1")
    assert events.status_code == 200
    assert "event: engine.invocation.started" in events.text
    assert "event: report_draft.updated" in events.text
    assert "event: report.generated" in events.text


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
    assert payload["workspace"]["delegation"]["agents"] == []


def test_debug_llm_calls_endpoint_lists_details_and_clears_records(monkeypatch) -> None:
    get_llm_debug_recorder().clear()
    client, foundation = _build_client(monkeypatch)
    debug_client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=replace(
                    foundation, model_factory=DebugRecordingModelFactory()
                ),
                graph_builder=build_v2_supervisor_graph,
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
    assert message.status_code == 503
    assert "requires a configured model_factory" in message.json()["detail"]


def test_resolve_approval_advances_episode_and_exposes_runs_and_artifacts(
    monkeypatch,
) -> None:
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
    lines = [
        line for line in stream_response.text.splitlines() if line.startswith("data: ")
    ]
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
        json={
            "project_id": "proj_001",
            "objective": "Research thermostability evidence",
        },
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
    assert research["unresolved_gaps"][0]["summary"].startswith(
        "Missing structure-backed"
    )


def test_unified_supervisor_resumes_design_then_execution_on_one_episode_thread(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={
            "project_id": "proj_001",
            "objective": "Research thermostability evidence",
        },
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


def test_report_query_and_projection_become_available_after_supervisor_completion(
    monkeypatch,
) -> None:
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


def test_project_and_episode_queries_support_browser_shell_bootstrap(
    monkeypatch,
) -> None:
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
    assert {episode["episode_id"] for episode in episodes.json()} >= {
        created["episode_id"]
    }
