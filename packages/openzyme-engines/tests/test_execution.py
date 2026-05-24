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


class BioSandboxRunner:
    def __init__(self, operations: tuple[tuple[str, dict[str, object]], ...]) -> None:
        self.operations = operations
        self.results: list[dict[str, object]] = []
        self.calls = 0

    def preflight(self) -> SandboxPreflight:
        return SandboxPreflight(True)

    def run_pipeline(self, *, session_id, invocation_id, code, inputs=(), control_handler=None):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        self.calls += 1
        if control_handler is not None:
            for method, params in self.operations:
                self.results.append(dict(control_handler(method, params)))
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


def _save_pipeline_source(
    repositories: CoreRepositories,
    *,
    artifact_id: str,
    code: str,
    session_id: str = "sess_001",
    task_id: str = "task_001",
    lane_id: str = "lane_001",
) -> str:
    source_path = Path(f"/tmp/{artifact_id}.py")
    source_path.write_text(code, encoding="utf-8")
    source_digest = f"sha256:{hashlib.sha256(code.encode('utf-8')).hexdigest()}"
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=lane_id,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.CODE,
            storage_uri=str(source_path),
            relative_path=f"code/{artifact_id}/v1/{artifact_id}/pipeline.py",
            title="pipeline.py",
            description=None,
            metadata={
                "format": "python",
                "semantic_type": "pipeline_source",
                "content_digest": source_digest,
                "lineage_root_artifact_id": artifact_id,
                "version": 1,
            },
            created_at="2026-04-20T12:00:04+00:00",
        )
    )
    return artifact_id


def _pipeline_source_id(repositories: CoreRepositories, artifact_id: str, code: str) -> str:
    return _save_pipeline_source(repositories, artifact_id=artifact_id, code=code)


def _save_hmm_artifact(repositories: CoreRepositories, artifact_id: str = "art_hmm_001") -> str:
    hmm_path = Path(f"/tmp/{artifact_id}.hmm")
    hmm_path.write_text("HMMER3/f [fixture]\nNAME fixture\n//\n", encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id="sess_001",
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri=str(hmm_path),
            relative_path=f"hmms/{artifact_id}.hmm",
            title=f"{artifact_id}.hmm",
            description=None,
            metadata={"source": "seed", "format": "hmm"},
            created_at="2026-04-20T12:00:04+00:00",
        )
    )
    return artifact_id


def _save_fasta_artifact(repositories: CoreRepositories, artifact_id: str = "art_fasta_001") -> str:
    fasta_path = Path(f"/tmp/{artifact_id}.fasta")
    fasta_path.write_text(">seq1\nMKTAYIAKQRQISFVKSHFSRQ\n>seq2\nMKADKSELVQKAKLAEQAERYD\n", encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id="sess_001",
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.SEQUENCE,
            storage_uri=str(fasta_path),
            relative_path=f"sequences/{artifact_id}.fasta",
            title=f"{artifact_id}.fasta",
            description=None,
            metadata={"source": "seed", "format": "fasta"},
            created_at="2026-04-20T12:00:04+00:00",
        )
    )
    return artifact_id


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
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_legacy_handoff_rejected",
        "from openzyme_pipeline import artifacts, hpc\nstructure = artifacts.get('art_001')\nhpc.fpocket(structure_artifact_id=structure['artifact_id'])\n",
    )
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
                "code_artifact_id": code_artifact_id,
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


def test_pipeline_start_requires_code_artifact_id_and_rejects_inline_code() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    missing = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        inputs={"artifact_ids": ["art_001"]},
    )
    inline = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code="print('inline is unsupported')\n",
        inputs={"artifact_ids": ["art_001"]},
    )

    assert missing.invocation.status is EngineInvocationStatus.FAILED
    assert missing.parsed_result is not None
    assert missing.parsed_result.structured_findings["error"]["error_code"] == "missing_code_artifact_id"
    assert inline.invocation.status is EngineInvocationStatus.FAILED
    assert inline.parsed_result is not None
    assert inline.parsed_result.structured_findings["error"]["error_code"] == "unsupported_inline_pipeline_code"


def test_pipeline_start_validates_code_artifact_scope_type_and_digest() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_digest_mismatch",
        "print('digest mismatch')\n",
    )
    artifact = repositories.artifacts.get(code_artifact_id)
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
            storage_uri=artifact.storage_uri,
            relative_path=artifact.relative_path,
            title=artifact.title,
            description=artifact.description,
            metadata={**dict(artifact.metadata or {}), "content_digest": "sha256:stale"},
            created_at=artifact.created_at,
        )
    )
    repositories.sessions.save(
        Session(
            session_id="sess_other",
            project_id="proj_001",
            title="Other",
            objective="Other",
            status=SessionStatus.ACTIVE,
            created_at="2026-04-20T12:00:00+00:00",
            updated_at="2026-04-20T12:00:00+00:00",
        )
    )
    _save_pipeline_source(
        repositories,
        artifact_id="code_other_session",
        session_id="sess_other",
        task_id=None,
        lane_id=None,
        code="print('other')\n",
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    non_code = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id="art_001",
        inputs={"artifact_ids": ["art_001"]},
    )
    cross_session = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id="code_other_session",
        inputs={"artifact_ids": ["art_001"]},
    )
    digest_mismatch = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )

    assert non_code.parsed_result is not None
    assert non_code.parsed_result.structured_findings["error"]["error_code"] == "invalid_code_artifact"
    assert cross_session.parsed_result is not None
    assert cross_session.parsed_result.structured_findings["error"]["error_code"] == "code_artifact_not_found"
    assert digest_mismatch.parsed_result is not None
    assert digest_mismatch.parsed_result.structured_findings["error"]["error_code"] == "source_code_digest_mismatch"


def test_execution_pipeline_start_rejects_duplicate_task_invocation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_duplicate_pipeline_start",
        "from openzyme_pipeline import artifacts, hpc\nstructure = artifacts.get('art_001')\nhpc.fpocket(structure_artifact_id=structure['artifact_id'])\n",
    )
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
        "code_artifact_id": code_artifact_id,
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
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_dry_run",
        "from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
    )
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(repositories, runner)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_dry_run",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
        dry_run=True,
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert result.approval is None
    assert runner.payloads == []
    assert result.parsed_result is not None
    plan = result.parsed_result.structured_findings["plan"]
    assert plan["plan_digest"]
    assert plan["source_code_artifact_id"] == code_artifact_id
    assert plan["source_code_digest"]
    assert plan["source_code_version"] == 1
    assert plan["hpc_operations"][0]["method"] == "hpc.fpocket"
    assert plan["approval_requirements"][0]["kind"] == "hpc_operation"


def test_pipeline_dry_run_lists_bio_operations_and_rejects_direct_network() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    bio_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_dry_run",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'])\n"
        "bio.uniprot_fetch(accessions=['Q8XYZ1'], batch_size=50)\n"
        "bio.hmmer_search(hmm_artifact_id='art_hmm_001', database='uniprotkb')\n",
    )
    network_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_direct_network",
        "import requests\nrequests.get('https://example.org')\n",
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    dry_run = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=bio_code_artifact_id,
        inputs={},
        dry_run=True,
    )
    rejected = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=network_code_artifact_id,
        inputs={},
        dry_run=True,
    )

    assert dry_run.parsed_result is not None
    plan = dry_run.parsed_result.structured_findings["plan"]
    assert [operation["method"] for operation in plan["bio_operations"]] == [
        "bio.ncbi_fetch_proteins",
        "bio.uniprot_fetch",
        "bio.hmmer_search",
    ]
    assert plan["resource_quota_estimate"]["bio_operation_count"] == 3
    assert plan["resource_quota_estimate"]["provider_requests"] == 3
    assert plan["expected_outputs"][0]["path"] == "bio/ncbi/proteins.fasta"
    assert rejected.invocation.status is EngineInvocationStatus.FAILED
    assert rejected.parsed_result is not None
    assert rejected.parsed_result.structured_findings["error"]["error_code"] == "unsupported_sandbox_network_call"


def test_pipeline_dry_run_lists_bio_tool_operations_and_rejects_direct_cli() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    bio_tools_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_dry_run",
        "from openzyme_pipeline import bio_tools\n"
        "bio_tools.cdhit(input_fasta_artifact_id='art_fasta_001', identity=0.9)\n"
        "bio_tools.mafft(input_fasta_artifact_id='art_fasta_001')\n"
        "bio_tools.hmmbuild(alignment_artifact_id='art_alignment')\n"
        "bio_tools.hmmalign(hmm_artifact_id='art_hmm', fasta_artifact_id='art_fasta_001')\n"
        "bio_tools.hmmer_search_cli(hmm_artifact_id='art_hmm', target_fasta_artifact_id='art_fasta_001')\n",
    )
    subprocess_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_direct_subprocess",
        "import subprocess\nsubprocess.run(['mafft', 'input.fasta'])\n",
    )
    shell_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_direct_shell",
        "from os import system\nsystem('mafft input.fasta')\n",
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    dry_run = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=bio_tools_code_artifact_id,
        inputs={},
        dry_run=True,
    )
    rejected = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=subprocess_code_artifact_id,
        inputs={},
        dry_run=True,
    )
    rejected_shell = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=shell_code_artifact_id,
        inputs={},
        dry_run=True,
    )

    assert dry_run.parsed_result is not None
    plan = dry_run.parsed_result.structured_findings["plan"]
    assert [operation["method"] for operation in plan["bio_tool_operations"]] == [
        "bio_tools.cdhit",
        "bio_tools.mafft",
        "bio_tools.hmmbuild",
        "bio_tools.hmmalign",
        "bio_tools.hmmer_search_cli",
    ]
    assert plan["resource_quota_estimate"]["bio_tool_operation_count"] == 5
    assert plan["expected_outputs"][0]["path"] == "bio_tools/cdhit/clustered.fasta"
    assert rejected.invocation.status is EngineInvocationStatus.FAILED
    assert rejected.parsed_result is not None
    assert rejected.parsed_result.structured_findings["error"]["error_code"] == "unsupported_sandbox_process_call"
    assert rejected_shell.invocation.status is EngineInvocationStatus.FAILED
    assert rejected_shell.parsed_result is not None
    assert rejected_shell.parsed_result.structured_findings["error"]["error_code"] == "unsupported_sandbox_process_call"


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
    code_artifact_id = _pipeline_source_id(repositories, "code_execute_after_dry_run", code)
    inputs = {"artifact_ids": ["art_001"]}

    dry_run = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs=inputs,
        dry_run=True,
    )
    execute = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs=inputs,
        dry_run=False,
    )

    assert dry_run.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert execute.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert execute.approval is not None
    assert execute.invocation.approval_id == execute.approval.approval_id
    assert execute.parsed_result is not None
    assert execute.parsed_result.structured_findings["plan"]["source_code_artifact_id"] == code_artifact_id
    assert dry_run.invocation.idempotency_key != execute.invocation.idempotency_key
    approvals = repositories.approvals.list_by_session("sess_001")
    assert [approval.approval_id for approval in approvals] == [
        execute.approval.approval_id
    ]


def test_pipeline_single_plan_approval_policy_gates_bio_tool_execution() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_single_plan_bio_tools",
        "from openzyme_pipeline import bio, bio_tools\n"
        "refs = bio.ncbi_fetch_proteins(accessions=['AAC72747.1'])\n"
        "bio_tools.cdhit(input_fasta_artifact_id=refs['artifact_ids'][0], identity=0.9)\n",
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=BioSandboxRunner(()),
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs={"approval_policy": "single_plan"},
    )

    assert result.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert result.approval is not None
    assert result.approval.kind == "execution_pipeline_plan"
    assert result.parsed_result is not None
    plan = result.parsed_result.structured_findings["plan"]
    assert plan["approval_requirements"][0]["kind"] == "pipeline_plan"
    assert plan["bio_operations"][0]["approval_required"] is True
    assert plan["bio_tool_operations"][0]["approval_required"] is True


def test_pipeline_bio_ncbi_and_uniprot_fetch_persist_bounded_artifacts() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_fetch",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'])\n"
        "bio.uniprot_fetch(accessions=['Q8XYZ1', 'MISSING999'], batch_size=1)\n",
    )
    sandbox = BioSandboxRunner(
        (
            ("bio.ncbi_fetch_proteins", {"accessions": ["P12345"], "fields": ["taxonomy"]}),
            (
                "bio.uniprot_fetch",
                {
                    "accessions": ["Q8XYZ1", "MISSING999"],
                    "fields": ["length", "taxonomy", "reviewed"],
                    "batch_size": 1,
                },
            ),
        )
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_fetch",
        code_artifact_id=code_artifact_id,
        inputs={},
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert len(sandbox.results) == 2
    assert sandbox.results[0]["artifact_count"] == 2
    assert sandbox.results[1]["warnings"][0]["warning_code"] == "partial_accession_missing"
    assert "sequence" not in sandbox.results[0]["artifacts"][0]["metadata"]
    artifacts = repositories.artifacts.list_by_invocation("sess_001", "inv_pipeline_bio_fetch")
    bio_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.metadata and artifact.metadata.get("source") == "host_supervised_bio_sdk"
    ]
    assert {artifact.relative_path for artifact in bio_artifacts} == {
        "bio/ncbi/proteins.fasta",
        "bio/ncbi/proteins.metadata.json",
        "bio/uniprot/sequences.fasta",
        "bio/uniprot/metadata.json",
    }
    fasta_artifact = next(artifact for artifact in bio_artifacts if artifact.relative_path == "bio/ncbi/proteins.fasta")
    assert fasta_artifact.kind is ArtifactKind.SEQUENCE
    assert fasta_artifact.metadata is not None
    assert fasta_artifact.metadata["provider"] == "ncbi"
    assert fasta_artifact.metadata["response_digest"].startswith("sha256:")
    assert fasta_artifact.metadata["source_code_artifact_id"] == code_artifact_id
    assert Path(fasta_artifact.storage_uri).read_text(encoding="utf-8").startswith(">P12345")
    metadata_artifact = next(artifact for artifact in bio_artifacts if artifact.relative_path == "bio/uniprot/metadata.json")
    metadata_payload = json.loads(Path(metadata_artifact.storage_uri).read_text(encoding="utf-8"))
    assert "sequence" not in metadata_payload["records"][0]
    status = engine.get_pipeline_status("inv_pipeline_bio_fetch")
    assert status["details"]["bio_artifact_ids"]
    assert "P12345" not in str(status.get("sandbox_outcome", {}))


def test_pipeline_bio_hmmer_search_persists_raw_and_parsed_hits() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_hmmer",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='uniprotkb')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {"hmm_artifact_id": hmm_artifact_id, "database": "uniprotkb", "params": {"E": 1e-5}},
            ),
        )
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_hmmer",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert sandbox.results[0]["summary"]["hit_count"] == 1
    artifacts = repositories.artifacts.list_by_invocation("sess_001", "inv_pipeline_bio_hmmer")
    paths = {artifact.relative_path for artifact in artifacts}
    assert "bio/hmmer/raw_hits.json" in paths
    assert "bio/hmmer/parsed_hits.csv" in paths
    parsed = next(artifact for artifact in artifacts if artifact.relative_path == "bio/hmmer/parsed_hits.csv")
    assert parsed.metadata is not None
    assert parsed.metadata["provider"] == "ebi_hmmer"
    assert parsed.metadata["query_hmm_artifact_id"] == hmm_artifact_id
    assert "fixture_hit_001" in Path(parsed.storage_uri).read_text(encoding="utf-8")


def test_pipeline_bio_hmmer_empty_results_returns_warning() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_empty")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_hmmer_empty",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='empty')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {"hmm_artifact_id": hmm_artifact_id, "database": "empty", "params": {}},
            ),
        )
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_empty",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert sandbox.results[0]["summary"]["hit_count"] == 0
    assert sandbox.results[0]["warnings"][0]["warning_code"] == "empty_results"
    parsed = next(
        artifact
        for artifact in repositories.artifacts.list_by_invocation("sess_001", "inv_pipeline_bio_empty")
        if artifact.relative_path == "bio/hmmer/parsed_hits.csv"
    )
    assert Path(parsed.storage_uri).read_text(encoding="utf-8") == "target,accession,evalue,score\n"


def test_pipeline_bio_provider_timeout_is_structured_failure() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_timeout")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_timeout",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='uniprotkb', params={{'simulate': 'timeout'}})\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "database": "uniprotkb",
                    "params": {"simulate": "timeout"},
                },
            ),
        )
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_timeout",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "bio_provider_timeout"
    assert error["stage"] == "bio_provider_request"
    assert error["retryable"] is True
    assert error["details"]["provider"] == "ebi_hmmer"


@pytest.mark.parametrize(
    ("simulation", "error_type", "stage", "retryable"),
    [
        ("schema_drift", "bio_schema_drift", "bio_result_parse", False),
        ("pagination_failure", "bio_pagination_failure", "bio_provider_pagination", True),
    ],
)
def test_pipeline_bio_schema_and_pagination_failures_are_structured(
    simulation: str,
    error_type: str,
    stage: str,
    retryable: bool,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, f"art_hmm_{simulation}")
    code_artifact_id = _pipeline_source_id(
        repositories,
        f"code_bio_{simulation}",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='uniprotkb', params={{'simulate': '{simulation}'}})\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "database": "uniprotkb",
                    "params": {"simulate": simulation},
                },
            ),
        )
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id=f"inv_pipeline_bio_{simulation}",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == error_type
    assert error["stage"] == stage
    assert error["retryable"] is retryable


def test_pipeline_bio_tools_persist_declared_outputs_with_provenance() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_tools")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools",
        "from openzyme_pipeline import bio_tools\n"
        f"bio_tools.cdhit(input_fasta_artifact_id='{fasta_artifact_id}', identity=0.9)\n"
        f"bio_tools.mafft(input_fasta_artifact_id='{fasta_artifact_id}')\n"
        f"bio_tools.hmmbuild(alignment_artifact_id='{fasta_artifact_id}')\n"
        f"bio_tools.hmmalign(hmm_artifact_id='{hmm_artifact_id}', fasta_artifact_id='{fasta_artifact_id}')\n"
        f"bio_tools.hmmer_search_cli(hmm_artifact_id='{hmm_artifact_id}', target_fasta_artifact_id='{fasta_artifact_id}')\n",
    )
    sandbox = BioSandboxRunner(
        (
            ("bio_tools.cdhit", {"input_fasta_artifact_id": fasta_artifact_id, "identity": 0.9, "mode": "protein"}),
            ("bio_tools.mafft", {"input_fasta_artifact_id": fasta_artifact_id, "params": {}}),
            ("bio_tools.hmmbuild", {"alignment_artifact_id": fasta_artifact_id, "params": {}}),
            ("bio_tools.hmmalign", {"hmm_artifact_id": hmm_artifact_id, "fasta_artifact_id": fasta_artifact_id, "params": {}}),
            (
                "bio_tools.hmmer_search_cli",
                {"hmm_artifact_id": hmm_artifact_id, "target_fasta_artifact_id": fasta_artifact_id, "params": {}},
            ),
        )
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id, hmm_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert len(sandbox.results) == 5
    artifacts = repositories.artifacts.list_by_invocation("sess_001", "inv_pipeline_bio_tools")
    paths = {artifact.relative_path for artifact in artifacts}
    assert {
        "bio_tools/cdhit/clustered.fasta",
        "bio_tools/cdhit/clusters.csv",
        "bio_tools/mafft/alignment.fasta",
        "bio_tools/hmmbuild/model.hmm",
        "bio_tools/hmmalign/aligned.fasta",
        "bio_tools/hmmer_search_cli/hits.csv",
        "bio_tools/hmmer_search_cli/tool.log",
    }.issubset(paths)
    hits = next(artifact for artifact in artifacts if artifact.relative_path == "bio_tools/hmmer_search_cli/hits.csv")
    assert hits.metadata is not None
    assert hits.metadata["source"] == "host_supervised_bio_tools_sdk"
    assert hits.metadata["tool_name"] == "hmmsearch"
    assert hits.metadata["parameter_digest"].startswith("sha256:")
    assert hits.metadata["source_code_artifact_id"] == code_artifact_id
    assert "target,accession,evalue,score" in Path(hits.storage_uri).read_text(encoding="utf-8")


def test_pipeline_bio_tools_tool_missing_invalid_input_and_output_failures_are_structured() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fasta_fail")
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_fail")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_failure",
        "from openzyme_pipeline import bio_tools\n"
        f"bio_tools.cdhit(input_fasta_artifact_id='{fasta_artifact_id}', identity=0.9)\n",
    )
    cases = [
        (
            "tool_missing",
            ("bio_tools.mafft", {"input_fasta_artifact_id": fasta_artifact_id, "params": {"simulate": "tool_missing"}}),
            "tool_missing",
            "bio_tools_preflight",
        ),
        (
            "invalid_fasta",
            ("bio_tools.cdhit", {"input_fasta_artifact_id": "art_001", "identity": 0.9, "mode": "protein"}),
            "invalid_fasta",
            "bio_tools_input_validation",
        ),
        (
            "declared_output_missing",
            (
                "bio_tools.hmmer_search_cli",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "target_fasta_artifact_id": fasta_artifact_id,
                    "params": {"simulate": "declared_output_missing"},
                },
            ),
            "declared_output_missing",
            "bio_tools_output_validation",
        ),
    ]
    for suffix, operation, error_type, stage in cases:
        sandbox = BioSandboxRunner((operation,))
        engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)
        result = engine.start_pipeline(
            session_id="sess_001",
            task_id="task_001",
            invocation_id=f"inv_pipeline_bio_tools_{suffix}",
            code_artifact_id=code_artifact_id,
            inputs={"artifact_ids": [fasta_artifact_id, hmm_artifact_id]},
            idempotency_key=f"case:{suffix}",
        )

        assert result.invocation.status is EngineInvocationStatus.FAILED
        assert result.parsed_result is not None
        error = result.parsed_result.structured_findings["error"]
        assert error["type"] == error_type
        assert error["stage"] == stage


def test_pipeline_bio_tools_oversized_log_is_artifactized_with_warning() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fasta_log")
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_log")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_log",
        "from openzyme_pipeline import bio_tools\n"
        f"bio_tools.hmmer_search_cli(hmm_artifact_id='{hmm_artifact_id}', target_fasta_artifact_id='{fasta_artifact_id}', params={{'simulate': 'oversized_log'}})\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.hmmer_search_cli",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "target_fasta_artifact_id": fasta_artifact_id,
                    "params": {"simulate": "oversized_log"},
                },
            ),
        )
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox)

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools_log",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id, hmm_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert sandbox.results[0]["warnings"][0]["warning_code"] == "log_truncated"
    log_artifact = next(
        artifact
        for artifact in repositories.artifacts.list_by_invocation("sess_001", "inv_pipeline_bio_tools_log")
        if artifact.relative_path == "bio_tools/hmmer_search_cli/tool.log"
    )
    assert log_artifact.kind is ArtifactKind.LOG
    assert log_artifact.metadata is not None
    assert log_artifact.metadata["log_truncated"] is True


def test_pipeline_rejects_literal_artifact_get_ids_missing_from_inputs() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner(), sandbox_runner=HandlerSandboxRunner())
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_missing_inputs",
        "from openzyme_pipeline import artifacts, hpc\n"
        "structure = artifacts.get('art_001')\n"
        "hpc.fpocket(structure_artifact_id=structure['artifact_id'])\n",
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_infer_artifact",
        code_artifact_id=code_artifact_id,
        inputs={},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    assert result.parsed_result.structured_findings["error"]["error_code"] == "missing_pipeline_artifact_inputs"
    assert "art_001" in result.parsed_result.structured_findings["error"]["hint"]


def test_pipeline_supervisor_propagates_sandbox_preflight_failure() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(preflight_ok=False),
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_preflight_failure",
        "print('hello from sandbox')\n",
    )

    with pytest.raises(RuntimeError, match="sandbox preflight failed"):
        engine.start_pipeline(
            session_id="sess_001",
            task_id="task_001",
            code_artifact_id=code_artifact_id,
            inputs={"artifact_ids": ["art_001"]},
        )


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
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_invalid_fpocket",
        "from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_invalid_fpocket",
        code_artifact_id=code_artifact_id,
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
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_hpc_approval",
        "from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_approval",
        code_artifact_id=code_artifact_id,
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
    assert status["details"]["source_code_artifact_id"] == code_artifact_id
    assert status["output_artifact_ids"]
    assert status["runs"]
    assert status["artifacts"]
    provenance_artifact = next(
        artifact
        for artifact in resumed.artifacts
        if artifact.metadata and artifact.metadata.get("source_code_artifact_id") == code_artifact_id
    )
    assert provenance_artifact.metadata is not None
    assert provenance_artifact.metadata["source_code_digest"]
    assert provenance_artifact.metadata["source_code_version"] == 1
    public_status = str(status)
    assert "storage_uri" not in public_status
    assert "local_path" not in public_status
    assert "source_storage_uri" not in public_status
    assert "intermediate_storage_uri" not in public_status
    assert "storage_uri" not in str(resumed.parsed_result.structured_findings)
    assert len(runner.payloads) == 1
    assert sandbox.calls == 1


def test_pipeline_hpc_backend_failure_exposes_runner_details(tmp_path: Path) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingFailedRunner()
    sandbox = FailedHpcSandboxRunner(tmp_path / "stderr.log")
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_hpc_failed",
        "from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_hpc_failed",
        code_artifact_id=code_artifact_id,
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
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_hpc_timeout",
        "from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_hpc_timeout",
        code_artifact_id=code_artifact_id,
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
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_unplanned_hpc",
        "from openzyme_pipeline import hpc\nhpc.fpocket(structure_artifact_id='art_001')\n",
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_unplanned",
        code_artifact_id=code_artifact_id,
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
