from openzyme_host_api.eval_support import product_path_has_quiescent_failure


def _workspace(*, pending_signals: int, runtime_state: str) -> dict[str, object]:
    return {
        "task_board": {"items": [{"task": {"status": "failed"}}]},
        "delegation": {
            "agents": [
                {
                    "agent": {"runtime_state": runtime_state},
                    "pending_signal_count": pending_signals,
                    "unread_inbox_count": 0,
                }
            ]
        },
    }


def test_live_e2e_polling_stops_on_quiescent_business_failure() -> None:
    assert product_path_has_quiescent_failure(
        _workspace(pending_signals=0, runtime_state="failed")
    )


def test_live_e2e_polling_waits_while_failure_recovery_is_pending() -> None:
    assert not product_path_has_quiescent_failure(
        _workspace(pending_signals=1, runtime_state="idle")
    )
    assert not product_path_has_quiescent_failure(
        _workspace(pending_signals=0, runtime_state="working")
    )
