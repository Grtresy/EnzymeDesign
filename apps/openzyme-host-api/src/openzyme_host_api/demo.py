from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import ArtifactKind
from openzyme_domain import Project
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult

from .app import HostApiDependencies
from .app import create_app


REPO_ROOT = Path(__file__).resolve().parents[4]
UI_DIST_DIR = REPO_ROOT / "apps" / "openzyme-web-ui" / "dist"
SQLITE_DB_PATH = REPO_ROOT / ".tmp" / "openzyme-demo.sqlite3"


@dataclass(slots=True)
class DemoExecutionAdapter:
    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> ExecutionOutcome:
        return ExecutionOutcome(
            run_id="run_001",
            status=RunStatus.SUCCEEDED,
            execution_mode="demo",
            remote_run_dir=f"/demo/{episode_id}/run_001",
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri="/tmp/openzyme-demo/stdout.log",
                    relative_path="stdout.log",
                    kind=ArtifactKind.LOG,
                ),
                ExecutionArtifactRef(
                    storage_uri="/tmp/openzyme-demo/result.json",
                    relative_path="result.json",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            raw_result={"status": "completed", "mode": "demo"},
        )


@dataclass(slots=True)
class DemoResearchAdapter:
    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult:
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the demo objective.",
            findings=(
                ResearchFinding(
                    summary=f"Demo finding for {unit.query}",
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Demo source for {unit.unit_id}",
                            locator=f"https://example.org/demo/{unit.unit_id}",
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need wet-lab follow-up for the top hypothesis.",),
        )


class InMemoryCheckpointerFactory:
    def __init__(self) -> None:
        self._saver = InMemorySaver()

    @contextmanager
    def open(self):
        yield self._saver


def build_demo_foundation() -> RuntimeFoundation:
    SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_sqlite(str(SQLITE_DB_PATH))
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    if repositories.projects.get("proj_001") is None:
        repositories.projects.save(
            Project.create(
                "proj_001",
                "Thermostability demo project",
                "Preloaded project for the local Phase B workspace demo.",
            )
        )
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=InMemoryCheckpointerFactory(),  # type: ignore[arg-type]
        execution_adapter=DemoExecutionAdapter(),
        research_adapter=DemoResearchAdapter(),
    )


def main() -> None:
    app = create_app(
        HostApiDependencies(
            foundation=build_demo_foundation(),
            graph_builder=build_v2_supervisor_graph,
        ),
        ui_dist_dir=UI_DIST_DIR if UI_DIST_DIR.exists() else None,
    )
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
