from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import time
from typing import Any
from typing import Callable

from fastapi.testclient import TestClient
from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_domain import ArtifactKind
from openzyme_domain import SessionArtifactRecord
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ResearchBriefDraft as EngineResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft
from openzyme_engines import ResearchUnitPlan
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import get_settings

from .app import HostApiDependencies
from .app import create_app
from .foundation import build_configured_foundation
from .foundation import build_local_eval_foundation
from .tracing import workflow_trace


FoundationBuilder = Callable[[Path], RuntimeFoundation]


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


def _focused_task_from_prompt(system_prompt: str) -> str:
    for line in system_prompt.splitlines():
        if line.startswith("Focused task: "):
            return line.removeprefix("Focused task: ").strip()
    return ""


class V3LocalEvalInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.workflow_calls = 0
        self.report_delegated = False

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        if self.purpose == "deep_research_researcher":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_eval_deep_research_search",
                            "name": "web.search",
                            "args": {
                                "query": "thermostable glycoside hydrolase xylan substrate evidence",
                                "topic": "enzyme design",
                                "max_results": 3,
                            },
                        }
                    ],
                }
            return {"content": "Source-backed enzyme design evidence collected.", "tool_calls": []}
        if self.purpose == "v3_teammate_loop:researcher":
            return self._researcher_response(system_prompt)
        if self.purpose == "v3_teammate_loop:executor":
            return self._executor_response(system_prompt, messages)
        if self.purpose == "v3_teammate_loop:reporter":
            return self._reporter_response(system_prompt)
        return self._master_response(system_prompt, messages)

    def _researcher_response(self, system_prompt: str) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_research"
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_research_start",
                        "name": "deep_research.start",
                        "args": {
                            "task_id": task_id,
                            "brief": "Collect enzyme design evidence for thermostability, substrate scope, and assay constraints.",
                        },
                    }
                ],
            }
        if self.calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_research_task_complete",
                        "name": "task.update",
                        "args": {"task_id": task_id, "status": "completed"},
                    }
                ],
            }
        return {"content": "Research evidence collected.", "tool_calls": []}

    def _executor_response(
        self, system_prompt: str, messages: list[object]
    ) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_execution"
        if any(_tool_message_name(message) == "task.update" for message in messages):
            return {
                "content": "Execution approval resolved and artifacts captured.",
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
                        "id": "call_eval_execution_task_complete",
                        "name": "task.update",
                        "args": {
                            "task_id": task_id,
                            "status": "completed",
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
                        "id": "call_eval_execution_start",
                        "name": "execution.pipeline.start",
                        "args": {
                            "task_id": task_id,
                            "code_artifact_id": code_artifact_id,
                            "inputs": {
                                "artifact_ids": ["art_eval_structure"],
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
                        "id": "call_eval_execution_source",
                        "name": "artifact.create_text",
                        "args": {
                            "filename": "fpocket_pipeline.py",
                            "content": (
                                "from openzyme_pipeline import artifacts, hpc\n"
                                "structure = artifacts.get('art_eval_structure')\n"
                                "hpc.fpocket(structure_artifact_id=structure['artifact_id'])\n"
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
                        "id": "call_eval_execution_status",
                        "name": "execution.pipeline.status",
                        "args": {"invocation_id": invocation_id},
                    }
                ],
            }
        return {
            "content": "Execution started and is waiting for approval.",
            "tool_calls": [],
        }

    def _reporter_response(self, system_prompt: str) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_report"
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_report_draft",
                        "name": "report_draft.update",
                        "args": {
                            "task_id": task_id,
                            "title": "V3 cutover evaluation report",
                            "summary": "Research, execution, and reporting completed through the V3 harness path.",
                            "status": "ready",
                            "markdown": (
                                "# V3 cutover evaluation report\n\n"
                                "The deterministic V3 eval completed research, execution, and final reporting."
                            ),
                        },
                    }
                ],
            }
        if self.calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_report_publish",
                        "name": "report.publish",
                        "args": {
                            "task_id": task_id,
                            "title": "V3 cutover evaluation report",
                            "summary": "Research, execution, and reporting completed through the V3 harness path.",
                            "stage_summary": "Deterministic cutover eval passed the V3 workspace path.",
                        },
                    }
                ],
            }
        if self.calls == 3:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_report_task_complete",
                        "name": "task.update",
                        "args": {"task_id": task_id, "status": "completed"},
                    }
                ],
            }
        return {"content": "Report published.", "tool_calls": []}

    def _master_response(
        self, system_prompt: str, messages: list[object]
    ) -> dict[str, object]:
        latest_user_message = next(
            (
                _message_content(message)
                for message in reversed(messages)
                if _message_role(message) == "user"
            ),
            "",
        )
        focused_task = _focused_task_from_prompt(system_prompt)
        if (
            focused_task == "task_eval_research"
            and "completed task_id=task_eval_research" in system_prompt
        ):
            return {"content": "Research evidence collected.", "tool_calls": []}
        if (
            focused_task == "task_eval_execution"
            and "completed task_id=task_eval_execution" in system_prompt
        ):
            return {
                "content": "Execution artifacts were captured and are ready for reporting.",
                "tool_calls": [],
            }
        if (
            focused_task == "task_eval_report"
            and "completed task_id=task_eval_report" in system_prompt
        ):
            return {
                "content": "V3 evaluation report has been published.",
                "tool_calls": [],
            }
        self.workflow_calls += 1
        if self.workflow_calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_lane",
                        "name": "lane.create",
                        "args": {
                            "lane_id": "lane_eval_design",
                            "name": "design-eval",
                            "cwd": "/tmp/openzyme-v3-eval",
                            "branch_name": "eval/v3-cutover",
                        },
                    },
                    {
                        "id": "call_eval_research_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_eval_research",
                            "subject": "Extract design goals and evidence",
                            "description": "Extract design goals from the literature brief and collect supporting evidence.",
                            "kind": "research",
                            "priority": "high",
                        },
                    },
                    {
                        "id": "call_eval_bind_research",
                        "name": "lane.bind_task",
                        "args": {
                            "task_id": "task_eval_research",
                            "lane_id": "lane_eval_design",
                        },
                    },
                ],
            }
        if self.workflow_calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_delegate_research",
                        "name": "task.delegate",
                        "args": {
                            "task_id": "task_eval_research",
                            "agent_role": "researcher",
                            "instructions": "Extract the enzyme design goals and summarize supporting research evidence.",
                        },
                    },
                ],
            }
        if self.workflow_calls == 3:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_execution_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_eval_execution",
                            "subject": "Run design execution check",
                            "description": "Run the deterministic execution check for the selected enzyme design scaffold.",
                            "kind": "execution",
                            "priority": "high",
                        },
                    },
                    {
                        "id": "call_eval_bind_execution",
                        "name": "lane.bind_task",
                        "args": {
                            "task_id": "task_eval_execution",
                            "lane_id": "lane_eval_design",
                        },
                    },
                    {
                        "id": "call_eval_delegate_execution",
                        "name": "task.delegate",
                        "args": {
                            "task_id": "task_eval_execution",
                            "agent_role": "executor",
                            "instructions": "Run the execution check and capture artifacts after approval.",
                        },
                    },
                ],
            }
        if "report" in latest_user_message.lower():
            if not self.report_delegated:
                self.report_delegated = True
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_eval_report_task",
                            "name": "task.create",
                            "args": {
                                "task_id": "task_eval_report",
                                "subject": "Draft final delivery report",
                                "description": "Draft and publish the final V3 design delivery report.",
                                "kind": "reporting",
                                "priority": "normal",
                            },
                        },
                        {
                            "id": "call_eval_bind_report",
                            "name": "lane.bind_task",
                            "args": {
                                "task_id": "task_eval_report",
                                "lane_id": "lane_eval_design",
                            },
                        },
                        {
                            "id": "call_eval_delegate_report",
                            "name": "task.delegate",
                            "args": {
                                "task_id": "task_eval_report",
                                "agent_role": "reporter",
                                "instructions": "Create and publish the final report draft from the workspace state.",
                            },
                        },
                    ],
                }
            return {
                "content": "V3 evaluation report has been published.",
                "tool_calls": [],
            }
        return {
            "content": "Execution is waiting for approval before final delivery.",
            "tool_calls": [],
        }


class V3LocalEvalModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, V3LocalEvalInvoker] = {}

    def create_structured_invoker(self, *, purpose: str) -> "V3LocalEvalStructuredInvoker":
        return V3LocalEvalStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str) -> V3LocalEvalInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = V3LocalEvalInvoker(purpose)
        return self.invokers[purpose]


class V3LocalEvalStructuredInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose

    def invoke_structured(
        self, *, schema: object, system_prompt: str, user_payload: dict[str, object]
    ) -> object:
        del system_prompt
        if schema is EngineResearchBriefDraft:
            return EngineResearchBriefDraft(
                research_brief=(
                    "Collect source-backed enzyme engineering evidence for thermostable "
                    "glycoside hydrolase scaffolds and soluble xylan turnover."
                )
            )
        if schema is ResearchSupervisorAction:
            if user_payload.get("unit_results"):
                return ResearchSupervisorAction(
                    action_kind="complete",
                    rationale="The eval research unit returned usable source-backed findings.",
                )
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one focused source-backed evidence unit.",
                unit_plan=ResearchUnitPlan(
                    units=[
                        ResearchUnitDraft(
                            unit_id="eval_evidence",
                            topic="enzyme design evidence",
                            query="thermostable glycoside hydrolase xylan substrate evidence",
                            rationale="Support downstream execution and reporting.",
                        )
                    ],
                    synthesis_goal="Summarize evidence for the V3 eval design path.",
                ),
            )
        if schema is EvidenceSynthesis:
            return EvidenceSynthesis(
                summary="Source-backed enzyme design evidence supports the V3 eval scaffold path.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Thermostable glycoside hydrolase evidence supports the scaffold direction.",
                        query="thermostable glycoside hydrolase xylan substrate evidence",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Deterministic enzyme design source",
                                locator="https://example.org/eval-enzyme-design",
                                kind="web_page",
                                snippet="Thermostable scaffold evidence with xylan turnover context.",
                            )
                        ],
                    )
                ],
                unresolved_gaps=["Wet-lab validation remains outside the local eval."],
            )
        raise AssertionError(f"Unhandled eval structured schema {schema!r}")


def build_local_eval_runtime(sqlite_db_path: Path) -> RuntimeFoundation:
    settings = get_settings()
    return build_local_eval_foundation(
        sqlite_db_path=sqlite_db_path,
        settings=replace(
            settings,
            llm=replace(settings.llm, api_key=None),
        ),
    )


def build_live_eval_foundation(sqlite_db_path: Path) -> RuntimeFoundation:
    return build_configured_foundation(sqlite_db_path=sqlite_db_path)


def build_v3_eval_repositories() -> CoreRepositories:
    connection = connect_v3_sqlite(":memory:")
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def seed_v3_eval_execution_artifact(
    repositories: CoreRepositories, session_id: str
) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "fpocket" / "1ubq.pdb"
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_eval_structure",
            session_id=session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri=str(fixture_path),
            relative_path="fixtures/fpocket/1ubq.pdb",
            title="1ubq.pdb",
            description=None,
            metadata={
                "source": "eval_fixture",
                "format": "pdb",
                "validation_profile": "fpocket_valid",
            },
            created_at="2026-04-20T12:00:03+00:00",
        )
    )


def _poll_v3_background_workspace(
    client: TestClient,
    *,
    session_id: str,
    is_ready: Callable[[dict[str, Any]], bool],
    timeout_seconds: float = 15.0,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    workspace: dict[str, Any] = {}
    event_text = ""
    runtime_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        workspace_response = client.get(f"/v3/sessions/{session_id}/workspace")
        if workspace_response.status_code != 200:
            runtime_response = client.get("/debug/v3-runtime")
            raise RuntimeError(
                {
                    "step": "get_v3_workspace",
                    "status_code": workspace_response.status_code,
                    "body": workspace_response.text,
                    "workspace": workspace,
                    "runtime_status": runtime_response.json()
                    if runtime_response.status_code == 200
                    else runtime_response.text,
                    "events": event_text[-1000:],
                }
            )
        workspace_response.raise_for_status()
        workspace = workspace_response.json()
        events_response = client.get(f"/v3/sessions/{session_id}/events?replay=1")
        if events_response.status_code != 200:
            runtime_response = client.get("/debug/v3-runtime")
            raise RuntimeError(
                {
                    "step": "get_v3_events",
                    "status_code": events_response.status_code,
                    "body": events_response.text,
                    "workspace": workspace,
                    "runtime_status": runtime_response.json()
                    if runtime_response.status_code == 200
                    else runtime_response.text,
                    "events": event_text[-1000:],
                }
            )
        events_response.raise_for_status()
        event_text = events_response.text
        runtime_response = client.get("/debug/v3-runtime")
        runtime_response.raise_for_status()
        runtime_status = runtime_response.json()

        approvals = workspace.get("pending_approvals") or []
        if approvals:
            resolved = client.post(
                f"/v3/approvals/{approvals[0]['approval_id']}/resolve",
                json={"decision": "approved", "actor_ref": "eval"},
            )
            resolved.raise_for_status()
            time.sleep(0.2)
            continue

        if is_ready(workspace):
            return workspace, event_text, runtime_status
        time.sleep(0.2)
    return workspace, event_text, runtime_status


def _run_v3_design_cutover_scenario(
    *,
    foundation_builder: FoundationBuilder,
    model_factory: Any | None,
    upload_results: bool = False,
    scenario_id: str = "v3_design_cutover_path",
) -> dict[str, Any]:
    objective = (
        "Given a literature brief on a thermostable enzyme scaffold, extract design "
        "goals and run the V3 research, execution, and report delivery path."
    )
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-eval-") as temp_dir:
        foundation = foundation_builder(Path(temp_dir) / "eval.sqlite3")
        if model_factory is not None:
            foundation = replace(foundation, model_factory=model_factory)
        v3_repositories = build_v3_eval_repositories()
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                v3_repositories=v3_repositories,
                v3_background_runtime_enabled=True,
            )
        )
        with TestClient(app) as client:
            created = client.post(
                "/v3/sessions",
                json={
                    "session_id": "sess_eval_v3_cutover",
                    "project_id": "proj_001",
                    "objective": objective,
                    "title": "V3 cutover eval",
                },
            )
            created.raise_for_status()
            seed_v3_eval_execution_artifact(v3_repositories, "sess_eval_v3_cutover")

            prompt = (
                "Use this literature brief to run the V3 design workflow. "
                "A glycoside hydrolase scaffold retains activity after 65 C heat "
                "challenge but needs improved substrate turnover on soluble xylan. "
                "Extract design goals, delegate research, run an execution check, "
                "and stop for approval if execution requires it."
            )
            with workflow_trace(
                "openzyme.v3_eval_scenario",
                action="v3_local_eval" if model_factory is not None else "v3_live_eval",
                project_id="proj_001",
                phase="evaluation",
                inputs={"scenario_id": scenario_id, "objective": objective},
                enabled=upload_results,
            ) as run:
                first_turn = client.post(
                    "/v3/sessions/sess_eval_v3_cutover/messages",
                    json={"message": prompt},
                )
                first_turn.raise_for_status()
                _poll_v3_background_workspace(
                    client,
                    session_id="sess_eval_v3_cutover",
                    is_ready=lambda workspace: (
                        "deep_research" in workspace["capabilities"]
                        and workspace["capabilities"]["deep_research"][0]["status"]
                        == "succeeded"
                        and "execution" in workspace["capabilities"]
                        and workspace["capabilities"]["execution"][0]["status"]
                        == "succeeded"
                    ),
                )

                report_turn = client.post(
                    "/v3/sessions/sess_eval_v3_cutover/messages",
                    json={
                        "message": "Publish the final report from the completed research and execution evidence.",
                    },
                )
                report_turn.raise_for_status()
                workspace, event_text, runtime_status = _poll_v3_background_workspace(
                    client,
                    session_id="sess_eval_v3_cutover",
                    is_ready=lambda workspace: (
                        bool(workspace["reports"])
                        and bool(workspace["report_drafts"])
                        and workspace["report_drafts"][0]["status"] == "published"
                    ),
                )
                tasks = [item["task"] for item in workspace["task_board"]["items"]]
                task_kinds = {task["kind"] for task in tasks}
                agent_roles = {
                    item["agent"]["role"] for item in workspace["delegation"]["agents"]
                }
                capability_keys = set(workspace["capabilities"])
                report_drafts = workspace["report_drafts"]
                reports = workspace["reports"]
                checks = {
                    "task_create_event": "event: task.created" in event_text,
                    "delegate_tool_event": "task.delegate" in event_text,
                    "teammate_wakeup": bool(
                        agent_roles & {"researcher", "executor", "reporter"}
                    ),
                    "background_runtime": runtime_status.get("worker_id")
                    == "host-api:background-runtime"
                    and int(runtime_status.get("processed_signal_count") or 0) > 0,
                    "signal_lifecycle": "event: signal.claimed" in event_text
                    and "event: signal.completed" in event_text,
                    "research_completed": "deep_research" in capability_keys
                    and workspace["capabilities"]["deep_research"][0]["status"]
                    == "succeeded",
                    "execution_artifact": bool(workspace["artifacts"])
                    and "execution" in capability_keys
                    and workspace["capabilities"]["execution"][0]["status"]
                    == "succeeded",
                    "report_draft_published": bool(report_drafts)
                    and report_drafts[0]["status"] == "published",
                    "final_report_ready": bool(reports)
                    and reports[0]["status"] == "ready",
                    "workspace_projection": {"research", "execution", "reporting"}
                    <= task_kinds,
                }
                result = {
                    "scenario_id": scenario_id,
                    "session_id": workspace["session"]["session_id"],
                    "task_count": len(tasks),
                    "agent_roles": sorted(agent_roles),
                    "capability_keys": sorted(capability_keys),
                    "report_count": len(reports),
                    "checks": checks,
                    "passed": all(checks.values()),
                }
                if run is not None:
                    run.end(outputs=result)
                return result


def run_v3_local_evals(*, upload_results: bool = False) -> dict[str, Any]:
    result = _run_v3_design_cutover_scenario(
        foundation_builder=build_local_eval_runtime,
        model_factory=V3LocalEvalModelFactory(),
        upload_results=upload_results,
    )
    return {
        "scenario_count": 1,
        "passed": 1 if result["passed"] else 0,
        "failed": 0 if result["passed"] else 1,
        "upload_results": upload_results,
        "results": [result],
    }


def _run_v3_live_task_plan_scenario(*, upload_results: bool = False) -> dict[str, Any]:
    objective = (
        "Extract enzyme design goals from a literature abstract and generate an "
        "executable V3 design workflow task plan."
    )
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-live-eval-") as temp_dir:
        foundation = build_live_eval_foundation(Path(temp_dir) / "eval.sqlite3")
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                v3_repositories=build_v3_eval_repositories(),
                v3_background_runtime_enabled=True,
            )
        )
        with TestClient(app) as client:
            created = client.post(
                "/v3/sessions",
                json={
                    "session_id": "sess_eval_v3_live_plan",
                    "project_id": "proj_001",
                    "objective": objective,
                    "title": "V3 live task-plan eval",
                },
            )
            created.raise_for_status()
            prompt = (
                "Read this abstract and create an executable design workflow task plan. "
                "Abstract: A thermostable GH10 xylanase variant retains 80% activity "
                "after 65 C incubation, but soluble xylan turnover and alkaline pH "
                "stability remain limiting for biomass pretreatment. "
                "Call task.create exactly three times with these subjects: "
                "'Extract design goals', 'Run execution screen', and "
                "'Draft final report'. Use kind values research, execution, "
                "and reporting respectively. "
                "Then reply with one concise sentence."
            )
            with workflow_trace(
                "openzyme.v3_live_task_plan_eval",
                action="v3_live_eval",
                project_id="proj_001",
                phase="evaluation",
                inputs={
                    "scenario_id": "v3_live_design_task_plan",
                    "objective": objective,
                },
                enabled=upload_results,
            ) as run:
                response = client.post(
                    "/v3/sessions/sess_eval_v3_live_plan/messages",
                    json={"message": prompt},
                )
                response.raise_for_status()
                workspace, event_text, runtime_status = _poll_v3_background_workspace(
                    client,
                    session_id="sess_eval_v3_live_plan",
                    timeout_seconds=240.0,
                    is_ready=lambda current: len(
                        (current.get("task_board") or {}).get("items", [])
                    )
                    >= 3
                    and any(
                        message.get("role") == "assistant"
                        for message in current.get("conversation", [])
                    ),
                )
                tasks = [item["task"] for item in workspace["task_board"]["items"]]
                subjects = {task["subject"] for task in tasks}
                task_kinds = {task["kind"] for task in tasks}
                checks = {
                    "extracted_goal_task": "Extract design goals" in subjects,
                    "execution_task": "Run execution screen" in subjects,
                    "report_task": "Draft final report" in subjects,
                    "full_flow_kinds": {"research", "execution", "reporting"}
                    <= task_kinds,
                    "assistant_output": any(
                        message["role"] == "assistant"
                        for message in workspace["conversation"]
                    ),
                    "background_runtime": runtime_status.get("worker_id")
                    == "host-api:background-runtime",
                    "signal_lifecycle": "event: signal.claimed" in event_text
                    and "event: signal.completed" in event_text,
                    "workspace_projection": len(tasks) >= 3,
                }
                result = {
                    "scenario_id": "v3_live_design_task_plan",
                    "session_id": workspace["session"]["session_id"],
                    "task_count": len(tasks),
                    "subjects": sorted(subjects),
                    "task_kinds": sorted(task_kinds),
                    "checks": checks,
                    "passed": all(checks.values()),
                }
                if run is not None:
                    run.end(outputs=result)
                return result


def run_v3_live_evals(*, upload_results: bool = False) -> dict[str, Any]:
    result = _run_v3_live_task_plan_scenario(upload_results=upload_results)
    return {
        "scenario_count": 1,
        "passed": 1 if result["passed"] else 0,
        "failed": 0 if result["passed"] else 1,
        "upload_results": upload_results,
        "results": [result],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run OpenZyme V3 workflow evals"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use configured live providers for the selected eval path",
    )
    parser.add_argument(
        "--upload-results",
        action="store_true",
        help="Enable LangSmith trace upload for eval scenario runs",
    )
    args = parser.parse_args(argv)
    summary = (
        run_v3_live_evals(upload_results=args.upload_results)
        if args.live
        else run_v3_local_evals(upload_results=args.upload_results)
    )
    print(summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
