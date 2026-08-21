from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
import json
from time import monotonic
from typing import Callable

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureObservation
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import RetryEligibility
from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_runtime_spi import RuntimeCapabilityGateway
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeToolRequest
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome
from openzyme_runtime_spi import RuntimeUsage

from .configuration import LlmAdapterConfiguration
from .provider import LLM_PROVIDER_BACKEND_CONTRACT_DIGEST
from .provider import LlmProviderBackend
from .provider import LlmProviderError
from .provider import ProviderTurnRequest


LLM_RUNTIME_ADAPTER_ID = "openzyme.runtime.llm"
LLM_RUNTIME_ADAPTER_CONTRACT = "openzyme.agent-runtime-adapter@1"
LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": LLM_RUNTIME_ADAPTER_CONTRACT,
        "command": "runtime_turn_command@1",
        "outcome": "runtime_turn_outcome@1",
        "provider_backend_contract_digest": LLM_PROVIDER_BACKEND_CONTRACT_DIGEST,
        "prompt_owner": LLM_RUNTIME_ADAPTER_ID,
        "bounded_steps": True,
        "silent_provider_switch": False,
        "task_transition_inference": False,
    }
)
LLM_ADAPTER_PREFLIGHT_CONTRACT = "openzyme.llm-adapter-preflight@1"
LLM_ADAPTER_PREFLIGHT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": LLM_ADAPTER_PREFLIGHT_CONTRACT,
        "fields": [
            "adapter_id",
            "adapter_contract_digest",
            "provider_id",
            "provider_backend_identity_digest",
            "configuration_digest",
            "ready",
            "network_probe_performed",
        ],
        "network_probe_performed": False,
    }
)


@dataclass(frozen=True, slots=True)
class LlmAdapterPreflight:
    adapter_id: str
    adapter_contract_digest: str
    provider_id: str
    provider_backend_identity_digest: str
    configuration_digest: str
    ready: bool
    network_probe_performed: bool = False

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "adapter_id": self.adapter_id,
                "adapter_contract_digest": self.adapter_contract_digest,
                "provider_id": self.provider_id,
                "provider_backend_identity_digest": self.provider_backend_identity_digest,
                "configuration_digest": self.configuration_digest,
                "ready": self.ready,
                "network_probe_performed": self.network_probe_performed,
            }
        )


@dataclass(slots=True)
class LlmRuntimeAdapter:
    configuration: LlmAdapterConfiguration
    provider: LlmProviderBackend
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    clock: Callable[[], float] = monotonic
    adapter_id: str = LLM_RUNTIME_ADAPTER_ID
    adapter_contract_digest: str = LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST

    def __post_init__(self) -> None:
        if self.provider.provider_id != self.configuration.provider_id:
            raise ValueError("selected provider backend does not match configuration")

    def preflight(self) -> LlmAdapterPreflight:
        provider_preflight = getattr(self.provider, "preflight", None)
        if callable(provider_preflight):
            provider_preflight()
        return LlmAdapterPreflight(
            adapter_id=self.adapter_id,
            adapter_contract_digest=self.adapter_contract_digest,
            provider_id=self.provider.provider_id,
            provider_backend_identity_digest=self.provider.backend_identity_digest,
            configuration_digest=self.configuration.configuration_digest,
            ready=True,
            network_probe_performed=False,
        )

    def run_turn(
        self,
        command: RuntimeTurnCommand,
        capability_gateway: RuntimeCapabilityGateway,
    ) -> RuntimeTurnOutcome:
        if command.runtime_adapter_id != self.adapter_id or (
            command.runtime_adapter_contract_digest != self.adapter_contract_digest
        ):
            raise ValueError("runtime command targets another Adapter identity")
        tools = capability_gateway.list_tools(
            command_id=command.command_id,
            affordance_snapshot_digest=command.affordance_snapshot_digest,
        )
        messages = _compose_bounded_context(command)
        started = self.clock()
        input_units = 0
        output_units = 0
        provider_reported = True
        emitted_messages: list[RuntimeMessage] = []
        emitted_requests: list[RuntimeToolRequest] = []

        for step in range(1, command.max_steps + 1):
            if self.clock() - started >= command.max_duration_seconds:
                return self._outcome(
                    command,
                    disposition=RuntimeTurnDisposition.STEP_LIMIT_REACHED,
                    summary="Bounded LLM turn reached its duration limit.",
                    messages=emitted_messages,
                    tool_requests=emitted_requests,
                    input_units=input_units,
                    output_units=output_units,
                    provider_reported=provider_reported,
                )
            try:
                response = self._invoke_provider(
                    command=command,
                    messages=tuple(messages),
                    tools=tools,
                    step=step,
                )
            except LlmProviderError as exc:
                return self._failed_outcome(command, exc)
            input_units += response.input_units
            output_units += response.output_units
            provider_reported = provider_reported and response.provider_reported_usage
            if input_units > command.max_input_units or output_units > command.max_output_units:
                return self._outcome(
                    command,
                    disposition=RuntimeTurnDisposition.STEP_LIMIT_REACHED,
                    summary="Provider usage exceeded the bounded turn budget.",
                    messages=emitted_messages,
                    tool_requests=emitted_requests,
                    input_units=input_units,
                    output_units=output_units,
                    provider_reported=provider_reported,
                )

            assistant_message = RuntimeMessage(
                message_id=_stable_id(command.command_id, "assistant", step),
                role=RuntimeMessageRole.ASSISTANT,
                content=response.content or "Model requested tool execution.",
            )
            emitted_messages.append(assistant_message)
            messages.append(_provider_message(assistant_message))
            if not response.tool_calls:
                return self._outcome(
                    command,
                    disposition=RuntimeTurnDisposition.IDLE,
                    summary="Bounded LLM turn completed without implicit Task transition.",
                    messages=emitted_messages,
                    tool_requests=emitted_requests,
                    input_units=input_units,
                    output_units=output_units,
                    provider_reported=provider_reported,
                )

            for call in response.tool_calls:
                invocation = ToolInvocation(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    session_id=command.session_id,
                    agent_member_id=command.agent_member_id,
                    task_id=command.task_id,
                    lane_id=command.lane_id,
                    affordance_snapshot_digest=command.affordance_snapshot_digest,
                )
                request = RuntimeToolRequest(
                    request_id=_stable_id(command.command_id, call.call_id, step),
                    invocation=invocation,
                    affordance_snapshot_digest=command.affordance_snapshot_digest,
                )
                emitted_requests.append(request)
                result = capability_gateway.invoke(
                    command_id=command.command_id,
                    request=request,
                )
                tool_message = RuntimeMessage(
                    message_id=_stable_id(command.command_id, "tool", call.call_id, step),
                    role=RuntimeMessageRole.TOOL,
                    content=json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True),
                    tool_call_id=call.call_id,
                )
                emitted_messages.append(tool_message)
                messages.append(_provider_message(tool_message))
                if result.terminates_turn:
                    return self._outcome(
                        command,
                        disposition=RuntimeTurnDisposition.IDLE,
                        summary="Tool requested bounded turn termination; Task truth was not inferred.",
                        messages=emitted_messages,
                        tool_requests=emitted_requests,
                        input_units=input_units,
                        output_units=output_units,
                        provider_reported=provider_reported,
                    )

        return self._outcome(
            command,
            disposition=RuntimeTurnDisposition.STEP_LIMIT_REACHED,
            summary="Bounded LLM turn reached its step limit without Task inference.",
            messages=emitted_messages,
            tool_requests=emitted_requests,
            input_units=input_units,
            output_units=output_units,
            provider_reported=provider_reported,
        )

    def _invoke_provider(
        self,
        *,
        command: RuntimeTurnCommand,
        messages: tuple[dict[str, object], ...],
        tools: tuple,
        step: int,
    ):
        attempts = self.configuration.max_retries + 1
        last_error: LlmProviderError | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self.provider.invoke(
                    ProviderTurnRequest(
                        provider_id=self.configuration.provider_id,
                        model=self.configuration.model,
                        messages=messages,
                        tools=tools,
                        max_output_units=min(
                            command.max_output_units,
                            self.configuration.default_output_units,
                        ),
                        timeout_seconds=min(
                            command.max_duration_seconds,
                            self.configuration.timeout_seconds,
                        ),
                        attempt=attempt,
                        metadata={
                            "command_id": command.command_id,
                            "turn_id": command.turn_id,
                            "step": str(step),
                            "provider_backend_identity_digest": (
                                self.provider.backend_identity_digest
                            ),
                        },
                    )
                )
            except LlmProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt == attempts:
                    raise
        assert last_error is not None
        raise last_error

    def _outcome(
        self,
        command: RuntimeTurnCommand,
        *,
        disposition: RuntimeTurnDisposition,
        summary: str,
        messages: list[RuntimeMessage],
        tool_requests: list[RuntimeToolRequest],
        input_units: int,
        output_units: int,
        provider_reported: bool,
    ) -> RuntimeTurnOutcome:
        return RuntimeTurnOutcome(
            outcome_id=_stable_id(command.command_id, "outcome"),
            command_id=command.command_id,
            command_digest=command.command_digest,
            turn_id=command.turn_id,
            session_id=command.session_id,
            agent_id=command.agent_id,
            agent_member_id=command.agent_member_id,
            signal_id=command.signal_id,
            signal_attempt=command.signal_attempt,
            runtime_lease_generation=command.runtime_lease_generation,
            runtime_fence=command.runtime_fence,
            process_epoch=command.process_epoch,
            disposition=disposition,
            summary=summary,
            messages=tuple(messages),
            tool_requests=tuple(tool_requests),
            usage=RuntimeUsage(
                input_units=input_units,
                output_units=output_units,
                total_units=input_units + output_units,
                provider_reported=provider_reported,
            ),
        )

    def _failed_outcome(
        self,
        command: RuntimeTurnCommand,
        error: LlmProviderError,
    ) -> RuntimeTurnOutcome:
        created_at = self.now().astimezone(UTC).isoformat()
        failure_id = _stable_id(command.command_id, "failure", error.code)
        diagnostic_id = _stable_id(command.command_id, "diagnostic", error.code)
        failure = FailureObservation(
            failure_id=failure_id,
            session_id=command.session_id,
            task_id=command.task_id,
            lane_id=command.lane_id,
            agent_id=command.agent_id,
            source_kind="agent_runtime_adapter",
            source_ref=command.command_id,
            source_version=command.command_digest,
            phase=error.phase,
            failure_class=FailureClass.PROVIDER,
            recoverability=(
                FailureRecoverability.RUNTIME_RETRY
                if error.retryable
                else FailureRecoverability.TERMINAL
            ),
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=(
                RetryEligibility.SAME_PHASE_SAFE
                if error.retryable
                else RetryEligibility.TERMINAL
            ),
            actor_kind=FailureActorKind.SYSTEM,
            error_code=error.code,
            safe_summary="The explicitly selected LLM provider failed.",
            facts={
                "provider_id": self.configuration.provider_id,
                "provider_backend_identity_digest": (
                    self.provider.backend_identity_digest
                ),
                "mutation_applied": False,
                "fallback_performed": False,
            },
            likely_causes=("The selected provider or its configuration is unavailable.",),
            evidence_refs=(),
            created_at=created_at,
            safe_hint="Inspect the private diagnostic and retry only when policy permits.",
            component=self.adapter_id,
            operation="run_turn",
            identities={
                "command_id": command.command_id,
                "provider_id": self.configuration.provider_id,
            },
            mutation_applied=False,
            fallback_performed=False,
            cause_chain=(
                {
                    "type": "LlmProviderError",
                    "code": error.code,
                    "message_digest": canonical_sha256_digest(
                        {"message": str(error)}
                    ),
                },
            ),
            diagnostic_id=diagnostic_id,
            next_action=("retry_selected_provider" if error.retryable else "inspect_diagnostic"),
        )
        return RuntimeTurnOutcome(
            outcome_id=_stable_id(command.command_id, "outcome", "failed"),
            command_id=command.command_id,
            command_digest=command.command_digest,
            turn_id=command.turn_id,
            session_id=command.session_id,
            agent_id=command.agent_id,
            agent_member_id=command.agent_member_id,
            signal_id=command.signal_id,
            signal_attempt=command.signal_attempt,
            runtime_lease_generation=command.runtime_lease_generation,
            runtime_fence=command.runtime_fence,
            process_epoch=command.process_epoch,
            disposition=RuntimeTurnDisposition.FAILED,
            summary="The selected LLM provider failed; no fallback was performed.",
            failure=failure,
        )


def _compose_bounded_context(command: RuntimeTurnCommand) -> list[dict[str, object]]:
    messages = [_provider_message(item) for item in command.messages]
    estimated = sum(max(1, len(str(item["content"])) // 4) for item in messages)
    if estimated <= command.max_input_units:
        return messages
    system = [item for item in messages if item["role"] == "system"]
    non_system = [item for item in messages if item["role"] != "system"]
    kept: list[dict[str, object]] = []
    budget = max(1, command.max_input_units - sum(len(str(item["content"])) // 4 for item in system))
    used = 0
    for item in reversed(non_system):
        units = max(1, len(str(item["content"])) // 4)
        if kept and used + units > budget:
            break
        kept.append(item)
        used += units
    return [
        *system,
        {
            "role": "system",
            "content": "Older turn context was deterministically compacted by the selected LLM Adapter.",
        },
        *reversed(kept),
    ]


def _provider_message(message: RuntimeMessage) -> dict[str, object]:
    value: dict[str, object] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_call_id is not None:
        value["tool_call_id"] = message.tool_call_id
    return value


def _stable_id(*parts: object) -> str:
    encoded = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "id_" + hashlib.sha256(encoded).hexdigest()[:28]


__all__ = [
    "LLM_ADAPTER_PREFLIGHT_CONTRACT",
    "LLM_ADAPTER_PREFLIGHT_CONTRACT_DIGEST",
    "LLM_RUNTIME_ADAPTER_CONTRACT",
    "LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST",
    "LLM_RUNTIME_ADAPTER_ID",
    "LlmAdapterPreflight",
    "LlmRuntimeAdapter",
]
