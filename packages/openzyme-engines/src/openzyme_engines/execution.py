from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re
from typing import Any
from typing import Protocol
from uuid import uuid4

from openzyme_core import EngineDescriptor
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import ToolResult
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import RunRecord
from openzyme_domain import RunStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain.control_plane import utc_now_iso


def _new_document_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _safe_ref(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "artifact"


def _invocation_status_from_run(run_status: RunStatus) -> EngineInvocationStatus:
    return {
        RunStatus.QUEUED: EngineInvocationStatus.RUNNING,
        RunStatus.RUNNING: EngineInvocationStatus.RUNNING,
        RunStatus.SUCCEEDED: EngineInvocationStatus.SUCCEEDED,
        RunStatus.FAILED: EngineInvocationStatus.FAILED,
        RunStatus.CANCELLED: EngineInvocationStatus.CANCELLED,
    }[run_status]


def _artifact_kind_from_path(path: str) -> ArtifactKind:
    lowered = path.lower()
    if lowered.endswith(".log") or "/logs/" in lowered:
        return ArtifactKind.LOG
    if lowered.endswith((".pdb", ".cif", ".mol2", ".sdf", ".pdbqt")):
        return ArtifactKind.STRUCTURE
    if lowered.endswith((".md", ".pdf", ".html")):
        return ArtifactKind.REPORT
    return ArtifactKind.RESULT


@dataclass(frozen=True, slots=True)
class ExecutionArtifactRef:
    storage_uri: str
    relative_path: str
    kind: ArtifactKind

    def to_dict(self) -> dict[str, Any]:
        return {
            "storage_uri": self.storage_uri,
            "relative_path": self.relative_path,
            "kind": self.kind.value,
        }


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: str
    status: RunStatus
    execution_mode: str
    remote_run_dir: str
    raw_result: dict[str, Any]
    artifacts: tuple[ExecutionArtifactRef, ...] = ()
    job_id: str | None = None
    exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class ExecutionStatusSnapshot:
    run_id: str
    status: RunStatus
    remote_run_dir: str
    raw_result: dict[str, Any]
    job_id: str | None = None
    exit_code: int | None = None


class ExecutionRunner(Protocol):
    def submit_execution(self, session_id: str, payload: dict[str, Any]) -> ExecutionOutcome: ...

    def get_execution_status(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> ExecutionStatusSnapshot: ...

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        runspec: dict[str, Any],
        job_id: str | None = None,
    ) -> ExecutionOutcome: ...

    def cancel_execution(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> ExecutionOutcome: ...


@dataclass(frozen=True, slots=True)
class ExecutionParsedResult:
    result_summary: str
    structured_findings: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_summary": self.result_summary,
            "structured_findings": self.structured_findings,
        }


class ExecutionRequestCompiler(Protocol):
    def compile_request(
        self,
        *,
        handoff: "ExecutionHandoff",
        task: Any,
        resolved_required_artifacts: tuple[SessionArtifactRecord, ...],
        resolved_context_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> dict[str, Any]: ...


class ExecutionResultParser(Protocol):
    def parse_result(
        self,
        *,
        handoff: "ExecutionHandoff",
        outcome: ExecutionOutcome,
        artifact_refs: tuple[SessionArtifactRecord, ...],
    ) -> ExecutionParsedResult: ...


@dataclass(frozen=True, slots=True)
class ExecutionHandoff:
    execution_goal: str
    required_artifact_ids: tuple[str, ...] = ()
    context_artifact_ids: tuple[str, ...] = ()
    catalog_tool_id: str = "fpocket"
    tool_inputs: dict[str, Any] | None = None
    execution_mode: str = "auto"
    require_approval: bool = True
    requested_action: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ExecutionHandoff":
        return cls(
            execution_goal=str(payload["execution_goal"]),
            required_artifact_ids=tuple(str(value) for value in payload.get("required_artifact_ids", [])),
            context_artifact_ids=tuple(str(value) for value in payload.get("context_artifact_ids", [])),
            catalog_tool_id=str(payload.get("catalog_tool_id", "fpocket")),
            tool_inputs=None if payload.get("tool_inputs") is None else dict(payload.get("tool_inputs") or {}),
            execution_mode=str(payload.get("execution_mode", "auto")),
            require_approval=bool(payload.get("require_approval", True)),
            requested_action=None
            if payload.get("requested_action") is None
            else str(payload.get("requested_action")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_goal": self.execution_goal,
            "required_artifact_ids": list(self.required_artifact_ids),
            "context_artifact_ids": list(self.context_artifact_ids),
            "catalog_tool_id": self.catalog_tool_id,
            "tool_inputs": {} if self.tool_inputs is None else dict(self.tool_inputs),
            "execution_mode": self.execution_mode,
            "require_approval": self.require_approval,
            "requested_action": self.requested_action,
        }


@dataclass(frozen=True, slots=True)
class ExecutionStartResult:
    invocation: EngineInvocation
    run: RunRecord | None
    approval: ApprovalRequest | None
    artifacts: tuple[SessionArtifactRecord, ...] = ()
    parsed_result: ExecutionParsedResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation": self.invocation.to_dict(),
            "run": None if self.run is None else self.run.to_dict(),
            "approval": None if self.approval is None else self.approval.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "parsed_result": None if self.parsed_result is None else self.parsed_result.to_dict(),
        }


@dataclass(slots=True)
class DefaultExecutionRequestCompiler:
    def compile_request(
        self,
        *,
        handoff: ExecutionHandoff,
        task: Any,
        resolved_required_artifacts: tuple[SessionArtifactRecord, ...],
        resolved_context_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> dict[str, Any]:
        tool_inputs = {} if handoff.tool_inputs is None else dict(handoff.tool_inputs)
        primary_input = None if not resolved_required_artifacts else resolved_required_artifacts[0]
        subject_id = "artifact" if primary_input is None else primary_input.artifact_id
        subject_label = "artifact" if primary_input is None else (
            primary_input.title or primary_input.relative_path or primary_input.artifact_id
        )
        metadata = {
            "catalog_tool_id": handoff.catalog_tool_id,
            "tool_inputs": tool_inputs,
            "execution_goal": handoff.execution_goal,
            "required_artifact_ids": list(handoff.required_artifact_ids),
            "context_artifact_ids": list(handoff.context_artifact_ids),
            "resolved_artifacts": [artifact.to_dict() for artifact in (*resolved_required_artifacts, *resolved_context_artifacts)],
            "task_id": task.task_id,
        }
        if handoff.catalog_tool_id == "fpocket":
            structure_path = str(
                tool_inputs.get("structure_path")
                or (None if primary_input is None else primary_input.storage_uri)
                or "input_structure.pdb"
            )
            return {
                "tool_name": "exec.run",
                "runspec": {
                    "name": f"execution-{subject_id}",
                    "stage": "execution",
                    "command": ["fpocket", "-f", structure_path],
                    "execution_mode": handoff.execution_mode,
                    "metadata": metadata,
                },
            }
        if handoff.catalog_tool_id == "vina":
            receptor_path = str(
                tool_inputs.get("receptor_path")
                or (None if primary_input is None else primary_input.storage_uri)
                or "receptor.pdbqt"
            )
            ligand_path = str(tool_inputs.get("ligand_path") or "ligand.pdbqt")
            return {
                "tool_name": "exec.run",
                "runspec": {
                    "name": f"execution-{subject_id}",
                    "stage": "execution",
                    "command": ["vina", "--receptor", receptor_path, "--ligand", ligand_path],
                    "execution_mode": handoff.execution_mode,
                    "metadata": metadata,
                },
            }
        return {
            "tool_name": "exec.run",
            "runspec": {
                "name": f"execution-{subject_id}",
                "stage": "execution",
                "command": ["echo", subject_label],
                "execution_mode": handoff.execution_mode,
                "metadata": metadata,
            },
        }


@dataclass(slots=True)
class DefaultExecutionResultParser:
    def parse_result(
        self,
        *,
        handoff: ExecutionHandoff,
        outcome: ExecutionOutcome,
        artifact_refs: tuple[SessionArtifactRecord, ...],
    ) -> ExecutionParsedResult:
        if handoff.catalog_tool_id == "fpocket":
            pockets_found = int(outcome.raw_result.get("pockets_found") or 1)
            return ExecutionParsedResult(
                result_summary=f"fpocket found {pockets_found} pocket(s) for the selected artifact set.",
                structured_findings={
                    "design_signal": "proceed" if pockets_found > 0 else "revise",
                    "pockets_found": pockets_found,
                    "artifacts": [artifact.to_dict() for artifact in artifact_refs],
                },
            )
        if handoff.catalog_tool_id == "vina":
            affinity_value = outcome.raw_result.get("best_affinity")
            try:
                affinity = float(affinity_value)
            except (TypeError, ValueError):
                affinity = -5.5
            return ExecutionParsedResult(
                result_summary=f"vina completed with best affinity {affinity:.2f} kcal/mol.",
                structured_findings={
                    "design_signal": "proceed" if affinity <= -6.0 else "revise",
                    "best_affinity": affinity,
                    "artifacts": [artifact.to_dict() for artifact in artifact_refs],
                },
            )
        return ExecutionParsedResult(
            result_summary=f"{handoff.catalog_tool_id} execution completed.",
            structured_findings={
                "design_signal": "proceed",
                "artifacts": [artifact.to_dict() for artifact in artifact_refs],
            },
        )


@dataclass(slots=True)
class ExecutionEngine:
    repositories: Any
    runner: ExecutionRunner
    compiler: ExecutionRequestCompiler | None = None
    parser: ExecutionResultParser | None = None
    event_emitter: Any | None = None

    @property
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            engine_name="execution",
            tool_names=(
                "execution.start",
                "execution.resume",
                "execution.status",
            ),
            input_schema={"type": "object", "required": ["task_id", "handoff"]},
            output_schema={
                "type": "object",
                "required": ["invocation"],
            },
            requires_approval=True,
            supports_background=True,
            idempotency_key_shape="{task_id}:execution:{nonce}",
            produces_artifact_types=("run", "artifact"),
            capability_key="execution",
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        register_execution_tools(registry, self)

    def start_execution(
        self,
        *,
        session_id: str,
        task_id: str,
        handoff: dict[str, Any],
        invocation_id: str | None = None,
        lane_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ExecutionStartResult:
        session = self._require_session(session_id)
        task = self._require_task(session_id, task_id)
        handoff_model = ExecutionHandoff.from_payload(handoff)
        effective_lane_id = task.lane_id if lane_id is None else lane_id
        now = utc_now_iso()
        invocation_id = invocation_id or f"inv_{uuid4().hex[:12]}"
        input_id = _new_document_id("eng_in")
        approval = None
        approval_id = None
        invocation_status = EngineInvocationStatus.RUNNING
        if handoff_model.require_approval:
            approval_id = f"appr_{uuid4().hex[:12]}"
            approval = ApprovalRequest(
                approval_id=approval_id,
                session_id=session_id,
                task_id=task_id,
                lane_id=effective_lane_id,
                kind="execution_launch",
                requested_action=handoff_model.requested_action
                or f"Approve execution launch for task {task.subject}",
                status=ApprovalRequestStatus.PENDING,
                request_ref=f"artifact://approvals/{approval_id}.json",
                resolution_ref=None,
                created_at=now,
            )
            self.repositories.approvals.save(approval)
            invocation_status = EngineInvocationStatus.WAITING_APPROVAL
            self._emit(
                "approval.requested",
                {
                    "approval_id": approval.approval_id,
                    "task_id": approval.task_id,
                    "lane_id": approval.lane_id,
                    "kind": approval.kind,
                },
            )
        invocation = EngineInvocation(
            invocation_id=invocation_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            engine_name=self.descriptor.engine_name,
            status=invocation_status,
            input_ref=input_id,
            output_ref=None,
            approval_id=approval_id,
            idempotency_key=idempotency_key or f"{task_id}:execution:{uuid4().hex[:8]}",
            started_at=now,
        )
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_input",
                payload={"task_id": task_id, "lane_id": effective_lane_id, "handoff": handoff_model.to_dict()},
                created_at=now,
                updated_at=now,
            )
        )
        self._emit(
            "engine.invocation.started",
            {"invocation_id": invocation_id, "engine_name": self.descriptor.engine_name, "task_id": task_id},
        )
        if approval is not None:
            return ExecutionStartResult(invocation=invocation, run=None, approval=approval)
        return self._submit_execution(session=session, task=task, invocation=invocation, handoff=handoff_model)

    def resume_execution(self, *, invocation_id: str, resolution: str | None = None) -> ExecutionStartResult:
        invocation = self._require_invocation(invocation_id)
        session = self._require_session(invocation.session_id)
        task = self._require_task(invocation.session_id, str(invocation.task_id))
        handoff = self._load_handoff(invocation)
        approval = None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)
        self._update_input_document(invocation, resolution=resolution)
        if approval is None:
            running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
            self.repositories.invocations.save(running)
            return self._submit_execution(session=session, task=task, invocation=running, handoff=handoff)
        if approval.status is ApprovalRequestStatus.APPROVED:
            running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
            self.repositories.invocations.save(running)
            self._emit(
                "engine.invocation.updated",
                {"invocation_id": running.invocation_id, "engine_name": running.engine_name, "status": "running"},
            )
            return self._submit_execution(session=session, task=task, invocation=running, handoff=handoff)
        cancelled = self._replace_invocation(invocation, status=EngineInvocationStatus.CANCELLED, finished_at=utc_now_iso())
        self.repositories.invocations.save(cancelled)
        self._emit(
            "engine.invocation.completed",
            {"invocation_id": cancelled.invocation_id, "engine_name": cancelled.engine_name, "status": "cancelled"},
        )
        return ExecutionStartResult(invocation=cancelled, run=None, approval=approval)

    def get_execution_status(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._require_invocation(invocation_id)
        payload = invocation.to_dict()
        if invocation.status is EngineInvocationStatus.WAITING_APPROVAL:
            approval = None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)
            payload["approval"] = None if approval is None else approval.to_dict()
            return payload
        run = self.repositories.runs.get_by_invocation(invocation.session_id, invocation.invocation_id)
        if run is None:
            return payload
        if invocation.status.is_terminal and invocation.output_ref is not None:
            payload["run"] = run.to_dict()
            payload["artifacts"] = [
                artifact.to_dict() for artifact in self.repositories.artifacts.list_by_run(run.run_id)
            ]
            return payload
        reconciled = self.reconcile_execution(invocation_id)
        return reconciled.to_dict()

    def reconcile_execution(self, invocation_id: str) -> ExecutionStartResult:
        invocation = self._require_invocation(invocation_id)
        if invocation.status is EngineInvocationStatus.WAITING_APPROVAL:
            approval = None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)
            return ExecutionStartResult(invocation=invocation, run=None, approval=approval)
        run = self._require_run(invocation)
        status = self.runner.get_execution_status(
            run_id=run.runner_run_id,
            remote_run_dir=run.remote_run_dir,
            job_id=run.runner_run_id if run.execution_mode == "sbatch" else None,
        )
        updated_run = RunRecord(
            run_id=run.run_id,
            session_id=run.session_id,
            task_id=run.task_id,
            lane_id=run.lane_id,
            invocation_id=run.invocation_id,
            approval_id=run.approval_id,
            engine_name=run.engine_name,
            runner_run_id=run.runner_run_id,
            status=status.status,
            execution_mode=run.execution_mode,
            remote_run_dir=status.remote_run_dir,
            summary=run.summary,
            created_at=run.created_at,
            updated_at=utc_now_iso(),
            finished_at=run.finished_at,
        )
        self.repositories.runs.save(updated_run)
        if not status.status.is_terminal:
            running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
            self.repositories.invocations.save(running)
            return ExecutionStartResult(invocation=running, run=updated_run, approval=self._load_approval(running))
        input_payload = self._require_input_payload(invocation)
        runspec = dict((input_payload.get("request") or {}).get("runspec") or {})
        if status.status is RunStatus.SUCCEEDED:
            fetched = self.runner.fetch_execution_artifacts(
                run_id=run.runner_run_id,
                remote_run_dir=run.remote_run_dir,
                job_id=run.runner_run_id if run.execution_mode == "sbatch" else None,
                runspec=runspec,
            )
            return self._finalize_terminal(
                invocation=invocation,
                run=updated_run,
                handoff=self._load_handoff(invocation),
                outcome=fetched,
            )
        terminal_outcome = ExecutionOutcome(
            run_id=status.run_id,
            status=status.status,
            execution_mode=run.execution_mode,
            remote_run_dir=status.remote_run_dir,
            raw_result=status.raw_result,
            artifacts=(),
            job_id=status.job_id,
            exit_code=status.exit_code,
        )
        return self._finalize_terminal(
            invocation=invocation,
            run=updated_run,
            handoff=self._load_handoff(invocation),
            outcome=terminal_outcome,
        )

    def _submit_execution(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        handoff: ExecutionHandoff,
    ) -> ExecutionStartResult:
        required_artifacts = self._resolve_artifacts(session.session_id, handoff.required_artifact_ids)
        context_artifacts = self._resolve_artifacts(session.session_id, handoff.context_artifact_ids)
        compiler = self.compiler or DefaultExecutionRequestCompiler()
        request = compiler.compile_request(
            handoff=handoff,
            task=task,
            resolved_required_artifacts=required_artifacts,
            resolved_context_artifacts=context_artifacts,
        )
        self._update_input_document(invocation, request=request)
        outcome = self.runner.submit_execution(session.session_id, request)
        now = utc_now_iso()
        run = RunRecord(
            run_id=f"run_{invocation.invocation_id}",
            session_id=session.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            approval_id=invocation.approval_id,
            engine_name=invocation.engine_name,
            runner_run_id=outcome.job_id or outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            summary=None,
            created_at=now,
            updated_at=now,
            finished_at=now if outcome.status.is_terminal else None,
        )
        self.repositories.runs.save(run)
        if outcome.status.is_terminal:
            return self._finalize_terminal(invocation=invocation, run=run, handoff=handoff, outcome=outcome)
        running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
        self.repositories.invocations.save(running)
        self._emit(
            "engine.invocation.updated",
            {"invocation_id": running.invocation_id, "engine_name": running.engine_name, "status": "running"},
        )
        return ExecutionStartResult(invocation=running, run=run, approval=None)

    def _finalize_terminal(
        self,
        *,
        invocation: EngineInvocation,
        run: RunRecord,
        handoff: ExecutionHandoff,
        outcome: ExecutionOutcome,
    ) -> ExecutionStartResult:
        now = utc_now_iso()
        artifacts = self._persist_artifacts(
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            run_id=run.run_id,
            created_at=now,
            artifacts=outcome.artifacts,
        )
        parser = self.parser or DefaultExecutionResultParser()
        parsed_result = parser.parse_result(handoff=handoff, outcome=outcome, artifact_refs=artifacts)
        output_id = _new_document_id("eng_out")
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="execution_result",
                payload={
                    "run": run.to_dict(),
                    "outcome": {
                        "run_id": outcome.run_id,
                        "status": outcome.status.value,
                        "execution_mode": outcome.execution_mode,
                        "remote_run_dir": outcome.remote_run_dir,
                        "job_id": outcome.job_id,
                        "exit_code": outcome.exit_code,
                        "artifacts": [artifact.to_dict() for artifact in outcome.artifacts],
                        "raw_result": outcome.raw_result,
                    },
                    "parsed_result": parsed_result.to_dict(),
                },
                created_at=now,
                updated_at=now,
            )
        )
        updated_run = RunRecord(
            run_id=run.run_id,
            session_id=run.session_id,
            task_id=run.task_id,
            lane_id=run.lane_id,
            invocation_id=run.invocation_id,
            approval_id=run.approval_id,
            engine_name=run.engine_name,
            runner_run_id=run.runner_run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            summary=parsed_result.result_summary,
            created_at=run.created_at,
            updated_at=now,
            finished_at=now,
        )
        self.repositories.runs.save(updated_run)
        finalized_invocation = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=_invocation_status_from_run(outcome.status),
            input_ref=invocation.input_ref,
            output_ref=output_id,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(finalized_invocation)
        self.repositories.memory.save(
            MemoryEntry(
                memory_id=f"mem_{uuid4().hex[:12]}",
                session_id=invocation.session_id,
                scope_kind=MemoryScopeKind.TASK,
                scope_ref=str(invocation.task_id or invocation.session_id),
                kind=MemoryKind.SUMMARY,
                summary=parsed_result.result_summary,
                source_range=f"engine:{invocation.invocation_id}",
                importance=6,
                created_at=now,
            )
        )
        self._emit(
            "engine.invocation.completed",
            {
                "invocation_id": finalized_invocation.invocation_id,
                "engine_name": finalized_invocation.engine_name,
                "status": finalized_invocation.status.value,
            },
        )
        return ExecutionStartResult(
            invocation=finalized_invocation,
            run=updated_run,
            approval=None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id),
            artifacts=artifacts,
            parsed_result=parsed_result,
        )

    def _persist_artifacts(
        self,
        *,
        session_id: str,
        task_id: str | None,
        lane_id: str | None,
        invocation_id: str,
        run_id: str,
        created_at: str,
        artifacts: tuple[ExecutionArtifactRef, ...],
    ) -> tuple[SessionArtifactRecord, ...]:
        persisted: list[SessionArtifactRecord] = []
        for artifact in artifacts:
            artifact_id = f"{run_id}:{_safe_ref(artifact.relative_path)}"
            record = SessionArtifactRecord(
                artifact_id=artifact_id,
                session_id=session_id,
                task_id=task_id,
                lane_id=lane_id,
                invocation_id=invocation_id,
                run_id=run_id,
                kind=artifact.kind,
                storage_uri=artifact.storage_uri,
                relative_path=artifact.relative_path,
                title=PurePosixPath(artifact.relative_path).name,
                description=None,
                metadata={"source": "execution_engine"},
                created_at=created_at,
            )
            self.repositories.artifacts.save(record)
            persisted.append(record)
        return tuple(persisted)

    def _resolve_artifacts(self, session_id: str, artifact_ids: tuple[str, ...]) -> tuple[SessionArtifactRecord, ...]:
        resolved: list[SessionArtifactRecord] = []
        for artifact_id in artifact_ids:
            artifact = self.repositories.artifacts.get(artifact_id)
            if artifact is None:
                raise ValueError(f"artifact {artifact_id!r} does not exist")
            if artifact.session_id != session_id:
                raise ValueError(f"artifact {artifact_id!r} belongs to session {artifact.session_id!r}, not {session_id!r}")
            resolved.append(artifact)
        return tuple(resolved)

    def _require_run(self, invocation: EngineInvocation) -> RunRecord:
        run = self.repositories.runs.get_by_invocation(invocation.session_id, invocation.invocation_id)
        if run is None:
            raise ValueError(f"invocation {invocation.invocation_id!r} does not have a persisted run")
        return run

    def _load_approval(self, invocation: EngineInvocation) -> ApprovalRequest | None:
        return None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)

    def _load_handoff(self, invocation: EngineInvocation) -> ExecutionHandoff:
        input_payload = self._require_input_payload(invocation)
        return ExecutionHandoff.from_payload(dict(input_payload["handoff"]))

    def _require_session(self, session_id: str) -> Any:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        return session

    def _require_task(self, session_id: str, task_id: str) -> Any:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        if task.session_id != session_id:
            raise ValueError(f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}")
        return task

    def _require_invocation(self, invocation_id: str) -> EngineInvocation:
        invocation = self.repositories.invocations.get(invocation_id)
        if invocation is None:
            raise ValueError(f"invocation {invocation_id!r} does not exist")
        return invocation

    def _require_input_payload(self, invocation: EngineInvocation) -> dict[str, Any]:
        if invocation.input_ref is None:
            raise ValueError(f"invocation {invocation.invocation_id!r} does not have an input document")
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            raise ValueError(f"input document {invocation.input_ref!r} does not exist")
        return document.payload

    def _update_input_document(
        self,
        invocation: EngineInvocation,
        *,
        request: dict[str, Any] | None = None,
        resolution: str | None = None,
    ) -> None:
        if invocation.input_ref is None:
            return
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            return
        payload = dict(document.payload)
        if request is not None:
            payload["request"] = request
        if resolution is not None:
            payload["resolution"] = resolution
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=document.document_id,
                session_id=document.session_id,
                invocation_id=str(document.invocation_id),
                document_kind=document.document_kind,
                payload=payload,
                created_at=document.created_at,
                updated_at=utc_now_iso(),
            )
        )

    def _replace_invocation(
        self,
        invocation: EngineInvocation,
        *,
        status: EngineInvocationStatus,
        finished_at: str | None,
    ) -> EngineInvocation:
        return EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=status,
            input_ref=invocation.input_ref,
            output_ref=invocation.output_ref,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=finished_at,
        )

    def _document_record(
        self,
        *,
        document_id: str,
        session_id: str,
        invocation_id: str,
        document_kind: str,
        payload: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> Any:
        from openzyme_core import EngineDocumentRecord

        return EngineDocumentRecord(
            document_id=document_id,
            session_id=session_id,
            invocation_id=invocation_id,
            document_kind=document_kind,
            payload=payload,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)


def register_execution_tools(registry: ToolRegistry, engine: ExecutionEngine) -> None:
    def start_handler(context: Any, invocation: ToolInvocation) -> ToolResult:
        result = engine.start_execution(
            session_id=context.snapshot.session.session_id,
            task_id=str(invocation.arguments["task_id"]),
            handoff=dict(invocation.arguments["handoff"]),
            invocation_id=None if invocation.arguments.get("invocation_id") is None else str(invocation.arguments["invocation_id"]),
            lane_id=invocation.lane_id if invocation.arguments.get("lane_id") is None else str(invocation.arguments["lane_id"]),
            idempotency_key=None if invocation.arguments.get("idempotency_key") is None else str(invocation.arguments["idempotency_key"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status not in {EngineInvocationStatus.FAILED, EngineInvocationStatus.CANCELLED},
            content=json.dumps(result.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )

    def resume_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        result = engine.resume_execution(
            invocation_id=str(invocation.arguments["invocation_id"]),
            resolution=None if invocation.arguments.get("resolution") is None else str(invocation.arguments["resolution"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status not in {EngineInvocationStatus.FAILED, EngineInvocationStatus.CANCELLED},
            content=json.dumps(result.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )

    def status_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        status = engine.get_execution_status(str(invocation.arguments["invocation_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(status, sort_keys=True),
        )

    registry.register("execution.start", start_handler)
    registry.register("execution.resume", resume_handler)
    registry.register("execution.status", status_handler)


__all__ = [
    "DefaultExecutionRequestCompiler",
    "DefaultExecutionResultParser",
    "ExecutionArtifactRef",
    "ExecutionEngine",
    "ExecutionHandoff",
    "ExecutionOutcome",
    "ExecutionParsedResult",
    "ExecutionRequestCompiler",
    "ExecutionRunner",
    "ExecutionStartResult",
    "ExecutionStatusSnapshot",
    "register_execution_tools",
]
