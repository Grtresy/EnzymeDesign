from __future__ import annotations

from pathlib import Path

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


class CapturingFailedRunner(ImmediateSuccessRunner):
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id
        self.payloads.append(payload)
        return ExecutionOutcome(
            run_id="runner_failed_001",
            status=RunStatus.FAILED,
            execution_mode="ssh",
            remote_run_dir="/remote/run_failed",
            raw_result={
                "status": "failed",
                "exit_code": 127,
                "error_code": "APPTAINER_MISSING",
                "stdout": "",
                "stderr": "apptainer: command not found",
            },
            artifacts=(),
            exit_code=127,
        )


class CapturingTimeoutRunner(CapturingFailedRunner):
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id
        self.payloads.append(payload)
        return ExecutionOutcome(
            run_id="runner_timeout_001",
            status=RunStatus.FAILED,
            execution_mode="ssh",
            remote_run_dir="/remote/run_timeout",
            raw_result={
                "status": "failed",
                "exit_code": 124,
                "error_code": "COMMAND_TIMEOUT",
                "stage": "remote_execution",
                "stdout": "",
                "stderr": "Command timed out after 7200 seconds",
            },
            artifacts=(),
            exit_code=124,
        )


class SandboxPreflight:
    def __init__(self, ok: bool, message: str = "ok") -> None:
        self.ok = ok
        self.message = message


class HandlerSandboxRunner:
    def __init__(self, *, preflight_ok: bool = True) -> None:
        self.preflight_ok = preflight_ok
        self.calls = 0

    def preflight(self) -> SandboxPreflight:
        return SandboxPreflight(self.preflight_ok, "podman missing")

    def run_pipeline(self, *, session_id, invocation_id, code, inputs=(), control_handler=None):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        self.calls += 1
        if control_handler is not None:
            control_handler("hpc.fpocket", {"structure_artifact_id": "art_001", "params": {}})
        return ExecutionOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.SUCCEEDED,
            execution_mode="podman",
            remote_run_dir=f"podman://{invocation_id}",
            raw_result={"registered_artifact_count": 0},
            artifacts=(),
        )


class FailedHpcSandboxRunner(HandlerSandboxRunner):
    def __init__(self, stderr_path: Path) -> None:
        super().__init__()
        self.stderr_path = stderr_path

    def run_pipeline(self, *, session_id, invocation_id, code, inputs=(), control_handler=None):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionArtifactRef
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        self.calls += 1
        if control_handler is not None:
            control_handler("hpc.fpocket", {"structure_artifact_id": "art_001", "params": {}})
        self.stderr_path.write_text(
            "openzyme_pipeline.client.PipelineSdkError: "
            f"hpc.fpocket failed with status failed for run run_{invocation_id}_1",
            encoding="utf-8",
        )
        return ExecutionOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.FAILED,
            execution_mode="podman",
            remote_run_dir=f"podman://{invocation_id}",
            raw_result={"registered_artifact_count": 0},
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri=str(self.stderr_path),
                    relative_path="logs/stderr.log",
                    kind=ArtifactKind.LOG,
                ),
            ),
            exit_code=1,
        )


class UnplannedHpcSandboxRunner(HandlerSandboxRunner):
    def run_pipeline(self, *, session_id, invocation_id, code, inputs=(), control_handler=None):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, invocation_id, code, inputs
        self.calls += 1
        if control_handler is not None:
            control_handler("hpc.vina", {"receptor_artifact_id": "art_001", "ligand_artifact_id": "art_001", "params": {}})
        return ExecutionOutcome(
            run_id="sandbox_unplanned",
            status=RunStatus.SUCCEEDED,
            execution_mode="podman",
            remote_run_dir="podman://unplanned",
            raw_result={},
            artifacts=(),
        )


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


def _valid_test_pdb(residue_count: int = 10, atoms_per_residue: int = 5) -> str:
    lines: list[str] = []
    serial = 1
    atom_names = ("N", "CA", "C", "O", "CB")
    for residue_index in range(1, residue_count + 1):
        for atom_index in range(atoms_per_residue):
            atom_name = atom_names[atom_index % len(atom_names)]
            lines.append(
                f"ATOM  {serial:5d} {atom_name:<4} ALA A{residue_index:4d}    "
                f"{float(residue_index):8.3f}{float(atom_index):8.3f}{0.0:8.3f}  1.00 20.00           C"
            )
            serial += 1
    lines.append("END")
    return "\n".join(lines) + "\n"


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    Path("/tmp/input_structure.pdb").write_text(_valid_test_pdb(), encoding="utf-8")
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

    resumed = engine.continue_after_approval(invocation_id="inv_exec_001", resolution="Approved for launch.")

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

    resumed = engine.continue_after_approval(
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

    resumed = engine.continue_after_approval(invocation_id="inv_exec_rejected_resume")

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
    status = engine.get_pipeline_status("inv_exec_bg")

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


def test_execution_pipeline_rejects_legacy_handoff_input() -> None:
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
            tool_name="execution.pipeline.start",
            arguments={
                "task_id": "task_001",
                "code": "from openzyme_pipeline import artifacts, hpc\nstructure = artifacts.get('art_001')\nhpc.fpocket(structure_artifact_id=structure['artifact_id'])\n",
                "inputs": {
                    "handoff": {
                        "execution_goal": "Run fpocket on the selected structure",
                        "required_artifact_ids": ["art_001"],
                        "catalog_tool_id": "fpocket",
                        "require_approval": False,
                    },
                },
            },
            task_id="task_001",
            lane_id="lane_001",
        ),
    )

    assert result.ok is False
    assert "unsupported_pipeline_handoff" in result.content


def test_execution_pipeline_start_rejects_duplicate_task_invocation() -> None:
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
    arguments = {
        "task_id": "task_001",
        "code": "from openzyme_pipeline import artifacts, hpc\nstructure = artifacts.get('art_001')\nhpc.fpocket(structure_artifact_id=structure['artifact_id'])\n",
        "inputs": {"artifact_ids": ["art_001"]},
    }

    first = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_start_first",
            tool_name="execution.pipeline.start",
            arguments=arguments,
            task_id="task_001",
            lane_id="lane_001",
        ),
    )
    second = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_start_second",
            tool_name="execution.pipeline.start",
            arguments=arguments,
            task_id="task_001",
            lane_id="lane_001",
        ),
    )

    assert first.ok is True
    assert second.ok is False
    assert second.status == "existing_execution_invocation"
    assert second.error_code == "existing_execution_invocation"
    assert "execution.pipeline.status" in second.hint


def test_pipeline_dry_run_returns_plan_without_approval_or_runner_submit() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(repositories, runner)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_dry_run",
        code="from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
        inputs={"artifact_ids": ["art_001"]},
        dry_run=True,
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert result.approval is None
    assert runner.payloads == []
    assert result.parsed_result is not None
    plan = result.parsed_result.structured_findings["plan"]
    assert plan["plan_digest"]
    assert plan["hpc_operations"][0]["method"] == "hpc.fpocket"
    assert plan["approval_requirements"][0]["kind"] == "hpc_operation"


def test_pipeline_execute_after_dry_run_uses_distinct_idempotency_and_links_approval() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories,
        runner,
        sandbox_runner=HandlerSandboxRunner(),
    )
    code = (
        "from openzyme_pipeline import artifacts, hpc\n"
        "structure = artifacts.get('art_001')\n"
        "hpc.fpocket(structure_artifact_id=structure['artifact_id'])\n"
    )
    inputs = {"artifact_ids": ["art_001"]}

    dry_run = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code=code,
        inputs=inputs,
        dry_run=True,
    )
    execute = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code=code,
        inputs=inputs,
        dry_run=False,
    )

    assert dry_run.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert execute.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert execute.approval is not None
    assert execute.invocation.approval_id == execute.approval.approval_id
    assert dry_run.invocation.idempotency_key != execute.invocation.idempotency_key
    approvals = repositories.approvals.list_by_session("sess_001")
    assert [approval.approval_id for approval in approvals] == [
        execute.approval.approval_id
    ]


def test_pipeline_rejects_literal_artifact_get_ids_missing_from_inputs() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=HandlerSandboxRunner())

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_infer_artifact",
        code=(
            "from openzyme_pipeline import artifacts, hpc\n"
            "structure = artifacts.get('art_001')\n"
            "hpc.fpocket(structure_artifact_id=structure['artifact_id'])\n"
        ),
        inputs={},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    assert result.parsed_result.structured_findings["error"]["error_code"] == "missing_pipeline_artifact_inputs"
    assert "art_001" in result.parsed_result.structured_findings["error"]["hint"]


def test_pipeline_supervisor_fails_when_sandbox_preflight_fails() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(preflight_ok=False),
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code="print('hello from sandbox')\n",
        inputs={"artifact_ids": ["art_001"]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    assert result.parsed_result.structured_findings["error"]["type"] == "sandbox_preflight_failed"


def test_pipeline_rejects_toy_pdb_before_fpocket_approval() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    Path("/tmp/toy_structure.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000\nEND\n",
        encoding="utf-8",
    )
    artifact = repositories.artifacts.get("art_001")
    assert artifact is not None
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact.artifact_id,
            session_id=artifact.session_id,
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
            invocation_id=artifact.invocation_id,
            run_id=artifact.run_id,
            kind=artifact.kind,
            storage_uri="/tmp/toy_structure.pdb",
            relative_path="toy_structure.pdb",
            title="toy_structure.pdb",
            description=artifact.description,
            metadata={"source": "toy", "format": "pdb"},
            created_at=artifact.created_at,
        )
    )
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=HandlerSandboxRunner())

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_invalid_fpocket",
        code="from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
        inputs={"artifact_ids": ["art_001"]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.approval is None
    assert runner.payloads == []
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "invalid_fpocket_input"
    assert error["stage"] == "input_validation"


def test_pipeline_hpc_operation_waits_for_approval_then_resumes_once() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingSuccessRunner()
    sandbox = HandlerSandboxRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_approval",
        code="from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
        inputs={"artifact_ids": ["art_001"]},
    )

    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    assert runner.payloads == []

    approval = repositories.approvals.get(first.approval.approval_id)
    assert approval is not None
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
            resolution_ref="artifact://approval-resolution.json",
            created_at=approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    resumed = engine.continue_after_approval(invocation_id="inv_pipeline_approval", resolution="approved")
    repeated = engine.continue_after_approval(invocation_id="inv_pipeline_approval", resolution="approved")
    status = engine.get_pipeline_status("inv_pipeline_approval")

    assert resumed.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert repeated.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert resumed.run is not None
    assert resumed.run.summary == "Pipeline sandbox completed."
    assert resumed.parsed_result is not None
    assert (
        resumed.parsed_result.result_summary
        == "fpocket found 2 pocket(s) for the selected artifact set."
    )
    assert status["parsed_result"]["result_summary"] == "fpocket found 2 pocket(s) for the selected artifact set."
    assert status["output_artifact_ids"]
    assert status["runs"]
    assert status["artifacts"]
    assert len(runner.payloads) == 1
    assert sandbox.calls == 1


def test_pipeline_hpc_backend_failure_exposes_runner_details(tmp_path: Path) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingFailedRunner()
    sandbox = FailedHpcSandboxRunner(tmp_path / "stderr.log")
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_hpc_failed",
        code="from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=first.approval.approval_id,
            session_id=first.approval.session_id,
            task_id=first.approval.task_id,
            lane_id=first.approval.lane_id,
            kind=first.approval.kind,
            requested_action=first.approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=first.approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=first.approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    resumed = engine.continue_after_approval(invocation_id="inv_pipeline_hpc_failed", resolution="approved")
    status = engine.get_pipeline_status("inv_pipeline_hpc_failed")
    error = status["output_payload"]["pipeline"]["error"]

    assert resumed.invocation.status is EngineInvocationStatus.FAILED
    assert error["type"] == "hpc_operation_failed"
    assert error["hpc_failure"]["runner_run_id"] == "runner_failed_001"
    assert error["hpc_failure"]["error_code"] == "APPTAINER_MISSING"
    assert error["hpc_failure"]["stderr_excerpt"] == "apptainer: command not found"


def test_pipeline_hpc_runner_timeout_is_not_sandbox_preflight_failure(tmp_path: Path) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingTimeoutRunner()
    sandbox = FailedHpcSandboxRunner(tmp_path / "stderr.log")
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_hpc_timeout",
        code="from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=first.approval.approval_id,
            session_id=first.approval.session_id,
            task_id=first.approval.task_id,
            lane_id=first.approval.lane_id,
            kind=first.approval.kind,
            requested_action=first.approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=first.approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=first.approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    engine.continue_after_approval(invocation_id="inv_pipeline_hpc_timeout", resolution="approved")
    status = engine.get_pipeline_status("inv_pipeline_hpc_timeout")
    error = status["output_payload"]["pipeline"]["error"]

    assert error["type"] == "hpc_runner_timeout"
    assert error["stage"] == "remote_execution"
    assert error["hpc_failure"]["error_code"] == "COMMAND_TIMEOUT"


def test_pipeline_runtime_unplanned_hpc_operation_requests_secondary_approval() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingSuccessRunner()
    sandbox = UnplannedHpcSandboxRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_unplanned",
        code="from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=first.approval.approval_id,
            session_id=first.approval.session_id,
            task_id=first.approval.task_id,
            lane_id=first.approval.lane_id,
            kind=first.approval.kind,
            requested_action=first.approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=first.approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=first.approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    resumed = engine.continue_after_approval(invocation_id="inv_pipeline_unplanned", resolution="approved")

    assert resumed.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert resumed.approval is not None
    assert resumed.approval.kind == "execution_pipeline_operation"
    assert runner.payloads == []
