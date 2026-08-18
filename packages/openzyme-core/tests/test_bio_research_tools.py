from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from openzyme_core import AgentCapsuleProcessResult
from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import WorkspaceFileHandoffError
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
            return AgentCapsuleProcessResult(
                0,
                f"OPENZYME_CLEANUP_PATH={argv[-1]}\n",
                "",
            )
        raise AssertionError("unexpected capsule writer command")


class _FailingWorkspaceProcessRunner(_WorkspaceProcessRunner):
    def run(self, **kwargs) -> AgentCapsuleProcessResult:
        argv = kwargs["argv"]
        if "encoded_chunk" in argv[4]:
            raise RuntimeError("injected capsule failure")
        return super().run(**kwargs)


class _ScriptedWorkspaceProcessRunner(_WorkspaceProcessRunner):
    def __init__(
        self,
        *,
        primary_phase: str | None = None,
        primary_kind: str = "exception",
        cleanup_kind: str | None = None,
        preserve_post_effect_residue: bool = False,
    ) -> None:
        super().__init__()
        self.primary_phase = primary_phase
        self.primary_kind = primary_kind
        self.cleanup_kind = cleanup_kind
        self.preserve_post_effect_residue = preserve_post_effect_residue

    @staticmethod
    def _phase(script: str) -> str:
        if "noclobber" in script:
            return "initialize"
        if "encoded_chunk" in script:
            return "append"
        if "OPENZYME_PATH" in script:
            return "finalize"
        if "rm -f" in script:
            return "cleanup"
        raise AssertionError("unexpected capsule writer command")

    def run(self, **kwargs) -> AgentCapsuleProcessResult:
        argv = kwargs["argv"]
        phase = self._phase(argv[4])
        if phase == self.primary_phase:
            if self.primary_kind == "exception":
                raise RuntimeError(f"injected {phase} exception")
            return AgentCapsuleProcessResult(
                73,
                f"{phase}-stdout",
                f"{phase}-stderr",
            )
        if phase == "cleanup" and self.cleanup_kind is not None:
            if self.cleanup_kind == "exception":
                raise OSError("injected cleanup exception")
            return AgentCapsuleProcessResult(74, "cleanup-stdout", "cleanup-stderr")
        result = super().run(**kwargs)
        if phase == "finalize" and self.preserve_post_effect_residue:
            temporary_path = argv[-2]
            self.temporary[temporary_path] = bytearray(b"residue")
        return result


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
    assert written.cleanup_result is not None
    assert written.cleanup_result.completed is True
    assert written.cleanup_result.temporary_path.startswith(
        "research/large/.openzyme-write-"
    )


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
    assert result.failure_observation is not None
    assert result.failure_observation["component"] == (
        "openzyme_core.workspace_file_handoffs"
    )
    assert result.failure_observation["operation"] == "append"
    assert result.failure_observation["effect_certainty"] == "no_effect"
    assert result.failure_observation["mutation_applied"] is False
    assert result.failure_observation["fallback_performed"] is False
    assert result.failure_observation["cause_chain"][0]["type"] == (
        "WorkspaceFileHandoffError"
    )
    private = repositories.private_diagnostics.get_for_operator(
        result.failure_observation["diagnostic_id"],
        operator_authorized=True,
    )
    assert private is not None
    assert private.private_context["phase"] == "append"
    assert private.private_context["cleanup"]["completed"] is True
    assert [
        item["role"] for item in private.private_context["ordered_failures"]
    ] == ["primary"]
    assert invocation.status is EngineInvocationStatus.FAILED
    assert invocation.output_ref is None
    assert runner.temporary == {}
    assert runner.files == {}


@pytest.mark.parametrize("phase", ["initialize", "append", "finalize"])
@pytest.mark.parametrize("failure_kind", ["exception", "nonzero"])
def test_workspace_write_phase_failure_has_diagnostic_cleanup_result(
    phase: str,
    failure_kind: str,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, _ = _context(repositories, session)
    runner = _ScriptedWorkspaceProcessRunner(
        primary_phase=phase,
        primary_kind=failure_kind,
    )
    context.agent_capsule_process_runner = runner

    with pytest.raises(WorkspaceFileHandoffError) as caught:
        write_bytes_to_current_agent_workspace(
            context,
            repository_path="research/result.bin",
            content=b"bounded-result",
        )

    error = caught.value
    assert error.phase == phase
    assert error.error_code == "workspace_file_handoff_failed"
    assert error.mutation_applied is False
    assert error.fallback_performed is False
    assert error.cleanup_result is not None
    assert error.cleanup_result.completed is True
    assert error.temporary_path == error.cleanup_result.temporary_path
    assert error.diagnostic_context["ordered_failures"] == [
        {
            "order": 1,
            "role": "primary",
            "type": error.primary_failure.__class__.__qualname__,
            "message": str(error.primary_failure),
            "error_code": getattr(error.primary_failure, "error_code", None),
        }
    ]
    assert caught.value.__cause__ is error.primary_failure
    assert runner.temporary == {}
    assert runner.files == {}


@pytest.mark.parametrize("cleanup_kind", ["exception", "nonzero"])
def test_workspace_write_orders_primary_then_cleanup_failure(
    cleanup_kind: str,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, _ = _context(repositories, session)
    runner = _ScriptedWorkspaceProcessRunner(
        primary_phase="append",
        primary_kind="exception",
        cleanup_kind=cleanup_kind,
    )
    context.agent_capsule_process_runner = runner

    with pytest.raises(WorkspaceFileHandoffError) as caught:
        write_bytes_to_current_agent_workspace(
            context,
            repository_path="research/result.bin",
            content=b"bounded-result",
        )

    error = caught.value
    assert error.error_code == "workspace_file_cleanup_incomplete"
    assert error.cleanup_result is not None
    assert error.cleanup_result.completed is False
    assert error.cleanup_result.failure_kind == (
        "exception" if cleanup_kind == "exception" else "nonzero_exit"
    )
    ordered = error.diagnostic_context["ordered_failures"]
    assert [item["role"] for item in ordered] == ["primary", "cleanup"]
    assert [item["order"] for item in ordered] == [1, 2]
    assert error.temporary_path in runner.temporary
    assert error.temporary_path in str(error)


@pytest.mark.parametrize("cleanup_kind", ["exception", "nonzero"])
def test_workspace_write_reports_successful_effect_with_cleanup_residue(
    cleanup_kind: str,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context, _ = _context(repositories, session)
    runner = _ScriptedWorkspaceProcessRunner(
        cleanup_kind=cleanup_kind,
        preserve_post_effect_residue=True,
    )
    context.agent_capsule_process_runner = runner

    with pytest.raises(WorkspaceFileHandoffError) as caught:
        write_bytes_to_current_agent_workspace(
            context,
            repository_path="research/result.bin",
            content=b"bounded-result",
        )

    error = caught.value
    assert error.error_code == "workspace_file_cleanup_incomplete"
    assert error.phase == "post_effect_cleanup"
    assert error.mutation_applied is True
    assert error.fallback_performed is False
    assert error.cleanup_result is not None
    assert error.cleanup_result.completed is False
    assert error.temporary_path == error.cleanup_result.temporary_path
    assert runner.files["research/result.bin"] == b"bounded-result"
    assert runner.temporary[error.temporary_path] == bytearray(b"residue")
