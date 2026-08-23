import pytest

from enzymedesign_bio_provider_adapters import BioHttpQualificationProbeBridge
from enzymedesign_bio_provider_adapters import DeterministicBioProviderAdapter
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeRequest


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


@pytest.mark.parametrize("provider_id", ["uniprot", "rcsb", "interpro"])
def test_bio_http_bridge_compiles_one_exact_read_smoke(provider_id: str) -> None:
    binding = ExternalQualificationBridgeBinding.create(
        component_id="enzymedesign.bio-provider-http",
        operation="read-smoke",
        route_id=f"enzymedesign.bio-provider-http.{provider_id}.read@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
    )
    request = ExternalQualificationProbeRequest.create(
        attempt_id=f"attempt.bio.{provider_id}",
        plan_digest=binding.plan_digest,
        unit_digest=binding.unit_digest,
        operation=binding.operation,
        timeout_seconds=30,
        input_digest=binding.input_digest,
        expected_result_schema_digest=binding.expected_result_schema_digest,
        credential_locator_id=None,
    )
    bridge = BioHttpQualificationProbeBridge(
        binding=binding,
        adapter=DeterministicBioProviderAdapter(),
        provider_id=provider_id,
    )

    outcome = bridge.dispatch(request)

    assert outcome.disposition is ExternalQualificationProbeDisposition.SUCCEEDED
    assert outcome.external_effect_performed is True
    assert outcome.credential_material_accessed is False
    assert outcome.fallback_performed is False
    assert bridge.reconcile(request) == outcome
    with pytest.raises(ExternalQualificationError) as captured:
        bridge.dispatch(request)
    assert captured.value.error_code == "qualification_probe_redispatch_forbidden"
