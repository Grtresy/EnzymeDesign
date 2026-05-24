from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_engines import PodmanPipelineSandboxRunner


pytestmark = pytest.mark.podman


def test_podman_pipeline_runs_container_and_registers_output(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("authorized input\n", encoding="utf-8")
    artifact = SessionArtifactRecord(
        artifact_id="art_input",
        session_id="sess_001",
        task_id="task_001",
        lane_id=None,
        invocation_id=None,
        run_id=None,
        kind=ArtifactKind.RESULT,
        storage_uri=str(source),
        relative_path="input.txt",
        title="input.txt",
        description=None,
        metadata={"format": "txt"},
        created_at="2026-05-01T00:00:00+00:00",
    )
    runner = PodmanPipelineSandboxRunner(workspace_root=tmp_path / "runs", timeout_seconds=30)

    outcome = runner.run_pipeline(
        session_id="sess_001",
        invocation_id="inv_podman_smoke",
        inputs=(artifact,),
        code=(
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "record = artifacts.get('art_input')\n"
            "assert record['path'].startswith('/openzyme/input/')\n"
            "assert 'storage_uri' not in record\n"
            "data = Path(record['path']).read_text(encoding='utf-8')\n"
            "Path('/openzyme/output/result.txt').write_text(data.upper(), encoding='utf-8')\n"
            "artifacts.register('/openzyme/output/result.txt', kind='result', format='txt')\n"
        ),
    )

    assert outcome.status is RunStatus.SUCCEEDED
    result_artifact = next(artifact for artifact in outcome.artifacts if artifact.relative_path == "result.txt")
    assert Path(result_artifact.storage_uri).read_text(encoding="utf-8") == "AUTHORIZED INPUT\n"


def test_podman_pipeline_rejects_output_escape(tmp_path: Path) -> None:
    runner = PodmanPipelineSandboxRunner(workspace_root=tmp_path / "runs", timeout_seconds=30)

    outcome = runner.run_pipeline(
        session_id="sess_001",
        invocation_id="inv_podman_escape",
        code=(
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "Path('/openzyme/work/bad.txt').write_text('bad', encoding='utf-8')\n"
            "artifacts.register('/openzyme/work/bad.txt', kind='result')\n"
        ),
    )

    assert outcome.status is RunStatus.FAILED
    stderr = next(artifact for artifact in outcome.artifacts if artifact.relative_path == "logs/stderr.log")
    assert "artifacts.register only accepts files under /openzyme/output" in Path(stderr.storage_uri).read_text(encoding="utf-8")


def test_podman_pipeline_validates_registered_csv_columns(tmp_path: Path) -> None:
    runner = PodmanPipelineSandboxRunner(workspace_root=tmp_path / "runs", timeout_seconds=30)

    outcome = runner.run_pipeline(
        session_id="sess_001",
        invocation_id="inv_csv",
        code=(
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "Path('/openzyme/output/nodes.csv').write_text('node_id,label\\nn1,AOX\\n', encoding='utf-8')\n"
            "artifacts.register(\n"
            "    '/openzyme/output/nodes.csv',\n"
            "    kind='result',\n"
            "    format='csv',\n"
            "    metadata={'required_columns': ['node_id', 'label', 'score']},\n"
            ")\n"
        ),
    )

    assert outcome.status is RunStatus.FAILED
    stderr = next(artifact for artifact in outcome.artifacts if artifact.relative_path == "logs/stderr.log")
    assert "missing required columns" in Path(stderr.storage_uri).read_text(encoding="utf-8")
