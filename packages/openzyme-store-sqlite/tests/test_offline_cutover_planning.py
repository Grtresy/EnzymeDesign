from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import CutoverInventoryKind
from openzyme_store_sqlite import CutoverInventoryObservation
from openzyme_store_sqlite import CutoverRecoveryAction
from openzyme_store_sqlite import LegacySessionCutoverObservation
from openzyme_store_sqlite import OfflineBackupKind
from openzyme_store_sqlite import OfflineBackupObservation
from openzyme_store_sqlite import QuiescenceObservation
from openzyme_store_sqlite import QuiescenceRequirement
from openzyme_store_sqlite import QuiescenceSurfaceKind
from openzyme_store_sqlite import RecoveryBoundary
from openzyme_store_sqlite import SessionCutoverDispositionKind
from openzyme_store_sqlite import build_offline_cutover_dry_run
from openzyme_store_sqlite import classify_legacy_session
from openzyme_store_sqlite import select_cutover_recovery_action
from openzyme_store_sqlite import verify_offline_backup_set
from openzyme_store_sqlite import verify_offline_quiescence


def _digest(label: str) -> str:
    return canonical_sha256_digest({"identity": label})


def _inventory() -> tuple[CutoverInventoryObservation, ...]:
    return tuple(
        CutoverInventoryObservation(
            inventory_kind=kind,
            identity_digest=_digest(f"inventory-{kind.value}"),
            item_count=0,
            expected_disposition_digest=_digest(f"disposition-{kind.value}"),
        )
        for kind in CutoverInventoryKind
    )


def test_dry_run_closes_every_inventory_kind_without_mutation() -> None:
    proof = build_offline_cutover_dry_run(
        source_release_digest=_digest("source"),
        target_release_digest=_digest("target"),
        observations=_inventory(),
    )

    assert proof.ready is True
    assert len(proof.observations) == len(CutoverInventoryKind)
    assert proof.mutation_applied is False
    assert proof.external_effect_performed is False
    assert proof.proof_digest == canonical_sha256_digest(proof.to_dict())

    with pytest.raises(ValueError, match="exact closed inventory-kind set"):
        build_offline_cutover_dry_run(
            source_release_digest=_digest("source"),
            target_release_digest=_digest("target"),
            observations=_inventory()[:-1],
        )


def test_dry_run_reports_unresolved_or_unsettled_facts_without_hiding_them() -> None:
    observations = list(_inventory())
    session_index = next(
        index
        for index, item in enumerate(observations)
        if item.inventory_kind is CutoverInventoryKind.SESSION
    )
    observations[session_index] = replace(
        observations[session_index],
        item_count=1,
        unresolved_item_count=1,
    )
    effect_index = next(
        index
        for index, item in enumerate(observations)
        if item.inventory_kind is CutoverInventoryKind.UNSETTLED_EFFECT
    )
    observations[effect_index] = replace(observations[effect_index], item_count=1)

    proof = build_offline_cutover_dry_run(
        source_release_digest=_digest("source"),
        target_release_digest=_digest("target"),
        observations=tuple(observations),
    )

    assert proof.ready is False
    assert proof.blocker_codes == (
        "unresolved_session",
        "unsettled_effect_present",
    )


def test_quiescence_requires_every_exact_surface_and_empty_effect_set() -> None:
    required = tuple(
        QuiescenceRequirement(owner_id=f"owner-{kind.value}", surface_kind=kind)
        for kind in QuiescenceSurfaceKind
    )
    observed = tuple(
        QuiescenceObservation(
            owner_id=item.owner_id,
            surface_kind=item.surface_kind,
            stopped_or_isolated=True,
            observation_digest=_digest(f"stopped-{item.owner_id}"),
            writer_generation=(
                2
                if item.surface_kind
                in {
                    QuiescenceSurfaceKind.SQLITE_WRITER,
                    QuiescenceSurfaceKind.GIT_WRITER,
                }
                else None
            ),
            writer_fence=(
                7
                if item.surface_kind
                in {
                    QuiescenceSurfaceKind.SQLITE_WRITER,
                    QuiescenceSurfaceKind.GIT_WRITER,
                }
                else None
            ),
        )
        for item in required
    )
    receipt = verify_offline_quiescence(
        required=required,
        observed=observed,
        deployment_inventory_digest=_digest("deployment-inventory"),
        unsettled_effect_identities=(),
        unknown_effect_count=0,
        verified_at="2026-08-20T03:00:00Z",
    )

    assert len(receipt.observations) == len(QuiescenceSurfaceKind)
    assert receipt.mutation_applied is False

    with pytest.raises(ValueError, match="exact required surface set"):
        verify_offline_quiescence(
            required=required,
            observed=observed[:-1],
            deployment_inventory_digest=_digest("deployment-inventory"),
            unsettled_effect_identities=(),
            unknown_effect_count=0,
            verified_at="2026-08-20T03:00:00Z",
        )
    with pytest.raises(ValueError, match="empty unsettled-effect set"):
        verify_offline_quiescence(
            required=required,
            observed=observed,
            deployment_inventory_digest=_digest("deployment-inventory"),
            unsettled_effect_identities=("operation-unknown",),
            unknown_effect_count=1,
            verified_at="2026-08-20T03:00:00Z",
        )


def test_backup_set_requires_exact_independent_readback_and_one_way_boundary() -> None:
    observations = tuple(
        OfflineBackupObservation(
            backup_id=f"backup-{kind.value}",
            backup_kind=kind,
            source_identity_digest=_digest(f"source-id-{kind.value}"),
            source_content_digest=_digest(f"content-{kind.value}"),
            source_size_bytes=100,
            backup_identity_digest=_digest(f"backup-id-{kind.value}"),
            backup_content_digest=_digest(f"content-{kind.value}"),
            backup_size_bytes=100,
            independent_readback_digest=_digest(f"content-{kind.value}"),
            verifier_id="independent-backup-verifier",
            recoverable=True,
            verified_at="2026-08-20T03:00:00Z",
        )
        for kind in OfflineBackupKind
    )
    proof = verify_offline_backup_set(observations)

    assert proof.pre_activation_boundary is (
        RecoveryBoundary.PRE_ACTIVATION_EXACT_ROLLBACK
    )
    assert proof.post_activation_boundary is RecoveryBoundary.POST_ACTIVATION_FORWARD_ONLY
    assert len(proof.receipts) == 3

    with pytest.raises(ValueError, match="independent verification"):
        verify_offline_backup_set(
            (
                replace(
                    observations[0],
                    independent_readback_digest=_digest("tampered"),
                ),
                *observations[1:],
            )
        )


def test_session_classification_never_fabricates_a_pin_for_blocked_state() -> None:
    base = LegacySessionCutoverObservation(
        session_id="session-1",
        terminal=False,
        source_contract_id="file_workspace_public@1",
        core_rows_exact=True,
        extension_rows_exact=True,
        workspace_backend_exact=True,
        authority_mapping_exact=True,
        inventory_binding_exact=True,
        continuations_settled=True,
        controlled_operations_settled=True,
        target_composition_pin_digest=_digest("pin"),
        target_capability_binding_digest=_digest("binding"),
        evidence_digest=_digest("evidence"),
    )

    migrated = classify_legacy_session(base)
    historical = classify_legacy_session(replace(base, terminal=True))
    blocked = classify_legacy_session(replace(base, authority_mapping_exact=False))

    assert migrated.disposition is SessionCutoverDispositionKind.MIGRATED_AT2
    assert historical.disposition is (
        SessionCutoverDispositionKind.CLOSED_HISTORICAL_AT1
    )
    assert historical.composition_pin_digest is None
    assert blocked.disposition is SessionCutoverDispositionKind.BLOCKED
    assert blocked.composition_pin_digest is None
    assert blocked.capability_binding_digest is None


def test_recovery_never_downgrades_after_activation_or_canonical_mutation() -> None:
    assert select_cutover_recovery_action(
        activation_epoch_persisted=False,
        post_freeze_canonical_mutation_count=0,
    ) is CutoverRecoveryAction.RESTORE_EXACT_PRE_ACTIVATION_BACKUPS
    assert select_cutover_recovery_action(
        activation_epoch_persisted=True,
        post_freeze_canonical_mutation_count=0,
    ) is CutoverRecoveryAction.QUIESCE_AND_FORWARD_REPAIR
    assert select_cutover_recovery_action(
        activation_epoch_persisted=False,
        post_freeze_canonical_mutation_count=1,
    ) is CutoverRecoveryAction.QUIESCE_AND_FORWARD_REPAIR
