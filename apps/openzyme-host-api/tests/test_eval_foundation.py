from __future__ import annotations

from openzyme_host_api.evals import build_local_eval_runtime


def test_local_eval_runtime_is_repeatable_without_sqlite_state() -> None:
    first = build_local_eval_runtime()
    second = build_local_eval_runtime()

    assert first.execution_adapter is not second.execution_adapter
    assert first.research_adapter is not second.research_adapter
    assert first.model_factory is not second.model_factory
