from __future__ import annotations

from pathlib import Path

from openzyme_host_api.evals import build_local_eval_runtime


def test_local_eval_runtime_uses_temp_sqlite_only(tmp_path) -> None:
    repo_demo_db = Path(".tmp/openzyme-demo.sqlite3")
    original_bytes = repo_demo_db.read_bytes() if repo_demo_db.exists() else None

    build_local_eval_runtime(tmp_path / "eval.sqlite3")

    if original_bytes is None:
        assert not repo_demo_db.exists()
    else:
        assert repo_demo_db.read_bytes() == original_bytes


def test_local_eval_runtime_is_repeatable_with_fresh_sqlite_paths(tmp_path) -> None:
    first = build_local_eval_runtime(tmp_path / "first.sqlite3")
    second = build_local_eval_runtime(tmp_path / "second.sqlite3")

    assert first.repositories.projects.get("proj_001") is not None
    assert second.repositories.projects.get("proj_001") is not None
