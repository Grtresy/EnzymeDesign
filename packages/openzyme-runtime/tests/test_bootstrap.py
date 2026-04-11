from contextlib import contextmanager

from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite
from openzyme_runtime import validate_runtime_foundation_support


class FakeCheckpointer:
    def __init__(self) -> None:
        self.setup_called = False

    def setup(self) -> None:
        self.setup_called = True


class FakeExecutionAdapter:
    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> dict[str, object]:
        return {"episode_id": episode_id, "payload": payload}


class FakeProjectionLoader:
    def load_workflow_projection(self, episode_id: str) -> dict[str, object]:
        return {"episode_id": episode_id}

    def load_run_projection(self, episode_id: str) -> list[dict[str, object]]:
        return [{"episode_id": episode_id, "kind": "run"}]

    def load_artifact_projection(self, episode_id: str) -> list[dict[str, object]]:
        return [{"episode_id": episode_id, "kind": "artifact"}]

    def load_pending_actions(self, episode_id: str) -> list[dict[str, object]]:
        return [{"episode_id": episode_id, "kind": "approval"}]


@contextmanager
def _fake_open(self: PostgresCheckpointerFactory):
    checkpointer = FakeCheckpointer()
    if self.config.setup_on_bootstrap:
        checkpointer.setup()
    yield checkpointer


def test_postgres_checkpointer_factory_uses_conn_string_and_setup(monkeypatch) -> None:
    calls: list[str] = []

    class FakeSaver:
        @classmethod
        @contextmanager
        def from_conn_string(cls, conn_string: str):
            calls.append(conn_string)
            yield FakeCheckpointer()

    monkeypatch.setattr(
        "openzyme_runtime.checkpointer._load_postgres_saver_class",
        lambda: FakeSaver,
    )
    factory = PostgresCheckpointerFactory(
        PostgresCheckpointerConfig(
            conn_string="postgresql://postgres:postgres@localhost/openzyme",
            setup_on_bootstrap=True,
        )
    )

    with factory.open() as checkpointer:
        assert checkpointer.setup_called is True

    assert calls == ["postgresql://postgres:postgres@localhost/openzyme"]


def test_runtime_facade_binds_repositories_checkpointer_and_internal_seams(monkeypatch) -> None:
    monkeypatch.setattr("openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open", _fake_open)

    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    foundation = RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://runtime/foundation")
        ),
        execution_adapter=FakeExecutionAdapter(),
        projection_loader=FakeProjectionLoader(),
    )
    facade = GraphRuntimeFacade(foundation)

    with facade.compile_graph(
        lambda inputs: {
            "checkpointer_setup_called": inputs.checkpointer.setup_called,
            "repository_bundle": inputs.repositories,
            "execution_adapter": inputs.execution_adapter,
            "projection_loader": inputs.projection_loader,
        }
    ) as compiled:
        assert compiled["checkpointer_setup_called"] is True
        assert compiled["repository_bundle"] is repositories
        assert compiled["execution_adapter"] is foundation.execution_adapter
        assert compiled["projection_loader"] is foundation.projection_loader

    assert facade.build_episode_graph_config("ep_001") == {"configurable": {"thread_id": "ep_001"}}
    assert build_episode_graph_config("ep_002") == {"configurable": {"thread_id": "ep_002"}}


def test_runtime_foundation_support_alignment_covers_later_phase_b_changes() -> None:
    validate_runtime_foundation_support()
