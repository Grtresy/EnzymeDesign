from __future__ import annotations

from pathlib import Path

import pytest

from enzyme_host_runtime.agent_backend import LLMSidecarConfig
from enzyme_host_runtime.agent_backend import SidecarInvocationError
from enzyme_host_runtime.agent_backend import SidecarResponse
from enzyme_host_runtime.planning import AgentBackendBlockedError
from enzyme_host_runtime.planning import AgentObservation
from enzyme_host_runtime.planning import AgentState
from enzyme_host_runtime.planning import LLMAgentAdapter


class _FakeClient:
    def __init__(self, response: SidecarResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    def request(self, *, operation: str, context: dict[str, object], backend: dict[str, object]) -> SidecarResponse:
        del operation, context, backend
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _config(*, allow_fallback: bool) -> LLMSidecarConfig:
    return LLMSidecarConfig(
        provider="fake",
        model="fake-structured-agent",
        timeout_seconds=1.0,
        allow_fallback=allow_fallback,
        command=("node", "unused"),
        cwd=str(Path.cwd()),
        config_path=str(Path.cwd() / ".enzyme" / "agent_backend.json"),
    )


def test_llm_adapter_maps_sidecar_success_and_records_meta() -> None:
    adapter = LLMAgentAdapter(
        client=_FakeClient(
            response=SidecarResponse(
                request_id="req-1",
                operation="derive_design_contract",
                result={
                    "summary": "Improve binding",
                    "goals": ["Improve binding"],
                    "constraints": [],
                    "assumptions": ["Use the workspace as source of truth."],
                    "open_questions": [],
                },
                provenance={
                    "provider": "fake",
                    "model": "fake-structured-agent",
                    "sidecar": {"name": "pi-ai-sidecar", "version": "0.1.0"},
                },
            )
        ),
        config=_config(allow_fallback=True),
    )

    state = AgentState.from_dict({}, episode_id="0001", objective="Improve binding")
    contract = adapter.derive_design_contract(
        episode_id="0001",
        goal="Improve binding",
        current_state=state,
    )

    assert contract.summary == "Improve binding"
    assert contract.meta["backend"] == "llm-sidecar"
    assert contract.meta["provider"] == "fake"
    assert contract.meta["fallback_used"] is False


def test_llm_adapter_falls_back_on_structured_validation_failure() -> None:
    adapter = LLMAgentAdapter(
        client=_FakeClient(
            response=SidecarResponse(
                request_id="req-2",
                operation="propose_candidate_actions",
                result={"not": "a-list"},
                provenance={"provider": "fake", "model": "fake-structured-agent"},
            )
        ),
        config=_config(allow_fallback=True),
    )

    state = AgentState.from_dict({}, episode_id="0001", objective="Improve binding")
    candidates = adapter.propose_candidate_actions(state=state)

    assert candidates
    assert candidates[0].meta["fallback_used"] is True
    assert candidates[0].meta["degraded"] is True
    assert "must be a list" in str(candidates[0].meta["last_error_summary"])


def test_llm_adapter_raises_blocked_error_when_fallback_is_disabled() -> None:
    adapter = LLMAgentAdapter(
        client=_FakeClient(
            error=SidecarInvocationError(
                "Fake provider unavailable.",
                category="provider-unavailable",
                retryable=True,
                provenance={"provider": "fake", "model": "fake-structured-agent"},
            )
        ),
        config=_config(allow_fallback=False),
    )

    state = AgentState.from_dict({}, episode_id="0001", objective="Improve binding")
    observation = AgentObservation(
        observation_id="obs-1",
        source="tool",
        summary="tool failed",
        created_at=state.session.updated_at,
        payload={"status": "failed"},
    )

    with pytest.raises(AgentBackendBlockedError):
        adapter.summarize_observation(state=state, observation=observation)


def test_llm_adapter_rejects_selected_action_outside_candidate_list() -> None:
    adapter = LLMAgentAdapter(
        client=_FakeClient(
            response=SidecarResponse(
                request_id="req-3",
                operation="select_action",
                result={
                    "action_id": "rogue-action",
                    "kind": "tool",
                    "title": "Unplanned tool call",
                    "rationale": "Bypass the candidate list.",
                    "tool_action": {
                        "tool": "prepare_receptor",
                        "inputs": {"input": "data/inputs/rogue.pdb"},
                    },
                },
                provenance={"provider": "fake", "model": "fake-structured-agent"},
            )
        ),
        config=_config(allow_fallback=False),
    )

    state = AgentState.from_dict({}, episode_id="0001", objective="Improve binding")
    candidates = adapter.fallback_adapter.propose_candidate_actions(state=state)

    with pytest.raises(AgentBackendBlockedError) as exc_info:
        adapter.select_action(state=state, candidates=candidates)

    assert "must match one of the proposed candidate actions" in str(exc_info.value)
