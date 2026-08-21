from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import GitObjectFormat
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel import ProjectRepositoryBindingCommand
from openzyme_kernel import SessionRepositoryBindingPinCommand
from openzyme_kernel import WorkspaceGenerationTransitionCommand
from openzyme_kernel import WorkspaceIdentityKernelApplicationService
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _context(command_id: str) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=command_id,
        session_id="session-1",
        actor_id="operator-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="authority-1",
        authority_generation=2,
        authority_fence=3,
        expected_session_version=5,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"idempotency-{command_id}",
        correlation_id=f"correlation-{command_id}",
    )


def _binding(*, binding_id: str = "binding-1", version: int = 1):
    return ProjectRepositoryBinding.create(
        binding_id=binding_id,
        project_id="project-1",
        binding_version=version,
        repository_id="repository-1",
        internal_git_service_id="git-service-1",
        internal_git_endpoint="https://git.internal.example/repository-1",
        lfs_service_id="lfs-service-1",
        lfs_endpoint="https://lfs.internal.example/repository-1",
        upstream_identity="upstream-1",
        upstream_url="https://example.com/org/repository.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/main",
        default_base_commit="a" * 40,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/history",
        ),
        repository_policy_version="policy-1",
        repository_policy_digest=_digest("repository-policy"),
        created_at="2026-08-19T00:00:00+00:00",
        created_by="operator-1",
    )


def _store() -> InMemoryControlStore:
    authority = {
        "lease_id": "authority-1",
        "session_id": "session-1",
        "agent_member_id": "operator-1",
        "state": "active",
        "generation": 2,
        "fence": 3,
        "expires_at": "2026-08-20T00:00:00+00:00",
        "grants": [
            {
                "scope_id": "session-1",
                "operations": [
                    "repository.binding.register",
                    "repository.binding.pin",
                    "workspace.generation.transition",
                ],
            }
        ],
    }
    return InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=5,
                payload={"status": "active", "project_id": "project-1"},
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id="authority-1",
                state_version=1,
                payload=authority,
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="member-1",
                state_version=1,
                payload={
                    "session_id": "session-1",
                    "agent_id": "agent-1",
                    "status": "working",
                    "process_epoch": 1,
                },
            ),
        )
    )


def _service(store: InMemoryControlStore) -> WorkspaceIdentityKernelApplicationService:
    return WorkspaceIdentityKernelApplicationService(
        store=store,
        reader=store,
        clock=DeterministicClock(datetime(2026, 8, 19, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )


def _pin(binding: ProjectRepositoryBinding) -> SessionRepositoryBindingPin:
    return SessionRepositoryBindingPin(
        session_id="session-1",
        project_id="project-1",
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        resolved_base_commit=binding.default_base_commit,
        binding_canonical_digest=binding.canonical_digest,
        pinned_at="2026-08-19T00:00:01+00:00",
    )


def _generation(
    *,
    status: WorkspaceGenerationStatus,
    state_version: int,
    root: str | None = None,
    operation_id: str | None = None,
    receipt: str | None = None,
    retired_at: str | None = None,
) -> WorkspaceGeneration:
    return WorkspaceGeneration(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=1,
        state_version=state_version,
        status=status,
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
        created_at="2026-08-19T00:00:02+00:00",
        updated_at=f"2026-08-19T00:00:0{state_version}+00:00",
        root_identity_digest=root,
        transition_receipt_digest=receipt,
        controlled_operation_id=operation_id,
        retired_at=retired_at,
    )


def _seed_operation(store: InMemoryControlStore, operation_id: str, receipt: str) -> None:
    store.seed(
        KernelRecordSnapshot.create(
            entity_type="controlled_operation",
            entity_id=operation_id,
            state_version=3,
            payload={
                "operation_id": operation_id,
                "session_id": "session-1",
                "state": "settled",
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "terminal_receipt_digest": receipt,
            },
        )
    )


def test_repository_binding_registration_and_session_pin_are_exact_and_immutable() -> None:
    store = _store()
    service = _service(store)
    binding = _binding()

    registered = service.register_project_binding(
        ProjectRepositoryBindingCommand(
            context=_context("register-binding"), binding=binding
        )
    )
    pinned = service.pin_session_binding(
        SessionRepositoryBindingPinCommand(
            context=_context("pin-binding"), pin=_pin(binding)
        )
    )

    assert registered.mutation_applied is True
    assert pinned.mutation_applied is True
    pin = store.read(entity_type="session_repository_binding_pin", entity_id="session-1")
    assert pin is not None
    assert pin.payload["binding_canonical_digest"] == binding.canonical_digest

    replacement = SessionRepositoryBindingPin(
        **{
            **_pin(binding).to_dict(),
            "resolved_base_commit": "b" * 40,
        }
    )
    with pytest.raises(KernelContractError) as immutable:
        service.pin_session_binding(
            SessionRepositoryBindingPinCommand(
                context=_context("replace-pin"), pin=replacement
            )
        )
    assert immutable.value.code == "repository_pin_immutable"


def test_repository_binding_version_must_advance_without_rewriting_history() -> None:
    store = _store()
    service = _service(store)
    service.register_project_binding(
        ProjectRepositoryBindingCommand(
            context=_context("register-v1"), binding=_binding()
        )
    )

    with pytest.raises(KernelContractError) as version:
        service.register_project_binding(
            ProjectRepositoryBindingCommand(
                context=_context("register-v3"),
                binding=_binding(binding_id="binding-3", version=3),
            )
        )
    assert version.value.code == "repository_binding_version_non_monotonic"
    assert store.read(
        entity_type="project_repository_binding", entity_id="binding-3"
    ) is None


def test_workspace_ready_requires_settled_operation_and_materializes_runtime_binding() -> None:
    store = _store()
    service = _service(store)
    service.transition_workspace_generation(
        WorkspaceGenerationTransitionCommand(
            context=_context("reserve-workspace"),
            generation=_generation(
                status=WorkspaceGenerationStatus.RESERVED, state_version=1
            ),
            expected_record_version=None,
        )
    )
    service.transition_workspace_generation(
        WorkspaceGenerationTransitionCommand(
            context=_context("provision-workspace"),
            generation=_generation(
                status=WorkspaceGenerationStatus.PROVISIONING, state_version=2
            ),
            expected_record_version=1,
        )
    )
    receipt = _digest("workspace-provision-receipt")
    ready = _generation(
        status=WorkspaceGenerationStatus.READY,
        state_version=3,
        root=_digest("workspace-root"),
        operation_id="operation-provision-1",
        receipt=receipt,
    )
    with pytest.raises(KernelContractError) as unsettled:
        service.transition_workspace_generation(
            WorkspaceGenerationTransitionCommand(
                context=_context("ready-unsettled"),
                generation=ready,
                expected_record_version=2,
            )
        )
    assert unsettled.value.code == "workspace_transition_receipt_unsettled"
    _seed_operation(store, "operation-provision-1", receipt)

    result = service.transition_workspace_generation(
        WorkspaceGenerationTransitionCommand(
            context=_context("ready-workspace"),
            generation=ready,
            expected_record_version=2,
        )
    )

    runtime = store.read(
        entity_type="workspace_runtime_binding", entity_id="workspace-1"
    )
    assert result.mutation_applied is True
    assert runtime is not None
    assert runtime.payload["generation"] == 1
    assert runtime.payload["root_identity_digest"] == _digest("workspace-root")
    assert store.read(entity_type="task", entity_id="task-1") is None


def test_workspace_stale_transition_and_retiring_remove_runtime_affordance() -> None:
    store = _store()
    service = _service(store)
    service.transition_workspace_generation(
        WorkspaceGenerationTransitionCommand(
            context=_context("reserve"),
            generation=_generation(
                status=WorkspaceGenerationStatus.RESERVED, state_version=1
            ),
            expected_record_version=None,
        )
    )
    with pytest.raises(KernelContractError) as stale:
        service.transition_workspace_generation(
            WorkspaceGenerationTransitionCommand(
                context=_context("stale"),
                generation=_generation(
                    status=WorkspaceGenerationStatus.PROVISIONING, state_version=2
                ),
                expected_record_version=2,
            )
        )
    assert stale.value.code == "workspace_generation_record_stale"


def test_new_workspace_generation_requires_terminal_predecessor() -> None:
    store = _store()
    service = _service(store)
    service.transition_workspace_generation(
        WorkspaceGenerationTransitionCommand(
            context=_context("reserve-g1"),
            generation=_generation(
                status=WorkspaceGenerationStatus.RESERVED, state_version=1
            ),
            expected_record_version=None,
        )
    )
    generation_two = replace(
        _generation(status=WorkspaceGenerationStatus.RESERVED, state_version=1),
        generation=2,
    )
    with pytest.raises(KernelContractError) as active:
        service.transition_workspace_generation(
            WorkspaceGenerationTransitionCommand(
                context=_context("reserve-g2"),
                generation=generation_two,
                expected_record_version=1,
            )
        )
    assert active.value.code == "workspace_generation_non_monotonic"
