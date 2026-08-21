from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import KernelRecordSnapshot
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import TaskEvidenceApplicationCommand
from openzyme_extension_spi import TaskEvidenceCommandKind
from openzyme_extension_spi import TaskEvidenceValidation
from openzyme_kernel import FinishValidatorBinding
from openzyme_kernel import FinishValidatorRegistry
from openzyme_kernel import KernelContractError
from openzyme_kernel import TaskEvidenceKernelApplicationService

from test_controlled_operation_application import _Clock
from test_controlled_operation_application import _Ids
from test_controlled_operation_application import _Store
from test_controlled_operation_application import _digest


class _Validator:
    validator_id = "openzyme.science.finish"

    def validate(self, context, task, evidence_refs):  # noqa: ANN001
        accepted = len(evidence_refs) == 1
        return TaskEvidenceValidation(
            accepted=accepted,
            validator_ids=(self.validator_id,),
            rejection_codes=() if accepted else ("science_evidence_missing",),
            validation_digest=_digest(f"validation:{accepted}"),
        )


def _store() -> _Store:
    store = _Store()
    store.records[("task", "task-1")] = KernelRecordSnapshot.create(
        entity_type="task",
        entity_id="task-1",
        state_version=2,
        payload={
            "session_id": "session-1",
            "owner_actor_id": "agent-1",
            "status": "in_progress",
            "finish_validator_ids": ["openzyme.science.finish"],
        },
    )
    store.records[("agent_authority_lease", "lease-1")] = KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id="lease-1",
        state_version=1,
        payload={
            "session_id": "session-1",
            "agent_member_id": "agent-1",
            "state": "active",
            "generation": 3,
            "fence": 8,
            "expires_at": "2026-08-20T11:00:00+00:00",
            "grants": [
                {
                    "scope_id": "task-1",
                    "operations": ["task.evidence.register"],
                }
            ],
        },
    )
    return store


def _context(*, phase: str) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=f"command-{phase}",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.science",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=4,
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"evidence-{phase}",
        correlation_id="correlation-1",
    )


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        evidence_id="evidence-1",
        evidence_kind=EvidenceKind.EXTENSION,
        contract_id="science-closure-1",
        owner_component_id="openzyme.science",
        project_id="project-1",
        session_id="session-1",
        task_id="task-1",
        subject_ref="closure-1",
        subject_digest=_digest("closure-1"),
        attributes={},
    )


def _service(store: _Store) -> TaskEvidenceKernelApplicationService:
    return TaskEvidenceKernelApplicationService(
        store=store,
        reader=store,
        clock=_Clock(),
        ids=_Ids(),
        finish_validators=FinishValidatorRegistry(
            (FinishValidatorBinding("openzyme.science", _Validator()),)
        ),
    )


def test_register_then_read_only_validate_keeps_task_non_terminal() -> None:
    store = _store()
    service = _service(store)
    registered = service.execute(
        TaskEvidenceApplicationCommand(
            context=_context(phase="register"),
            operation=TaskEvidenceCommandKind.REGISTER,
            task_id="task-1",
            evidence_ref=_evidence(),
            expected_task_version=2,
        )
    )
    validated = service.execute(
        TaskEvidenceApplicationCommand(
            context=_context(phase="validate"),
            operation=TaskEvidenceCommandKind.VALIDATE,
            task_id="task-1",
            evidence_ref=_evidence(),
            expected_task_version=2,
        )
    )

    assert registered.mutation_applied is True
    assert registered.result["task_transition_performed"] is False
    assert validated.mutation_applied is False
    assert validated.result["accepted"] is True
    assert validated.result["task_transition_performed"] is False
    assert store.read(entity_type="task", entity_id="task-1").payload["status"] == "in_progress"


def test_unregistered_or_content_drifted_evidence_fails_closed() -> None:
    store = _store()
    service = _service(store)
    with pytest.raises(KernelContractError, match="absent") as missing:
        service.validate(_context(phase="query").to_query_context(), "task-1", (_evidence(),))
    assert missing.value.code == "task_evidence_unregistered"

    service.execute(
        TaskEvidenceApplicationCommand(
            context=_context(phase="register"),
            operation=TaskEvidenceCommandKind.REGISTER,
            task_id="task-1",
            evidence_ref=_evidence(),
            expected_task_version=2,
        )
    )
    drifted = replace(_evidence(), subject_digest=_digest("other-closure"))
    with pytest.raises(KernelContractError, match="differs"):
        service.validate(
            _context(phase="query").to_query_context(),
            "task-1",
            (drifted,),
        )
