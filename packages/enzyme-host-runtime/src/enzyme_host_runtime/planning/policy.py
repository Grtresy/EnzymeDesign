from __future__ import annotations

from dataclasses import dataclass

from mcp_project_memory.models import utc_now_iso

from .models import AgentAction
from .models import ApprovalGate
from .models import new_object_id

_HIGH_RISK_TOOLS = {
    "fpocket",
    "hhblits",
    "chai_fold",
    "colabfold",
    "alphafold3",
    "tunnels",
    "vina",
}


@dataclass(slots=True)
class GatePolicyDecision:
    risk_level: str
    policy_reason: str
    required_feedback_type: str


class ApprovalPolicy:
    def evaluate(self, action: AgentAction) -> GatePolicyDecision | None:
        tool_action = action.tool_action
        if tool_action is None:
            return None
        if tool_action.tool in _HIGH_RISK_TOOLS:
            return GatePolicyDecision(
                risk_level="high",
                policy_reason="HPC and cost-amplifying actions require explicit approval.",
                required_feedback_type="approval",
            )
        return None

    def build_gate(self, action: AgentAction, decision: GatePolicyDecision) -> ApprovalGate:
        return ApprovalGate(
            gate_id=new_object_id("gate"),
            action_id=action.action_id,
            action_revision=action.action_revision,
            action_type=action.kind,
            risk_level=decision.risk_level,
            policy_reason=decision.policy_reason,
            required_feedback_type=decision.required_feedback_type,
            status="pending",
            created_at=utc_now_iso(),
            action_snapshot=action.to_dict(),
        )
