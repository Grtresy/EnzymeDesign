from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Command
from langgraph.types import interrupt
from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import Run
from openzyme_domain import RunStatus
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .state import ExecutionHandoff
from .state import GraphPhase
from .state import InterruptType
from .state import ProgressStatus
from .state import SupervisorStatus


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _progress(active_node: str, status: ProgressStatus, message: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.EXECUTION.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


def _build_approval_id(episode_id: str) -> str:
    return f"{episode_id}-execution-approval"


def _build_artifact_id(run_id: str, index: int) -> str:
    return f"{run_id}-artifact-{index}"


def _resolve_artifact_kind(value: str) -> ArtifactKind:
    try:
        return ArtifactKind(value)
    except ValueError:
        return ArtifactKind.RESULT


class ExecutionSubgraphState(TypedDict, total=False):
    episode_id: str
    project_id: str
    objective: str
    current_phase: str
    status: str
    progress: dict[str, Any]
    pending_interrupt: dict[str, Any] | None
    candidate_plan: dict[str, Any]
    run_request: dict[str, Any]
    approval_id: str | None
    approval_decision: dict[str, Any] | None
    run_summary: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    latest_run_id: str | None
    recommended_next_phase: str | None
    execution_handoff: ExecutionHandoff | None


def build_execution_subgraph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    def prepare_execution_approval(state: ExecutionSubgraphState) -> dict[str, Any]:
        approval_id = _build_approval_id(state["episode_id"])
        requested_action = "Approve execution submission"
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.PENDING,
                requested_action=requested_action,
                created_at=_utc_now_iso(),
            )
        )
        return {
            "approval_id": approval_id,
            "pending_interrupt": {
                "type": InterruptType.APPROVAL.value,
                "episode_id": state["episode_id"],
                "phase": GraphPhase.EXECUTION.value,
                "approval_id": approval_id,
                "requested_action": requested_action,
            },
            "current_phase": GraphPhase.EXECUTION.value,
            "status": SupervisorStatus.INTERRUPTED.value,
            "progress": _progress(
                "execution_review_gate",
                ProgressStatus.WAITING,
                "Waiting for execution approval",
            ),
        }

    def execution_review_gate(
        state: ExecutionSubgraphState,
    ) -> Command[Literal["execute_runner", "__end__"]]:
        approval_id = str(state["approval_id"])
        decision = interrupt(state["pending_interrupt"])
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
                requested_action="Approve execution submission",
                created_at=_utc_now_iso(),
                resolved_at=_utc_now_iso(),
            )
        )
        if not approved:
            return Command(
                update={
                    "approval_decision": {"approved": False},
                    "pending_interrupt": None,
                    "status": SupervisorStatus.FAILED.value,
                    "progress": _progress(
                        "execution_review_gate",
                        ProgressStatus.FAILED,
                        "Execution submission rejected",
                    ),
                },
                goto=END,
            )
        return Command(
            update={
                "approval_decision": {"approved": True},
                "pending_interrupt": None,
                "current_phase": GraphPhase.EXECUTION.value,
                "status": SupervisorStatus.ACTIVE.value,
                "progress": _progress(
                    "execute_runner",
                    ProgressStatus.RUNNING,
                    "Approval received; executing runner",
                ),
            },
            goto="execute_runner",
        )

    def execute_runner(state: ExecutionSubgraphState) -> dict[str, Any]:
        if inputs.execution_adapter is None:
            msg = "execution_adapter is required for the execution node"
            raise RuntimeError(msg)
        outcome = inputs.execution_adapter.submit_execution(
            state["episode_id"],
            state["run_request"],
        )
        created_at = _utc_now_iso()
        completed_at = created_at if outcome.status.is_terminal else None
        run = Run(
            run_id=outcome.run_id,
            episode_id=state["episode_id"],
            approval_id=state.get("approval_id"),
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            created_at=created_at,
            completed_at=completed_at,
        )
        inputs.repositories.runs.save(run)

        artifact_payloads: list[dict[str, Any]] = []
        for index, artifact in enumerate(outcome.artifacts, start=1):
            record = ArtifactRecord(
                artifact_id=_build_artifact_id(outcome.run_id, index),
                episode_id=state["episode_id"],
                run_id=outcome.run_id,
                kind=_resolve_artifact_kind(artifact.kind.value),
                storage_uri=artifact.storage_uri,
                created_at=_utc_now_iso(),
            )
            inputs.repositories.artifact_records.save(record)
            artifact_payloads.append(
                {
                    "artifact_id": record.artifact_id,
                    "kind": record.kind.value,
                    "storage_uri": record.storage_uri,
                }
            )

        run_summary = {
            "run_id": outcome.run_id,
            "status": outcome.status.value,
            "execution_mode": outcome.execution_mode,
            "remote_run_dir": outcome.remote_run_dir,
        }
        execution_handoff: ExecutionHandoff = {
            "run_summary": run_summary,
            "artifact_refs": artifact_payloads,
            "latest_run_id": outcome.run_id,
            "recommended_next_phase": GraphPhase.REPORT_REVIEW.value,
        }
        return {
            "current_phase": GraphPhase.EXECUTION.value,
            "status": (
                SupervisorStatus.COMPLETED.value
                if outcome.status is RunStatus.SUCCEEDED
                else SupervisorStatus.FAILED.value
            ),
            "run_summary": run_summary,
            "artifact_refs": artifact_payloads,
            "latest_run_id": outcome.run_id,
            "recommended_next_phase": GraphPhase.REPORT_REVIEW.value,
            "execution_handoff": execution_handoff,
            "progress": _progress(
                "execute_runner",
                ProgressStatus.SUCCEEDED if outcome.status is RunStatus.SUCCEEDED else ProgressStatus.FAILED,
                "Execution completed" if outcome.status is RunStatus.SUCCEEDED else "Execution failed",
            ),
        }

    graph = StateGraph(ExecutionSubgraphState)
    graph.add_node("prepare_execution_approval", prepare_execution_approval)
    graph.add_node("execution_review_gate", execution_review_gate)
    graph.add_node("execute_runner", execute_runner)
    graph.add_edge(START, "prepare_execution_approval")
    graph.add_edge("prepare_execution_approval", "execution_review_gate")
    graph.add_edge("execute_runner", END)
    if include_checkpointer:
        return graph.compile(checkpointer=inputs.checkpointer)
    return graph.compile()
