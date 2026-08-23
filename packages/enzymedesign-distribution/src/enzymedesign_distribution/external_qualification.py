from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Iterable

from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import ExternalQualificationProfileRef
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import ExternalQualificationUnit
from openzyme_contracts import QualificationCredentialLocator
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ComponentIdentity
from openzyme_kernel import ActivatedDistributionComposition

from .composition import activate_enzymedesign_composition


BASE_PROFILE = "base"
EXTERNAL_QUALIFICATION_CREDENTIAL_SLOTS = (
    "git.primary",
    "hpc.slurm.primary",
    "hpc.ssh.primary",
    "llm.primary",
    "research.tavily.primary",
)
EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS: Mapping[str, str | None] = {
    "git.primary": None,
    "hpc.slurm.primary": "credential.hpc.diannan.qualification",
    "hpc.ssh.primary": "credential.hpc.diannan.qualification",
    "llm.primary": "credential.llm.micuapi.qualification",
    "research.tavily.primary": "credential.tavily.qualification",
}
OPTIONAL_PROFILES = (
    "alphafold",
    "docking",
    "hmmer",
    "hpc-primary",
    "research-provider",
)
REQUIRED_NEGATIVE_TESTS = (
    "auth.failure",
    "operation.mismatch",
    "response.loss",
    "schema.mismatch",
    "timeout.before.effect",
)


@dataclass(frozen=True, slots=True)
class _QualificationBlueprint:
    component_id: str
    capability_id: str
    operation: str
    route_id: str
    subject_kind: ExternalQualificationSubjectKind
    subject_id: str
    profile_id: str
    qualification_spec_id: str
    credential_slot_id: str | None = None


def _blueprints() -> tuple[_QualificationBlueprint, ...]:
    provider = ExternalQualificationSubjectKind.PROVIDER
    target = ExternalQualificationSubjectKind.TARGET
    rows: list[_QualificationBlueprint] = [
        _QualificationBlueprint(
            "openzyme.runtime.llm",
            "openzyme.agent.turn",
            "bounded-turn",
            "openzyme.runtime.llm.turn@1",
            provider,
            "provider.llm.primary",
            BASE_PROFILE,
            "openzyme.runtime.llm.preflight@1",
            "llm.primary",
        ),
        *(
            _QualificationBlueprint(
                "openzyme.workspace.git.lfs",
                "openzyme.workspace.revision",
                operation,
                f"openzyme.workspace.git.lfs.{operation}@1",
                target,
                "git.primary",
                BASE_PROFILE,
                "openzyme.workspace.git.lfs.preflight@1",
                "git.primary",
            )
            for operation in (
                "clone",
                "checkpoint",
                "publish",
                "lfs-fetch",
                "response-loss-reconcile",
            )
        ),
        *(
            _QualificationBlueprint(
                "openzyme.process.podman",
                "openzyme.workspace.process",
                operation,
                f"openzyme.process.podman.{operation}@1",
                target,
                "local.podman",
                BASE_PROFILE,
                "openzyme.process.podman.preflight@1",
            )
            for operation in (
                "container-start",
                "mount",
                "create",
                "read",
                "update",
                "delete",
                "exec",
                "timeout",
                "retire",
            )
        ),
        *(
            _QualificationBlueprint(
                "enzymedesign.bio-provider-http",
                f"enzymedesign.provider.{provider_name}",
                "read-smoke",
                f"enzymedesign.bio-provider-http.{provider_name}.read@1",
                provider,
                f"provider.{provider_name}.public",
                BASE_PROFILE,
                f"enzymedesign.bio-provider-http.{provider_name}.preflight@1",
            )
            for provider_name in ("uniprot", "rcsb", "interpro")
        ),
        _QualificationBlueprint(
            "openzyme.research.tavily",
            "openzyme.research.provider",
            "bounded-query",
            "openzyme.research.tavily.query@1",
            provider,
            "provider.tavily.primary",
            "research-provider",
            "openzyme.research.tavily.preflight@1",
            "research.tavily.primary",
        ),
        *(
            _QualificationBlueprint(
                "openzyme.hpc.ssh",
                "openzyme.hpc.workspace",
                operation,
                f"openzyme.hpc.ssh.{operation}@1",
                target,
                "hpc-primary",
                "hpc-primary",
                "openzyme.hpc.ssh.preflight@1",
                "hpc.ssh.primary",
            )
            for operation in (
                "helper-identity",
                "version",
                "create",
                "read",
                "update",
                "delete",
                "exec",
                "response-loss-reconcile",
            )
        ),
        *(
            _QualificationBlueprint(
                "openzyme.hpc.slurm",
                "openzyme.execution.revision-job",
                operation,
                f"openzyme.hpc.slurm.{operation}@1",
                target,
                "hpc-primary",
                "hpc-primary",
                "openzyme.hpc.slurm.preflight@1",
                "hpc.slurm.primary",
            )
            for operation in ("submit", "observe", "cancel", "reconcile")
        ),
    ]
    for component_id, route_kind in (
        ("enzymedesign.hmmer.local", "local"),
        ("enzymedesign.hmmer.hpc", "hpc-primary"),
    ):
        rows.extend(
            _QualificationBlueprint(
                component_id,
                "software.hmmer",
                operation,
                f"enzymedesign.hmmer.{route_kind}.{operation}@1",
                target,
                route_kind,
                "hmmer",
                "enzymedesign.hmmer.qualification@1",
                "hpc.ssh.primary" if route_kind == "hpc-primary" else None,
            )
            for operation in ("hmmbuild", "hmmsearch")
        )
    for component_id, route_kind in (
        ("enzymedesign.vina.local", "local"),
        ("enzymedesign.vina.hpc", "hpc-primary"),
    ):
        rows.append(
            _QualificationBlueprint(
                component_id,
                "software.autodock-vina",
                "dock",
                f"enzymedesign.vina.{route_kind}.dock@1",
                target,
                route_kind,
                "docking",
                "enzymedesign.vina.qualification@1",
                "hpc.ssh.primary" if route_kind == "hpc-primary" else None,
            )
        )
    for component_id, route_kind in (
        ("enzymedesign.fpocket.local", "local"),
        ("enzymedesign.fpocket.hpc", "hpc-primary"),
    ):
        rows.append(
            _QualificationBlueprint(
                component_id,
                "software.fpocket",
                "detect",
                f"enzymedesign.fpocket.{route_kind}.detect@1",
                target,
                route_kind,
                "docking",
                "enzymedesign.fpocket.qualification@1",
                "hpc.ssh.primary" if route_kind == "hpc-primary" else None,
            )
        )
    for software, spec_id, operations in (
        (
            "rdkit",
            "enzymedesign.docking.preprocess.rdkit@1",
            ("smiles_to_3d",),
        ),
        (
            "meeko",
            "enzymedesign.docking.preprocess.meeko@1",
            ("prepare_ligand",),
        ),
        (
            "openbabel",
            "enzymedesign.docking.preprocess.openbabel@1",
            ("convert_format", "prepare_ligand", "prepare_receptor"),
        ),
    ):
        rows.extend(
            _QualificationBlueprint(
                "enzymedesign.docking.preprocess",
                f"software.{software}",
                operation,
                f"enzymedesign.docking.preprocess.{software}.{operation}@1",
                target,
                "local.podman",
                "docking",
                spec_id,
            )
            for operation in operations
        )
    rows.append(
        _QualificationBlueprint(
            "enzymedesign.alphafold.hpc",
            "software.alphafold3",
            "predict",
            "enzymedesign.alphafold.hpc.predict@1",
            target,
            "hpc-primary",
            "alphafold",
            "enzymedesign.alphafold.qualification@1",
            "hpc.ssh.primary",
        )
    )
    return tuple(rows)


def _component_identities(
    composition: ActivatedDistributionComposition,
) -> dict[str, tuple[ComponentIdentity, str, str]]:
    """Return component identity, source manifest digest and config digest source."""

    observed: dict[str, tuple[ComponentIdentity, str, str]] = {}
    for binding in composition.adapters:
        manifest = binding.manifest
        if (
            binding.selection.adapter_component_id != manifest.identity.component_id
            or binding.selection.manifest_digest != manifest.manifest_digest
        ):
            raise ExternalQualificationError(
                "qualification_catalog_component_identity_drift",
                "Adapter selection and manifest identity differ",
            )
        observed[manifest.identity.component_id] = (
            manifest.identity,
            manifest.manifest_digest,
            manifest.configuration_schema_digest,
        )
    for activation in composition.plugins.activations:
        manifest = activation.manifest
        if manifest is None:
            continue
        if (
            activation.selection.plugin_id != manifest.identity.component_id
            or activation.selection.manifest_digest != manifest.manifest_digest
        ):
            raise ExternalQualificationError(
                "qualification_catalog_component_identity_drift",
                "Plugin selection and manifest identity differ",
            )
        observed[manifest.identity.component_id] = (
            manifest.identity,
            manifest.manifest_digest,
            manifest.configuration_schema_digest or manifest.manifest_digest,
        )
    for binding in composition.drivers:
        manifest = binding.manifest
        if (
            binding.selection.driver_id != manifest.identity.component_id
            or binding.selection.manifest_digest != manifest.manifest_digest
        ):
            raise ExternalQualificationError(
                "qualification_catalog_component_identity_drift",
                "Driver selection and manifest identity differ",
            )
        observed[manifest.identity.component_id] = (
            manifest.identity,
            manifest.manifest_digest,
            canonical_sha256_digest(
                {
                    "workload_contract_digest": manifest.workload_contract_digest,
                    "result_contract_digest": manifest.result_contract_digest,
                    "route_kind": manifest.route_kind,
                }
            ),
        )
    return observed


def _expected_external_component_ids(
    composition: ActivatedDistributionComposition,
) -> set[str]:
    adapter_ids = {
        item.manifest.identity.component_id
        for item in composition.adapters
        if item.manifest.identity.component_id != "openzyme.store.sqlite"
    }
    driver_ids = {
        item.manifest.identity.component_id
        for item in composition.drivers
        if item.manifest.identity.component_id != "enzymedesign.aox.executor"
    }
    plugin_ids = {
        activation.plugin_id
        for activation in composition.plugins.activations
        if activation.plugin_id == "enzymedesign.docking.preprocess"
        and activation.manifest is not None
    }
    return adapter_ids | driver_ids | plugin_ids


def build_enzymedesign_external_qualification_catalog(
    composition: ActivatedDistributionComposition | None = None,
    *,
    credential_locator_ids: Mapping[str, str | None] | None = None,
) -> tuple[tuple[str, ExternalQualificationUnit], ...]:
    exact = activate_enzymedesign_composition() if composition is None else composition
    identities = _component_identities(exact)
    qualification_specs = {
        spec.qualification_spec_id: spec
        for activation in exact.plugins.activations
        if activation.manifest is not None
        for spec in activation.manifest.qualification_specs
    }
    blueprints = _blueprints()
    if credential_locator_ids is not None and set(credential_locator_ids) != set(
        EXTERNAL_QUALIFICATION_CREDENTIAL_SLOTS
    ):
        raise ExternalQualificationError(
            "qualification_credential_slot_coverage_mismatch",
            "exact qualification credential mapping must cover every declared slot",
        )
    covered = {item.component_id for item in blueprints}
    expected = _expected_external_component_ids(exact)
    if covered != expected:
        raise ExternalQualificationError(
            "qualification_catalog_component_coverage_gap",
            "external qualification catalog differs from exact selected components: "
            f"missing={sorted(expected - covered)!r}; "
            f"unexpected={sorted(covered - expected)!r}",
        )
    catalog: list[tuple[str, ExternalQualificationUnit]] = []
    for blueprint in blueprints:
        try:
            identity, source_digest, config_source_digest = identities[
                blueprint.component_id
            ]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_catalog_component_missing",
                f"selected component is unavailable: {blueprint.component_id}",
            ) from exc
        configuration_digest = canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_non_live_qualification_config@1",
                "configuration_schema_or_driver_digest": config_source_digest,
                "route_id": blueprint.route_id,
                "subject_kind": blueprint.subject_kind.value,
                "subject_id": blueprint.subject_id,
                "external_effects_real": False,
            }
        )
        declared_spec = qualification_specs.get(blueprint.qualification_spec_id)
        if declared_spec is not None:
            if (
                declared_spec.capability_id != blueprint.capability_id
                or blueprint.operation not in declared_spec.expected_operations
            ):
                raise ExternalQualificationError(
                    "qualification_catalog_spec_operation_drift",
                    "qualification blueprint differs from the selected Plugin spec",
                )
            qualification_spec_digest = declared_spec.qualification_spec_digest
            expected_schema_digest = canonical_sha256_digest(
                declared_spec.to_dict()["expected_result_schema"]
            )
        else:
            if ".preflight@" not in blueprint.qualification_spec_id:
                raise ExternalQualificationError(
                    "qualification_catalog_spec_missing",
                    "qualification blueprint references no selected Plugin spec",
                )
            expected_schema_digest = canonical_sha256_digest(
                {
                    "schema_version": "enzymedesign_qualification_probe_result@1",
                    "component_id": blueprint.component_id,
                    "capability_id": blueprint.capability_id,
                    "operation": blueprint.operation,
                    "required": [
                        "operation",
                        "subject_id",
                        "deterministic_result",
                    ],
                }
            )
            qualification_spec_digest = canonical_sha256_digest(
                {
                    "qualification_spec_id": blueprint.qualification_spec_id,
                    "component_manifest_digest": source_digest,
                    "operation": blueprint.operation,
                    "expected_result_schema_digest": expected_schema_digest,
                }
            )
        locator = None
        if blueprint.credential_slot_id is not None:
            locator_id = (
                f"nonlive.locator.{blueprint.credential_slot_id}"
                if credential_locator_ids is None
                else credential_locator_ids[blueprint.credential_slot_id]
            )
            if locator_id is not None:
                locator = QualificationCredentialLocator(
                    credential_slot_id=blueprint.credential_slot_id,
                    credential_locator_id=locator_id,
                    scope_digest=canonical_sha256_digest(
                        {
                            "credential_slot_id": blueprint.credential_slot_id,
                            "subject_id": blueprint.subject_id,
                            "operation": blueprint.operation,
                            "material_resolution_allowed": (
                                credential_locator_ids is not None
                            ),
                            **(
                                {"credential_locator_id": locator_id}
                                if credential_locator_ids is not None
                                else {}
                            ),
                        }
                    ),
                )
        unit = ExternalQualificationUnit.create(
            component_id=identity.component_id,
            capability_id=blueprint.capability_id,
            operation=blueprint.operation,
            route_id=blueprint.route_id,
            subject_kind=blueprint.subject_kind,
            subject_id=blueprint.subject_id,
            source_digest=source_digest,
            build_digest=identity.build_digest,
            configuration_digest=configuration_digest,
            contract_digest=identity.contract_digest,
            qualification_spec_id=blueprint.qualification_spec_id,
            qualification_spec_digest=qualification_spec_digest,
            validator_id=f"{blueprint.qualification_spec_id}.validator",
            expected_result_schema_digest=expected_schema_digest,
            credential_locator=locator,
        )
        catalog.append((blueprint.profile_id, unit))
    keys = [
        (
            unit.capability_id,
            unit.operation,
            unit.route_id,
            unit.subject_kind.value,
            unit.subject_id,
        )
        for _, unit in catalog
    ]
    if len(keys) != len(set(keys)):
        raise ExternalQualificationError(
            "qualification_unit_identity_collision",
            "external qualification catalog contains colliding units",
        )
    return tuple(sorted(catalog, key=lambda item: (item[0], item[1].unit_digest)))


def build_enzymedesign_external_qualification_plan(
    *,
    plan_id: str,
    created_at: str,
    enabled_optional_profiles: Iterable[str] = (),
    composition: ActivatedDistributionComposition | None = None,
    credential_locator_ids: Mapping[str, str | None] | None = None,
) -> ExternalQualificationPlan:
    exact = activate_enzymedesign_composition() if composition is None else composition
    requested = tuple(enabled_optional_profiles)
    optional = tuple(sorted(set(requested)))
    if len(optional) != len(requested):
        raise ExternalQualificationError(
            "qualification_profile_duplicate",
            "enabled external qualification profiles must be unique",
        )
    unknown = sorted(set(optional).difference(OPTIONAL_PROFILES))
    if unknown:
        raise ExternalQualificationError(
            "qualification_profile_unknown",
            f"unknown external qualification profiles: {unknown!r}",
        )
    enabled = (BASE_PROFILE, *optional)
    catalog = build_enzymedesign_external_qualification_catalog(
        exact,
        credential_locator_ids=credential_locator_ids,
    )
    selected = tuple((profile, unit) for profile, unit in catalog if profile in enabled)
    profiles = tuple(
        ExternalQualificationProfileRef(
            profile_id=profile_id,
            required=profile_id == BASE_PROFILE,
            unit_digests=tuple(
                unit.unit_digest
                for profile, unit in selected
                if profile == profile_id
            ),
            required_negative_tests=REQUIRED_NEGATIVE_TESTS,
        )
        for profile_id in enabled
    )
    return ExternalQualificationPlan.create(
        plan_id=plan_id,
        distribution_id=exact.distribution_id,
        distribution_digest=exact.activation_digest,
        enabled_profiles=enabled,
        profiles=profiles,
        units=tuple(unit for _, unit in selected),
        created_at=created_at,
        live_allowed=False,
    )


def external_qualification_catalog_digest(
    composition: ActivatedDistributionComposition | None = None,
) -> str:
    return canonical_sha256_digest(
        [
            {"profile_id": profile_id, "unit": unit.to_dict()}
            for profile_id, unit in build_enzymedesign_external_qualification_catalog(
                composition
            )
        ]
    )


__all__ = [
    "BASE_PROFILE",
    "EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS",
    "EXTERNAL_QUALIFICATION_CREDENTIAL_SLOTS",
    "OPTIONAL_PROFILES",
    "REQUIRED_NEGATIVE_TESTS",
    "build_enzymedesign_external_qualification_catalog",
    "build_enzymedesign_external_qualification_plan",
    "external_qualification_catalog_digest",
]
