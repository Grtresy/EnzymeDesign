from __future__ import annotations

import argparse
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any
from typing import Callable

from fastapi.testclient import TestClient
from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_domain import ArtifactKind
from openzyme_domain import SessionArtifactRecord
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import get_settings

from .app import HostApiDependencies
from .app import create_app
from .foundation import build_configured_foundation
from .foundation import build_local_eval_foundation
from .tracing import workflow_trace


@dataclass(frozen=True, slots=True)
class EvalScenario:
    scenario_id: str
    objective: str
    decisions: tuple[str, ...]
    expected_status: str
    expect_report: bool
    expected_phase: str


SEEDED_SCENARIOS: tuple[EvalScenario, ...] = (
    EvalScenario(
        scenario_id="happy_path_report",
        objective="Design a thermostable enzyme candidate with a final report",
        decisions=("approved", "approved"),
        expected_status="completed",
        expect_report=True,
        expected_phase="report_review",
    ),
    EvalScenario(
        scenario_id="design_rejected",
        objective="Design a candidate but reject the first approval gate",
        decisions=("rejected",),
        expected_status="interrupted",
        expect_report=False,
        expected_phase="execution",
    ),
)


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

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        if self.purpose == "v3_teammate_loop:researcher":
            return self._researcher_response(system_prompt)
        if self.purpose == "v3_teammate_loop:executor":
            return self._executor_response(system_prompt)
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
        return {"content": "Research evidence collected.", "tool_calls": []}

    def _executor_response(self, system_prompt: str) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_execution"
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_execution_start",
                        "name": "execution.pipeline.start",
                        "args": {
                            "task_id": task_id,
                            "code": "from openzyme_pipeline import artifacts, hpc\nstructure = artifacts.get('art_eval_structure')\nhpc.fpocket(structure_artifact_id=structure['artifact_id'])\n",
                            "inputs": {
                                "artifact_ids": ["art_eval_structure"],
                            },
                        },
                    }
                ],
            }
        return {
            "content": "Execution approval resolved and artifacts captured.",
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
            if self.workflow_calls == 4:
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

    def create_tool_calling_invoker(self, *, purpose: str) -> V3LocalEvalInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = V3LocalEvalInvoker(purpose)
        return self.invokers[purpose]


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


def _run_scenario(
    scenario: EvalScenario,
    *,
    foundation_builder: FoundationBuilder,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="openzyme-eval-") as temp_dir:
        foundation = foundation_builder(Path(temp_dir) / "eval.sqlite3")
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                graph_builder=build_v2_supervisor_graph,
            )
        )
        with TestClient(app) as client:
            created = client.post(
                "/commands/create_episode",
                json={"project_id": "proj_001", "objective": scenario.objective},
            )
            created.raise_for_status()
            payload = created.json()
            episode_id = payload["episode_id"]

            for decision in scenario.decisions:
                workspace_response = client.get(f"/episodes/{episode_id}/workspace")
                workspace_response.raise_for_status()
                workspace = workspace_response.json()
                if workspace["workflow"]["status"] in {"completed", "failed"}:
                    break
                pending = client.get(f"/episodes/{episode_id}/pending-actions")
                pending.raise_for_status()
                pending_actions = pending.json()
                if not pending_actions:
                    break
                resolved = client.post(
                    "/commands/resolve_approval",
                    json={
                        "episode_id": episode_id,
                        "approval_id": pending_actions[0]["approval_id"],
                        "decision": decision,
                    },
                )
                resolved.raise_for_status()

            workspace_response = client.get(f"/episodes/{episode_id}/workspace")
            workspace_response.raise_for_status()
            reports_response = client.get(f"/episodes/{episode_id}/reports")
            reports_response.raise_for_status()
            workspace = workspace_response.json()
            reports = reports_response.json()

    workflow = workspace["workflow"]
    summary = workflow["summary"]
    checks = {
        "workflow_status": workflow["status"] == scenario.expected_status,
        "phase": workflow["current_phase"] == scenario.expected_phase,
        "report_presence": (len(reports) > 0) is scenario.expect_report,
        "report_summary": (not scenario.expect_report)
        or bool(workspace["report"] and workspace["report"]["summary"]),
        "artifact_workspace": summary["artifact_count"]
        >= summary["focused_artifact_count"],
    }
    return {
        "scenario_id": scenario.scenario_id,
        "episode_id": workspace["episode_id"],
        "workflow_status": workflow["status"],
        "phase": workflow["current_phase"],
        "report_count": len(reports),
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_workflow_evals(
    *,
    foundation_builder: FoundationBuilder,
    upload_results: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for scenario in SEEDED_SCENARIOS:
        with workflow_trace(
            "openzyme.local_eval_scenario",
            action="local_eval",
            project_id="proj_001",
            phase="evaluation",
            inputs={
                "scenario_id": scenario.scenario_id,
                "objective": scenario.objective,
            },
            enabled=upload_results,
        ) as run:
            result = _run_scenario(scenario, foundation_builder=foundation_builder)
            if run is not None:
                run.end(outputs=result)
            results.append(result)
    passed = sum(1 for result in results if result["passed"])
    return {
        "scenario_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "upload_results": upload_results,
        "results": results,
    }


def run_local_workflow_evals(*, upload_results: bool = False) -> dict[str, Any]:
    return run_workflow_evals(
        foundation_builder=build_local_eval_runtime,
        upload_results=upload_results,
    )


def run_live_workflow_evals(*, upload_results: bool = False) -> dict[str, Any]:
    return run_workflow_evals(
        foundation_builder=build_live_eval_foundation,
        upload_results=upload_results,
    )


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
                graph_builder=build_v2_supervisor_graph,
                v3_repositories=v3_repositories,
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
                    json={"message": prompt, "max_steps": 8},
                )
                first_turn.raise_for_status()
                first_payload = first_turn.json()
                approvals = first_payload["workspace"]["pending_approvals"]
                if approvals:
                    resolved = client.post(
                        f"/v3/approvals/{approvals[0]['approval_id']}/resolve",
                        json={"decision": "approved", "actor_ref": "eval"},
                    )
                    resolved.raise_for_status()

                report_turn = client.post(
                    "/v3/sessions/sess_eval_v3_cutover/messages",
                    json={
                        "message": "Create and publish the final V3 report draft.",
                        "max_steps": 8,
                    },
                )
                report_turn.raise_for_status()
                workspace_response = client.get(
                    "/v3/sessions/sess_eval_v3_cutover/workspace"
                )
                workspace_response.raise_for_status()
                workspace = workspace_response.json()
                events_response = client.get(
                    "/v3/sessions/sess_eval_v3_cutover/events?replay=1"
                )
                events_response.raise_for_status()

                event_text = events_response.text
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
                graph_builder=build_v2_supervisor_graph,
                v3_repositories=build_v3_eval_repositories(),
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
                    json={"message": prompt, "max_steps": 6},
                )
                response.raise_for_status()
                workspace = response.json()["workspace"]
                tasks = [item["task"] for item in workspace["task_board"]["items"]]
                subjects = {task["subject"] for task in tasks}
                task_kinds = {task["kind"] for task in tasks}
                checks = {
                    "extracted_goal_task": "Extract design goals" in subjects,
                    "execution_task": "Run execution screen" in subjects,
                    "report_task": "Draft final report" in subjects,
                    "full_flow_kinds": {"research", "execution", "reporting"}
                    <= task_kinds,
                    "assistant_output": bool(response.json()["outputs"]),
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
        description="Run local OpenZyme routed workflow evals"
    )
    parser.add_argument(
        "--v3",
        action="store_true",
        help="Run V3 cutover evals instead of the legacy V2 seeded workflow evals",
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
    if args.v3:
        summary = (
            run_v3_live_evals(upload_results=args.upload_results)
            if args.live
            else run_v3_local_evals(upload_results=args.upload_results)
        )
    else:
        summary = (
            run_live_workflow_evals(upload_results=args.upload_results)
            if args.live
            else run_local_workflow_evals(upload_results=args.upload_results)
        )
    print(summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
