from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_engines import podman_sandbox
from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_runtime import FASTA_ZERO_RECORDS_VALIDATION_PROFILE


pytestmark = pytest.mark.podman


def test_registered_empty_fasta_requires_typed_zero_byte_contract(
    tmp_path: Path,
) -> None:
    server = podman_sandbox._ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        input_dir=tmp_path / "input",
        output_dir=tmp_path,
        artifacts={},
    )
    empty = tmp_path / "empty.fasta"
    empty.write_bytes(b"")
    metadata = {
        "format": "fasta",
        "validation_profile": FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
        "empty_result_reason": "no_candidates_after_motif_filter",
        "derivation_contract_id": "aox_motif_candidate_filter@1",
    }

    server._validate_registered_output(
        empty,
        relative_path="aox_hmm/AOX_candidates.fasta",
        kind=ArtifactKind.SEQUENCE,
        validation_profile=FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
        metadata=metadata,
    )

    with pytest.raises(ValueError, match="registered artifact is empty"):
        server._validate_registered_output(
            empty,
            relative_path="aox_hmm/AOX_candidates.fasta",
            kind=ArtifactKind.SEQUENCE,
            validation_profile=None,
            metadata={"format": "fasta"},
        )

    sentinel = tmp_path / "sentinel.fasta"
    sentinel.write_text(">EMPTY\nX\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be selected through validation_profile"):
        server._register(
            {
                "path": "/workspace/output/sentinel.fasta",
                "kind": "sequence",
                "format": "fasta",
                "metadata": {
                    **metadata,
                    "validation_profile": FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
                },
            }
        )

    with pytest.raises(ValueError, match="fasta_zero_records@1 artifact is invalid"):
        server._validate_registered_output(
            sentinel,
            relative_path="aox_hmm/AOX_candidates.fasta",
            kind=ArtifactKind.SEQUENCE,
            validation_profile=FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
            metadata=metadata,
        )


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
    stderr_text = Path(stderr.storage_uri).read_text(encoding="utf-8")
    assert (
        "artifacts.register only accepts files under /workspace/output" in stderr_text
        or "artifacts.register only accepts files under /openzyme/output" in stderr_text
    )


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
