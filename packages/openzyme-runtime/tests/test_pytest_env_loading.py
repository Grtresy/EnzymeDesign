import os
from pathlib import Path

from openzyme_runtime import load_env_files


def test_load_env_files_keeps_existing_environment(monkeypatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENZYME_LLM_MODEL=from-file\n", encoding="utf-8")

    monkeypatch.setenv("OPENZYME_LLM_MODEL", "from-env")
    load_env_files((str(env_path),))

    assert os.environ["OPENZYME_LLM_MODEL"] == "from-env"
