from __future__ import annotations

from dataclasses import asdict
from dataclasses import field
from dataclasses import dataclass
from typing import Any
import uuid

from mcp_project_memory.models import utc_now_iso


def new_object_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class DesignContract:
    summary: str
    goals: list[str]
    constraints: list[str]
    assumptions: list[str]
    open_questions: list[str]
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["_meta"] = payload.pop("meta")
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> DesignContract:
        payload = payload or {}
        return cls(
            summary=str(payload.get("summary") or ""),
            goals=[str(item) for item in payload.get("goals") or []],
            constraints=[str(item) for item in payload.get("constraints") or []],
            assumptions=[str(item) for item in payload.get("assumptions") or []],
            open_questions=[str(item) for item in payload.get("open_questions") or []],
            meta=dict(payload.get("_meta") or {}),
        )


@dataclass(slots=True)
class ToolAction:
    tool: str
    inputs: dict[str, Any]
    risk_level: str = "normal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> ToolAction | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            tool=str(payload.get("tool") or ""),
            inputs=dict(payload.get("inputs") or {}),
            risk_level=str(payload.get("risk_level") or "normal"),
        )


@dataclass(slots=True)
class AgentAction:
    action_id: str
    kind: str
    title: str
    rationale: str
    action_revision: int = 1
    tool_action: ToolAction | None = None
    gate_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_revision": self.action_revision,
            "kind": self.kind,
            "title": self.title,
            "rationale": self.rationale,
            "tool_action": self.tool_action.to_dict() if self.tool_action else None,
            "gate_id": self.gate_id,
            "_meta": self.meta,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> AgentAction | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            action_id=str(payload.get("action_id") or new_object_id("action")),
            action_revision=int(payload.get("action_revision") or 1),
            kind=str(payload.get("kind") or "noop"),
            title=str(payload.get("title") or ""),
            rationale=str(payload.get("rationale") or ""),
            tool_action=ToolAction.from_dict(payload.get("tool_action")),
            gate_id=_optional_str(payload.get("gate_id")),
            meta=dict(payload.get("_meta") or {}),
        )


@dataclass(slots=True)
class AgentObservation:
    observation_id: str
    source: str
    summary: str
    created_at: str
    payload: dict[str, Any]
    run_id: str | None = None
    manifest_path: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["_meta"] = payload.pop("meta")
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> AgentObservation | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            observation_id=str(payload.get("observation_id") or new_object_id("obs")),
            source=str(payload.get("source") or "system"),
            summary=str(payload.get("summary") or ""),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            payload=dict(payload.get("payload") or {}),
            run_id=_optional_str(payload.get("run_id")),
            manifest_path=_optional_str(payload.get("manifest_path")),
            meta=dict(payload.get("_meta") or {}),
        )


@dataclass(slots=True)
class HumanFeedback:
    feedback_id: str
    kind: str
    content: str
    actor: str
    created_at: str
    interrupt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> HumanFeedback | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            feedback_id=str(payload.get("feedback_id") or new_object_id("feedback")),
            kind=str(payload.get("kind") or "comment"),
            content=str(payload.get("content") or ""),
            actor=str(payload.get("actor") or "host-user"),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            interrupt_id=_optional_str(payload.get("interrupt_id")),
        )


@dataclass(slots=True)
class ApprovalGate:
    gate_id: str
    action_id: str
    action_revision: int
    action_type: str
    risk_level: str
    policy_reason: str
    required_feedback_type: str
    status: str
    created_at: str
    action_snapshot: dict[str, Any]
    resolved_by: str | None = None
    resolved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> ApprovalGate | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            gate_id=str(payload.get("gate_id") or new_object_id("gate")),
            action_id=str(payload.get("action_id") or ""),
            action_revision=int(payload.get("action_revision") or 1),
            action_type=str(payload.get("action_type") or ""),
            risk_level=str(payload.get("risk_level") or "normal"),
            policy_reason=str(payload.get("policy_reason") or ""),
            required_feedback_type=str(payload.get("required_feedback_type") or "approval"),
            status=str(payload.get("status") or "pending"),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            action_snapshot=dict(payload.get("action_snapshot") or {}),
            resolved_by=_optional_str(payload.get("resolved_by")),
            resolved_at=_optional_str(payload.get("resolved_at")),
        )


@dataclass(slots=True)
class AgentInterrupt:
    interrupt_id: str
    kind: str
    status: str
    title: str
    prompt: str
    created_at: str
    active_state_version: int | None = None
    resume_token: str | None = None
    related_action_id: str | None = None
    gate_id: str | None = None
    updated_at: str | None = None
    resolved_at: str | None = None
    resolution: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> AgentInterrupt | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            interrupt_id=str(payload.get("interrupt_id") or new_object_id("interrupt")),
            kind=str(payload.get("kind") or "clarification_request"),
            status=str(payload.get("status") or "pending"),
            title=str(payload.get("title") or ""),
            prompt=str(payload.get("prompt") or ""),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            active_state_version=_optional_int(payload.get("active_state_version")),
            resume_token=_optional_str(payload.get("resume_token")),
            related_action_id=_optional_str(payload.get("related_action_id")),
            gate_id=_optional_str(payload.get("gate_id")),
            updated_at=_optional_str(payload.get("updated_at")),
            resolved_at=_optional_str(payload.get("resolved_at")),
            resolution=_optional_str(payload.get("resolution")),
        )


@dataclass(slots=True)
class DecisionTraceEntry:
    entry_id: str
    kind: str
    summary: str
    created_at: str
    refs: list[str]
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["_meta"] = payload.pop("meta")
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> DecisionTraceEntry | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            entry_id=str(payload.get("entry_id") or new_object_id("trace")),
            kind=str(payload.get("kind") or "decision"),
            summary=str(payload.get("summary") or ""),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            refs=[str(item) for item in payload.get("refs") or []],
            meta=dict(payload.get("_meta") or {}),
        )


@dataclass(slots=True)
class AgentSession:
    session_id: str
    episode_id: str
    active_state_version: int
    pending_interrupt_ids: list[str]
    last_selected_action_id: str | None
    last_observation_ids: list[str]
    awaiting_feedback: bool
    resume_token: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None, *, episode_id: str) -> AgentSession:
        payload = payload or {}
        return cls(
            session_id=str(payload.get("session_id") or new_object_id("session")),
            episode_id=episode_id,
            active_state_version=int(payload.get("active_state_version") or 1),
            pending_interrupt_ids=[str(item) for item in payload.get("pending_interrupt_ids") or []],
            last_selected_action_id=_optional_str(payload.get("last_selected_action_id")),
            last_observation_ids=[str(item) for item in payload.get("last_observation_ids") or []],
            awaiting_feedback=bool(payload.get("awaiting_feedback")),
            resume_token=str(payload.get("resume_token") or new_object_id("resume")),
            updated_at=str(payload.get("updated_at") or utc_now_iso()),
        )


@dataclass(slots=True)
class AgentState:
    episode_id: str
    objective: str
    design_contract: DesignContract
    working_plan: dict[str, Any]
    candidate_actions: list[AgentAction]
    selected_action: AgentAction | None
    observations: list[AgentObservation]
    human_feedback: list[HumanFeedback]
    approval_gates: list[ApprovalGate]
    pending_interrupts: list[AgentInterrupt]
    decision_trace: list[DecisionTraceEntry]
    session: AgentSession
    status: str
    termination_status: str
    state_version: int
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "objective": self.objective,
            "design_contract": self.design_contract.to_dict(),
            "working_plan": self.working_plan,
            "candidate_actions": [item.to_dict() for item in self.candidate_actions],
            "selected_action": self.selected_action.to_dict() if self.selected_action else None,
            "observations": [item.to_dict() for item in self.observations],
            "human_feedback": [item.to_dict() for item in self.human_feedback],
            "approval_gates": [item.to_dict() for item in self.approval_gates],
            "pending_interrupts": [item.to_dict() for item in self.pending_interrupts],
            "decision_trace": [item.to_dict() for item in self.decision_trace],
            "session": self.session.to_dict(),
            "status": self.status,
            "termination_status": self.termination_status,
            "state_version": self.state_version,
            "_meta": self.meta,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None, *, episode_id: str, objective: str) -> AgentState:
        payload = payload or {}
        return cls(
            episode_id=episode_id,
            objective=str(payload.get("objective") or objective),
            design_contract=DesignContract.from_dict(payload.get("design_contract")),
            working_plan=dict(payload.get("working_plan") or {}),
            candidate_actions=_load_items(payload.get("candidate_actions"), AgentAction.from_dict),
            selected_action=AgentAction.from_dict(payload.get("selected_action")),
            observations=_load_items(payload.get("observations"), AgentObservation.from_dict),
            human_feedback=_load_items(payload.get("human_feedback"), HumanFeedback.from_dict),
            approval_gates=_load_items(payload.get("approval_gates"), ApprovalGate.from_dict),
            pending_interrupts=_load_items(payload.get("pending_interrupts"), AgentInterrupt.from_dict),
            decision_trace=_load_items(payload.get("decision_trace"), DecisionTraceEntry.from_dict),
            session=AgentSession.from_dict(payload.get("session"), episode_id=episode_id),
            status=str(payload.get("status") or "idle"),
            termination_status=str(payload.get("termination_status") or "active"),
            state_version=int(payload.get("state_version") or 1),
            meta=dict(payload.get("_meta") or {}),
        )


def _load_items(values: Any, factory) -> list[Any]:
    if not isinstance(values, list):
        return []
    items: list[Any] = []
    for value in values:
        item = factory(value)
        if item is not None:
            items.append(item)
    return items


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    return rendered or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
