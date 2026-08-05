from __future__ import annotations

import signal

import pytest

from .fault_process import evaluate_retirement_semantics


@pytest.mark.parametrize(
    ("raw_exit_code", "expected_signal"),
    ((0, None), (23, None), (-signal.SIGINT, signal.SIGINT), (-signal.SIGKILL, signal.SIGKILL)),
)
def test_retirement_semantics_are_deterministic_and_signal_preserving(
    raw_exit_code: int,
    expected_signal: int | None,
) -> None:
    semantics = evaluate_retirement_semantics(
        identity_exact=True,
        raw_exit_code=raw_exit_code,
        final_group_member_count=0,
    )

    assert semantics.retirement_proven is True
    assert semantics.quarantine_required is False
    assert semantics.raw_signal == expected_signal
    assert semantics.external_outcome == "unknown"
    assert semantics.cutover_eligible is False


@pytest.mark.parametrize(
    ("identity_exact", "raw_exit_code", "member_count", "forced"),
    (
        (False, -signal.SIGTERM, 0, False),
        (True, None, 0, False),
        (True, -signal.SIGKILL, 1, False),
        (True, -signal.SIGTERM, 0, True),
    ),
)
def test_unproven_retirement_always_requires_quarantine(
    identity_exact: bool,
    raw_exit_code: int | None,
    member_count: int,
    forced: bool,
) -> None:
    semantics = evaluate_retirement_semantics(
        identity_exact=identity_exact,
        raw_exit_code=raw_exit_code,
        final_group_member_count=member_count,
        force_retirement_unproven=forced,
    )

    assert semantics.retirement_proven is False
    assert semantics.quarantine_required is True
    assert semantics.external_outcome == "unknown"
    assert semantics.cutover_eligible is False


def test_retirement_semantics_reject_impossible_member_count() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        evaluate_retirement_semantics(
            identity_exact=True,
            raw_exit_code=0,
            final_group_member_count=-1,
        )
