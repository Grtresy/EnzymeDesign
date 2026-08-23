from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_runtime_llm import LlmQualificationProbeBridge
from openzyme_runtime_llm import LlmQualificationLocatorPreparationExecutor
from openzyme_runtime_llm import ProviderToolCall
from openzyme_runtime_llm import ProviderTurnRequest
from openzyme_runtime_llm import ProviderTurnResponse


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


@dataclass
class _Backend:
    provider_id: str = "openai-compatible"
    backend_identity_digest: str = DIGEST
    calls: int = 0

    def invoke(self, request: ProviderTurnRequest) -> ProviderTurnResponse:
        self.calls += 1
        assert request.attempt == 1
        assert request.tools[0].tool_name == "qualification_echo"
        return ProviderTurnResponse(
            content="",
            tool_calls=(
                ProviderToolCall(
                    call_id="call.qualification",
                    tool_name="qualification_echo",
                    arguments={"token": "OPENZYME_QUALIFICATION_OK"},
                ),
            ),
            input_units=32,
            output_units=8,
            provider_reported_usage=True,
        )


def _binding() -> ExternalQualificationBridgeBinding:
    return ExternalQualificationBridgeBinding.create(
        component_id="openzyme.runtime.llm",
        operation="bounded-turn",
        route_id="openzyme.runtime.llm.turn@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
        credential_locator_id="credential.llm.micuapi.qualification",
    )


def _request() -> ExternalQualificationProbeRequest:
    binding = _binding()
    return ExternalQualificationProbeRequest.create(
        attempt_id="attempt.llm.qualification",
        plan_digest=binding.plan_digest,
        unit_digest=binding.unit_digest,
        operation=binding.operation,
        timeout_seconds=60,
        input_digest=binding.input_digest,
        expected_result_schema_digest=binding.expected_result_schema_digest,
        credential_locator_id="credential.llm.micuapi.qualification",
    )


def test_llm_bridge_runs_one_exact_tool_call_and_never_redispatches() -> None:
    backend = _Backend()
    bridge = LlmQualificationProbeBridge(
        binding=_binding(),
        backend=backend,
        provider_id=backend.provider_id,
        model="gpt-5.5",
        expected_backend_identity_digest=backend.backend_identity_digest,
    )
    request = _request()

    outcome = bridge.dispatch(request)

    assert outcome.disposition is ExternalQualificationProbeDisposition.SUCCEEDED
    assert outcome.external_effect_performed is True
    assert outcome.credential_material_accessed is True
    assert outcome.fallback_performed is False
    assert bridge.reconcile(request) == outcome
    assert backend.calls == 1
    with pytest.raises(ExternalQualificationError) as captured:
        bridge.dispatch(request)
    assert captured.value.error_code == "qualification_probe_redispatch_forbidden"
    assert backend.calls == 1


def test_llm_bridge_rejects_request_drift_before_provider_call() -> None:
    backend = _Backend()
    bridge = LlmQualificationProbeBridge(
        binding=_binding(),
        backend=backend,
        provider_id=backend.provider_id,
        model="gpt-5.5",
        expected_backend_identity_digest=backend.backend_identity_digest,
    )
    request = _request()
    drifted = ExternalQualificationProbeRequest.create(
        attempt_id=request.attempt_id,
        plan_digest=request.plan_digest,
        unit_digest=request.unit_digest,
        operation=request.operation,
        timeout_seconds=request.timeout_seconds,
        input_digest=DIGEST,
        expected_result_schema_digest=request.expected_result_schema_digest,
        credential_locator_id=request.credential_locator_id,
    )

    with pytest.raises(ExternalQualificationError) as captured:
        bridge.dispatch(drifted)
    assert captured.value.error_code == "qualification_bridge_request_binding_mismatch"
    assert backend.calls == 0


class _PreparationMaterial:
    locator_id = "credential.llm.micuapi.qualification"
    locator_version = "v1"
    material_kind = "bearer-token"

    def field_value(self, field_name: str) -> str:
        return {
            "token": "secret-canary-never-export",
            "account_locator_id": "micuapi-qualification-account",
            "scope_id": "chat-completions-bounded-turn",
        }[field_name]


def test_llm_locator_preparation_exports_only_opaque_identity() -> None:
    executor = LlmQualificationLocatorPreparationExecutor()
    result = executor(
        plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
        authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
        action=SimpleNamespace(
            action_id="prepare.batch-1.llm-primary",
            owner_component_id="openzyme.runtime.llm",
            effect_id="provider.llm.qualification-locator.configure",
            credential_locator_id="credential.llm.micuapi.qualification",
            input_binding_digest="sha256:" + "3" * 64,
        ),
        occurrence_id="occurrence.llm-preparation",
        request_digest="sha256:" + "4" * 64,
        credential_material=_PreparationMaterial(),
    )

    assert {item.field_id for item in result.safe_identity_fields} == {
        "account_or_project_locator_digest",
        "credential_locator_id",
        "credential_scope_digest",
    }
    assert "secret-canary-never-export" not in str(result.to_dict())
    assert result.observation.credential_material_accessed is True
