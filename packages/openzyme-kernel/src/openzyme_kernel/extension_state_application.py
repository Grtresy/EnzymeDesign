from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import ClockPort
from openzyme_extension_spi import AuthorityApplicationService
from openzyme_extension_spi import AuthorityCheckRequest
from openzyme_extension_spi import ExtensionMutationResult
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionTransactionCoordinatorPort
from openzyme_extension_spi import ExtensionTransactionParticipant

from .activation import ActivatedDistributionComposition
from .errors import KernelContractError
from .extension_mount import MountedExtensionSurfaces
from .session_composition import SessionCompositionGuard
from .session_composition import SessionCompositionRepository
from .session_composition import SessionCompositionSurface


@dataclass(frozen=True, slots=True)
class _ParticipantBinding:
    owner_plugin_id: str
    participant: ExtensionTransactionParticipant


class ExtensionStateKernelApplicationService:
    """Admit one exact Plugin mutation before delegating Store mechanics.

    Plugins receive neither a Core repository aggregate nor a database handle. The
    selected participant runs only after Session composition, bundle/binding identity,
    Plugin ownership and the current authority generation/fence have all been checked.
    """

    authority_operation = "extension.state.mutate"

    def __init__(
        self,
        *,
        composition: ActivatedDistributionComposition,
        mounted: MountedExtensionSurfaces,
        session_repository: SessionCompositionRepository,
        session_guard: SessionCompositionGuard,
        authority: AuthorityApplicationService,
        coordinator: ExtensionTransactionCoordinatorPort,
        clock: ClockPort,
    ) -> None:
        self._composition = composition
        self._mounted = mounted
        self._session_repository = session_repository
        self._session_guard = session_guard
        self._authority = authority
        self._coordinator = coordinator
        self._clock = clock
        owners = {
            declaration.contribution_id: manifest.identity.component_id
            for manifest in composition.plugins.contributing_manifests
            for declaration in manifest.transaction_participants
        }
        runtimes = dict(mounted.transaction_participants)
        if set(owners) != set(runtimes):
            raise KernelContractError(
                "extension_participant_mount_drift",
                "mounted transaction participants differ from the activated catalog",
                details={
                    "declared": sorted(owners),
                    "mounted": sorted(runtimes),
                },
            )
        self._participants = {
            participant_id: _ParticipantBinding(
                owner_plugin_id=owner,
                participant=runtimes[participant_id],
            )
            for participant_id, owner in owners.items()
        }

    def execute(self, command: ExtensionStateCommand) -> ExtensionMutationResult:
        context = command.context
        binding = self._participants.get(command.participant_id)
        if binding is None:
            raise KernelContractError(
                "extension_participant_not_activated",
                "extension mutation names an inactive transaction participant",
                details={"participant_id": command.participant_id},
            )
        if context.owner_plugin_id != binding.owner_plugin_id:
            raise KernelContractError(
                "extension_participant_owner_mismatch",
                "extension mutation crossed its activated Plugin owner",
                details={
                    "participant_id": command.participant_id,
                    "expected_owner": binding.owner_plugin_id,
                    "observed_owner": context.owner_plugin_id,
                },
            )
        if command.namespace != binding.participant.state_namespace:
            raise KernelContractError(
                "extension_participant_namespace_mismatch",
                "extension mutation crossed its activated state namespace",
                details={
                    "participant_id": command.participant_id,
                    "expected_namespace": binding.participant.state_namespace,
                    "observed_namespace": command.namespace,
                },
            )
        pin = self._session_repository.get_pin(context.session_id)
        capability_binding = self._session_repository.latest_capability_binding(
            context.session_id
        )
        self._session_guard.require(
            session_id=context.session_id,
            surface=SessionCompositionSurface.TOOL_INVOCATION,
            pin=pin,
            capability_binding=capability_binding,
        )
        if (
            pin is None
            or capability_binding is None
            or context.extension_bundle_digest
            != pin.release_identity.extension_bundle_digest
            or context.extension_bundle_digest
            != self._composition.plugins.extension_bundle_digest
            or context.capability_binding_digest != capability_binding.binding_digest
        ):
            raise KernelContractError(
                "extension_command_composition_stale",
                "extension mutation context differs from the exact Session pin",
                details={
                    "session_id": context.session_id,
                    "owner_plugin_id": context.owner_plugin_id,
                },
            )
        decision = self._authority.authorize(
            AuthorityCheckRequest(
                context=context.to_query_context(),
                operation=self.authority_operation,
                scope_id=context.session_id,
                expected_generation=context.authority_generation,
                expected_fence=context.authority_fence,
            )
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "extension_mutation_authority_denied",
                "extension mutation authority was denied",
                details={
                    "participant_id": command.participant_id,
                    "owner_plugin_id": context.owner_plugin_id,
                    "generation": context.authority_generation,
                    "fence": context.authority_fence,
                },
            )
        return self._coordinator.execute(
            command=command,
            participant=binding.participant,
            timestamp=self._clock.now_iso(),
        )


__all__ = ["ExtensionStateKernelApplicationService"]
