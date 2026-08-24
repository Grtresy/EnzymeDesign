from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import json

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import RetryEligibility
from openzyme_contracts import RuntimeContextSection
from openzyme_contracts import RuntimeContextSectionKind
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_contracts import validate_failure_diagnostic_pair
from openzyme_runtime_llm import LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST
from openzyme_runtime_llm import LLM_RUNTIME_ADAPTER_ID
from openzyme_runtime_llm import LangChainProviderBackend
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


def test_openai_compatible_provider_uses_explicit_langchain_implementation_identity(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_init_chat_model(*, model, model_provider, **options):
        captured.update(
            model=model,
            model_provider=model_provider,
            options=options,
        )
        return sentinel

    monkeypatch.setattr(
        "langchain.chat_models.init_chat_model",
        fake_init_chat_model,
    )
    configuration = LlmAdapterConfiguration(
        provider_id="micuapi",
        model="gpt-5.5",
        base_url="https://www.micuapi.ai/v1",
        credential_slot="credential.llm.micuapi.qualification",
        timeout_seconds=60,
        max_retries=0,
        context_window_units=128_000,
        default_output_units=256,
        provider_options={"langchain_model_provider": "openai"},
    )

    backend = LangChainProviderBackend(configuration=configuration, api_key="secret")

    assert backend._model_instance() is sentinel
    assert captured["model_provider"] == "openai"
    assert captured["model"] == "gpt-5.5"
    assert "langchain_model_provider" not in captured["options"]


def _command(
    *,
    max_steps: int = 3,
    max_input_units: int = 4_000,
) -> RuntimeTurnCommand:
    context = RuntimeTurnContext(
        context_id="context-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        signal_id="signal-1",
        request_lineage_id="request-lineage-1",
        task_id="task-1",
        lane_id="lane-1",
        sections=tuple(
            RuntimeContextSection(kind=kind, items=())
            for kind in RuntimeContextSectionKind
        ),
        max_bytes=131_072,
        created_at="2026-08-24T00:00:00+00:00",
    )
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
        workflow_authority_id="workflow-authority-1",
        workflow_authority_epoch=3,
        workflow_authority_digest=_digest("workflow-authority"),
        signal_authority_link_digest=_digest("signal-authority-link"),
        tool_exposure_snapshot_id="exposure-1",
        tool_exposure_snapshot_digest=_digest("tool-exposure"),
        context=context,
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
                correlation_id="correlation-1",
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
    def __init__(self, *, fail_revalidation_at: int | None = None) -> None:
        self.requests: list[RuntimeToolRequest] = []
        self.list_calls = 0
        self.revalidations: list[dict[str, object]] = []
        self.fail_revalidation_at = fail_revalidation_at

    def revalidate_provider_step(self, **identities) -> None:
        self.revalidations.append(identities)
        if len(self.revalidations) == self.fail_revalidation_at:
            error = RuntimeError("private stale workflow detail")
            error.code = "workflow_authority_epoch_stale"  # type: ignore[attr-defined]
            raise error
        assert identities == {
            "command_id": "command-1",
            "workflow_authority_id": "workflow-authority-1",
            "workflow_authority_epoch": 3,
            "workflow_authority_digest": _digest("workflow-authority"),
            "tool_exposure_snapshot_id": "exposure-1",
            "tool_exposure_snapshot_digest": _digest("tool-exposure"),
        }

    def list_tools(self, *, command_id: str, affordance_snapshot_digest: str):
        self.list_calls += 1
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


class ResultGateway(FakeGateway):
    def __init__(self, result: ToolResult) -> None:
        super().__init__()
        self.result = result

    def invoke(self, *, command_id: str, request: RuntimeToolRequest) -> ToolResult:
        assert command_id == "command-1"
        self.requests.append(request)
        return self.result


def _structured_tool_failure(command: RuntimeTurnCommand) -> ToolResult:
    records = observe_structured_failure(
        RuntimeError("operator-only-tool-token=top-secret"),
        context=StructuredFailureContext(
            failure_id="failure-tool-1",
            diagnostic_id="diagnostic-tool-1",
            session_id=command.session_id,
            component="example.plugin",
            operation="invoke",
            phase="tool_dispatch",
            source_kind="mounted_tool_runtime",
            source_ref="call-1",
            source_version=_digest("world-inspect-runtime"),
            created_at="2026-08-24T00:00:01+00:00",
            task_id=command.task_id,
            lane_id=command.lane_id,
            agent_id=command.agent_id,
            correlation_id="correlation-1",
        ),
        failure_class=FailureClass.TOOL,
        recoverability=FailureRecoverability.RECONCILIATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        actor_kind=FailureActorKind.HARNESS,
        error_code="extension_tool_runtime_failed",
        safe_summary="The mounted tool failed after dispatch began.",
        safe_hint="Reconcile the exact dispatch.",
        next_action="reconcile_exact_tool_dispatch",
        mutation_applied=None,
        fallback_performed=False,
        reconcile_required=True,
        identities={"command_id": command.command_id, "call_id": "call-1"},
        private_context={"credential": "operator-only-tool-token=top-secret"},
    )
    return ToolResult(
        call_id="call-1",
        tool_name="world.inspect",
        ok=False,
        status="runtime_contract_failure",
        summary=records.public.safe_summary,
        payload={
            "effect_certainty": "dispatch_in_doubt",
            "mutation_applied": None,
            "fallback_performed": False,
            "retry_performed": False,
            "reconcile_required": True,
            "diagnostic_id": records.public.diagnostic_id,
        },
        error_code=records.public.error_code,
        hint=records.public.safe_hint,
        failure_observation=records.public.to_dict(),
        terminates_turn=True,
        private_diagnostic=records.private,
    )


def _compaction_command() -> tuple[RuntimeTurnCommand, dict[str, str]]:
    current_facts = {
        RuntimeContextSectionKind.SESSION: {
            "objective": "current-session-objective",
            "session_status": "active",
        },
        RuntimeContextSectionKind.AGENT: {
            "runtime_lease_generation": 1,
            "runtime_fence": 1,
            "process_epoch": 1,
        },
        RuntimeContextSectionKind.TASK_BOARD: {
            "task_id": "task-1",
            "status": "in_progress",
            "objective": "current-task-objective",
        },
        RuntimeContextSectionKind.LANE_WORKSPACE: {
            "lane_id": "lane-1",
            "workspace_id": "workspace-1",
            "workspace_generation": 2,
            "workspace_revision": "revision-current",
        },
        RuntimeContextSectionKind.INBOX_PROTOCOL: {
            "message_id": "protocol-message-current",
            "delivery_status": "pending",
        },
        RuntimeContextSectionKind.APPROVAL_CONTINUATION: {
            "approval_id": "approval-current",
            "approval_status": "required",
            "continuation_id": "continuation-current",
        },
        RuntimeContextSectionKind.FAILURE: {
            "failure_id": "failure-current",
            "error_code": "workspace_blocked",
            "effect_certainty": "no_effect",
        },
        RuntimeContextSectionKind.WORKFLOW_AUTHORITY: {
            "workflow_authority_id": "workflow-authority-1",
            "workflow_authority_epoch": 3,
            "workflow_authority_digest": _digest("workflow-authority"),
        },
        RuntimeContextSectionKind.CAPABILITY_EXPOSURE: {
            "tool_exposure_snapshot_id": "exposure-1",
            "tool_exposure_snapshot_digest": _digest("tool-exposure"),
            "direct_tool_names": ["world.inspect"],
            "deferred_count": 1,
            "hidden_count": 2,
            "hidden_identity_digest": _digest("hidden-tools"),
        },
        RuntimeContextSectionKind.TRANSCRIPT: {
            "message_id": "canonical-transcript-current",
            "content_digest": _digest("canonical-transcript"),
        },
        RuntimeContextSectionKind.TRUNCATION: {
            "kind": "inbox_protocol",
            "omitted_count": 4,
            "next_cursor": "inbox-cursor-current",
        },
    }
    context = RuntimeTurnContext(
        context_id="context-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        signal_id="signal-1",
        request_lineage_id="request-lineage-1",
        task_id="task-1",
        lane_id="lane-1",
        sections=tuple(
            RuntimeContextSection(kind=kind, items=(current_facts[kind],))
            for kind in RuntimeContextSectionKind
        ),
        max_bytes=131_072,
        created_at="2026-08-24T00:00:00+00:00",
    )
    contents = {
        "oldest_user": "historical-user-omitted::" + ("u" * 10_000),
        "older_assistant": "historical-assistant-omitted::" + ("a" * 10_000),
        "older_tool": "historical-tool-omitted::" + ("t" * 10_000),
        "recent_user": "recent-user-kept::" + ("r" * 300),
        "recent_assistant": "recent-assistant-kept::" + ("s" * 300),
    }
    messages = (
        RuntimeMessage(
            message_id="history-user",
            role=RuntimeMessageRole.USER,
            content=contents["oldest_user"],
            correlation_id="correlation-1",
        ),
        RuntimeMessage(
            message_id="history-assistant",
            role=RuntimeMessageRole.ASSISTANT,
            content=contents["older_assistant"],
            correlation_id="correlation-1",
        ),
        RuntimeMessage(
            message_id="history-tool",
            role=RuntimeMessageRole.TOOL,
            content=contents["older_tool"],
            correlation_id="correlation-1",
            tool_call_id="historical-call",
        ),
        RuntimeMessage(
            message_id="recent-user",
            role=RuntimeMessageRole.USER,
            content=contents["recent_user"],
            correlation_id="correlation-1",
        ),
        RuntimeMessage(
            message_id="recent-assistant",
            role=RuntimeMessageRole.ASSISTANT,
            content=contents["recent_assistant"],
            correlation_id="correlation-1",
        ),
    )
    return replace(
        _command(),
        context=context,
        messages=messages,
        max_input_units=3_000,
    ), contents


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
    assert gateway.list_calls == 2
    assert len(gateway.revalidations) == 5
    assert gateway.requests[0].affordance_snapshot_digest == _digest("snapshot")
    assert gateway.requests[0].invocation.task_id == "task-1"
    prompt_context = provider.requests[0].messages[0]
    assert prompt_context["role"] == "system"
    assert "openzyme_runtime_prompt_context@1" in str(prompt_context["content"])
    assert outcome.workflow_authority_epoch == 3
    assert outcome.tool_exposure_snapshot_id == "exposure-1"
    assert outcome.correlation_id == "correlation-1"
    assert "task_status" not in outcome.to_dict()


def test_historical_compaction_is_deterministic_and_preserves_current_context() -> None:
    command, contents = _compaction_command()
    captured_requests: list[ProviderTurnRequest] = []

    for _ in range(2):
        provider = FakeProvider(
            responses=[
                ProviderTurnResponse(
                    content="Compacted context inspected without a tool call.",
                    input_units=1,
                    output_units=1,
                    provider_reported_usage=True,
                )
            ]
        )
        gateway = FakeGateway()

        outcome = LlmRuntimeAdapter(
            _configuration(max_retries=4),
            provider,
        ).run_turn(command, gateway)

        assert outcome.disposition is RuntimeTurnDisposition.IDLE
        assert outcome.failure is None
        assert outcome.tool_requests == ()
        assert len(provider.requests) == 1
        assert provider.requests[0].attempt == 1
        assert provider.requests[0].provider_id == "openai"
        assert provider.requests[0].metadata[
            "provider_backend_identity_digest"
        ] == _digest("provider-backend")
        assert gateway.list_calls == 1
        assert gateway.requests == []
        assert len(gateway.revalidations) == 2
        captured_requests.append(provider.requests[0])

    assert captured_requests[0].messages == captured_requests[1].messages
    provider_messages = captured_requests[0].messages
    assert len(provider_messages) == 4

    canonical_content = provider_messages[0]["content"]
    marker_content = provider_messages[1]["content"]
    assert isinstance(canonical_content, str)
    assert isinstance(marker_content, str)
    canonical_payload = json.loads(canonical_content)
    marker_payload = json.loads(marker_content)

    assert canonical_payload == {
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
    protected_kinds = (
        RuntimeContextSectionKind.SESSION,
        RuntimeContextSectionKind.AGENT,
        RuntimeContextSectionKind.TASK_BOARD,
        RuntimeContextSectionKind.LANE_WORKSPACE,
        RuntimeContextSectionKind.INBOX_PROTOCOL,
        RuntimeContextSectionKind.APPROVAL_CONTINUATION,
        RuntimeContextSectionKind.FAILURE,
        RuntimeContextSectionKind.WORKFLOW_AUTHORITY,
        RuntimeContextSectionKind.CAPABILITY_EXPOSURE,
    )
    projected_sections = {
        section["kind"]: section
        for section in canonical_payload["runtime_turn_context"]["sections"]
    }
    for kind in protected_kinds:
        assert projected_sections[kind.value] == command.context.section(kind).to_dict()

    assert marker_payload == {
        "schema_version": "openzyme_transcript_compaction@1",
        "reason": "provider_input_budget",
        "historical_only": True,
        "canonical_context_preserved": True,
        "fallback_performed": False,
    }
    assert "workflow-authority-1" not in marker_content
    assert _digest("workflow-authority") not in marker_content
    assert tuple(message["content"] for message in provider_messages[2:]) == (
        contents["recent_user"],
        contents["recent_assistant"],
    )
    serialized_provider_messages = json.dumps(
        provider_messages,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert contents["oldest_user"] not in serialized_provider_messages
    assert contents["older_assistant"] not in serialized_provider_messages
    assert contents["older_tool"] not in serialized_provider_messages


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
    assert outcome.private_diagnostic is not None
    assert "secret provider failure" in outcome.private_diagnostic.exception_message
    validate_failure_diagnostic_pair(outcome.failure, outcome.private_diagnostic)
    assert outcome.private_diagnostic.record_digest not in str(outcome.to_dict())
    assert len(provider.requests) == 1


def test_unclassified_provider_exception_uses_structured_pair_and_is_not_retried() -> (
    None
):
    class ExplodingProvider:
        provider_id = "openai"
        backend_identity_digest = _digest("provider-backend")

        def __init__(self) -> None:
            self.requests: list[ProviderTurnRequest] = []

        def invoke(self, request: ProviderTurnRequest) -> ProviderTurnResponse:
            self.requests.append(request)
            raise RuntimeError("operator-only-unclassified-provider-secret")

    provider = ExplodingProvider()
    outcome = LlmRuntimeAdapter(_configuration(max_retries=4), provider).run_turn(
        _command(),
        FakeGateway(),
    )

    assert outcome.disposition is RuntimeTurnDisposition.FAILED
    assert outcome.failure is not None
    assert outcome.failure.failure_class is FailureClass.PROVIDER
    assert outcome.failure.error_code == "llm_provider_call_failed"
    assert outcome.failure.fallback_performed is False
    assert outcome.private_diagnostic is not None
    assert "operator-only-unclassified-provider-secret" in str(
        outcome.private_diagnostic.to_dict()
    )
    assert "operator-only-unclassified-provider-secret" not in str(outcome.to_dict())
    assert len(provider.requests) == 1


def test_structured_tool_failure_is_canonical_and_stops_before_another_provider_step() -> (
    None
):
    command = _command()
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
            ),
            ProviderTurnResponse(content="must not be called"),
        ]
    )
    gateway = ResultGateway(_structured_tool_failure(command))

    outcome = LlmRuntimeAdapter(_configuration(), provider).run_turn(command, gateway)

    assert outcome.disposition is RuntimeTurnDisposition.FAILED
    assert outcome.failure is not None
    assert outcome.failure.error_code == "extension_tool_runtime_failed"
    assert outcome.failure.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert outcome.failure.fallback_performed is False
    assert outcome.private_diagnostic is not None
    validate_failure_diagnostic_pair(outcome.failure, outcome.private_diagnostic)
    assert len(provider.requests) == 1
    assert len(gateway.requests) == 1
    assert len(outcome.messages) == 2
    assert outcome.messages[-1].role is RuntimeMessageRole.TOOL
    public_transcript = outcome.messages[-1].content
    assert "operator-only-tool-token" not in public_transcript
    assert "private_diagnostic_digest" not in public_transcript
    assert outcome.private_diagnostic.record_digest not in public_transcript
    public_outcome = json.dumps(outcome.to_dict(), sort_keys=True)
    assert "operator-only-tool-token" not in public_outcome
    assert outcome.private_diagnostic.record_digest not in public_outcome


def test_malformed_structured_tool_failure_fails_closed_without_provider_continuation() -> (
    None
):
    command = _command()
    malformed = _structured_tool_failure(command)
    assert malformed.failure_observation is not None
    object.__setattr__(
        malformed,
        "failure_observation",
        {
            **dict(malformed.failure_observation),
            "private_context": {"credential": "must-not-enter-runtime-wire"},
        },
    )
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
            ),
            ProviderTurnResponse(content="must not be called"),
        ]
    )

    outcome = LlmRuntimeAdapter(_configuration(), provider).run_turn(
        command,
        ResultGateway(malformed),
    )

    assert outcome.disposition is RuntimeTurnDisposition.FAILED
    assert outcome.failure is not None
    assert outcome.failure.error_code == "runtime_tool_dispatch_failed"
    assert len(provider.requests) == 1
    assert len(outcome.messages) == 1
    assert "must-not-enter-runtime-wire" not in str(outcome.to_dict())


def test_nonterminal_typed_tool_failure_remains_transcript_and_allows_replan() -> None:
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
            ),
            ProviderTurnResponse(content="I replanned after the typed rejection."),
        ]
    )
    typed_rejection = ToolResult(
        call_id="call-1",
        tool_name="world.inspect",
        ok=False,
        status="rejected",
        summary="The typed request was rejected before dispatch.",
        payload={
            "effect_certainty": "no_effect",
            "mutation_applied": False,
            "fallback_performed": False,
            "retry_performed": False,
            "reconcile_required": False,
        },
        error_code="typed_request_rejected",
        hint="Replan with current facts.",
    )

    outcome = LlmRuntimeAdapter(_configuration(), provider).run_turn(
        _command(),
        ResultGateway(typed_rejection),
    )

    assert outcome.disposition is RuntimeTurnDisposition.IDLE
    assert outcome.failure is None
    assert len(provider.requests) == 2
    assert len(outcome.messages) == 3
    tool_message = outcome.messages[1]
    assert tool_message.role is RuntimeMessageRole.TOOL
    assert json.loads(tool_message.content)["error_code"] == "typed_request_rejected"
    assert json.loads(tool_message.content)["terminates_turn"] is False


def test_adapter_relists_deferred_tool_after_inspection_and_resets_for_new_command() -> (
    None
):
    direct = ToolSpec(
        tool_name="capabilities.inspect",
        description="Inspect and expand deferred capabilities.",
        input_schema={"type": "object"},
    )
    deferred = ToolSpec(
        tool_name="world.observe",
        description="Observe deferred world facts.",
        input_schema={"type": "object"},
    )

    class DeferredGateway:
        def __init__(self) -> None:
            self.expanded_commands: set[str] = set()
            self.requests: list[tuple[str, str]] = []

        def revalidate_provider_step(self, **identities) -> None:  # noqa: ANN003
            assert identities["command_id"] in {"command-1", "command-2"}

        def list_tools(self, *, command_id: str, affordance_snapshot_digest: str):
            assert affordance_snapshot_digest == _digest("snapshot")
            if command_id in self.expanded_commands:
                return (direct, deferred)
            return (direct,)

        def invoke(self, *, command_id: str, request: RuntimeToolRequest) -> ToolResult:
            tool_name = request.invocation.tool_name
            self.requests.append((command_id, tool_name))
            if tool_name == "capabilities.inspect":
                self.expanded_commands.add(command_id)
                return ToolResult(
                    call_id=request.invocation.call_id,
                    tool_name=tool_name,
                    ok=True,
                    status="expanded",
                    summary="Expanded one command-scoped deferred tool.",
                    payload={"expanded_tool_names": ["world.observe"]},
                )
            assert tool_name == "world.observe"
            assert command_id in self.expanded_commands
            return ToolResult(
                call_id=request.invocation.call_id,
                tool_name=tool_name,
                ok=True,
                status="observed",
                summary="Observed deferred world facts.",
                payload={"task_transition_performed": False},
            )

    gateway = DeferredGateway()
    provider = FakeProvider(
        responses=[
            ProviderTurnResponse(
                content="Inspect capabilities.",
                tool_calls=(
                    ProviderToolCall(
                        call_id="inspect-call",
                        tool_name="capabilities.inspect",
                        arguments={"expand_tool_names": ["world.observe"]},
                    ),
                ),
            ),
            ProviderTurnResponse(
                content="Use the newly visible capability.",
                tool_calls=(
                    ProviderToolCall(
                        call_id="observe-call",
                        tool_name="world.observe",
                        arguments={},
                    ),
                ),
            ),
            ProviderTurnResponse(content="Deferred observation complete."),
        ]
    )

    first = LlmRuntimeAdapter(_configuration(), provider).run_turn(
        _command(),
        gateway,
    )

    assert first.disposition is RuntimeTurnDisposition.IDLE
    assert tuple(spec.tool_name for spec in provider.requests[0].tools) == (
        "capabilities.inspect",
    )
    assert tuple(spec.tool_name for spec in provider.requests[1].tools) == (
        "capabilities.inspect",
        "world.observe",
    )
    assert gateway.requests == [
        ("command-1", "capabilities.inspect"),
        ("command-1", "world.observe"),
    ]

    next_provider = FakeProvider(
        responses=[ProviderTurnResponse(content="New command inspected direct tools.")]
    )
    second = LlmRuntimeAdapter(_configuration(), next_provider).run_turn(
        replace(_command(), command_id="command-2"),
        gateway,
    )
    assert second.disposition is RuntimeTurnDisposition.IDLE
    assert tuple(spec.tool_name for spec in next_provider.requests[0].tools) == (
        "capabilities.inspect",
    )


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

    gateway = FakeGateway()
    outcome = adapter.run_turn(_command(), gateway)

    assert outcome.disposition is RuntimeTurnDisposition.IDLE
    assert [request.provider_id for request in provider.requests] == [
        "openai",
        "openai",
    ]
    assert {
        request.metadata["provider_backend_identity_digest"]
        for request in provider.requests
    } == {_digest("provider-backend")}
    assert len(gateway.revalidations) == 3


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


def test_stale_workflow_epoch_before_tool_dispatch_fails_without_dispatch() -> None:
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
            )
        ]
    )
    gateway = FakeGateway(fail_revalidation_at=3)

    outcome = LlmRuntimeAdapter(_configuration(), provider).run_turn(
        _command(),
        gateway,
    )

    assert outcome.disposition is RuntimeTurnDisposition.FAILED
    assert outcome.failure is not None
    assert outcome.failure.error_code == "workflow_authority_epoch_stale"
    assert outcome.failure.fallback_performed is False
    assert len(outcome.messages) == 1
    assert len(outcome.tool_requests) == 1
    assert gateway.requests == []


def test_current_canonical_context_over_budget_fails_before_provider() -> None:
    provider = FakeProvider(
        responses=[ProviderTurnResponse(content="must not be called")]
    )
    gateway = FakeGateway()

    outcome = LlmRuntimeAdapter(_configuration(), provider).run_turn(
        _command(max_input_units=1),
        gateway,
    )

    assert outcome.disposition is RuntimeTurnDisposition.FAILED
    assert outcome.failure is not None
    assert outcome.failure.error_code == "runtime_context_budget_exceeded"
    assert outcome.failure.fallback_performed is False
    assert provider.requests == []
    assert gateway.list_calls == 0
    assert gateway.requests == []
    assert gateway.revalidations == []


@pytest.mark.parametrize(
    "case",
    ("context_identity_drift", "legacy_schema", "missing_structured_context"),
)
def test_noncurrent_structured_command_fails_before_provider_or_tool_boundary(
    case: str,
) -> None:
    provider = FakeProvider(
        responses=[ProviderTurnResponse(content="must not be called")]
    )
    gateway = FakeGateway()
    payload = _command().to_dict()
    if case == "legacy_schema":
        payload["schema_version"] = "runtime_turn_command@1"
    elif case == "missing_structured_context":
        payload.pop("context")
    else:
        context = dict(payload["context"])
        context["session_id"] = "session-other"
        context.pop("byte_size")
        context.pop("context_digest")
        payload["context"] = context
        payload.pop("command_digest")

    with pytest.raises(ValueError):
        command = RuntimeTurnCommand.from_dict(payload)
        LlmRuntimeAdapter(_configuration(), provider).run_turn(command, gateway)

    assert provider.requests == []
    assert gateway.list_calls == 0
    assert gateway.requests == []
    assert gateway.revalidations == []


def test_missing_fence_revalidator_fails_closed_before_provider() -> None:
    provider = FakeProvider(
        responses=[ProviderTurnResponse(content="must not be called")]
    )

    class UnfencedGateway:
        def list_tools(self, **kwargs):  # noqa: ANN003, ANN201
            raise AssertionError("tool listing must not run")

        def invoke(self, **kwargs):  # noqa: ANN003, ANN201
            raise AssertionError("tool dispatch must not run")

    outcome = LlmRuntimeAdapter(_configuration(), provider).run_turn(
        _command(),
        UnfencedGateway(),  # type: ignore[arg-type]
    )

    assert outcome.disposition is RuntimeTurnDisposition.FAILED
    assert outcome.failure is not None
    assert outcome.failure.error_code == "runtime_turn_fence_revalidator_missing"
    assert provider.requests == []


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
