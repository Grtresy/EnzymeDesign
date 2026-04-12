from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field

import uvicorn
from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import ArtifactKind
from openzyme_domain import Project
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_runtime import get_settings
from openzyme_runtime import OpenAICompatibleChatModelFactory
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import REPO_ROOT
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult

from .app import HostApiDependencies
from .app import create_app


UI_DIST_DIR = REPO_ROOT / "apps" / "openzyme-web-ui" / "dist"
SQLITE_DB_PATH = REPO_ROOT / ".tmp" / "openzyme-demo.sqlite3"


@dataclass(slots=True)
class DemoExecutionAdapter:
    _episode_call_counts: dict[str, int] = field(default_factory=dict)

    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> ExecutionOutcome:
        call_count = self._episode_call_counts.get(episode_id, 0) + 1
        self._episode_call_counts[episode_id] = call_count
        run_id = f"run_{episode_id}_{call_count}"
        return ExecutionOutcome(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            execution_mode="demo",
            remote_run_dir=f"/demo/{episode_id}/{run_id}",
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


def build_model_factory_from_env() -> OpenAICompatibleChatModelFactory | None:
    settings = get_settings()
    if not settings.llm.enabled or settings.llm.api_key is None:
        return None

    return OpenAICompatibleChatModelFactory(
        model=settings.llm.model,
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        temperature=settings.llm.temperature,
        timeout=settings.llm.timeout,
        max_retries=settings.llm.max_retries,
    )


def build_demo_foundation(*, sqlite_db_path=None) -> RuntimeFoundation:
    settings = get_settings()
    db_path = sqlite_db_path or SQLITE_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_sqlite(str(db_path))
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
        model_factory=build_model_factory_from_env(),
        settings=settings,
    )


def main() -> None:
    settings = get_settings()
    app = create_app(
        HostApiDependencies(
            foundation=build_demo_foundation(),
            graph_builder=build_v2_supervisor_graph,
        ),
        ui_dist_dir=UI_DIST_DIR if UI_DIST_DIR.exists() else None,
    )
    uvicorn.run(
        app,
        host=settings.host_api.bind_host,
        port=settings.host_api.bind_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
