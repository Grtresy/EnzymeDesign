from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalIdentityPreparationAction
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
from openzyme_contracts import ExternalIdentityPreparationPlan
from openzyme_contracts import ExternalIdentityPreparationResult
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import create_external_identity_preparation_success
from openzyme_contracts import verify_external_qualification_probe_request_binding

from .provider import LlmProviderBackend
from .provider import LlmProviderError
from .provider import ProviderTurnRequest


_QUALIFICATION_TOOL = ToolSpec(
    tool_name="qualification_echo",
    description="Return the exact bounded qualification token.",
    input_schema={
        "type": "object",
        "properties": {"token": {"type": "string"}},
        "required": ["token"],
        "additionalProperties": False,
    },
)


class LlmQualificationCredentialMaterial(Protocol):
    locator_id: str
    locator_version: str
    material_kind: str

    def field_value(self, field_name: str) -> str: ...


@dataclass(frozen=True, slots=True)
class LlmQualificationLocatorPreparationExecutor:
    """Bind opaque account/scope identity without placing the token in evidence."""

    provider_id: str = "micuapi"
    endpoint: str = "https://www.micuapi.ai/v1"
    model: str = "gpt-5.5"

    def __call__(
        self,
        *,
        plan: ExternalIdentityPreparationPlan,
        authorization: ExternalIdentityPreparationOccurrenceAuthorization,
        action: ExternalIdentityPreparationAction,
        occurrence_id: str,
        request_digest: str,
        credential_material: LlmQualificationCredentialMaterial,
    ) -> ExternalIdentityPreparationResult:
        if (
            action.owner_component_id != "openzyme.runtime.llm"
            or action.effect_id != "provider.llm.qualification-locator.configure"
            or credential_material.locator_id != action.credential_locator_id
        ):
            raise ExternalQualificationError(
                "qualification_llm_preparation_binding_mismatch",
                "LLM locator preparation differs from the exact planned action",
            )
        credential_material.field_value("token")
        account_locator_id = credential_material.field_value("account_locator_id")
        scope_id = credential_material.field_value("scope_id")
        fields = tuple(
            sorted(
                (
                    SafeIdentityField(
                        "account_or_project_locator_digest",
                        canonical_sha256_digest(
                            {
                                "provider_id": self.provider_id,
                                "account_locator_id": account_locator_id,
                                "locator_version": credential_material.locator_version,
                            }
                        ),
                    ),
                    SafeIdentityField(
                        "credential_scope_digest",
                        canonical_sha256_digest(
                            {
                                "provider_id": self.provider_id,
                                "scope_id": scope_id,
                                "material_kind": credential_material.material_kind,
                            }
                        ),
                    ),
                    SafeIdentityField(
                        "credential_locator_id", credential_material.locator_id
                    ),
                ),
                key=lambda item: item.field_id,
            )
        )
        return create_external_identity_preparation_success(
            occurrence_id=occurrence_id,
            preparation_plan_digest=plan.preparation_plan_digest,
            authorization_digest=authorization.authorization_digest,
            action_id=action.action_id,
            owner_component_id=action.owner_component_id,
            effect_id=action.effect_id,
            input_binding_digest=action.input_binding_digest,
            request_digest=request_digest,
            safe_identity_fields=fields,
            receipt_payload={
                "schema_version": "llm_qualification_locator_preparation_receipt@1",
                "occurrence_id": occurrence_id,
                "provider_id": self.provider_id,
                "endpoint": self.endpoint,
                "model": self.model,
                "locator_id": credential_material.locator_id,
                "locator_version": credential_material.locator_version,
                "safe_identity_fields": [item.to_dict() for item in fields],
            },
            external_effect_performed=True,
            credential_material_accessed=True,
        )


@dataclass(slots=True)
class LlmQualificationProbeBridge:
    """Adapter-owned exact bounded-turn bridge; construction performs no call."""

    binding: ExternalQualificationBridgeBinding
    backend: LlmProviderBackend
    provider_id: str
    model: str
    expected_backend_identity_digest: str
    token: str = "OPENZYME_QUALIFICATION_OK"
    timeout_seconds: float = 60.0
    _outcomes: dict[str, ExternalQualificationProbeOutcome] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.runtime.llm":
            raise ValueError(
                "LLM qualification bridge requires the selected LLM binding"
            )
        if self.binding.operation != "bounded-turn":
            raise ValueError("LLM qualification bridge supports only bounded-turn")
        if self.binding.route_id != "openzyme.runtime.llm.turn@1":
            raise ValueError("LLM qualification bridge requires the selected route")
        if self.backend.provider_id != self.provider_id:
            raise ExternalQualificationError(
                "qualification_llm_provider_identity_mismatch",
                "LLM backend differs from the exact selected provider",
            )
        if (
            self.backend.backend_identity_digest
            != self.expected_backend_identity_digest
        ):
            raise ExternalQualificationError(
                "qualification_llm_backend_identity_mismatch",
                "LLM backend identity differs from the selected subject closure",
            )
        if self.binding.credential_locator_id is None:
            raise ValueError("LLM qualification requires one exact credential locator")
        if not self.model or not self.token or not 0 < self.timeout_seconds <= 120:
            raise ValueError("LLM qualification request must be bounded")

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        if request.attempt_id in self._outcomes:
            raise ExternalQualificationError(
                "qualification_probe_redispatch_forbidden",
                "LLM qualification attempt cannot be dispatched twice",
            )
        provider_request = ProviderTurnRequest(
            provider_id=self.provider_id,
            model=self.model,
            messages=(
                {
                    "role": "system",
                    "content": "Call qualification_echo exactly once with the supplied token.",
                },
                {"role": "user", "content": self.token},
            ),
            tools=(_QUALIFICATION_TOOL,),
            max_output_units=256,
            timeout_seconds=min(self.timeout_seconds, float(request.timeout_seconds)),
            attempt=1,
            metadata={
                "qualification_attempt_id": request.attempt_id,
                "qualification_binding_digest": self.binding.binding_digest,
            },
        )
        try:
            response = self.backend.invoke(provider_request)
            valid_calls = tuple(
                call
                for call in response.tool_calls
                if call.tool_name == _QUALIFICATION_TOOL.tool_name
                and call.arguments.get("token") == self.token
            )
            if len(valid_calls) != 1 or len(response.tool_calls) != 1:
                outcome = self._failure(
                    request,
                    error_code="qualification_llm_tool_call_invalid",
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                )
            else:
                payload = {
                    "content": response.content,
                    "input_units": response.input_units,
                    "output_units": response.output_units,
                    "provider_reported_usage": response.provider_reported_usage,
                    "tool_call": {
                        "call_id": valid_calls[0].call_id,
                        "tool_name": valid_calls[0].tool_name,
                        "arguments": dict(valid_calls[0].arguments),
                    },
                }
                receipt_digest = canonical_sha256_digest(payload)
                outcome = ExternalQualificationProbeOutcome(
                    attempt_id=request.attempt_id,
                    request_digest=request.request_digest,
                    disposition=ExternalQualificationProbeDisposition.SUCCEEDED,
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                    observed_operation=request.operation,
                    output_digest=canonical_sha256_digest(
                        {"provider_response_digest": receipt_digest}
                    ),
                    observed_result_schema_digest=(
                        request.expected_result_schema_digest
                    ),
                    backend_receipt_digest=receipt_digest,
                    external_effect_performed=True,
                    credential_material_accessed=True,
                    fallback_performed=False,
                )
        except LlmProviderError as exc:
            outcome = self._failure(
                request,
                error_code=exc.code,
                effect_certainty=(
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if exc.retryable
                    else ExternalEffectCertainty.TERMINAL_KNOWN
                ),
            )
        self._outcomes[request.attempt_id] = outcome
        return outcome

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        try:
            return self._outcomes[request.attempt_id]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "LLM reconcile requires the same prior attempt",
            ) from exc

    @staticmethod
    def _failure(
        request: ExternalQualificationProbeRequest,
        *,
        error_code: str,
        effect_certainty: ExternalEffectCertainty,
    ) -> ExternalQualificationProbeOutcome:
        return ExternalQualificationProbeOutcome(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            disposition=(
                ExternalQualificationProbeDisposition.RECONCILE_REQUIRED
                if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else ExternalQualificationProbeDisposition.FAILED
            ),
            effect_certainty=effect_certainty,
            observed_operation=None,
            output_digest=None,
            observed_result_schema_digest=None,
            backend_receipt_digest=None,
            error_code=error_code,
            external_effect_performed=True,
            credential_material_accessed=True,
            fallback_performed=False,
        )


__all__ = [
    "LlmQualificationCredentialMaterial",
    "LlmQualificationLocatorPreparationExecutor",
    "LlmQualificationProbeBridge",
]
