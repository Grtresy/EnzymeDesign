from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_runtime_llm import LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST
from openzyme_runtime_llm import LLM_RUNTIME_ADAPTER_ID
from openzyme_runtime_llm import LlmAdapterConfiguration
from openzyme_runtime_llm import LlmProviderError
from openzyme_runtime_llm import LlmRuntimeAdapter
from openzyme_runtime_llm import ProviderToolCall
from openzyme_runtime_llm import ProviderTurnRequest
from openzyme_runtime_llm import ProviderTurnResponse
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeToolRequest
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_runtime_spi import RuntimeTurnDisposition


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _configuration(*, max_retries: int = 0) -> LlmAdapterConfiguration:
    return LlmAdapterConfiguration(
        provider_id="openai",
        model="model-1",
        base_url="https://provider.invalid/v1",
        credential_slot="llm-primary",
        timeout_seconds=30,
        max_retries=max_retries,
        context_window_units=16_000,
        default_output_units=2_000,
        provider_options={},
    )


def _command(
    *,
    max_steps: int = 3,
    max_input_units: int = 4_000,
) -> RuntimeTurnCommand:
    return RuntimeTurnCommand(
        command_id="command-1",
        turn_id="turn-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        signal_id="signal-1",
        signal_attempt=1,
        signal_claim_token="claim-1",
        runtime_lease_token="lease-1",
        runtime_lease_generation=1,
        runtime_fence=1,
        process_epoch=1,
        distribution_id="openzyme.standard",
        distribution_manifest_digest=_digest("distribution"),
        release_digest=_digest("release"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        capability_binding_id="binding-1",
        capability_binding_revision=1,
        capability_binding_digest=_digest("binding"),
        affordance_snapshot_id="snapshot-1",
        affordance_snapshot_digest=_digest("snapshot"),
        runtime_adapter_id=LLM_RUNTIME_ADAPTER_ID,
        runtime_adapter_contract_digest=LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST,
        max_steps=max_steps,
        max_duration_seconds=60,
        max_input_units=max_input_units,
        max_output_units=4_000,
        messages=(
            RuntimeMessage(
                message_id="message-1",
                role=RuntimeMessageRole.USER,
                content="Inspect canonical facts.",
            ),
        ),
        task_id="task-1",
        lane_id="lane-1",
    )


@dataclass
class FakeProvider:
    responses: list[ProviderTurnResponse | LlmProviderError]
    provider_id: str = "openai"
    backend_identity_digest: str = _digest("provider-backend")

    def __post_init__(self) -> None:
        self.requests: list[ProviderTurnRequest] = []

    def invoke(self, request: ProviderTurnRequest) -> ProviderTurnResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, LlmProviderError):
            raise response
        return response


class FakeGateway:
    def __init__(self) -> None:
        self.requests: list[RuntimeToolRequest] = []

    def list_tools(self, *, command_id: str, affordance_snapshot_digest: str):
        assert command_id == "command-1"
        assert affordance_snapshot_digest == _digest("snapshot")
        return (
            ToolSpec(
                tool_name="world.inspect",
                description="Inspect safe canonical facts.",
                input_schema={"type": "object", "additionalProperties": False},
            ),
        )

    def invoke(self, *, command_id: str, request: RuntimeToolRequest) -> ToolResult:
        assert command_id == "command-1"
        self.requests.append(request)
        return ToolResult(
            call_id=request.invocation.call_id,
            tool_name=request.invocation.tool_name,
            ok=True,
            status="succeeded",
            summary="facts inspected",
            payload={"task_status": "in_progress"},
        )


def test_adapter_uses_exact_provider_and_affordance_then_does_not_finish_task() -> None:
    provider = FakeProvider(
        responses=[
            ProviderTurnResponse(
                content="I will inspect.",
                tool_calls=(
                    ProviderToolCall(
                        call_id="call-1",
                        tool_name="world.inspect",
                        arguments={},
                    ),
                ),
                input_units=20,
                output_units=5,
                provider_reported_usage=True,
            ),
            ProviderTurnResponse(
                content="Inspection complete; the task remains in progress.",
                input_units=30,
                output_units=10,
                provider_reported_usage=True,
            ),
        ]
    )
    gateway = FakeGateway()
    adapter = LlmRuntimeAdapter(_configuration(), provider)

    outcome = adapter.run_turn(_command(), gateway)

    assert outcome.disposition is RuntimeTurnDisposition.IDLE
    assert outcome.usage is not None
    assert outcome.usage.total_units == 65
    assert len(provider.requests) == 2
    assert {request.provider_id for request in provider.requests} == {"openai"}
    assert len(gateway.requests) == 1
    assert gateway.requests[0].affordance_snapshot_digest == _digest("snapshot")
    assert gateway.requests[0].invocation.task_id == "task-1"
    assert "task_status" not in outcome.to_dict()


def test_provider_failure_is_structured_and_never_switches_provider() -> None:
    provider = FakeProvider(
        responses=[
            LlmProviderError(
                "llm_provider_call_failed",
                "secret provider failure",
                retryable=False,
            )
        ]
    )
    adapter = LlmRuntimeAdapter(_configuration(max_retries=4), provider)

    outcome = adapter.run_turn(_command(), FakeGateway())

    assert outcome.disposition is RuntimeTurnDisposition.FAILED
    assert outcome.failure is not None
    assert outcome.failure.error_code == "llm_provider_call_failed"
    assert outcome.failure.mutation_applied is False
    assert outcome.failure.fallback_performed is False
    assert outcome.failure.facts["provider_id"] == "openai"
    assert "secret provider failure" not in str(outcome.to_dict())
    assert len(provider.requests) == 1


def test_retry_policy_retries_only_the_same_selected_backend() -> None:
    provider = FakeProvider(
        responses=[
            LlmProviderError(
                "llm_provider_call_failed",
                "temporary failure",
                retryable=True,
            ),
            ProviderTurnResponse(content="Recovered.", input_units=1, output_units=1),
        ]
    )
    adapter = LlmRuntimeAdapter(_configuration(max_retries=1), provider)

    outcome = adapter.run_turn(_command(), FakeGateway())

    assert outcome.disposition is RuntimeTurnDisposition.IDLE
    assert [request.provider_id for request in provider.requests] == ["openai", "openai"]
    assert {
        request.metadata["provider_backend_identity_digest"]
        for request in provider.requests
    } == {_digest("provider-backend")}


def test_step_limit_is_a_runtime_outcome_not_a_task_transition() -> None:
    provider = FakeProvider(
        responses=[
            ProviderTurnResponse(
                content="Again.",
                tool_calls=(
                    ProviderToolCall(
                        call_id="call-1",
                        tool_name="world.inspect",
                        arguments={},
                    ),
                ),
            )
        ]
    )
    outcome = LlmRuntimeAdapter(_configuration(), provider).run_turn(
        _command(max_steps=1),
        FakeGateway(),
    )

    assert outcome.disposition is RuntimeTurnDisposition.STEP_LIMIT_REACHED
    assert "Task" in outcome.summary
    assert "task_status" not in outcome.to_dict()


def test_configuration_is_closed_and_credential_free() -> None:
    value = _configuration().safe_projection()
    parsed = LlmAdapterConfiguration.from_mapping(value)
    assert parsed.configuration_digest == _configuration().configuration_digest
    with pytest.raises(ValueError, match="closed"):
        LlmAdapterConfiguration.from_mapping({**value, "api_key": "secret"})
    with pytest.raises(ValueError, match="credential-free"):
        LlmAdapterConfiguration(
            **{
                **{
                    key: getattr(_configuration(), key)
                    for key in (
                        "provider_id",
                        "model",
                        "base_url",
                        "credential_slot",
                        "timeout_seconds",
                        "max_retries",
                        "context_window_units",
                        "default_output_units",
                    )
                },
                "provider_options": {"api_key": "secret"},
            }
        )
