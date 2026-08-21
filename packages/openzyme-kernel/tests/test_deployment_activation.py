from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_kernel import DeploymentActivationCoordinator
from openzyme_kernel import DeploymentActivationGate
from openzyme_kernel import DeploymentActivationRequest
from openzyme_kernel import DeploymentSurface
from openzyme_kernel import DeploymentVerificationKind
from openzyme_kernel import KernelContractError
from openzyme_kernel import ReadOnlyDeploymentVerification

from composition_test_support import activate_gate
from composition_test_support import activated_composition
from composition_test_support import digest


def _proofs(composition: object, release: object) -> tuple:
    return tuple(
        ReadOnlyDeploymentVerification.create(
            verification_id=f"proof-{kind.value}",
            verification_kind=kind,
            verifier_id="startup-verifier",
            expected_digest=expected,
            observed_digest=expected,
            verified_at="2026-08-19T01:00:00+00:00",
        )
        for kind, expected in (
            (DeploymentVerificationKind.COMPOSITION, composition.activation_digest),
            (DeploymentVerificationKind.CORE_SCHEMA, release.core_schema_digest),
            (DeploymentVerificationKind.INSTALLED_WHEELS, digest("wheels")),
        )
    )


def _request(composition: object, release: object) -> DeploymentActivationRequest:
    return DeploymentActivationRequest(
        epoch_id="epoch-1",
        sequence=1,
        expected_wheel_set_digest=digest("wheels"),
        activated_by_actor_id="operator-1",
        activated_at="2026-08-19T01:00:00+00:00",
        verifications=_proofs(composition, release),
    )


@pytest.mark.parametrize("surface", tuple(DeploymentSurface))
def test_every_runtime_surface_is_closed_before_activation(surface: DeploymentSurface) -> None:
    gate = DeploymentActivationGate()

    with pytest.raises(KernelContractError) as raised:
        gate.require_active(surface)

    assert raised.value.code == "deployment_not_active"
    assert raised.value.mutation_applied is False
    assert raised.value.effect_certainty == "no_effect"
    assert gate.active_epoch is None


def test_activation_requires_all_read_only_proofs_without_partial_surface() -> None:
    composition, release, _ = activated_composition()
    gate = DeploymentActivationGate()
    request = _request(composition, release)
    request = replace(
        request,
        verifications=tuple(
            proof
            for proof in request.verifications
            if proof.verification_kind is not DeploymentVerificationKind.INSTALLED_WHEELS
        ),
    )

    with pytest.raises(KernelContractError) as raised:
        DeploymentActivationCoordinator(gate).activate(
            composition=composition,
            release_identity=release,
            request=request,
        )

    assert raised.value.code == "deployment_verification_incomplete"
    assert gate.active_epoch is None


def test_drifted_wheel_proof_fails_before_any_surface_is_authorized() -> None:
    composition, release, _ = activated_composition()
    gate = DeploymentActivationGate()
    request = _request(composition, release)
    proofs = list(request.verifications)
    index = next(
        index
        for index, proof in enumerate(proofs)
        if proof.verification_kind is DeploymentVerificationKind.INSTALLED_WHEELS
    )
    proofs[index] = ReadOnlyDeploymentVerification.create(
        verification_id="proof-installed_wheels",
        verification_kind=DeploymentVerificationKind.INSTALLED_WHEELS,
        verifier_id="startup-verifier",
        expected_digest=digest("wheels"),
        observed_digest=digest("other-wheels"),
        verified_at="2026-08-19T01:00:00+00:00",
    )

    with pytest.raises(KernelContractError) as raised:
        DeploymentActivationCoordinator(gate).activate(
            composition=composition,
            release_identity=release,
            request=replace(request, verifications=tuple(proofs)),
        )

    assert raised.value.code == "deployment_verification_failed"
    assert gate.active_epoch is None


def test_verification_contract_rejects_mutating_or_effectful_receipt() -> None:
    proof = ReadOnlyDeploymentVerification.create(
        verification_id="proof-schema",
        verification_kind=DeploymentVerificationKind.CORE_SCHEMA,
        verifier_id="startup-verifier",
        expected_digest=digest("schema"),
        observed_digest=digest("schema"),
        verified_at="2026-08-19T01:00:00+00:00",
    )

    with pytest.raises(ValueError):
        replace(proof, mutation_applied=True)
    with pytest.raises(ValueError):
        replace(proof, effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN)


def test_valid_activation_produces_exact_epoch_and_surface_authorizations() -> None:
    composition, release, _ = activated_composition()
    gate, epoch = activate_gate(composition, release)

    assert gate.active_epoch == epoch
    assert epoch.has_valid_digest()
    assert epoch.release_identity == release
    for surface in DeploymentSurface:
        authorization = gate.require_active(surface)
        assert gate.validate_authorization(authorization, surface=surface) == epoch

    with pytest.raises(KernelContractError) as raised:
        DeploymentActivationCoordinator(gate).activate(
            composition=composition,
            release_identity=release,
            request=_request(composition, release),
        )
    assert raised.value.code == "deployment_hot_activation_forbidden"


def test_restart_reactivates_exact_persisted_epoch_after_fresh_read_only_proofs() -> None:
    composition, release, _ = activated_composition()
    persisted = DeploymentActivationCoordinator(DeploymentActivationGate()).activate(
        composition=composition,
        release_identity=release,
        request=_request(composition, release),
    )
    restart_gate = DeploymentActivationGate()

    observed = DeploymentActivationCoordinator(restart_gate).reactivate_persisted(
        composition=composition,
        persisted_epoch=persisted,
        expected_wheel_set_digest=digest("wheels"),
        verifications=_proofs(composition, release),
    )

    assert observed is persisted
    assert restart_gate.active_epoch is persisted


def test_restart_rejects_persisted_epoch_or_current_wheel_drift() -> None:
    composition, release, _ = activated_composition()
    persisted = DeploymentActivationCoordinator(DeploymentActivationGate()).activate(
        composition=composition,
        release_identity=release,
        request=_request(composition, release),
    )
    drifted_epoch = type(persisted).create(
        epoch_id=persisted.epoch_id,
        sequence=persisted.sequence,
        distribution_id=persisted.distribution_id,
        kernel_manifest_digest=persisted.kernel_manifest_digest,
        distribution_manifest_digest=digest("other-distribution"),
        composition_document_digest=persisted.composition_document_digest,
        composition_activation_digest=persisted.composition_activation_digest,
        driver_bundle_digest=persisted.driver_bundle_digest,
        http_route_catalog_digest=persisted.http_route_catalog_digest,
        contribution_catalogs_digest=persisted.contribution_catalogs_digest,
        release_identity=persisted.release_identity,
        schema_verification_digest=persisted.schema_verification_digest,
        wheel_verification_digest=persisted.wheel_verification_digest,
        activated_by_actor_id=persisted.activated_by_actor_id,
        activated_at=persisted.activated_at,
    )

    gate = DeploymentActivationGate()
    with pytest.raises(KernelContractError) as raised:
        DeploymentActivationCoordinator(gate).reactivate_persisted(
            composition=composition,
            persisted_epoch=drifted_epoch,
            expected_wheel_set_digest=digest("wheels"),
            verifications=_proofs(composition, release),
        )
    assert raised.value.code == "deployment_persisted_epoch_drift"
    assert gate.active_epoch is None

    wheel_proofs = tuple(
        ReadOnlyDeploymentVerification.create(
            verification_id=proof.verification_id,
            verification_kind=proof.verification_kind,
            verifier_id=proof.verifier_id,
            expected_digest=proof.expected_digest,
            observed_digest=(
                digest("unexpected-installed-wheels")
                if proof.verification_kind
                is DeploymentVerificationKind.INSTALLED_WHEELS
                else proof.observed_digest
            ),
            verified_at=proof.verified_at,
        )
        for proof in _proofs(composition, release)
    )
    with pytest.raises(KernelContractError) as raised:
        DeploymentActivationCoordinator(gate).reactivate_persisted(
            composition=composition,
            persisted_epoch=persisted,
            expected_wheel_set_digest=digest("wheels"),
            verifications=wheel_proofs,
        )
    assert raised.value.code == "deployment_verification_failed"
    assert gate.active_epoch is None


def test_release_catalog_drift_blocks_activation() -> None:
    composition, release, _ = activated_composition()
    gate = DeploymentActivationGate()
    drifted = replace(release, projection_catalog_digest=digest("wrong-projection"))

    with pytest.raises(KernelContractError) as raised:
        DeploymentActivationCoordinator(gate).activate(
            composition=composition,
            release_identity=drifted,
            request=_request(composition, drifted),
        )

    assert raised.value.code == "deployment_release_identity_drift"
    assert raised.value.details["drifted_fields"] == ["projection_catalog_digest"]
    assert gate.active_epoch is None
