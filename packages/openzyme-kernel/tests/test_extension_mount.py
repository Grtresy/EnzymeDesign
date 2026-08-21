from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_kernel import DeploymentActivationGate
from openzyme_kernel import KernelContractError
from openzyme_kernel import PluginRuntimeContributions
from openzyme_kernel import mount_extension_surfaces

from composition_test_support import activate_gate
from composition_test_support import activated_composition


@dataclass(frozen=True)
class FakeToolRuntime:
    owner_plugin_id: str
    runtime_id: str
    contract: object

    def invoke(self, invocation: object) -> object:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeCapabilityRouteRuntime:
    route_id: str
    owner_plugin_id: str
    driver_id: str | None

    def invoke(self, invocation: object) -> object:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeHttpRouteRuntime:
    route_id: str
    owner_plugin_id: str
    method: str
    path: str
    contract_digest: str

    def invoke(self, invocation: object) -> object:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeProjection:
    section_id: str
    section_contract_digest: str

    def project(self, request: object) -> object:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeWorker:
    worker_id: str

    def claim(self, request: object) -> tuple:
        return ()

    def run(self, claim: object) -> object:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeValidator:
    validator_id: str

    def validate(self, context: object, task: object, evidence_refs: tuple) -> object:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeParticipant:
    participant_id: str
    state_namespace: str

    def prepare(self, command: object, state: object) -> object:
        raise NotImplementedError

    def apply(self, plan: object, state: object) -> object:
        raise NotImplementedError


def _bundle(plugin: object) -> PluginRuntimeContributions:
    return PluginRuntimeContributions(
        owner_plugin_id=plugin.identity.component_id,
        manifest_digest=plugin.manifest_digest,
        tools=(
            FakeToolRuntime(
                owner_plugin_id=plugin.identity.component_id,
                runtime_id=plugin.tools[0].runtime_id,
                contract=plugin.tools[0].contract,
            ),
        ),
        capability_routes=(
            FakeCapabilityRouteRuntime(
                route_id=plugin.routes[0].route_id,
                owner_plugin_id=plugin.identity.component_id,
                driver_id=plugin.routes[0].driver_id,
            ),
        ),
        http_routes=(
            FakeHttpRouteRuntime(
                route_id=plugin.http_routes[0].route_id,
                owner_plugin_id=plugin.identity.component_id,
                method=plugin.http_routes[0].method.value,
                path=plugin.http_routes[0].path,
                contract_digest=plugin.http_routes[0].contract_digest,
            ),
        ),
        projections=(
            FakeProjection(
                section_id=plugin.projections[0].contribution_id,
                section_contract_digest=plugin.projections[0].contract_digest,
            ),
        ),
        workers=(FakeWorker(plugin.workers[0].contribution_id),),
        finish_validators=(
            FakeValidator(plugin.finish_validators[0].contribution_id),
        ),
        transaction_participants=(
            FakeParticipant(
                plugin.transaction_participants[0].contribution_id,
                plugin.state_namespace,
            ),
        ),
    )


def test_mount_is_atomic_and_exactly_matches_manifest_surfaces() -> None:
    composition, release, plugin = activated_composition()
    assert plugin is not None
    gate, epoch = activate_gate(composition, release)

    mounted = mount_extension_surfaces(
        gate=gate,
        composition=composition,
        runtime_bundles=(_bundle(plugin),),
    )

    assert mounted.epoch_id == epoch.epoch_id
    assert mounted.activation_digest == epoch.activation_digest
    assert [item[0] for item in mounted.tools] == ["test.plugin.run"]
    assert [item[0] for item in mounted.capability_routes] == [
        "test.plugin.local-route"
    ]
    assert [item[0] for item in mounted.http_routes] == ["test.plugin.http-route"]
    assert [item[0] for item in mounted.transaction_participants] == [
        "test.plugin.participant"
    ]


def test_missing_runtime_surface_rejects_whole_mount() -> None:
    composition, release, plugin = activated_composition()
    assert plugin is not None
    gate, _ = activate_gate(composition, release)
    bundle = _bundle(plugin)
    bundle = PluginRuntimeContributions(
        owner_plugin_id=bundle.owner_plugin_id,
        manifest_digest=bundle.manifest_digest,
        tools=bundle.tools,
        capability_routes=bundle.capability_routes,
        http_routes=bundle.http_routes,
        projections=bundle.projections,
        workers=(),
        finish_validators=bundle.finish_validators,
        transaction_participants=bundle.transaction_participants,
    )

    with pytest.raises(KernelContractError) as raised:
        mount_extension_surfaces(
            gate=gate,
            composition=composition,
            runtime_bundles=(bundle,),
        )

    assert raised.value.code == "plugin_runtime_surface_incomplete"
    assert raised.value.details["missing_ids"] == ["test.plugin.worker"]


def test_unselected_runtime_bundle_is_rejected_as_ambient_capability() -> None:
    composition, release, _ = activated_composition(include_plugin=False)
    gate, _ = activate_gate(composition, release)
    bundle = PluginRuntimeContributions(
        owner_plugin_id="ambient.plugin",
        manifest_digest="sha256:" + "1" * 64,
    )

    with pytest.raises(KernelContractError) as raised:
        mount_extension_surfaces(
            gate=gate,
            composition=composition,
            runtime_bundles=(bundle,),
        )

    assert raised.value.code == "runtime_bundle_unselected"


def test_driver_runtime_cannot_mount_on_another_route_or_plugin() -> None:
    composition, release, plugin = activated_composition()
    assert plugin is not None
    gate, _ = activate_gate(composition, release)
    bundle = _bundle(plugin)
    wrong_route = FakeCapabilityRouteRuntime(
        route_id=plugin.routes[0].route_id,
        owner_plugin_id=plugin.identity.component_id,
        driver_id="other.plugin.driver",
    )
    bundle = PluginRuntimeContributions(
        owner_plugin_id=bundle.owner_plugin_id,
        manifest_digest=bundle.manifest_digest,
        tools=bundle.tools,
        capability_routes=(wrong_route,),
        http_routes=bundle.http_routes,
        projections=bundle.projections,
        workers=bundle.workers,
        finish_validators=bundle.finish_validators,
        transaction_participants=bundle.transaction_participants,
    )

    with pytest.raises(KernelContractError) as raised:
        mount_extension_surfaces(
            gate=gate,
            composition=composition,
            runtime_bundles=(bundle,),
        )

    assert raised.value.code == "capability_route_runtime_drift"


def test_http_runtime_must_match_exact_declared_method_path_and_contract() -> None:
    composition, release, plugin = activated_composition()
    assert plugin is not None
    gate, _ = activate_gate(composition, release)
    bundle = _bundle(plugin)
    declared = plugin.http_routes[0]
    stale_http = FakeHttpRouteRuntime(
        route_id=declared.route_id,
        owner_plugin_id=plugin.identity.component_id,
        method=declared.method.value,
        path=declared.path,
        contract_digest="sha256:" + "9" * 64,
    )
    bundle = PluginRuntimeContributions(
        owner_plugin_id=bundle.owner_plugin_id,
        manifest_digest=bundle.manifest_digest,
        tools=bundle.tools,
        capability_routes=bundle.capability_routes,
        http_routes=(stale_http,),
        projections=bundle.projections,
        workers=bundle.workers,
        finish_validators=bundle.finish_validators,
        transaction_participants=bundle.transaction_participants,
    )

    with pytest.raises(KernelContractError) as raised:
        mount_extension_surfaces(
            gate=gate,
            composition=composition,
            runtime_bundles=(bundle,),
        )

    assert raised.value.code == "http_route_runtime_contract_drift"


def test_host_internal_runtime_object_is_rejected() -> None:
    composition, release, plugin = activated_composition()
    assert plugin is not None
    gate, _ = activate_gate(composition, release)
    bundle = _bundle(plugin)
    original_module = FakeToolRuntime.__module__
    FakeToolRuntime.__module__ = "openzyme_host_api.internal"
    try:
        with pytest.raises(KernelContractError) as raised:
            mount_extension_surfaces(
                gate=gate,
                composition=composition,
                runtime_bundles=(bundle,),
            )
    finally:
        FakeToolRuntime.__module__ = original_module

    assert raised.value.code == "plugin_runtime_forbidden_dependency"


def test_mount_requires_active_deployment() -> None:
    composition, _, plugin = activated_composition()
    assert plugin is not None

    with pytest.raises(KernelContractError) as raised:
        mount_extension_surfaces(
            gate=DeploymentActivationGate(),
            composition=composition,
            runtime_bundles=(_bundle(plugin),),
        )

    assert raised.value.code == "deployment_not_active"
