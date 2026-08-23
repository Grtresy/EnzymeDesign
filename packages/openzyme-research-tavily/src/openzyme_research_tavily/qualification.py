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
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import create_external_identity_preparation_success
from openzyme_contracts import verify_external_qualification_probe_request_binding
from openzyme_research import ResearchProviderReceipt
from openzyme_research import ResearchProviderRequest
from openzyme_research import ResearchUnitSpec

from .adapter import TavilyResearchProvider


class TavilyQualificationCredentialMaterial(Protocol):
    locator_id: str
    locator_version: str
    material_kind: str

    def field_value(self, field_name: str) -> str: ...


@dataclass(frozen=True, slots=True)
class TavilyQualificationLocatorPreparationExecutor:
    service_endpoint_identity: str = "https.api.tavily.com"

    def __call__(
        self,
        *,
        plan: ExternalIdentityPreparationPlan,
        authorization: ExternalIdentityPreparationOccurrenceAuthorization,
        action: ExternalIdentityPreparationAction,
        occurrence_id: str,
        request_digest: str,
        credential_material: TavilyQualificationCredentialMaterial,
    ) -> ExternalIdentityPreparationResult:
        if (
            action.owner_component_id != "openzyme.research.tavily"
            or action.effect_id != "provider.tavily.dedicated-account.provision"
            or credential_material.locator_id != action.credential_locator_id
        ):
            raise ExternalQualificationError(
                "qualification_tavily_preparation_binding_mismatch",
                "Tavily locator preparation differs from the exact planned action",
            )
        credential_material.field_value("token")
        account_locator_id = credential_material.field_value("account_locator_id")
        scope_id = credential_material.field_value("scope_id")
        fields = tuple(
            sorted(
                (
                    SafeIdentityField(
                        "account_locator_digest",
                        canonical_sha256_digest(
                            {
                                "provider_id": "tavily",
                                "account_locator_id": account_locator_id,
                                "locator_version": credential_material.locator_version,
                            }
                        ),
                    ),
                    SafeIdentityField(
                        "credential_scope_digest",
                        canonical_sha256_digest(
                            {
                                "provider_id": "tavily",
                                "scope_id": scope_id,
                                "material_kind": credential_material.material_kind,
                            }
                        ),
                    ),
                    SafeIdentityField(
                        "credential_locator_id", credential_material.locator_id
                    ),
                    SafeIdentityField(
                        "service_endpoint_identity", self.service_endpoint_identity
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
                "schema_version": "tavily_qualification_locator_preparation_receipt@1",
                "occurrence_id": occurrence_id,
                "provider_id": "tavily",
                "service_endpoint_identity": self.service_endpoint_identity,
                "locator_id": credential_material.locator_id,
                "locator_version": credential_material.locator_version,
                "safe_identity_fields": [item.to_dict() for item in fields],
            },
            external_effect_performed=True,
            credential_material_accessed=True,
        )


@dataclass(slots=True)
class TavilyQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    provider: TavilyResearchProvider
    deadline_at: str
    query: str = "OpenZyme bounded external qualification source identity"
    _dispatched_attempts: set[str] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.research.tavily":
            raise ValueError("Tavily bridge requires the selected Tavily binding")
        if self.binding.operation != "bounded-query":
            raise ValueError("Tavily bridge supports only bounded-query")
        if (
            self.binding.route_id != "openzyme.research.tavily.query@1"
            or self.provider.provider_id != "openzyme.research.tavily"
            or self.provider.route_id != "openzyme.research.tavily.search@1"
        ):
            raise ValueError("Tavily bridge requires the selected Adapter route")
        if (
            self.binding.credential_locator_id is None
            or self.provider.configuration.secret_locator
            != self.binding.credential_locator_id
        ):
            raise ExternalQualificationError(
                "qualification_tavily_credential_locator_mismatch",
                "Tavily Adapter locator differs from the exact selected binding",
            )
        if self.provider.configuration.max_results > 3:
            raise ValueError("Tavily qualification permits at most three results")
        if not self.deadline_at or not self.query:
            raise ValueError("Tavily qualification request must be bounded")

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        if request.attempt_id in self._dispatched_attempts:
            raise ExternalQualificationError(
                "qualification_probe_redispatch_forbidden",
                "Tavily qualification attempt cannot be dispatched twice",
            )
        self._dispatched_attempts.add(request.attempt_id)
        receipt = self.provider.dispatch(self._provider_request(request))
        return self._outcome(request, receipt)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        try:
            receipt = self.provider.reconcile(request.attempt_id)
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "Tavily reconcile requires the same prior operation",
            ) from exc
        return self._outcome(request, receipt)

    def private_diagnostic_context(
        self, request: ExternalQualificationProbeRequest
    ) -> dict[str, object]:
        """Return secret-safe provider failure detail for protected diagnostics only."""

        try:
            receipt = self.provider.reconcile(request.attempt_id)
        except KeyError:
            return {"provider_observation_present": False}
        return {
            "provider_observation_present": True,
            "provider_id": receipt.provider_id,
            "provider_status": receipt.status,
            "provider_error_code": receipt.error_code,
            "provider_summary": receipt.summary,
            "provider_effect_certainty": receipt.effect_certainty.value,
            "provider_response_digest": receipt.response_digest,
        }

    def _provider_request(
        self, request: ExternalQualificationProbeRequest
    ) -> ResearchProviderRequest:
        return ResearchProviderRequest(
            operation_id=request.attempt_id,
            request_digest=request.request_digest,
            session_id="session.external-qualification",
            unit=ResearchUnitSpec(
                unit_id="unit.tavily.qualification",
                topic="external-qualification",
                query=self.query,
            ),
            deadline_at=self.deadline_at,
        )

    @staticmethod
    def _outcome(
        request: ExternalQualificationProbeRequest,
        receipt: ResearchProviderReceipt,
    ) -> ExternalQualificationProbeOutcome:
        if receipt.fallback_performed:
            raise ExternalQualificationError(
                "qualification_probe_fallback_forbidden",
                "Tavily qualification receipt reported fallback",
            )
        if receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            disposition = ExternalQualificationProbeDisposition.RECONCILE_REQUIRED
        elif receipt.status == "completed" and 1 <= len(receipt.sources) <= 3:
            disposition = ExternalQualificationProbeDisposition.SUCCEEDED
        else:
            disposition = ExternalQualificationProbeDisposition.FAILED
        terminal = (
            disposition is not ExternalQualificationProbeDisposition.RECONCILE_REQUIRED
        )
        receipt_digest = (
            canonical_sha256_digest(receipt.to_dict()) if terminal else None
        )
        return ExternalQualificationProbeOutcome(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            disposition=disposition,
            effect_certainty=receipt.effect_certainty,
            observed_operation=request.operation if terminal else None,
            output_digest=(
                canonical_sha256_digest(
                    {
                        "receipt_digest": receipt_digest,
                        "source_count": len(receipt.sources),
                    }
                )
                if disposition is ExternalQualificationProbeDisposition.SUCCEEDED
                else None
            ),
            observed_result_schema_digest=(
                request.expected_result_schema_digest
                if disposition is ExternalQualificationProbeDisposition.SUCCEEDED
                else None
            ),
            backend_receipt_digest=receipt_digest,
            error_code=(
                receipt.error_code
                if disposition is not ExternalQualificationProbeDisposition.SUCCEEDED
                else None
            ),
            external_effect_performed=True,
            credential_material_accessed=True,
            fallback_performed=False,
        )


__all__ = [
    "TavilyQualificationCredentialMaterial",
    "TavilyQualificationLocatorPreparationExecutor",
    "TavilyQualificationProbeBridge",
]
