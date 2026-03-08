from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from mcp_project_memory.models import utc_now_iso

from ..agent_backend import LLMSidecarClient
from ..agent_backend import LLMSidecarConfig
from ..agent_backend import SidecarInvocationError
from .adapters import AgentBackendBlockedError
from .adapters import HeuristicAgentAdapter
from .models import AgentAction
from .models import AgentInterrupt
from .models import AgentObservation
from .models import AgentState
from .models import DesignContract
from .models import ToolAction


@dataclass(slots=True)
class LLMAgentAdapter:
    client: LLMSidecarClient
    config: LLMSidecarConfig
    fallback_adapter: HeuristicAgentAdapter = field(default_factory=HeuristicAgentAdapter)
    adapter_name: str = "llm-agent-adapter"
    _backend_status: dict[str, Any] = field(default_factory=dict, init=False)

    def derive_design_contract(self, *, episode_id: str, goal: str, current_state: AgentState) -> DesignContract:
        return self._invoke(
            "derive_design_contract",
            context={
                "episode_id": episode_id,
                "goal": goal,
                "state": current_state.to_dict(),
            },
            mapper=self._map_design_contract,
            fallback=lambda: self.fallback_adapter.derive_design_contract(
                episode_id=episode_id,
                goal=goal,
                current_state=current_state,
            ),
        )

    def build_working_plan(self, *, state: AgentState, candidates: list[AgentAction]) -> dict[str, object]:
        return self._invoke(
            "build_working_plan",
            context={
                "state": state.to_dict(),
                "candidates": [item.to_dict() for item in candidates],
            },
            mapper=self._map_working_plan,
            fallback=lambda: self.fallback_adapter.build_working_plan(state=state, candidates=candidates),
        )

    def propose_candidate_actions(self, *, state: AgentState) -> list[AgentAction]:
        return self._invoke(
            "propose_candidate_actions",
            context={
                "state": state.to_dict(),
                "observation": state.observations[-1].to_dict() if state.observations else None,
            },
            mapper=self._map_candidate_actions,
            fallback=lambda: self.fallback_adapter.propose_candidate_actions(state=state),
        )

    def select_action(self, *, state: AgentState, candidates: list[AgentAction]) -> AgentAction:
        return self._invoke(
            "select_action",
            context={
                "state": state.to_dict(),
                "candidates": [item.to_dict() for item in candidates],
            },
            mapper=lambda payload, status: self._require_selected_candidate(
                self._map_action(payload, status),
                candidates,
            ),
            fallback=lambda: self.fallback_adapter.select_action(state=state, candidates=candidates),
        )

    def build_clarification_interrupt(self, *, state: AgentState, reason: str) -> AgentInterrupt:
        return self._invoke(
            "build_clarification_interrupt",
            context={
                "state": state.to_dict(),
                "reason": reason,
            },
            mapper=self._map_interrupt,
            fallback=lambda: self.fallback_adapter.build_clarification_interrupt(state=state, reason=reason),
        )

    def summarize_observation(self, *, state: AgentState, observation: AgentObservation) -> str:
        return self._invoke(
            "summarize_observation",
            context={
                "state": state.to_dict(),
                "observation": observation.to_dict(),
            },
            mapper=self._map_summary,
            fallback=lambda: self.fallback_adapter.summarize_observation(state=state, observation=observation),
        )

    def current_backend_status(self) -> dict[str, Any]:
        if self._backend_status:
            return dict(self._backend_status)
        return self._build_backend_status()

    def _invoke(self, operation: str, *, context: dict[str, Any], mapper, fallback):
        try:
            response = self.client.request(
                operation=operation,
                context=context,
                backend={
                    "name": "llm-sidecar",
                    "provider": self.config.provider,
                    "model": self.config.model,
                },
            )
            status = self._build_backend_status(response.provenance)
            self._backend_status = status
            return mapper(response.result, status)
        except (SidecarInvocationError, ValueError, TypeError) as exc:
            status = self._build_backend_status(
                getattr(exc, "provenance", None),
                degraded=self.config.allow_fallback,
                fallback_used=self.config.allow_fallback,
                last_error_summary=str(exc),
            )
            self._backend_status = status
            if not self.config.allow_fallback:
                raise AgentBackendBlockedError(
                    str(exc),
                    operation=operation,
                    backend_status=status,
                ) from exc
            return self._apply_meta(fallback(), status, operation)

    def _build_backend_status(
        self,
        provenance: dict[str, Any] | None = None,
        *,
        degraded: bool = False,
        fallback_used: bool = False,
        last_error_summary: str | None = None,
    ) -> dict[str, Any]:
        provenance = dict(provenance or {})
        return {
            "adapter": self.adapter_name,
            "backend": "llm-sidecar",
            "provider": str(provenance.get("provider") or self.config.provider),
            "model": str(provenance.get("model") or self.config.model),
            "sidecar": dict(provenance.get("sidecar") or {}),
            "degraded": degraded,
            "fallback_used": fallback_used,
            "fallback_backend": "heuristic" if fallback_used else None,
            "last_error_summary": last_error_summary,
        }

    def _map_design_contract(self, payload: Any, status: dict[str, Any]) -> DesignContract:
        data = self._require_mapping(payload, "Design contract payload must be a mapping.")
        contract = DesignContract(
            summary=self._require_non_empty_str(data.get("summary"), "Design contract summary is required."),
            goals=self._require_str_list(data.get("goals"), "Design contract goals must be a list."),
            constraints=self._require_str_list(data.get("constraints"), "Design contract constraints must be a list."),
            assumptions=self._require_str_list(data.get("assumptions"), "Design contract assumptions must be a list."),
            open_questions=self._require_str_list(
                data.get("open_questions"),
                "Design contract open_questions must be a list.",
            ),
            meta={},
        )
        return self._apply_meta(contract, status, "derive_design_contract")

    def _map_working_plan(self, payload: Any, status: dict[str, Any]) -> dict[str, object]:
        data = self._require_mapping(payload, "Working plan payload must be a mapping.")
        candidate_actions = self._require_str_list(
            data.get("candidate_actions"),
            "Working plan candidate_actions must be a list.",
        )
        steps_payload = data.get("steps")
        if not isinstance(steps_payload, list):
            raise ValueError("Working plan steps must be a list.")
        steps: list[dict[str, Any]] = []
        for item in steps_payload:
            step = self._require_mapping(item, "Working plan step must be a mapping.")
            normalized: dict[str, Any] = {
                "id": self._require_non_empty_str(step.get("id"), "Working plan step id is required."),
                "title": self._require_non_empty_str(step.get("title"), "Working plan step title is required."),
            }
            if step.get("tool") is not None:
                normalized["tool"] = self._require_non_empty_str(step.get("tool"), "Working plan step tool is invalid.")
            if step.get("inputs") is not None:
                normalized["inputs"] = self._require_mapping(step.get("inputs"), "Working plan step inputs must be a mapping.")
            steps.append(normalized)
        plan = {
            "summary": self._require_non_empty_str(data.get("summary"), "Working plan summary is required."),
            "candidate_actions": candidate_actions,
            "steps": steps,
        }
        return self._apply_meta(plan, status, "build_working_plan")

    def _map_candidate_actions(self, payload: Any, status: dict[str, Any]) -> list[AgentAction]:
        if not isinstance(payload, list):
            raise ValueError("Candidate actions payload must be a list.")
        return [self._apply_meta(self._map_action(item, status), status, "propose_candidate_actions") for item in payload]

    def _map_action(self, payload: Any, status: dict[str, Any]) -> AgentAction:
        data = self._require_mapping(payload, "Action payload must be a mapping.")
        kind = self._require_non_empty_str(data.get("kind"), "Action kind is required.")
        tool_action_payload = data.get("tool_action")
        tool_action = None
        if tool_action_payload is not None:
            tool_mapping = self._require_mapping(tool_action_payload, "tool_action must be a mapping.")
            tool_action = ToolAction(
                tool=self._require_non_empty_str(tool_mapping.get("tool"), "Tool name is required."),
                inputs=self._require_mapping(tool_mapping.get("inputs"), "Tool inputs must be a mapping."),
                risk_level=str(tool_mapping.get("risk_level") or "normal"),
            )
        if kind == "tool" and tool_action is None:
            raise ValueError("Tool actions must include tool_action.")
        action = AgentAction(
            action_id=self._require_non_empty_str(data.get("action_id"), "Action id is required."),
            action_revision=int(data.get("action_revision") or 1),
            kind=kind,
            title=self._require_non_empty_str(data.get("title"), "Action title is required."),
            rationale=self._require_non_empty_str(data.get("rationale"), "Action rationale is required."),
            tool_action=tool_action,
            gate_id=self._optional_str(data.get("gate_id")),
            meta={},
        )
        return self._apply_meta(action, status, "select_action")

    def _map_interrupt(self, payload: Any, status: dict[str, Any]) -> AgentInterrupt:
        data = self._require_mapping(payload, "Interrupt payload must be a mapping.")
        return AgentInterrupt(
            interrupt_id=self._require_non_empty_str(data.get("interrupt_id"), "Interrupt id is required."),
            kind=self._require_non_empty_str(data.get("kind"), "Interrupt kind is required."),
            status=self._require_non_empty_str(data.get("status"), "Interrupt status is required."),
            title=self._require_non_empty_str(data.get("title"), "Interrupt title is required."),
            prompt=self._require_non_empty_str(data.get("prompt"), "Interrupt prompt is required."),
            created_at=self._require_non_empty_str(data.get("created_at"), "Interrupt created_at is required."),
            related_action_id=self._optional_str(data.get("related_action_id")),
            gate_id=self._optional_str(data.get("gate_id")),
        )

    def _map_summary(self, payload: Any, status: dict[str, Any]) -> str:
        if isinstance(payload, str):
            summary = payload
        else:
            data = self._require_mapping(payload, "Summary payload must be a mapping.")
            summary = self._require_non_empty_str(data.get("summary"), "Observation summary is required.")
        self._backend_status = {
            **status,
            "last_summary_at": utc_now_iso(),
        }
        return summary

    def _apply_meta(self, value: Any, status: dict[str, Any], operation: str):
        meta = {
            **status,
            "operation": operation,
        }
        if isinstance(value, DesignContract):
            value.meta = meta
            return value
        if isinstance(value, AgentAction):
            value.meta = meta
            return value
        if isinstance(value, dict):
            value["_meta"] = meta
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, AgentAction):
                    item.meta = meta
            return value
        return value

    def _require_mapping(self, payload: Any, message: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError(message)
        return dict(payload)

    def _require_non_empty_str(self, value: Any, message: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(message)
        return value

    def _require_str_list(self, value: Any, message: str) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(message)
        rendered: list[str] = []
        for item in value:
            rendered.append(self._require_non_empty_str(item, message))
        return rendered

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        return self._require_non_empty_str(value, "Expected optional string.")

    def _require_selected_candidate(self, selected: AgentAction, candidates: list[AgentAction]) -> AgentAction:
        for candidate in candidates:
            if (
                candidate.action_id == selected.action_id
                and candidate.action_revision == selected.action_revision
            ):
                candidate.meta = {
                    **candidate.meta,
                    **selected.meta,
                    "operation": "select_action",
                }
                return candidate
        raise ValueError(
            "Selected action must match one of the proposed candidate actions."
        )
