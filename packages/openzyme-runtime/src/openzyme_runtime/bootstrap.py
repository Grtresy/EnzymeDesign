from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Iterator

from openzyme_storage import GRAPH_STATE_DEPENDENCY_EXPECTATIONS
from openzyme_storage import HOST_UI_DEPENDENCY_EXPECTATIONS
from openzyme_storage import RELATIONAL_RECORDS

from .checkpointer import PostgresCheckpointerFactory
from .repositories import PhaseBRepositories
from .seams import ExecutionAdapter
from .seams import ProjectionLoader
from .seams import ResearchAdapter


GraphBuilder = Callable[["GraphAssemblyInputs"], Any]
GRAPH_THREAD_KEY = "episode_id"


@dataclass(frozen=True, slots=True)
class RuntimeFoundation:
    repositories: PhaseBRepositories
    checkpointer_factory: PostgresCheckpointerFactory
    execution_adapter: ExecutionAdapter | None = None
    research_adapter: ResearchAdapter | None = None
    projection_loader: ProjectionLoader | None = None


@dataclass(frozen=True, slots=True)
class GraphAssemblyInputs:
    repositories: PhaseBRepositories
    checkpointer: Any
    execution_adapter: ExecutionAdapter | None
    research_adapter: ResearchAdapter | None
    projection_loader: ProjectionLoader | None


class GraphRuntimeFacade:
    def __init__(self, foundation: RuntimeFoundation) -> None:
        self._foundation = foundation

    @property
    def repositories(self) -> PhaseBRepositories:
        return self._foundation.repositories

    def build_episode_graph_config(self, episode_id: str) -> dict[str, dict[str, str]]:
        return build_episode_graph_config(episode_id)

    @contextmanager
    def compile_graph(self, builder: GraphBuilder) -> Iterator[Any]:
        with self._foundation.checkpointer_factory.open() as checkpointer:
            yield builder(
                GraphAssemblyInputs(
                    repositories=self._foundation.repositories,
                    checkpointer=checkpointer,
                    execution_adapter=self._foundation.execution_adapter,
                    research_adapter=self._foundation.research_adapter,
                    projection_loader=self._foundation.projection_loader,
                )
            )


def build_episode_graph_config(episode_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": episode_id}}


def validate_runtime_foundation_support() -> None:
    required_records = {"projects", "episodes", "approvals", "runs", "artifact_records"}
    assert required_records.issubset(set(RELATIONAL_RECORDS))
    assert GRAPH_THREAD_KEY == "episode_id"
    assert any("graph anchor" in item for item in GRAPH_STATE_DEPENDENCY_EXPECTATIONS)
    assert any("canonical records" in item for item in HOST_UI_DEPENDENCY_EXPECTATIONS)
