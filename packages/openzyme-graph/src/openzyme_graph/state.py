from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import TypedDict

from openzyme_domain import CORE_ENTITY_NAMES
from openzyme_storage import CHECKPOINT_STATE_FIELDS


class GraphPhase(StrEnum):
    INTAKE = "intake"
    DESIGN = "design"
    EXECUTION = "execution"
    REPORT_REVIEW = "report_review"


class SupervisorStatus(StrEnum):
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    COMPLETED = "completed"


class InterruptType(StrEnum):
    CLARIFICATION = "clarification"
    APPROVAL = "approval"
    ESCALATION = "escalation"
    RECOVERABLE_FAILURE = "recoverable_failure"


class ProgressStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


FIXED_PHASES: tuple[str, ...] = (
    GraphPhase.INTAKE.value,
    GraphPhase.DESIGN.value,
    GraphPhase.EXECUTION.value,
    GraphPhase.REPORT_REVIEW.value,
)
GRAPH_THREAD_KEY = "episode_id"
RESUMABLE_STATUSES: frozenset[SupervisorStatus] = frozenset(
    {SupervisorStatus.ACTIVE, SupervisorStatus.INTERRUPTED},
)


class RuntimeInterruptPayload(TypedDict):
    type: str
    episode_id: str
    phase: str
    reason: str
    active_state_version: int
    checkpoint_ns: str
    checkpoint_id: str
    approval_id: str | None
    requested_action: str | None
    details: dict[str, Any] | None


class RuntimeProgressState(TypedDict):
    phase: str
    active_node: str
    status: str
    updated_at: str
    message: str | None


class RuntimeSupervisorState(TypedDict):
    episode_id: str
    current_phase: str
    status: str
    checkpoint_ns: str
    checkpoint_id: str
    progress: RuntimeProgressState
    pending_interrupt: RuntimeInterruptPayload | None


class IntakeHandoff(TypedDict):
    design_brief: str
    research_brief: str
    recommended_next_phase: str


class DesignHandoff(TypedDict):
    candidate_plan: dict[str, Any]
    run_summary: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    design_summary: dict[str, Any]
    selected_candidate_id: str | None
    recent_turns: list[dict[str, Any]]
    recommended_next_phase: str


class ExecutionHandoff(TypedDict):
    candidate_plan: dict[str, Any]
    execution_goal: str
    question_to_answer: str
    preferred_stage_tags: list[str]
    preferred_capability_tags: list[str]
    recommended_next_phase: str


@dataclass(frozen=True, slots=True)
class CheckpointLineage:
    thread_id: str
    checkpoint_ns: str
    checkpoint_id: str


@dataclass(frozen=True, slots=True)
class ResumeAnchor:
    episode_id: str
    checkpoint: CheckpointLineage
    active_state_version: int


@dataclass(frozen=True, slots=True)
class ApprovalPayload:
    approval_id: str
    requested_action: str


@dataclass(frozen=True, slots=True)
class InterruptEnvelope:
    type: InterruptType
    episode_id: str
    phase: GraphPhase
    resume_anchor: ResumeAnchor
    reason: str
    approval: ApprovalPayload | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        data["phase"] = self.phase.value
        return data

    def to_runtime_interrupt_payload(self) -> RuntimeInterruptPayload:
        return {
            "type": self.type.value,
            "episode_id": self.episode_id,
            "phase": self.phase.value,
            "reason": self.reason,
            "active_state_version": self.resume_anchor.active_state_version,
            "checkpoint_ns": self.resume_anchor.checkpoint.checkpoint_ns,
            "checkpoint_id": self.resume_anchor.checkpoint.checkpoint_id,
            "approval_id": None if self.approval is None else self.approval.approval_id,
            "requested_action": None if self.approval is None else self.approval.requested_action,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class NodeProgress:
    phase: GraphPhase
    active_node: str
    status: ProgressStatus
    updated_at: str
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.phase.value
        data["status"] = self.status.value
        return data

    def to_runtime_progress_state(self) -> RuntimeProgressState:
        return {
            "phase": self.phase.value,
            "active_node": self.active_node,
            "status": self.status.value,
            "updated_at": self.updated_at,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class SubgraphContract:
    phase: GraphPhase
    required_inputs: tuple[str, ...]
    completion_outputs: tuple[str, ...]
    interrupt_types: tuple[InterruptType, ...]


@dataclass(frozen=True, slots=True)
class SupervisorState:
    episode_id: str
    current_phase: GraphPhase
    status: SupervisorStatus
    checkpoint: CheckpointLineage
    progress: NodeProgress
    pending_interrupt: InterruptEnvelope | None = None

    @property
    def thread_id(self) -> str:
        return self.episode_id

    @property
    def is_resumable(self) -> bool:
        return self.status in RESUMABLE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["current_phase"] = self.current_phase.value
        data["status"] = self.status.value
        if self.pending_interrupt is not None:
            data["pending_interrupt"]["type"] = self.pending_interrupt.type.value
            data["pending_interrupt"]["phase"] = self.pending_interrupt.phase.value
        data["progress"]["phase"] = self.progress.phase.value
        data["progress"]["status"] = self.progress.status.value
        return data

    def to_runtime_state(self) -> RuntimeSupervisorState:
        return {
            "episode_id": self.episode_id,
            "current_phase": self.current_phase.value,
            "status": self.status.value,
            "checkpoint_ns": self.checkpoint.checkpoint_ns,
            "checkpoint_id": self.checkpoint.checkpoint_id,
            "progress": self.progress.to_runtime_progress_state(),
            "pending_interrupt": None
            if self.pending_interrupt is None
            else self.pending_interrupt.to_runtime_interrupt_payload(),
        }


def build_subgraph_contracts() -> dict[GraphPhase, SubgraphContract]:
    return {
        GraphPhase.INTAKE: SubgraphContract(
            phase=GraphPhase.INTAKE,
            required_inputs=("episode_id", "user_goal", "project_context"),
            completion_outputs=("intake_handoff",),
            interrupt_types=(InterruptType.CLARIFICATION,),
        ),
        GraphPhase.DESIGN: SubgraphContract(
            phase=GraphPhase.DESIGN,
            required_inputs=("episode_id", "design_brief"),
            completion_outputs=("design_handoff", "execution_handoff"),
            interrupt_types=(InterruptType.CLARIFICATION,),
        ),
        GraphPhase.EXECUTION: SubgraphContract(
            phase=GraphPhase.EXECUTION,
            required_inputs=("episode_id", "execution_handoff"),
            completion_outputs=("execution_result_handoff",),
            interrupt_types=(InterruptType.APPROVAL,),
        ),
        GraphPhase.REPORT_REVIEW: SubgraphContract(
            phase=GraphPhase.REPORT_REVIEW,
            required_inputs=("episode_id", "design_handoff"),
            completion_outputs=("report_summary", "report_artifact_id"),
            interrupt_types=(),
        ),
    }


def validate_domain_and_storage_alignment() -> None:
    assert "Episode" in CORE_ENTITY_NAMES
    assert GRAPH_THREAD_KEY == "episode_id"
    assert "current_phase" in CHECKPOINT_STATE_FIELDS
    assert "pending_interrupt" in CHECKPOINT_STATE_FIELDS


def build_langgraph_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def build_resume_command_payload(resume_value: bool | str | dict[str, Any]) -> dict[str, Any]:
    # Host/API layers can translate this payload into Command(resume=...) at invoke time.
    return {"resume": resume_value}
