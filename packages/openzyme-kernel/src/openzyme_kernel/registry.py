from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import ExtensionCapabilityFact
from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import RouteRef
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import CapabilityCardinality
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import RouteContribution

from .catalog import DeclaredToolEntry
from .catalog import RouteCatalog
from .composition import ActivatedPluginComposition
from .errors import KernelContractError


@dataclass(frozen=True, slots=True)
class ExtensionBundleRegistry:
    extension_bundle_digest: str
    activation_epoch: int
    capability_facts: tuple[ExtensionCapabilityFact, ...]
    cardinalities: tuple[tuple[str, CapabilityCardinality], ...]
    registry_digest: str

    def digest_payload(self) -> dict[str, object]:
        return {
            "extension_bundle_digest": self.extension_bundle_digest,
            "activation_epoch": self.activation_epoch,
            "capability_facts": [fact.to_dict() for fact in self.capability_facts],
            "cardinalities": [
                [capability_id, cardinality.value]
                for capability_id, cardinality in self.cardinalities
            ],
        }

    def has_valid_digest(self) -> bool:
        return canonical_sha256_digest(self.digest_payload()) == self.registry_digest

    @classmethod
    def create(
        cls,
        composition: ActivatedPluginComposition,
        *,
        activation_epoch: int,
    ) -> ExtensionBundleRegistry:
        if activation_epoch < 1:
            raise ValueError("activation_epoch must be positive")
        facts: list[ExtensionCapabilityFact] = []
        cardinalities: dict[str, CapabilityCardinality] = {}
        for manifest in composition.contributing_manifests:
            for provision in manifest.provides:
                previous = cardinalities.get(provision.capability_id)
                if previous is not None and previous is not provision.cardinality:
                    raise KernelContractError(
                        "capability_cardinality_conflict",
                        "capability providers disagree about cardinality",
                        details={"capability_id": provision.capability_id},
                    )
                cardinalities[provision.capability_id] = provision.cardinality
                contract_id = (
                    f"{provision.capability_id}@{provision.contract_version}"
                )
                facts.append(
                    ExtensionCapabilityFact(
                        capability_id=provision.capability_id,
                        contract_id=contract_id,
                        provider_component_id=manifest.identity.component_id,
                        provider_version=manifest.identity.component_version,
                        contract_digest=canonical_sha256_digest(
                            {
                                "provider_contract_digest": (
                                    manifest.identity.contract_digest
                                ),
                                "provision": provision.to_dict(),
                            }
                        ),
                        activation_epoch=activation_epoch,
                        contract_version=provision.contract_version,
                        operations=provision.operations,
                    )
                )
        canonical_facts = tuple(
            sorted(
                facts,
                key=lambda fact: (
                    fact.capability_id,
                    fact.provider_component_id,
                    fact.contract_version,
                ),
            )
        )
        identities = [
            (fact.capability_id, fact.provider_component_id) for fact in canonical_facts
        ]
        if len(set(identities)) != len(identities):
            raise KernelContractError(
                "extension_capability_fact_collision",
                "extension capability facts are not unique by provider",
            )
        canonical_cardinalities = tuple(sorted(cardinalities.items()))
        payload = {
            "extension_bundle_digest": composition.extension_bundle_digest,
            "activation_epoch": activation_epoch,
            "capability_facts": [fact.to_dict() for fact in canonical_facts],
            "cardinalities": [
                [capability_id, cardinality.value]
                for capability_id, cardinality in canonical_cardinalities
            ],
        }
        return cls(
            extension_bundle_digest=composition.extension_bundle_digest,
            activation_epoch=activation_epoch,
            capability_facts=canonical_facts,
            cardinalities=canonical_cardinalities,
            registry_digest=canonical_sha256_digest(payload),
        )

    def facts_for(self, capability_id: str) -> tuple[ExtensionCapabilityFact, ...]:
        return tuple(
            fact
            for fact in self.capability_facts
            if fact.capability_id == capability_id
        )


@dataclass(frozen=True, slots=True)
class CapabilityRegistry:
    extension_bundle: ExtensionBundleRegistry
    binding: SessionCapabilityBindingRevision
    resource_facts: tuple[ResourceCapabilityFact, ...]
    declared_routes: tuple[RouteContribution, ...]
    route_refs: tuple[RouteRef, ...]
    registry_digest: str

    def digest_payload(self) -> dict[str, object]:
        return {
            "extension_registry_digest": self.extension_bundle.registry_digest,
            "binding_digest": self.binding.binding_digest,
            "resource_facts": [fact.to_dict() for fact in self.resource_facts],
            "declared_routes": [route.to_dict() for route in self.declared_routes],
            "route_refs": [route.to_dict() for route in self.route_refs],
        }

    def has_valid_digest(self) -> bool:
        return (
            self.extension_bundle.has_valid_digest()
            and canonical_sha256_digest(self.digest_payload()) == self.registry_digest
        )

    @classmethod
    def create(
        cls,
        *,
        extension_bundle: ExtensionBundleRegistry,
        binding: SessionCapabilityBindingRevision,
        route_catalog: RouteCatalog,
        resource_facts: tuple[ResourceCapabilityFact, ...],
    ) -> CapabilityRegistry:
        if not binding.has_valid_digest():
            raise KernelContractError(
                "capability_binding_digest_mismatch",
                "Session capability binding has an invalid digest",
            )
        if binding.extension_bundle_digest != extension_bundle.extension_bundle_digest:
            raise KernelContractError(
                "extension_bundle_binding_mismatch",
                "Session binding names another extension bundle",
            )
        if binding.route_catalog_digest != route_catalog.catalog_digest:
            raise KernelContractError(
                "route_catalog_binding_mismatch",
                "Session binding names another route catalog",
            )
        bindings = {
            item.target_id: item for item in binding.inventory_bindings
        }
        canonical_resources = tuple(
            sorted(
                resource_facts,
                key=lambda fact: (
                    fact.target_id,
                    fact.inventory_generation,
                    fact.capability_id,
                    fact.version or "",
                ),
            )
        )
        resource_identities = [
            (fact.target_id, fact.inventory_generation, fact.capability_id)
            for fact in canonical_resources
        ]
        if len(set(resource_identities)) != len(resource_identities):
            raise KernelContractError(
                "resource_capability_fact_collision",
                "resource facts are ambiguous within one inventory generation",
            )
        for fact in canonical_resources:
            inventory = bindings.get(fact.target_id)
            if inventory is None:
                raise KernelContractError(
                    "resource_fact_target_unbound",
                    "resource fact belongs to an inventory not adopted by the Session",
                    details={"target_id": fact.target_id},
                )
            if (
                inventory.inventory_generation != fact.inventory_generation
                or inventory.inventory_digest != fact.inventory_digest
            ):
                raise KernelContractError(
                    "resource_fact_inventory_mismatch",
                    "resource fact does not match the adopted inventory identity",
                    details={
                        "target_id": fact.target_id,
                        "capability_id": fact.capability_id,
                    },
                )

        route_refs: list[RouteRef] = []
        for route in route_catalog.routes:
            target_binding = (
                None if route.target_id is None else bindings.get(route.target_id)
            )
            if route.target_id is not None and target_binding is None:
                continue
            target_resources = tuple(
                fact
                for fact in canonical_resources
                if route.target_id is not None and fact.target_id == route.target_id
            )
            extension_proofs = tuple(
                fact
                for fact in extension_bundle.capability_facts
                if fact.capability_id in route.capability_ids
            )
            resource_proofs = tuple(
                fact
                for fact in target_resources
                if fact.capability_id in route.capability_ids
            )
            proven_capabilities = {
                fact.capability_id for fact in (*extension_proofs, *resource_proofs)
            }
            if not set(route.capability_ids).issubset(proven_capabilities):
                continue
            proof_digest = canonical_sha256_digest(
                {
                    "extension_facts": [fact.to_dict() for fact in extension_proofs],
                    "resource_facts": [fact.to_dict() for fact in resource_proofs],
                }
            )
            route_refs.append(
                RouteRef(
                    route_id=route.route_id,
                    provider_component_id=route.owner_component_id,
                    capability_ids=route.capability_ids,
                    route_digest=canonical_sha256_digest(
                        {
                            "route": route.to_dict(),
                            "binding_digest": binding.binding_digest,
                            "capability_proof_digest": proof_digest,
                        }
                    ),
                    capability_proof_digest=proof_digest,
                    target_id=route.target_id,
                    inventory_generation=(
                        None
                        if target_binding is None
                        else target_binding.inventory_generation
                    ),
                    inventory_digest=(
                        None if target_binding is None else target_binding.inventory_digest
                    ),
                    driver_id=route.driver_id,
                )
            )
        canonical_routes = tuple(sorted(route_refs, key=lambda route: route.route_id))
        payload = {
            "extension_registry_digest": extension_bundle.registry_digest,
            "binding_digest": binding.binding_digest,
            "resource_facts": [fact.to_dict() for fact in canonical_resources],
            "declared_routes": [route.to_dict() for route in route_catalog.routes],
            "route_refs": [route.to_dict() for route in canonical_routes],
        }
        return cls(
            extension_bundle=extension_bundle,
            binding=binding,
            resource_facts=canonical_resources,
            declared_routes=route_catalog.routes,
            route_refs=canonical_routes,
            registry_digest=canonical_sha256_digest(payload),
        )

    def extension_facts_for(
        self,
        capability_id: str,
    ) -> tuple[ExtensionCapabilityFact, ...]:
        return self.extension_bundle.facts_for(capability_id)

    def resource_facts_for(
        self,
        capability_id: str,
        *,
        target_id: str | None = None,
    ) -> tuple[ResourceCapabilityFact, ...]:
        return tuple(
            fact
            for fact in self.resource_facts
            if fact.capability_id == capability_id
            and (target_id is None or fact.target_id == target_id)
        )


@dataclass(frozen=True, slots=True)
class CapabilityResolutionBlocker:
    code: str
    capability_id: str
    requirement: str | None = None
    target_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "capability_id": self.capability_id,
            "requirement": self.requirement,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilityRouteResolution:
    extension_facts: tuple[ExtensionCapabilityFact, ...]
    resource_facts: tuple[ResourceCapabilityFact, ...]
    routes: tuple[RouteRef, ...]
    blockers: tuple[CapabilityResolutionBlocker, ...]


def _contract_matches(contract_version: str, contract_spec: str) -> bool:
    normalized_version = contract_version.removeprefix("@")
    normalized_spec = contract_spec.removeprefix("@")
    if normalized_spec in {"*", normalized_version}:
        return True
    if normalized_spec.endswith(".*"):
        return normalized_version.startswith(normalized_spec[:-1])
    return normalized_version.split(".", maxsplit=1)[0] == normalized_spec


def _version_tuple(value: str) -> tuple[int, ...] | None:
    parts = value.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def version_satisfies(version: str | None, version_spec: str | None) -> bool:
    if version_spec is None:
        return True
    if version is None:
        return False
    observed = _version_tuple(version)
    if observed is None:
        return False
    for raw_clause in version_spec.split(","):
        clause = raw_clause.strip()
        comparator = next(
            (item for item in (">=", "<=", "==", ">", "<") if clause.startswith(item)),
            "==",
        )
        expected_text = clause.removeprefix(comparator) if comparator != "==" else (
            clause.removeprefix("==")
        )
        expected = _version_tuple(expected_text)
        if expected is None:
            return False
        width = max(len(observed), len(expected))
        left = (*observed, *((0,) * (width - len(observed))))
        right = (*expected, *((0,) * (width - len(expected))))
        comparisons = {
            "==": left == right,
            ">=": left >= right,
            ">": left > right,
            "<=": left <= right,
            "<": left < right,
        }
        if not comparisons[comparator]:
            return False
    return True


def _extension_matches(
    requirement: CapabilityRequirement,
    registry: CapabilityRegistry,
) -> tuple[ExtensionCapabilityFact, ...]:
    return tuple(
        fact
        for fact in registry.extension_facts_for(requirement.capability_id)
        if _contract_matches(fact.contract_version, requirement.contract_spec)
        and set(requirement.operations).issubset(fact.operations)
    )


def _resource_matches(
    requirement: CapabilityRequirement,
    registry: CapabilityRegistry,
    *,
    target_id: str | None = None,
) -> tuple[ResourceCapabilityFact, ...]:
    return tuple(
        fact
        for fact in registry.resource_facts_for(
            requirement.capability_id,
            target_id=target_id,
        )
        if _contract_matches(fact.contract_version, requirement.contract_spec)
        and set(requirement.operations).issubset(fact.operations)
        and version_satisfies(fact.version, requirement.version_spec)
    )


def resolve_tool_capabilities(
    entry: DeclaredToolEntry,
    registry: CapabilityRegistry,
) -> CapabilityRouteResolution:
    extension_facts: list[ExtensionCapabilityFact] = []
    resource_facts: list[ResourceCapabilityFact] = []
    blockers: list[CapabilityResolutionBlocker] = []
    required_capability_ids = {
        requirement.capability_id for requirement in entry.requirements
    }
    for requirement in entry.requirements:
        if requirement.kind is CapabilityRequirementKind.EXTENSION:
            matches = _extension_matches(requirement, registry)
            if not matches:
                blockers.append(
                    CapabilityResolutionBlocker(
                        code="extension_requirement_unsatisfied",
                        capability_id=requirement.capability_id,
                        requirement=requirement.contract_spec,
                    )
                )
            extension_facts.extend(matches)
        else:
            matches = _resource_matches(requirement, registry)
            if not matches:
                candidate_targets = tuple(
                    sorted(
                        {
                            route.target_id
                            for route in registry.declared_routes
                            if route.target_id is not None
                            and required_capability_ids.issubset(
                                route.capability_ids
                            )
                            and any(
                                binding.target_id == route.target_id
                                for binding in registry.binding.inventory_bindings
                            )
                        }
                    )
                )
                blockers.extend(
                    CapabilityResolutionBlocker(
                        code="software_requirement_unsatisfied",
                        capability_id=requirement.capability_id,
                        requirement=(
                            f"{requirement.capability_id}"
                            f"{requirement.version_spec or ''}"
                        ),
                        target_id=target_id,
                    )
                    for target_id in (candidate_targets or (None,))
                )
            resource_facts.extend(matches)
    if blockers:
        return CapabilityRouteResolution(
            extension_facts=tuple(extension_facts),
            resource_facts=tuple(resource_facts),
            routes=(),
            blockers=tuple(blockers),
        )

    routes: list[RouteRef] = []
    for route in registry.route_refs:
        if not required_capability_ids.issubset(route.capability_ids):
            continue
        route_resources = [
            fact
            for requirement in entry.requirements
            if requirement.kind is CapabilityRequirementKind.RESOURCE
            for fact in _resource_matches(
                requirement,
                registry,
                target_id=route.target_id,
            )
        ]
        resource_requirements = tuple(
            requirement
            for requirement in entry.requirements
            if requirement.kind is CapabilityRequirementKind.RESOURCE
        )
        if resource_requirements and len(route_resources) < len(resource_requirements):
            continue
        same_target_ok = all(
            requirement.same_target_as is None
            or requirement.same_target_as in route.capability_ids
            for requirement in resource_requirements
        )
        if not same_target_ok:
            continue
        routes.append(route)
    if entry.requires_explicit_route and not routes:
        blockers.append(
            CapabilityResolutionBlocker(
                code="compatible_route_missing",
                capability_id=entry.contract.tool_name,
            )
        )
    return CapabilityRouteResolution(
        extension_facts=tuple(
            sorted(
                set(extension_facts),
                key=lambda fact: (fact.capability_id, fact.provider_component_id),
            )
        ),
        resource_facts=tuple(
            sorted(
                set(resource_facts),
                key=lambda fact: (fact.target_id, fact.capability_id),
            )
        ),
        routes=tuple(sorted(routes, key=lambda route: route.route_id)),
        blockers=tuple(blockers),
    )


__all__ = [
    "CapabilityRegistry",
    "CapabilityResolutionBlocker",
    "CapabilityRouteResolution",
    "ExtensionBundleRegistry",
    "resolve_tool_capabilities",
    "version_satisfies",
]
