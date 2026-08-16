from __future__ import annotations

import inspect
import json
from pathlib import Path
import socket

import pytest

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_engines import podman_sandbox
from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_pipeline import artifacts as pipeline_artifacts
from openzyme_pipeline.client import ControlClient
from openzyme_pipeline.client import PipelineSdkError
from openzyme_runtime import ArtifactBoundaryError
from openzyme_runtime import FASTA_ZERO_RECORDS_VALIDATION_PROFILE


pytestmark = pytest.mark.podman


def test_host_supervised_pipeline_does_not_inherit_native_capsule_network() -> None:
    source = inspect.getsource(PodmanPipelineSandboxRunner.run_pipeline)

    assert '"--network=none"' in source
    assert "OPENZYME_AGENT_CAPSULE_DEPLOYMENT_NETWORK" not in source
    assert "/openzyme/control.sock" in source
    assert "OPENZYME_SANDBOX_MODE=s10" in source


def _send_raw_control_frame(socket_path: Path, payload: bytes) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(socket_path))
        client.sendall(payload)
        response = bytearray()
        while b"\n" not in response:
            response.extend(client.recv(64 * 1024))
    return dict(json.loads(bytes(response).split(b"\n", 1)[0]))


def test_compat_control_socket_frames_inline_and_sidecar_metadata_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sandbox"
    output_dir = root / "output"
    output_dir.mkdir(parents=True)
    (root / "input").mkdir()
    (root / "work").mkdir()
    (output_dir / "inline.csv").write_text("id\n1\n", encoding="utf-8")
    (output_dir / "sidecar.csv").write_text("id\n2\n", encoding="utf-8")
    server = podman_sandbox._ControlSocketServer(
        socket_path=root / "control.sock",
        input_dir=root / "input",
        output_dir=output_dir,
        artifacts={},
    )
    monkeypatch.setattr(
        pipeline_artifacts,
        "ARTIFACT_REGISTRATION_METADATA_WORK_ROOT",
        root / "work",
    )
    monkeypatch.setattr(
        pipeline_artifacts,
        "call",
        lambda method, params: ControlClient(str(root / "control.sock")).call(
            method,
            params,
        ),
    )
    server.start()
    try:
        inline_response = pipeline_artifacts.register(
            "/workspace/output/inline.csv",
            kind="result",
            format="csv",
            metadata={"padding": "x" * (128 * 1024)},
        )
        sidecar_response = pipeline_artifacts.register(
            "/workspace/output/sidecar.csv",
            kind="result",
            format="csv",
            metadata={"padding": "y" * (5 * 1024 * 1024)},
        )
    finally:
        server.stop()

    assert inline_response["schema_id"] == (
        "pipeline_provisional_registration_response@1"
    )
    assert sidecar_response["schema_id"] == (
        "pipeline_provisional_registration_response@1"
    )
    assert inline_response["canonical"] is False
    assert set(sidecar_response) == {
        "schema_id",
        "canonical",
        "artifact_id",
        "observed_content_digest",
        "metadata",
    }
    assert len(json.dumps(sidecar_response).encode("utf-8")) < 32 * 1024
    assert len(server.registered) == 2
    assert len(server.registered[0].metadata["padding"]) == 128 * 1024
    assert len(server.registered[1].metadata["padding"]) == 5 * 1024 * 1024
    sidecars = list(
        (root / "work" / ".openzyme" / "artifact-metadata").glob("*.json")
    )
    assert len(sidecars) == 1
    assert sidecars[0].stat().st_size > 4 * 1024 * 1024
    with pytest.raises(PipelineSdkError) as error:
        pipeline_artifacts.registered_artifact_ref(sidecar_response)
    assert error.value.error_code == "artifact_registration_projection_invalid"


def test_compat_register_many_max_success_projection_stays_bounded(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (tmp_path / "input").mkdir()
    server = podman_sandbox._ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        input_dir=tmp_path / "input",
        output_dir=output_dir,
        artifacts={},
    )
    items = []
    for index in range(128):
        relative_path = f"nested/result_{index:03d}.csv"
        target = output_dir / relative_path
        target.parent.mkdir(exist_ok=True)
        target.write_text("id\n1\n", encoding="utf-8")
        items.append(
            {
                "path": f"/workspace/output/{relative_path}",
                "kind": "result",
                "format": "csv",
                "metadata": {},
            }
        )

    response = server._handle(
        {
            "jsonrpc": "2.0",
            "id": "rpc_max_batch",
            "method": "artifacts.register_many",
            "params": {"items": items},
        }
    )

    assert "error" not in response
    results = response["result"]
    assert isinstance(results, list)
    assert len(results) == 128
    assert all(
        set(item) == {
            "schema_id",
            "canonical",
            "artifact_id",
            "observed_content_digest",
            "metadata",
        }
        for item in results
    )
    assert len(json.dumps(response, ensure_ascii=True).encode("utf-8")) < 4 * 1024 * 1024
    assert len(server.registered) == 128


def test_compat_control_socket_rejects_invalid_frames_before_effect_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sandbox"
    output_dir = root / "output"
    output_dir.mkdir(parents=True)
    (root / "input").mkdir()
    (output_dir / "result.csv").write_text("id\n1\n", encoding="utf-8")
    server = podman_sandbox._ControlSocketServer(
        socket_path=root / "control.sock",
        input_dir=root / "input",
        output_dir=output_dir,
        artifacts={},
    )
    monkeypatch.setattr(
        podman_sandbox,
        "_CONTROL_SOCKET_IO_TIMEOUT_SECONDS",
        0.05,
    )
    server.start()
    try:
        request = {
            "id": "missing-jsonrpc",
            "method": "artifacts.register",
            "params": {
                "path": "/workspace/output/result.csv",
                "kind": "result",
                "format": "csv",
            },
        }
        invalid = _send_raw_control_frame(
            root / "control.sock",
            json.dumps(request, sort_keys=True).encode("utf-8") + b"\n",
        )
        assert invalid["id"] == "missing-jsonrpc"
        assert dict(invalid["error"])["error_code"] == (
            "sandbox_transport_request_invalid"
        )
        assert server.registered == []

        non_finite = _send_raw_control_frame(
            root / "control.sock",
            (
                b'{"jsonrpc":"2.0","id":"non-finite","method":"artifacts.register",'
                b'"params":{"path":"/workspace/output/result.csv","kind":"result",'
                b'"format":"csv","probe":NaN}}\n'
            ),
        )
        assert non_finite["id"] is None
        assert dict(non_finite["error"])["error_code"] == (
            "sandbox_transport_request_invalid"
        )
        assert server.registered == []

        duplicate = _send_raw_control_frame(
            root / "control.sock",
            (
                b'{"jsonrpc":"2.0","id":"duplicate","method":"artifacts.register",'
                b'"params":{},"params":{}}\n'
            ),
        )
        assert duplicate["id"] is None
        assert dict(duplicate["error"])["error_code"] == (
            "sandbox_transport_request_invalid"
        )
        assert server.registered == []

        request["jsonrpc"] = "2.0"
        request["id"] = "x" * 257
        unsafe_id = _send_raw_control_frame(
            root / "control.sock",
            json.dumps(request, sort_keys=True).encode("utf-8") + b"\n",
        )
        assert unsafe_id["id"] is None
        assert dict(unsafe_id["error"])["error_code"] == (
            "sandbox_transport_request_invalid"
        )
        assert server.registered == []

        timed_out = _send_raw_control_frame(
            root / "control.sock",
            b'{"jsonrpc":"2.0"',
        )
        assert timed_out["id"] is None
        assert dict(timed_out["error"])["error_code"] == (
            "sandbox_transport_request_timeout"
        )
        assert server.registered == []

        valid = ControlClient(str(root / "control.sock")).call(
            "artifacts.register",
            {
                "path": "/workspace/output/result.csv",
                "kind": "result",
                "format": "csv",
            },
        )
    finally:
        server.stop()

    assert valid["schema_id"] == "pipeline_provisional_registration_response@1"
    assert len(server.registered) == 1


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

    with pytest.raises(ValueError, match="fasta_zero_records@1 artifact is invalid"):
        server._validate_registered_output(
            empty,
            relative_path="aox_hmm/AOX_candidates.fasta",
            kind=ArtifactKind.SEQUENCE,
            validation_profile=FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
            metadata={
                **metadata,
                "derivation_contract_id": f"{'a' * 256}@1",
            },
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

    with pytest.raises(
        ArtifactBoundaryError,
        match="artifact registration metadata contains Host-owned digest fields",
    ):
        server._register(
            {
                "path": "/workspace/output/empty.fasta",
                "kind": "sequence",
                "format": "fasta",
                "validation_profile": FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
                "metadata": {**metadata, "tree_digest": "x" * 1024},
            }
        )
    assert server.registered == []


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
