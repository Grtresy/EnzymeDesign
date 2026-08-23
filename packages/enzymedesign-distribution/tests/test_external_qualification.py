from dataclasses import replace

import pytest

from enzymedesign_distribution import BASE_PROFILE
from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import build_enzymedesign_external_qualification_catalog
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import external_qualification_catalog_digest
from enzymedesign_distribution.composition import activate_enzymedesign_composition
from openzyme_contracts import ExternalQualificationError


CREATED_AT = "2026-08-22T00:00:00+00:00"


def test_catalog_closes_exact_selected_external_components_and_operations() -> None:
    catalog = build_enzymedesign_external_qualification_catalog()

    assert len(catalog) == 45
    assert {profile for profile, _ in catalog} == {BASE_PROFILE, *OPTIONAL_PROFILES}
    assert len({unit.unit_digest for _, unit in catalog}) == len(catalog)
    assert {
        unit.subject_version_spec
        for _, unit in catalog
        if unit.capability_id == "software.autodock-vina"
    } == {">=1.2,<2"}
    assert {
        "openzyme.runtime.llm",
        "openzyme.research.tavily",
        "enzymedesign.bio-provider-http",
        "openzyme.workspace.git.lfs",
        "openzyme.process.podman",
        "openzyme.hpc.ssh",
        "openzyme.hpc.slurm",
        "enzymedesign.hmmer.local",
        "enzymedesign.hmmer.hpc",
        "enzymedesign.vina.local",
        "enzymedesign.vina.hpc",
        "enzymedesign.fpocket.local",
        "enzymedesign.fpocket.hpc",
        "enzymedesign.alphafold.hpc",
        "enzymedesign.docking.preprocess",
    } == {unit.component_id for _, unit in catalog}
    assert external_qualification_catalog_digest() == (
        "sha256:9681536f47d5db9ce1a8acbccc7c11d2dd8b0b41a5c2fc13d5cc2dabdaf10912"
    )


def test_base_and_explicit_optional_profiles_form_exact_plan_closure() -> None:
    base = build_enzymedesign_external_qualification_plan(
        plan_id="readiness.plan.base",
        created_at=CREATED_AT,
    )
    assert base.enabled_profiles == (BASE_PROFILE,)
    assert len(base.units) == 18
    assert base.live_allowed is False

    selected = build_enzymedesign_external_qualification_plan(
        plan_id="readiness.plan.selected",
        created_at=CREATED_AT,
        enabled_optional_profiles=("research-provider", "hmmer"),
    )
    assert selected.enabled_profiles == (BASE_PROFILE, "hmmer", "research-provider")
    assert len(selected.units) == 23


@pytest.mark.parametrize(
    ("profiles", "error_code"),
    [
        (("unknown",), "qualification_profile_unknown"),
        (("hmmer", "hmmer"), "qualification_profile_duplicate"),
    ],
)
def test_profile_request_fails_closed(
    profiles: tuple[str, ...],
    error_code: str,
) -> None:
    with pytest.raises(ExternalQualificationError) as captured:
        build_enzymedesign_external_qualification_plan(
            plan_id="readiness.plan.invalid",
            created_at=CREATED_AT,
            enabled_optional_profiles=profiles,
        )
    assert captured.value.error_code == error_code


def test_catalog_rejects_manifest_identity_drift() -> None:
    composition = activate_enzymedesign_composition()
    first = composition.adapters[0]
    drifted_identity = replace(
        first.manifest.identity,
        build_digest="sha256:" + "f" * 64,
    )
    drifted_binding = replace(
        first,
        manifest=replace(first.manifest, identity=drifted_identity),
    )
    drifted_composition = replace(
        composition,
        adapters=(drifted_binding, *composition.adapters[1:]),
    )

    with pytest.raises(ExternalQualificationError) as captured:
        build_enzymedesign_external_qualification_catalog(drifted_composition)
    assert captured.value.error_code == "qualification_catalog_component_identity_drift"
