from __future__ import annotations

from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import ProtocolService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import RunStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_engines import ExecutionEngine
from openzyme_engines import register_execution_tools
from openzyme_engines.execution import PreprocessArtifactDraft
from openzyme_engines.execution import PreprocessResult


class ImmediateSuccessRunner:
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionArtifactRef
        from openzyme_engines.execution import ExecutionOutcome

        del session_id
        expected_outputs = list((dict(payload.get("runspec") or {}).get("expected_outputs") or []))
        relative_path = str((expected_outputs[0] if expected_outputs else {}).get("path") or "stdout.log")
        kind = ArtifactKind.LOG if relative_path.endswith(".log") else ArtifactKind.RESULT
        if relative_path.endswith((".pdb", ".pdbqt", ".sdf", ".mol2", ".cif")):
            kind = ArtifactKind.STRUCTURE
        return ExecutionOutcome(
            run_id="runner_run_001",
            status=RunStatus.SUCCEEDED,
            execution_mode="ssh",
            remote_run_dir="/remote/run_001",
            raw_result={"pockets_found": 2},
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri=f"/tmp/{relative_path}",
                    relative_path=relative_path,
                    kind=kind,
                ),
            ),
        )

    def get_execution_status(self, *, run_id: str, remote_run_dir: str, job_id: str | None = None):  # type: ignore[no-untyped-def]
        raise AssertionError("status polling should not be used for immediate execution")

    def fetch_execution_artifacts(self, *, run_id: str, remote_run_dir: str, runspec: dict[str, object], job_id: str | None = None):  # type: ignore[no-untyped-def]
        raise AssertionError("fetch should not be used for immediate execution")

    def cancel_execution(self, *, run_id: str, remote_run_dir: str, job_id: str | None = None):  # type: ignore[no-untyped-def]
        raise AssertionError("cancel should not be used in this test")


class BackgroundRunner:
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, payload
        return ExecutionOutcome(
            run_id="runner_job_123",
            status=RunStatus.QUEUED,
            execution_mode="sbatch",
            remote_run_dir="/remote/run_bg",
            raw_result={"submitted": True},
            job_id="runner_job_123",
        )

    def get_execution_status(self, *, run_id: str, remote_run_dir: str, job_id: str | None = None):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionStatusSnapshot

        del remote_run_dir, job_id
        return ExecutionStatusSnapshot(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            remote_run_dir="/remote/run_bg",
            raw_result={"state": "completed", "pockets_found": 1},
            job_id="runner_job_123",
            exit_code=0,
        )

    def fetch_execution_artifacts(self, *, run_id: str, remote_run_dir: str, runspec: dict[str, object], job_id: str | None = None):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionArtifactRef
        from openzyme_engines.execution import ExecutionOutcome

        del remote_run_dir, job_id
        expected_outputs = list((runspec or {}).get("expected_outputs") or [])
        relative_path = str((expected_outputs[0] if expected_outputs else {}).get("path") or "result.json")
        return ExecutionOutcome(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            execution_mode="sbatch",
            remote_run_dir="/remote/run_bg",
            raw_result={"pockets_found": 1},
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri=f"/tmp/{relative_path}",
                    relative_path=relative_path,
                    kind=ArtifactKind.RESULT,
                ),
            ),
            job_id="runner_job_123",
            exit_code=0,
        )

    def cancel_execution(self, *, run_id: str, remote_run_dir: str, job_id: str | None = None):  # type: ignore[no-untyped-def]
        raise AssertionError("cancel should not be used in this test")


class CapturingSuccessRunner(ImmediateSuccessRunner):
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        self.payloads.append(payload)
        return super().submit_execution(session_id, payload)


class FakeVinaPreprocessAdapter:
    def preprocess_for_execution(
        self,
        *,
        session_id: str,
        invocation_id: str,
        handoff,
        required_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> PreprocessResult:
        del session_id, handoff
        return PreprocessResult(
            required_artifacts=required_artifacts,
            created_artifacts=(
                PreprocessArtifactDraft(
                    source_artifact_id="art_001",
                    operation="prepare_receptor",
                    storage_uri="/tmp/preprocess/receptor.pdbqt",
                    relative_path=f"preprocess/{invocation_id}/receptor.pdbqt",
                    input_format="pdb",
                    output_format="pdbqt",
                    tool="fake-preprocess",
                    metadata={"fake": True},
                ),
            ),
        )


class InjectingCompiler:
    def compile_request(self, *, handoff, task, resolved_required_artifacts, resolved_context_artifacts):  # type: ignore[no-untyped-def]
        del handoff, task, resolved_required_artifacts, resolved_context_artifacts
        return {
            "tool_name": "exec.run",
            "runspec": {
                "name": "bad",
                "stage": "execution",
                "command": ["cat", "/work/input.pdb"],
                "inputs": [
                    {
                        "artifact_id": "art_001",
                        "local_path": "/etc/passwd",
                        "remote_path": "input.pdb",
                    }
                ],
                "expected_outputs": [],
                "metadata": {},
            },
        }


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Execution",
        objective="Run execution engine",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-20T12:00:00+00:00",
        updated_at="2026-04-20T12:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name="wt/analysis",
            claimed_ref="agent:planner",
            created_at="2026-04-20T12:00:01+00:00",
            updated_at="2026-04-20T12:00:01+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Execute fpocket",
            description="Evaluate the focused structure.",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="execution",
            assigned_ref="agent:planner",
            created_at="2026-04-20T12:00:02+00:00",
            updated_at="2026-04-20T12:00:02+00:00",
            lane_id="lane_001",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="seed_invocation",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="seed",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="seed:artifact",
            started_at="2026-04-20T12:00:02+00:00",
            finished_at="2026-04-20T12:00:03+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/input_structure.pdb",
            relative_path="input_structure.pdb",
            title="input_structure.pdb",
            description=None,
            metadata={"source": "seed"},
            created_at="2026-04-20T12:00:03+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_002",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/ligand.pdbqt",
            relative_path="ligand.pdbqt",
            title="ligand.pdbqt",
            description=None,
            metadata={"source": "seed"},
            created_at="2026-04-20T12:00:03+00:00",
        )
    )
    return session


def test_execution_engine_waits_for_approval_before_submitting() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    started = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_001",
    )

    assert started.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert started.approval is not None
    assert repositories.runs.list_by_invocation(session.session_id, "inv_exec_001") == []


def test_execution_engine_resumes_after_approval_and_persists_run_and_artifacts() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    first = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_001",
    )
    approval = first.approval
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=approval.request_ref,
            resolution_ref="artifact://approvals/appr_001-resolution.json",
            created_at=approval.created_at,
            resolved_at="2026-04-20T12:00:04+00:00",
        )
    )

    resumed = engine.resume_execution(invocation_id="inv_exec_001", resolution="Approved for launch.")

    assert resumed.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert resumed.run is not None
    assert resumed.run.status is RunStatus.SUCCEEDED
    assert resumed.run.summary == "fpocket found 2 pocket(s) for the selected artifact set."
    assert resumed.parsed_result is not None
    assert (
        resumed.parsed_result.result_summary
        == "fpocket found 2 pocket(s) for the selected artifact set."
    )
    assert resumed.artifacts[0].artifact_id == "run_inv_exec_001:target_out"
    payload = resumed.to_dict()
    assert payload["run"]["summary"] == payload["parsed_result"]["result_summary"]
    assert payload["artifacts"]
    assert repositories.runs.get_by_invocation(session.session_id, "inv_exec_001").summary is not None


def test_execution_engine_resume_keeps_pending_approval_waiting() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    first = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_pending_resume",
    )

    resumed = engine.resume_execution(
        invocation_id="inv_exec_pending_resume",
        resolution="Attempted direct resume.",
    )

    assert first.approval is not None
    assert resumed.approval is not None
    assert resumed.approval.status is ApprovalRequestStatus.PENDING
    assert resumed.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert repositories.invocations.get("inv_exec_pending_resume").status is EngineInvocationStatus.WAITING_APPROVAL
    assert repositories.runs.list_by_invocation(session.session_id, "inv_exec_pending_resume") == []


def test_execution_engine_resume_cancels_rejected_approval() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    first = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_rejected_resume",
    )
    approval = first.approval
    assert approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=ApprovalRequestStatus.REJECTED,
            request_ref=approval.request_ref,
            resolution_ref="artifact://approvals/rejected-resolution.json",
            created_at=approval.created_at,
            resolved_at="2026-04-20T12:00:04+00:00",
        )
    )

    resumed = engine.resume_execution(invocation_id="inv_exec_rejected_resume")

    assert resumed.invocation.status is EngineInvocationStatus.CANCELLED
    assert resumed.approval is not None
    assert resumed.approval.status is ApprovalRequestStatus.REJECTED
    assert repositories.runs.list_by_invocation(session.session_id, "inv_exec_rejected_resume") == []


def test_execution_engine_status_polling_finalizes_background_run() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, BackgroundRunner())

    started = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": False,
        },
        invocation_id="inv_exec_bg",
    )
    status = engine.get_execution_status("inv_exec_bg")

    assert started.invocation.status is EngineInvocationStatus.RUNNING
    assert status["invocation"]["status"] == "succeeded"
    assert status["artifacts"][0]["artifact_id"] == "run_inv_exec_bg:target_out"


def test_execution_engine_compiles_staged_inputs_from_session_artifacts() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(repositories, runner)

    engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": False,
        },
        invocation_id="inv_exec_staging",
    )

    runspec = runner.payloads[0]["runspec"]
    assert runspec["inputs"][0]["artifact_id"] == "art_001"
    assert runspec["inputs"][0]["local_path"] == "/tmp/input_structure.pdb"
    assert runspec["inputs"][0]["remote_path"] == "target.pdb"
    assert runspec["expected_outputs"][0]["path"] == "target_out"
    assert "/tmp/input_structure.pdb" not in " ".join(runspec["command"])


def test_execution_engine_persists_preprocess_artifact_and_stages_it_for_vina() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories,
        runner,
        preprocess_adapter=FakeVinaPreprocessAdapter(),
    )

    result = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Dock ligand",
            "required_artifact_ids": ["art_001", "art_002"],
            "catalog_tool_id": "vina",
            "require_approval": False,
        },
        invocation_id="inv_exec_vina_preprocess",
    )

    runspec = runner.payloads[0]["runspec"]
    assert runspec["inputs"][0]["local_path"] == "/tmp/preprocess/receptor.pdbqt"
    assert runspec["inputs"][1]["local_path"] == "/tmp/ligand.pdbqt"
    preprocess_records = [
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.metadata and artifact.metadata.get("source") == "preprocess"
    ]
    assert [item["artifact_id"] for item in runspec["inputs"]] == [
        preprocess_records[0].artifact_id,
        "art_002",
    ]
    assert preprocess_records[0].metadata["source_artifact_id"] == "art_001"
    assert result.artifacts[0].metadata["preprocess_artifact_ids"] == [
        preprocess_records[0].artifact_id
    ]


def test_execution_engine_rejects_compiled_input_local_path_injection() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        compiler=InjectingCompiler(),
    )

    try:
        engine.start_execution(
            session_id=session.session_id,
            task_id="task_001",
            handoff={
                "execution_goal": "Run an unsafe request",
                "required_artifact_ids": ["art_001"],
                "catalog_tool_id": "fpocket",
                "require_approval": False,
            },
            invocation_id="inv_exec_injection",
        )
    except ValueError as exc:
        assert "local_path" in str(exc)
    else:
        raise AssertionError("unsafe compiled local_path was accepted")


def test_execution_engine_reconcile_closes_background_completion_without_protocol_output_writeback() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, BackgroundRunner())
    protocol = ProtocolService(repositories)

    started = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": False,
        },
        invocation_id="inv_exec_bg_reconcile",
    )
    assert started.invocation.output_ref is None

    protocol.complete_background_task(
        session_id=session.session_id,
        correlation_id="corr_exec_bg",
        recipient="harness",
        payload_ref="artifact://engine/inv_exec_bg_reconcile/background.json",
        invocation_id="inv_exec_bg_reconcile",
        success=True,
    )
    assert repositories.invocations.get("inv_exec_bg_reconcile").output_ref is None

    reconciled = engine.reconcile_execution("inv_exec_bg_reconcile")

    assert reconciled.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert reconciled.invocation.output_ref is not None
    assert reconciled.artifacts[0].artifact_id == "run_inv_exec_bg_reconcile:target_out"


def test_execution_tools_register_with_tool_registry() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    registry = ToolRegistry()
    register_execution_tools(registry, engine)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_001",
            tool_name="execution.start",
            arguments={
                "task_id": "task_001",
                "handoff": {
                    "execution_goal": "Run fpocket on the selected structure",
                    "required_artifact_ids": ["art_001"],
                    "catalog_tool_id": "fpocket",
                    "require_approval": False,
                },
            },
            task_id="task_001",
            lane_id="lane_001",
        ),
    )

    assert result.ok is True
    assert "\"status\": \"succeeded\"" in result.content
