from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
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
from openzyme_contracts import PrivateDiagnosticRecord
from openzyme_contracts import RetryEligibility
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_contracts import parse_failure_observation
from openzyme_contracts import validate_failure_diagnostic_pair
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
from .provider import ProviderTurnResponse


LLM_RUNTIME_ADAPTER_ID = "openzyme.runtime.llm"
LLM_RUNTIME_ADAPTER_CONTRACT = "openzyme.agent-runtime-adapter@1"
LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": LLM_RUNTIME_ADAPTER_CONTRACT,
        "command": "runtime_turn_command@2",
        "outcome": "runtime_turn_outcome@1",
        "provider_backend_contract_digest": LLM_PROVIDER_BACKEND_CONTRACT_DIGEST,
        "prompt_owner": LLM_RUNTIME_ADAPTER_ID,
        "bounded_steps": True,
        "silent_provider_switch": False,
        "task_transition_inference": False,
        "structured_runtime_context": True,
        "provider_step_fence_revalidation": True,
        "provider_step_tool_relisting": True,
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


class _AdapterGuardError(RuntimeError):
    def __init__(self, code: str, phase: str, summary: str) -> None:
        self.code = code
        self.phase = phase
        self.retryable = False
        self.safe_summary = summary
        super().__init__(summary)


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
        try:
            messages = _compose_bounded_context(command)
        except _AdapterGuardError as exc:
            return self._failed_outcome(command, exc)
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
                self._revalidate_gateway(
                    command,
                    capability_gateway,
                    phase="provider_tool_list",
                )
                tools = capability_gateway.list_tools(
                    command_id=command.command_id,
                    affordance_snapshot_digest=command.affordance_snapshot_digest,
                )
            except _AdapterGuardError as exc:
                return self._failed_outcome(
                    command,
                    exc,
                    messages=emitted_messages,
                    tool_requests=emitted_requests,
                    input_units=input_units,
                    output_units=output_units,
                    provider_reported=provider_reported,
                )
            except Exception as exc:
                return self._failed_outcome(
                    command,
                    _guard_error(
                        exc,
                        phase="provider_tool_list",
                        default_code="runtime_tool_listing_failed",
                    ),
                    messages=emitted_messages,
                    tool_requests=emitted_requests,
                    input_units=input_units,
                    output_units=output_units,
                    provider_reported=provider_reported,
                )
            try:
                response = self._invoke_provider(
                    command=command,
                    capability_gateway=capability_gateway,
                    messages=tuple(messages),
                    tools=tools,
                    step=step,
                )
            except LlmProviderError as exc:
                return self._failed_outcome(
                    command,
                    exc,
                    messages=emitted_messages,
                    tool_requests=emitted_requests,
                    input_units=input_units,
                    output_units=output_units,
                    provider_reported=provider_reported,
                )
            except _AdapterGuardError as exc:
                return self._failed_outcome(
                    command,
                    exc,
                    messages=emitted_messages,
                    tool_requests=emitted_requests,
                    input_units=input_units,
                    output_units=output_units,
                    provider_reported=provider_reported,
                )
            input_units += response.input_units
            output_units += response.output_units
            provider_reported = provider_reported and response.provider_reported_usage
            if (
                input_units > command.max_input_units
                or output_units > command.max_output_units
            ):
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
                correlation_id=_command_correlation_id(command),
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
                try:
                    self._revalidate_gateway(
                        command,
                        capability_gateway,
                        phase="tool_dispatch",
                    )
                    result = capability_gateway.invoke(
                        command_id=command.command_id,
                        request=request,
                    )
                    tool_failure = self._tool_failure(command, result)
                except _AdapterGuardError as exc:
                    return self._failed_outcome(
                        command,
                        exc,
                        messages=emitted_messages,
                        tool_requests=emitted_requests,
                        input_units=input_units,
                        output_units=output_units,
                        provider_reported=provider_reported,
                    )
                except Exception as exc:
                    return self._failed_outcome(
                        command,
                        _guard_error(
                            exc,
                            phase="tool_dispatch",
                            default_code="runtime_tool_dispatch_failed",
                        ),
                        messages=emitted_messages,
                        tool_requests=emitted_requests,
                        input_units=input_units,
                        output_units=output_units,
                        provider_reported=provider_reported,
                    )
                tool_message = RuntimeMessage(
                    message_id=_stable_id(
                        command.command_id, "tool", call.call_id, step
                    ),
                    role=RuntimeMessageRole.TOOL,
                    content=json.dumps(
                        result.to_dict(), ensure_ascii=False, sort_keys=True
                    ),
                    correlation_id=_command_correlation_id(command),
                    tool_call_id=call.call_id,
                )
                emitted_messages.append(tool_message)
                messages.append(_provider_message(tool_message))
                if tool_failure is not None:
                    failure, private_diagnostic = tool_failure
                    return self._structured_tool_failed_outcome(
                        command,
                        failure=failure,
                        private_diagnostic=private_diagnostic,
                        messages=emitted_messages,
                        tool_requests=emitted_requests,
                        input_units=input_units,
                        output_units=output_units,
                        provider_reported=provider_reported,
                    )
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
        capability_gateway: RuntimeCapabilityGateway,
        messages: tuple[dict[str, object], ...],
        tools: tuple,
        step: int,
    ):
        attempts = self.configuration.max_retries + 1
        last_error: LlmProviderError | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._revalidate_gateway(
                    command,
                    capability_gateway,
                    phase="provider_invoke",
                )
                response = self.provider.invoke(
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
                            "workflow_authority_id": (command.workflow_authority_id),
                            "workflow_authority_epoch": str(
                                command.workflow_authority_epoch
                            ),
                            "tool_exposure_snapshot_id": (
                                command.tool_exposure_snapshot_id
                            ),
                            "provider_backend_identity_digest": (
                                self.provider.backend_identity_digest
                            ),
                        },
                    )
                )
                if not isinstance(response, ProviderTurnResponse):
                    raise TypeError(
                        "selected provider returned a non-ProviderTurnResponse value"
                    )
                return response
            except _AdapterGuardError:
                raise
            except LlmProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt == attempts:
                    raise
            except Exception as exc:
                raise _provider_error(exc) from exc
        assert last_error is not None
        raise last_error

    @staticmethod
    def _tool_failure(
        command: RuntimeTurnCommand,
        result: ToolResult,
    ) -> tuple[FailureObservation, PrivateDiagnosticRecord] | None:
        if not isinstance(result, ToolResult):
            raise TypeError("capability gateway returned a non-ToolResult value")
        if result.failure_observation is None:
            if result.private_diagnostic is not None:
                raise ValueError(
                    "ToolResult private diagnostic lacks a public failure observation"
                )
            return None
        parsed = parse_failure_observation(result.failure_observation)
        if not isinstance(parsed, FailureObservation):
            raise ValueError("legacy tool failure cannot enter a current runtime turn")
        if result.private_diagnostic is None:
            raise ValueError("structured tool failure lacks its private diagnostic")
        if result.ok or not result.terminates_turn:
            raise ValueError(
                "structured tool failure must fail and terminate the bounded turn"
            )
        failure = replace(
            parsed,
            private_diagnostic_digest=result.private_diagnostic.record_digest,
        )
        validate_failure_diagnostic_pair(failure, result.private_diagnostic)
        if (
            failure.session_id != command.session_id
            or failure.agent_id != command.agent_id
            or failure.task_id != command.task_id
            or failure.lane_id != command.lane_id
        ):
            raise ValueError("structured tool failure escaped the command identity")
        return failure, result.private_diagnostic

    @staticmethod
    def _revalidate_gateway(
        command: RuntimeTurnCommand,
        capability_gateway: RuntimeCapabilityGateway,
        *,
        phase: str,
    ) -> None:
        validator = getattr(capability_gateway, "revalidate_provider_step", None)
        if not callable(validator):
            raise _AdapterGuardError(
                "runtime_turn_fence_revalidator_missing",
                phase,
                "The capability gateway cannot revalidate the current turn fences.",
            )
        try:
            validator(
                command_id=command.command_id,
                workflow_authority_id=command.workflow_authority_id,
                workflow_authority_epoch=command.workflow_authority_epoch,
                workflow_authority_digest=command.workflow_authority_digest,
                tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
                tool_exposure_snapshot_digest=(command.tool_exposure_snapshot_digest),
            )
        except Exception as exc:
            raise _guard_error(
                exc,
                phase=phase,
                default_code="runtime_turn_fence_stale",
            ) from exc

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
            workflow_authority_id=command.workflow_authority_id,
            workflow_authority_epoch=command.workflow_authority_epoch,
            workflow_authority_digest=command.workflow_authority_digest,
            tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
            tool_exposure_snapshot_digest=command.tool_exposure_snapshot_digest,
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
            task_id=command.task_id,
            lane_id=command.lane_id,
            correlation_id=_command_correlation_id(command),
        )

    def _failed_outcome(
        self,
        command: RuntimeTurnCommand,
        error: LlmProviderError | _AdapterGuardError,
        *,
        messages: list[RuntimeMessage] | None = None,
        tool_requests: list[RuntimeToolRequest] | None = None,
        input_units: int = 0,
        output_units: int = 0,
        provider_reported: bool = False,
    ) -> RuntimeTurnOutcome:
        emitted_messages = [] if messages is None else messages
        emitted_requests = [] if tool_requests is None else tool_requests
        provider_failure = isinstance(error, LlmProviderError)
        created_at = self.now().astimezone(UTC).isoformat()
        failure_id = _stable_id(command.command_id, "failure", error.code)
        diagnostic_id = _stable_id(command.command_id, "diagnostic", error.code)
        records = observe_structured_failure(
            error,
            context=StructuredFailureContext(
                failure_id=failure_id,
                diagnostic_id=diagnostic_id,
                session_id=command.session_id,
                component=self.adapter_id,
                operation="run_turn",
                phase=error.phase,
                source_kind="agent_runtime_adapter",
                source_ref=command.command_id,
                source_version=command.command_digest,
                created_at=created_at,
                task_id=command.task_id,
                lane_id=command.lane_id,
                agent_id=command.agent_id,
                correlation_id=_command_correlation_id(command),
            ),
            failure_class=(
                FailureClass.PROVIDER if provider_failure else FailureClass.RUNTIME
            ),
            recoverability=(
                FailureRecoverability.RUNTIME_RETRY
                if provider_failure and error.retryable
                else FailureRecoverability.TERMINAL
            ),
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=(
                RetryEligibility.SAME_PHASE_SAFE
                if provider_failure and error.retryable
                else RetryEligibility.TERMINAL
            ),
            actor_kind=FailureActorKind.SYSTEM,
            error_code=error.code,
            safe_summary=(
                "The explicitly selected LLM provider failed."
                if provider_failure
                else error.safe_summary
            ),
            public_facts={
                "provider_id": self.configuration.provider_id,
                "provider_backend_identity_digest": (
                    self.provider.backend_identity_digest
                ),
                "workflow_authority_id": command.workflow_authority_id,
                "workflow_authority_epoch": command.workflow_authority_epoch,
                "tool_exposure_snapshot_id": command.tool_exposure_snapshot_id,
                "prior_output_message_count": len(emitted_messages),
                "prior_tool_request_count": len(emitted_requests),
            },
            likely_causes=(
                ("The selected provider or its configuration is unavailable.",)
                if provider_failure
                else ("A current runtime fence or bounded context contract changed.",)
            ),
            evidence_refs=(),
            safe_hint="Inspect the private diagnostic and retry only when policy permits.",
            identities={
                "command_id": command.command_id,
                "provider_id": self.configuration.provider_id,
            },
            mutation_applied=False,
            fallback_performed=False,
            reconcile_required=False,
            next_action=(
                "retry_selected_provider"
                if provider_failure and error.retryable
                else "inspect_diagnostic"
            ),
            private_context={
                "command_id": command.command_id,
                "turn_id": command.turn_id,
                "provider_id": self.configuration.provider_id,
                "provider_backend_identity_digest": (
                    self.provider.backend_identity_digest
                ),
                "configuration_digest": self.configuration.configuration_digest,
                "prior_output_message_count": len(emitted_messages),
                "prior_tool_request_count": len(emitted_requests),
            },
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
            workflow_authority_id=command.workflow_authority_id,
            workflow_authority_epoch=command.workflow_authority_epoch,
            workflow_authority_digest=command.workflow_authority_digest,
            tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
            tool_exposure_snapshot_digest=command.tool_exposure_snapshot_digest,
            disposition=RuntimeTurnDisposition.FAILED,
            summary=(
                "The selected LLM provider failed; no fallback was performed."
                if provider_failure
                else "The bounded runtime turn failed before unsafe continuation."
            ),
            messages=tuple(emitted_messages),
            tool_requests=tuple(emitted_requests),
            usage=RuntimeUsage(
                input_units=input_units,
                output_units=output_units,
                total_units=input_units + output_units,
                provider_reported=provider_reported,
            ),
            failure=records.public,
            task_id=command.task_id,
            lane_id=command.lane_id,
            correlation_id=_command_correlation_id(command),
            private_diagnostic=records.private,
        )

    def _structured_tool_failed_outcome(
        self,
        command: RuntimeTurnCommand,
        *,
        failure: FailureObservation,
        private_diagnostic: PrivateDiagnosticRecord,
        messages: list[RuntimeMessage],
        tool_requests: list[RuntimeToolRequest],
        input_units: int,
        output_units: int,
        provider_reported: bool,
    ) -> RuntimeTurnOutcome:
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
            workflow_authority_id=command.workflow_authority_id,
            workflow_authority_epoch=command.workflow_authority_epoch,
            workflow_authority_digest=command.workflow_authority_digest,
            tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
            tool_exposure_snapshot_digest=command.tool_exposure_snapshot_digest,
            disposition=RuntimeTurnDisposition.FAILED,
            summary=(
                "A mounted tool failed with uncertain dispatch; no fallback or "
                "additional provider step was performed."
            ),
            messages=tuple(messages),
            tool_requests=tuple(tool_requests),
            usage=RuntimeUsage(
                input_units=input_units,
                output_units=output_units,
                total_units=input_units + output_units,
                provider_reported=provider_reported,
            ),
            failure=failure,
            task_id=command.task_id,
            lane_id=command.lane_id,
            correlation_id=_command_correlation_id(command),
            private_diagnostic=private_diagnostic,
        )


def _compose_bounded_context(command: RuntimeTurnCommand) -> list[dict[str, object]]:
    canonical_context = {
        "schema_version": "openzyme_runtime_prompt_context@1",
        "precedence": (
            "canonical_runtime_facts_override_conflicting_conversation_or_memory"
        ),
        "task_terminal_transition_rule": (
            "only_explicit_task_finish_or_documented_mechanical_migration"
        ),
        "fallback_performed": False,
        "runtime_turn_context": command.context.to_dict(),
    }
    constraint_message: dict[str, object] = {
        "role": "system",
        "content": json.dumps(
            canonical_context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    constraint_units = _estimated_message_units(constraint_message)
    if constraint_units > command.max_input_units:
        raise _AdapterGuardError(
            "runtime_context_budget_exceeded",
            "context_compose",
            "Current canonical runtime constraints exceed the provider input budget.",
        )
    conversation = [_provider_message(item) for item in command.messages]
    conversation_units = sum(_estimated_message_units(item) for item in conversation)
    if constraint_units + conversation_units <= command.max_input_units:
        return [constraint_message, *conversation]

    marker: dict[str, object] = {
        "role": "system",
        "content": json.dumps(
            {
                "schema_version": "openzyme_transcript_compaction@1",
                "reason": "provider_input_budget",
                "historical_only": True,
                "canonical_context_preserved": True,
                "fallback_performed": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    fixed_units = constraint_units + _estimated_message_units(marker)
    if fixed_units > command.max_input_units:
        raise _AdapterGuardError(
            "runtime_context_budget_exceeded",
            "context_compose",
            "Current canonical runtime constraints leave no safe compaction envelope.",
        )
    available = command.max_input_units - fixed_units
    kept_reversed: list[dict[str, object]] = []
    used = 0
    for item in reversed(conversation):
        units = _estimated_message_units(item)
        if used + units > available:
            break
        kept_reversed.append(item)
        used += units
    return [constraint_message, marker, *reversed(kept_reversed)]


def _provider_message(message: RuntimeMessage) -> dict[str, object]:
    value: dict[str, object] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_call_id is not None:
        value["tool_call_id"] = message.tool_call_id
    return value


def _estimated_message_units(message: dict[str, object]) -> int:
    encoded = json.dumps(
        message,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return max(1, (len(encoded) + 3) // 4)


def _guard_error(
    error: Exception,
    *,
    phase: str,
    default_code: str,
) -> _AdapterGuardError:
    code = getattr(error, "code", default_code)
    if not isinstance(code, str) or not code:
        code = default_code
    guarded = _AdapterGuardError(
        code,
        phase,
        "A current runtime fence or capability contract rejected the turn step.",
    )
    guarded.__cause__ = error
    return guarded


def _provider_error(error: Exception) -> LlmProviderError:
    guarded = LlmProviderError(
        "llm_provider_call_failed",
        "The selected LLM provider failed without a typed provider receipt.",
        retryable=False,
    )
    guarded.__cause__ = error
    return guarded


def _command_correlation_id(command: RuntimeTurnCommand) -> str | None:
    return next(
        (
            message.correlation_id
            for message in reversed(command.messages)
            if message.correlation_id is not None
        ),
        None,
    )


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
