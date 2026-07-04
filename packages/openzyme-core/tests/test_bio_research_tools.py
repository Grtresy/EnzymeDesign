from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import register_bio_research_tools
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_research import DeterministicBioResearchService


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Research tools",
        objective="Download biological artifacts.",
        status=SessionStatus.ACTIVE,
        created_at="2026-07-04T00:00:00+00:00",
        updated_at="2026-07-04T00:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Download inputs",
            description="Download external biological inputs.",
            status=TaskStatus.TODO,
            priority=TaskPriority.NORMAL,
            kind="research",
            assigned_ref=None,
            created_at="2026-07-04T00:00:01+00:00",
            updated_at="2026-07-04T00:00:01+00:00",
        )
    )
    return session


def _context(repositories: CoreRepositories, session: Session) -> SessionRuntimeContext:
    registry = ToolRegistry()
    register_bio_research_tools(
        registry,
        service=DeterministicBioResearchService(),
    )
    return SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
    )


@pytest.mark.parametrize(
    ("tool_name", "arguments", "provider", "external_id", "artifact_format"),
    (
        (
            "rcsb_pdb.download_structure",
            {"pdb_id": "1ABC", "format": "pdb"},
            "rcsb_pdb",
            "1ABC",
            "pdb",
        ),
        (
            "uniprot.download_fasta",
            {"accession": "P12345"},
            "uniprot",
            "P12345",
            "fasta",
        ),
    ),
)
def test_download_research_tools_persist_sealed_artifact_metadata(
    tool_name: str,
    arguments: dict[str, object],
    provider: str,
    external_id: str,
    artifact_format: str,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = _context(repositories, session)

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id=f"call_{tool_name}",
            tool_name=tool_name,
            arguments=arguments,
            task_id="task_001",
        ),
    )

    assert result.ok is True
    artifacts = repositories.artifacts.list_by_task(session.session_id, "task_001")
    assert len(artifacts) == 1
    artifact = artifacts[0]
    metadata = dict(artifact.metadata or {})
    actual_digest = (
        f"sha256:{hashlib.sha256(Path(artifact.storage_uri).read_bytes()).hexdigest()}"
    )
    assert metadata["content_digest"] == actual_digest
    assert metadata["sealed_digest"] == actual_digest
    assert metadata["provider"] == provider
    assert metadata["external_id"] == external_id
    assert metadata["format"] == artifact_format
    assert metadata["source_locator"]
    assert metadata["retrieved_at"]
    assert metadata["provenance"] == {
        "provider": provider,
        "external_id": external_id,
        "source_locator": metadata["source_locator"],
        "format": artifact_format,
        "retrieved_at": metadata["retrieved_at"],
        "digest": actual_digest,
    }

    payload = json.loads(result.content)
    payload_artifact = payload["artifacts"][0]
    assert payload_artifact["artifact_id"] == artifact.artifact_id
    assert payload_artifact["content_digest"] == actual_digest
    assert payload_artifact["sealed_digest"] == actual_digest
    assert payload_artifact["metadata"]["content_digest"] == actual_digest
    assert "storage_uri" not in json.dumps(payload_artifact)
