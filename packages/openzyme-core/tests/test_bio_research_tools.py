from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace

from openzyme_core import AgentCapsuleProcessResult
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
from openzyme_core import write_bytes_to_current_agent_workspace
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_research import DeterministicBioResearchService


class _WorkspaceRepository:
    def __init__(self, workspace: object) -> None:
        self.workspace = workspace

    def get_current(self, *, session_id: str, agent_member_id: str) -> object:
        assert session_id == "sess_001"
        assert agent_member_id == "member_researcher"
        return self.workspace


class _WorkspaceProcessRunner:
    def __init__(self) -> None:
        self.temporary: dict[str, bytearray] = {}
        self.files: dict[str, bytes] = {}

    def run(
        self,
        *,
        workspace: object,
        argv: tuple[str, ...],
        credential_environment: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> AgentCapsuleProcessResult:
        del workspace, credential_environment, timeout_seconds
        script = argv[4]
        if "noclobber" in script:
            self.temporary[argv[-1]] = bytearray()
            return AgentCapsuleProcessResult(0, "", "")
        if "encoded_chunk" in script:
            temporary_path = argv[6]
            for encoded_chunk in argv[7:]:
                self.temporary[temporary_path].extend(base64.b64decode(encoded_chunk))
            return AgentCapsuleProcessResult(0, "", "")
        if "OPENZYME_PATH" in script:
            repository_path, temporary_path, expected_digest = argv[-3:]
            content = bytes(self.temporary.pop(temporary_path))
            assert hashlib.sha256(content).hexdigest() == expected_digest
            self.files[repository_path] = content
            return AgentCapsuleProcessResult(
                0,
                (
                    f"OPENZYME_PATH={repository_path}\n"
                    f"OPENZYME_SHA256={expected_digest}\n"
                ),
                "",
            )
        if "rm -f" in script:
            self.temporary.pop(argv[-1], None)
            return AgentCapsuleProcessResult(0, "", "")
        raise AssertionError("unexpected capsule writer command")


class _FailingWorkspaceProcessRunner(_WorkspaceProcessRunner):
    def run(self, **kwargs) -> AgentCapsuleProcessResult:
        argv = kwargs["argv"]
        if "encoded_chunk" in argv[4]:
            raise RuntimeError("injected capsule failure")
        return super().run(**kwargs)


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Research tools",
        objective="Write provider results into the researcher workspace.",
        status=SessionStatus.ACTIVE,
        created_at="2026-08-17T00:00:00+00:00",
        updated_at="2026-08-17T00:00:00+00:00",
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
            assigned_ref="agent:researcher",
            created_at="2026-08-17T00:00:01+00:00",
            updated_at="2026-08-17T00:00:01+00:00",
        )
    )
    repositories.agents.save(
        AgentMember(
            member_id="member_researcher",
            agent_id="agent:researcher",
            session_id=session.session_id,
            lane_id=None,
            task_id="task_001",
            name="Researcher",
            role="researcher",
            status=AgentMemberStatus.ACTIVE,
            created_at="2026-08-17T00:00:02+00:00",
            updated_at="2026-08-17T00:00:02+00:00",
        )
    )
    return session


def _context(
    repositories: CoreRepositories,
    session: Session,
) -> tuple[SessionRuntimeContext, _WorkspaceProcessRunner]:
    registry = ToolRegistry()
    register_bio_research_tools(
        registry,
        service=DeterministicBioResearchService(),
    )
    workspace = SimpleNamespace(
        workspace_id="workspace_1",
        workspace_generation=1,
        status=AgentGitWorkspaceStatus.READY,
    )
    repositories.agent_git_workspaces = _WorkspaceRepository(workspace)  # type: ignore[assignment]
    runner = _WorkspaceProcessRunner()
    return (
        SessionRuntimeContext(
            repositories=repositories,
            event_sink=MemoryEventBus(),
            snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
            tool_registry=registry,
            restore_focus=RestoreFocus(task_id="task_001"),
            agent_id="agent:researcher",
            agent_capsule_process_runner=runner,
        ),
        runner,
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


def test_download_writes_workspace_files_without_secondary_record() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, runner = _context(repositories, session)

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_fasta",
            tool_name="uniprot.download_fasta",
            arguments={"accession": "P12345"},
            task_id="task_001",
        ),
    )

    assert result.ok is True
    payload = json.loads(result.content)
    observation_path = payload["workspace_file"]["repository_path"]
    assert observation_path.endswith("/observations/observation.json")
    observation = json.loads(runner.files[observation_path])
    download_path = observation["raw_ref"]["workspace_files"][0][
        "repository_path"
    ]
    assert download_path.endswith("/downloads/P12345.fasta")
    assert runner.files[download_path].startswith(b">P12345")
    assert repositories.research_summaries.list_by_session(session.session_id) == []


def test_provider_observation_engine_document_is_bounded_file_index() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, runner = _context(repositories, session)

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_lookup",
            tool_name="uniprot.lookup",
            arguments={"accession": "P12345"},
            task_id="task_001",
        ),
    )

    assert result.ok is True
    invocation = repositories.invocations.list_by_task(
        session.session_id, "task_001"
    )[0]
    output = repositories.engine_documents.get(invocation.output_ref or "")
    assert output is not None
    assert output.document_kind == "research_tool_file_index"
    assert set(output.payload) == {"schema_version", "tool_name", "workspace_file"}
    output_path = output.payload["workspace_file"]["repository_path"]
    assert output_path in runner.files
    assert "findings" not in output.payload


def test_research_argument_metadata_is_bounded_before_provider_call() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, _ = _context(repositories, session)

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_oversized",
            tool_name="uniprot.lookup",
            arguments={"accession": "P" * 9_000},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert "bounded metadata limit" in result.content


def test_workspace_file_writer_chunks_large_content_and_publishes_no_alias() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, runner = _context(repositories, session)
    content = b"research-result\n" * 100_000

    written = write_bytes_to_current_agent_workspace(
        context,
        repository_path="research/large/tool-result.bin",
        content=content,
    )

    assert runner.files[written.repository_path] == content
    assert written.content_digest == (
        f"sha256:{hashlib.sha256(content).hexdigest()}"
    )
    assert written.commit_performed is False
    assert written.publication_performed is False


def test_workspace_write_failure_cleans_temporary_and_fails_invocation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, _ = _context(repositories, session)
    runner = _FailingWorkspaceProcessRunner()
    context.agent_capsule_process_runner = runner

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_write_failure",
            tool_name="uniprot.lookup",
            arguments={"accession": "P12345"},
            task_id="task_001",
        ),
    )

    invocation = repositories.invocations.list_by_task(
        session.session_id, "task_001"
    )[0]
    assert result.ok is False
    assert result.error_code == "workspace_file_handoff_failed"
    assert invocation.status is EngineInvocationStatus.FAILED
    assert invocation.output_ref is None
    assert runner.temporary == {}
    assert runner.files == {}
