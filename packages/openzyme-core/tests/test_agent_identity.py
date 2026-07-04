from __future__ import annotations

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import Session
from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core.agent_identity import create_agent_member


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories, session_id: str = "sess_001") -> Session:
    session = Session.create(session_id, "proj_001", "Identity", "Test identity")
    repositories.sessions.save(session)
    return session


def test_agent_member_identity_generation_uses_project_global_nicknames() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.agents.save(
        AgentMember(
            agent_id="agent:researcher:manual",
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name="Sagan",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-04-17T10:00:00+00:00",
            updated_at="2026-04-17T10:00:00+00:00",
            nickname="Sagan",
            display_name="Sagan",
            handle="@sagan",
        )
    )

    reporter = create_agent_member(
        repositories,
        session_id=session.session_id,
        role="reporter",
    )

    assert reporter.role == "reporter"
    assert reporter.nickname == "Carson"
    assert reporter.handle == "@carson"
    assert reporter.agent_id.startswith("agent:reporter:")


def test_agent_member_identity_generation_adds_stable_suffix_after_pool_exhaustion() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    agents = [
        create_agent_member(
            repositories,
            session_id=session.session_id,
            role="researcher",
        )
        for _ in range(5)
    ]

    assert [agent.nickname for agent in agents] == [
        "Ada",
        "Curie",
        "Franklin",
        "Turing",
        "Ada-2",
    ]
    assert [agent.handle for agent in agents] == [
        "@ada",
        "@curie",
        "@franklin",
        "@turing",
        "@ada-2",
    ]
