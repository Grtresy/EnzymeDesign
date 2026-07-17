from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import ArtifactBoundaryError
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import register_bio_research_tools
from openzyme_domain import Session
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_research import BioResearchService
from openzyme_research import BoundedHttpClient
from openzyme_research import DefaultBioResearchService
from openzyme_research import DeterministicBioResearchService
from openzyme_research import ProviderAttempt
from openzyme_research import ProviderProvenance
from openzyme_research import failed_result


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


def _context(
    repositories: CoreRepositories,
    session: Session,
    *,
    service: BioResearchService | None = None,
    artifact_blob_root: Path | None = None,
) -> SessionRuntimeContext:
    registry = ToolRegistry()
    register_bio_research_tools(
        registry,
        service=service or DeterministicBioResearchService(),
    )
    return SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
        artifact_blob_root=artifact_blob_root,
    )


def test_bio_research_tools_do_not_install_implicit_fixture_service() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    register_bio_research_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_unconfigured_bio",
            tool_name="uniprot.lookup",
            arguments={"accession": "P12345"},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.error_code == "unknown_tool"


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
    assert metadata["source"] == "external_provider_artifact_boundary"
    assert metadata["storage_model"] == "sealed_blob"
    assert metadata["provenance"]["provider"] == provider
    assert metadata["provenance"]["external_id"] == external_id
    assert metadata["provenance"]["source_locator"] == metadata["source_locator"]
    assert metadata["provenance"]["format"] == artifact_format
    assert metadata["provenance"]["retrieved_at"] == metadata["retrieved_at"]
    assert metadata["provenance"]["digest"] == actual_digest
    assert metadata["provenance"]["request_digest"].startswith("sha256:")
    assert metadata["provenance"]["response_digest"] == actual_digest
    assert metadata["provenance"]["sealed_digest"] == actual_digest
    assert Path(artifact.storage_uri).stat().st_mode & 0o222 == 0

    payload = json.loads(result.content)
    payload_artifact = payload["artifacts"][0]
    assert payload_artifact["artifact_id"] == artifact.artifact_id
    assert payload_artifact["content_digest"] == actual_digest
    assert payload_artifact["sealed_digest"] == actual_digest
    assert payload_artifact["metadata"]["content_digest"] == actual_digest
    assert "storage_uri" not in json.dumps(payload_artifact)


def test_literature_provider_failure_is_persisted_before_returning_tool_error() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(
            request.full_url,
            429,
            "rate limited",
            {"Retry-After": "0"},
            BytesIO(),
        )

    service = DefaultBioResearchService(
        http_client=BoundedHttpClient(
            opener=opener,
            sleeper=lambda delay: None,
            max_attempts=3,
        )
    )
    context = _context(repositories, session, service=service)

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_pubmed_rate_limited",
            tool_name="pubmed.search",
            arguments={"query": "alternative oxidase", "limit": 5},
            task_id="task_001",
        ),
    )

    assert calls == 3
    assert result.ok is False
    assert result.error_code == "provider_rate_limited"
    assert "rate limited" not in result.content.lower()
    invocations = repositories.invocations.list_by_session(session.session_id)
    assert len(invocations) == 1
    assert invocations[0].status is EngineInvocationStatus.FAILED
    assert invocations[0].input_ref is not None
    assert invocations[0].output_ref is not None
    output = repositories.engine_documents.get(invocations[0].output_ref)
    assert output is not None
    assert output.payload["status"] == "failed"
    provider_call = output.payload["raw_ref"]["provider_call"]
    assert provider_call["failure"]["error_code"] == "provider_rate_limited"
    assert provider_call["provenance"]["attempt_count"] == 3
    artifact = repositories.artifacts.list_by_invocation(
        session.session_id,
        invocations[0].invocation_id,
    )[0]
    assert artifact.metadata["storage_model"] == "sealed_blob"
    assert Path(artifact.storage_uri).stat().st_mode & 0o222 == 0
    assert json.loads(Path(artifact.storage_uri).read_text())["failure"][
        "error_code"
    ] == "provider_rate_limited"


def test_enrichment_rate_limit_is_terminal_degradation_not_synthetic_failure() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    def opener(request, timeout):
        del timeout
        raise HTTPError(
            request.full_url,
            429,
            "contains provider secret",
            {"Retry-After": "0"},
            BytesIO(),
        )

    service = DefaultBioResearchService(
        semantic_scholar_api_key="semantic-private-key",
        http_client=BoundedHttpClient(
            opener=opener,
            sleeper=lambda delay: None,
            max_attempts=2,
        ),
    )
    context = _context(repositories, session, service=service)

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_semantic_degraded",
            tool_name="semantic_scholar.search",
            arguments={"query": "alternative oxidase", "limit": 5},
            task_id="task_001",
        ),
    )

    assert result.ok is True
    assert result.status == "degraded"
    payload = json.loads(result.content)
    assert payload["status"] == "partial"
    assert payload["findings"] == []
    assert payload["raw_ref"]["provider_call"]["failure"]["error_code"] == (
        "provider_rate_limited"
    )
    invocation = repositories.invocations.list_by_session(session.session_id)[0]
    assert invocation.status is EngineInvocationStatus.SUCCEEDED
    public = json.dumps(
        SessionProjectionBuilder(repositories)
        .build_session_workspace(session.session_id)
        .to_dict(),
        sort_keys=True,
    )
    assert "semantic-private-key" not in public
    assert "contains provider secret" not in public


def test_required_pubmed_empty_result_fails_closed_and_seals_absence() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    class EmptyResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"esearchresult":{"idlist":[]}}'

    service = DefaultBioResearchService(
        http_client=BoundedHttpClient(
            opener=lambda request, timeout: EmptyResponse(),
            sleeper=lambda delay: None,
        )
    )
    context = _context(repositories, session, service=service)

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_pubmed_empty",
            tool_name="pubmed.search",
            arguments={"query": "bounded AOX query", "limit": 5},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.status == "required_provider_empty"
    assert result.error_code == "required_provider_empty"
    payload = json.loads(result.content)
    assert payload["status"] == "failed"
    assert payload["findings"] == []
    assert payload["unresolved_gaps"] == [
        "pubmed returned no records for the required query"
    ]
    quorum = payload["raw_ref"]["call_local_literature_quorum"]
    assert quorum["status"] == "failed"
    assert quorum["cutover_eligible"] is False
    invocation = repositories.invocations.list_by_session(session.session_id)[0]
    assert invocation.status is EngineInvocationStatus.FAILED
    artifact = repositories.artifacts.list_by_invocation(
        session.session_id,
        invocation.invocation_id,
    )[0]
    assert artifact.metadata["cutover_eligible"] is False
    sealed = json.loads(Path(artifact.storage_uri).read_text())
    assert sealed["outcome"] == "empty"
    assert sealed["call_local_literature_quorum"]["status"] == "failed"


def test_fixture_pubmed_result_cannot_satisfy_direct_tool_quorum() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = _context(
        repositories,
        session,
        service=DeterministicBioResearchService(),
    )

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_pubmed_fixture",
            tool_name="pubmed.search",
            arguments={"query": "alternative oxidase", "limit": 5},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.error_code == "fixture_non_cutover"
    invocation = repositories.invocations.list_by_session(session.session_id)[0]
    assert invocation.status is EngineInvocationStatus.FAILED
    output = repositories.engine_documents.get(invocation.output_ref or "")
    assert output is not None
    assert output.payload["findings"] == []
    assert output.payload["raw_ref"]["call_local_literature_quorum"][
        "cutover_eligible"
    ] is False
    artifact = repositories.artifacts.list_by_invocation(
        session.session_id,
        invocation.invocation_id,
    )[0]
    assert artifact.metadata["cutover_eligible"] is False


def test_typed_failed_provider_result_cannot_complete_tool_invocation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    class TypedFailedService(DeterministicBioResearchService):
        def search_pubmed_result(self, *, query: str, limit: int):
            del query, limit
            timestamp = "2026-07-17T00:00:00+00:00"
            return failed_result(
                provenance=ProviderProvenance(
                    provider="pubmed",
                    operation="literature.search",
                    endpoint_id="pubmed.esearch:v1",
                    request_digest="sha256:" + "1" * 64,
                    retrieved_at=timestamp,
                    attempt_count=1,
                    attempts=(
                        ProviderAttempt(
                            attempt=1,
                            started_at=timestamp,
                            finished_at=timestamp,
                            outcome="failed",
                            status_code=503,
                            error_code="provider_unavailable",
                        ),
                    ),
                    response_status=503,
                ),
                error_code="provider_unavailable",
                message="pubmed is unavailable",
                retryable=True,
                status_code=503,
            )

    context = _context(
        repositories,
        session,
        service=TypedFailedService(),
    )

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_pubmed_typed_failed",
            tool_name="pubmed.search",
            arguments={"query": "alternative oxidase", "limit": 5},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.error_code == "provider_unavailable"
    invocation = repositories.invocations.list_by_session(session.session_id)[0]
    assert invocation.status is EngineInvocationStatus.FAILED
    artifact = repositories.artifacts.list_by_invocation(
        session.session_id,
        invocation.invocation_id,
    )[0]
    assert artifact.metadata["provider_outcome"] == "failed"
    assert artifact.metadata["cutover_eligible"] is False


def test_literature_evidence_seal_failure_terminates_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    class EmptyResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"esearchresult":{"idlist":[]}}'

    service = DefaultBioResearchService(
        http_client=BoundedHttpClient(
            opener=lambda request, timeout: EmptyResponse(),
            sleeper=lambda delay: None,
        )
    )
    context = _context(repositories, session, service=service)

    def fail_seal(*args, **kwargs):
        del args, kwargs
        raise ArtifactBoundaryError("artifact_seal_failed", "private host failure")

    monkeypatch.setattr(
        "openzyme_core.bio_research_tools.ArtifactBoundaryService.seal_external_bytes",
        fail_seal,
    )

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_pubmed_seal_failure",
            tool_name="pubmed.search",
            arguments={"query": "bounded AOX query", "limit": 5},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.error_code == "artifact_seal_failed"
    assert "private host failure" not in result.content
    invocation = repositories.invocations.list_by_session(session.session_id)[0]
    assert invocation.status is EngineInvocationStatus.FAILED
    assert invocation.output_ref is not None
    assert repositories.artifacts.list_by_invocation(
        session.session_id, invocation.invocation_id
    ) == []


def test_pubmed_evidence_round_trips_repository_sealing_and_safe_projection(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    responses = iter(
        (
            {"esearchresult": {"idlist": ["12345"]}},
            {
                "result": {
                    "uids": ["12345"],
                    "12345": {
                        "uid": "12345",
                        "title": "Alternative oxidase evidence",
                        "pubdate": "2024 Jan",
                        "fulljournalname": "Plant Physiology",
                        "authors": [{"name": "Doe J", "authtype": "Author"}],
                        "articleids": [
                            {"idtype": "pubmed", "value": "12345"},
                            {"idtype": "doi", "value": "10.1000/aox.1"},
                        ],
                    },
                }
            },
        )
    )

    class JsonResponse:
        status = 200
        headers = {
            "Content-Type": "application/json",
            "X-Request-Id": "request-public",
            "Authorization": "response-secret",
        }

        def __init__(self, payload: dict[str, object]) -> None:
            self.body = json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.body

    def opener(request, timeout):
        del request, timeout
        running = repositories.invocations.list_by_session(session.session_id)
        assert len(running) == 1
        assert running[0].status is EngineInvocationStatus.RUNNING
        return JsonResponse(next(responses))

    service = DefaultBioResearchService(
        pubmed_email="ncbi-private@example.org",
        pubmed_api_key="pubmed-private-key",
        http_client=BoundedHttpClient(
            opener=opener,
            sleeper=lambda delay: None,
        ),
    )
    artifact_blob_root = tmp_path / "attempt-blobs"
    context = _context(
        repositories,
        session,
        service=service,
        artifact_blob_root=artifact_blob_root,
    )

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_pubmed_round_trip",
            tool_name="pubmed.search",
            arguments={"query": "alternative oxidase", "limit": 5},
            task_id="task_001",
        ),
    )

    assert result.ok is True
    invocation = repositories.invocations.list_by_session(session.session_id)[0]
    assert invocation.status is EngineInvocationStatus.SUCCEEDED
    artifact = repositories.artifacts.list_by_invocation(
        session.session_id,
        invocation.invocation_id,
    )[0]
    assert artifact.metadata["schema_version"] == "provider_literature_evidence@1"
    assert artifact.metadata["storage_model"] == "sealed_blob"
    assert artifact.metadata["cutover_eligible"] is True
    assert artifact.metadata["quorum_status"] == "degraded"
    assert Path(artifact.storage_uri).resolve().is_relative_to(
        artifact_blob_root.resolve()
    )
    sealed_payload = json.loads(Path(artifact.storage_uri).read_text())
    assert sealed_payload["call_local_literature_quorum"]["cutover_eligible"] is True
    assert sealed_payload["provenance"]["provider_identity"][
        "identity_digest"
    ].startswith("sha256:")
    assert sealed_payload["citations"][0] == {
        "authors": [{"author_type": "Author", "name": "Doe J"}],
        "doi": "10.1000/aox.1",
        "external_id": "PMID:12345",
        "locator": "https://pubmed.ncbi.nlm.nih.gov/12345/",
        "pmid": "12345",
        "provider": "pubmed",
        "publication_date": "2024 Jan",
        "title": "Alternative oxidase evidence",
        "venue": "Plant Physiology",
        "year": 2024,
    }
    source = repositories.research_source_refs.list_by_invocation(
        session.session_id,
        invocation.invocation_id,
    )[0]
    assert source.provider == "pubmed"
    assert source.external_id == "PMID:12345"
    assert source.pmid == "12345"
    assert source.doi == "10.1000/aox.1"
    assert source.authors == ({"name": "Doe J", "author_type": "Author"},)
    assert source.venue == "Plant Physiology"
    assert source.publication_date == "2024 Jan"
    assert source.request_digest.startswith("sha256:")
    assert source.response_digest.startswith("sha256:")
    assert source.evidence_artifact_id == artifact.artifact_id
    workspace = SessionProjectionBuilder(repositories).build_session_workspace(
        session.session_id
    ).to_dict()
    public = json.dumps(workspace, sort_keys=True)
    assert source.pmid in public
    assert source.doi in public
    assert "pubmed-private-key" not in public
    assert "ncbi-private@example.org" not in public
    assert "response-secret" not in public
    assert artifact.storage_uri not in public
