from __future__ import annotations

from openzyme_kernel import OfflinePluginChangeRequest
from openzyme_kernel import PluginChangeKind
from openzyme_kernel import PluginContinuationObservation
from openzyme_kernel import PluginOperationObservation
from openzyme_kernel import PluginOwnedStateObservation
from openzyme_kernel import PluginSessionPinObservation
from openzyme_kernel import PluginStateDisposition
from openzyme_kernel import verify_offline_plugin_change

from composition_test_support import digest


def _request(
    *,
    change_kind: PluginChangeKind = PluginChangeKind.REMOVE,
    session_pins: tuple[PluginSessionPinObservation, ...] = (),
    continuations: tuple[PluginContinuationObservation, ...] = (),
    owned_state: tuple[PluginOwnedStateObservation, ...] = (),
    operations: tuple[PluginOperationObservation, ...] = (),
    deployment_quiescent: bool = True,
    migration_plan_digest: str | None = None,
) -> OfflinePluginChangeRequest:
    return OfflinePluginChangeRequest(
        change_id="plugin-change-1",
        change_kind=change_kind,
        plugin_id="test.plugin",
        current_manifest_digest=digest("manifest-v1"),
        proposed_manifest_digest=(
            digest("manifest-v2")
            if change_kind is PluginChangeKind.UPGRADE
            else None
        ),
        migration_plan_digest=migration_plan_digest,
        quiescence_receipt_digest=digest("quiescence"),
        deployment_quiescent=deployment_quiescent,
        session_pins=session_pins,
        continuations=continuations,
        owned_state=owned_state,
        operations=operations,
    )


def test_unused_plugin_removal_is_allowed_without_mutation() -> None:
    verification = verify_offline_plugin_change(_request())

    assert verification.allowed is True
    assert verification.blockers == ()
    assert verification.mutation_applied is False
    assert verification.fallback_performed is False


def test_non_terminal_session_pin_blocks_removal() -> None:
    verification = verify_offline_plugin_change(
        _request(
            session_pins=(
                PluginSessionPinObservation(
                    session_id="session-1",
                    pin_digest=digest("pin"),
                    terminal=False,
                ),
            )
        )
    )

    assert verification.allowed is False
    assert [item.code for item in verification.blockers] == [
        "non_terminal_session_pins_plugin"
    ]


def test_explicitly_migrated_or_terminal_session_does_not_block() -> None:
    verification = verify_offline_plugin_change(
        _request(
            session_pins=(
                PluginSessionPinObservation(
                    session_id="session-migrated",
                    pin_digest=digest("pin-migrated"),
                    terminal=False,
                    explicitly_migrated=True,
                ),
                PluginSessionPinObservation(
                    session_id="session-terminal",
                    pin_digest=digest("pin-terminal"),
                    terminal=True,
                ),
            )
        )
    )

    assert verification.allowed is True


def test_live_continuation_and_unsettled_effect_both_block_removal() -> None:
    verification = verify_offline_plugin_change(
        _request(
            continuations=(
                PluginContinuationObservation(
                    continuation_id="continuation-1",
                    session_id="session-1",
                    source_version=1,
                    terminal=False,
                ),
            ),
            operations=(
                PluginOperationObservation(
                    operation_id="operation-1",
                    source_version=2,
                    terminal=True,
                    effect_settled=False,
                ),
            ),
        )
    )

    assert verification.allowed is False
    assert {item.code for item in verification.blockers} == {
        "non_terminal_continuation_pins_plugin",
        "plugin_operation_unsettled",
    }


def test_non_empty_state_requires_removal_disposition_receipt() -> None:
    verification = verify_offline_plugin_change(
        _request(
            owned_state=(
                PluginOwnedStateObservation(
                    state_namespace="test_plugin",
                    row_count=3,
                    state_digest=digest("state"),
                    disposition=PluginStateDisposition.UNDECLARED,
                ),
            )
        )
    )

    assert verification.allowed is False
    assert verification.blockers[0].code == "plugin_state_disposition_missing"


def test_archived_state_with_receipt_allows_removal() -> None:
    verification = verify_offline_plugin_change(
        _request(
            owned_state=(
                PluginOwnedStateObservation(
                    state_namespace="test_plugin",
                    row_count=3,
                    state_digest=digest("state"),
                    disposition=PluginStateDisposition.ARCHIVE,
                    disposition_receipt_digest=digest("archive-receipt"),
                ),
            )
        )
    )

    assert verification.allowed is True


def test_upgrade_with_state_requires_migration_plan_and_valid_disposition() -> None:
    state = PluginOwnedStateObservation(
        state_namespace="test_plugin",
        row_count=3,
        state_digest=digest("state"),
        disposition=PluginStateDisposition.MIGRATE,
        disposition_receipt_digest=digest("migration-disposition"),
    )

    blocked = verify_offline_plugin_change(
        _request(change_kind=PluginChangeKind.UPGRADE, owned_state=(state,))
    )
    allowed = verify_offline_plugin_change(
        _request(
            change_kind=PluginChangeKind.UPGRADE,
            owned_state=(state,),
            migration_plan_digest=digest("migration-plan"),
        )
    )

    assert blocked.allowed is False
    assert blocked.blockers[0].code == "plugin_migration_plan_missing"
    assert allowed.allowed is True


def test_non_quiescent_deployment_blocks_every_plugin_change() -> None:
    verification = verify_offline_plugin_change(
        _request(deployment_quiescent=False)
    )

    assert verification.allowed is False
    assert verification.blockers[0].code == "deployment_not_quiescent"
