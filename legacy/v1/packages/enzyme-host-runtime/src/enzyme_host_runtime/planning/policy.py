from __future__ import annotations

from dataclasses import dataclass

from mcp_project_memory.models import utc_now_iso

from ..workspace import TrustPolicyConfig
from ..workspace import TrustPolicyRuleConfig
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
    decision: str
    risk_level: str
    policy_reason: str
    plain_language_reason: str
    trust_decision: str
    required_feedback_type: str
    rule_id: str | None = None
    policy_scope: str = "default"


class ApprovalPolicy:
    def __init__(self, config: TrustPolicyConfig | None = None) -> None:
        self.config = config or TrustPolicyConfig()

    def evaluate(self, action: AgentAction) -> GatePolicyDecision | None:
        tool_action = action.tool_action
        if tool_action is None:
            return None
        matched = self._match_rule(tool_action.tool)
        if matched is not None:
            return matched
        if tool_action.tool in _HIGH_RISK_TOOLS:
            return GatePolicyDecision(
                decision="approval",
                risk_level="high",
                policy_reason="HPC and cost-amplifying actions require explicit approval.",
                plain_language_reason="这是高成本或远程计算动作，执行前需要你确认。",
                trust_decision="approval_required",
                required_feedback_type="approval",
                rule_id=f"builtin:{tool_action.tool}",
                policy_scope="builtin",
            )
        normalized = _normalize_action(self.config.default_decision)
        return GatePolicyDecision(
            decision=normalized,
            risk_level=tool_action.risk_level,
            policy_reason=self.config.default_policy_reason,
            plain_language_reason=self.config.default_plain_language_reason,
            trust_decision=self.config.default_trust_decision or _trust_decision_for(normalized),
            required_feedback_type="approval",
            rule_id=None,
            policy_scope="default",
        )

    def build_gate(self, action: AgentAction, decision: GatePolicyDecision) -> ApprovalGate:
        return ApprovalGate(
            gate_id=new_object_id("gate"),
            action_id=action.action_id,
            action_revision=action.action_revision,
            action_type=action.kind,
            risk_level=decision.risk_level,
            policy_reason=decision.policy_reason,
            plain_language_reason=decision.plain_language_reason,
            trust_decision=decision.trust_decision,
            required_feedback_type=decision.required_feedback_type,
            status="pending",
            created_at=utc_now_iso(),
            action_snapshot=action.to_dict(),
            policy_rule_id=decision.rule_id,
            policy_scope=decision.policy_scope,
        )

    def _match_rule(self, tool_name: str) -> GatePolicyDecision | None:
        for rule in self.config.rules:
            if not _rule_matches(rule, tool_name):
                continue
            normalized = _normalize_action(rule.decision)
            return GatePolicyDecision(
                decision=normalized,
                risk_level=rule.risk_level,
                policy_reason=rule.policy_reason or _fallback_policy_reason(rule),
                plain_language_reason=rule.plain_language_reason or _fallback_plain_language_reason(rule),
                trust_decision=rule.trust_decision or _trust_decision_for(normalized),
                required_feedback_type="approval",
                rule_id=rule.rule_id or f"project:{tool_name}",
                policy_scope="project",
            )
        return None


def _rule_matches(rule: TrustPolicyRuleConfig, tool_name: str) -> bool:
    return rule.tool == "*" or rule.tool == tool_name


def _fallback_policy_reason(rule: TrustPolicyRuleConfig) -> str:
    normalized = _normalize_action(rule.decision)
    if normalized == "block":
        return f"Project trust policy blocks `{rule.tool}` in the current workspace."
    if normalized == "approval":
        return f"Project trust policy requires approval before `{rule.tool}` can run."
    return f"Project trust policy allows `{rule.tool}` to continue without approval."


def _fallback_plain_language_reason(rule: TrustPolicyRuleConfig) -> str:
    normalized = _normalize_action(rule.decision)
    if normalized == "block":
        return "当前项目策略不允许系统直接执行这个动作。"
    if normalized == "approval":
        return "这个动作命中了项目审批规则，继续前需要你确认。"
    return "这个动作命中了项目自动放行规则，系统可以直接继续。"


def _trust_decision_for(decision: str) -> str:
    if decision == "block":
        return "blocked"
    if decision == "approval":
        return "approval_required"
    return "auto_allowed"


def _normalize_action(action: str) -> str:
    if action in {"approval_required", "approval"}:
        return "approval"
    if action in {"blocked", "block"}:
        return "block"
    return "allow"
