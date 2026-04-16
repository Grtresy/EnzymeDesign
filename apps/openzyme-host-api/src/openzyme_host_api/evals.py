from __future__ import annotations

import argparse
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any
from typing import Callable

from fastapi.testclient import TestClient
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
        "artifact_workspace": summary["artifact_count"] >= summary["focused_artifact_count"],
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
            inputs={"scenario_id": scenario.scenario_id, "objective": scenario.objective},
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local OpenZyme routed workflow evals")
    parser.add_argument(
        "--upload-results",
        action="store_true",
        help="Enable LangSmith trace upload for eval scenario runs",
    )
    args = parser.parse_args(argv)
    summary = run_local_workflow_evals(upload_results=args.upload_results)
    print(summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
