from __future__ import annotations

from dataclasses import dataclass

from enzymedesign_alphafold import AlphaFoldPluginRuntimeSurfaces
from enzymedesign_aox import AoxPluginRuntimeSurfaces
from enzymedesign_bio_providers import BioProviderCapabilityRouteRuntime
from enzymedesign_docking_preprocess import PreprocessPluginRuntimeSurfaces
from enzymedesign_hmmer import HmmerPluginRuntimeSurfaces
from enzymedesign_sequence_toolpack import SequenceToolRuntime
from enzymedesign_structure import StructurePluginRuntimeSurfaces
from enzymedesign_vina import VinaPluginRuntimeSurfaces
from openzyme_compute import ComputePluginRuntimeSurfaces
from openzyme_hpc import HpcPluginRuntimeSurfaces
from openzyme_kernel import ActivatedDistributionComposition
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_kernel import PluginRuntimeContributions
from openzyme_kernel import mount_extension_surfaces
from openzyme_reporting import ReportingPluginRuntimeSurfaces
from openzyme_research import ResearchPluginRuntimeSurfaces
from openzyme_science import SciencePluginRuntimeSurfaces

from .composition import EnzymeDesignDeploymentStartup


@dataclass(frozen=True, slots=True)
class EnzymeDesignPluginRuntimeSurfaceSet:
    """Typed runtime objects for every manifest-contributing EnzymeDesign Plugin."""

    compute: ComputePluginRuntimeSurfaces
    hpc: HpcPluginRuntimeSurfaces
    reporting: ReportingPluginRuntimeSurfaces
    research: ResearchPluginRuntimeSurfaces
    science: SciencePluginRuntimeSurfaces
    bio_provider_routes: tuple[BioProviderCapabilityRouteRuntime, ...]
    hmmer: HmmerPluginRuntimeSurfaces
    sequence_tools: tuple[SequenceToolRuntime, ...]
    aox: AoxPluginRuntimeSurfaces
    alphafold: AlphaFoldPluginRuntimeSurfaces
    preprocess: PreprocessPluginRuntimeSurfaces
    structure: StructurePluginRuntimeSurfaces
    vina: VinaPluginRuntimeSurfaces


def build_enzymedesign_runtime_bundles(
    *,
    composition: ActivatedDistributionComposition,
    surfaces: EnzymeDesignPluginRuntimeSurfaceSet,
) -> tuple[PluginRuntimeContributions, ...]:
    """Translate typed Plugin-owned surfaces into exact Kernel mount bundles."""

    manifest_digests = {
        manifest.identity.component_id: manifest.manifest_digest
        for manifest in composition.plugins.contributing_manifests
    }

    def bundle(
        plugin_id: str,
        *,
        tools=(),
        capability_routes=(),
        http_routes=(),
        projections=(),
        workers=(),
        finish_validators=(),
        transaction_participants=(),
    ) -> PluginRuntimeContributions:
        try:
            manifest_digest = manifest_digests[plugin_id]
        except KeyError as exc:
            raise ValueError(
                f"runtime surfaces were supplied for non-contributing Plugin {plugin_id}"
            ) from exc
        return PluginRuntimeContributions(
            owner_plugin_id=plugin_id,
            manifest_digest=manifest_digest,
            tools=tuple(tools),
            capability_routes=tuple(capability_routes),
            http_routes=tuple(http_routes),
            projections=tuple(projections),
            workers=tuple(workers),
            finish_validators=tuple(finish_validators),
            transaction_participants=tuple(transaction_participants),
        )

    return (
        bundle(
            "enzymedesign.alphafold",
            tools=surfaces.alphafold.tools,
            capability_routes=surfaces.alphafold.capability_routes,
        ),
        bundle(
            "enzymedesign.aox",
            capability_routes=surfaces.aox.capability_routes,
        ),
        bundle(
            "enzymedesign.bio-providers",
            capability_routes=surfaces.bio_provider_routes,
        ),
        bundle(
            "enzymedesign.docking.preprocess",
            tools=surfaces.preprocess.tools,
        ),
        bundle(
            "enzymedesign.hmmer",
            tools=surfaces.hmmer.tools,
            capability_routes=surfaces.hmmer.capability_routes,
        ),
        bundle(
            "enzymedesign.sequence.toolpack",
            tools=surfaces.sequence_tools,
        ),
        bundle(
            "enzymedesign.structure",
            tools=surfaces.structure.tools,
            capability_routes=surfaces.structure.capability_routes,
        ),
        bundle(
            "enzymedesign.vina",
            tools=surfaces.vina.tools,
            capability_routes=surfaces.vina.capability_routes,
        ),
        bundle(
            "openzyme.compute",
            tools=surfaces.compute.tools,
            projections=surfaces.compute.projections,
            workers=surfaces.compute.workers,
            transaction_participants=surfaces.compute.transaction_participants,
        ),
        bundle(
            "openzyme.hpc",
            tools=surfaces.hpc.tools,
            capability_routes=surfaces.hpc.capability_routes,
            projections=surfaces.hpc.projections,
            workers=surfaces.hpc.workers,
        ),
        bundle(
            "openzyme.reporting",
            tools=surfaces.reporting.tools,
            http_routes=surfaces.reporting.http_routes,
            projections=surfaces.reporting.projections,
            workers=surfaces.reporting.workers,
            finish_validators=surfaces.reporting.finish_validators,
            transaction_participants=surfaces.reporting.transaction_participants,
        ),
        bundle(
            "openzyme.research",
            tools=surfaces.research.tools,
            projections=surfaces.research.projections,
            workers=surfaces.research.workers,
        ),
        bundle(
            "openzyme.science",
            tools=surfaces.science.tools,
            http_routes=surfaces.science.http_routes,
            projections=surfaces.science.projections,
            workers=surfaces.science.workers,
            finish_validators=surfaces.science.finish_validators,
            transaction_participants=surfaces.science.transaction_participants,
        ),
    )


def mount_enzymedesign_extension_surfaces(
    *,
    startup: EnzymeDesignDeploymentStartup,
    composition: ActivatedDistributionComposition,
    surfaces: EnzymeDesignPluginRuntimeSurfaceSet,
) -> MountedExtensionSurfaces:
    """Mount the exact product surfaces after the read-only startup gate is active."""

    return mount_extension_surfaces(
        gate=startup.gate,
        composition=composition,
        runtime_bundles=build_enzymedesign_runtime_bundles(
            composition=composition,
            surfaces=surfaces,
        ),
    )


__all__ = [
    "EnzymeDesignPluginRuntimeSurfaceSet",
    "build_enzymedesign_runtime_bundles",
    "mount_enzymedesign_extension_surfaces",
]
