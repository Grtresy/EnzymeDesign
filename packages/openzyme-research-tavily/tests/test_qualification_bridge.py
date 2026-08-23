from types import SimpleNamespace

import pytest

from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_research_tavily import TavilyConfiguration
from openzyme_research_tavily import TavilyQualificationProbeBridge
from openzyme_research_tavily import TavilyQualificationLocatorPreparationExecutor
from openzyme_research_tavily import TavilyResearchProvider


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


def _binding() -> ExternalQualificationBridgeBinding:
    return ExternalQualificationBridgeBinding.create(
        component_id="openzyme.research.tavily",
        operation="bounded-query",
        route_id="openzyme.research.tavily.query@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
        credential_locator_id="credential.tavily.qualification",
    )


def _request() -> ExternalQualificationProbeRequest:
    binding = _binding()
    return ExternalQualificationProbeRequest.create(
        attempt_id="attempt.tavily.qualification",
        plan_digest=binding.plan_digest,
        unit_digest=binding.unit_digest,
        operation=binding.operation,
        timeout_seconds=30,
        input_digest=binding.input_digest,
        expected_result_schema_digest=binding.expected_result_schema_digest,
        credential_locator_id="credential.tavily.qualification",
    )


def test_tavily_bridge_uses_one_bounded_query_and_same_attempt_reconcile() -> None:
    calls = 0

    def search_callable(**kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["max_results"] == 3
        return {
            "results": [
                {
                    "title": "OpenZyme",
                    "url": "https://example.org/openzyme",
                    "content": "bounded qualification source",
                }
            ]
        }

    provider = TavilyResearchProvider(
        configuration=TavilyConfiguration(
            secret_locator="credential.tavily.qualification",
            max_results=3,
            include_raw_content=False,
        ),
        search_callable=search_callable,
    )
    bridge = TavilyQualificationProbeBridge(
        binding=_binding(),
        provider=provider,
        deadline_at="2026-08-23T00:00:00+00:00",
    )
    request = _request()

    outcome = bridge.dispatch(request)

    assert outcome.disposition is ExternalQualificationProbeDisposition.SUCCEEDED
    assert outcome.fallback_performed is False
    assert bridge.reconcile(request) == outcome
    assert calls == 1
    with pytest.raises(ExternalQualificationError) as captured:
        bridge.dispatch(request)
    assert captured.value.error_code == "qualification_probe_redispatch_forbidden"
    assert calls == 1


def test_tavily_bridge_rejects_request_drift_before_provider_call() -> None:
    calls = 0

    def search_callable(**kwargs):
        nonlocal calls
        calls += 1
        return {"results": []}

    bridge = TavilyQualificationProbeBridge(
        binding=_binding(),
        provider=TavilyResearchProvider(
            configuration=TavilyConfiguration(
                secret_locator="credential.tavily.qualification"
            ),
            search_callable=search_callable,
        ),
        deadline_at="2026-08-23T00:00:00+00:00",
    )
    request = _request()
    drifted = ExternalQualificationProbeRequest.create(
        attempt_id=request.attempt_id,
        plan_digest=request.plan_digest,
        unit_digest=request.unit_digest,
        operation="other-operation",
        timeout_seconds=request.timeout_seconds,
        input_digest=request.input_digest,
        expected_result_schema_digest=request.expected_result_schema_digest,
        credential_locator_id=request.credential_locator_id,
    )

    with pytest.raises(ExternalQualificationError) as captured:
        bridge.dispatch(drifted)
    assert captured.value.error_code == "qualification_bridge_request_binding_mismatch"
    assert calls == 0


class _PreparationMaterial:
    locator_id = "credential.tavily.qualification"
    locator_version = "v1"
    material_kind = "bearer-token"

    def field_value(self, field_name: str) -> str:
        return {
            "token": "secret-canary-never-export",
            "account_locator_id": "tavily-dedicated-qualification",
            "scope_id": "search-extract-bounded",
        }[field_name]


def test_tavily_locator_preparation_exports_only_opaque_identity() -> None:
    executor = TavilyQualificationLocatorPreparationExecutor()
    result = executor(
        plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
        authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
        action=SimpleNamespace(
            action_id="prepare.batch-1.tavily-primary",
            owner_component_id="openzyme.research.tavily",
            effect_id="provider.tavily.dedicated-account.provision",
            credential_locator_id="credential.tavily.qualification",
            input_binding_digest="sha256:" + "3" * 64,
        ),
        occurrence_id="occurrence.tavily-preparation",
        request_digest="sha256:" + "4" * 64,
        credential_material=_PreparationMaterial(),
    )

    assert {item.field_id for item in result.safe_identity_fields} == {
        "account_locator_digest",
        "credential_locator_id",
        "credential_scope_digest",
        "service_endpoint_identity",
    }
    assert "secret-canary-never-export" not in str(result.to_dict())
    assert result.observation.credential_material_accessed is True
